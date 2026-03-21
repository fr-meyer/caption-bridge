"""Mistral realtime transcription client."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable

from mistralai import Mistral
from mistralai.models import (
    AudioFormat,
    RealtimeTranscriptionError,
    RealtimeTranscriptionSessionCreated,
    TranscriptionStreamDone,
    TranscriptionStreamTextDelta,
)

try:
    from mistralai.extra.realtime import UnknownRealtimeEvent
except ImportError:  # pragma: no cover
    UnknownRealtimeEvent = None  # type: ignore[assignment,misc]

from app.config import AppConfig

logger = logging.getLogger(__name__)


async def transcribe(
    audio_stream: AsyncIterator[bytes],
    config: AppConfig,
    on_delta: Callable[[str], None],
    on_done: Callable[[], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> None:
    """Stream audio to Mistral realtime transcription and forward events."""
    client_kwargs: dict = {"api_key": config.mistral_api_key}
    if config.realtime_base_url is not None:
        client_kwargs["server_url"] = config.realtime_base_url

    try:
        async with Mistral(**client_kwargs) as client:
            audio_format = AudioFormat(
                encoding="pcm_s16le",
                sample_rate=config.audio_sample_rate,
            )

            events = client.audio.realtime.transcribe_stream(
                audio_stream=audio_stream,
                model=config.transcribe_model,
                audio_format=audio_format,
                target_streaming_delay_ms=config.target_streaming_delay_ms,
            )

            async for event in events:
                if isinstance(event, RealtimeTranscriptionSessionCreated):
                    logger.info("Transcription session established")
                elif isinstance(event, TranscriptionStreamTextDelta):
                    on_delta(event.text)
                elif isinstance(event, TranscriptionStreamDone):
                    logger.info("Transcription stream done")
                    if on_done is not None:
                        on_done()
                    break
                elif isinstance(event, RealtimeTranscriptionError):
                    logger.error("Transcription error: %s", event)
                    if on_error is not None:
                        on_error(event)
                    break
                elif UnknownRealtimeEvent is not None and isinstance(
                    event, UnknownRealtimeEvent
                ):
                    logger.debug("Unknown realtime event: %s", event)
                else:
                    logger.debug("Unhandled event type: %s", type(event).__name__)

    except Exception as exc:
        logger.exception("Transcription failed")
        if on_error is not None:
            on_error(exc)
