"""Mistral realtime transcription with verified settings and terminal text."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from mistralai.client import Mistral
from mistralai.client.models import (
    AudioFormat,
    RealtimeTranscriptionError,
    RealtimeTranscriptionSessionCreated,
    RealtimeTranscriptionSessionUpdated,
    TranscriptionStreamDone,
    TranscriptionStreamTextDelta,
)

try:
    from mistralai.extra.realtime import UnknownRealtimeEvent
except ImportError:  # pragma: no cover
    UnknownRealtimeEvent = None  # type: ignore[assignment,misc]

from app.asr_diagnostics import AsrDiagnostics
from app.config import AppConfig
from app.pipeline_diagnostics import AsrProtocolDiagnostics
from app.reconnect import classify_reconnect_failure

logger = logging.getLogger(__name__)
_pending_connection_cleanup: set[asyncio.Task] = set()


class AsrStreamError(RuntimeError):
    """A safe reason code; provider details are never copied into the message."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            "Realtime transcription provider error"
            if reason == "provider_error"
            else "Realtime transcription failed"
        )
        self.reason = reason


async def _dispose_pending_connection(task: asyncio.Task) -> None:
    # SDK connect does not close its pre-return socket on CancelledError.
    try:
        connection = await task
        await connection.close()
    except Exception:
        logger.debug("ASR connection cleanup failed")


def _safe_count(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2**63 - 1
        else None
    )


def _preserve_cancellation() -> None:
    # SDK events() catches CancelledError and returns EOF. Stop must remain a
    # cancellation even when the SDK consumes that exception.
    task = asyncio.current_task()
    if task is not None and task.cancelling():
        raise asyncio.CancelledError


