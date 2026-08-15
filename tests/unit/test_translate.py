"""Tests for translation message construction and system prompt."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.translate import TranslationDispatcher, _build_system_prompt


def _make_dispatcher() -> TranslationDispatcher:
    config = MagicMock()
    config.mistral_api_key = "test-key"
    config.translate_model = "test-model"
    return TranslationDispatcher(MagicMock(), config)


def _make_segment(source_text: str = "Hello world", seq: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        source_text=source_text,
        segment_kind="complete",
        seq=seq,
    )


def _user_message(messages: list[dict]) -> str:
    return next(msg["content"] for msg in messages if msg["role"] == "user")


def test_context_tags_present_when_context_given() -> None:
    dispatcher = _make_dispatcher()
    segment = _make_segment("Translate me")
    context = [_make_segment("Prior context", seq=0)]

    messages = dispatcher._build_messages(segment, context, "en")
    user_content = _user_message(messages)

    assert "<context_do_not_translate>" in user_content
    assert "<segment_to_translate>" in user_content


def test_no_context_tag_when_no_context() -> None:
    dispatcher = _make_dispatcher()
    segment = _make_segment("Translate me")

    messages = dispatcher._build_messages(segment, [], "en")
    user_content = _user_message(messages)

    assert "<segment_to_translate>" in user_content
    assert "<context_do_not_translate>" not in user_content


def test_system_prompt_forbids_wrapper_phrases() -> None:
    prompt = _build_system_prompt("en")

    assert '"Caption:"' in prompt
    assert '"Here\'s the translation:"' in prompt
    assert '"Translation:"' in prompt


def test_system_prompt_forbids_alternatives() -> None:
    prompt = _build_system_prompt("en")

    assert "no multiple alternatives" in prompt


def test_system_prompt_forbids_context_echo() -> None:
    prompt = _build_system_prompt("en")

    assert "Do not translate or echo any context block" in prompt


def test_system_prompt_forbids_markdown() -> None:
    prompt = _build_system_prompt("en")

    assert "no markdown" in prompt


def test_retry_logs_exclude_provider_details(monkeypatch, caplog) -> None:
    dispatcher = _make_dispatcher()
    dispatcher._await_translation = AsyncMock(
        side_effect=RuntimeError("sensitive retry provider body")
    )
    monkeypatch.setattr("app.translate.asyncio.sleep", AsyncMock())
    caplog.set_level("WARNING")

    result = asyncio.run(
        dispatcher._generic_one_second_retry(
            messages=[],
            timeout_s=1.0,
            seq=7,
            session_id="session-1",
            target_language="en",
            cause_exc=RuntimeError("sensitive first provider body"),
        )
    )

    assert result is None
    assert "sensitive first provider body" not in caplog.text
    assert "sensitive retry provider body" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    dispatcher._session_manager.mark_translation_failed.assert_called_once_with(
        7, "session-1"
    )
