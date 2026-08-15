from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from app.config import AppConfig
from app.translate import TranslationDispatcher
from scripts.resilience_soak import ScriptedTranslationProvider, run_soak


def test_provider_config_refuses_unimplemented_backends() -> None:
    with pytest.raises(ValidationError):
        AppConfig(_env_file=None, TRANSLATION_PROVIDER="unimplemented")


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("TRANSLATION_TIMEOUT_MS", 99),
        ("TRANSLATION_MAX_CONCURRENCY", 0),
        ("TRANSLATION_429_MAX_RETRIES", 11),
        ("TRANSLATION_429_JITTER_FACTOR", 1.1),
    ],
)
def test_resilience_config_bounds(setting: str, value: int | float) -> None:
    with pytest.raises(ValidationError):
        AppConfig(_env_file=None, **{setting: value})


def test_injected_provider_does_not_build_default_client(monkeypatch) -> None:
    class Manager:
        pass

    def forbidden_client(*args, **kwargs):
        raise AssertionError("default provider must not be built")

    monkeypatch.setattr("app.translate.MistralTranslationProvider", forbidden_client)
    config = AppConfig(_env_file=None)
    provider = ScriptedTranslationProvider()

    dispatcher = TranslationDispatcher(Manager(), config, provider=provider)

    assert dispatcher._provider is provider


def test_deterministic_soak_reaches_all_terminal_states() -> None:
    report = asyncio.run(run_soak(250))

    assert report.passed is True
    assert report.segments == 250
    assert report.done == 242
    assert report.timed_out == 5
    assert report.failed == 3
    assert report.pending == 0
    assert report.delivered == 250
    assert report.degraded_source_only == 8
    assert report.duplicates == 0
    assert report.ordered is True
    assert report.provider_calls == report.expected_provider_calls
    assert report.capacity_warnings == 3
    assert 1 <= report.peak_provider_concurrency <= report.max_provider_concurrency
    assert report.active_provider_calls == 0
    assert report.remaining_tasks == 0


def test_soak_report_is_content_free() -> None:
    report = asyncio.run(run_soak(25))
    output = json.dumps(report.to_dict())

    assert "Synthetic segment" not in output
    assert "Synthetic translated caption" not in output
    assert "MISTRAL_API_KEY" not in output
    assert "source_text" not in output
    assert "translated_text" not in output
