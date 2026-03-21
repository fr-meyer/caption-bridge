"""Segment boundary detection."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Hangul syllable followed by sentence-ending punctuation (anywhere in text).
_SENTENCE_END_RE = re.compile(r"[\uAC00-\uD7A3][.!?]")


class BoundaryDetector:
    """Accumulates transcription deltas and fires callbacks on segment boundaries.

    A boundary is detected either by Korean sentence-ending punctuation or by a
    pause timeout (no new deltas within *pause_timeout_s* seconds).
    """

    def __init__(
        self,
        pause_timeout_s: float = 1.5,
        on_partial: Callable[[str], None] | None = None,
        on_finalize: Callable[[str], None] | None = None,
    ) -> None:
        self._pause_timeout_s = pause_timeout_s
        self._on_partial = on_partial
        self._on_finalize = on_finalize

        self._buffer: str = ""
        self._timer_handle: asyncio.TimerHandle | None = None

    def push(self, text: str) -> None:
        """Append a text delta and evaluate boundary conditions."""
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
                loop = asyncio.get_event_loop()
                self._timer_handle = loop.call_later(
                    self._pause_timeout_s, self._on_pause_timeout
                )
        else:
            if self._on_partial is not None:
                self._on_partial(self._buffer)
            loop = asyncio.get_event_loop()
            self._timer_handle = loop.call_later(
                self._pause_timeout_s, self._on_pause_timeout
            )

    def _finalize(self) -> None:
        if not self._buffer:
            return
        self._cancel_timer()
        text = self._buffer
        self._buffer = ""
        if self._on_finalize is not None:
            self._on_finalize(text)

    def _on_pause_timeout(self) -> None:
        logger.debug("Pause timeout fired — finalizing segment")
        self._finalize()

    def _cancel_timer(self) -> None:
        if self._timer_handle is not None:
            self._timer_handle.cancel()
            self._timer_handle = None

    def flush_reconnect_fragment(self) -> str | None:
        """Return and clear the current buffer (hook for reconnection manager)."""
        if not self._buffer:
            return None
        self._cancel_timer()
        text = self._buffer
        self._buffer = ""
        return text

    def reset(self) -> None:
        """Clear all state. Used on clean shutdown."""
        self._buffer = ""
        self._cancel_timer()
