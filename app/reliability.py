"""Content-free reliability records and history loading."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

import orjson

from app.latency import LatencyTracker, validate_latency_snapshot

if TYPE_CHECKING:
    from app.state import Session

SCHEMA_VERSION = 3
SCHEMA_VERSION_V2 = 2
SCHEMA_VERSION_V1 = 1
ExportOutcome = Literal["not_requested", "succeeded", "failed", "discarded"]
ReconnectOutcome = Literal["none", "recovered", "exhausted", "permanent", "cancelled"]
RunType = Literal["translation_resilience", "full_pipeline"]

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SESSION_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "session_id",
        "recorded_at",
        "started_at",
        "ended_at",
        "duration_ms",
        "terminal_state",
        "translation",
        "reconnect",
        "queues",
        "export",
        "latency",
    }
)
_SESSION_KEYS_V1 = _SESSION_KEYS - {"latency"}

_TRANSLATION_KEYS = frozenset(
    {
        "total",
        "done",
        "failed",
        "timed_out",
        "pending",
        "quality_checked",
        "initially_flagged",
        "repair_attempts",
        "repair_succeeded",
        "still_flagged",
    }
)
_RECONNECT_KEYS = frozenset(
    {
        "cycles",
        "attempts",
        "recovered",
        "exhausted",
        "permanent",
        "cancelled",
        "downtime_ms",
        "last_outcome",
    }
)
_QUEUE_KEYS = frozenset({"audio", "websocket", "tts"})
_AUDIO_KEYS = frozenset({"peak_depth", "dropped"})
_WEBSOCKET_KEYS = frozenset(
    {"peak_depth", "dropped", "coalesced", "critical_drops"}
)
_TTS_KEYS_V2 = frozenset({"peak_depth", "retries", "skipped", "failures"})
_TTS_KEYS = _TTS_KEYS_V2 | {"catch_up_actions", "catch_up_skipped"}
_EXPORT_KEYS = frozenset({"outcome"})
_SOAK_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "run_id",
        "recorded_at",
        "run_type",
        "passed",
        "duration_ms",
        "case_count",
    }
)
_TERMINAL_STATES = frozenset(
    {"idle_blocked", "idle_ready", "listening", "reconnecting", "session_ended"}
)
_EXPORT_OUTCOMES = frozenset({"not_requested", "succeeded", "failed", "discarded"})
_RECONNECT_OUTCOMES = frozenset(
    {"none", "recovered", "exhausted", "permanent", "cancelled"}
)
_RUN_TYPES = frozenset({"translation_resilience", "full_pipeline"})


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _exact_keys(value: object, keys: frozenset[str]) -> bool:
    return isinstance(value, dict) and frozenset(value) == keys


def _valid_timestamp(value: object, *, nullable: bool = False) -> bool:
    if value is None:
        return nullable
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


@dataclass
class ReliabilityTracker:
    """Session-scoped aggregate metrics; event payload text is never retained."""

    export_outcome: ExportOutcome = "not_requested"
    reconnect_cycles: int = 0
    reconnect_attempts: int = 0
    reconnect_recovered: int = 0
    reconnect_exhausted: int = 0
    reconnect_permanent: int = 0
    reconnect_cancelled: int = 0
    reconnect_downtime_ms: int = 0
    reconnect_last_outcome: ReconnectOutcome = "none"
    audio_peak_depth: int = 0
    audio_dropped: int = 0
    websocket_peak_depth: int = 0
    websocket_dropped: int = 0
    websocket_coalesced: int = 0
    websocket_critical_drops: int = 0
    tts_peak_depth: int = 0
    tts_retries: int = 0
    tts_skipped: int = 0
    tts_failures: int = 0
    tts_catch_up_actions: int = 0
    tts_catch_up_skipped: int = 0
    latency: LatencyTracker = field(default_factory=LatencyTracker)

    def observe_event(self, event: dict[str, Any]) -> None:
        """Reduce an application event to allow-listed counters only."""
        event_type = event.get("type")
        if event_type == "provider_temporarily_unavailable":
            outcome = event.get("outcome")
            if outcome == "retrying" and event.get("attempts") == 0:
                self.reconnect_cycles += 1
            elif outcome in {"exhausted", "permanent"}:
                self._observe_reconnect_terminal(str(outcome), event)
        elif event_type == "reconnect_attempt":
            self.reconnect_attempts += 1
        elif event_type == "recovered":
            self._observe_reconnect_terminal("recovered", event)
        elif event_type == "reconnect_cancelled":
            self._observe_reconnect_terminal("cancelled", event)
        elif event_type == "tts_retrying":
            self.tts_retries += 1
        elif event_type == "tts_skipped":
            self.latency.discard_tts(event.get("seq"))
            count = event.get("count", 1)
            count = count if _nonnegative_int(count) else 1
            self.tts_skipped += count
            if event.get("reason") == "user_catch_up":
                self.tts_catch_up_skipped += count
        elif event_type == "tts_caught_up":
            self.tts_catch_up_actions += 1
        elif event_type == "tts_error":
            self.latency.discard_tts(event.get("seq"))
            self.tts_failures += 1

    def _observe_reconnect_terminal(
        self, outcome: str, event: dict[str, Any]
    ) -> None:
        if outcome == "recovered":
            self.reconnect_recovered += 1
        elif outcome == "exhausted":
            self.reconnect_exhausted += 1
        elif outcome == "permanent":
            self.reconnect_permanent += 1
        elif outcome == "cancelled":
            self.reconnect_cancelled += 1
        else:
            return
        downtime_ms = event.get("downtime_ms")
        if _nonnegative_int(downtime_ms):
            self.reconnect_downtime_ms += downtime_ms
        self.reconnect_last_outcome = outcome  # type: ignore[assignment]

    def record_audio_queue(self, depth: int, dropped: int) -> None:
        self.audio_peak_depth = max(self.audio_peak_depth, max(0, depth))
        self.audio_dropped += max(0, dropped)

    def record_websocket_queue(
        self,
        depth: int,
        *,
        dropped: int = 0,
        coalesced: int = 0,
        critical_drops: int = 0,
    ) -> None:
        self.websocket_peak_depth = max(self.websocket_peak_depth, max(0, depth))
        self.websocket_dropped += max(0, dropped)
        self.websocket_coalesced += max(0, coalesced)
        self.websocket_critical_drops += max(0, critical_drops)

    def record_tts_queue(self, depth: int) -> None:
        self.tts_peak_depth = max(self.tts_peak_depth, max(0, depth))

    def set_export_outcome(self, outcome: ExportOutcome) -> None:
        self.export_outcome = outcome

    def snapshot(self) -> dict[str, Any]:
        return {
            "reconnect": {
                "cycles": self.reconnect_cycles,
                "attempts": self.reconnect_attempts,
                "recovered": self.reconnect_recovered,
                "exhausted": self.reconnect_exhausted,
                "permanent": self.reconnect_permanent,
                "cancelled": self.reconnect_cancelled,
                "downtime_ms": self.reconnect_downtime_ms,
                "last_outcome": self.reconnect_last_outcome,
            },
            "queues": {
                "audio": {
                    "peak_depth": self.audio_peak_depth,
                    "dropped": self.audio_dropped,
                },
                "websocket": {
                    "peak_depth": self.websocket_peak_depth,
                    "dropped": self.websocket_dropped,
                    "coalesced": self.websocket_coalesced,
                    "critical_drops": self.websocket_critical_drops,
                },
                "tts": {
                    "peak_depth": self.tts_peak_depth,
                    "retries": self.tts_retries,
                    "skipped": self.tts_skipped,
                    "failures": self.tts_failures,
                    "catch_up_actions": self.tts_catch_up_actions,
                    "catch_up_skipped": self.tts_catch_up_skipped,
                },
            },
            "export": {"outcome": self.export_outcome},
            "latency": self.latency.snapshot(),
        }

    def build_session_record(self, session: Session) -> dict[str, Any]:
        qualities = [segment.quality for segment in session.segments if segment.quality]
        ended_at = session.ended_at
        if session.started_at is not None:
            duration_end = ended_at or datetime.now(timezone.utc)
            duration_ms = max(
                0, round((duration_end - session.started_at).total_seconds() * 1000)
            )
        else:
            duration_ms = 0
        translation = {
            "total": len(session.segments),
            "done": sum(s.translation_status == "done" for s in session.segments),
            "failed": sum(s.translation_status == "failed" for s in session.segments),
            "timed_out": sum(
                s.translation_status == "timed_out" for s in session.segments
            ),
            "pending": sum(
                s.translation_status == "pending" for s in session.segments
            ),
            "quality_checked": len(qualities),
            "initially_flagged": sum(q.flagged for q in qualities),
            "repair_attempts": sum(q.repair_attempts for q in qualities),
            "repair_succeeded": sum(q.repair_succeeded is True for q in qualities),
            "still_flagged": sum(q.final_flagged for q in qualities),
        }
        record = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "session",
            "session_id": session.id,
            "recorded_at": _utcnow_iso(),
            "started_at": (
                session.started_at.isoformat() if session.started_at else None
            ),
            "ended_at": ended_at.isoformat() if ended_at else None,
            "duration_ms": duration_ms,
            "terminal_state": session.status,
            "translation": translation,
            **self.snapshot(),
        }
        # snapshot() already includes latency for runtime metrics;
        # persisted records keep the same object.
        if not validate_session_record(record):
            raise ValueError("invalid reliability session record")
        return record


def validate_session_record(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    version = record.get("schema_version")
    if version == SCHEMA_VERSION_V1:
        if not _exact_keys(record, _SESSION_KEYS_V1):
            return False
    elif version in {SCHEMA_VERSION_V2, SCHEMA_VERSION}:
        if not _exact_keys(record, _SESSION_KEYS):
            return False
        if not validate_latency_snapshot(record.get("latency")):
            return False
    else:
        return False
    if record["record_type"] != "session":
        return False
    if not isinstance(record["session_id"], str) or not _SAFE_ID.fullmatch(
        record["session_id"]
    ):
        return False
    if not _valid_timestamp(record["recorded_at"]):
        return False
    if not _valid_timestamp(record["started_at"], nullable=True):
        return False
    if not _valid_timestamp(record["ended_at"], nullable=True):
        return False
    if not _nonnegative_int(record["duration_ms"]):
        return False
    if record["terminal_state"] not in _TERMINAL_STATES:
        return False

    translation = record["translation"]
    reconnect = record["reconnect"]
    queues = record["queues"]
    export = record["export"]
    if not _exact_keys(translation, _TRANSLATION_KEYS) or not all(
        _nonnegative_int(value) for value in translation.values()
    ):
        return False
    if not _exact_keys(reconnect, _RECONNECT_KEYS):
        return False
    if not all(
        _nonnegative_int(reconnect[key]) for key in _RECONNECT_KEYS - {"last_outcome"}
    ):
        return False
    if reconnect["last_outcome"] not in _RECONNECT_OUTCOMES:
        return False
    if not _exact_keys(queues, _QUEUE_KEYS):
        return False
    queue_specs = (
        (queues["audio"], _AUDIO_KEYS),
        (queues["websocket"], _WEBSOCKET_KEYS),
        (queues["tts"], _TTS_KEYS if version == SCHEMA_VERSION else _TTS_KEYS_V2),
    )
    if any(
        not _exact_keys(queue, keys)
        or not all(_nonnegative_int(value) for value in queue.values())
        for queue, keys in queue_specs
    ):
        return False
    return (
        _exact_keys(export, _EXPORT_KEYS)
        and export["outcome"] in _EXPORT_OUTCOMES
    )


def validate_soak_record(record: object) -> bool:
    if not _exact_keys(record, _SOAK_KEYS):
        return False
    assert isinstance(record, dict)
    return all(
        (
            record["schema_version"] in {SCHEMA_VERSION, SCHEMA_VERSION_V2, SCHEMA_VERSION_V1},
            record["record_type"] == "soak",
            isinstance(record["run_id"], str),
            bool(_SAFE_ID.fullmatch(record["run_id"])),
            _valid_timestamp(record["recorded_at"]),
            record["run_type"] in _RUN_TYPES,
            isinstance(record["passed"], bool),
            _nonnegative_int(record["duration_ms"]),
            _nonnegative_int(record["case_count"]),
        )
    )


def _atomic_write(root: Path, filename: str, record: dict[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / filename
    temporary = root / f".{filename}.{uuid4().hex}.tmp"
    try:
        temporary.write_bytes(orjson.dumps(record, option=orjson.OPT_INDENT_2))
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def write_session_record(root: Path, record: dict[str, Any]) -> Path:
    if not validate_session_record(record):
        raise ValueError("invalid reliability session record")
    return _atomic_write(root, f"session-{record['session_id']}.json", record)


def write_soak_record(
    root: Path,
    *,
    run_type: RunType,
    passed: bool,
    duration_ms: int,
    case_count: int,
) -> Path:
    run_id = uuid4().hex
    record = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "soak",
        "run_id": run_id,
        "recorded_at": _utcnow_iso(),
        "run_type": run_type,
        "passed": passed,
        "duration_ms": duration_ms,
        "case_count": case_count,
    }
    if not validate_soak_record(record):
        raise ValueError("invalid reliability soak record")
    return _atomic_write(root, f"soak-{run_type}-{run_id}.json", record)


def load_history(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Load only exact reliability filenames; transcript exports are never scanned."""
    sessions: list[dict[str, Any]] = []
    soaks: list[dict[str, Any]] = []
    skipped = 0
    for path, validator, destination in (
        *((p, validate_session_record, sessions) for p in root.glob("session-*.json")),
        *((p, validate_soak_record, soaks) for p in root.glob("soak-*.json")),
    ):
        try:
            payload = orjson.loads(path.read_bytes())
        except Exception:
            skipped += 1
            continue
        if not validator(payload):
            skipped += 1
            continue
        destination.append(payload)
    sessions.sort(key=lambda item: item["recorded_at"])
    soaks.sort(key=lambda item: item["recorded_at"])
    return sessions, soaks, skipped
