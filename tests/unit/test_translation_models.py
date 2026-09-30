"""Model-selection validation, dispatch-time freeze, and private provenance."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import app.ws as ws_mod
from app.config import AppConfig
from app.journal import SessionJournal, run_recovery
from app.providers import TranslationResponse
from app.state import Segment, SessionManager, TranslationModelChange
from app.translate import TranslationDispatcher
from app.translation_models import available_translation_models, validate_translation_model
from app.ws import _handle_set_translation_model, _handle_start, _OutboundObsState


def config_at(path: Path) -> AppConfig:
    return AppConfig(
        _env_file=None,
        JOURNAL_DIR=str(path / "journal"),
        RECOVERY_EXPORT_DIR=str(path / "recovered"),
        EXPORT_DIR=str(path / "exports"),
        RELIABILITY_DIR=str(path / "reliability"),
        MISTRAL_TTS_ENABLED=False,
    )


def test_model_list_accepts_only_explicit_ids(tmp_path: Path) -> None:
    config = config_at(tmp_path)
    assert config.translate_model == "mistral-medium-latest"
    assert available_translation_models(config)[0]["id"] == "mistral-medium-latest"
    ids = {item["id"] for item in available_translation_models(config)}
    assert ids == {"mistral-small-latest", "mistral-medium-latest", "zai-glm-5-3"}
    assert validate_translation_model("zai-glm-5-3", config) == "zai-glm-5-3"
    for value in (None, "", {}, "voxtral-mini-transcribe-realtime-2602", "arbitrary"):
        with pytest.raises(ValueError):
            validate_translation_model(value, config)


def test_invalid_start_model_has_no_session_or_pipeline_side_effects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    async def scenario() -> None:
        manager = SessionManager(config_at(tmp_path))
        manager.session.status = "idle_ready"
        original = manager.session.model_dump(mode="json")
        pipeline = AsyncMock()
        monkeypatch.setattr(ws_mod, "manager", manager)
        monkeypatch.setattr(ws_mod, "start_pipeline", pipeline)
        queue: asyncio.Queue = asyncio.Queue(maxsize=16)
        await _handle_start(
            {"type": "start", "target_language": "fr",
             "translation_model": "not-on-list", "glossary": []},
            queue, _OutboundObsState(),
        )
        assert manager.session.model_dump(mode="json") == original
        pipeline.assert_not_awaited()
        assert queue.get_nowait()[0]["message"] == "Choose a listed translation model."

    asyncio.run(scenario())


def test_invalid_live_model_preserves_selected_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    async def scenario() -> None:
        manager = SessionManager(config_at(tmp_path))
        manager.session.status = "listening"
        manager.session.started_at = datetime.now(timezone.utc)
        monkeypatch.setattr(ws_mod, "manager", manager)
        queue: asyncio.Queue = asyncio.Queue(maxsize=16)
        await _handle_set_translation_model(
            {"type": "set_translation_model", "model": "unknown"},
            queue, _OutboundObsState(),
        )
        assert manager.session.translation_model == "mistral-medium-latest"
        assert manager.session.translation_model_revision == 0
        assert manager.session.translation_model_changes == []
        assert queue.get_nowait()[0]["message"] == "Choose a listed translation model."

    asyncio.run(scenario())


class _RecordingProvider:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def translate(self, *, model: str, messages: list[dict],
                        temperature: float, max_tokens: int) -> str:
        self.calls.append(model)
        await asyncio.sleep(0)
        return TranslationResponse(
            text="These results require further validation.",
            resolved_model=model, prompt_tokens=21, completion_tokens=9,
        )


def test_switch_keeps_in_flight_segments_on_their_original_model(tmp_path: Path) -> None:
    async def scenario() -> None:
        config = config_at(tmp_path)
        manager = SessionManager(config)
        provider = _RecordingProvider()
        dispatcher = TranslationDispatcher(manager, config, provider)
        manager.set_dispatcher(dispatcher)
        manager.session.status = "listening"
        manager.session.started_at = datetime.now(timezone.utc)
        manager.finalize_segment("이 결과는 추가 검증이 필요합니다.")
        manager.set_translation_model("mistral-small-latest")
        manager.finalize_segment("다음 결과도 검증해야 합니다.")
        await dispatcher.drain()
        assert provider.calls == ["mistral-medium-latest", "mistral-small-latest"]
        assert [(seg.translation_model, seg.translation_model_revision)
                for seg in manager.session.segments] == [
                    ("mistral-medium-latest", 0), ("mistral-small-latest", 1)
                ]
        assert manager.session.translation_model_changes[0].applies_from_seq == 2
        assert [seg.translation_model_resolved for seg in manager.session.segments] == provider.calls
        assert [seg.translation_prompt_tokens for seg in manager.session.segments] == [21, 21]
        assert [seg.translation_completion_tokens for seg in manager.session.segments] == [9, 9]

    asyncio.run(scenario())


def test_empty_provider_answer_fails_without_another_request(tmp_path: Path) -> None:
    class EmptyProvider:
        name = "fake"

        def __init__(self) -> None:
            self.calls = 0

        async def translate(self, **kwargs) -> TranslationResponse:
            self.calls += 1
            return TranslationResponse(
                text="", resolved_model=kwargs["model"],
                prompt_tokens=155, completion_tokens=200,
            )

    async def scenario() -> None:
        config = config_at(tmp_path)
        manager = SessionManager(config)
        provider = EmptyProvider()
        dispatcher = TranslationDispatcher(manager, config, provider)
        manager.set_dispatcher(dispatcher)
        manager.session.status = "listening"
        manager.session.started_at = datetime.now(timezone.utc)
        manager.finalize_segment("이 결과는 통계적으로 유의미합니다.")
        await dispatcher.drain()
        segment = manager.session.segments[0]
        assert provider.calls == 1
        assert segment.translation_status == "failed"
        assert segment.failure_reason == "provider_no_text"
        assert segment.translation_model_resolved == "mistral-medium-latest"
        assert segment.translation_completion_tokens == 200

    asyncio.run(scenario())


def test_recovery_preserves_each_model_and_old_unknown_metadata(tmp_path: Path) -> None:
    config = config_at(tmp_path)
    journal = SessionJournal("model-session", config)
    journal.record_session_started()
    journal.record_translation_model_start("mistral-small-latest")
    journal.record_segment_created(Segment(
        seq=1, source_text="첫 문장", segment_kind="complete",
        translation_model="mistral-small-latest", translation_model_revision=0,
    ))
    change = TranslationModelChange(
        model="zai-glm-5-3", revision=1, applies_from_seq=2
    )
    journal.record_translation_model_change(change)
    second = Segment(
        seq=2, source_text="둘째 문장", segment_kind="complete",
        translation_model="zai-glm-5-3", translation_model_revision=1,
        translation_model_resolved="zai-glm-5-3",
        translation_prompt_tokens=21, translation_completion_tokens=9,
        translated_text="Second sentence", translation_status="done",
    )
    journal.record_segment_created(second)
    journal.record_translation_updated(second)
    result = run_recovery(config)
    assert result.notice is not None and result.notice.status == "success"
    data = json.loads((Path(result.notice.export_path) / "transcript.json").read_text())
    assert [item["translation_model"] for item in data["segments"]] == [
        "mistral-small-latest", "zai-glm-5-3"
    ]
    assert data["translation_model_changes"][0]["applies_from_seq"] == 2
    assert data["segments"][1]["translation_model_resolved"] == "zai-glm-5-3"
    assert data["segments"][1]["translation_prompt_tokens"] == 21
    assert data["segments"][1]["translation_completion_tokens"] == 9

    old = Path(config.journal_dir) / "legacy-model-session.jsonl"
    old.write_text(json.dumps({
        "type": "session_started", "session_id": "legacy-model-session",
        "ts": datetime.now(timezone.utc).isoformat(),
    }) + "\n" + json.dumps({
        "type": "segment_created", "session_id": "legacy-model-session",
        "seq": 1, "source_text": "old", "segment_kind": "complete",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }) + "\n")
    result = run_recovery(config)
    assert result.notice is not None and result.notice.status == "success"
    legacy = json.loads((Path(result.notice.export_path) / "transcript.json").read_text())
    assert legacy["segments"][0]["translation_model"] is None
