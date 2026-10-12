"""Content-free latency aggregates and speech-onset behavior."""

from __future__ import annotations

import struct
import time

from app.latency import (
    _MAX_SEQUENCES,
    LatencyTracker,
    SpeechOnsetDetector,
    empty_latency_snapshot,
    summarize_samples,
    validate_latency_snapshot,
)
from app.reliability import (
    SCHEMA_VERSION,
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


def test_render_ack_uses_translation_complete_not_dispatch() -> None:
    tracker = LatencyTracker()
    tracker.observe_final_source(7)
    tracker.observe_translation_dispatch(7)
    tracker.observe_translation_complete(7)
    time.sleep(0.03)
    tracker.observe_render_dispatch(7)
    tracker.observe_render_ack(7)
    render = tracker.snapshot()["dimensions"]["translation_completion_to_render_ack"]["ordinary"]
    assert render["count"] == 1
    assert render["max_ms"] >= 25


def test_render_ack_without_translation_complete_is_ignored() -> None:
    tracker = LatencyTracker()
    tracker.observe_final_source(8)
    tracker.observe_render_dispatch(8)
    tracker.observe_render_ack(8)
    render = tracker.snapshot()["dimensions"]["translation_completion_to_render_ack"]["ordinary"]
    assert render["count"] == 0


def test_duplicate_browser_acks_are_consumed_once() -> None:
    tracker = LatencyTracker()
    tracker.observe_final_source(9)
    tracker.observe_translation_dispatch(9)
    tracker.observe_translation_complete(9)
    tracker.observe_render_ack(9)
    tracker.observe_render_ack(9)
    tracker.observe_tts_request(9)
    tracker.observe_tts_playback_start(9)
    tracker.observe_tts_playback_start(9)
    tracker.observe_tts_playback_complete(9)
    tracker.observe_tts_playback_complete(9)
    snap = tracker.snapshot()
    assert snap["dimensions"]["translation_completion_to_render_ack"]["ordinary"]["count"] == 1
    assert snap["dimensions"]["tts_request_to_playback_start"]["ordinary"]["count"] == 1
    assert snap["dimensions"]["tts_playback_start_to_completion"]["ordinary"]["count"] == 1


def test_sequence_state_is_bounded() -> None:
    tracker = LatencyTracker()
    for seq in range(1, _MAX_SEQUENCES + 80):
        tracker.observe_final_source(seq)
        tracker.observe_translation_complete(seq)
    assert len(tracker._stamps) <= _MAX_SEQUENCES
    assert len(tracker._classes) <= _MAX_SEQUENCES


def test_current_record_keeps_loading_legacy_history(tmp_path) -> None:
    current = _record()
    assert current["schema_version"] == SCHEMA_VERSION
    assert validate_session_record(current)
    assert validate_latency_snapshot(current["latency"])

    # Legacy records predate the catch-up counters.
    legacy_queues = {key: dict(value) for key, value in current["queues"].items()}
    legacy_queues["tts"].pop("catch_up_actions")
    legacy_queues["tts"].pop("catch_up_skipped")
    v1 = {
        key: value for key, value in current.items()
        if key not in {"latency", "speech_playback", "pipeline"}
    }
    v1["schema_version"] = 1
    v1["queues"] = legacy_queues
    assert validate_session_record(v1)

    root = tmp_path / "reliability"
    write_session_record(root, current)
    (root / "session-legacy.json").write_text(
        __import__("orjson").dumps(v1).decode()
    )
    sessions, _soaks, skipped = load_history(root)
    assert skipped == 0
    assert {item["schema_version"] for item in sessions} == {1, SCHEMA_VERSION}


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
