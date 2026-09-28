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
             "translation_model": "mistral-medium-latest"},
            asyncio.Queue(), ws._OutboundObsState(),
        )
        assert manager.session.caption_profile.id == "shorter"
        assert manager.session.translation_model == "mistral-medium-latest"
        manager.set_status("session_ended")
        exported = Path(export_session(manager.session, config))
        data = json.loads((exported / "transcript.json").read_text())
        assert data["caption_profile"]["id"] == "shorter"
        assert data["translation_model_at_export"] == "mistral-medium-latest"
        records = [json.loads(line) for line in next((tmp_path / "journal").glob("*.jsonl")).read_text().splitlines()]
        assert {record["type"] for record in records} >= {"session_caption_profile", "session_translation_model"}
    asyncio.run(scenario())
