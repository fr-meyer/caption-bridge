"""Tests for bounded translation-repair configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import AppConfig


def test_translation_repair_budget_defaults_to_one() -> None:
    config = AppConfig(_env_file=None)

    assert config.transcript_retention_days == 30
    assert config.translation_repair_max_attempts == 1


@pytest.mark.parametrize("value", [-1, 2])
def test_translation_repair_budget_rejects_unbounded_values(value: int) -> None:
    with pytest.raises(ValidationError):
        AppConfig(
            _env_file=None,
            TRANSLATION_REPAIR_MAX_ATTEMPTS=value,
        )


@pytest.mark.parametrize("value", [0, 3651])
def test_transcript_retention_rejects_unsafe_values(value: int) -> None:
    with pytest.raises(ValidationError):
        AppConfig(
            _env_file=None,
            TRANSCRIPT_RETENTION_DAYS=value,
        )


def test_fragment_merge_defaults_are_bounded() -> None:
    config = AppConfig(_env_file=None)

    assert config.fragment_merge_enabled is True
    assert config.fragment_max_hold_ms == 3000
    assert config.fragment_min_chars == 15
    assert config.fragment_min_tokens == 3


def test_fragment_merge_can_be_disabled_explicitly() -> None:
    config = AppConfig(
        _env_file=None,
        FRAGMENT_MERGE_ENABLED="false",
        FRAGMENT_MAX_HOLD_MS=0,
    )

    assert config.fragment_merge_enabled is False
    assert config.fragment_max_hold_ms == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("PAUSE_TIMEOUT_MS", 99),
        ("PAUSE_TIMEOUT_MS", 10001),
        ("FRAGMENT_MAX_HOLD_MS", -1),
        ("FRAGMENT_MAX_HOLD_MS", 15001),
        ("FRAGMENT_MIN_CHARS", 0),
        ("FRAGMENT_MIN_CHARS", 501),
        ("FRAGMENT_MIN_TOKENS", 0),
        ("FRAGMENT_MIN_TOKENS", 51),
    ],
)
def test_fragment_configuration_rejects_unbounded_values(
    field: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        AppConfig(_env_file=None, **{field: value})
