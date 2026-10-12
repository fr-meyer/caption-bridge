"""WebSocket handler — bridges SessionManager events to the browser."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

import orjson
from fastapi import WebSocket, WebSocketDisconnect

from app import terminology
from app.config import settings
from app.glossary import parse_glossary
from app.journal import SessionJournal, discard_recovery, retry_recovery
from app.languages import is_valid_target_language
from app.profiles import resolve_profile
from app.state import RecoveryNotice, SessionManager
from app.translation_models import (
    validate_reasoning_effort,
    validate_translation_model,
)
from app.tts import VOICE_MAP

if TYPE_CHECKING:
    from app.readiness import ReadinessPoller

logger = logging.getLogger(__name__)

_OUTBOUND_QUEUE_WARN_DEPTH = 50
_OUTBOUND_QUEUE_CRITICAL_DEPTH = 200
_OUTBOUND_SEND_LAG_WARN_SECS = 2.0
_OBS_LOG_REPEAT_INTERVAL_SECS = 30.0
_COALESCIBLE_EVENT_TYPES = frozenset({"source_partial", "elapsed", "readiness"})
_CRITICAL_EVENT_TYPES = frozenset(
    {
        "caption",
        "terminology_updated",
        "terminology_error",
        "error",
        "export_result",
        "provider_temporarily_unavailable",
        "reconnect_attempt",
        "reconnect_cancelled",
        "recovered",
        "session_snapshot",
        "status",
        "asr_state",
        "finish_input_complete",
        "connection_lifecycle",
        "translation_model_changed",
        "tts_error",
        "tts_skipped",
        "tts_caught_up",
        "tts_queue",
    }
)



@dataclass
class _OutboundObsState:
    """Per-connection outbound queue / send-lag observability (throttled logging)."""

    depth_band: str = "ok"
    last_depth_log_mono: float = field(default=0.0)
    lag_above_warn: bool = False
    last_lag_log_mono: float = field(default=0.0)


@dataclass
class _WsMetrics:
    depth_warn_crossings: int = 0
    depth_critical_crossings: int = 0
    depth_recovery_crossings: int = 0
    lag_warn_crossings: int = 0
    lag_recovery_crossings: int = 0
    current_depth: int = 0
    peak_depth: int = 0
    last_lag_secs: float = 0.0
    dropped_events: int = 0
    coalesced_events: int = 0
    critical_drops: int = 0
    connections_admitted: int = 0
    connections_rejected: int = 0
    connections_closed: int = 0


_ws_metrics = _WsMetrics()


def _is_expected_websocket_disconnect(exc: RuntimeError) -> bool:
    """Recognize Starlette's disconnect signal for a superseded socket."""
    return str(exc).startswith("WebSocket is not connected.")


def get_ws_metrics() -> dict[str, Any]:
    return asdict(_ws_metrics)


def _maybe_log_outbound_depth(
    obs: _OutboundObsState, depth: int, event_type: Any
) -> None:
    """Log on band transitions, periodically while degraded, or on recovery to ok."""
    _ws_metrics.current_depth = depth
    _ws_metrics.peak_depth = max(_ws_metrics.peak_depth, depth)

    if depth >= _OUTBOUND_QUEUE_CRITICAL_DEPTH:
        band = "critical"
    elif depth >= _OUTBOUND_QUEUE_WARN_DEPTH:
        band = "warn"
    else:
        band = "ok"

    now = time.monotonic()
    if band == "ok":
        if obs.depth_band != "ok":
            logger.info(
                "Outbound queue recovered: depth=%s (was %s)",
                depth,
                obs.depth_band,
            )
            obs.depth_band = "ok"
            obs.last_depth_log_mono = now
            _ws_metrics.depth_recovery_crossings += 1
        return

    transition = band != obs.depth_band
    periodic = (now - obs.last_depth_log_mono) >= _OBS_LOG_REPEAT_INTERVAL_SECS
    if transition or periodic:
        obs.depth_band = band
        obs.last_depth_log_mono = now
        if band == "critical":
            logger.error(
                "Outbound queue critical depth: depth=%s event_type=%s — possible memory growth risk",
                depth,
                event_type,
            )
        else:
            logger.warning("Outbound queue pressure: depth=%s event_type=%s", depth, event_type)
        if transition:
            if band == "critical":
                _ws_metrics.depth_critical_crossings += 1
            elif band == "warn":
                _ws_metrics.depth_warn_crossings += 1


