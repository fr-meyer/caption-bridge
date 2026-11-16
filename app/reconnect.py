"""Bounded realtime transcription reconnection management."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal

from app.asr_diagnostics import AsrDiagnostics, safe_asr_reason

if TYPE_CHECKING:
    from app.boundary import BoundaryDetector
    from app.config import AppConfig
    from app.state import SessionManager

logger = logging.getLogger(__name__)

_POST_HANDSHAKE_HEALTH_TIMEOUT_S = 2.0
_RECOVERABLE_CLOSE_CODES = frozenset({1001, 1006, 1011, 1012, 1013})
_PERMANENT_HTTP_STATUSES = frozenset({400, 401, 403, 404, 405, 409, 422})


@dataclass(frozen=True)
class ReconnectFailureInfo:
    """Privacy-safe classification of a transcription stream failure."""

    category: Literal[
        "provider_restart",
        "websocket_close",
        "transport",
        "provider_transient",
        "provider_configuration",
        "unknown",
    ]
    recoverable: bool
    close_code: int | None = None
    status_code: int | None = None


@dataclass
class ReconnectMetrics:
    cycles_started: int = 0
    attempts: int = 0
    recovered: int = 0
    exhausted: int = 0
    permanent_failures: int = 0
    cancelled: int = 0
    total_downtime_ms: int = 0
    last_outcome: str | None = None


_reconnect_metrics = ReconnectMetrics()


def get_reconnect_metrics() -> dict[str, int | str | None]:
    return asdict(_reconnect_metrics)


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 4:
        return int(value)
    return None


def _extract_close_code(exc: Exception) -> int | None:
    direct = _coerce_int(getattr(exc, "code", None))
    if direct is not None and 1000 <= direct <= 4999:
        return direct
    for attr in ("rcvd", "sent"):
        frame = getattr(exc, attr, None)
        code = _coerce_int(getattr(frame, "code", None))
        if code is not None and 1000 <= code <= 4999:
            return code
    return None


def classify_reconnect_failure(exc: Exception) -> ReconnectFailureInfo:
    """Classify without retaining exception text or provider response bodies."""
    seen = set()
    current: BaseException | None = exc
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        info = _classify_direct_failure(current)
        if info.category != "unknown":
            return info
        current = current.__cause__ or current.__context__
    return ReconnectFailureInfo(category="unknown", recoverable=True)


def _classify_direct_failure(exc: BaseException) -> ReconnectFailureInfo:
    close_code = _extract_close_code(exc)
    status_code = _coerce_int(getattr(exc, "status_code", None))
    if status_code is not None and not 100 <= status_code <= 599:
        status_code = None

    if close_code == 1012:
        return ReconnectFailureInfo(
            category="provider_restart", recoverable=True, close_code=close_code
        )
    if close_code is not None:
        return ReconnectFailureInfo(
            category="websocket_close",
            recoverable=close_code in _RECOVERABLE_CLOSE_CODES,
            close_code=close_code,
        )
    if status_code in _PERMANENT_HTTP_STATUSES:
        return ReconnectFailureInfo(
            category="provider_configuration",
            recoverable=False,
            status_code=status_code,
        )
    if status_code == 429 or (status_code is not None and status_code >= 500):
        return ReconnectFailureInfo(
            category="provider_transient",
            recoverable=True,
            status_code=status_code,
        )
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return ReconnectFailureInfo(category="transport", recoverable=True)

    # Unknown SDK failures retain the old reconnect behavior, but the retry and
    # elapsed-time ceilings below make that behavior safe.
    return ReconnectFailureInfo(category="unknown", recoverable=True)


class ReconnectionManager:
    """Reconnect a dropped transcription stream within explicit ceilings."""

    def __init__(self, session_manager: SessionManager, config: AppConfig) -> None:
        self._sm = session_manager
        self._config = config
        self._retry_task: asyncio.Task[None] | None = None
        self._attempt_id: int = 0
        self._attempt_failed: asyncio.Event = asyncio.Event()
        self._attempt_summary: tuple[ReconnectFailureInfo, str] | None = None
        self.diagnostics = AsrDiagnostics()

        self.get_detector: Callable[[], BoundaryDetector | None] | None = None
        self.teardown_pipeline: Callable[[], Awaitable[None]] | None = None
        self.start_pipeline: Callable[[], Awaitable[None]] | None = None
        self.finalize_reconnect_fragment: Callable[[str], None] | None = None
        self.wait_for_stream: Callable[[], Awaitable[None]] | None = None

    @property
    def current_attempt_id(self) -> int:
        return self._attempt_id

    @property
    def attempt_failed(self) -> asyncio.Event:
        return self._attempt_failed

    def signal_attempt_failed(self, exc: Exception | None = None) -> None:
        """Signal that the current reconnect attempt failed post-handshake."""
        if exc is not None and self._attempt_summary is None:
            self._attempt_summary = (classify_reconnect_failure(exc), safe_asr_reason(exc))
        self._attempt_failed.set()

    def record_stream_failure(self, exc: Exception, attempt_id: int) -> bool:
        return self.diagnostics.failure(exc, attempt_id=attempt_id,
                                        info=classify_reconnect_failure(exc))

    def begin_run(self) -> None:
        # A cancelled older retry may settle after the next Start. Give each
        # run its own sink so that its terminal event keeps the old correlation.
        self.diagnostics = AsrDiagnostics()

    def on_connection_error(self, exc: Exception) -> None:
        if self._sm.session.status not in ("listening", "reconnecting"):
            return
        self.record_stream_failure(exc, self._attempt_id)
        if self._retry_task is not None and not self._retry_task.done():
            if self._sm.session.status == "reconnecting":
                logger.info("Failure during active reconnect attempt")
                self.signal_attempt_failed(exc)
            else:
                logger.info("Reconnect already in progress")
            return
        self._retry_task = asyncio.create_task(self._reconnect_loop(exc, started=time.monotonic()))

    def cancel(self) -> None:
        if self._retry_task is not None:
            self._retry_task.cancel()
            self._retry_task = None
        self._attempt_failed.clear()
        self._attempt_summary = None

    def _emit_unavailable(
        self,
        info: ReconnectFailureInfo,
        *,
        outcome: str,
        attempts: int,
        downtime_ms: int,
    ) -> None:
        self._sm._emit(
            "provider_temporarily_unavailable",
            {
                "service": "transcription",
                "outcome": outcome,
                "attempts": attempts,
                "downtime_ms": downtime_ms,
                "close_class": info.category,
                "close_code": info.close_code,
                "status_code": info.status_code,
                "max_attempts": self._config.reconnect_max_attempts,
                "manual_recovery_available": outcome in {"exhausted", "permanent"},
            },
        )

    async def _reconnect_loop(self, exc: Exception, *, started: float | None = None) -> None:
        if started is None:
            started = time.monotonic()
        attempts = 0
        initial_info = classify_reconnect_failure(exc)
        last_info = initial_info
        last_reason = safe_asr_reason(exc)
        diagnostics = self.diagnostics
        attempt_id = self._attempt_id
        diagnostics.failure(exc, attempt_id=attempt_id, info=initial_info)
        diagnostics.emit("reconnect_started", attempt_id=attempt_id,
                              reason=last_reason, info=initial_info)
        _reconnect_metrics.cycles_started += 1

        try:
            self._sm.set_status("reconnecting")
            self._emit_unavailable(
                initial_info, outcome="retrying", attempts=0, downtime_ms=0
            )

            if self.get_detector is not None:
                detector = self.get_detector()
                if detector is not None:
                    fragment = detector.flush_reconnect_fragment()
                    if fragment is not None and self.finalize_reconnect_fragment is not None:
                        self.finalize_reconnect_fragment(fragment)

            self._sm.update_partial("")

            assert self.teardown_pipeline is not None
            await self.teardown_pipeline()

            if not initial_info.recoverable:
                _reconnect_metrics.permanent_failures += 1
                _reconnect_metrics.last_outcome = "permanent"
                downtime_ms = int((time.monotonic() - started) * 1000)
                _reconnect_metrics.total_downtime_ms += downtime_ms
                self._emit_unavailable(
                    initial_info,
                    outcome="permanent",
                    attempts=0,
                    downtime_ms=downtime_ms,
                )
                diagnostics.emit("permanent", attempt_id=attempt_id,
                                      reason=last_reason, info=initial_info,
                                      downtime_ms=downtime_ms)
                self._sm.set_status("session_ended")
                return

            backoff_ms = self._config.reconnect_base_backoff_ms
            assert self.start_pipeline is not None

            while attempts < self._config.reconnect_max_attempts:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                jitter = random.uniform(
                    -self._config.reconnect_jitter_factor,
                    self._config.reconnect_jitter_factor,
                )
                delay_ms = max(0, int(backoff_ms * (1 + jitter)))
                if elapsed_ms + delay_ms > self._config.reconnect_max_elapsed_ms:
                    break

                await asyncio.sleep(delay_ms / 1000)
                attempts += 1
                self._attempt_id += 1
                attempt_id = self._attempt_id
                _reconnect_metrics.attempts += 1
                self._attempt_failed.clear()
                self._attempt_summary = None
                diagnostics.emit("reconnect_attempt", attempt_id=attempt_id,
                                      reason=last_reason, info=last_info, attempt=attempts,
                                      downtime_ms=int((time.monotonic() - started) * 1000))
                self._sm._emit(
                    "reconnect_attempt",
                    {
                        "service": "transcription",
                        "attempt": attempts,
                        "max_attempts": self._config.reconnect_max_attempts,
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    },
                )

                try:
                    await self.start_pipeline()
                    if self.wait_for_stream is not None:
                        await self.wait_for_stream()

                    try:
                        await asyncio.wait_for(
                            self._attempt_failed.wait(),
                            timeout=_POST_HANDSHAKE_HEALTH_TIMEOUT_S,
                        )
                        raise RuntimeError(
                            "Stream failed post-handshake health check"
                        )
                    except asyncio.TimeoutError:
                        pass

                    if self._attempt_failed.is_set():
                        raise RuntimeError(
                            "Stream failed post-handshake health check"
                        )

                    self._sm.set_status("listening")
                    self._sm.update_partial("")
                    downtime_ms = int((time.monotonic() - started) * 1000)
                    _reconnect_metrics.recovered += 1
                    _reconnect_metrics.total_downtime_ms += downtime_ms
                    _reconnect_metrics.last_outcome = "recovered"
                    self._sm._emit(
                        "recovered",
                        {
                            "service": "transcription",
                            "attempts": attempts,
                            "downtime_ms": downtime_ms,
                        },
                    )
                    diagnostics.emit("recovered", attempt_id=attempt_id,
                                          attempt=attempts, downtime_ms=downtime_ms)
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as retry_exc:
                    if self._attempt_summary is not None:
                        last_info, last_reason = self._attempt_summary
                    else:
                        last_info, last_reason = classify_reconnect_failure(retry_exc), safe_asr_reason(retry_exc)
                    diagnostics.failure(retry_exc, attempt_id=attempt_id,
                                             info=last_info, reason=last_reason)
                    diagnostics.emit("reconnect_attempt_failed", attempt_id=attempt_id,
                                          reason=last_reason, info=last_info, attempt=attempts,
                                          downtime_ms=int((time.monotonic() - started) * 1000))
                    await self.teardown_pipeline()
                    if not last_info.recoverable:
                        break
                    backoff_ms = min(
                        backoff_ms * 2, self._config.reconnect_max_backoff_ms
                    )

            downtime_ms = int((time.monotonic() - started) * 1000)
            if last_info.recoverable:
                _reconnect_metrics.exhausted += 1
                outcome = "exhausted"
            else:
                _reconnect_metrics.permanent_failures += 1
                outcome = "permanent"
            _reconnect_metrics.total_downtime_ms += downtime_ms
            _reconnect_metrics.last_outcome = outcome
            self._emit_unavailable(
                last_info,
                outcome=outcome,
                attempts=attempts,
                downtime_ms=downtime_ms,
            )
            diagnostics.emit(outcome, attempt_id=attempt_id, reason=last_reason,
                                  info=last_info, attempt=attempts, downtime_ms=downtime_ms)
            self._sm.set_status("session_ended")
        except asyncio.CancelledError:
            downtime_ms = int((time.monotonic() - started) * 1000)
            _reconnect_metrics.cancelled += 1
            _reconnect_metrics.total_downtime_ms += downtime_ms
            _reconnect_metrics.last_outcome = "cancelled"
            self._sm._emit(
                "reconnect_cancelled",
                {
                    "service": "transcription",
                    "attempts": attempts,
                    "downtime_ms": downtime_ms,
                },
            )
            diagnostics.emit("cancelled", attempt_id=attempt_id,
                                  attempt=attempts, downtime_ms=downtime_ms)
            raise
