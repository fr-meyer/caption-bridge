"""Provider-free session profile validation, pipeline and recovery contracts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

import app.ws as ws
from app.config import AppConfig
from app.exporter import export_session
from app.journal import SessionJournal, run_recovery
from app.profiles import ERROR_MESSAGE, resolve_profile
from app.state import Segment, SessionManager


def config_at(path: Path) -> AppConfig:
    return AppConfig(
        _env_file=None, MISTRAL_TTS_ENABLED=False,
        journal_dir=str(path / "journal"), export_dir=str(path / "exports"),
        recovery_export_dir=str(path / "recovered"), reliability_dir=str(path / "reliability"),
    )


@pytest.mark.parametrize("raw", [None, {}, [], True, 1, "", "private-invalid-choice", {"id": "shorter"}])
def test_invalid_start_profile_has_no_side_effects(raw, monkeypatch, tmp_path, caplog) -> None:
    async def scenario() -> None:
        manager = SessionManager(config_at(tmp_path))
        manager.session.status = "idle_ready"
        old_profile = manager.session.caption_profile
        start = AsyncMock()
        monkeypatch.setattr(ws, "manager", manager)
        monkeypatch.setattr(ws, "start_pipeline", start)
        queue = asyncio.Queue()
        await ws._handle_start(
            {"target_language": "fr", "caption_profile": raw,
             "glossary": [{"source": "synthetic", "preferred": "term"}]},
            queue, ws._OutboundObsState(),
        )
        start.assert_not_awaited()
        assert manager.session.target_language == "en"
        assert manager.session.caption_profile == old_profile
        assert manager.session.glossary is None
        assert queue.get_nowait()[0]["message"] == ERROR_MESSAGE
        assert "private-invalid-choice" not in caplog.text
    asyncio.run(scenario())


def test_current_profile_preserves_custom_values_and_is_immutable(tmp_path) -> None:
    config = config_at(tmp_path)
    config.pause_timeout_ms = 3500
    config.fragment_max_hold_ms = 0
    manager = SessionManager(config)
    profile = manager.session.caption_profile
    assert profile.pause_timeout_ms == 3500
    assert profile.fragment_max_hold_ms == 0
    config.pause_timeout_ms = 100
    assert profile.pause_timeout_ms == 3500
    with pytest.raises(ValidationError):
        profile.id = "longer"


def test_start_freezes_journals_exports_and_new_session_resets(monkeypatch, tmp_path) -> None:
    async def scenario() -> None:
        config = config_at(tmp_path)
        manager = SessionManager(config)
        manager.session.status = "idle_ready"
        manager.set_journal(SessionJournal(manager.session.id, config))
        async def start() -> None:
            manager.set_status("listening")
        monkeypatch.setattr(ws, "manager", manager)
        monkeypatch.setattr(ws, "start_pipeline", start)
        await ws._handle_start(
            {"target_language": "fr", "caption_profile": "longer"},
            asyncio.Queue(), ws._OutboundObsState(),
        )
        profile = manager.session.caption_profile.model_dump(mode="json")
        assert profile == {"id": "longer", "pause_timeout_ms": 2200, "fragment_max_hold_ms": 5000}
        config.pause_timeout_ms = 4100
        manager.set_status("reconnecting")
        manager.set_target_language("en")
        manager.set_status("listening")
        assert manager.get_snapshot()["caption_profile"] == profile
        manager.set_status("session_ended")
        records = [json.loads(line) for line in next((tmp_path / "journal").glob("*.jsonl")).read_text().splitlines()]
        assert len([r for r in records if r["type"] == "session_caption_profile"]) == 1
        exported = Path(export_session(manager.session, config))
        assert json.loads((exported / "transcript.json").read_text())["caption_profile"] == profile
        assert "pause 2200 ms, fragment hold 5000 ms" in (exported / "transcript.txt").read_text()
        await manager.reset()
        assert manager.session.caption_profile.id == "current"
        assert manager.session.caption_profile.pause_timeout_ms == 4100
        assert manager.session.target_language == "en"
    asyncio.run(scenario())


def test_omitted_profile_keeps_existing_start_behavior(monkeypatch, tmp_path) -> None:
    async def scenario() -> None:
        manager = SessionManager(config_at(tmp_path))
        manager.config.pause_timeout_ms = 3700
        manager.config.fragment_max_hold_ms = 0
        manager.session.status = "idle_ready"
        start = AsyncMock()
        monkeypatch.setattr(ws, "manager", manager)
        monkeypatch.setattr(ws, "start_pipeline", start)
        await ws._handle_start({}, asyncio.Queue(), ws._OutboundObsState())
        start.assert_awaited_once()
        assert manager.session.caption_profile.pause_timeout_ms == 3700
        assert manager.session.caption_profile.fragment_max_hold_ms == 0
    asyncio.run(scenario())


def test_pipeline_reconnect_uses_frozen_values_and_one_stream(monkeypatch, tmp_path) -> None:
    import app.main as main
    async def scenario() -> None:
        config = config_at(tmp_path)
        manager = SessionManager(config)
        manager.session.caption_profile = resolve_profile("shorter", config)
        manager.session.status = "reconnecting"
        config.pause_timeout_ms = 7900
        config.fragment_max_hold_ms = 14000
        received = []
        stream_configs = []
        class Audio:
            def __init__(self, **_kwargs): pass
            def start(self): pass
            def stop(self): pass
            async def stream(self):
                if False:
                    yield b""
        from app.boundary import BoundaryDetector
        def detector(**kwargs):
            received.append(kwargs)
            return BoundaryDetector(**kwargs)
        async def transcribe(**kwargs):
            stream_configs.append(kwargs["config"])
        monkeypatch.setattr(main, "settings", config)
        monkeypatch.setattr(main, "manager", manager)
        monkeypatch.setattr(main, "AudioCapture", Audio)
        monkeypatch.setattr(main, "BoundaryDetector", detector)
        monkeypatch.setattr(main, "transcribe", transcribe)
        await main._start_pipeline()
        await asyncio.sleep(0)
        try:
            assert received[0]["pause_timeout_s"] == 0.8
            assert received[0]["fragment_max_hold_s"] == 2.0
            assert len(stream_configs) == 1
            assert stream_configs[0].target_streaming_delay_ms == config.target_streaming_delay_ms
        finally:
            await main._teardown_pipeline()
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["valid", "legacy", "invalid"])
def test_recovery_keeps_valid_profile_and_does_not_invent_legacy_timing(kind, tmp_path, caplog) -> None:
    config = config_at(tmp_path)
    journal = SessionJournal(kind, config)
    journal.record_session_started()
    if kind == "valid":
        journal.record_caption_profile(resolve_profile("longer", config))
    elif kind == "invalid":
        journal._write({"type": "session_caption_profile", "caption_profile": {
            "id": "private-invalid-profile", "pause_timeout_ms": "800", "fragment_max_hold_ms": 2000,
        }})
    journal.record_segment_created(Segment(seq=1, source_text="Synthetic source.", segment_kind="complete"))
    result = run_recovery(config)
    assert result.notice.status == "success"
    data = json.loads((Path(result.notice.export_path) / "transcript.json").read_text())
    assert data["caption_profile"] == (resolve_profile("longer", config).model_dump(mode="json") if kind == "valid" else None)
    assert data["segments"][0]["failure_reason"] == "recovered_pending"
    assert "private-invalid-profile" not in caplog.text


@pytest.mark.parametrize("choice,ceiling", [("current", 4500), ("shorter", 2800), ("longer", 7200)])
def test_presets_keep_semantic_boundaries_and_forced_release_bounded(choice, ceiling, tmp_path) -> None:
    from scripts.benchmark_segmentation import run_benchmark
    profile = resolve_profile(choice, config_at(tmp_path))
    report = asyncio.run(run_benchmark(
        pause_timeout_ms=profile.pause_timeout_ms,
        additional_hold_ms=profile.fragment_max_hold_ms,
        max_policy_delay_ms=ceiling,
    ))
    assert report.cases == 10
    assert report.passed
    assert report.unexpected_standalone_fragments == 0
    assert report.delayed_clear_boundaries == 0
    assert report.policy_max_translation_boundary_delay_ms <= ceiling