def _is_critical_event(event: dict[str, Any]) -> bool:
    event_type = event.get("type")
    return event_type in _CRITICAL_EVENT_TYPES or (
        event_type == "tts_audio" and event.get("is_last") is True
    )


def _enqueue_outbound(
    queue: asyncio.Queue[tuple[dict[str, Any], float]],
    event: dict[str, Any],
    obs: _OutboundObsState,
) -> bool:
    """Enqueue without blocking while preserving critical state transitions."""
    enqueue_time = time.monotonic()
    event_type = event.get("type")
    dropped_before = _ws_metrics.dropped_events
    coalesced_before = _ws_metrics.coalesced_events
    critical_before = _ws_metrics.critical_drops

    if not queue.full():
        queue.put_nowait((event, enqueue_time))
        depth = queue.qsize()
        _ws_metrics.current_depth = depth
        _maybe_log_outbound_depth(obs, depth, event_type)
        if manager is not None:
            manager.record_websocket_queue(depth)
        return True

    items: list[tuple[dict[str, Any], float]] = []
    while not queue.empty():
        items.append(queue.get_nowait())
        queue.task_done()

    accepted = False
    drop_index: int | None = None
    if event_type in _COALESCIBLE_EVENT_TYPES:
        matches = [
            index
            for index, (queued, _queued_at) in enumerate(items)
            if queued.get("type") == event_type
        ]
        if matches:
            drop_index = matches[-1]
            _ws_metrics.coalesced_events += 1
    elif _is_critical_event(event):
        drop_index = next(
            (
                index
                for index, (queued, _queued_at) in enumerate(items)
                if not _is_critical_event(queued)
            ),
            0,
        )
        if _is_critical_event(items[drop_index][0]):
            _ws_metrics.critical_drops += 1

    if drop_index is not None:
        items.pop(drop_index)
        items.append((event, enqueue_time))
        accepted = True
    else:
        _ws_metrics.dropped_events += 1

    for queued_item in items:
        queue.put_nowait(queued_item)

    if accepted:
        _ws_metrics.dropped_events += 1
    if _ws_metrics.dropped_events == 1 or _ws_metrics.dropped_events % 100 == 0:
        logger.warning(
            "Outbound queue drops: total=%s event_type=%s max_depth=%s",
            _ws_metrics.dropped_events,
            event_type,
            queue.maxsize,
        )

    depth = queue.qsize()
    _ws_metrics.current_depth = depth
    _maybe_log_outbound_depth(obs, depth, event_type)
    if manager is not None:
        manager.record_websocket_queue(
            depth,
            dropped=_ws_metrics.dropped_events - dropped_before,
            coalesced=_ws_metrics.coalesced_events - coalesced_before,
            critical_drops=_ws_metrics.critical_drops - critical_before,
        )
    return accepted



# Module-level references set by main.py at startup
manager: SessionManager | None = None
start_pipeline: Callable[[], Any] | None = None
stop_pipeline: Callable[[], Any] | None = None
finish_input: Callable[[], Any] | None = None
poller: ReadinessPoller | None = None

@dataclass(eq=False)
class _ClientConnection:
    websocket: WebSocket
    connection_id: str
    closed: bool = False
    close_reason: str = "transport_closed"


_active_connection: _ClientConnection | None = None
_connection_counter: int = 0
OWNER_CONFLICT_CODE = 4409
OWNER_CONFLICT_REASON = "owner_active"
_LIFECYCLE_STATES = frozenset({"admitted", "rejected", "closed"})
_LIFECYCLE_REASONS = frozenset({
    "owner_admitted", "owner_active", "transport_closed", "writer_failed",
    "handler_failed", "cancelled", "ownership_lost",
})


def _lifecycle(connection: _ClientConnection, state: str, reason: str) -> dict[str, str]:
    """Only generated connection IDs and fixed enums reach lifecycle telemetry."""
    if state not in _LIFECYCLE_STATES or reason not in _LIFECYCLE_REASONS:
        raise ValueError("invalid connection lifecycle")
    data = {"connection_id": connection.connection_id, "state": state, "reason": reason}
    logger.info("WebSocket lifecycle: connection_id=%s state=%s reason=%s",
                connection.connection_id, state, reason)
    return data


