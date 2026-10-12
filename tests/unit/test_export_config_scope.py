"""Runtime export configuration must not imply a legacy caption's model."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config import AppConfig
from app.exporter import export_session
from app.journal import SessionJournal, retry_recovery, run_recovery
from app.state import RecoveryState, Segment, Session, TranslationModelChange

STAMP = datetime(2026, 10, 6, 8, 30, tzinfo=timezone.utc)


def config_at(path: Path) -> AppConfig:
    return AppConfig(
        _env_file=None, mistral_api_key="",
        MISTRAL_TRANSLATE_MODEL="zai-glm-5-3", MISTRAL_TTS_ENABLED=False,
        journal_dir=str(path / "journal"),
        recovery_export_dir=str(path / "recovered"),
        export_dir=str(path / "exports"),
        RELIABILITY_DIR=str(path / "reliability"),
    )


def recorded_session(status: str = "done") -> Session:
    segment = Segment(
        seq=1, source_text="Synthetic source.", segment_kind="complete",
        created_at=STAMP, translated_at=STAMP, target_language="en",
        translated_text="Synthetic result." if status == "done" else None,
        translation_status=status, translation_model="mistral-small-latest",
        translation_model_revision=0, translation_reasoning_effort="default",
        translation_max_tokens=200, translation_prompt_version="academic-caption-v1",
        translation_model_resolved="mistral-small-2603",
        translation_prompt_tokens=12, translation_completion_tokens=7,
        translation_finish_reason="stop",
    )
    return Session(
        id="synthetic-scope", started_at=STAMP,
        translation_model="mistral-small-latest",
        translation_reasoning_effort="default", segments=[segment],
    )


def exported(path: str) -> dict:
    return json.loads((Path(path) / "transcript.json").read_text())


def test_normal_export_labels_runtime_config_without_replacing_recorded_model(tmp_path):
    config = config_at(tmp_path)
    data = exported(export_session(recorded_session(), config))
    assert data["config_scope"] == "export_runtime"
    assert data["config"]["translate_model"] == "zai-glm-5-3"
    assert data["translation_model_at_export"] == "mistral-small-latest"
    assert data["segments"][0]["translation_model_resolved"] == "mistral-small-2603"
    assert data["segments"][0]["translated_at"] == STAMP.isoformat()


def test_legacy_recovery_labels_runtime_config_and_keeps_historical_model_unknown(tmp_path):
    config = config_at(tmp_path)
    journal = Path(config.journal_dir) / "synthetic-legacy.jsonl"
    journal.parent.mkdir(parents=True)
    records = [
        {"type": "session_started", "session_id": "synthetic-legacy", "ts": STAMP.isoformat()},
        {"type": "segment_created", "seq": 1, "source_text": "Synthetic legacy source.",
         "segment_kind": "complete", "created_at": STAMP.isoformat()},
        {"type": "translation_updated", "seq": 1, "translation_status": "done",
         "translated_text": "Synthetic legacy result.", "target_language": "en"},
    ]
    original = "\n".join(json.dumps(record) for record in records) + "\n"
    journal.write_text(original)
    result = run_recovery(config)
    data = exported(result.notice.export_path)
    assert data["config_scope"] == "recovery_runtime"
    assert data["config"]["translate_model"] == "zai-glm-5-3"
    assert data["translation_model_at_export"] is None
    assert data["translation_reasoning_effort_at_export"] is None
    segment = data["segments"][0]
    assert segment["translation_model"] is None
    assert segment["translation_model_resolved"] is None
    assert segment["translated_at"] is None
    assert segment["source_text"] == "Synthetic legacy source."
    archived = journal.parent / "_archived" / journal.name
    assert archived.read_text().startswith(original)


@pytest.mark.parametrize("status", ["done", "failed", "timed_out"])
def test_recorded_models_and_timestamps_survive_recovery_under_new_runtime(tmp_path, status):
    config = config_at(tmp_path)
    session = recorded_session(status)
    journal = SessionJournal(session.id, config)
    journal.record_session_started()
    journal.record_translation_model_start(session.translation_model, "default")
    journal.record_segment_created(session.segments[0])
    journal.record_translation_updated(session.segments[0])
    change = TranslationModelChange(
        model="mistral-medium-latest", reasoning_effort="high", revision=1,
        applies_from_seq=2, changed_at=STAMP,
    )
    journal.record_translation_model_change(change)
    session.translation_model = change.model
    session.translation_reasoning_effort = change.reasoning_effort
    session.translation_model_changes = [change]
    normal_path = export_session(session, config)
    before = (Path(normal_path) / "transcript.json").read_bytes()
    normal = exported(normal_path)
    recovered = exported(run_recovery(config).notice.export_path)
    assert normal["config_scope"] == "export_runtime"
    assert recovered["config_scope"] == "recovery_runtime"
    assert recovered["config"] == normal["config"]
    assert recovered["segments"] == normal["segments"]
    assert recovered["translation_model_at_export"] == "mistral-medium-latest"
    assert recovered["translation_reasoning_effort_at_export"] == "high"
    assert recovered["translation_model_changes"] == normal["translation_model_changes"]
    assert (Path(normal_path) / "transcript.json").read_bytes() == before


def test_retry_recovery_also_marks_configuration_as_recovery_runtime(tmp_path):
    config = config_at(tmp_path)
    session = recorded_session()
    journal = SessionJournal(session.id, config)
    journal.record_session_started()
    state = RecoveryState(
        recovered_session_id=session.id, session_payload=session,
        journal_path=str(journal._path), last_error="synthetic_export_failure", created_at=STAMP,
    )
    path, error = retry_recovery(state, config)
    assert error is None
    data = exported(path)
    assert data["config_scope"] == "recovery_runtime"
    assert data["segments"][0]["translation_model"] == "mistral-small-latest"
    assert data["segments"][0]["translated_at"] == STAMP.isoformat()
