"""Provider-free thinking selection, request, and provenance contracts."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.providers as providers_mod
import app.ws as ws
from app.config import AppConfig
from app.exporter import export_session
from app.journal import SessionJournal, run_recovery
from app.state import SessionManager
from app.translate import TranslationDispatcher
from app.translation_models import translation_output_limit, validate_reasoning_effort


def config_at(path: Path) -> AppConfig:
    return AppConfig(
        _env_file=None, MISTRAL_TTS_ENABLED=False,
        JOURNAL_DIR=str(path / "journal"), EXPORT_DIR=str(path / "exports"),
        RECOVERY_EXPORT_DIR=str(path / "recovered"),
        RELIABILITY_DIR=str(path / "reliability"),
    )


def test_glm_default_has_room_for_answer_after_thinking() -> None:
    assert translation_output_limit("zai-glm-5-3", "default") == 4096
    assert translation_output_limit("zai-glm-5-3", "high") == 4096
    assert translation_output_limit("mistral-small-latest", "default") == 200
    assert translation_output_limit("mistral-medium-latest", "default") == 200
    assert translation_output_limit("mistral-small-latest", "high") == 1024


def test_effort_allowlist_is_model_specific(tmp_path: Path) -> None:
    assert validate_reasoning_effort("high", "zai-glm-5-3") == "high"
    assert validate_reasoning_effort("default", "configured-other") == "default"
    for raw in (None, "max", "xhigh", "none", True, {}, "high "):
        with pytest.raises(ValueError):
            validate_reasoning_effort(raw, "zai-glm-5-3")
    with pytest.raises(ValueError):
        validate_reasoning_effort("high", "configured-other")


def test_invalid_start_effort_has_no_side_effects(monkeypatch, tmp_path: Path) -> None:
    async def scenario() -> None:
        manager = SessionManager(config_at(tmp_path))
        manager.session.status = "idle_ready"
        original = manager.session.model_dump(mode="json")
        start = AsyncMock()
        monkeypatch.setattr(ws, "manager", manager)
        monkeypatch.setattr(ws, "start_pipeline", start)
        queue: asyncio.Queue = asyncio.Queue()
        await ws._handle_start(
            {"type": "start", "translation_model": "zai-glm-5-3",
             "translation_reasoning_effort": "max"},
            queue, ws._OutboundObsState(),
        )
        assert manager.session.model_dump(mode="json") == original
        start.assert_not_awaited()
        assert queue.get_nowait()[0]["message"] == "Choose an available translation thinking level."

    asyncio.run(scenario())


class RecordingProvider:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def translate(self, **request) -> str:
        self.calls.append(request)
        await asyncio.sleep(0)
        return "This result is statistically significant but requires further validation."


def test_effort_switch_applies_to_future_segments_and_export(tmp_path: Path) -> None:
    async def scenario() -> None:
        config = config_at(tmp_path)
        manager = SessionManager(config)
        provider = RecordingProvider()
        dispatcher = TranslationDispatcher(manager, config, provider)
        manager.set_dispatcher(dispatcher)
        manager.session.status = "idle_ready"
        manager.set_journal(SessionJournal(manager.session.id, config))
        manager.set_translation_settings("zai-glm-5-3", "high")
        manager.set_status("listening")
        manager.finalize_segment("이 결과는 통계적으로 유의미하지만 추가 검증이 필요합니다.")
        manager.set_translation_settings("mistral-small-latest", "default")
        manager.finalize_segment("이 결과는 통계적으로 유의미하지만 추가 검증이 필요합니다.")
        manager.set_translation_settings("zai-glm-5-3", "default")
        manager.finalize_segment("이 결과는 통계적으로 유의미하지만 추가 검증이 필요합니다.")
        await dispatcher.drain()
        assert [call["max_tokens"] for call in provider.calls] == [4096, 200, 4096]
        assert provider.calls[0]["reasoning_effort"] == "high"
        assert "reasoning_effort" not in provider.calls[1]
        assert "reasoning_effort" not in provider.calls[2]
        assert [seg.translation_reasoning_effort for seg in manager.session.segments] == [
            "high", "default", "default"
        ]
        assert [seg.translation_max_tokens for seg in manager.session.segments] == [4096, 200, 4096]
        assert manager.session.translation_model_changes[0].reasoning_effort == "default"
        manager.set_status("session_ended")
        exported = Path(export_session(manager.session, config))
        data = json.loads((exported / "transcript.json").read_text())
        assert [seg["translation_reasoning_effort"] for seg in data["segments"]] == [
            "high", "default", "default"
        ]
        assert [seg["translation_max_tokens"] for seg in data["segments"]] == [4096, 200, 4096]
        records = [json.loads(line) for line in next((tmp_path / "journal").glob("*.jsonl")).read_text().splitlines()]
        assert next(rec for rec in records if rec["type"] == "session_translation_model")["reasoning_effort"] == "high"

    asyncio.run(scenario())


def test_recovery_keeps_thinking_and_legacy_unknown(tmp_path: Path) -> None:
    config = config_at(tmp_path)
    journal = SessionJournal("thinking-session", config)
    journal.record_session_started()
    journal.record_translation_model_start("zai-glm-5-3", "high")
    from app.state import Segment
    segment = Segment(
        seq=1, source_text="첫 문장", segment_kind="complete",
        translation_model="zai-glm-5-3", translation_reasoning_effort="high",
        translation_max_tokens=1024,
    )
    journal.record_segment_created(segment)
    result = run_recovery(config)
    assert result.notice is not None and result.notice.status == "success"
    data = json.loads((Path(result.notice.export_path) / "transcript.json").read_text())
    assert data["translation_reasoning_effort_at_export"] == "high"
    assert data["segments"][0]["translation_reasoning_effort"] == "high"
    assert data["segments"][0]["translation_max_tokens"] == 1024

    legacy = Path(config.journal_dir) / "legacy-thinking.jsonl"
    timestamp = datetime.now(timezone.utc).isoformat()
    legacy.write_text(
        json.dumps({"type": "session_started", "session_id": "legacy-thinking", "ts": timestamp}) + "\n"
        + json.dumps({"type": "segment_created", "session_id": "legacy-thinking",
                      "seq": 1, "source_text": "old", "segment_kind": "complete",
                      "created_at": timestamp}) + "\n"
    )
    result = run_recovery(config)
    assert result.notice is not None and result.notice.status == "success"
    data = json.loads((Path(result.notice.export_path) / "transcript.json").read_text())
    assert data["segments"][0]["translation_reasoning_effort"] is None
    assert data["segments"][0]["translation_max_tokens"] is None


def test_mistral_adapter_sends_only_selected_high(monkeypatch) -> None:
    requests: list[dict] = []

    async def complete_async(**request):
        requests.append(request)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Caption"), finish_reason="stop")],
            usage=None, model="zai-glm-5-3",
        )

    fake_client = SimpleNamespace(chat=SimpleNamespace(complete_async=complete_async))
    monkeypatch.setattr(providers_mod, "Mistral", lambda api_key: fake_client)
    provider = providers_mod.MistralTranslationProvider("unused")

    async def scenario() -> None:
        result = await provider.translate(
            model="zai-glm-5-3", messages=[], temperature=0.2,
            max_tokens=1024, reasoning_effort="high",
        )
        assert result.finish_reason == "stop"
        await provider.translate(
            model="zai-glm-5-3", messages=[], temperature=0.2,
            max_tokens=200,
        )

    asyncio.run(scenario())
    assert requests[0]["reasoning_effort"] == "high"
    assert "reasoning_effort" not in requests[1]


def test_invalid_live_effort_keeps_current_settings(monkeypatch, tmp_path: Path) -> None:
    async def scenario() -> None:
        manager = SessionManager(config_at(tmp_path))
        manager.session.status = "listening"
        manager.session.started_at = datetime.now(timezone.utc)
        original = manager.session.model_dump(mode="json")
        monkeypatch.setattr(ws, "manager", manager)
        queue: asyncio.Queue = asyncio.Queue()
        await ws._handle_set_translation_model(
            {"type": "set_translation_model", "model": "zai-glm-5-3",
             "reasoning_effort": "max"},
            queue, ws._OutboundObsState(),
        )
        assert manager.session.model_dump(mode="json") == original
        assert queue.get_nowait()[0]["message"] == "Choose an available translation thinking level."

    asyncio.run(scenario())


def test_glm_gets_its_own_timeout_without_changing_medium(tmp_path: Path) -> None:
    class DelayedProvider:
        name = "fake"

        async def translate(self, **request) -> str:
            await asyncio.sleep(0.15)
            return "These results require further validation."

    async def scenario() -> None:
        config = config_at(tmp_path)
        config.translation_timeout_ms = 100
        config.translation_glm_timeout_ms = 300
        config.translation_repair_max_attempts = 0
        manager = SessionManager(config)
        dispatcher = TranslationDispatcher(manager, config, DelayedProvider())
        manager.set_dispatcher(dispatcher)
        manager.session.status = "listening"
        manager.finalize_segment("이 결과는 추가 검증이 필요합니다.")
        manager.set_translation_model("mistral-medium-latest")
        manager.finalize_segment("이 결과는 추가 검증이 필요합니다.")
        await dispatcher.drain()
        assert [seg.translation_status for seg in manager.session.segments] == [
            "done", "timed_out",
        ]
        assert [seg.translation_max_tokens for seg in manager.session.segments] == [
            4096, 200,
        ]

    asyncio.run(scenario())


def test_glm_empty_response_preserves_finish_reason_in_export_and_recovery(
    tmp_path: Path,
) -> None:
    class ExhaustedProvider:
        name = "fake"

        async def translate(self, **request) -> providers_mod.TranslationResponse:
            return providers_mod.TranslationResponse(
                text="", resolved_model=request["model"],
                prompt_tokens=419, completion_tokens=4096, finish_reason="length",
            )

    async def scenario() -> None:
        config = config_at(tmp_path)
        manager = SessionManager(config)
        manager.set_journal(SessionJournal(manager.session.id, config))
        dispatcher = TranslationDispatcher(manager, config, ExhaustedProvider())
        manager.set_dispatcher(dispatcher)
        manager.session.status = "listening"
        manager.finalize_segment("이 결과는 추가 검증이 필요합니다.")
        await dispatcher.drain()
        segment = manager.session.segments[0]
        assert segment.translation_status == "failed"
        assert segment.failure_reason == "provider_no_text"
        assert segment.translation_finish_reason == "length"
        assert segment.translation_completion_tokens == 4096
        data = json.loads((Path(export_session(manager.session, config)) / "transcript.json").read_text())
        assert data["segments"][0]["translation_finish_reason"] == "length"
        recovered = run_recovery(config)
        assert recovered.notice is not None
        restored = json.loads(
            (Path(recovered.notice.export_path) / "transcript.json").read_text()
        )
        assert restored["segments"][0]["translation_finish_reason"] == "length"

    asyncio.run(scenario())
