"""Reliable startup, explicit override, reset and private provenance."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import app.ws as ws
from app.config import AppConfig
from app.exporter import export_session
from app.journal import SessionJournal
from app.state import SessionManager


@pytest.mark.parametrize("override", [None, "mistral-small-latest", "zai-glm-5-3"])
def test_startup_override_and_explicit_selection_survive_export_but_reset(
    monkeypatch, tmp_path: Path, override: str | None,
) -> None:
    if override is None:
        monkeypatch.delenv("MISTRAL_TRANSLATE_MODEL", raising=False)
    else:
        monkeypatch.setenv("MISTRAL_TRANSLATE_MODEL", override)
    config = AppConfig(
        _env_file=None, MISTRAL_TTS_ENABLED=False,
        JOURNAL_DIR=str(tmp_path / "journal"), EXPORT_DIR=str(tmp_path / "exports"),
        RELIABILITY_DIR=str(tmp_path / "reliability"),
    )
    expected = override or "mistral-medium-latest"
    assert config.translate_model == expected

    async def scenario() -> None:
        manager = SessionManager(config)
        manager.session.status = "idle_ready"
        manager.set_journal(SessionJournal(manager.session.id, config))

        async def start() -> None:
            manager.set_status("listening")

        monkeypatch.setattr(ws, "manager", manager)
        monkeypatch.setattr(ws, "start_pipeline", start)
        await ws._handle_start({"type": "start"}, asyncio.Queue(), ws._OutboundObsState())
        assert manager.session.translation_model == expected
        manager.finalize_segment("첫 결과입니다.")
        await ws._handle_set_translation_model(
            {"type": "set_translation_model", "model": "zai-glm-5-3", "reasoning_effort": "high"},
            asyncio.Queue(), ws._OutboundObsState(),
        )
        manager.finalize_segment("다음 결과입니다.")
        manager.set_status("session_ended")
        data = json.loads((Path(export_session(manager.session, config)) / "transcript.json").read_text())
        assert [s["translation_model"] for s in data["segments"]] == [expected, "zai-glm-5-3"]
        assert data["segments"][1]["translation_max_tokens"] == 4096
        assert data["segments"][1]["translation_reasoning_effort"] == "high"
        await manager.reset()
        assert manager.session.translation_model == expected
        assert manager.session.translation_reasoning_effort == "default"

    asyncio.run(scenario())
