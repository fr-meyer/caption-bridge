"""Allowed text-translation models for explicit session selection."""

from __future__ import annotations

from app.config import AppConfig

_CHOICES = (
    ("mistral-small-latest", "Mistral Small (latest)"),
    ("mistral-medium-latest", "Mistral Medium (latest)"),
    ("zai-glm-5-3", "Z.ai GLM 5.3 (preview)"),
)
ERROR_MESSAGE = "Choose a listed translation model."
TRANSLATION_PROMPT_VERSION = "academic-caption-v1"


def available_translation_models(config: AppConfig) -> list[dict[str, str]]:
    choices = [{"id": key, "label": label} for key, label in _CHOICES]
    if config.translate_model not in {choice["id"] for choice in choices}:
        choices.insert(0, {
            "id": config.translate_model,
            "label": "Configured default",
        })
    return choices


def validate_translation_model(raw: object, config: AppConfig) -> str:
    if not isinstance(raw, str) or raw not in {
        choice["id"] for choice in available_translation_models(config)
    }:
        raise ValueError(ERROR_MESSAGE)
    return raw
