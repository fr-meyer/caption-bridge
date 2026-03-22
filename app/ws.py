"""WebSocket handler — bridges SessionManager events to the browser."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import orjson
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.config import settings
from app.journal import SessionJournal, discard_recovery, retry_recovery
from app.languages import is_valid_target_language
from app.state import RecoveryNotice, SessionManager

if TYPE_CHECKING:
    from app.readiness import ReadinessPoller

logger = logging.getLogger(__name__)

# Module-level references set by main.py at startup
manager: SessionManager | None = None
start_pipeline: Callable[[], Any] | None = None
stop_pipeline: Callable[[], Any] | None = None
poller: ReadinessPoller | None = None

_active_ws: WebSocket | None = None


def _send_event(ws: WebSocket, event: dict[str, Any]) -> None:
    """Schedule a send on the WebSocket (fire-and-forget from sync context)."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    if ws.client_state != WebSocketState.CONNECTED:
        return

    async def _do_send() -> None:
        try:
            await ws.send_bytes(orjson.dumps(event))
        except Exception:
            logger.debug("Failed to send event %s", event.get("type"))

    loop.create_task(_do_send())


async def websocket_endpoint(websocket: WebSocket) -> None:
    """Main WebSocket handler at /ws."""
    global _active_ws  # noqa: PLW0603

    assert manager is not None, "SessionManager not wired"

    await websocket.accept()

    # If there's already a connection, replace it silently
    if _active_ws is not None:
        try:
            await _active_ws.close(code=1000, reason="replaced")
        except Exception:
            pass

    _active_ws = websocket

    def event_listener(event: dict[str, Any]) -> None:
        _send_event(websocket, event)

    manager.on_client_connect()
    manager.subscribe(event_listener)

    try:
        snapshot = manager.get_snapshot()
        await websocket.send_bytes(
            orjson.dumps({"type": "session_snapshot", **snapshot})
        )

        async for raw in websocket.iter_text():
            try:
                msg = orjson.loads(raw)
            except Exception:
                logger.warning("Invalid JSON from client: %s", raw[:100])
                continue

            msg_type = msg.get("type")

            if msg_type == "start":
                await _handle_start(websocket, msg)
            elif msg_type == "set_target_language":
                await _handle_set_target_language(websocket, msg)
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
            else:
                logger.debug("Unknown WS message type: %s", msg_type)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception:
        logger.exception("WebSocket handler error")
    finally:
        manager.unsubscribe(event_listener)
        if _active_ws is websocket:
            manager.on_client_disconnect()
            _active_ws = None


async def _handle_set_target_language(ws: WebSocket, msg: dict) -> None:
    assert manager is not None
    language = msg.get("language")
    if language is None or not isinstance(language, str):
        await ws.send_bytes(
            orjson.dumps({"type": "error", "message": "set_target_language: missing 'language' field"})
        )
        return
    if not is_valid_target_language(language):
        await ws.send_bytes(
            orjson.dumps({"type": "error", "message": f"Unsupported target language: {language!r}"})
        )
        return
    manager.set_target_language(language)


async def _handle_start(ws: WebSocket, msg: dict) -> None:
    assert manager is not None

    if manager.session.status != "idle_ready":
        await ws.send_bytes(
            orjson.dumps(
                {
                    "type": "error",
                    "message": f"Cannot start: system is not ready (status: {manager.session.status})",
                }
            )
        )
        return

    all_ready = all(c.ready for c in manager.checks)
    if not all_ready:
        await ws.send_bytes(
            orjson.dumps(
                {
                    "type": "error",
                    "message": "Cannot start: readiness checks not passing",
                }
            )
        )
        return

    target_language = msg.get("target_language")
    if target_language is not None:
        if not is_valid_target_language(target_language):
            await ws.send_bytes(
                orjson.dumps(
                    {
                        "type": "error",
                        "message": f"Unsupported target language: {target_language!r}",
                    }
                )
            )
            return
        manager.set_target_language(target_language)

    if start_pipeline is not None:
        try:
            await start_pipeline()
        except Exception as exc:
            logger.exception("Pipeline startup failed")
            await ws.send_bytes(
                orjson.dumps(
                    {
                        "type": "error",
                        "message": f"Pipeline startup failed: {exc}",
                    }
                )
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
    manager.reset(emit_snapshot=False)
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
