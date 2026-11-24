"""Unit-only policy evidence. No account, inference, audio or privacy approval."""
import asyncio
import copy
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import translation_models as models
from app.config import AppConfig
from app.model_lifecycle import (
    _FlightScripts,
    _nodes,
    lifecycle_metadata,
    parse_lifecycle,
    refresh_public_lifecycle,
)
from app.state import SessionManager
from app.translate import TranslationDispatcher
from app.translation_catalogue import reconcile

GLM = "zai-glm-5-3"
ALIASES = ["zai-glm-5", "zai-glm-latest"]
PREVIEW = "deepseek-v4-1-flash-1017"
FIXTURE = Path(__file__).parents[1] / "fixtures/model-lifecycle/large-current-flight.html"
URL = "https://docs.mistral.ai/models/mistral-large-4-0"


def account(model, *, aliases=None, chat=True):
    return dict(id=model, aliases=aliases or [],
                capabilities=dict(completion_chat=chat, reasoning=True))


def populate(rows, *, lifecycle=None, policies=None):
    cache = models.TranslationModelCatalogue()
    async def load():
        return rows
    asyncio.run(cache.refresh(load, lifecycle or models.LIFECYCLE,
                              models.EXECUTION_POLICIES if policies is None else policies))
    cache.public_verified_at = time.time()
    return cache


def by_id(cache):
    return {row["id"]: row for row in cache.snapshot()["models"]}


def hypothetical_alias_policies():
    """Unit-only contract proposal, never a production admission override."""
    policies = copy.deepcopy(models.EXECUTION_POLICIES)
    for alias in ALIASES:
        policies[alias] = copy.deepcopy(policies[GLM])
    return policies


@pytest.mark.parametrize("badge", ["Public Preview", "Labs"])
def test_ga_plus_preview_is_not_an_unambiguous_active_badge(badge):
    with pytest.raises(ValueError, match="conflicting"):
        parse_lifecycle('<span data-slot="badge">GA</span>'
                        '<span data-slot="badge">' + badge + '</span>')


@pytest.mark.parametrize("badge,status", [("GA", "active"), ("Public Preview", "preview"),
                                          ("Labs", "labs")])
def test_current_card_refresh_preserves_vendor_and_privacy_distinction(badge, status):
    parser = _FlightScripts()
    parser.feed(FIXTURE.read_text())
    records = {key: json.loads(body) for line in "".join(parser.chunks).splitlines()
               for key, _, body in [line.partition(":")]}
    header = next(node for node in _nodes(records["e"])
                  if "gap-6" in node[3].get("className", ""))
    next(node for node in _nodes(header)
         if node[3].get("data-slot") == "badge")[3]["children"] = badge
    stream = "".join(key + ":" + json.dumps(value) + "\n" for key, value in records.items())
    html = "<script>self.__next_f.push(" + json.dumps([1, stream]) + ")</script>"
    evidence = {"mistral-large-4": dict(source=URL, refresh_public=True, status="active")}
    async def fetch(url):
        assert url == URL
        return html
    result = asyncio.run(refresh_public_lifecycle(evidence, fetch))["mistral-large-4"]
    assert result["status"] == status
    assert result["vendor_status"] == badge
    assert result["privacy_status"] == lifecycle_metadata(status)["privacy_status"]
    assert evidence["mistral-large-4"]["status"] == "active"


def test_source_declarations_are_literal_not_invented_variants():
    assert models.LIFECYCLE[PREVIEW]["vendor_status"] == "Public Preview"
    assert models.LIFECYCLE[PREVIEW]["status"] == "preview"
    for alias in ALIASES:
        row = models.LIFECYCLE[alias]
        assert row["alias"] == alias
        assert row["family"] == models.LIFECYCLE[GLM]["family"]
        assert row["variant"] == models.LIFECYCLE[GLM]["variant"] == "standard"
        assert row["source"] == models.LIFECYCLE[GLM]["source"]
    assert "zai-glm-5-3-flash-latest" not in models.LIFECYCLE
    assert "deepseek-latest" not in models.LIFECYCLE


