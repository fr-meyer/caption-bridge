"""Combined draft settings survive a session start and export."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import app.ws as ws
from app.config import AppConfig
from app.exporter import export_session
from app.journal import SessionJournal
from app.state import SessionManager


def test_combined_settings_are_recorded(monkeypatch, tmp_path: Path) -> None:
    async def scenario() -> None:
        config = AppConfig(
            _env_file=None, MISTRAL_TTS_ENABLED=False,
            JOURNAL_DIR=str(tmp_path / "journal"),
            EXPORT_DIR=str(tmp_path / "exports"),
            RECOVERY_EXPORT_DIR=str(tmp_path / "recovered"),
            RELIABILITY_DIR=str(tmp_path / "reliability"),
        )
        manager = SessionManager(config)
        manager.session.status = "idle_ready"
        manager.set_journal(SessionJournal(manager.session.id, config))

        async def start() -> None:
            manager.set_status("listening")

        monkeypatch.setattr(ws, "manager", manager)
        monkeypatch.setattr(ws, "start_pipeline", start)
        await ws._handle_start(
            {"type": "start", "caption_profile": "shorter",
             "translation_model": "mistral-medium-latest",
             "translation_reasoning_effort": "high"},
            asyncio.Queue(), ws._OutboundObsState(),
        )
        assert manager.session.caption_profile.id == "shorter"
        assert manager.session.translation_model == "mistral-medium-latest"
        assert manager.session.translation_reasoning_effort == "high"
        manager.set_status("session_ended")
        exported = Path(export_session(manager.session, config))
        data = json.loads((exported / "transcript.json").read_text())
        assert data["caption_profile"]["id"] == "shorter"
        assert data["translation_model_at_export"] == "mistral-medium-latest"
        assert data["translation_reasoning_effort_at_export"] == "high"
        records = [json.loads(line) for line in next((tmp_path / "journal").glob("*.jsonl")).read_text().splitlines()]
        assert {record["type"] for record in records} >= {"session_caption_profile", "session_translation_model"}
        assert next(record for record in records if record["type"] == "session_translation_model")["reasoning_effort"] == "high"
    asyncio.run(scenario())



def test_live_model_change_keeps_timing_profile_and_caption_provenance(
    monkeypatch, tmp_path: Path,
) -> None:
    from app.providers import TranslationResponse
    from app.translate import TranslationDispatcher

    class RecordingProvider:
        name = "synthetic"

        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def translate(self, **request) -> TranslationResponse:
            self.calls.append(request)
            return TranslationResponse(
                text="A readable English caption.",
                resolved_model=request["model"],
                prompt_tokens=12,
                completion_tokens=6,
            )

    async def scenario() -> None:
        config = AppConfig(
            _env_file=None, MISTRAL_TTS_ENABLED=False,
            JOURNAL_DIR=str(tmp_path / "journal"),
            EXPORT_DIR=str(tmp_path / "exports"),
            RECOVERY_EXPORT_DIR=str(tmp_path / "recovered"),
            RELIABILITY_DIR=str(tmp_path / "reliability"),
        )
        manager = SessionManager(config)
        manager.session.status = "idle_ready"
        manager.set_journal(SessionJournal(manager.session.id, config))
        provider = RecordingProvider()
        dispatcher = TranslationDispatcher(manager, config, provider)
        manager.set_dispatcher(dispatcher)

        async def start() -> None:
            manager.set_status("listening")

        monkeypatch.setattr(ws, "manager", manager)
        monkeypatch.setattr(ws, "start_pipeline", start)
        queue: asyncio.Queue = asyncio.Queue()
        obs = ws._OutboundObsState()
        await ws._handle_start(
            {"type": "start", "target_language": "en",
             "caption_profile": "shorter",
             "translation_model": "mistral-small-latest",
             "translation_reasoning_effort": "default"},
            queue, obs,
        )
        assert manager.session.status == "listening"
        manager.finalize_segment("첫 번째 결과입니다.")
        await ws._handle_set_translation_model(
            {"type": "set_translation_model", "model": "zai-glm-5-3",
             "reasoning_effort": "high"},
            queue, obs,
        )
        manager.finalize_segment("두 번째 결과입니다.")
        await dispatcher.drain()
        assert manager.session.caption_profile.id == "shorter"
        assert [call["model"] for call in provider.calls] == [
            "mistral-small-latest", "zai-glm-5-3",
        ]
        assert [call["max_tokens"] for call in provider.calls] == [200, 4096]
        assert "reasoning_effort" not in provider.calls[0]
        assert provider.calls[1]["reasoning_effort"] == "high"
        assert [segment.translation_status for segment in manager.session.segments] == [
            "done", "done",
        ]
        manager.set_status("session_ended")
        exported = Path(export_session(manager.session, config))
        data = json.loads((exported / "transcript.json").read_text())
        assert data["caption_profile"]["id"] == "shorter"
        assert [item["translation_model"] for item in data["segments"]] == [
            "mistral-small-latest", "zai-glm-5-3",
        ]
        assert [item["translation_reasoning_effort"] for item in data["segments"]] == [
            "default", "high",
        ]
        assert [item["translation_max_tokens"] for item in data["segments"]] == [
            200, 4096,
        ]
        assert data["translation_model_changes"][0]["applies_from_seq"] == 2
        assert data["translation_model_changes"][0]["reasoning_effort"] == "high"

    asyncio.run(scenario())
