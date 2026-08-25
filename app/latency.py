"""Content-free end-to-end latency aggregates.

Durations use one server-side monotonic clock. Render acknowledgements are
measured from translation completion to inbound ack on that same clock.
Playback acknowledgements consume their start stamp once. JavaScript clocks
are never compared with Python clocks. Caption text, audio, prompts, and
provider bodies are never stored here.
"""

from __future__ import annotations

import math
import struct
import time
from typing import Final

LATENCY_DIMENSIONS: Final[tuple[str, ...]] = (
    "speech_onset_to_first_partial",
    "speech_onset_to_final_source",
    "finalization_to_translation_dispatch",
    "translation_dispatch_to_completion",
    "translation_completion_to_render_ack",
    "tts_request_to_synthesis_start",
    "tts_synthesis_start_to_first_audio",
    "tts_request_to_playback_start",
    "tts_queue_wait",
    "tts_playback_start_to_completion",
)
LATENCY_CLASSES: Final[tuple[str, ...]] = (
    "ordinary",
    "repaired",
    "reconnect",
    "browser_replacement",
)
DISTRIBUTION_KEYS: Final[tuple[str, ...]] = (
    "count",
    "median_ms",
    "p90_ms",
    "p95_ms",
    "p99_ms",
    "max_ms",
    "outlier_count",
)
_MAX_SAMPLES = 2048
_MAX_SEQUENCES = 256
_OUTLIER_MS = 30_000
_SAFE_SEQ_MAX = 1_000_000_000
_CAPTION_STAMPS: Final[tuple[str, ...]] = (
    "finalized",
    "translate_dispatch",
    "translate_complete",
    "render_dispatch",
)


def empty_distribution() -> dict[str, int]:
    return {key: 0 for key in DISTRIBUTION_KEYS}


def empty_latency_snapshot() -> dict[str, object]:
    return {
        "dimensions": {
            name: {cls: empty_distribution() for cls in LATENCY_CLASSES}
            for name in LATENCY_DIMENSIONS
        },
        "speech_onset": {"detections": 0, "false_start_resets": 0},
    }


def _percentile_nearest(sorted_values: list[int], fraction: float) -> int:
    if not sorted_values:
        return 0
    index = min(len(sorted_values) - 1, max(0, math.ceil(fraction * len(sorted_values)) - 1))
    return sorted_values[index]


def summarize_samples(samples: list[int]) -> dict[str, int]:
    if not samples:
        return empty_distribution()
    ordered = sorted(samples)
    return {
        "count": len(ordered),
        "median_ms": _percentile_nearest(ordered, 0.50),
        "p90_ms": _percentile_nearest(ordered, 0.90),
        "p95_ms": _percentile_nearest(ordered, 0.95),
        "p99_ms": _percentile_nearest(ordered, 0.99),
        "max_ms": ordered[-1],
        "outlier_count": sum(1 for value in ordered if value > _OUTLIER_MS),
    }


def validate_latency_snapshot(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"dimensions", "speech_onset"}:
        return False
    dimensions = value["dimensions"]
    onset = value["speech_onset"]
    if not isinstance(dimensions, dict) or set(dimensions) != set(LATENCY_DIMENSIONS):
        return False
    if not isinstance(onset, dict) or set(onset) != {"detections", "false_start_resets"}:
        return False
    if not all(isinstance(onset[key], int) and onset[key] >= 0 for key in onset):
        return False
    for name in LATENCY_DIMENSIONS:
        classes = dimensions[name]
        if not isinstance(classes, dict) or set(classes) != set(LATENCY_CLASSES):
            return False
        for cls in LATENCY_CLASSES:
            bucket = classes[cls]
            if not isinstance(bucket, dict) or set(bucket) != set(DISTRIBUTION_KEYS):
                return False
            if not all(isinstance(bucket[key], int) and bucket[key] >= 0 for key in DISTRIBUTION_KEYS):
                return False
    return True


