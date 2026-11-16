"""Content-free ASR lifecycle logs; no exception text or provider identifiers."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from app.pipeline_diagnostics import ASR_REASONS

logger = logging.getLogger(__name__)
_EVENTS = frozenset({
    "stream_connecting", "stream_ready", "stream_failure", "reconnect_started",
    "reconnect_attempt", "reconnect_attempt_failed", "recovered", "exhausted",
    "permanent", "cancelled",
})
_CATEGORIES = frozenset({
    "provider_restart", "websocket_close", "transport", "provider_transient",
    "provider_configuration", "unknown",
})


def safe_asr_reason(exc: BaseException) -> str:
    value = getattr(exc, "reason", None)
    return value if isinstance(value, str) and value in ASR_REASONS else "transport_error"


def _bounded(value: object, maximum: int = 2**63 - 1) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= maximum else None


class AsrDiagnostics:
    """One opaque run and the last failed attempt; no unbounded event history."""

    def __init__(self) -> None:
        self.new_run()

    def new_run(self) -> None:
        self.run_id = uuid.uuid4().hex
        self._last_failed_attempt: int | None = None

    def emit(self, event: str, *, attempt_id: int, reason: str = "none", info=None,
             attempt: int = 0, downtime_ms: int = 0) -> None:
        if event not in _EVENTS or _bounded(attempt_id) is None:
            raise ValueError("invalid ASR diagnostic event")
        category = getattr(info, "category", "unknown")
        if not isinstance(category, str) or category not in _CATEGORIES:
            category = "unknown"
        close = _bounded(getattr(info, "close_code", None), 4999)
        status = _bounded(getattr(info, "status_code", None), 599)
        record = {
            "schema_version": 1,
            "at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event, "run_id": self.run_id, "attempt_id": attempt_id,
            "attempt": _bounded(attempt) or 0,
            "downtime_ms": _bounded(downtime_ms) or 0,
            "reason": reason if isinstance(reason, str) and reason in ASR_REASONS else "transport_error",
            "category": category,
            "close_code": close if close is not None and close >= 1000 else None,
            "status_code": status if status is not None and status >= 100 else None,
        }
        # Uvicorn's normal configuration need not enable INFO on app loggers.
        # Keep the entire outage/recovery audit visible at the default WARNING
        # threshold; routine connection/ready observations remain INFO.
        severity = logging.INFO if event in {"stream_connecting", "stream_ready"} else logging.WARNING
        logger.log(severity, "asr_diagnostic %s", json.dumps(record, separators=(",", ":")))

    def failure(self, exc: BaseException, *, attempt_id: int, info=None, reason: str | None = None) -> bool:
        if attempt_id == self._last_failed_attempt:
            return False
        self.emit("stream_failure", attempt_id=attempt_id,
                  reason=safe_asr_reason(exc) if reason is None else reason, info=info)
        self._last_failed_attempt = attempt_id
        return True
