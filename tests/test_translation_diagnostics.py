"""Provider-free software tests, never provider/audio acceptance.

The dispatcher class is compiled from its real AST with imports excluded, as
in test_asr_recovery_contract. Narrow injected seams avoid SDK/application
initialization on bootstrap hosts. Production configuration and diagnostics
are imported normally; the SDK/ASGI dependency graph is not qualified here.
"""
from __future__ import annotations

import ast
import asyncio
import json
import logging
import random
import sys
import time
import types
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import translation_quality
from app.config import AppConfig
from app.glossary import add_to_messages
from app.languages import get_language_label
from app.pipeline_diagnostics import TranslationDiagnostics


def dispatcher_class():
    errors = types.ModuleType("diagnostics_error_contract")
    errors.__dict__.update(json=json, dataclass=dataclass)
    tree = ast.parse(Path("app/errors.py").read_text())
    nodes = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    # Keep future annotations without importing SDK-only exception types.
    nodes.insert(0, ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0))
    sys.modules[errors.__name__] = errors
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "app/errors.py", "exec"), errors.__dict__)
    env = dict(asyncio=asyncio, json=json, logging=logging, random=random, time=time,
               ContextVar=ContextVar, TranslationDiagnostics=TranslationDiagnostics,
               translation_quality=translation_quality, SegmentQuality=SimpleNamespace,
               add_to_messages=add_to_messages, get_language_label=get_language_label,
               extract_provider_error_info=errors.extract_provider_error_info,
               is_capacity_exceeded=errors.is_capacity_exceeded,
               logger=logging.getLogger("diagnostics_contract"))
    tree = ast.parse(Path("app/translate.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TranslationDispatcher")
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, cls], type_ignores=[])), "app/translate.py", "exec"), env)
    return env["TranslationDispatcher"]


def make_dispatcher(**settings):
    cls = dispatcher_class()
    config = AppConfig(_env_file=None, MISTRAL_API_KEY="", **settings)
    manager = MagicMock()
    manager.session = SimpleNamespace(id="synthetic-session")
    # The constructor imports this annotation-only name locally. Replace only
    # that SDK-adjacent import, not the dispatcher constructor or its methods.
    state_seam = types.ModuleType("app.state")
    state_seam.SessionManager = object
    with patch.dict(sys.modules, {"app.state": state_seam}):
        dispatcher = cls(manager, config, SimpleNamespace(name="synthetic"))
    dispatcher._build_messages = lambda *args: []
    dispatcher._check_and_repair = AsyncMock(return_value=("Synthetic translation", None))
    return dispatcher


def record(diagnostics, **overrides):
    values = dict(segment_seq=1, stage="request", reason="provider_error",
                  error_type="http_error", status_code=503, request_timeout_ms=20000)
    return diagnostics.record_failure(**(values | overrides))


def test_first_failure_is_immutable_and_snapshots_do_not_alias():
    diagnostics = TranslationDiagnostics()
    first = record(diagnostics)
    later = record(diagnostics, segment_seq=2, stage="drain", reason="drain_timeout",
                   error_type="timeout", status_code=None)
    assert later["first_failure"] == first["first_failure"]
    assert diagnostics.snapshot()["failure_events"] == 2
    later["first_failure"]["reason"] = "changed outside"
    assert diagnostics.snapshot()["first_failure"]["reason"] == "provider_error"
    assert TranslationDiagnostics().run_id != diagnostics.run_id


@pytest.mark.parametrize("status", [True, False, "503", 99, 600, {}, None])
def test_status_is_bounded_and_never_coerced(status):
    assert record(TranslationDiagnostics(), status_code=status)["status_code"] is None


@pytest.mark.parametrize("override", [
    dict(reason="PRIVATE provider body"), dict(stage="PRIVATE caption"),
    dict(error_type="PRIVATE arbitrary exception class"), dict(segment_seq=True),
    dict(request_timeout_ms=120001), dict(reason={}),
])
def test_non_allowlisted_diagnostics_fail_closed(override):
    with pytest.raises(ValueError):
        record(TranslationDiagnostics(), **override)


def test_exact_default_and_campaign_budgets_remain_distinct():
    dispatcher = make_dispatcher()
    assert dispatcher.diagnostics_snapshot()["timeouts"] == dict(
        standard_request_ms=10000, large_request_ms=20000, glm_request_ms=20000, drain_ms=30000)
    assert not dispatcher.diagnostics_snapshot()["drain_shorter_than_max_request"]
    for model in ("mistral-large-4", "mistral-large-4-0", "mistral-large-latest"):
        assert dispatcher._timeout_for_model(model) == 20000
    assert dispatcher._timeout_for_model("mistral-medium-latest") == 10000
    campaign = make_dispatcher(TRANSLATION_LARGE_TIMEOUT_MS=60000,
                               TRANSLATION_DRAIN_TIMEOUT_MS=90000)
    assert campaign._timeout_for_model("mistral-large-4") == 60000
    assert campaign.diagnostics_snapshot()["timeouts"]["drain_ms"] == 90000
    assert not campaign.diagnostics_snapshot()["drain_shorter_than_max_request"]
    short_drain = make_dispatcher(TRANSLATION_LARGE_TIMEOUT_MS=60000)
    assert short_drain.diagnostics_snapshot()["drain_shorter_than_max_request"]


