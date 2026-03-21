"""CaptionBridge — FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from app.audio import AudioCapture
from app.boundary import BoundaryDetector
from app.config import settings
from app.readiness import ReadinessPoller
from app.state import SessionManager
from app.transcribe import transcribe
from app import ws

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Core singletons
# ---------------------------------------------------------------------------

manager = SessionManager(config=settings)
poller = ReadinessPoller(manager=manager, config=settings)

# Wire module-level references in ws.py
ws.manager = manager

# ---------------------------------------------------------------------------
# Pipeline state (one session at a time)
# ---------------------------------------------------------------------------

_audio: AudioCapture | None = None
_detector: BoundaryDetector | None = None
_transcribe_task: asyncio.Task | None = None


async def _start_pipeline() -> None:
    """Spin up mic capture → transcription → boundary detection."""
    global _audio, _detector, _transcribe_task  # noqa: PLW0603

    loop = asyncio.get_running_loop()
    audio = AudioCapture(sample_rate=settings.audio_sample_rate, loop=loop)
    detector = BoundaryDetector(
        pause_timeout_s=settings.pause_timeout_ms / 1000,
        on_partial=manager.update_partial,
        on_finalize=manager.finalize_segment,
    )

    try:
        audio.start()
    except Exception:
        try:
            audio.stop()
        except Exception:
            pass
        raise

    _audio = audio
    _detector = detector
    manager.set_status("listening")

    _transcribe_task = asyncio.ensure_future(
        transcribe(
            audio_stream=_audio.stream(),
            config=settings,
            on_delta=_detector.push,
            on_done=_on_transcription_done,
            on_error=_on_transcription_error,
        )
    )


async def _stop_pipeline() -> None:
    """Gracefully tear down the active pipeline."""
    global _audio, _detector, _transcribe_task  # noqa: PLW0603

    if _audio is not None:
        _audio.stop()

    if _transcribe_task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(_transcribe_task), timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _transcribe_task.cancel()
        except Exception:
            logger.debug("Transcription task finished with error during stop")
        _transcribe_task = None

    if _detector is not None:
        _detector.reset()

    _audio = None
    _detector = None


def _on_transcription_done() -> None:
    if _detector is not None:
        remaining = _detector.flush_reconnect_fragment()
        if remaining:
            manager.finalize_segment(remaining)
    logger.info("Transcription stream completed")


def _on_transcription_error(exc: Exception) -> None:
    logger.error("Transcription error: %s", exc)
    manager._emit("error", {"message": str(exc)})

    async def _cleanup() -> None:
        await _stop_pipeline()
        if manager.session.status in ("listening", "reconnecting"):
            manager.set_status("session_ended")

    asyncio.ensure_future(_cleanup())


async def _on_grace_expiry() -> None:
    """Called when browser disconnect grace period expires — full teardown."""
    await _stop_pipeline()
    if manager.session.status in ("listening", "reconnecting"):
        manager.set_status("session_ended")


# Wire pipeline functions into ws.py
ws.start_pipeline = _start_pipeline
ws.stop_pipeline = _stop_pipeline
manager.set_grace_expiry_hook(_on_grace_expiry)

# ---------------------------------------------------------------------------
# FastAPI app with lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    poller.start()
    logger.info("CaptionBridge started on %s:%s", settings.host, settings.port)
    yield
    poller.stop()
    await _stop_pipeline()
    logger.info("CaptionBridge shut down")


app = FastAPI(title="CaptionBridge", lifespan=lifespan)

# WebSocket route MUST be registered before the catch-all static mount
app.add_api_websocket_route("/ws", ws.websocket_endpoint)

# Static files — catch-all, must be last
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
