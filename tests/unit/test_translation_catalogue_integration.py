"""Catalogue wiring with SDK and provider boundaries mocked, no account requests."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import translation_models
from app.config import AppConfig
from app.providers import MistralTranslationProvider
from app.state import SessionManager
from app.translate import TranslationDispatcher
from app.translation_catalogue import ModelCatalogue, reconcile


def test_bounded_metadata_serialization_is_not_inference(monkeypatch):
    completion = AsyncMock()
    monkeypatch.setattr("app.providers.Mistral", lambda **kwargs: SimpleNamespace(
        chat=SimpleNamespace(complete_async=completion)))
    original = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "mistral-large-4",
            "aliases": ["mistral-large-latest"], "capabilities": {"completion_chat": True}}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs:
                        original(**kwargs, transport=httpx.MockTransport(respond)))
    result = asyncio.run(MistralTranslationProvider(api_key="synthetic").list_models())
    assert result[0]["id"] == "mistral-large-4"
    assert result[0]["aliases"] == ["mistral-large-latest"]
    assert len(requests) == 1
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

@pytest.mark.parametrize("target_family,target_policy,target_present", [
    ("small", {"max_tokens": 200}, True), ("large", None, True),
    ("large", {"max_tokens": 200}, True), ("large", {"max_tokens": 4096}, False),
])
def test_alias_requires_family_target_and_identical_contract(target_family, target_policy, target_present):
    rows = [{"id": "alias", "capabilities": {"completion_chat": True}}]
    if target_present:
        rows.append({"id": "snapshot", "aliases": ["alias"], "capabilities": {"completion_chat": True}})
    evidence = {"alias": dict(status="active", family="large", alias="alias"),
                "snapshot": dict(status="active", family=target_family)}
    policies = {"alias": {"max_tokens": 4096}}
    if target_policy is not None:
        policies["snapshot"] = target_policy
    assert not next(row for row in reconcile(rows, evidence, policies) if row["id"] == "alias")["enabled"]


def test_revoked_reasoning_blocks_future_dispatch_without_downgrade(tmp_path, monkeypatch, synthetic_model_catalogue):
    config = AppConfig(_env_file=None, MISTRAL_TRANSLATE_MODEL="mistral-small-latest",
                       MISTRAL_TTS_ENABLED=False, JOURNAL_DIR=str(tmp_path / "journal"),
                       RELIABILITY_DIR=str(tmp_path / "reliability"))
    manager = SessionManager(config)
    manager.session.translation_reasoning_effort = "high"
    for row in synthetic_model_catalogue.entries:
        row["efforts"] = ["default"]
    provider = SimpleNamespace(name="synthetic", translate=AsyncMock())
    manager.set_dispatcher(TranslationDispatcher(manager, config, provider))
    manager.session.status = "listening"
    manager.finalize_segment("Synthetic revoked capability fixture.")
    assert manager.session.segments[0].failure_reason == "model_effort_unavailable"
    assert manager.session.translation_reasoning_effort == "high"
    provider.translate.assert_not_awaited()

@pytest.mark.parametrize("status,body", [(302, b""), (429, b"{}"), (200, b"x" * 2_000_001)], ids=["redirect", "no-retry", "oversize"])
def test_metadata_redirect_retry_and_byte_ceiling(monkeypatch, status, body):
    monkeypatch.setattr("app.providers.Mistral", lambda **kwargs: SimpleNamespace())
    original = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, content=body, headers={"location": "https://elsewhere.invalid"})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "AsyncClient", client)
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        asyncio.run(MistralTranslationProvider(api_key="synthetic").list_models())
    assert len(requests) == 1
