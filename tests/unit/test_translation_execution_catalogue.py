"""Source-only execution matrix, all account/lifecycle/provider data synthetic."""
import asyncio
import time

import pytest

from app.config import AppConfig
from app.providers import TranslationResponse
from app.state import SessionManager
from app.translate import TranslationDispatcher
from app.translation_catalogue import ModelCatalogue
from app import translation_models


@pytest.mark.parametrize("model,limit", [
    ("mistral-medium-latest", 200), ("mistral-small-latest", 200),
    ("mistral-large-latest", 4096), ("zai-glm-5-3", 4096),
])
@pytest.mark.parametrize("text,finish,reason", [
    ("", "length", "provider_output_limit"),
    ("Partial answer", "length", "provider_output_limit"),
    ("", "stop", "provider_no_text"),
    ("", "reasoning_only", "provider_reasoning_only"),
    ("", "refusal", "provider_refusal"),
])
def test_bounded_errors_and_return_to_medium(tmp_path, monkeypatch, model, limit, text, finish, reason):
    cache = ModelCatalogue()
    cache.verified_at = time.monotonic()
    cache.entries = [dict(id=key, label=key, enabled=True, efforts=["default"])
                     for key in {model, "mistral-medium-latest"}]
    monkeypatch.setattr(translation_models, "catalogue", cache)
    class Provider:
        name = "synthetic"
        calls = []
        async def translate(self, **request):
            self.calls.append(request)
            return TranslationResponse(text=text, finish_reason=finish,
                                       resolved_model=request["model"])
    async def scenario():
        config = AppConfig(_env_file=None, MISTRAL_TRANSLATE_MODEL=model,
                           MISTRAL_TTS_ENABLED=False,
                           JOURNAL_DIR=str(tmp_path / "journal"),
                           RELIABILITY_DIR=str(tmp_path / "reliability"))
        manager = SessionManager(config)
        provider = Provider()
        dispatcher = TranslationDispatcher(manager, config, provider)
        manager.set_dispatcher(dispatcher)
        manager.session.status = "listening"
        manager.finalize_segment("Synthetic fixture requiring translation.")
        await dispatcher.drain()
        first = manager.session.segments[0]
        assert first.failure_reason == reason
        assert first.translated_text is None
        assert first.translation_model_resolved is None  # echoed alias is not resolution
        assert len(provider.calls) == 1
        assert provider.calls[0]["max_tokens"] == limit
        manager.set_translation_model("mistral-medium-latest")
        assert manager.session.translation_model == "mistral-medium-latest"
    asyncio.run(scenario())