def _owns_connection(connection: _ClientConnection) -> bool:
    return _active_connection is connection and not connection.closed


async def websocket_endpoint(websocket: WebSocket) -> None:
    """Main WebSocket handler at /ws."""
    global _active_connection, _connection_counter  # noqa: PLW0603

    assert manager is not None, "SessionManager not wired"

    await websocket.accept()

    _connection_counter += 1
    connection = _ClientConnection(websocket, f"conn-{_connection_counter:06d}")
    # Claim synchronously: there is no await between check and reservation.
    # Attached owners are protected in idle as well as during active capture.
    if _active_connection is not None:
        _ws_metrics.connections_rejected += 1
        lifecycle = _lifecycle(connection, "rejected", OWNER_CONFLICT_REASON)
        try:
            await websocket.send_bytes(orjson.dumps({"type": "connection_lifecycle", **lifecycle}))
        except Exception:
            pass
        try:
            await websocket.close(code=OWNER_CONFLICT_CODE, reason=OWNER_CONFLICT_REASON)
        except Exception:
            pass
        return
    _active_connection = connection
    _ws_metrics.connections_admitted += 1

    obs = _OutboundObsState()
    outbound_queue: asyncio.Queue[tuple[dict[str, Any], float]] = asyncio.Queue(
        maxsize=settings.ws_outbound_queue_max
    )

    # A broken send/close need not produce reader EOF. Supervise that failure
    # separately so a dead transport cannot reserve ownership indefinitely.
    writer_failed = asyncio.Event()
    reader_task: asyncio.Task | None = None
    failure_task: asyncio.Task | None = None

    async def _writer() -> None:
        try:
            while True:
                event, enqueue_time = await outbound_queue.get()
                if not _owns_connection(connection):
                    outbound_queue.task_done()
                    return
                lag = time.monotonic() - enqueue_time
                _ws_metrics.last_lag_secs = lag
                now = time.monotonic()
                event_type = event.get("type")
                above = lag >= _OUTBOUND_SEND_LAG_WARN_SECS
                if not above:
                    if obs.lag_above_warn:
                        logger.info(
                            "Outbound send lag recovered: lag=%.2fs event_type=%s",
                            lag,
                            event_type,
                        )
                        obs.lag_above_warn = False
                        obs.last_lag_log_mono = now
                        _ws_metrics.lag_recovery_crossings += 1
                else:
                    transition = not obs.lag_above_warn
                    periodic = (now - obs.last_lag_log_mono) >= _OBS_LOG_REPEAT_INTERVAL_SECS
                    if transition or periodic:
                        obs.lag_above_warn = True
                        obs.last_lag_log_mono = now
                        logger.warning(
                            "Outbound send lag: lag=%.2fs event_type=%s",
                            lag,
                            event_type,
                        )
                        if transition:
                            _ws_metrics.lag_warn_crossings += 1
                try:
                    await websocket.send_bytes(orjson.dumps(event))
                except Exception:
                    connection.closed = True
                    connection.close_reason = "writer_failed"
                    writer_failed.set()
                    try:
                        await websocket.close(code=1011, reason="writer_failed")
                    except Exception:
                        pass
                    return
                finally:
                    outbound_queue.task_done()
                    depth = outbound_queue.qsize()
                    _ws_metrics.current_depth = depth
                    _maybe_log_outbound_depth(obs, depth, event_type)
        except asyncio.CancelledError:
            raise

    writer_task = asyncio.create_task(_writer())

    def event_listener(event: dict[str, Any]) -> None:
        if _owns_connection(connection):
            if event.get("type") == "session_snapshot":
                event = {**event, "connection_lifecycle": {
                    "connection_id": connection.connection_id,
                    "state": "admitted", "reason": "owner_admitted",
                }}
            _enqueue_outbound(outbound_queue, event, obs)

    try:
        manager.on_client_connect()
        manager.subscribe(event_listener)
        lifecycle = _lifecycle(connection, "admitted", "owner_admitted")
        _enqueue_outbound(outbound_queue, {"type": "connection_lifecycle", **lifecycle}, obs)
        snapshot = manager.get_snapshot()
        _enqueue_outbound(
            outbound_queue, {"type": "session_snapshot", **snapshot, "connection_lifecycle": lifecycle}, obs
        )

        async def _read_commands() -> None:
            async for raw in websocket.iter_text():
                if not _owns_connection(connection):
                    connection.close_reason = "ownership_lost" if not connection.closed else connection.close_reason
                    break
                try:
                    msg = orjson.loads(raw)
                except Exception:
                    logger.warning("Invalid JSON from client: chars=%d", len(raw))
                    continue

                if not isinstance(msg, dict):
                    logger.warning("Invalid WebSocket command shape")
                    continue

                msg_type = msg.get("type")
                if not isinstance(msg_type, str):
                    logger.warning("Invalid WebSocket command type")
                    continue

                if msg_type == "start":
                    await _handle_start(msg, outbound_queue, obs)
                elif msg_type == "set_target_language":
                    await _handle_set_target_language(msg, outbound_queue, obs)
                elif msg_type == "set_translation_model":
                    await _handle_set_translation_model(msg, outbound_queue, obs)
                elif msg_type in {"update_terminology", "undo_terminology"}:
                    _handle_terminology(msg, outbound_queue, obs)
                elif msg_type == "stop":
                    await _handle_stop()
                elif msg_type == "finish_input":
                    await _handle_finish_input(outbound_queue, obs)
                elif msg_type == "export":
                    _handle_export()
                elif msg_type == "new_session":
                    await _handle_new_session(msg, outbound_queue, obs)
                elif msg_type == "retry_recovery":
                    await _handle_retry_recovery()
                elif msg_type == "discard_recovery":
                    await _handle_discard_recovery()
                elif msg_type == "tts_audio_enabled":
                    await _handle_tts_audio_enabled()
                elif msg_type == "tts_mute":
                    await _handle_tts_mute(msg, outbound_queue, obs)
                elif msg_type == "tts_catch_up":
                    _handle_tts_catch_up(msg)
                elif msg_type == "tts_replay":
                    await _handle_tts_replay(msg, outbound_queue, obs)
                elif msg_type == "render_ack":
                    _handle_latency_ack(msg, "render")
                elif msg_type == "tts_chunk_received":
                    _handle_tts_browser_ack(msg)
                elif msg_type in {"tts_playback_error", "tts_playback_stats"}:
                    _handle_tts_browser_ack(msg)
                elif msg_type == "tts_playback_start":
                    _handle_latency_ack(msg, "tts_start")
                elif msg_type == "tts_playback_complete":
                    _handle_latency_ack(msg, "tts_complete")
                else:
                    logger.debug("Unknown WebSocket command")

        reader_task = asyncio.create_task(_read_commands())
        failure_task = asyncio.create_task(writer_failed.wait())
        done, _pending = await asyncio.wait(
            [reader_task, failure_task], return_when=asyncio.FIRST_COMPLETED
        )
        if failure_task not in done and not writer_failed.is_set():
            await reader_task

    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        if not writer_failed.is_set():
            connection.close_reason = "cancelled"
        raise
    except RuntimeError as exc:
        if _is_expected_websocket_disconnect(exc):
            pass
        else:
            connection.close_reason = "handler_failed"
            logger.error("WebSocket handler failed: error_type=%s", type(exc).__name__)
    except Exception as exc:
        connection.close_reason = "handler_failed"
        logger.error("WebSocket handler failed: error_type=%s", type(exc).__name__)
    finally:
        connection.closed = True
        manager.unsubscribe(event_listener)
        if _active_connection is connection:
            if manager._tts_dispatcher is not None:
                manager._tts_dispatcher.set_audio_unlocked(False)
            manager.on_client_disconnect()
            _active_connection = None
            _ws_metrics.connections_closed += 1
        _lifecycle(connection, "closed", connection.close_reason)
        # All owner effects happen before this await. Old writer cleanup cannot
        # relock TTS or disconnect a new owner admitted during cancellation.
        tasks = [task for task in (reader_task, failure_task, writer_task) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _handle_tts_audio_enabled() -> None:
    assert manager is not None
    if manager._tts_dispatcher is None:
        return
    manager._tts_dispatcher.set_audio_unlocked(True)
    logger.debug("TTS audio unlocked by client")


async def _handle_tts_mute(
    msg: dict,
    outbound_queue: asyncio.Queue[tuple[dict[str, Any], float]],
    obs: _OutboundObsState,
) -> None:
    assert manager is not None
    muted = msg.get("muted")
    if not isinstance(muted, bool):
        _enqueue_outbound(
            outbound_queue,
            {"type": "error", "message": "tts_mute: 'muted' must be a boolean"},
            obs,
        )
        return
    if manager._tts_dispatcher is None:
        return
    manager._tts_dispatcher.set_muted(muted)


def _handle_tts_catch_up(msg: dict) -> None:
    assert manager is not None
    dispatcher = manager._tts_dispatcher
    epoch = msg.get("tts_epoch")
    if dispatcher is None or manager.session.status not in {
        "listening", "reconnecting", "session_ended"
    }:
        return
    if not isinstance(epoch, int) or isinstance(epoch, bool):
        return
    if epoch != dispatcher._tts_epoch:
        # A duplicate/stale request must not skip newly queued speech.
        manager._emit("tts_queue", dispatcher.get_speech_state())
        return
    dispatcher.catch_up()


async def _handle_tts_replay(
    msg: dict,
    outbound_queue: asyncio.Queue[tuple[dict[str, Any], float]],
    obs: _OutboundObsState,
) -> None:
    assert manager is not None
    seq = msg.get("seq")
    if not isinstance(seq, int):
        _enqueue_outbound(
            outbound_queue,
            {"type": "error", "message": "tts_replay: 'seq' must be an integer"},
            obs,
        )
        return

    seg = next((s for s in manager.session.segments if s.seq == seq), None)
    if seg is None:
        _enqueue_outbound(
            outbound_queue,
            {"type": "error", "message": f"tts_replay: segment {seq} not found"},
            obs,
        )
        return

    if seg.translated_text is None or seg.translated_text == "":
        _enqueue_outbound(
            outbound_queue,
            {"type": "error", "message": f"tts_replay: segment {seq} has no translation"},
            obs,
        )
        return

    if seg.target_language is None or seg.target_language == "":
        _enqueue_outbound(
            outbound_queue,
            {
                "type": "error",
                "message": f"tts_replay: segment {seq} has no target language",
            },
            obs,
        )
        return

    if seg.target_language not in VOICE_MAP:
        tts_epoch = (
            manager._tts_dispatcher._tts_epoch
            if manager._tts_dispatcher is not None
            else 0
        )
        _enqueue_outbound(
            outbound_queue,
            {
                "type": "tts_skipped",
                "seq": seq,
                "reason": "unsupported_language",
                "tts_epoch": tts_epoch,
            },
            obs,
        )
        return

    if manager._tts_dispatcher is None:
        return

    status = manager.session.status
    muted = manager._tts_dispatcher._muted

    if status == "session_ended":
        if not muted:
            manager._tts_dispatcher.enqueue_replay(seq, seg.translated_text, seg.target_language)
    elif status in ("listening", "reconnecting"):
        if not muted:
            manager._tts_dispatcher.enqueue_replay(seq, seg.translated_text, seg.target_language)
        else:
            logger.debug("tts_replay ignored: muted while %s", status)
    else:
        logger.debug("tts_replay ignored: status %s", status)


async def _handle_set_target_language(
    msg: dict,
    outbound_queue: asyncio.Queue[tuple[dict[str, Any], float]],
    obs: _OutboundObsState,
) -> None:
    assert manager is not None
    language = msg.get("language")
    if language is None or not isinstance(language, str):
        _enqueue_outbound(
            outbound_queue,
            {"type": "error", "message": "set_target_language: missing 'language' field"},
            obs,
        )
        return
    if not is_valid_target_language(language):
        _enqueue_outbound(
            outbound_queue,
            {"type": "error", "message": f"Unsupported target language: {language!r}"},
            obs,
        )
        return
    manager.set_target_language(language)


async def _handle_set_translation_model(
    msg: dict,
    outbound_queue: asyncio.Queue[tuple[dict[str, Any], float]],
    obs: _OutboundObsState,
) -> None:
    assert manager is not None
    try:
        model = validate_translation_model(msg.get("model"), manager.config)
        effort = validate_reasoning_effort(
            msg.get("reasoning_effort", manager.session.translation_reasoning_effort or "default"),
            model,
        )
        manager.set_translation_settings(model, effort)
    except ValueError as exc:
        _enqueue_outbound(
            outbound_queue, {"type": "error", "message": str(exc)}, obs
        )


async def _handle_start(
    msg: dict,
    outbound_queue: asyncio.Queue[tuple[dict[str, Any], float]],
    obs: _OutboundObsState,
) -> None:
    assert manager is not None

    if manager.session.status != "idle_ready":
        _enqueue_outbound(
            outbound_queue,
            {
                "type": "error",
                "message": f"Cannot start: system is not ready (status: {manager.session.status})",
            },
            obs,
        )
        return

    all_ready = all(c.ready for c in manager.checks)
    if not all_ready:
        _enqueue_outbound(
            outbound_queue,
            {
                "type": "error",
                "message": "Cannot start: readiness checks not passing",
            },
            obs,
        )
        return

    tts_muted = msg.get("tts_muted", False)
    if not isinstance(tts_muted, bool):
        _enqueue_outbound(
            outbound_queue,
            {"type": "error", "message": "start: 'tts_muted' must be a boolean"},
            obs,
        )
        return

    target_language = msg.get("target_language")
    if target_language is not None:
        if not isinstance(target_language, str) or not is_valid_target_language(target_language):
            _enqueue_outbound(
                outbound_queue,
                {
                    "type": "error",
                    "message": "Unsupported target language.",
                },
                obs,
            )
            return
    language = target_language or manager.session.target_language
    try:
        glossary = parse_glossary(msg.get("glossary", []), language)
        profile = resolve_profile(msg.get("caption_profile", "current"), manager.config)
    except ValueError as exc:
        _enqueue_outbound(
            outbound_queue, {"type": "error", "message": str(exc)}, obs
        )
        return
    try:
        model = validate_translation_model(
            msg.get("translation_model", manager.session.translation_model),
            manager.config,
        )
        effort = validate_reasoning_effort(
            msg.get("translation_reasoning_effort", "default"), model
        )
    except ValueError as exc:
        _enqueue_outbound(
            outbound_queue, {"type": "error", "message": str(exc)}, obs
        )
        return
    manager.set_target_language(language)
    manager.set_translation_settings(model, effort)
    manager.session.caption_profile = profile
    terminology.initialize(manager.session, glossary)

    if start_pipeline is not None:
        try:
            if manager._tts_dispatcher is not None:
                manager._tts_dispatcher.set_muted(tts_muted)
            await start_pipeline()
            manager._emit("terminology_updated", terminology.state(manager.session))
        except Exception as exc:
            logger.error("Pipeline startup failed: error_type=%s", type(exc).__name__)
            _enqueue_outbound(
                outbound_queue,
                {
                    "type": "error",
                    "message": "Pipeline startup failed. Check readiness and logs.",
                },
                obs,
            )


def _handle_terminology(msg: dict, outbound_queue: asyncio.Queue, obs: _OutboundObsState) -> None:
    assert manager is not None
    try:
        terminology.change(manager, msg, undo=msg.get("type") == "undo_terminology")
    except ValueError as exc:
        _enqueue_outbound(outbound_queue, {
            "type": "terminology_error", "message": str(exc),
            **terminology.state(manager.session),
        }, obs)
    except OSError:
        _enqueue_outbound(outbound_queue, {
            "type": "terminology_error", "message": "Terminology could not be saved. Try again.",
            **terminology.state(manager.session),
        }, obs)


async def _handle_stop() -> None:
    assert manager is not None
    if stop_pipeline is not None:
        await stop_pipeline()
    if manager.session.status in ("listening", "reconnecting"):
        manager.set_status("session_ended")


async def _handle_finish_input(outbound_queue: asyncio.Queue, obs: _OutboundObsState) -> None:
    if finish_input is None:
        _enqueue_outbound(outbound_queue, {"type": "error", "message": "Finishing input is unavailable"}, obs)
        return
    try:
        await finish_input()
    except ValueError:
        _enqueue_outbound(outbound_queue, {"type": "error", "message": "Input can only finish after transcription is ready"}, obs)


def _handle_export() -> None:
    assert manager is not None
    if manager.session.status != "session_ended":
        manager._emit("export_result", {
            "success": False,
            "path": None,
            "error": (
                f"Export is only available after the session has ended "
                f"(current status: {manager.session.status})"
            ),
        })
        return
    result = manager.export()
    manager._emit("export_result", result)


async def _handle_new_session(
    msg: dict,
    outbound_queue: asyncio.Queue[tuple[dict[str, Any], float]],
    obs: _OutboundObsState,
) -> None:
    assert manager is not None
    tts_muted = msg.get("tts_muted", False)
    if not isinstance(tts_muted, bool):
        _enqueue_outbound(
            outbound_queue,
            {"type": "error", "message": "new_session: 'tts_muted' must be a boolean"},
            obs,
        )
        return
    if stop_pipeline is not None and manager.session.status in (
        "listening",
        "reconnecting",
    ):
        await stop_pipeline()
    await manager.reset(emit_snapshot=False)
    if manager._tts_dispatcher is not None:
        manager._tts_dispatcher.set_muted(tts_muted)
    journal = SessionJournal(session_id=manager.session.id, config=settings)
    manager.set_journal(journal)
    if poller is not None:
        await poller.evaluate_now()
    manager._emit("session_snapshot", manager.get_snapshot())


async def _handle_retry_recovery() -> None:
    assert manager is not None
    if manager.recovery_state is None:
        logger.warning("retry_recovery: no recovery state")
        return
    if manager.recovery_notice is None or manager.recovery_notice.status != "failed":
        logger.warning("retry_recovery: recovery notice is not in failed state")
        return

    export_path, error = retry_recovery(manager.recovery_state, settings)
    if export_path is not None:
        manager.recovery_notice = RecoveryNotice(
            recovered_session_id=manager.recovery_state.recovered_session_id,
            status="success",
            export_path=export_path,
            created_at=manager.recovery_state.created_at,
        )
        manager.recovery_state = None
    else:
        manager.recovery_state.last_error = error  # type: ignore[assignment]
        if manager.recovery_notice is not None:
            manager.recovery_notice.error = error

    if poller is not None:
        await poller.evaluate_now()
    manager._emit("session_snapshot", manager.get_snapshot())


async def _handle_discard_recovery() -> None:
    assert manager is not None
    if manager.recovery_state is None:
        logger.warning("discard_recovery: no recovery state")
        return

    discard_recovery(manager.recovery_state, settings)
    manager.recovery_state = None
    manager.recovery_notice = None

    if poller is not None:
        await poller.evaluate_now()
    manager._emit("session_snapshot", manager.get_snapshot())


def _handle_latency_ack(msg: dict, kind: str) -> None:
    assert manager is not None
    seq = msg.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool):
        return
    if kind == "render":
        manager.observe_render_ack(seq)
    elif kind in {"tts_start", "tts_complete"}:
        dispatcher = getattr(manager, "_tts_dispatcher", None)
        if dispatcher is not None:
            epoch = msg.get("tts_epoch")
            if not isinstance(epoch, int) or isinstance(epoch, bool):
                return
            clip_id = msg.get("clip_id")
            if clip_id is not None and (not isinstance(clip_id, int) or isinstance(clip_id, bool)):
                return
            if not dispatcher.acknowledge_playback(
                seq, epoch, complete=kind == "tts_complete", clip_id=clip_id,
            ):
                return
        if kind == "tts_start":
            manager.observe_tts_playback_start(seq)
        else:
            manager.observe_tts_playback_complete(seq)


def _handle_tts_browser_ack(msg: dict) -> None:
    assert manager is not None
    dispatcher = getattr(manager, "_tts_dispatcher", None)
    if dispatcher is None:
        return
    if msg.get("type") == "tts_chunk_received":
        values = [msg.get(key) for key in ("seq", "tts_epoch", "clip_id")]
        if all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            dispatcher.acknowledge_first_chunk(*values)
    else:
        dispatcher.acknowledge_browser_result(msg)
