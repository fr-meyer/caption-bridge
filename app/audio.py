"""Audio capture from microphone."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

import sounddevice as sd

logger = logging.getLogger(__name__)


class AudioCapture:
    """Captures PCM audio from the default microphone via sounddevice."""

    def __init__(self, sample_rate: int, loop: asyncio.AbstractEventLoop) -> None:
        self._sample_rate = sample_rate
        self._loop = loop
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._stream: sd.RawInputStream | None = None
        self._stopped = False

    def _audio_callback(
        self,
        indata: bytes,
        frames: int,  # noqa: ARG002
        time_info: dict,  # noqa: ARG002
        status: sd.CallbackFlags,
    ) -> None:
        """PortAudio callback — runs on the C audio thread."""
        if status:
            logger.warning("sounddevice status: %s", status)
        chunk = bytes(indata)
        self._loop.call_soon_threadsafe(self._queue.put_nowait, chunk)

    def start(self) -> None:
        blocksize = self._sample_rate // 10  # ~100 ms chunks
        self._stream = sd.RawInputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            callback=self._audio_callback,
            blocksize=blocksize,
        )
        self._stream.start()
        logger.info(
            "AudioCapture started (rate=%d, blocksize=%d)",
            self._sample_rate,
            blocksize,
        )

    async def stream(self) -> AsyncGenerator[bytes, None]:
        while True:
            chunk = await self._queue.get()
            if chunk is None:
                break
            yield chunk

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            logger.info("AudioCapture stopped")

        # Drain buffered audio chunks before enqueuing the sentinel so
        # stream() is guaranteed to see it.
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        self._queue.put_nowait(None)
