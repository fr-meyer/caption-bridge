"""Private inherited-pipe PCM protocol, never a trust or closure attestation.

Frames are <=496 bytes (below POSIX's minimum PIPE_BUF). Payload is PCM16 LE,
interleaved native-rate mono/stereo. No payload is logged or persisted here.
"""
from __future__ import annotations

import struct
import sys

MAGIC = b"CBPCM001"
HEADER = struct.Struct("!8s16sQIHHII")
MAX_PAYLOAD = 448
MAX_PACKET = HEADER.size + MAX_PAYLOAD
END = 1
ASR_RATE = 16000


class PcmProtocolError(RuntimeError):
    def __init__(self, reason="native_pcm_invalid"):
        super().__init__(reason)


class PcmDecoder:
    """Incremental decoder with strict epoch, sequence, format and duration bounds."""

    def __init__(self, epoch: bytes, milliseconds: int):
        if type(epoch) is not bytes or len(epoch) != 16 or epoch == bytes(16):
            raise ValueError("native_pcm_epoch")
        if type(milliseconds) is not int or not 1 <= milliseconds <= 2000:
            raise ValueError("native_pcm_duration")
        self.epoch = epoch
        self.milliseconds = milliseconds
        self.pending = bytearray()
        self.sequence = 0
        self.format: tuple[int, int] | None = None
        self.frames = 0
        self.ended = False

    def feed(self, data: bytes) -> list[bytes]:
        # Caller reads at most four packets per event-loop turn; no giant input copy.
        if type(data) is not bytes or len(data) > 4 * MAX_PACKET:
            raise PcmProtocolError()
        if self.ended and data:
            raise PcmProtocolError("native_pcm_after_end")
        self.pending.extend(data)
        chunks = []
        while len(self.pending) >= HEADER.size:
            magic, epoch, sequence, rate, channels, flags, frames, size = HEADER.unpack_from(self.pending)
            if (magic != MAGIC or epoch != self.epoch or sequence != self.sequence
                    or not 8000 <= rate <= 192000 or channels not in (1, 2)
                    or flags not in (0, END) or size > MAX_PAYLOAD
                    or (flags == END and (size or frames))
                    or (flags == 0 and (not frames or size != frames * channels * 2))):
                raise PcmProtocolError()
            if self.format is None:
                self.format = (rate, channels)
            if self.format != (rate, channels):
                raise PcmProtocolError("native_pcm_format_changed")
            if len(self.pending) < HEADER.size + size:
                break
            self.frames += frames
            if self.frames > rate * self.milliseconds // 1000:
                raise PcmProtocolError("native_pcm_duration_exceeded")
            packet = bytes(self.pending[HEADER.size:HEADER.size + size])
            del self.pending[:HEADER.size + size]
            self.sequence += 1
            if flags == END:
                self.ended = True
                if self.pending:
                    raise PcmProtocolError("native_pcm_after_end")
                break
            chunks.append(packet)
        if len(self.pending) >= MAX_PACKET:
            raise PcmProtocolError()
        return chunks

    def eof(self) -> None:
        if not self.ended or self.pending:
            raise PcmProtocolError("native_pcm_truncated_hold")

    def clear(self) -> None:
        # Python bytes already handed to ASR cannot be securely erased. No retention
        # or secure-erasure claim is made; discard all references on stop/failure.
        self.pending.clear()


class AsrPcmConverter:
    """Per-epoch stateful mono/16 kHz conversion, not a device-rate mutation.

    Python 3.13 removed audioop: conversion fails closed on that runtime rather
    than silently supplying wrong-rate PCM. No optional install or fallback.
    """

    def __init__(self, output_rate: int):
        if type(output_rate) is not int or output_rate != ASR_RATE or sys.byteorder != "little":
            raise ValueError("native_pcm_asr_contract")
        self.rate = output_rate
        self.format = None
        self.state = None
        self.audioop = None

    def convert(self, pcm: bytes, native_format: tuple[int, int]) -> bytes:
        rate, channels = native_format
        if channels not in (1, 2) or not 8000 <= rate <= 192000 or len(pcm) % (2 * channels):
            raise PcmProtocolError()
        if self.format is not None and self.format != native_format:
            raise PcmProtocolError("native_pcm_format_changed")
        self.format = native_format
        if rate == self.rate and channels == 1:
            return pcm
        if self.audioop is None:
            try:
                # CPython stdlib on 3.11/3.12; the exactly locked PSF-licensed
                # audioop-lts port supplies the same API on 3.13+. Preserve
                # tomono/ratecv rounding and persistent chunk state, not new DSP.
                import audioop
            except ImportError:
                raise PcmProtocolError("native_pcm_conversion_unavailable") from None
            self.audioop = audioop
        if channels == 2:
            pcm = self.audioop.tomono(pcm, 2, 0.5, 0.5)
        if rate != self.rate:
            pcm, self.state = self.audioop.ratecv(pcm, 2, 1, rate, self.rate, self.state)
        return pcm

    def clear(self):
        self.state = None
