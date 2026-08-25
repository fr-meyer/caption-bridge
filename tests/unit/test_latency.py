"""Content-free latency aggregates and speech-onset behavior."""

from __future__ import annotations

import struct
import time

from app.latency import (
    LatencyTracker,
    SpeechOnsetDetector,
    empty_latency_snapshot,
    summarize_samples,
    validate_latency_snapshot,
)
from app.reliability import (
    ReliabilityTracker,
    load_history,
    validate_session_record,
    write_session_record,
)
from tests.unit.test_reliability import _record, _session


def _pcm(rms_level: float, samples: int = 1600) -> bytes:
    amplitude = max(0, min(32767, int(rms_level * 32767)))
    return struct.pack("<" + "h" * samples, *([amplitude] * samples))


def test_percentiles_and_outliers_are_content_free() -> None:
    summary = summarize_samples([10, 20, 30, 40, 50, 40_000])
    assert summary["count"] == 6
    assert summary["median_ms"] == 30
    assert summary["max_ms"] == 40_000
    assert summary["outlier_count"] == 1
    assert validate_latency_snapshot(empty_latency_snapshot())


def test_onset_detects_loud_run_and_counts_false_start() -> None:
    detector = SpeechOnsetDetector(loud_chunks=2, quiet_chunks=2)
    quiet = _pcm(0.0)
    loud = _pcm(0.4)
    assert detector.observe_pcm16(quiet) is False
    assert detector.observe_pcm16(loud) is False
    assert detector.observe_pcm16(loud) is True
    assert detector.detections == 1
    assert detector.observe_pcm16(quiet) is False
    assert detector.observe_pcm16(quiet) is False
    assert detector.false_start_resets == 1


def test_tracker_records_monotonic_pipeline_without_text() -> None:
    tracker = LatencyTracker()
    assert tracker.observe_pcm16(_pcm(0.5)) is False
    assert tracker.observe_pcm16(_pcm(0.5)) is True
    time.sleep(0.01)
    tracker.observe_first_partial()
    tracker.observe_final_source(3)
    tracker.observe_translation_dispatch(3)
    tracker.observe_translation_complete(3, repaired=True)
    tracker.observe_render_dispatch(3)
    tracker.observe_render_ack(3)
    tracker.observe_tts_request(3)
    tracker.observe_tts_queue_wait(3, 0.02)
    tracker.observe_tts_synth_start(3)
    tracker.observe_tts_first_audio(3)
    tracker.observe_tts_playback_start(3)
    tracker.observe_tts_playback_complete(3)

    snap = tracker.snapshot()
    assert validate_latency_snapshot(snap)
    repaired = snap["dimensions"]["translation_dispatch_to_completion"]["repaired"]
    assert repaired["count"] == 1
    assert repaired["max_ms"] >= 0
    serialized = str(snap)
    assert "private" not in serialized
    assert "source" not in serialized or "speech_onset_to_final_source" in serialized


def test_reconnect_and_replacement_classes() -> None:
    tracker = LatencyTracker()
    tracker.mark_reconnect_period(True)
    tracker.observe_final_source(1, reconnect=True)
    tracker.observe_translation_dispatch(1)
    tracker.observe_translation_complete(1)
    snap = tracker.snapshot()
    assert snap["dimensions"]["finalization_to_translation_dispatch"]["reconnect"]["count"] == 1

    tracker.mark_browser_replacement(hold_s=30)
    tracker.observe_render_dispatch(1)
    tracker.observe_render_ack(1)
    snap = tracker.snapshot()
    assert snap["dimensions"]["translation_completion_to_render_ack"]["browser_replacement"]["count"] == 1


def test_schema_v2_record_keeps_loading_v1(tmp_path) -> None:
    v2 = _record()
    assert v2["schema_version"] == 2
    assert validate_session_record(v2)
    assert "latency" in v2
    assert validate_latency_snapshot(v2["latency"])

    v1 = {
        key: value
        for key, value in v2.items()
        if key != "latency"
    }
    v1["schema_version"] = 1
    assert validate_session_record(v1)

    root = tmp_path / "reliability"
    write_session_record(root, v2)
    (root / "session-legacy.json").write_text(
        __import__("orjson").dumps(v1).decode()
    )
    sessions, _soaks, skipped = load_history(root)
    assert skipped == 0
    assert {item["schema_version"] for item in sessions} == {1, 2}


def test_session_record_still_strips_private_payloads() -> None:
    tracker = ReliabilityTracker()
    tracker.observe_event(
        {
            "type": "recovered",
            "source_text": "private source",
            "downtime_ms": 5,
        }
    )
    record = tracker.build_session_record(_session())
    blob = __import__("orjson").dumps(record)
    assert b"private" not in blob
    assert validate_session_record(record)
