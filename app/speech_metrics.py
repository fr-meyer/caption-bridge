"""Bounded content-free browser startup/underrun distributions.

Server request-to-inbound-chunk ACK uses only Python's monotonic clock. Browser
buffer and startup durations use only the browser clock and include queue wait.
Neither is a physical speaker-onset measurement.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.latency import DISTRIBUTION_KEYS, summarize_samples

MODES = ("buffered", "streaming")
DURATIONS = ("first_chunk_to_playback_ms", "initial_buffer_ms")
FAILURE_REASONS = frozenset({"buffer_limit", "missing_chunk", "invalid_pcm", "stream_timeout", "playback_failure"})


def _int(value: object, maximum: int = 3_600_000) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= maximum


@dataclass
class SpeechPlaybackMetrics:
    request_to_chunk: list[int] = field(default_factory=list)
    modes: dict = field(default_factory=lambda: {
        mode: {**{key: [] for key in DURATIONS}, "clips": 0, "underruns": 0, "gap_ms": 0}
        for mode in MODES
    })
    failures: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FAILURE_REASONS, 0))

    @staticmethod
    def _append(values: list[int], value: int) -> None:
        values.append(value)
        del values[:-2048]

    def observe_request_to_chunk(self, seconds: float) -> None:
        self._append(self.request_to_chunk, max(0, min(3_600_000, round(seconds * 1000))))

    def observe_failure(self, reason: str) -> None:
        if reason in self.failures:
            self.failures[reason] += 1

    def observe_browser(self, msg: dict) -> bool:
        mode = msg.get("mode")
        if mode not in MODES or not all(_int(msg.get(key)) for key in DURATIONS):
            return False
        if not _int(msg.get("underruns"), 512) or not _int(msg.get("gap_ms")):
            return False
        bucket = self.modes[mode]
        for key in DURATIONS:
            self._append(bucket[key], msg[key])
        bucket["clips"] += 1
        bucket["underruns"] += msg["underruns"]
        bucket["gap_ms"] += msg["gap_ms"]
        return True

    def snapshot(self) -> dict:
        return {
            "request_to_first_browser_chunk": summarize_samples(self.request_to_chunk),
            "modes": {mode: {
                **{key: summarize_samples(bucket[key]) for key in DURATIONS},
                **{key: bucket[key] for key in ("clips", "underruns", "gap_ms")},
            } for mode, bucket in self.modes.items()},
            "failures": self.failures.copy(),
        }


def validate_speech_snapshot(value: object) -> bool:
    def distribution(item: object) -> bool:
        return isinstance(item, dict) and set(item) == set(DISTRIBUTION_KEYS) and all(
            isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in item.values()
        )
    if not isinstance(value, dict) or set(value) != {"request_to_first_browser_chunk", "modes", "failures"}:
        return False
    if not distribution(value["request_to_first_browser_chunk"]):
        return False
    modes, failures = value["modes"], value["failures"]
    if not isinstance(modes, dict) or set(modes) != set(MODES):
        return False
    if not isinstance(failures, dict) or set(failures) != FAILURE_REASONS:
        return False
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in failures.values()):
        return False
    for bucket in modes.values():
        if not isinstance(bucket, dict) or set(bucket) != set(DURATIONS) | {"clips", "underruns", "gap_ms"}:
            return False
        if not all(distribution(bucket[key]) for key in DURATIONS):
            return False
        if not all(isinstance(bucket[key], int) and not isinstance(bucket[key], bool) and bucket[key] >= 0
                   for key in ("clips", "underruns", "gap_ms")):
            return False
    return True
