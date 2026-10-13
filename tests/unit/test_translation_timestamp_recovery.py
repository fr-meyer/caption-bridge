"""Recover the recorded completion timestamp without inventing legacy timings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.exporter import export_session
from app.journal import run_recovery
from tests.unit.test_caption_terminology import listening


@pytest.mark.parametrize("status", ["done", "failed", "timed_out"])
def test_translation_completion_timestamp_survives_journal_and_private_export(tmp_path, status):
    manager = listening(tmp_path)
    segment = manager.session.segments[0]
    segment.translation_status = "pending"
    if status == "done":
        manager.mark_translated(1, "Recorded result.", "en", manager.session.id)
    elif status == "failed":
        manager.mark_translation_failed(1, manager.session.id, reason="synthetic")
    else:
        manager.mark_translation_timed_out(1, manager.session.id)
    assert segment.translated_at is not None
    records = [json.loads(line) for line in manager._journal._path.read_text().splitlines()]
    update = [record for record in records if record["type"] == "translation_updated"][-1]
    assert update["translated_at"] == segment.translated_at.isoformat()
    data = json.loads((Path(export_session(manager.session, manager.config)) / "transcript.json").read_text())
    result = run_recovery(manager.config)
    recovered = json.loads((Path(result.notice.export_path) / "transcript.json").read_text())
    assert recovered["segments"][0] == data["segments"][0]
    assert recovered["segments"][0]["translation_status"] == status


@pytest.mark.parametrize("value", [None, "PRIVATE_INVALID_TIMESTAMP", 7])
def test_legacy_or_invalid_timestamp_preserves_other_recovery_fields(tmp_path, caplog, value):
    manager = listening(tmp_path)
    segment = manager.session.segments[0]
    manager.mark_translated(1, "Recorded result.", "en", manager.session.id)
    records = [json.loads(line) for line in manager._journal._path.read_text().splitlines()]
    for record in records:
        if record["type"] == "translation_updated":
            if value is None:
                record.pop("translated_at", None)
            else:
                record["translated_at"] = value
    manager._journal._path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    result = run_recovery(manager.config)
    assert result.notice.status == "success"
    recovered = json.loads((Path(result.notice.export_path) / "transcript.json").read_text())
    assert recovered["segments"][0]["translated_at"] is None
    assert recovered["segments"][0]["translated_text"] == segment.translated_text
    assert recovered["segments"][0]["source_text"] == segment.source_text
    assert recovered["segments"][0]["translation_status"] == "done"
    assert "PRIVATE_INVALID_TIMESTAMP" not in caplog.text
