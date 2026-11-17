"""Catalogue wiring with SDK and provider boundaries mocked, no account requests."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mistralai.client.models import BaseModelCard, ModelCapabilities

from app import translation_models
from app.config import AppConfig
from app.providers import MistralTranslationProvider
from app.state import SessionManager
from app.translate import TranslationDispatcher
from app.translation_catalogue import ModelCatalogue, reconcile


def test_sdk_metadata_serialization_is_not_inference(monkeypatch):
    metadata = BaseModelCard(id="mistral-large-4", aliases=["mistral-large-latest"],
                             capabilities=ModelCapabilities(completion_chat=True))
    listing = AsyncMock(return_value=SimpleNamespace(data=[metadata]))
    completion = AsyncMock()
    monkeypatch.setattr("app.providers.Mistral", lambda **kwargs: SimpleNamespace(
        models=SimpleNamespace(list_async=listing),
        chat=SimpleNamespace(complete_async=completion)))
    result = asyncio.run(MistralTranslationProvider(api_key="").list_models())
    assert result[0]["id"] == "mistral-large-4"
    assert result[0]["aliases"] == ["mistral-large-latest"]
    listing.assert_awaited_once()
    completion.assert_not_awaited()


def test_public_medium_is_deprecated_not_an_invented_current_alias(monkeypatch):
    entry = reconcile([dict(id="mistral-medium-latest", capabilities={"completion_chat": True})],
                      translation_models.LIFECYCLE, translation_models.EXECUTION_POLICIES)[0]
    assert entry["reason"] == "lifecycle_deprecated"
    assert not entry["enabled"]
    cache = ModelCatalogue()
    monkeypatch.setattr(translation_models, "catalogue", cache)
    config = AppConfig(_env_file=None)
    assert config.translate_model == "mistral-medium-latest"
    assert not translation_models.available_translation_models(config)[0]["enabled"]
    with pytest.raises(ValueError):
        translation_models.validate_translation_model(config.translate_model, config)


@pytest.mark.parametrize("deprecation,expected", [
    ("2026-10-31T00:00:00Z", "account_deprecated"),
    ("invalid", "account_lifecycle_unverified"),
    ("2099-01-01T00:00:00Z", None),
])
def test_account_lifecycle_is_independent_and_fail_closed(deprecation, expected):
    result = reconcile([dict(id="x", deprecation=deprecation,
                              capabilities={"completion_chat": True})],
                       {"x": {"status": "active"}}, {"x": {}})[0]
    assert result["reason"] == expected


def test_account_reasoning_capability_limits_controls():
    result = reconcile([dict(id="x", capabilities={"completion_chat": True, "reasoning": False})],
                       {"x": {"status": "active"}}, {"x": {"efforts": ["default", "high"]}})[0]
    assert result["efforts"] == ["default"]


def test_expired_account_cannot_be_bypassed_by_config_or_future_dispatch(tmp_path, monkeypatch):
    cache = ModelCatalogue()
    monkeypatch.setattr(translation_models, "catalogue", cache)
    config = AppConfig(_env_file=None, MISTRAL_TRANSLATE_MODEL="mistral-large-latest",
                       MISTRAL_TTS_ENABLED=False, JOURNAL_DIR=str(tmp_path / "journal"),
                       RELIABILITY_DIR=str(tmp_path / "reliability"))
    manager = SessionManager(config)
    provider = SimpleNamespace(name="synthetic", translate=AsyncMock())
    dispatcher = TranslationDispatcher(manager, config, provider)
    manager.set_dispatcher(dispatcher)
    manager.session.status = "listening"
    manager.finalize_segment("Synthetic fixture with no eligible account metadata.")
    assert manager.session.segments[0].failure_reason == "model_catalogue_unavailable"
    provider.translate.assert_not_awaited()


def test_public_evidence_expiry_requires_successful_public_refresh(monkeypatch, synthetic_model_catalogue):
    cache = synthetic_model_catalogue
    deadline = 1795478400
    monkeypatch.setattr(translation_models, "time", SimpleNamespace(time=lambda: deadline + 1))
    cache.public_verified_at = None
    config = AppConfig(_env_file=None)
    with pytest.raises(ValueError):
        translation_models.validate_translation_model("mistral-large-latest", config)
    cache.public_verified_at = deadline
    assert translation_models.validate_translation_model("mistral-large-latest", config) == "mistral-large-latest"
