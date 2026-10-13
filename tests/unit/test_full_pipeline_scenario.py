from __future__ import annotations

import asyncio
import json

import pytest

import app.ws as ws_module
from scripts import full_pipeline_scenario as scenario_module
from scripts.full_pipeline_scenario import run_full_pipeline_scenario


def test_deterministic_full_pipeline_scenario() -> None:
    report = asyncio.run(run_full_pipeline_scenario())

    assert report.passed is True
    assert (report.segments, report.done, report.timed_out, report.failed) == (
        6,
        4,
        1,
        1,
    )
    assert report.pending == 0
    assert report.captions == 6
    assert report.duplicates == 0
    assert report.ordered is True
    assert report.reconnect_fragments == 1
    assert report.reconnect_attempts == 2
    assert report.reconnect_recovered == 1
    assert report.capacity_warnings == 1
    assert report.translation_provider_calls == 7
    assert report.tts_provider_calls == 5
    assert report.tts_retries == 1
    assert report.tts_recovered == 1
    assert report.tts_guardrail_skips == 1
    assert report.tts_audio_completed == 3
    assert report.browser_queue_depth == 4
    assert report.browser_queue_bounded is True
    assert report.browser_queue_coalesced == 1
    assert report.browser_queue_dropped == 2
    assert report.browser_critical_preserved is True
    assert report.owner_conflict_rejected is True
    assert report.owner_retained_on_conflict is True
    assert report.reconnect_audio_relocked is True
    assert report.reconnect_snapshot_preserved is True
    assert report.export_files == 2
    assert report.export_statuses_preserved is True
    assert report.journal_stopped is True
    assert report.journal_exported is True
    assert report.remaining_translation_tasks == 0
    assert report.remaining_tts_jobs == 0
    assert report.remaining_tts_tasks == 0
    assert report.remaining_browser_tasks == 0
    assert report.remaining_lifecycle_tasks == 0
    assert report.temporary_artifacts_removed is True


def test_full_pipeline_report_is_content_free() -> None:
    report = asyncio.run(run_full_pipeline_scenario())
    output = json.dumps(report.to_dict())

    assert "Synthetic segment" not in output
    assert "Synthetic translated caption" not in output
    assert "synthetic-audio" not in output
    assert "MISTRAL_API_KEY" not in output
    assert "source_text" not in output
    assert "translated_text" not in output
    assert "caption-bridge-full-pipeline" not in output
    assert "session_id" not in output


@pytest.mark.parametrize("fail_after_ownership", [False, True])
def test_scenario_restores_connection_state(monkeypatch, fail_after_ownership) -> None:
    original_owner = object()
    monkeypatch.setattr(ws_module, "_active_connection", original_owner)
    monkeypatch.setattr(ws_module, "_connection_counter", 212)
    original_manager = ws_module.manager
    original_settings = ws_module.settings
    original_metrics = ws_module._ws_metrics
    if fail_after_ownership:
        ownership_scenario = scenario_module._test_websocket_ownership

        async def fail_after_connections(*args):
            await ownership_scenario(*args)
            raise RuntimeError("synthetic scenario failure")

        monkeypatch.setattr(scenario_module, "_test_websocket_ownership", fail_after_connections)
        with pytest.raises(RuntimeError, match="synthetic scenario failure"):
            asyncio.run(run_full_pipeline_scenario())
    else:
        assert asyncio.run(run_full_pipeline_scenario()).passed

    assert ws_module._active_connection is original_owner
    assert ws_module._connection_counter == 212
    assert ws_module.manager is original_manager
    assert ws_module.settings is original_settings
    assert ws_module._ws_metrics is original_metrics
