"""Reconnection manager."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.boundary import BoundaryDetector
    from app.config import AppConfig
    from app.state import SessionManager

logger = logging.getLogger(__name__)


class ReconnectionManager:
    """Handles automatic reconnection with exponential backoff when the
    transcription stream drops unexpectedly."""

    def __init__(self, session_manager: SessionManager, config: AppConfig) -> None:
        self._sm = session_manager
        self._config = config
        self._retry_task: asyncio.Task[None] | None = None

        self.get_detector: Callable[[], BoundaryDetector | None] | None = None
        self.teardown_pipeline: Callable[[], Awaitable[None]] | None = None
        self.start_pipeline: Callable[[], Awaitable[None]] | None = None
        self.finalize_reconnect_fragment: Callable[[str], None] | None = None
        self.wait_for_stream: Callable[[], Awaitable[None]] | None = None

    def on_connection_error(self, exc: Exception) -> None:
        if self._sm.session.status not in ("listening", "reconnecting"):
            return
        if self._retry_task is not None and not self._retry_task.done():
            logger.info("Reconnect already in progress — ignoring duplicate error")
            return
        self._retry_task = asyncio.ensure_future(self._reconnect_loop(exc))

    def cancel(self) -> None:
        if self._retry_task is not None:
            self._retry_task.cancel()
            self._retry_task = None

    async def _reconnect_loop(self, exc: Exception) -> None:
        try:
            self._sm.set_status("reconnecting")
            self._sm._emit("error", {"message": str(exc)})

            if self.get_detector is not None:
                detector = self.get_detector()
                if detector is not None:
                    fragment = detector.flush_reconnect_fragment()
                    if fragment is not None and self.finalize_reconnect_fragment is not None:
                        self.finalize_reconnect_fragment(fragment)

            self._sm.update_partial("")

            assert self.teardown_pipeline is not None
            await self.teardown_pipeline()

            backoff_ms = 1000
            assert self.start_pipeline is not None
            while True:
                await asyncio.sleep(backoff_ms / 1000)
                try:
                    await self.start_pipeline()
                    if self.wait_for_stream is not None:
                        await self.wait_for_stream()
                    self._sm.set_status("listening")
                    self._sm.update_partial("")
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as retry_exc:
                    logger.warning(
                        "Reconnect attempt failed (backoff=%dms): %s",
                        backoff_ms,
                        retry_exc,
                    )
                    await self.teardown_pipeline()
                    backoff_ms = min(
                        backoff_ms * 2, self._config.reconnect_max_backoff_ms
                    )
        except asyncio.CancelledError:
            logger.info("Reconnect loop cancelled")
            raise
