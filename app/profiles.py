"""Bounded caption timing choices, resolved once per session."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config import AppConfig

ProfileId = Literal["current", "shorter", "longer"]
ERROR_MESSAGE = "Choose Current settings, Shorter pauses or Longer pauses."
_CHOICES = (
    ("current", "Current settings", "Use the operator's configured caption timing."),
    ("shorter", "Shorter pauses", "Show captions after shorter pauses; phrases may split more often and increase translation cost."),
    ("longer", "Longer pauses", "Wait longer through pauses; captions may arrive later."),
)


class CaptionProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: ProfileId
    pause_timeout_ms: int = Field(strict=True, ge=100, le=10000)
    fragment_max_hold_ms: int = Field(strict=True, ge=0, le=15000)


def resolve_profile(raw: object, config: AppConfig) -> CaptionProfile:
    if not isinstance(raw, str) or raw not in {"current", "shorter", "longer"}:
        raise ValueError(ERROR_MESSAGE)
    pause, hold = {
        "current": (config.pause_timeout_ms, config.fragment_max_hold_ms),
        "shorter": (800, 2000),
        "longer": (2200, 5000),
    }[raw]
    return CaptionProfile(id=raw, pause_timeout_ms=pause, fragment_max_hold_ms=hold)


def available_profiles(config: AppConfig) -> list[dict]:
    return [
        {**resolve_profile(key, config).model_dump(mode="json"),
         "label": label, "description": description}
        for key, label, description in _CHOICES
    ]
