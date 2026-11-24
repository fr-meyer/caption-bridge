"""Allowed text-translation models for explicit session selection."""

from __future__ import annotations

import time

from app.config import AppConfig
from app.model_lifecycle import lifecycle_metadata
from app.translation_catalogue import ModelCatalogue


class TranslationModelCatalogue(ModelCatalogue):
    """Reuse reconciliation/cache ownership, add translation privacy admission."""

    def snapshot(self):
        snapshot = super().snapshot()
        snapshot["models"] = [_execution_choice(row) for row in snapshot["models"]]
        return snapshot


catalogue = TranslationModelCatalogue(timeout=10)
# Public model declarations checked 2026-11-24. Account availability and
# applicable privacy terms remain independent from a GA vendor badge.
# Medium 3.5 explicitly deprecated 2026-10-31; preserve family, never substitute.
LIFECYCLE = {
    "mistral-large-latest": {"status": "active", "family": "large", "alias": "mistral-large-latest"},
    "mistral-large-4": {"status": "active", "family": "large", "release": 20261105},
    "mistral-large-4-0": {"status": "active", "family": "large", "release": 20261105},
    "mistral-small-latest": {"status": "active", "family": "small", "alias": "mistral-small-latest"},
    "mistral-small-2603": {"status": "active", "family": "small", "release": 202603},
    "mistral-medium-latest": {"status": "deprecated", "family": "medium"},
    "mistral-medium-3": {"status": "deprecated", "family": "medium"},
    "mistral-medium-3-5": {"status": "deprecated", "family": "medium", "release": 20260428},
    "zai-glm-5-3": {"status": "active", "family": "glm", "variant": "standard", "release": 53},
    "zai-glm-5": {"status": "active", "family": "glm", "variant": "standard", "alias": "zai-glm-5"},
    "zai-glm-latest": {"status": "active", "family": "glm", "variant": "standard", "alias": "zai-glm-latest"},
    "zai-glm-5-3-flash": {"status": "active", "family": "glm-flash", "variant": "flash", "release": 20261022},
    "deepseek-v4-1-flash-1017": {"status": "preview", "family": "deepseek-flash", "release": 20261028},
    "zai-glm-5-2": {"status": "deprecated", "family": "glm", "release": 52},
    "mistral-large-2512": {"status": "deprecated", "family": "large", "release": 20251201},
}
_SOURCE_PAGES = {
    "large": "mistral-large-4-0", "small": "mistral-small-4-0-26-03",
    "medium": "mistral-medium-3-5-26-04", "glm": "zai-glm-5-3",
    "glm-flash": "zai-glm-5-3-flash", "deepseek-flash": "deepseek-v4-flash-1017",
}
# Additional currently active code/compact/audio-understanding chat families.
# Identifiers and rolling aliases are literal names from their official cards.
for _family, _page, _version, _alias in [
    ("codestral", "codestral-25-08", "codestral-2508", "codestral-latest"),
    ("ministral-3b", "ministral-3-3b-25-12", "ministral-3b-2512", "ministral-3b-latest"),
    ("ministral-8b", "ministral-3-8b-25-12", "ministral-8b-2512", "ministral-8b-latest"),
    ("ministral-14b", "ministral-3-14b-25-12", "ministral-14b-2512", "ministral-14b-latest"),
    ("voxtral-small", "voxtral-small-25-07", "voxtral-small-2507", "voxtral-small-latest"),
]:
    _SOURCE_PAGES[_family] = _page
    LIFECYCLE[_version] = {"status": "active", "family": _family, "release": 1}
    LIFECYCLE[_alias] = {"status": "active", "family": _family, "alias": _alias}

for _model, _evidence in LIFECYCLE.items():
    _evidence["source"] = "https://docs.mistral.ai/models/" + _SOURCE_PAGES[_evidence["family"]]
    _evidence["refresh_public"] = _evidence["status"] in {"active", "preview", "labs"}
    _evidence.update(lifecycle_metadata(_evidence["status"]))
    if _model in {"zai-glm-5-2", "mistral-large-2512", "mistral-medium-3"}:
        _evidence["source"] = "https://docs.mistral.ai/models"