class SpeechOnsetDetector:
    """Bounded local energy onset detector for int16 mono PCM.

    False positives: short noise bursts, keyboard taps, and door slams can
    cross the adaptive floor. False negatives: very quiet or far-field speech,
    and speech that begins while an utterance is already open, may be missed.
    """

    def __init__(
        self,
        *,
        loud_chunks: int = 2,
        quiet_chunks: int = 3,
        ratio: float = 3.5,
        min_floor: float = 0.01,
        ema: float = 0.95,
    ) -> None:
        self._loud_needed = loud_chunks
        self._quiet_needed = quiet_chunks
        self._ratio = ratio
        self._min_floor = min_floor
        self._ema = ema
        self._floor = min_floor
        self._loud_run = 0
        self._quiet_run = 0
        self._in_utterance = False
        self.detections = 0
        self.false_start_resets = 0
        self._awaiting_partial = False

    def reset(self) -> None:
        self._floor = self._min_floor
        self._loud_run = 0
        self._quiet_run = 0
        self._in_utterance = False
        self._awaiting_partial = False

    def note_partial_seen(self) -> None:
        self._awaiting_partial = False

    def note_false_start(self) -> None:
        if self._awaiting_partial:
            self.false_start_resets += 1
            self._awaiting_partial = False

    def observe_pcm16(self, chunk: bytes) -> bool:
        if len(chunk) < 2:
            return False
        count = len(chunk) // 2
        samples = struct.unpack("<" + "h" * count, chunk[: count * 2])
        mean_square = sum(sample * sample for sample in samples) / count
        rms = math.sqrt(mean_square) / 32768.0
        threshold = max(self._min_floor, self._floor * self._ratio)
        if rms < threshold:
            self._floor = (self._ema * self._floor) + ((1.0 - self._ema) * max(rms, self._min_floor))
            self._loud_run = 0
            if self._in_utterance:
                self._quiet_run += 1
                if self._quiet_run >= self._quiet_needed:
                    self._in_utterance = False
                    if self._awaiting_partial:
                        self.false_start_resets += 1
                        self._awaiting_partial = False
            return False
        self._quiet_run = 0
        self._loud_run += 1
        if self._in_utterance or self._loud_run < self._loud_needed:
            return False
        self._in_utterance = True
        self.detections += 1
        self._awaiting_partial = True
        return True


