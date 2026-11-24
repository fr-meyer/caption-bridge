"""Local metadata transport/dispatch regressions; no account qualification."""
import asyncio
import copy
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import translation_models as models
from app.config import AppConfig
from app.providers import MistralTranslationProvider
from app.state import SessionManager
from app.translate import TranslationDispatcher

GLM = "zai-glm-5-3"


@pytest.mark.parametrize("alias", ["zai-glm-5", "zai-glm-latest"])
@pytest.mark.parametrize("raw_target", [GLM, [GLM], {"id": GLM}])
@pytest.mark.parametrize("declared", [False, True])
def test_metadata_target_is_derived_only_from_account_declaration(
        alias, raw_target, declared, tmp_path, monkeypatch):
    capabilities = dict(completion_chat=True, reasoning=True)
    rows = [dict(id=alias, capabilities=capabilities, catalogue_target=raw_target)]
    if declared:
        rows.append(dict(id=GLM, capabilities=capabilities, aliases=[alias],
                         catalogue_target="untrusted-sabotage"))
    original = copy.deepcopy(rows)
    requests = []
    def response(request):
        assert str(request.url) == "https://api.mistral.ai/v1/models"
        requests.append(request)
        return httpx.Response(200, json=dict(data=rows))
    original_client = httpx.AsyncClient
    def local_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(response)
        return original_client(*args, **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", local_client)
    cache = models.TranslationModelCatalogue()
    monkeypatch.setattr(models, "catalogue", cache)
    async def scenario():
        adapter = MistralTranslationProvider("synthetic-unit-key-not-real")
        await cache.refresh(adapter.list_models, models.LIFECYCLE, models.EXECUTION_POLICIES)
        cache.public_verified_at = time.time()
        choice = next(row for row in cache.snapshot()["models"] if row["id"] == alias)
        assert choice["enabled"] is declared
        assert choice["catalogue_target"] == (GLM if declared else None)
        config = AppConfig(_env_file=None, MISTRAL_API_KEY="",
                           MISTRAL_TRANSLATE_MODEL=alias, MISTRAL_TTS_ENABLED=False,
                           JOURNAL_DIR=str(tmp_path / "journal"),
                           RELIABILITY_DIR=str(tmp_path / "reliability"),
                           TRANSLATION_REPAIR_MAX_ATTEMPTS=0)
        provider = SimpleNamespace(name="local-only", translate=AsyncMock(return_value="Unit result"))
        manager = SessionManager(config)
        dispatcher = TranslationDispatcher(manager, config, provider)
        manager.set_dispatcher(dispatcher)
        manager.session.status = "listening"
        manager.finalize_segment("Unit-only synthetic source.")
        await dispatcher.drain()
        if declared:
            assert models.validate_translation_model(alias, config) == alias
            provider.translate.assert_awaited_once()
            assert provider.translate.await_args.kwargs["model"] == alias
        else:
            assert choice["reason"] == "alias_target_unverified"
            with pytest.raises(ValueError):
                models.validate_translation_model(alias, config)
            provider.translate.assert_not_awaited()
            assert manager.session.segments[0].failure_reason == "model_catalogue_unavailable"
        assert not dispatcher._in_flight
    asyncio.run(scenario())
    assert len(requests) == 1  # local MockTransport, never a live request
    assert rows == original
