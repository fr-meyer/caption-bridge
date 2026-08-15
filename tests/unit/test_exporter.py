"""Tests for transcript export quality summaries and JSON shape."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import orjson

from app.exporter import _compute_quality_summary, _write_transcript_json, export_session
from app.state import Segment, SegmentQuality, Session


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def make_session(segments_spec: list[dict]) -> Session:
    segments: list[Segment] = []
    for idx, spec in enumerate(segments_spec, start=1):
        segments.append(
            Segment(
                seq=idx,
                created_at=_utcnow(),
                source_text=spec.get("source_text", f"segment {idx}"),
                segment_kind="complete",
                translated_text=spec.get("translated_text"),
                target_language=spec.get("target_language", "en"),
                translation_status=spec.get("translation_status", "pending"),
                quality=spec.get("quality"),
                failure_reason=spec.get("failure_reason"),
            )
        )
    return Session(
        id="test-session",
        started_at=_utcnow(),
        segments=segments,
        source_language="ko",
        target_language="en",
    )


def _mock_config(export_dir: str) -> MagicMock:
    config = MagicMock()
    config.export_dir = export_dir
    config.recovery_export_dir = export_dir
    config.transcribe_model = "test-transcribe"
    config.translate_model = "test-translate"
    return config


def test_legacy_quality_metadata_backfills_final_state() -> None:
    quality = SegmentQuality.model_validate(
        {
            "flagged": True,
            "reasons": ["prompt_leakage"],
            "retried": True,
            "repair_succeeded": False,
        }
    )

    assert quality.final_flagged is True
    assert quality.final_reasons == ["prompt_leakage"]
    assert quality.repair_attempts == 1


def test_quality_summary_counts_done() -> None:
    session = make_session(
        [
            {"translation_status": "done"},
            {"translation_status": "done"},
            {"translation_status": "done"},
            {"translation_status": "failed"},
            {"translation_status": "timed_out"},
        ]
    )

    summary = _compute_quality_summary(session)

    assert summary["done"] == 3
    assert summary["failed"] == 1
    assert summary["timed_out"] == 1


def test_quality_summary_counts_retried() -> None:
    retried_quality = SegmentQuality(
        flagged=True,
        reasons=["prompt_leakage"],
        retried=True,
        repair_succeeded=False,
    )
    session = make_session(
        [
            {"translation_status": "done", "quality": retried_quality},
            {"translation_status": "done", "quality": retried_quality},
            {"translation_status": "done"},
        ]
    )

    summary = _compute_quality_summary(session)

    assert summary["retried"] == 2


def test_quality_summary_counts_flagged() -> None:
    flagged_quality = SegmentQuality(
        flagged=True,
        reasons=["length_ratio"],
        retried=False,
        repair_succeeded=None,
    )
    session = make_session(
        [
            {"translation_status": "done", "quality": flagged_quality},
            {"translation_status": "done", "quality": flagged_quality},
            {"translation_status": "done"},
        ]
    )

    summary = _compute_quality_summary(session)

    assert summary["quality_flagged"] == 2


def test_quality_summary_total() -> None:
    session = make_session([{} for _ in range(5)])

    summary = _compute_quality_summary(session)

    assert summary["total_segments"] == 5


def test_quality_summary_reports_repair_outcomes_reasons_and_latency() -> None:
    repaired = SegmentQuality(
        flagged=True,
        reasons=["prompt_leakage"],
        retried=True,
        repair_succeeded=True,
        final_flagged=False,
        final_reasons=[],
        repair_attempts=1,
        repair_latency_ms=120,
    )
    still_flagged = SegmentQuality(
        flagged=True,
        reasons=["residual_source_script"],
        retried=True,
        repair_succeeded=False,
        final_flagged=True,
        final_reasons=["residual_source_script"],
        repair_attempts=1,
        repair_latency_ms=80,
    )
    repair_disabled = SegmentQuality(
        flagged=True,
        reasons=["length_ratio"],
        retried=False,
        repair_succeeded=None,
        final_flagged=True,
        final_reasons=["length_ratio"],
        repair_attempts=0,
        repair_latency_ms=None,
    )
    clean = SegmentQuality(
        flagged=False,
        reasons=[],
        retried=False,
        repair_succeeded=None,
    )
    session = make_session(
        [
            {"translation_status": "done", "quality": repaired},
            {"translation_status": "done", "quality": still_flagged},
            {"translation_status": "done", "quality": repair_disabled},
            {"translation_status": "done", "quality": clean},
        ]
    )

    summary = _compute_quality_summary(session)

    assert summary["quality_checked"] == 4
    assert summary["quality_flagged"] == 3
    assert summary["repair_attempts"] == 2
    assert summary["repair_succeeded"] == 1
    assert summary["quality_still_flagged"] == 2
    assert summary["initial_reason_counts"] == {
        "length_ratio": 1,
        "prompt_leakage": 1,
        "residual_source_script": 1,
    }
    assert summary["final_reason_counts"] == {
        "length_ratio": 1,
        "residual_source_script": 1,
    }
    assert summary["repair_latency_samples"] == 2
    assert summary["repair_latency_ms_total"] == 200
    assert summary["repair_latency_ms_average"] == 100.0
    assert summary["repair_latency_ms_max"] == 120


def test_per_segment_quality_in_json(tmp_path: Path) -> None:
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    flagged_quality = SegmentQuality(
        flagged=True,
        reasons=["prompt_leakage"],
        retried=True,
        repair_succeeded=True,
    )
    session = make_session(
        [
            {
                "translation_status": "done",
                "translated_text": "Hello",
                "quality": flagged_quality,
            }
        ]
    )
    config = _mock_config(str(tmp_path))

    _write_transcript_json(export_dir, session, config)
    data = json.loads((export_dir / "transcript.json").read_text(encoding="utf-8"))

    quality = data["segments"][0]["quality"]
    assert quality is not None
    assert quality["flagged"] is True
    assert quality["reasons"] == ["prompt_leakage"]
    assert quality["retried"] is True
    assert quality["repair_succeeded"] is True


def test_per_segment_quality_null_when_none(tmp_path: Path) -> None:
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    session = make_session([{"translation_status": "done", "quality": None}])
    config = _mock_config(str(tmp_path))

    _write_transcript_json(export_dir, session, config)
    data = json.loads((export_dir / "transcript.json").read_text(encoding="utf-8"))

    assert data["segments"][0]["quality"] is None


def test_recovered_pending_normalization(tmp_path: Path) -> None:
    session = make_session([{"translation_status": "pending"}])
    config = _mock_config(str(tmp_path))

    export_dir = export_session(session, config, recovery=True)
    data = orjson.loads((Path(export_dir) / "transcript.json").read_bytes())

    segment = data["segments"][0]
    assert segment["translation_status"] == "failed"
    assert segment["failure_reason"] == "recovered_pending"


def test_recovered_pending_not_applied_to_normal_export(tmp_path: Path) -> None:
    session = make_session([{"translation_status": "pending"}])
    config = _mock_config(str(tmp_path))

    export_dir = export_session(session, config, recovery=False)
    data = orjson.loads((Path(export_dir) / "transcript.json").read_bytes())

    segment = data["segments"][0]
    assert segment["translation_status"] == "pending"
    assert segment.get("failure_reason") is None
