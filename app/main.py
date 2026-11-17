"""CaptionBridge — FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from mistralai.client import Mistral
from starlette.staticfiles import StaticFiles

from app import ws
from app.asr_diagnostics import safe_asr_reason
from app.audio import AudioCapture
from app.audio_devices import native_input_devices
from app.boundary import BoundaryDetector
from app.config import settings
from app.identity import runtime_identity
from app.journal import SessionJournal, run_recovery
from app.profiles import resolve_profile
from app.readiness import ReadinessPoller
from app.reconnect import ReconnectionManager
from app.state import SessionManager
from app.transcribe import AsrStreamError, transcribe
from app.translate import TranslationDispatcher
from app.tts import TTSDispatcher

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Core singletons
# ---------------------------------------------------------------------------

manager = SessionManager(config=settings)
manager.input_devices = native_input_devices(settings.audio_sample_rate)
dispatcher = TranslationDispatcher(session_manager=manager, config=settings)
manager.set_dispatcher(dispatcher)
mistral_client = Mistral(api_key=settings.mistral_api_key)
tts_dispatcher = TTSDispatcher(mistral_client, manager, settings)
manager.set_tts_dispatcher(tts_dispatcher)
poller = ReadinessPoller(manager=manager, config=settings)
reconnect_manager = ReconnectionManager(session_manager=manager, config=settings)

# Wire module-level references in ws.py
ws.catalogue_loader = dispatcher._provider.list_models
ws.manager = manager
ws.poller = poller

# ---------------------------------------------------------------------------
# Pipeline state (one session at a time)
# ---------------------------------------------------------------------------

_audio: AudioCapture | None = None
_detector: BoundaryDetector | None = None
_transcribe_task: asyncio.Task | None = None
_stream_ready: asyncio.Event = asyncio.Event()
_stream_error: Exception | None = None
_pipeline_stopping: bool = False
_pipeline_generation: int = 0
_stream_established: bool = False
_has_verified_session: bool = False
_initial_establishment_task: asyncio.Task | None = None
_input_finishing: bool = False
_stream_completed: bool = False


def _on_session_created(generation: int | None = None) -> None:
    """Called when the Mistral realtime session handshake completes."""
    global _stream_error, _stream_established, _has_verified_session
    if _stream_completed or (generation is not None and not _is_current_pipeline(generation)):
        return
    _stream_error = None
    _stream_established = True
    _has_verified_session = True
    manager.set_asr_state("ready")
    reconnect_manager.diagnostics.emit("stream_ready", attempt_id=reconnect_manager.current_attempt_id)
    _stream_ready.set()


def _is_current_pipeline(generation: int) -> bool:
    return generation == _pipeline_generation and not _pipeline_stopping


def _accepts_stream_data(generation: int) -> bool:
    # Established streams may deliver final text while normal Stop drains;
    # state callbacks still cannot revive a stopping or replaced pipeline.
    return (not _stream_completed and generation == _pipeline_generation
            and (not _pipeline_stopping or _stream_established))


async def _watch_initial_establishment(generation: int) -> None:
    """Establish once within a deadline; Start never blocks the WS Stop handler."""
    try:
        await asyncio.wait_for(
            _wait_for_stream_established(), settings.asr_initial_timeout_ms / 1000
        )
    except asyncio.CancelledError:
        return
    except Exception as exc:
        if not _is_current_pipeline(generation):
            return
        reason = "initial_timeout" if isinstance(exc, TimeoutError) else safe_asr_reason(exc)
        if isinstance(exc, TimeoutError):
            if reconnect_manager.record_stream_failure(AsrStreamError(reason), reconnect_manager.current_attempt_id):
                manager.record_asr_error()
        manager.set_asr_state("failed", reason)
        await _stop_pipeline()
        if manager.session.status in ("listening", "reconnecting"):
            manager.set_status("session_ended")
        manager._write_reliability_record()


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
    global _pipeline_generation, _stream_established, _has_verified_session, _initial_establishment_task
    global _input_finishing, _stream_completed

    _pipeline_stopping = False
    _input_finishing = False
    _stream_completed = False
    _pipeline_generation += 1
    generation = _pipeline_generation
    _stream_established = False
    initial = manager.session.status != "reconnecting"
    if initial:
        _has_verified_session = False
        reconnect_manager.begin_run()
    _stream_ready.clear()
    _stream_error = None

    loop = asyncio.get_running_loop()
    audio = AudioCapture(
        device=manager.input_devices.capture_device() if manager.input_devices is not None else None,
        sample_rate=settings.audio_sample_rate,
        loop=loop,
        max_queue_chunks=settings.audio_queue_max_chunks,
        metrics_callback=manager.record_audio_queue,
        onset_callback=lambda chunk: manager.observe_speech_pcm(chunk) if _is_current_pipeline(generation) else None,
        # Received PCM remains capture ingress while its accepted tail drains;
        # only generation replacement makes those capture counters stale.
        ingress_callback=lambda metrics: manager.record_audio_ingress(metrics) if generation == _pipeline_generation else None,
    )
    profile = manager.session.caption_profile or resolve_profile("current", settings)
    detector = BoundaryDetector(
        pause_timeout_s=profile.pause_timeout_ms / 1000,
        on_partial=manager.update_partial,
        on_finalize=manager.finalize_segment,
        fragment_merge_enabled=settings.fragment_merge_enabled,
        fragment_max_hold_s=profile.fragment_max_hold_ms / 1000,
        min_segment_chars=settings.fragment_min_chars,
        min_segment_tokens=settings.fragment_min_tokens,
    )

    try:
        audio.start()
    except Exception:
        try:
            audio.stop()
        except Exception:
            pass
        manager.set_capture_active(False)
        manager.set_asr_state("failed", "microphone_error")
        manager.record_asr_error()
        raise

    _audio = audio
    _detector = detector
    manager.set_capture_active(True)
    manager.set_asr_state("connecting")
    reconnect_manager.diagnostics.emit("stream_connecting", attempt_id=reconnect_manager.current_attempt_id)

    if manager.session.status != "reconnecting":
        manager.set_status("listening")

    attempt_id = reconnect_manager.current_attempt_id
    _transcribe_task = asyncio.ensure_future(
        transcribe(
            audio_stream=_audio.stream(),
            config=settings,
            on_delta=lambda text: detector.push(text) if _accepts_stream_data(generation) else None,
            on_final_text=lambda text: detector.push(text) if _accepts_stream_data(generation) else None,
            on_protocol=lambda data: manager.record_asr_protocol(data) if _accepts_stream_data(generation) else None,
            on_done=lambda: _on_transcription_done(attempt_id, generation),
            on_error=lambda exc: _on_transcription_error(exc, attempt_id, generation),
            on_session_created=lambda: _on_session_created(generation),
            on_sent=lambda size: manager.record_asr_sent(size) if _accepts_stream_data(generation) else None,
            on_event=lambda kind, chars: manager.record_asr_event(kind, chars) if _accepts_stream_data(generation) else None,
        )
    )
    if initial:
        _initial_establishment_task = asyncio.create_task(_watch_initial_establishment(generation))


async def _teardown_pipeline() -> None:
    """Low-level cleanup: stop audio, cancel transcription task, reset detector."""
    global _audio, _detector, _transcribe_task, _pipeline_generation  # noqa: PLW0603

    if not _pipeline_stopping:
        _pipeline_generation += 1

    if _audio is not None:
        _audio.stop()
        manager.set_capture_active(False)

    if _transcribe_task is not None:
        if not _stream_established:
            _transcribe_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(_transcribe_task), timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _transcribe_task.cancel()
            await asyncio.gather(_transcribe_task, return_exceptions=True)
        except Exception:
            logger.debug("Transcription task finished with error during stop")
        _transcribe_task = None

    if _detector is not None:
        if _pipeline_stopping:
            remaining = _detector.flush_buffer()
            if remaining:
                manager.finalize_segment(remaining)
        _detector.reset()

    _audio = None
    _detector = None
    if _pipeline_stopping:
        _pipeline_generation += 1


async def _stop_pipeline() -> None:
    """Full stop: cancel reconnection, tear down pipeline, drain translations."""
    global _pipeline_stopping, _initial_establishment_task, _input_finishing
    _pipeline_stopping = True
    _input_finishing = False
    if _initial_establishment_task is not None:
        if _initial_establishment_task is not asyncio.current_task():
            _initial_establishment_task.cancel()
        _initial_establishment_task = None
    reconnect_manager.cancel()
    await _teardown_pipeline()
    if manager._reliability.pipeline.state != "failed":
        manager.set_asr_state("stopped", "user_stop")
    await dispatcher.drain()
    await tts_dispatcher.drain()


async def _finish_input() -> None:
    """Explicitly finish mic input while admitted captions/speech complete."""
    global _pipeline_stopping, _input_finishing
    if _input_finishing or manager._reliability.pipeline.reason == "input_finished":
        return
    if (manager.session.status != "listening" or not _stream_established
            or _stream_completed or _pipeline_stopping or _audio is None):
        raise ValueError("Input can only finish after transcription is ready")
    _input_finishing = True
    _pipeline_stopping = True
    reconnect_manager.cancel()
    manager.set_asr_state("draining")
    _audio.finish_input()
    manager.set_capture_active(False)


def _complete_finished_input(state: str, reason: str) -> None:
    if _detector is not None:
        remaining = _detector.flush_buffer()
        if remaining:
            manager.finalize_segment(remaining)
    manager.set_asr_state(state, reason)
    # Emitted after the final source flush, so this count is the admission
    # ceiling for callers waiting for captions and translated speech to drain.
    manager._emit("finish_input_complete", {
        "asr_state": state, "reason": reason,
        "source_count": len(manager.session.segments),
        "translation_pending_count": sum(seg.translation_status == "pending" for seg in manager.session.segments),
    })


def _on_transcription_done(attempt_id: int, generation: int | None = None) -> None:
    global _stream_error, _stream_completed

    if _stream_completed or (generation is not None and generation != _pipeline_generation):
        return
    if _pipeline_stopping and not _input_finishing:
        return
    if manager.session.status == "reconnecting" and attempt_id != reconnect_manager.current_attempt_id:
        return
    _stream_completed = True

    if _input_finishing:
        _complete_finished_input("stopped", "input_finished")
        return

    if not _stream_ready.is_set():
        _stream_error = AsrStreamError("closed_before_ready")
        _stream_ready.set()

    if not _has_verified_session and not _pipeline_stopping:
        if reconnect_manager.record_stream_failure(AsrStreamError("closed_before_ready"), attempt_id):
            manager.record_asr_error()
        return

    if _pipeline_stopping:
        if _detector is not None:
            remaining = _detector.flush_buffer()
            if remaining:
                manager.finalize_segment(remaining)
        logger.info("Transcription stream completed (pipeline stopping)")
        return

    if manager.session.status == "reconnecting":
        if _detector is not None:
            remaining = _detector.flush_reconnect_fragment()
            if remaining:
                manager.finalize_reconnect_fragment(remaining)
        _stream_error = AsrStreamError("stream_done")
        if reconnect_manager.record_stream_failure(_stream_error, attempt_id):
            manager.record_asr_error()
        reconnect_manager.signal_attempt_failed(_stream_error)
        return

    error = AsrStreamError("stream_done")
    if reconnect_manager.record_stream_failure(error, attempt_id):
        manager.record_asr_error()
    manager.set_asr_state("failed", "stream_done")
    reconnect_manager.on_connection_error(
        error
    )


def _on_transcription_error(exc: Exception, attempt_id: int, generation: int | None = None) -> None:
    global _stream_error, _stream_completed
    if _stream_completed or (generation is not None and generation != _pipeline_generation):
        return
    if _pipeline_stopping and not _input_finishing:
        return
    if manager.session.status == "reconnecting" and attempt_id != reconnect_manager.current_attempt_id:
        return
    _stream_completed = True
    if reconnect_manager.record_stream_failure(exc, attempt_id):
        manager.record_asr_error()
    if not _stream_ready.is_set():
        _stream_error = exc
        _stream_ready.set()

    if not _has_verified_session:
        return

    reason = safe_asr_reason(exc)
    if _input_finishing:
        _complete_finished_input("failed", reason)
        return
    manager.set_asr_state("failed", reason)

    if manager.session.status == "reconnecting":
        _stream_error = exc
        reconnect_manager.signal_attempt_failed(exc)
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
ws.finish_input = _finish_input
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
    result = run_recovery(settings)
    if result.notice is not None:
        manager.recovery_notice = result.notice
        if result.recovery_state is not None:
            manager.recovery_state = result.recovery_state
            logger.warning(
                "Recovery failed for session %s: %s",
                result.notice.recovered_session_id,
                result.notice.error,
            )
        else:
            logger.info(
                "Recovered session %s → %s",
                result.notice.recovered_session_id,
                result.notice.export_path,
            )

    journal = SessionJournal(session_id=manager.session.id, config=settings)
    manager.set_journal(journal)

    poller.start()
    await tts_dispatcher.start()
    if settings.tts_enabled and not settings.tts_voice_id:
        logger.warning(
            "TTS is enabled but MISTRAL_TTS_VOICE_ID is not set; default VOICE_MAP values may be invalid for your account. "
            "Set MISTRAL_TTS_VOICE_ID to a saved voice UUID to avoid TTS failures."
        )
    logger.info("CaptionBridge started on %s:%s", settings.host, settings.port)
    yield
    poller.stop()
    await tts_dispatcher.stop()
    await _stop_pipeline()
    logger.info("CaptionBridge shut down")


app = FastAPI(title="CaptionBridge", lifespan=lifespan)

BROWSER_ASSET_PATHS = frozenset({"/", "/app.js", "/pcm-player.js", "/audio-devices.js", "/styles.css"})


@app.middleware("http")
async def disable_browser_asset_cache(request, call_next):
    response = await call_next(request)
    if request.url.path in BROWSER_ASSET_PATHS:
        response.headers["Cache-Control"] = "no-store"
    return response


# WebSocket route MUST be registered before the catch-all static mount
app.add_api_websocket_route("/ws", ws.websocket_endpoint)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Content-free liveness endpoint for local lifecycle checks."""
    return {"service": "caption-bridge", "status": "ok"}


@app.get("/version")
async def version() -> dict[str, object]:
    """Content-free package and checkout identity."""
    return await asyncio.to_thread(runtime_identity)

@app.get("/favicon.ico", include_in_schema=False, status_code=204)
async def favicon() -> None:
    """Suppress harmless browser favicon 404 noise without external assets."""
    return None



# Static files — catch-all, must be last
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
