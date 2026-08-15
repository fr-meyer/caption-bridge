"""Tests for segment boundary hold/merge behavior."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.boundary import MIN_SEGMENT_CHARS, MIN_SEGMENT_TOKENS, BoundaryDetector


def _make_detector(
    pause_timeout_s: float = 1.5,
    *,
    fragment_merge_enabled: bool = True,
    fragment_max_hold_s: float = 3.0,
    min_segment_chars: int = MIN_SEGMENT_CHARS,
    min_segment_tokens: int = MIN_SEGMENT_TOKENS,
) -> tuple[BoundaryDetector, MagicMock, MagicMock]:
    on_partial = MagicMock()
    on_finalize = MagicMock()
    detector = BoundaryDetector(
        pause_timeout_s=pause_timeout_s,
        on_partial=on_partial,
        on_finalize=on_finalize,
        fragment_merge_enabled=fragment_merge_enabled,
        fragment_max_hold_s=fragment_max_hold_s,
        min_segment_chars=min_segment_chars,
        min_segment_tokens=min_segment_tokens,
    )
    return detector, on_partial, on_finalize


@patch("asyncio.get_running_loop")
def test_hold_fires_on_short_buffer(mock_loop: MagicMock) -> None:
    detector, on_partial, on_finalize = _make_detector()
    detector.push("hello")

    detector._on_pause_timeout()

    on_finalize.assert_not_called()
    assert detector._held is True
    on_partial.assert_called()


@patch("asyncio.get_running_loop")
def test_hold_budget_exhaustion_finalizes(mock_loop: MagicMock) -> None:
    detector, _on_partial, on_finalize = _make_detector()
    detector.push("hello")
    detector._hold_started_at = time.monotonic() - (detector._max_hold_ms / 1000 + 1)

    detector._on_pause_timeout()

    on_finalize.assert_called_once()
    assert on_finalize.call_args[0][0] == "hello"


@patch("asyncio.get_running_loop")
def test_fragment_merge_after_hold(mock_loop: MagicMock) -> None:
    detector, _on_partial, on_finalize = _make_detector()
    detector.push("hello")
    detector._on_pause_timeout()
    assert detector._held is True

    merged_text = "hello world test"
    assert len(merged_text.strip()) >= MIN_SEGMENT_CHARS
    assert len(merged_text.split()) >= MIN_SEGMENT_TOKENS
    detector.push(" world test")

    detector._on_pause_timeout()

    on_finalize.assert_called_once()
    assert on_finalize.call_args[0][0] == merged_text


@patch("asyncio.get_running_loop")
def test_punctuation_bypass_hold(mock_loop: MagicMock) -> None:
    detector, _on_partial, on_finalize = _make_detector()
    short_sentence = "Hello."
    assert len(short_sentence) < MIN_SEGMENT_CHARS

    detector.push(short_sentence)

    on_finalize.assert_called_once_with(short_sentence)
    assert detector._held is False


@patch("asyncio.get_running_loop")
def test_reconnect_fragment_bypasses_hold(mock_loop: MagicMock) -> None:
    detector, _on_partial, on_finalize = _make_detector()
    detector.push("short")

    text = detector.flush_reconnect_fragment()

    assert text == "short"
    assert detector._held is False
    assert detector._hold_started_at is None
    on_finalize.assert_not_called()


@patch("asyncio.get_running_loop")
def test_hold_state_reset_on_new_delta(mock_loop: MagicMock) -> None:
    detector, _on_partial, on_finalize = _make_detector()
    detector.push("hello")
    detector._on_pause_timeout()
    assert detector._held is True

    detector.push(" more")

    assert detector._held is False
    on_finalize.assert_not_called()


@patch("asyncio.get_running_loop")
def test_long_buffer_finalizes_immediately(mock_loop: MagicMock) -> None:
    detector, _on_partial, on_finalize = _make_detector()
    long_buffer = "one two three four five"
    assert len(long_buffer.strip()) >= MIN_SEGMENT_CHARS
    assert len(long_buffer.split()) >= MIN_SEGMENT_TOKENS

    detector.push(long_buffer)
    detector._on_pause_timeout()

    on_finalize.assert_called_once_with(long_buffer)
    assert detector._held is False


@patch("asyncio.get_running_loop")
def test_long_korean_nonfinal_clause_is_held(mock_loop: MagicMock) -> None:
    detector, on_partial, on_finalize = _make_detector()
    fragment = "이 결과는 통계적으로 유의미하지만"
    assert len(fragment.strip()) >= MIN_SEGMENT_CHARS
    assert len(fragment.split()) >= MIN_SEGMENT_TOKENS

    detector.push(fragment)
    detector._on_pause_timeout()

    on_finalize.assert_not_called()
    assert detector._held is True
    assert detector._pause_defer_reason() == "korean_nonfinal_ending"
    on_partial.assert_any_call(fragment)


@patch("asyncio.get_running_loop")
def test_korean_fragment_merges_until_clear_sentence_end(
    mock_loop: MagicMock,
) -> None:
    detector, on_partial, on_finalize = _make_detector()
    fragment = "이 결과는 통계적으로 유의미하지만"

    detector.push(fragment)
    detector._on_pause_timeout()
    detector.push(" 추가 검증이 필요합니다.")

    merged = fragment + " 추가 검증이 필요합니다."
    on_finalize.assert_called_once_with(merged)
    on_partial.assert_any_call(merged)
    assert detector._held is False


@patch("asyncio.get_running_loop")
@pytest.mark.parametrize(
    "complete_text",
    [
        "이 결과는 통계적으로 유의미합니다",
        "맞아요",
        "이 결과는 통계적으로 유의미합니다”",
    ],
)
def test_clear_korean_final_endings_finalize_at_first_pause(
    mock_loop: MagicMock,
    complete_text: str,
) -> None:
    detector, _on_partial, on_finalize = _make_detector()

    detector.push(complete_text)
    detector._on_pause_timeout()

    on_finalize.assert_called_once_with(complete_text)
    assert detector._held is False


@patch("asyncio.get_running_loop")
def test_mixed_caption_with_latin_tail_uses_ordinary_threshold(
    mock_loop: MagicMock,
) -> None:
    detector, _on_partial, on_finalize = _make_detector()
    text = "이 모델 is statistically significant"

    detector.push(text)
    detector._on_pause_timeout()

    on_finalize.assert_called_once_with(text)


@patch("asyncio.get_running_loop")
def test_korean_noun_phrase_waits_for_longer_silence(mock_loop: MagicMock) -> None:
    detector, _on_partial, on_finalize = _make_detector()
    detector.push("인공지능의 발전과 조직의 변화")

    detector._on_pause_timeout()

    on_finalize.assert_not_called()
    assert detector._held is True


@patch("asyncio.get_running_loop")
def test_fragment_merge_can_be_disabled(mock_loop: MagicMock) -> None:
    detector, _on_partial, on_finalize = _make_detector(
        fragment_merge_enabled=False
    )
    fragment = "이 결과는 통계적으로 유의미하지만"

    detector.push(fragment)
    detector._on_pause_timeout()

    on_finalize.assert_called_once_with(fragment)
    assert detector._held is False


@patch("asyncio.get_running_loop")
def test_zero_fragment_hold_finalizes_without_rescheduling(
    mock_loop: MagicMock,
) -> None:
    detector, _on_partial, on_finalize = _make_detector(
        fragment_max_hold_s=0
    )
    detector.push("짧은 구절")

    detector._on_pause_timeout()

    on_finalize.assert_called_once_with("짧은 구절")
    assert detector._held is False