async def transcribe(
    audio_stream: AsyncIterator[bytes],
    config: AppConfig,
    on_delta: Callable[[str], None],
    on_done: Callable[[], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    on_session_created: Callable[[], None] | None = None,
    on_sent: Callable[[int], None] | None = None,
    on_event: Callable[[str, int], None] | None = None,
    on_final_text: Callable[[str], None] | None = None,
    on_protocol: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Wait for a verified Updated ACK, then supervise audio and text streams.

    Final-only text uses a separate callback. Provider delta counters describe
    actual delta events; terminal aggregate text never rewrites delivered deltas.
    """
    protocol = AsrProtocolDiagnostics(
        requested_sample_rate=config.audio_sample_rate,
        requested_pcm_s16le=True,
        requested_target_delay_ms=config.target_streaming_delay_ms,
    )

    def report_protocol() -> None:
        if on_protocol is not None:
            on_protocol(protocol.snapshot())

    def event_kind(event) -> str:
        if isinstance(event, RealtimeTranscriptionSessionCreated):
            return "session_created"
        if isinstance(event, RealtimeTranscriptionSessionUpdated):
            return "session_updated"
        if isinstance(event, TranscriptionStreamTextDelta):
            return "text_delta"
        if isinstance(event, TranscriptionStreamDone):
            return "done"
        if isinstance(event, RealtimeTranscriptionError):
            return "provider_error"
        if UnknownRealtimeEvent is not None and isinstance(event, UnknownRealtimeEvent):
            return "unknown"
        return "other"

    def observe_event(event) -> str:
        kind = event_kind(event)
        if on_event is not None:
            on_event(kind, len(event.text) if kind == "text_delta" else 0)
        return kind

    def observe_done(event) -> None:
        protocol.done_received = True
        protocol.done_text_characters = len(event.text)
        protocol.done_text_handling = "empty" if not event.text else "not_admitted"
        protocol.prompt_audio_seconds = _safe_count(
            getattr(event.usage, "prompt_audio_seconds", None)
        )
        report_protocol()

    client_kwargs: dict = {"api_key": config.mistral_api_key}
    if config.realtime_base_url is not None:
        client_kwargs["server_url"] = config.realtime_base_url
    connect_task: asyncio.Task | None = None
    connection = None
    tasks: list[asyncio.Task] = []
    error: Exception | None = None
    received_done = False
    nonempty_delta_delivered = False
    report_protocol()
    try:
        async with Mistral(**client_kwargs) as client:
            connect_task = asyncio.create_task(
                client.audio.realtime.connect(
                    model=config.transcribe_model,
                    audio_format=AudioFormat(
                        encoding="pcm_s16le", sample_rate=config.audio_sample_rate
                    ),
                    target_streaming_delay_ms=config.target_streaming_delay_ms,
                    timeout_ms=config.asr_initial_timeout_ms,
                )
            )
            connection = await asyncio.shield(connect_task)
            async with connection:
                events = connection.__aiter__()
                # connect() verifies Created and sends Update. It does not wait
                # for the server's Updated ACK; audio admission waits here.
                async for event in events:
                    _preserve_cancellation()
                    kind = observe_event(event)
                    if kind == "provider_error":
                        raise AsrStreamError("provider_error")
                    if kind == "done":
                        observe_done(event)
                        raise AsrStreamError("closed_before_ready")
                    if kind != "session_updated":
                        continue
                    session = event.session
                    protocol.session_updated_received = True
                    protocol.ack_model_matches = session.model == config.transcribe_model
                    protocol.ack_pcm_s16le = session.audio_format.encoding == "pcm_s16le"
                    protocol.ack_sample_rate = _safe_count(session.audio_format.sample_rate)
                    if protocol.ack_sample_rate == 0:
                        protocol.ack_sample_rate = None
                    protocol.ack_target_delay_ms = _safe_count(session.target_streaming_delay_ms)
                    mandatory_match = (
                        protocol.ack_model_matches
                        and protocol.ack_pcm_s16le
                        and protocol.ack_sample_rate == config.audio_sample_rate
                    )
                    delay = session.target_streaming_delay_ms
                    # OptionalNullable/UNSET echo remains unknown. An explicit
                    # numeric value must match; no effective value is invented.
                    supplied_delay = isinstance(delay, int) and not isinstance(delay, bool)
                    delay_match = not supplied_delay or delay == config.target_streaming_delay_ms
                    protocol.settings_verified = bool(mandatory_match and delay_match)
                    protocol.delay_verified = bool(protocol.settings_verified and supplied_delay)
                    report_protocol()
                    if not protocol.settings_verified:
                        raise AsrStreamError("settings_mismatch")
                    break
                else:
                    _preserve_cancellation()
                    raise AsrStreamError("closed_before_ready")
                _preserve_cancellation()
                if on_session_created is not None:
                    on_session_created()

                async def send_audio() -> None:
                    try:
                        async for chunk in audio_stream:
                            if not isinstance(chunk, bytes) or len(chunk) % 2:
                                raise AsrStreamError("invalid_audio")
                            await connection.send_audio(chunk)
                            if on_sent is not None:
                                on_sent(len(chunk))
                        await connection.flush_audio()
                        protocol.input_flushed = True
                        report_protocol()
                        await connection.end_audio()
                        protocol.input_ended = True
                        report_protocol()
                    except AsrStreamError:
                        raise
                    except Exception as exc:
                        raise AsrStreamError("send_failed") from exc

                async def receive_events() -> None:
                    nonlocal received_done, nonempty_delta_delivered
                    async for event in events:
                        _preserve_cancellation()
                        kind = observe_event(event)
                        if kind == "text_delta":
                            on_delta(event.text)
                            nonempty_delta_delivered |= bool(event.text)
                        elif kind == "provider_error":
                            raise AsrStreamError("provider_error")
                        elif kind == "done":
                            observe_done(event)
                            if event.text and nonempty_delta_delivered:
                                protocol.done_text_handling = "deltas_preserved"
                            elif event.text and on_final_text is not None:
                                on_final_text(event.text)
                                protocol.done_text_handling = "final_only_admitted"
                            report_protocol()
                            received_done = True
                            return
                    _preserve_cancellation()
                    raise AsrStreamError("closed_before_done")

                sender = asyncio.create_task(send_audio())
                receiver = asyncio.create_task(receive_events())
                tasks = [sender, receiver]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                if sender in done:
                    await sender
                await receiver
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _preserve_cancellation()
        error = exc
        if connection is None:
            cause: BaseException | None = exc
            timed_out = False
            for _ in range(8):
                if cause is None:
                    break
                timed_out |= isinstance(cause, TimeoutError)
                cause = cause.__cause__
            error = AsrStreamError("initial_timeout" if timed_out else "transport_error")
            error.__cause__ = exc
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            if error is None:
                error = next((value for value in results if isinstance(value, Exception)), None)
        if connect_task is not None and connection is None:
            cleanup = asyncio.create_task(_dispose_pending_connection(connect_task))
            _pending_connection_cleanup.add(cleanup)
            cleanup.add_done_callback(_pending_connection_cleanup.discard)
    # A receiver-first result must not mask a sender failure during close.
    # Successful Done is announced only after both task outcomes are settled.
    _preserve_cancellation()
    if error is not None:
        if on_error is not None:
            on_error(error)
        else:
            AsrDiagnostics().failure(error, attempt_id=0, info=classify_reconnect_failure(error))
    elif received_done and on_done is not None:
        on_done()
