"""Offline entrypoints must not depend on pytest's eligible-model baseline."""
import asyncio

import pytest

from app import translation_models
from app.config import AppConfig
from app.translation_catalogue import ModelCatalogue
from scripts.full_pipeline_scenario import run_full_pipeline_scenario
from scripts.resilience_soak import run_soak
from scripts.synthetic_translation_catalogue import SYNTHETIC_MODEL, synthetic_translation_catalogue


@pytest.mark.parametrize("entrypoint", ["soak", "pipeline"])
def test_entrypoints_seed_only_scoped_synthetic_metadata(monkeypatch, entrypoint):
    original = ModelCatalogue()
    monkeypatch.setattr(translation_models, "catalogue", original)
    lifecycle_before = {key: dict(value) for key, value in translation_models.LIFECYCLE.items()}
    def forbidden_provider(*args, **kwargs):
        raise AssertionError("offline entrypoints cannot construct real provider")
    monkeypatch.setattr("app.translate.MistralTranslationProvider", forbidden_provider)
    report = asyncio.run(run_soak(25) if entrypoint == "soak" else run_full_pipeline_scenario())
    assert report.passed
    assert translation_models.catalogue is original
    assert not original.fresh
    assert translation_models.LIFECYCLE == lifecycle_before
    assert AppConfig(_env_file=None).translate_model == "mistral-medium-latest"
    assert lifecycle_before["mistral-medium-latest"]["status"] == "deprecated"
    with pytest.raises(ValueError):
        translation_models.validate_translation_model(SYNTHETIC_MODEL, AppConfig(_env_file=None))


def test_synthetic_scope_validates_real_policy_and_restores_after_exception(monkeypatch):
    original = ModelCatalogue()
    monkeypatch.setattr(translation_models, "catalogue", original)
    async def exercise():
        with pytest.raises(RuntimeError, match="synthetic cleanup"):
            async with synthetic_translation_catalogue() as cache:
                assert cache.fresh
                assert cache.public_verified_at is not None
                assert translation_models.validate_translation_model(SYNTHETIC_MODEL, AppConfig(_env_file=None)) == SYNTHETIC_MODEL
                assert all(row["lifecycle_source"] == "synthetic-offline-fixture" for row in cache.entries)
                assert "mistral-medium-latest" not in {row["id"] for row in cache.entries}
                raise RuntimeError("synthetic cleanup")
        assert translation_models.catalogue is original
    asyncio.run(exercise())


@pytest.mark.parametrize("scenario,model", [("idle_ready", "mistral-medium-latest"),
                                            ("model_override", "mistral-small-latest")])
def test_browser_baseline_declares_explicit_synthetic_freshness(scenario, model):
    from browser_tests.conftest import BrowserHarness
    harness = BrowserHarness()
    harness.configure(scenario)
    initial, _ = harness.on_connect()
    reset = harness.reset_session_snapshot()
    for snapshot in [initial, reset]:
        assert snapshot["translation_catalogue"]["fresh"] is True
        assert snapshot["translation_catalogue"]["qualification"] == "synthetic_fixture_only"
        assert snapshot["translation_model"] == model