@pytest.mark.parametrize("status,badge", [("preview", "Public Preview"), ("labs", "Labs")])
def test_account_capability_and_consent_cannot_admit_preview(monkeypatch, status, badge):
    lifecycle = copy.deepcopy(models.LIFECYCLE)
    lifecycle[PREVIEW].update(status=status, **lifecycle_metadata(status))
    monkeypatch.setattr(models, "LIFECYCLE", lifecycle)
    row = account(PREVIEW)
    row.update(privacy_approved=True, training_opt_out=True, zero_data_retention=True,
               user_consent=True, subscription="paid")  # untrusted unit-only fields
    cache = populate([row], lifecycle=lifecycle)
    choice = by_id(cache)[PREVIEW]
    assert not choice["enabled"]
    assert choice["vendor_status"] == badge
    assert choice["privacy_status"] == "ordinary_optout_zdr_excluded"
    assert choice["reason"] == "privacy_preview_excluded"


@pytest.mark.parametrize("old_status", [None, "active"])
def test_stale_generic_active_preview_cache_cannot_bypass_selection(monkeypatch, old_status):
    cache = models.TranslationModelCatalogue()
    cache.verified_at = time.monotonic()
    cache.public_verified_at = time.time()
    entry = dict(id=PREVIEW, label=PREVIEW, enabled=True, reason=None, efforts=["default"])
    if old_status:
        entry["public_status"] = old_status
    cache.entries = [entry]
    monkeypatch.setattr(models, "catalogue", cache)
    config = AppConfig(_env_file=None, MISTRAL_TRANSLATE_MODEL=PREVIEW)
    choice = models.available_translation_models(config)[0]
    assert not choice["enabled"]
    assert choice["vendor_status"] == "Public Preview"
    with pytest.raises(ValueError):
        models.validate_translation_model(PREVIEW, config)
    assert cache.entries[0]["enabled"] is True  # derived guard does not mutate cache


def test_preview_future_dispatch_makes_no_provider_request(tmp_path, monkeypatch):
    cache = populate([account(PREVIEW)])
    monkeypatch.setattr(models, "catalogue", cache)
    async def scenario():
        config = AppConfig(_env_file=None, MISTRAL_TRANSLATE_MODEL=PREVIEW,
                           MISTRAL_TTS_ENABLED=False, JOURNAL_DIR=str(tmp_path / "journal"),
                           RELIABILITY_DIR=str(tmp_path / "reliability"))
        manager = SessionManager(config)
        provider = SimpleNamespace(name="unit-only", translate=AsyncMock())
        manager.set_dispatcher(TranslationDispatcher(manager, config, provider))
        manager.session.status = "listening"
        manager.finalize_segment("Unit-only private-content admission sentinel.")
        await manager._dispatcher.drain()
        assert manager.session.segments[0].failure_reason == "model_catalogue_unavailable"
        provider.translate.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("alias", ALIASES)
def test_documented_alias_stays_disabled_until_actual_dispatch_contract_matches(alias):
    cache = populate([account(GLM, aliases=[alias])])
    assert not by_id(cache)[alias]["enabled"]
    assert by_id(cache)[alias]["reason"] == "alias_execution_contract_unverified"
    assert alias not in models.EXECUTION_POLICIES


@pytest.mark.parametrize("alias", ALIASES)
def test_same_family_variant_and_identical_candidate_contract_accepts_concrete_target(alias, monkeypatch):
    policies = hypothetical_alias_policies()
    monkeypatch.setattr(models, "EXECUTION_POLICIES", policies)
    cache = populate([account(GLM, aliases=[alias])], policies=policies)
    choice = by_id(cache)[alias]
    assert choice["enabled"]
    assert choice["catalogue_target"] == GLM
    assert choice["vendor_status"] == "GA"
    assert choice["privacy_status"] == "account_terms_unverified"
    assert choice["efforts"] == ["default", "high"]


