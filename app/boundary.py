"""Segment boundary detection."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Sentence-ending punctuation with two heuristic branches:
#   1. Latin (. ! ?) requires trailing whitespace or end-of-buffer to avoid
#      splitting on abbreviations, decimals, etc.
#   2. CJK / Arabic (。 ！ ？ ؟) split immediately — these scripts don't use
#      inter-sentence whitespace.
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)|[。！？؟]")

MIN_SEGMENT_CHARS = 15
MIN_SEGMENT_TOKENS = 3
_TERMINAL_PUNCT_RE = re.compile(r"[.!?。！？؟]\s*$")
_HANGUL_RE = re.compile(r"[가-힣]")
_TRAILING_CLOSERS_RE = re.compile(r"[\"'’”)}\]〉》」』]+$")

# Korean transcription commonly arrives without punctuation. Clear formal and
# polite sentence-closing endings can finalize at the ordinary pause timeout.
# Other Hangul endings are conservatively held for more speech or a bounded
# longer silence. This avoids pretending that a lightweight regex is a full
# morphological analyzer.
_KOREAN_CLEAR_FINAL_END_RE = re.compile(
    r"(?:"
    r"니다|"
    r"아요|어요|해요|예요|이에요|"
    r"지요|죠|네요|군요|구나|나요|까요|세요|십시오"
    r")$"
)


class BoundaryDetector:
    """Accumulates transcription deltas and fires callbacks on segment boundaries.

    A boundary is detected by sentence-ending punctuation **or** by a pause
    timeout (no new deltas within *pause_timeout_s* seconds).

    Punctuation split policy
    ------------------------
    * **Latin** (`. ! ?`): split only when followed by whitespace or the end
      of the current buffer, reducing false positives on abbreviations and
      decimal numbers.
    * **CJK / Arabic** (`。 ！ ？ ؟`): split immediately after the mark,
      because these scripts do not use inter-sentence whitespace.
    """

    def __init__(
        self,
        pause_timeout_s: float = 1.5,
        on_partial: Callable[[str], None] | None = None,
        on_finalize: Callable[[str], None] | None = None,
        fragment_merge_enabled: bool = True,
        fragment_max_hold_s: float = 3.0,
        min_segment_chars: int = MIN_SEGMENT_CHARS,
        min_segment_tokens: int = MIN_SEGMENT_TOKENS,
    ) -> None:
        self._pause_timeout_s = pause_timeout_s
        self._on_partial = on_partial
        self._on_finalize = on_finalize
        self._fragment_merge_enabled = fragment_merge_enabled
        self._min_segment_chars = min_segment_chars
        self._min_segment_tokens = min_segment_tokens

        self._buffer: str = ""
        self._timer_handle: asyncio.TimerHandle | None = None
        self._max_hold_ms = max(0.0, fragment_max_hold_s * 1000)
        self._held: bool = False
        self._hold_started_at: float | None = None

    def push(self, text: str) -> None:
        """Append a text delta and evaluate boundary conditions."""
        self._held = False
        self._buffer += text
        self._cancel_timer()

        matches = list(_SENTENCE_END_RE.finditer(self._buffer))

        if matches:
            full_buf = self._buffer
            cursor = 0
            for m in matches:
                split_pos = m.end()
                segment = full_buf[cursor:split_pos]
                self._buffer = segment
                if self._on_partial is not None:
                    self._on_partial(self._buffer)
                self._finalize()
                cursor = split_pos

            self._buffer = full_buf[cursor:].lstrip()

            if self._buffer:
                if self._on_partial is not None:
                    self._on_partial(self._buffer)
                loop = asyncio.get_running_loop()
                self._timer_handle = loop.call_later(
                    self._pause_timeout_s, self._on_pause_timeout
                )
        else:
            if self._on_partial is not None:
                self._on_partial(self._buffer)
            loop = asyncio.get_running_loop()
            self._timer_handle = loop.call_later(
                self._pause_timeout_s, self._on_pause_timeout
            )

    def _finalize(self) -> None:
        if not self._buffer:
            return
        self._cancel_timer()
        text = self._buffer
        self._buffer = ""
        self._held = False
        self._hold_started_at = None
        if self._on_finalize is not None:
            self._on_finalize(text)

    def _on_pause_timeout(self) -> None:
        logger.debug("Pause timeout fired — evaluating segment")

        if _TERMINAL_PUNCT_RE.search(self._buffer):
            self._finalize()
            return

        defer_reason = self._pause_defer_reason()
        if defer_reason is None:
            self._finalize()
            return

        if self._hold_started_at is None:
            self._hold_started_at = time.monotonic()

        elapsed_ms = (time.monotonic() - self._hold_started_at) * 1000
        if elapsed_ms < self._max_hold_ms:
            self._held = True
            logger.debug(
                "Deferring pause boundary: reason=%s chars=%d",
                defer_reason,
                len(self._buffer),
            )
            if self._on_partial is not None:
                self._on_partial(self._buffer)
            loop = asyncio.get_running_loop()
            remaining_s = (self._max_hold_ms - elapsed_ms) / 1000
            self._timer_handle = loop.call_later(
                min(self._pause_timeout_s, remaining_s),
                self._on_pause_timeout,
            )
            return

        logger.debug(
            "Fragment hold ceiling reached: reason=%s chars=%d",
            defer_reason,
            len(self._buffer),
        )
        self._finalize()

    def _pause_defer_reason(self) -> str | None:
        """Return a content-free reason when a pause is not a strong boundary."""
        if not self._fragment_merge_enabled:
            return None

        stripped = self._buffer.strip()
        if not stripped:
            return None

        tail = _TRAILING_CLOSERS_RE.sub("", stripped)
        last_token = tail.rsplit(maxsplit=1)[-1] if tail else ""
        if _HANGUL_RE.search(last_token):
            if _KOREAN_CLEAR_FINAL_END_RE.search(last_token):
                return None
            return "korean_nonfinal_ending"

        token_count = len(stripped.split())
        if (
            len(stripped) < self._min_segment_chars
            or token_count < self._min_segment_tokens
        ):
            return "short_fragment"

        return None

    def _cancel_timer(self) -> None:
        if self._timer_handle is not None:
            self._timer_handle.cancel()
            self._timer_handle = None

    def flush_buffer(self) -> str | None:
        """Return and clear the current buffer for normal stop-path draining."""
        self._cancel_timer()
        self._held = False
        self._hold_started_at = None
        if not self._buffer:
            return None
        text = self._buffer
        self._buffer = ""
        return text

    def flush_reconnect_fragment(self) -> str | None:
        """Return and clear the current buffer (hook for reconnection manager)."""
        self._cancel_timer()
        self._held = False
        self._hold_started_at = None
        if not self._buffer:
            return None
        text = self._buffer
        self._buffer = ""
        return text

    def reset(self) -> None:
        """Clear all state. Used on clean shutdown."""
        self._buffer = ""
        self._cancel_timer()
        self._held = False
        self._hold_started_at = None