def test_stale_session_failure_cannot_replace_new_session_diagnostics(caplog):
    dispatcher = make_dispatcher()
    dispatcher._record_failure(1, "synthetic-session", "request", "provider_error")
    previous = dispatcher.diagnostics_snapshot()
    dispatcher._session_manager.session.id = "synthetic-next-session"
    dispatcher._record_failure(2, "synthetic-session", "drain", "drain_timeout")
    current = dispatcher.diagnostics_snapshot()
    assert current["first_failure"] is None
    assert current["run_id"] != previous["run_id"]


def test_initial_http_cause_survives_retry_timeout_without_payload_logging(caplog):
    async def scenario():
        dispatcher = make_dispatcher()
        first = RuntimeError("PRIVATE provider payload")
        first.status_code = 503
        dispatcher._await_translation = AsyncMock(side_effect=first)
        async def retry(*args):
            dispatcher._handle_translation_timeout(1, "en", "synthetic-session", stage="retry")
            return None
        dispatcher._generic_one_second_retry = retry
        await dispatcher._translate_task(SimpleNamespace(seq=1), [], "synthetic-session", "en")
        snapshot = dispatcher.diagnostics_snapshot()
        assert snapshot["first_failure"]["status_code"] == 503
        assert snapshot["first_failure"]["stage"] == "request"
        assert snapshot["first_failure"]["error_type"] == "http_error"
        assert snapshot["failure_events"] == 2
        assert "PRIVATE" not in caplog.text
        dispatcher._session_manager.mark_translation_timed_out.assert_called_once()
    asyncio.run(scenario())


def test_recovered_request_keeps_first_failure_without_changing_outcome():
    async def scenario():
        dispatcher = make_dispatcher()
        dispatcher._await_translation = AsyncMock(side_effect=RuntimeError("synthetic failure"))
        dispatcher._generic_one_second_retry = AsyncMock(return_value="Recovered translation")
        await dispatcher._translate_task(SimpleNamespace(seq=1), [], "synthetic-session", "en")
        assert dispatcher.diagnostics_snapshot()["first_failure"]["reason"] == "provider_error"
        dispatcher._session_manager.mark_translated.assert_called_once()
        dispatcher._session_manager.mark_translation_failed.assert_not_called()
    asyncio.run(scenario())


def test_output_limit_preserves_failure_without_retry_or_success():
    async def scenario():
        dispatcher = make_dispatcher()
        dispatcher._await_translation = AsyncMock(return_value="Synthetic partial answer")
        dispatcher._generic_one_second_retry = AsyncMock()
        await dispatcher._translate_task(SimpleNamespace(seq=1, translation_finish_reason="length"),
                                         [], "synthetic-session", "en")
        assert dispatcher.diagnostics_snapshot()["first_failure"]["reason"] == "provider_output_limit"
        dispatcher._generic_one_second_retry.assert_not_awaited()
        dispatcher._session_manager.mark_translated.assert_not_called()
    asyncio.run(scenario())


def test_normal_task_cancellation_is_not_a_root_failure():
    async def scenario():
        dispatcher = make_dispatcher()
        dispatcher._await_translation = AsyncMock(side_effect=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await dispatcher._translate_task(SimpleNamespace(seq=1), [], "synthetic-session", "en")
        assert dispatcher.diagnostics_snapshot()["first_failure"] is None
        assert dispatcher.diagnostics_snapshot()["cancellations"] == 1
    asyncio.run(scenario())


def test_drain_keeps_custody_of_a_cancellation_resistant_task():
    async def scenario():
        dispatcher = make_dispatcher(TRANSLATION_DRAIN_TIMEOUT_MS=1000)
        release = asyncio.Event()
        started = asyncio.Event()
        async def resistant():
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
        task = asyncio.create_task(resistant())
        dispatcher._in_flight.add(task)
        dispatcher._task_segments[task] = (1, "synthetic-session", 20000)
        task.add_done_callback(dispatcher._task_done)
        await started.wait()
        try:
            await dispatcher.drain()
            assert not task.done()
            assert task in dispatcher._in_flight
            assert task in dispatcher._task_segments
            assert dispatcher.diagnostics_snapshot()["first_failure"]["reason"] == "drain_timeout"
        finally:
            release.set()
            await task
            await asyncio.sleep(0)
        assert not dispatcher._in_flight
        assert not dispatcher._task_segments
    asyncio.run(scenario())


@pytest.mark.parametrize("output_limit", [False, True])
def test_repair_failure_reports_its_own_budget_once(output_limit):
    async def scenario():
        dispatcher = make_dispatcher(TRANSLATION_TIMEOUT_MS=100)
        del dispatcher._check_and_repair  # Exercise the exact production method.
        segment = SimpleNamespace(seq=1, source_text="합성 수리 테스트입니다.",
                                  translation_finish_reason="length" if output_limit else "stop")
        dispatcher._call_repair_api = AsyncMock(
            return_value="Synthetic repair" if output_limit else None,
            side_effect=None if output_limit else TimeoutError(),
        )
        token = dispatcher._request_session_id.set("synthetic-session")
        try:
            text, quality = await dispatcher._check_and_repair("Caption: synthetic answer", segment, "en")
        finally:
            dispatcher._request_session_id.reset(token)
        assert text == "Caption: synthetic answer"
        assert quality.repair_succeeded is False
        snapshot = dispatcher.diagnostics_snapshot()
        assert snapshot["failure_events"] == 1
        assert snapshot["first_failure"]["reason"] == (
            "provider_output_limit" if output_limit else "repair_timeout")
        assert snapshot["first_failure"]["request_timeout_ms"] == 50
        assert snapshot["first_failure"]["stage"] == "repair"
    asyncio.run(scenario())
