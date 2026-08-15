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
