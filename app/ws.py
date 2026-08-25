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

from app.config import settings
from app.journal import SessionJournal, discard_recovery, retry_recovery
from app.languages import is_valid_target_language
from app.state import RecoveryNotice, SessionManager
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
        "error",
        "export_result",
        "provider_temporarily_unavailable",
        "reconnect_attempt",
        "reconnect_cancelled",
        "recovered",
        "session_snapshot",
        "status",
        "tts_error",
        "tts_skipped",
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
poller: ReadinessPoller | None = None

_active_ws: WebSocket | None = None


async def websocket_endpoint(websocket: WebSocket) -> None:
    """Main WebSocket handler at /ws."""
    global _active_ws  # noqa: PLW0603

    assert manager is not None, "SessionManager not wired"

    await websocket.accept()

    obs = _OutboundObsState()
    outbound_queue: asyncio.Queue[tuple[dict[str, Any], float]] = asyncio.Queue(
        maxsize=settings.ws_outbound_queue_max
    )

    async def _writer() -> None:
        try:
            while True:
                event, enqueue_time = await outbound_queue.get()
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
                    logger.debug("Failed to send event %s", event.get("type"))
                finally:
                    outbound_queue.task_done()
                    depth = outbound_queue.qsize()
                    _ws_metrics.current_depth = depth
                    _maybe_log_outbound_depth(obs, depth, event_type)
        except asyncio.CancelledError:
            raise

    writer_task = asyncio.create_task(_writer())

    # If there's already a connection, replace it silently
    if _active_ws is not None:
        manager.note_browser_replacement()
        if manager._tts_dispatcher is not None:
            manager._tts_dispatcher.set_audio_unlocked(False)
        try:
            await _active_ws.close(code=1000, reason="replaced")
        except Exception:
            pass

    _active_ws = websocket

    def event_listener(event: dict[str, Any]) -> None:
        _enqueue_outbound(outbound_queue, event, obs)

    manager.on_client_connect()
    manager.subscribe(event_listener)

    try:
        snapshot = manager.get_snapshot()
        _enqueue_outbound(
            outbound_queue, {"type": "session_snapshot", **snapshot}, obs
        )

        async for raw in websocket.iter_text():
            try:
                msg = orjson.loads(raw)
            except Exception:
                logger.warning("Invalid JSON from client: chars=%d", len(raw))
                continue

            msg_type = msg.get("type")

            if msg_type == "start":
                await _handle_start(msg, outbound_queue, obs)
            elif msg_type == "set_target_language":
                await _handle_set_target_language(msg, outbound_queue, obs)
            elif msg_type == "stop":
                await _handle_stop()
            elif msg_type == "export":
                _handle_export()
            elif msg_type == "new_session":
                await _handle_new_session()
            elif msg_type == "retry_recovery":
                await _handle_retry_recovery()
            elif msg_type == "discard_recovery":
                await _handle_discard_recovery()
            elif msg_type == "tts_audio_enabled":
                await _handle_tts_audio_enabled()
            elif msg_type == "tts_mute":
                await _handle_tts_mute(msg, outbound_queue, obs)
            elif msg_type == "tts_replay":
                await _handle_tts_replay(msg, outbound_queue, obs)
            elif msg_type == "render_ack":
                _handle_latency_ack(msg, "render")
            elif msg_type == "tts_playback_start":
                _handle_latency_ack(msg, "tts_start")
            elif msg_type == "tts_playback_complete":
                _handle_latency_ack(msg, "tts_complete")
            else:
                logger.debug("Unknown WS message type: %s", msg_type)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except RuntimeError as exc:
        if _is_expected_websocket_disconnect(exc):
            logger.info("WebSocket client disconnected")
        else:
            logger.exception("WebSocket handler error")
    except Exception:
        logger.exception("WebSocket handler error")
    finally:
        writer_task.cancel()
        await asyncio.gather(writer_task, return_exceptions=True)
        manager.unsubscribe(event_listener)
        if _active_ws is websocket:
            if manager._tts_dispatcher is not None:
                manager._tts_dispatcher.set_audio_unlocked(False)
            manager.on_client_disconnect()
            _active_ws = None


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

    target_language = msg.get("target_language")
    if target_language is not None:
        if not is_valid_target_language(target_language):
            _enqueue_outbound(
                outbound_queue,
                {
                    "type": "error",
                    "message": f"Unsupported target language: {target_language!r}",
                },
                obs,
            )
            return
        manager.set_target_language(target_language)

    if start_pipeline is not None:
        try:
            await start_pipeline()
            if manager._tts_dispatcher is not None:
                manager._tts_dispatcher.reset_mute()
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


async def _handle_stop() -> None:
    assert manager is not None
    if stop_pipeline is not None:
        await stop_pipeline()
    if manager.session.status in ("listening", "reconnecting"):
        manager.set_status("session_ended")


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


async def _handle_new_session() -> None:
    assert manager is not None
    if stop_pipeline is not None and manager.session.status in (
        "listening",
        "reconnecting",
    ):
        await stop_pipeline()
    await manager.reset(emit_snapshot=False)
    if manager._tts_dispatcher is not None:
        manager._tts_dispatcher.reset_mute()
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
    elif kind == "tts_start":
        manager.observe_tts_playback_start(seq)
    elif kind == "tts_complete":
        manager.observe_tts_playback_complete(seq)
