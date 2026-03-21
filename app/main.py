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
from app.reconnect import ReconnectionManager
from app.state import SessionManager
from app.transcribe import transcribe
from app.translate import TranslationDispatcher
from app import ws

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Core singletons
# ---------------------------------------------------------------------------

manager = SessionManager(config=settings)
dispatcher = TranslationDispatcher(session_manager=manager, config=settings)
manager.set_dispatcher(dispatcher)
poller = ReadinessPoller(manager=manager, config=settings)
reconnect_manager = ReconnectionManager(session_manager=manager, config=settings)

# Wire module-level references in ws.py
ws.manager = manager

# ---------------------------------------------------------------------------
# Pipeline state (one session at a time)
# ---------------------------------------------------------------------------

_audio: AudioCapture | None = None
_detector: BoundaryDetector | None = None
_transcribe_task: asyncio.Task | None = None
_stream_ready: asyncio.Event = asyncio.Event()
_stream_error: Exception | None = None
_pipeline_stopping: bool = False


def _on_session_created() -> None:
    """Called when the Mistral realtime session handshake completes."""
    global _stream_error
    _stream_error = None
    _stream_ready.set()


async def _wait_for_stream_established() -> None:
    """Block until the realtime stream session is created or an error occurs.

    During reconnect, also monitors the attempt-failure signal so that
    post-handshake errors/Done events are not silently swallowed.
    """
    if manager.session.status == "reconnecting":
        ready_fut = asyncio.ensure_future(_stream_ready.wait())
        failed_fut = asyncio.ensure_future(reconnect_manager.attempt_failed.wait())
        try:
            done, _pending = await asyncio.wait(
                [ready_fut, failed_fut],
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for t in (ready_fut, failed_fut):
                if not t.done():
                    t.cancel()
        if failed_fut in done:
            raise RuntimeError(
                "Reconnect attempt failed during stream establishment"
            )
    else:
        await _stream_ready.wait()
    if _stream_error is not None:
        raise _stream_error


async def _start_pipeline() -> None:
    """Spin up mic capture → transcription → boundary detection."""
    global _audio, _detector, _transcribe_task, _stream_error, _pipeline_stopping  # noqa: PLW0603

    _pipeline_stopping = False
    _stream_ready.clear()
    _stream_error = None

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

    if manager.session.status != "reconnecting":
        manager.set_status("listening")

    attempt_id = reconnect_manager.current_attempt_id
    _transcribe_task = asyncio.ensure_future(
        transcribe(
            audio_stream=_audio.stream(),
            config=settings,
            on_delta=_detector.push,
            on_done=lambda: _on_transcription_done(attempt_id),
            on_error=lambda exc: _on_transcription_error(exc, attempt_id),
            on_session_created=_on_session_created,
        )
    )


async def _teardown_pipeline() -> None:
    """Low-level cleanup: stop audio, cancel transcription task, reset detector."""
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


async def _stop_pipeline() -> None:
    """Full stop: cancel reconnection, tear down pipeline, drain translations."""
    global _pipeline_stopping
    _pipeline_stopping = True
    reconnect_manager.cancel()
    await _teardown_pipeline()
    await dispatcher.drain()


def _on_transcription_done(attempt_id: int) -> None:
    global _stream_error

    if not _stream_ready.is_set():
        _stream_error = RuntimeError("Stream closed before session was established")
        _stream_ready.set()

    if _pipeline_stopping:
        if _detector is not None:
            remaining = _detector.flush_reconnect_fragment()
            if remaining:
                manager.finalize_reconnect_fragment(remaining)
        logger.info("Transcription stream completed (pipeline stopping)")
        return

    if manager.session.status == "reconnecting":
        if attempt_id != reconnect_manager.current_attempt_id:
            logger.debug(
                "Ignoring stale stream-done from old attempt %d (current: %d)",
                attempt_id,
                reconnect_manager.current_attempt_id,
            )
            return
        if _detector is not None:
            remaining = _detector.flush_reconnect_fragment()
            if remaining:
                manager.finalize_reconnect_fragment(remaining)
        logger.warning(
            "Unexpected stream done during reconnect attempt %d "
            "— signaling attempt failure",
            reconnect_manager.current_attempt_id,
        )
        _stream_error = RuntimeError(
            "Stream closed unexpectedly during reconnect"
        )
        reconnect_manager.signal_attempt_failed()
        return

    logger.warning("Transcription stream ended unexpectedly — triggering reconnect")
    reconnect_manager.on_connection_error(
        RuntimeError("Transcription stream ended unexpectedly")
    )


def _on_transcription_error(exc: Exception, attempt_id: int) -> None:
    global _stream_error
    logger.error("Transcription error: %s", exc)
    if not _stream_ready.is_set():
        _stream_error = exc
        _stream_ready.set()

    if manager.session.status == "reconnecting":
        if attempt_id != reconnect_manager.current_attempt_id:
            logger.debug(
                "Ignoring stale error from old attempt %d (current: %d)",
                attempt_id,
                reconnect_manager.current_attempt_id,
            )
            return
        logger.warning(
            "Error during reconnect attempt %d — signaling attempt failure",
            reconnect_manager.current_attempt_id,
        )
        _stream_error = exc
        reconnect_manager.signal_attempt_failed()
        return

    reconnect_manager.on_connection_error(exc)


async def _on_grace_expiry() -> None:
    """Called when browser disconnect grace period expires — full teardown."""
    await _stop_pipeline()
    if manager.session.status in ("listening", "reconnecting"):
        manager.set_status("session_ended")


# Wire pipeline functions into ws.py
ws.start_pipeline = _start_pipeline
ws.stop_pipeline = _stop_pipeline
manager.set_grace_expiry_hook(_on_grace_expiry)


def _on_reconnect_fragment_finalized(fragment: str) -> None:
    """Route reconnect fragments through the same finalize+dispatch flow."""
    manager.finalize_reconnect_fragment(fragment)


# Wire reconnect manager dependencies
reconnect_manager.get_detector = lambda: _detector
reconnect_manager.teardown_pipeline = _teardown_pipeline
reconnect_manager.start_pipeline = _start_pipeline
reconnect_manager.finalize_reconnect_fragment = _on_reconnect_fragment_finalized
reconnect_manager.wait_for_stream = _wait_for_stream_established

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
