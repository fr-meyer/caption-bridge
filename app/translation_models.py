"""Allowed text-translation models for explicit session selection."""

from __future__ import annotations

import time

from app.config import AppConfig
from app.translation_catalogue import ModelCatalogue

catalogue = ModelCatalogue()
# Public evidence checked 2026-11-17, not account or live qualification.
# Overview conflicts with the Medium alias guide: fail closed, preserve selection.
LIFECYCLE = {
    "mistral-large-latest": {"status": "active", "family": "large", "alias": "mistral-large-latest"},
    "mistral-large-4": {"status": "active", "family": "large", "release": 4},
    "mistral-small-latest": {"status": "active", "family": "small", "alias": "mistral-small-latest"},
    "mistral-medium-latest": {"status": "conflicting", "family": "medium"},
    "zai-glm-5-3": {"status": "active", "family": "glm", "release": 53},
}
EXECUTION_POLICIES = {
    "mistral-medium-latest": {"efforts": ["default", "high"]},
    "mistral-small-latest": {"efforts": ["default", "high"]},
    "mistral-large-latest": {"efforts": ["default"]},
    "mistral-large-4": {"efforts": ["default"]},
    "zai-glm-5-3": {"efforts": ["default", "high"]},
}

_HIGH_REASONING_MODELS = frozenset({
    "mistral-medium-latest", "mistral-small-latest", "zai-glm-5-3",
})
ERROR_MESSAGE = "Choose a listed translation model."
EFFORT_ERROR_MESSAGE = "Choose an available translation thinking level."
DEFAULT_REASONING_EFFORT = "default"
HIGH_REASONING_EFFORT = "high"
TRANSLATION_PROMPT_VERSION = "academic-caption-v1"


def translation_output_limit(model: str, effort: str) -> int:
    # A live draft check also exhausted 1024 tokens on thinking without an answer.
    if model in {"zai-glm-5-3", "mistral-large-4", "mistral-large-latest"}:
        # GLM may spend the entire completion allowance on thinking.
        return 4096
    if effort == HIGH_REASONING_EFFORT:
        return 1024
    return 200


def available_translation_models(config: AppConfig) -> list[dict]:
    choices = catalogue.snapshot()["models"]
    # The source evidence packet expires on 2026-11-24 UTC. No retired fallback.
    if time.time() >= 1795478400:
        choices = [dict(row, enabled=False, reason="public_lifecycle_evidence_expired") for row in choices]
    if config.translate_model not in {row["id"] for row in choices}:
        choices = [dict(id=config.translate_model, label=config.translate_model,
                        enabled=False, reason="account_catalogue_unverified",
                        efforts=["default"])] + choices
    return choices


def validate_reasoning_effort(raw: object, model: str) -> str:
    """Only expose the Mistral request value used by its Vibe adapter."""
    allowed = {DEFAULT_REASONING_EFFORT}
    if model in _HIGH_REASONING_MODELS:
        allowed.add(HIGH_REASONING_EFFORT)
    if not isinstance(raw, str) or raw not in allowed:
        raise ValueError(EFFORT_ERROR_MESSAGE)
    return raw


def validate_translation_model(raw: object, config: AppConfig) -> str:
    if not isinstance(raw, str) or raw not in {
        choice["id"] for choice in available_translation_models(config) if choice.get("enabled")
    }:
        raise ValueError(ERROR_MESSAGE)
    return raw
