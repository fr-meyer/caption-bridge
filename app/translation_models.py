"""Allowed text-translation models for explicit session selection."""

from __future__ import annotations

from app.config import AppConfig

_CHOICES = (
    ("zai-glm-5-3", "Z.ai GLM 5.3 (preview)"),
    ("mistral-small-latest", "Mistral Small (latest)"),
    ("mistral-medium-latest", "Mistral Medium (latest)"),
)
ERROR_MESSAGE = "Choose a listed translation model."
EFFORT_ERROR_MESSAGE = "Choose an available translation thinking level."
DEFAULT_REASONING_EFFORT = "default"
HIGH_REASONING_EFFORT = "high"
TRANSLATION_PROMPT_VERSION = "academic-caption-v1"


def translation_output_limit(model: str, effort: str) -> int:
    # A live draft check also exhausted 1024 tokens on thinking without an answer.
    if model == "zai-glm-5-3":
        # GLM may spend the entire completion allowance on thinking.
        return 4096
    if effort == HIGH_REASONING_EFFORT:
        return 1024
    return 200


def available_translation_models(config: AppConfig) -> list[dict[str, str]]:
    choices = [{"id": key, "label": label} for key, label in _CHOICES]
    if config.translate_model not in {choice["id"] for choice in choices}:
        choices.insert(0, {
            "id": config.translate_model,
            "label": "Configured default",
        })
    return choices


def validate_reasoning_effort(raw: object, model: str) -> str:
    """Only expose the Mistral request value used by its Vibe adapter."""
    allowed = {DEFAULT_REASONING_EFFORT}
    if model in {item[0] for item in _CHOICES}:
        allowed.add(HIGH_REASONING_EFFORT)
    if not isinstance(raw, str) or raw not in allowed:
        raise ValueError(EFFORT_ERROR_MESSAGE)
    return raw


def validate_translation_model(raw: object, config: AppConfig) -> str:
    if not isinstance(raw, str) or raw not in {
        choice["id"] for choice in available_translation_models(config)
    }:
        raise ValueError(ERROR_MESSAGE)
    return raw
