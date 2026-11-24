"""Real application imports with an explicit synthetic provider; no inference."""
from __future__ import annotations

import asyncio

from app.config import AppConfig
from app.providers import TranslationResponse
from app.state import SessionManager
from app.translate import TranslationDispatcher


def config_at(tmp_path, **settings):
    return AppConfig(
        _env_file=None, MISTRAL_API_KEY="", EXPORT_DIR=str(tmp_path / "exports"),
        JOURNAL_DIR=str(tmp_path / "journals"),
        RECOVERY_EXPORT_DIR=str(tmp_path / "recovered"),
        RELIABILITY_DIR=str(tmp_path / "reliability"),
        TRANSLATION_REPAIR_MAX_ATTEMPTS=0, **settings,
    )


def test_real_dispatcher_request_timeout_preserves_first_failure(tmp_path):
    class Provider:
        name = "synthetic"

        async def translate(self, **request):
            await asyncio.sleep(1)
            raise AssertionError("synthetic request should have been cancelled")

    async def scenario():
        config = config_at(tmp_path, TRANSLATION_TIMEOUT_MS=100)
        manager = SessionManager(config)
        dispatcher = TranslationDispatcher(manager, config, Provider())
        manager.set_dispatcher(dispatcher)
        manager.session.status = "listening"
        manager.finalize_segment("합성 시간 초과 테스트입니다.")
        await dispatcher.drain()
        segment = manager.session.segments[0]
        assert segment.translation_status == "timed_out"
        snapshot = dispatcher.diagnostics_snapshot()
        assert snapshot["first_failure"]["reason"] == "request_timeout"
        assert snapshot["first_failure"]["request_timeout_ms"] == 100
        assert snapshot["in_flight"] == 0
        assert snapshot["cancellations"] == 0
    asyncio.run(scenario())


def test_real_dispatcher_output_limit_does_not_become_success(tmp_path):
    class Provider:
        name = "synthetic"
        calls = 0

        async def translate(self, **request):
            self.calls += 1
            return TranslationResponse(text="Synthetic partial answer", finish_reason="length")

    async def scenario():
        config = config_at(tmp_path)
        manager = SessionManager(config)
        provider = Provider()
        dispatcher = TranslationDispatcher(manager, config, provider)
        manager.set_dispatcher(dispatcher)
        manager.session.status = "listening"
        manager.finalize_segment("합성 출력 한도 테스트입니다.")
        await dispatcher.drain()
        segment = manager.session.segments[0]
        assert provider.calls == 1
        assert segment.translation_status == "failed"
        assert segment.failure_reason == "provider_output_limit"
        assert dispatcher.diagnostics_snapshot()["first_failure"]["reason"] == "provider_output_limit"
        assert dispatcher.diagnostics_snapshot()["in_flight"] == 0
    asyncio.run(scenario())


def test_admission_diagnostics_use_segment_model_budget(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import app.translate as translate

    class NeverProvider:
        name = "offline"

        async def translate(self, **request):
            raise AssertionError("admission failure must not call provider")

    for failure in ("model", "effort"):
        config = config_at(tmp_path, TRANSLATION_TIMEOUT_MS=10000,
                           TRANSLATION_LARGE_TIMEOUT_MS=20000)
        manager = SessionManager(config)
        dispatcher = TranslationDispatcher(manager, config, NeverProvider())
        segment = SimpleNamespace(seq=1, translation_model="mistral-large-latest",
                                  translation_reasoning_effort="default")
        def reject(*args):
            raise ValueError("unavailable")
        with monkeypatch.context() as patch:
            patch.setattr(translate, "validate_translation_model",
                          reject if failure == "model" else lambda *args: None)
            patch.setattr(translate, "validate_reasoning_effort", reject)
            dispatcher.dispatch(segment, [], manager.session.id, "en")
        row = dispatcher.diagnostics_snapshot()["first_failure"]
        assert row["stage"] == "admission"
        assert row["request_timeout_ms"] == 20000
        assert row["reason"] == ("model_catalogue_unavailable" if failure == "model"
                                 else "model_effort_unavailable")
        assert not dispatcher._in_flight
