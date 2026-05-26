"""Tests for segment boundary hold/merge behavior."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from app.boundary import BoundaryDetector, MIN_SEGMENT_CHARS, MIN_SEGMENT_TOKENS


def _make_detector(
    pause_timeout_s: float = 1.5,
) -> tuple[BoundaryDetector, MagicMock, MagicMock]:
    on_partial = MagicMock()
    on_finalize = MagicMock()
    detector = BoundaryDetector(
        pause_timeout_s=pause_timeout_s,
        on_partial=on_partial,
        on_finalize=on_finalize,
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
