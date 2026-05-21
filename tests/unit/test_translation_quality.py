"""Tests for deterministic translation quality checks."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.state import SegmentQuality
from app.translate import TranslationDispatcher
from app.translation_quality import (
    QualityCheckResult,
    build_repair_prompt,
    check,
    choose_better_translation,
)


def _make_dispatcher() -> TranslationDispatcher:
    config = MagicMock()
    config.mistral_api_key = "test-key"
    config.translate_model = "test-model"
    config.translation_timeout_ms = 10_000
    return TranslationDispatcher(MagicMock(), config)


def _make_segment(source_text: str = "Hello world") -> SimpleNamespace:
    return SimpleNamespace(source_text=source_text)


def test_prompt_leakage_detected() -> None:
    result = check("Caption: Hello", "Hello", "en")

    assert result.flagged is True
    assert "prompt_leakage" in result.reasons


def test_prompt_leakage_clean() -> None:
    result = check("Hello world", "Hello world", "en")

    assert result.flagged is False


def test_multiple_alternatives_numbered() -> None:
    result = check("1. Option A\n2. Option B", "Choose one", "en")

    assert "multiple_alternatives" in result.reasons


def test_multiple_alternatives_bullet() -> None:
    result = check("- Option A\n- Option B", "Choose one", "en")

    assert "multiple_alternatives" in result.reasons


def test_residual_source_script_hangul_in_latin_target() -> None:
    result = check("Hello 안녕", "Hello", "en")

    assert "residual_source_script" in result.reasons


def test_residual_source_script_clean() -> None:
    result = check("Hello world", "Hello world", "en")

    assert "residual_source_script" not in result.reasons


def test_residual_source_script_greek_in_latin_target() -> None:
    result = check("Γεια σου κόσμε", "Hello world", "en")

    assert "residual_source_script" in result.reasons


def test_residual_source_script_bengali_in_latin_target() -> None:
    result = check("হ্যালো বিশ্ব", "Hello world", "en")

    assert "residual_source_script" in result.reasons


def test_residual_source_script_tamil_in_latin_target() -> None:
    result = check("வணக்கம் உலகம்", "Hello world", "en")

    assert "residual_source_script" in result.reasons


def test_residual_source_script_mixed_ja_not_flagged() -> None:
    result = check("ResNet-50は画像分類モデルです", "ResNet-50 is an image classification model", "ja")

    assert "residual_source_script" not in result.reasons


def test_residual_source_script_native_punctuation_not_flagged() -> None:
    """Native punctuation must not count as significant non-target script characters."""
    result = check(
        "GPT-4は、大規模言語モデル（LLM）です！",
        "GPT-4 is a large language model",
        "ja",
    )

    assert "residual_source_script" not in result.reasons


def test_residual_source_script_high_latin_ratio_with_target_script_not_flagged() -> None:
    """Preserved ASCII terms can dominate latin ratio while target-script text is present."""
    translated = (
        "ResNet-50 BERT GPT-4 Transformer CNN RNN LSTM GRU "
        "Attention LayerNorm BatchNorm は深層学習モデルです"
    )
    result = check(translated, "ResNet-50 is a deep learning model", "ja")

    assert "residual_source_script" not in result.reasons


def test_residual_source_script_mixed_ko_not_flagged() -> None:
    result = check("BERT모델은 자연어 처리에 사용됩니다", "BERT model is used for natural language processing", "ko")

    assert "residual_source_script" not in result.reasons


def test_residual_source_script_mixed_ar_not_flagged() -> None:
    result = check("GPT-4 هو نموذج لغوي كبير", "GPT-4 is a large language model", "ar")

    assert "residual_source_script" not in result.reasons


def test_residual_source_script_fully_latin_ja_flagged() -> None:
    result = check(
        "This is a neural network model for image classification",
        "これは画像分類のためのニューラルネットワークモデルです",
        "ja",
    )

    assert "residual_source_script" in result.reasons


def test_residual_source_script_fully_latin_ko_flagged() -> None:
    result = check(
        "The transformer architecture uses attention mechanisms",
        "트랜스포머 아키텍처는 어텐션 메커니즘을 사용합니다",
        "ko",
    )

    assert "residual_source_script" in result.reasons


def test_residual_source_script_token_target_script_still_flagged() -> None:
    result = check(
        "Transformer attention mechanism の",
        "トランスフォーマーのアテンションメカニズム",
        "ja",
    )

    assert "residual_source_script" in result.reasons


def test_length_ratio_too_short() -> None:
    source = "A" * 25
    result = check("Hi", source, "en")

    assert "length_ratio" in result.reasons


def test_length_ratio_too_long() -> None:
    source = "A" * 25
    translated = "B" * 200
    result = check(translated, source, "en")

    assert "length_ratio" in result.reasons


def test_length_ratio_skipped_short_source() -> None:
    result = check("X", "short", "en")

    assert "length_ratio" not in result.reasons


def test_function_word_only() -> None:
    result = check("the a is", "Some source text", "en")

    assert "function_word_only" in result.reasons


def test_function_word_only_clean() -> None:
    result = check("the neural network", "Some source text", "en")

    assert "function_word_only" not in result.reasons


def test_build_repair_prompt_structure() -> None:
    messages = build_repair_prompt("Hello", "en", ["prompt_leakage"])

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_build_repair_prompt_names_reasons() -> None:
    reasons = ["prompt_leakage", "length_ratio"]
    messages = build_repair_prompt("Hello", "en", reasons)
    user_content = messages[1]["content"]

    assert "prompt_leakage" in user_content
    assert "length_ratio" in user_content


def test_build_repair_prompt_contains_segment_tag() -> None:
    messages = build_repair_prompt("Hello", "en", ["prompt_leakage"])

    assert "<segment_to_translate>" in messages[1]["content"]


def test_choose_better_translation_prefers_clean() -> None:
    raw = "Caption: Hello"
    repair = "Hello world"
    source = "Hello world"

    chosen = choose_better_translation(raw, repair, source, "en")

    assert chosen == repair


def test_choose_better_translation_prefers_fewer_flags() -> None:
    raw = "Caption: Hello 안녕"
    repair = "Caption: Hello"
    source = "Hello world"

    chosen = choose_better_translation(raw, repair, source, "en")

    assert chosen == repair


def test_choose_better_translation_ties_prefer_raw() -> None:
    raw = "Caption: Hello"
    repair = "Translation: Hello"
    source = "Hello world"

    chosen = choose_better_translation(raw, repair, source, "en")

    assert chosen == raw


def test_quality_check_result_shape() -> None:
    result = check("Hello world", "Hello world", "en")

    assert isinstance(result, QualityCheckResult)
    assert isinstance(result.flagged, bool)
    assert isinstance(result.reasons, list)


def test_check_and_repair_clean_repair() -> None:
    dispatcher = _make_dispatcher()
    segment = _make_segment()
    dispatcher._call_repair_api = AsyncMock(return_value="Hello world")

    text, quality = asyncio.run(
        dispatcher._check_and_repair("Caption: Hello", segment, "en")
    )

    assert text == "Hello world"
    assert quality == SegmentQuality(
        flagged=True,
        reasons=["prompt_leakage"],
        retried=True,
        repair_succeeded=True,
    )
    dispatcher._call_repair_api.assert_awaited_once()


def test_check_and_repair_failed_repair() -> None:
    dispatcher = _make_dispatcher()
    segment = _make_segment()
    dispatcher._call_repair_api = AsyncMock(return_value="Caption: Still bad")

    text, quality = asyncio.run(
        dispatcher._check_and_repair("Caption: Hello", segment, "en")
    )

    assert text == "Caption: Hello"
    assert quality == SegmentQuality(
        flagged=True,
        reasons=["prompt_leakage"],
        retried=True,
        repair_succeeded=False,
    )
    dispatcher._call_repair_api.assert_awaited_once()


def test_check_and_repair_timed_out_repair() -> None:
    dispatcher = _make_dispatcher()
    segment = _make_segment()
    dispatcher._call_repair_api = AsyncMock(side_effect=asyncio.TimeoutError())

    text, quality = asyncio.run(
        dispatcher._check_and_repair("Caption: Hello", segment, "en")
    )

    assert text == "Caption: Hello"
    assert quality == SegmentQuality(
        flagged=True,
        reasons=["prompt_leakage"],
        retried=True,
        repair_succeeded=False,
    )
    dispatcher._call_repair_api.assert_awaited_once()