class LatencyTracker:
    """In-memory duration samples; only aggregates are persisted."""

    def __init__(self) -> None:
        self._samples: dict[str, dict[str, list[int]]] = {
            name: {cls: [] for cls in LATENCY_CLASSES} for name in LATENCY_DIMENSIONS
        }
        self._onset = SpeechOnsetDetector()
        self._onset_mono: float | None = None
        self._first_partial_seen = False
        self._stamps: dict[int, dict[str, float]] = {}
        self._classes: dict[int, str] = {}
        self._reconnect_period = False
        self._replacement_until = 0.0

    def reset(self) -> None:
        self.__init__()

    def mark_reconnect_period(self, active: bool) -> None:
        self._reconnect_period = active

    def mark_browser_replacement(self, hold_s: float = 15.0) -> None:
        self._replacement_until = time.monotonic() + max(0.0, hold_s)

    def _active_class(self, seq: int | None = None, *, repaired: bool = False, reconnect: bool = False) -> str:
        if time.monotonic() < self._replacement_until:
            return "browser_replacement"
        if repaired:
            return "repaired"
        if seq is not None and seq in self._classes:
            return self._classes[seq]
        if reconnect or self._reconnect_period:
            return "reconnect"
        return "ordinary"

    def _record(self, dimension: str, duration_s: float, class_name: str) -> None:
        if dimension not in self._samples or class_name not in self._samples[dimension]:
            return
        if duration_s < 0:
            return
        bucket = self._samples[dimension][class_name]
        bucket.append(int(round(duration_s * 1000)))
        if len(bucket) > _MAX_SAMPLES:
            del bucket[: len(bucket) - _MAX_SAMPLES]

    def _stamp(self, seq: int, key: str) -> None:
        stamps = self._stamps.setdefault(seq, {})
        if key not in stamps:
            stamps[key] = time.monotonic()
        self._evict_overflow()

    def _duration_since(self, seq: int, key: str) -> float | None:
        started = self._stamps.get(seq, {}).get(key)
        if started is None:
            return None
        return time.monotonic() - started

    def _consume(self, seq: int, key: str) -> float | None:
        stamps = self._stamps.get(seq)
        if not stamps or key not in stamps:
            return None
        started = stamps.pop(key)
        if not stamps:
            self._stamps.pop(seq, None)
        return time.monotonic() - started

    def _discard_stamps(self, seq: int, *keys: str) -> None:
        stamps = self._stamps.get(seq)
        if not stamps:
            return
        for key in keys:
            stamps.pop(key, None)
        if not stamps:
            self._stamps.pop(seq, None)

    def _drop_seq(self, seq: int) -> None:
        self._stamps.pop(seq, None)
        self._classes.pop(seq, None)

    def _evict_overflow(self) -> None:
        while len(self._stamps) > _MAX_SEQUENCES:
            self._drop_seq(next(iter(self._stamps)))
        while len(self._classes) > _MAX_SEQUENCES:
            self._drop_seq(next(iter(self._classes)))

    def observe_pcm16(self, chunk: bytes) -> bool:
        if not self._onset.observe_pcm16(chunk):
            return False
        self._onset_mono = time.monotonic()
        self._first_partial_seen = False
        return True

    def observe_first_partial(self) -> None:
        if self._first_partial_seen or self._onset_mono is None:
            return
        self._first_partial_seen = True
        self._onset.note_partial_seen()
        self._record(
            "speech_onset_to_first_partial",
            time.monotonic() - self._onset_mono,
            self._active_class(),
        )

    def observe_final_source(self, seq: int, *, reconnect: bool = False) -> None:
        if not _valid_seq(seq):
            return
        class_name = self._active_class(reconnect=reconnect)
        self._classes[seq] = class_name
        if self._onset_mono is not None:
            self._record(
                "speech_onset_to_final_source",
                time.monotonic() - self._onset_mono,
                class_name,
            )
            if not self._first_partial_seen:
                self._onset.note_false_start()
        self._onset_mono = None
        self._first_partial_seen = False
        self._stamp(seq, "finalized")
        self._evict_overflow()

    def observe_translation_dispatch(self, seq: int) -> None:
        if not _valid_seq(seq):
            return
        elapsed = self._duration_since(seq, "finalized")
        if elapsed is not None:
            self._record(
                "finalization_to_translation_dispatch",
                elapsed,
                self._active_class(seq),
            )
        self._stamp(seq, "translate_dispatch")

    def observe_translation_complete(self, seq: int, *, repaired: bool = False) -> None:
        if not _valid_seq(seq):
            return
        if repaired:
            self._classes[seq] = "repaired"
        elapsed = self._duration_since(seq, "translate_dispatch")
        if elapsed is not None:
            self._record(
                "translation_dispatch_to_completion",
                elapsed,
                self._active_class(seq, repaired=repaired),
            )
        self._stamp(seq, "translate_complete")

    def observe_render_dispatch(self, seq: int) -> None:
        if not _valid_seq(seq):
            return
        self._stamp(seq, "render_dispatch")

    def observe_render_ack(self, seq: int) -> None:
        if not _valid_seq(seq):
            return
        elapsed = self._consume(seq, "translate_complete")
        if elapsed is None:
            return
        self._record(
            "translation_completion_to_render_ack",
            elapsed,
            self._active_class(seq),
        )
        self._discard_stamps(seq, *_CAPTION_STAMPS)

    def observe_tts_request(self, seq: int) -> None:
        if not _valid_seq(seq):
            return
        self._stamp(seq, "tts_request")

    def observe_tts_queue_wait(self, seq: int, duration_s: float) -> None:
        if not _valid_seq(seq):
            return
        self._record(
            "tts_queue_wait",
            duration_s,
            self._active_class(seq),
        )

    def observe_tts_synth_start(self, seq: int) -> None:
        if not _valid_seq(seq):
            return
        elapsed = self._duration_since(seq, "tts_request")
        if elapsed is not None:
            self._record(
                "tts_request_to_synthesis_start",
                elapsed,
                self._active_class(seq),
            )
        self._stamp(seq, "tts_synth_start")

    def observe_tts_first_audio(self, seq: int) -> None:
        if not _valid_seq(seq):
            return
        if "tts_first_audio" in self._stamps.get(seq, {}):
            return
        elapsed = self._duration_since(seq, "tts_synth_start")
        if elapsed is not None:
            self._record(
                "tts_synthesis_start_to_first_audio",
                elapsed,
                self._active_class(seq),
            )
        self._stamp(seq, "tts_first_audio")

    def observe_tts_playback_start(self, seq: int) -> None:
        if not _valid_seq(seq):
            return
        if "tts_playback_start" in self._stamps.get(seq, {}):
            return
        elapsed = self._duration_since(seq, "tts_request")
        if elapsed is not None:
            self._record(
                "tts_request_to_playback_start",
                elapsed,
                self._active_class(seq),
            )
        self._stamp(seq, "tts_playback_start")

    def observe_tts_playback_complete(self, seq: int) -> None:
        if not _valid_seq(seq):
            return
        elapsed = self._consume(seq, "tts_playback_start")
        if elapsed is None:
            return
        self._record(
            "tts_playback_start_to_completion",
            elapsed,
            self._active_class(seq),
        )
        self._discard_stamps(
            seq,
            "tts_request",
            "tts_synth_start",
            "tts_first_audio",
            "tts_playback_start",
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "dimensions": {
                name: {
                    cls: summarize_samples(self._samples[name][cls])
                    for cls in LATENCY_CLASSES
                }
                for name in LATENCY_DIMENSIONS
            },
            "speech_onset": {
                "detections": self._onset.detections,
                "false_start_resets": self._onset.false_start_resets,
            },
        }


def _valid_seq(seq: object) -> bool:
    return isinstance(seq, int) and not isinstance(seq, bool) and 0 < seq < _SAFE_SEQ_MAX
