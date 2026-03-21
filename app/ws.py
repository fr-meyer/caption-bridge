"""WebSocket handler — bridges SessionManager events to the browser."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import orjson
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.config import settings
from app.journal import SessionJournal
from app.state import SessionManager

logger = logging.getLogger(__name__)

# Module-level references set by main.py at startup
manager: SessionManager | None = None
start_pipeline: Callable[[], Any] | None = None
stop_pipeline: Callable[[], Any] | None = None

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
                await _handle_start(websocket)
            elif msg_type == "stop":
                await _handle_stop()
            elif msg_type == "export":
                _handle_export()
            elif msg_type == "new_session":
                await _handle_new_session()
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


async def _handle_start(ws: WebSocket) -> None:
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
    result = manager.export()
    manager._emit("export_result", result)


async def _handle_new_session() -> None:
    assert manager is not None
    if stop_pipeline is not None and manager.session.status in (
        "listening",
        "reconnecting",
    ):
        await stop_pipeline()
    manager.reset()
    journal = SessionJournal(session_id=manager.session.id, config=settings)
    manager.set_journal(journal)