@pytest.mark.parametrize("mutation,reason", [
    ("missing-target", "alias_target_unverified"),
    ("unknown-target", "alias_target_unverified"),
    ("deprecated-target", "alias_target_unverified"),
    ("preview-target", "alias_target_unverified"),
    ("family", "alias_execution_contract_unverified"),
    ("variant", "alias_execution_contract_unverified"),
    ("output-budget", "alias_execution_contract_unverified"),
    ("effort", "alias_execution_contract_unverified"),
    ("missing-policy", "alias_execution_contract_unverified"),
    ("conflicting-targets", "conflicting_account_metadata"),
    ("no-chat", "text_chat_not_supported"),
])
def test_adversarial_alias_resolution_is_closed(mutation, reason):
    alias = "zai-glm-latest"
    evidence = copy.deepcopy(models.LIFECYCLE)
    policies = hypothetical_alias_policies()
    rows = [account(GLM, aliases=[alias])]
    if mutation == "missing-target":
        rows = [account(alias)]
    elif mutation == "unknown-target":
        rows = [account("zai-glm-unknown", aliases=[alias])]
    elif mutation in {"deprecated-target", "preview-target"}:
        evidence[GLM]["status"] = "deprecated" if mutation == "deprecated-target" else "preview"
    elif mutation in {"family", "variant"}:
        evidence[GLM][mutation] = "flash"
    elif mutation == "output-budget":
        policies[GLM]["max_tokens"] = 200
    elif mutation == "effort":
        policies[GLM]["efforts"] = ["default"]
    elif mutation == "missing-policy":
        del policies[GLM]
    elif mutation == "conflicting-targets":
        rows.append(account("zai-glm-5-3-flash", aliases=[alias]))
    elif mutation == "no-chat":
        rows = [account(GLM, aliases=[alias], chat=False)]
    cache = populate(rows, lifecycle=evidence, policies=policies)
    choice = by_id(cache)[alias]
    assert not choice["enabled"]
    assert choice["reason"] == reason


@pytest.mark.parametrize("alias,target", [("zai-glm-latest", "zai-glm-5"),
                                         ("zai-glm-5", "zai-glm-latest")])
def test_alias_chain_is_not_concrete_resolution(monkeypatch, alias, target):
    policies = hypothetical_alias_policies()
    monkeypatch.setattr(models, "EXECUTION_POLICIES", policies)
    cache = populate([account(target, aliases=[alias])], policies=policies)
    choice = by_id(cache)[alias]
    assert not choice["enabled"]
    assert choice["reason"] == "alias_target_unverified"


@pytest.mark.parametrize("model", ["zai-glm-future-latest", "zai-glm-5-3-flash-latest",
                                   "deepseek-latest", "unlisted-chat-model"])
def test_unknown_alias_or_family_never_enabled(model):
    cache = populate([account(model)])
    assert not by_id(cache)[model]["enabled"]
    assert by_id(cache)[model]["reason"] == "lifecycle_unknown"


@pytest.mark.parametrize("model", ["mistral-large-4", "mistral-small-2603", GLM,
                                   "zai-glm-5-3-flash", "codestral-2508",
                                   "ministral-3b-2512", "ministral-8b-2512",
                                   "ministral-14b-2512", "voxtral-small-2507"])
def test_existing_ga_paths_remain_available_without_privacy_approval_claim(model):
    choice = by_id(populate([account(model)]))[model]
    assert choice["enabled"]
    assert choice["vendor_status"] == "GA"
    assert choice["privacy_status"] == "account_terms_unverified"


def test_default_is_unchanged_and_deprecated_medium_is_not_revived():
    config = AppConfig(_env_file=None)
    assert config.translate_model == "mistral-medium-latest"
    row = reconcile([account(config.translate_model)], models.LIFECYCLE,
                    models.EXECUTION_POLICIES)[0]
    assert not row["enabled"]
    assert row["reason"] == "lifecycle_deprecated"
