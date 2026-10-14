"""Inert, bounded numeric evidence for an explicitly selected public PCM fixture.

No application, SDK, device, environment, socket or filesystem is accessed here.
Source and browser offsets stay in separate monotonic clock domains.
"""

from __future__ import annotations

import asyncio
import base64
import math
import time
from types import SimpleNamespace

MAX_CHUNKS = 128
RATE = 24000
CHUNK_SAMPLES = 2400
MAX_SAMPLES = MAX_CHUNKS * CHUNK_SAMPLES


def number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("invalid_timing_value")
    if not math.isfinite(value) or not 0 <= value <= 60000:
        raise ValueError("invalid_timing_value")
    return float(value)


class FixtureDelivery:
    """Single-use anchored delivery; caller supplies already-prepared public PCM."""

    def __init__(self, pcm: bytes, *, clock=time.monotonic, sleep=asyncio.sleep):
        if not isinstance(pcm, bytes) or not pcm or len(pcm) % 4:
            raise ValueError("fixture_shape_required")
        if len(pcm) // 4 > MAX_SAMPLES:
            raise ValueError("fixture_limit")
        self._pcm = pcm
        self.clock, self.sleep = clock, sleep
        self.rows = []
        self.complete = False
        self._started = False
        self._closed = False
        self._iterator = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        if self._iterator is not None:
            await self._iterator.aclose()
        self._pcm = b""
        self._closed = True
        return False

    def __aiter__(self):
        if self._started or self._closed:
            raise ValueError("fixture_single_use")
        self._started = True
        self._iterator = self._chunks()
        return self._iterator

    async def _chunks(self):
        anchor = self.clock()
        deadline = anchor
        size = CHUNK_SAMPLES * 4
        try:
            for offset in range(0, len(self._pcm), size):
                data = base64.b64encode(self._pcm[offset:offset + size]).decode("ascii")
                count = min(size, len(self._pcm) - offset) // 4
                yielded = self.clock()
                row = {
                    "chunk_index": len(self.rows), "samples": count,
                    "nominal_offset_ms": number(offset / 4 / RATE * 1000),
                    "yield_offset_ms": number((yielded - anchor) * 1000),
                    "deadline_lateness_ms": number(max(0, yielded - deadline) * 1000),
                    "consumer_work_ms": None,
                }
                self.rows.append(row)
                yield SimpleNamespace(audio_data=data)
                row["consumer_work_ms"] = number((self.clock() - yielded) * 1000)
                deadline += count / RATE
                await self.sleep(max(0.0, deadline - self.clock()))
            self.complete = True
        finally:
            self._pcm = b""  # Completion/cancellation retains numeric evidence only.
            self._iterator = None

    def report(self):
        return {
            "schema_version": 1, "clock_domain": "source_monotonic_offsets",
            "completed": self.complete, "chunks": [dict(row) for row in self.rows],
        }


_SOURCE_KEYS = {"chunk_index", "samples", "nominal_offset_ms", "yield_offset_ms",
                "deadline_lateness_ms", "consumer_work_ms"}
_BROWSER_KEYS = {"schema_version", "clock_domain", "audio_clock_domain", "completed",
                 "rejected", "chunks", "schedules", "ready_to_first_schedule_ms"}
_CHUNK_KEYS = {"chunk_index", "receive_offset_ms", "receive_processing_ms"}
_SCHEDULE_KEYS = {"schedule_index", "covered_through_chunk_index", "submitted_offset_ms",
                  "scheduled_ahead_ms", "schedule_gap_ms", "duration_ms"}


def _rows(rows, keys, index_key):
    if not isinstance(rows, list) or not 0 < len(rows) <= MAX_CHUNKS:
        raise ValueError("invalid_timing_trace")
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.keys() != keys or row[index_key] != index:
            raise ValueError("invalid_timing_trace")
        if type(row[index_key]) is not int:
            raise ValueError("invalid_timing_trace")


