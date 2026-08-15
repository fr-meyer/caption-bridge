"""Ordering and shutdown regressions for quality-aware translation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import AppConfig
from app.state import SegmentQuality, SessionManager
from app.translate import TranslationDispatcher


def _quality(reason: str) -> SegmentQuality:
    return SegmentQuality(
        flagged=True,
        reasons=[reason],
        retried=False,
        repair_succeeded=None,
        final_flagged=True,
        final_reasons=[reason],
        repair_attempts=0,
    )


def test_out_of_order_quality_results_are_delivered_in_sequence() -> None:
    manager = SessionManager(
        AppConfig(_env_file=None, MISTRAL_TTS_ENABLED=False)
    )
    events: list[dict] = []
    manager.subscribe(events.append)
    manager.finalize_segment("Synthetic first segment.")
    manager.finalize_segment("Synthetic second segment.")
    session_id = manager.session.id

    manager.mark_translated(
        2,
        "Second translation.",
        "en",
        session_id,
        quality=_quality("length_ratio"),
    )

    assert [event for event in events if event["type"] == "caption"] == []

    manager.mark_translated(
        1,
        "First translation.",
        "en",
        session_id,
        quality=_quality("prompt_leakage"),
    )

    captions = [event for event in events if event["type"] == "caption"]
    assert [event["seq"] for event in captions] == [1, 2]
    assert manager.session.segments[0].quality.reasons == ["prompt_leakage"]
    assert manager.session.segments[1].quality.reasons == ["length_ratio"]


def test_quality_repair_propagates_shutdown_cancellation() -> None:
    async def scenario() -> None:
        config = MagicMock()
        config.mistral_api_key = "test-key"
        config.translate_model = "test-model"
        config.translation_timeout_ms = 10_000
        config.translation_repair_max_attempts = 1
        dispatcher = TranslationDispatcher(MagicMock(), config)
        repair_started = asyncio.Event()
        never_finish = asyncio.Event()

        async def blocked_repair(_messages: list[dict]) -> str:
            repair_started.set()
            await never_finish.wait()
            return "unreachable"

        dispatcher._call_repair_api = blocked_repair
        task = asyncio.create_task(
            dispatcher._check_and_repair(
                "Caption: Hello",
                SimpleNamespace(source_text="Hello world"),
                "en",
            )
        )
        await repair_started.wait()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert task.cancelled()

    asyncio.run(scenario())
