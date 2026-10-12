"""Tests for exact-schema, content-free reliability history."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import orjson

from app.config import AppConfig
from app.reliability import (
    ReliabilityTracker,
    load_history,
    validate_session_record,
    write_session_record,
    write_soak_record,
)
from app.state import Segment, SegmentQuality, Session, SessionManager
from scripts.reliability_report import build_report


def _session() -> Session:
    started = datetime(2026, 8, 16, 1, 0, tzinfo=timezone.utc)
    quality = SegmentQuality(
        flagged=True,
        reasons=["prompt_leakage"],
        retried=True,
        repair_succeeded=True,
        final_flagged=False,
        final_reasons=[],
        repair_attempts=1,
        repair_latency_ms=12,
    )
    return Session(
        id="safe-session-1",
        status="session_ended",
        started_at=started,
        ended_at=started + timedelta(seconds=12),
        segments=[
            Segment(
                seq=1,
                source_text="private source text",
                segment_kind="complete",
                translated_text="private translated text",
                translation_status="done",
                quality=quality,
            ),
            Segment(
                seq=2,
                source_text="another private source",
                segment_kind="complete",
                translation_status="timed_out",
            ),
        ],
    )


def _record() -> dict:
    tracker = ReliabilityTracker()
    tracker.observe_event(
        {
            "type": "provider_temporarily_unavailable",
            "outcome": "retrying",
            "attempts": 0,
            "provider_body": "must never be retained",
        }
    )
    tracker.observe_event({"type": "reconnect_attempt", "attempt": 1})
    tracker.observe_event(
        {
            "type": "recovered",
            "attempts": 1,
            "downtime_ms": 250,
            "source_text": "must never be retained",
        }
    )
    tracker.observe_event(
        {
            "type": "provider_temporarily_unavailable",
            "outcome": "retrying",
            "attempts": 0,
        }
    )
    tracker.observe_event({"type": "reconnect_attempt", "attempt": 1})
    tracker.observe_event(
        {"type": "recovered", "attempts": 1, "downtime_ms": 250}
    )
    tracker.observe_event({"type": "tts_retrying", "content": "private"})
    tracker.observe_event({"type": "tts_skipped", "reason": "queue_pressure"})
    tracker.observe_event({"type": "tts_error", "error": "private"})
    tracker.record_audio_queue(4, 1)
    tracker.record_audio_queue(2, 1)
    tracker.record_websocket_queue(
        7, dropped=2, coalesced=3, critical_drops=1
    )
    tracker.record_tts_queue(5)
    tracker.set_export_outcome("succeeded")
    return tracker.build_session_record(_session())


def _all_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.add(str(key))
            keys.update(_all_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.update(_all_keys(nested))
    return keys


def test_tracker_reduces_events_to_content_free_aggregates() -> None:
    record = _record()

    assert validate_session_record(record)
    assert record["duration_ms"] == 12_000
    assert record["translation"] == {
        "total": 2,
        "done": 1,
        "failed": 0,
        "timed_out": 1,
        "pending": 0,
        "quality_checked": 1,
        "initially_flagged": 1,
        "repair_attempts": 1,
        "repair_succeeded": 1,
        "still_flagged": 0,
    }
    assert record["reconnect"]["cycles"] == 2
    assert record["reconnect"]["attempts"] == 2
    assert record["reconnect"]["downtime_ms"] == 500
    assert record["queues"]["audio"] == {"peak_depth": 4, "dropped": 2}
    assert record["queues"]["websocket"]["peak_depth"] == 7
    assert record["queues"]["tts"] == {
        "peak_depth": 5,
        "retries": 1,
        "skipped": 1,
        "failures": 1,
        "catch_up_actions": 0,
        "catch_up_skipped": 0,
    }
    forbidden = {
        "text",
        "source_text",
        "translated_text",
        "content",
        "body",
        "prompt",
        "credential",
        "api_key",
        "error",
        "path",
    }
    assert _all_keys(record).isdisjoint(forbidden)
    serialized = orjson.dumps(record)
    assert b"private" not in serialized
    assert b"provider_body" not in serialized


def test_exact_schema_rejects_unknown_or_text_fields() -> None:
    record = _record()
    unsafe = deepcopy(record)
    unsafe["source_text"] = "private"
    assert not validate_session_record(unsafe)

    nested_unsafe = deepcopy(record)
    nested_unsafe["translation"]["provider_body"] = "private"
    assert not validate_session_record(nested_unsafe)

    wrong_type = deepcopy(record)
    wrong_type["queues"]["audio"]["dropped"] = True
    assert not validate_session_record(wrong_type)


def test_history_loader_scans_only_reliability_records(tmp_path: Path) -> None:
    root = tmp_path / "reliability"
    write_session_record(root, _record())
    write_soak_record(
        root,
        run_type="translation_resilience",
        passed=True,
        duration_ms=123,
        case_count=1000,
    )
    (root / "session-malformed.json").write_text(
        '{"source_text":"must not be surfaced"}', encoding="utf-8"
    )
    transcript_dir = tmp_path / "2026-08-16_010000"
    transcript_dir.mkdir()
    (transcript_dir / "transcript.json").write_text(
        '{"source_text":"not scanned"}', encoding="utf-8"
    )

    sessions, soaks, skipped = load_history(root)

    assert len(sessions) == 1
    assert len(soaks) == 1
    assert skipped == 1


def test_trend_compares_equal_recent_and_previous_windows() -> None:
    records = []
    for index in range(4):
        record = _record()
        record["session_id"] = f"safe-session-{index}"
        record["recorded_at"] = datetime(
            2026, 8, 16, 1, index, tzinfo=timezone.utc
        ).isoformat()
        record["duration_ms"] = (index + 1) * 1000
        record["reconnect"]["cycles"] = index
        record["reconnect"]["downtime_ms"] = index * 100
        assert validate_session_record(record)
        records.append(record)

    report = build_report(records, [], recent_limit=3, trend_window=2)

    assert report["sessions"]["total"] == 4
    assert len(report["sessions"]["recent"]) == 3
    assert report["trend"]["recent"]["average_duration_ms"] == 3500.0
    assert report["trend"]["previous"]["average_duration_ms"] == 1500.0
    assert report["trend"]["delta"]["average_duration_ms"] == 2000.0
    assert report["trend"]["delta"]["reconnect_cycles_per_session"] == 2.0


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        _env_file=None,
        MISTRAL_TTS_ENABLED=False,
        export_dir=str(tmp_path / "transcripts"),
        recovery_export_dir=str(tmp_path / "recovered"),
        journal_dir=str(tmp_path / "journal"),
        reliability_dir=str(tmp_path / "reliability"),
    )


def test_session_export_writes_separate_reliability_record(tmp_path: Path) -> None:
    config = _config(tmp_path)
    manager = SessionManager(config)
    manager.session = _session()
    manager._reliability = ReliabilityTracker()
    manager._reliability.set_export_outcome("not_requested")

    result = manager.export()

    assert result["success"] is True
    reliability_files = list(Path(config.reliability_dir).glob("session-*.json"))
    assert len(reliability_files) == 1
    payload = orjson.loads(reliability_files[0].read_bytes())
    assert validate_session_record(payload)
    assert payload["export"]["outcome"] == "succeeded"
    assert Path(result["path"]).parent == Path(config.export_dir)
    assert Path(config.reliability_dir) not in Path(result["path"]).parents


def test_failed_export_and_discard_are_recorded_without_error_text(
    tmp_path: Path, monkeypatch
) -> None:
    config = _config(tmp_path)
    manager = SessionManager(config)
    manager.session = _session()
    manager._reliability = ReliabilityTracker()

    def fail_export(*_args, **_kwargs):
        raise RuntimeError("private provider response")

    monkeypatch.setattr("app.exporter.export_session", fail_export)
    result = manager.export()
    assert result["success"] is False
    failed_path = next(Path(config.reliability_dir).glob("session-*.json"))
    assert b"private provider response" not in failed_path.read_bytes()
    assert orjson.loads(failed_path.read_bytes())["export"]["outcome"] == "failed"

    discarded = SessionManager(config)
    discarded_id = discarded.session.id
    asyncio.run(discarded.reset())
    discarded_path = Path(config.reliability_dir) / f"session-{discarded_id}.json"
    assert orjson.loads(discarded_path.read_bytes())["export"]["outcome"] == "discarded"
