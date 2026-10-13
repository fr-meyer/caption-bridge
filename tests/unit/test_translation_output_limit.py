"""Truncated answers must not become successful captions or speech."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.config import AppConfig
from app.exporter import export_session
from app.journal import SessionJournal, run_recovery
from app.providers import TranslationResponse
from app.state import SessionManager
from app.translate import TranslationDispatcher


def config_at(path: Path, model: str) -> AppConfig:
    return AppConfig(
        _env_file=None, MISTRAL_TRANSLATE_MODEL=model,
        JOURNAL_DIR=str(path / "journal"), EXPORT_DIR=str(path / "exports"),
        RECOVERY_EXPORT_DIR=str(path / "recovered"),
        RELIABILITY_DIR=str(path / "reliability"),
        TRANSLATION_REPAIR_MAX_ATTEMPTS=0,
    )


@pytest.mark.parametrize("model", ["zai-glm-5-3", "mistral-medium-latest"])
def test_truncated_answer_fails_once_without_speech_and_unblocks_next_caption(
    tmp_path: Path, model: str,
) -> None:
    class Provider:
        name = "synthetic"
        calls = 0

        async def translate(self, **request) -> TranslationResponse:
            self.calls += 1
            return TranslationResponse(
                text="These results are significant." if self.calls == 1 else "Validation is needed.",
                resolved_model=request["model"], prompt_tokens=30,
                completion_tokens=request["max_tokens"] if self.calls == 1 else 8,
                finish_reason="length" if self.calls == 1 else "stop",
            )

    async def scenario() -> None:
        config = config_at(tmp_path, model)
        manager = SessionManager(config)
        manager.set_journal(SessionJournal(manager.session.id, config))
        speech = MagicMock()
        manager.set_tts_dispatcher(speech)
        provider = Provider()
        dispatcher = TranslationDispatcher(manager, config, provider)
        manager.set_dispatcher(dispatcher)
        events = []
        manager.subscribe(events.append)
        manager.session.status = "listening"
        manager.finalize_segment("이 결과는 통계적으로 유의미하지만 추가 검증이 필요합니다.")
        manager.finalize_segment("검증이 필요합니다.")
        await dispatcher.drain()
        first, second = manager.session.segments
        assert provider.calls == 2
        assert first.translation_status == "failed"
        assert first.failure_reason == "provider_output_limit"
        assert first.translated_text is None
        assert first.translation_finish_reason == "length"
        assert first.translation_completion_tokens == first.translation_max_tokens
        assert second.translation_status == "done"
        assert [event["seq"] for event in events if event["type"] == "caption"] == [1, 2]
        speech.enqueue_live.assert_called_once_with(second)
        data = json.loads((Path(export_session(manager.session, config)) / "transcript.json").read_text())
        assert data["segments"][0]["failure_reason"] == "provider_output_limit"
        assert data["segments"][0]["translation_finish_reason"] == "length"
        recovered = run_recovery(config)
        assert recovered.notice is not None
        restored = json.loads((Path(recovered.notice.export_path) / "transcript.json").read_text())
        assert restored["segments"][0]["failure_reason"] == "provider_output_limit"

    asyncio.run(scenario())


def test_truncated_quality_repair_cannot_replace_original_caption(tmp_path: Path) -> None:
    class Provider:
        name = "synthetic"
        calls = 0

        async def translate(self, **request) -> TranslationResponse:
            self.calls += 1
            return TranslationResponse(
                text="Caption: Further validation is needed." if self.calls == 1
                else "These results are significant.",
                finish_reason="stop" if self.calls == 1 else "length",
                completion_tokens=12 if self.calls == 1 else request["max_tokens"],
            )

    async def scenario() -> None:
        config = config_at(tmp_path, "zai-glm-5-3")
        config.translation_repair_max_attempts = 1
        manager = SessionManager(config)
        provider = Provider()
        dispatcher = TranslationDispatcher(manager, config, provider)
        manager.set_dispatcher(dispatcher)
        manager.session.status = "listening"
        manager.finalize_segment("이 결과는 통계적으로 유의미하지만 추가 검증이 필요합니다.")
        await dispatcher.drain()
        segment = manager.session.segments[0]
        assert provider.calls == 2
        assert segment.translated_text == "Caption: Further validation is needed."
        assert segment.quality.repair_succeeded is False
        assert segment.quality.final_flagged is True
        assert segment.translation_finish_reason == "length"

    asyncio.run(scenario())