def classify(source, browser, *, tolerance_ms=5):
    """Evidence flags, never a causal claim or source/browser clock subtraction."""
    tolerance = number(tolerance_ms)
    if not isinstance(source, dict) or source.keys() != {
        "schema_version", "clock_domain", "completed", "chunks"
    }:
        raise ValueError("invalid_source_trace")
    if not isinstance(browser, dict) or browser.keys() != _BROWSER_KEYS:
        raise ValueError("invalid_browser_trace")
    if (type(source["schema_version"]) is not int or source["schema_version"] != 1
            or type(browser["schema_version"]) is not int or browser["schema_version"] != 1
            or source["clock_domain"] != "source_monotonic_offsets"
            or browser["clock_domain"] != "browser_monotonic_offsets"
            or browser["audio_clock_domain"] != "audio_schedule_durations"
            or type(source["completed"]) is not bool or type(browser["completed"]) is not bool
            or type(browser["rejected"]) is not int or browser["rejected"] < 0):
        raise ValueError("invalid_clock_domain")
    _rows(source["chunks"], _SOURCE_KEYS, "chunk_index")
    _rows(browser["chunks"], _CHUNK_KEYS, "chunk_index")
    if len(source["chunks"]) != len(browser["chunks"]):
        raise ValueError("unmatched_chunk_trace")
    _rows(browser["schedules"], _SCHEDULE_KEYS, "schedule_index")
    last_yield = last_receive = -1.0
    samples_before = 0
    lateness, work, processing, interval_excess = [], [], [], []
    for s, b in zip(source["chunks"], browser["chunks"], strict=True):
        if type(s["samples"]) is not int or not 0 < s["samples"] <= CHUNK_SAMPLES:
            raise ValueError("invalid_sample_count")
        nominal = number(s["nominal_offset_ms"])
        yielded, received = number(s["yield_offset_ms"]), number(b["receive_offset_ms"])
        if abs(nominal - samples_before / RATE * 1000) > .01:
            raise ValueError("invalid_nominal_deadline")
        if nominal > yielded + .001 or yielded < last_yield or received < last_receive:
            raise ValueError("nonmonotonic_trace")
        late = number(s["deadline_lateness_ms"])
        if abs(late - max(0, yielded - nominal)) > .01:
            raise ValueError("invalid_deadline_lateness")
        lateness.append(late)
        processing.append(number(b["receive_processing_ms"]))
        if s["consumer_work_ms"] is not None:
            work.append(number(s["consumer_work_ms"]))
        if last_yield >= 0:
            # Compare within-domain intervals; never subtract absolute clock origins.
            interval_excess.append(max(0, (received - last_receive) - (yielded - last_yield)))
        last_yield, last_receive = yielded, received
        samples_before += s["samples"]
    gaps = []
    for row in browser["schedules"]:
        covered = row["covered_through_chunk_index"]
        if type(covered) is not int or not 0 <= covered < len(source["chunks"]):
            raise ValueError("invalid_schedule_coverage")
        for key in _SCHEDULE_KEYS - {"schedule_index", "covered_through_chunk_index"}:
            number(row[key])
        gaps.append(row["schedule_gap_ms"])
    ready = browser["ready_to_first_schedule_ms"]
    ready = number(ready) if ready is not None else None
    complete = (source["completed"] and browser["completed"] and not browser["rejected"]
                and len(work) == len(source["chunks"]) and ready is not None)
    duration = sum(row["samples"] for row in source["chunks"]) / RATE * 1000
    if complete and abs(sum(row["duration_ms"] for row in browser["schedules"]) - duration) > .01:
        raise ValueError("schedule_duration_mismatch")
    evidence = {
        "source_deadline_late": max(lateness) > tolerance,
        "browser_receive_work_slow": max(processing) > tolerance,
        "receive_interval_excess": max(interval_excess, default=0) > tolerance,
        "ready_to_schedule_hold": ready is not None and ready > tolerance,
    }
    return {
        "schema_version": 1, "complete": complete, "chunk_count": len(lateness),
        "evidence": evidence, "source_max_lateness_ms": round(max(lateness), 6),
        "source_max_consumer_work_ms": round(max(work, default=0), 6),
        "browser_max_receive_work_ms": round(max(processing), 6),
        "max_receive_interval_excess_ms": round(max(interval_excess, default=0), 6),
        "ready_to_first_schedule_ms": ready, "total_schedule_gap_ms": round(sum(gaps), 6),
        "cause_assigned": False, "audible_onset_measured": False,
        "cross_clock_origins_subtracted": False,
        "interval_comparison_limit": "Clock rate/precision may differ; excess includes transit and dispatch.",
    }