# All use the existing Mistral text-chat adapter. Third-party models are enabled
# only with account completion_chat capability AND eligible lifecycle/privacy.
# A request budget is not admission: Preview/Labs contracts remain disabled.
# No undocumented effort is sent.
EXECUTION_POLICIES = {
    "mistral-medium-latest": {"efforts": ["default", "high"], "max_tokens": 200},
    "mistral-small-latest": {"efforts": ["default", "high"], "max_tokens": 200},
    "mistral-small-2603": {"efforts": ["default", "high"], "max_tokens": 200},
    "mistral-large-latest": {"efforts": ["default"], "max_tokens": 4096},
    "mistral-large-4": {"efforts": ["default"], "max_tokens": 4096},
    "mistral-large-4-0": {"efforts": ["default"], "max_tokens": 4096},
    "zai-glm-5-3": {"efforts": ["default", "high"], "max_tokens": 4096},
    # GLM aliases have public identity evidence, but no execution policies until
    # the coordinator-owned dispatcher patch gives them GLM deadline parity.
    "zai-glm-5-3-flash": {"efforts": ["default"], "max_tokens": 4096},
    "deepseek-v4-1-flash-1017": {"efforts": ["default"], "max_tokens": 4096},
}

for _model, _evidence in LIFECYCLE.items():
    if _evidence["family"] in {"codestral", "ministral-3b", "ministral-8b", "ministral-14b", "voxtral-small"}:
        EXECUTION_POLICIES[_model] = {"efforts": ["default"], "max_tokens": 200}

ERROR_MESSAGE = "Choose a listed translation model."
EFFORT_ERROR_MESSAGE = "Choose an available translation thinking level."
DEFAULT_REASONING_EFFORT = "default"
HIGH_REASONING_EFFORT = "high"
TRANSLATION_PROMPT_VERSION = "academic-caption-v1"


def translation_output_limit(model: str, effort: str) -> int:
    policy = EXECUTION_POLICIES.get(model)
    if policy is None:
        raise ValueError("Translation execution policy is unverified.")
    if effort == HIGH_REASONING_EFFORT and policy["max_tokens"] < 1024:
        return 1024
    return policy["max_tokens"]


def _execution_choice(row):
    evidence = LIFECYCLE.get(row["id"], {})
    registered_status = evidence.get("status", "unknown")
    status = row.get("public_status", registered_status)
    # A stale generic-active cache cannot override newer source-backed preview
    # exclusions. Graduation requires an explicit policy review, not consent.
    if registered_status in {"preview", "labs"}:
        status = registered_status
    row = dict(row, **lifecycle_metadata(status))
    if status in {"preview", "labs"}:
        row.update(enabled=False, reason="privacy_preview_excluded")
    elif row["id"] not in EXECUTION_POLICIES:
        row.update(enabled=False, reason=row.get("reason") or "execution_policy_unverified")
    elif row.get("catalogue_target") and LIFECYCLE.get(
        row["catalogue_target"], {}
    ).get("alias"):
        # Alias-to-alias metadata is not a resolved version, even if family and
        # request budgets match. Never follow or guess a rolling target chain.
        row.update(enabled=False, reason="alias_target_unverified")
    return row


def available_translation_models(config: AppConfig) -> list[dict]:
    choices = [_execution_choice(row) for row in catalogue.snapshot()["models"]
               if row.get("reason") != "text_chat_not_supported"]
    # The source evidence packet expires on 2026-11-24 UTC. No retired fallback.
    if time.time() >= max(1795478400, (catalogue.public_verified_at or 0) + 604800):
        choices = [dict(row, enabled=False, reason="public_lifecycle_evidence_expired") for row in choices]
    if config.translate_model not in {row["id"] for row in choices}:
        status = LIFECYCLE.get(config.translate_model, {}).get("status", "unknown")
        reason = "lifecycle_" + status if status != "active" else (
            "account_model_unavailable" if catalogue.fresh else "account_catalogue_unverified")
        choices = [dict(id=config.translate_model, label=config.translate_model,
                        enabled=False, reason=reason, efforts=["default"],
                        **lifecycle_metadata(status))] + choices
    return choices


def validate_reasoning_effort(raw: object, model: str) -> str:
    """Only expose the Mistral request value used by its Vibe adapter."""
    allowed = {DEFAULT_REASONING_EFFORT}
    choices = catalogue.snapshot()["models"]
    if any(row["id"] == model and row["enabled"] and
           HIGH_REASONING_EFFORT in row.get("efforts", []) for row in choices):
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
