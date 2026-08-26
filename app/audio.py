"""Audio capture from microphone."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable

import sounddevice as sd

logger = logging.getLogger(__name__)


class AudioCapture:
    """Captures PCM audio from the default microphone via sounddevice."""

    def __init__(
        self,
        sample_rate: int,
        loop: asyncio.AbstractEventLoop,
        max_queue_chunks: int = 50,
        metrics_callback: Callable[[int, int], None] | None = None,
        onset_callback: Callable[[bytes], None] | None = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._loop = loop
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(
            maxsize=max_queue_chunks
        )
        self._stream: sd.RawInputStream | None = None
        self._stopped = False
        self._dropped_chunks = 0
        self._metrics_callback = metrics_callback
        self._onset_callback = onset_callback

    def _report_metrics(self, dropped: int) -> None:
        if self._metrics_callback is None:
            return
        try:
            self._metrics_callback(self._queue.qsize(), dropped)
        except Exception as exc:
            logger.warning(
                "Audio metrics callback failed: error_type=%s", type(exc).__name__
            )

    def _enqueue_chunk(self, chunk: bytes) -> None:
        if self._stopped:
            return
        dropped = 0
        if self._queue.full():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                pass
            self._dropped_chunks += 1
            dropped = 1
            if self._dropped_chunks == 1 or self._dropped_chunks % 100 == 0:
                logger.warning(
                    "Audio queue pressure: dropped_chunks=%d max_chunks=%d",
                    self._dropped_chunks,
                    self._queue.maxsize,
                )
        self._queue.put_nowait(chunk)
        if self._onset_callback is not None:
            try:
                self._onset_callback(chunk)
            except Exception as exc:
                logger.warning(
                    "Audio onset callback failed: error_type=%s",
                    type(exc).__name__,
                )
        self._report_metrics(dropped)

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
        self._loop.call_soon_threadsafe(self._enqueue_chunk, chunk)

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
            self._queue.task_done()
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
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

        self._queue.put_nowait(None)
