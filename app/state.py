"""Session state management."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.config import AppConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

Status = Literal[
    "idle_blocked",
    "idle_ready",
    "listening",
    "reconnecting",
    "session_ended",
]

SegmentKind = Literal["complete", "reconnect_fragment"]
TranslationStatus = Literal["pending", "done", "timed_out", "failed"]


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Segment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=_uuid)
    seq: int
    created_at: datetime = Field(default_factory=_utcnow)
    source_text: str
    segment_kind: SegmentKind
    english_text: str | None = None
    translation_status: TranslationStatus = "pending"
    translated_at: datetime | None = None


class ReadinessCheck(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    key: str
    ready: bool
    detail: str


class RecoveryNotice(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recovered_session_id: str
    export_path: str
    created_at: datetime


class Session(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=_uuid)
    status: Status = "idle_blocked"
    started_at: datetime | None = None
    ended_at: datetime | None = None
    source_partial: str = ""
    segments: list[Segment] = Field(default_factory=list)
    next_seq: int = 1
    highest_pushed_seq: int = 0
    exported: bool = False
    export_path: str | None = None
    journal_path: str | None = None
    client_connected: bool = False
    disconnect_grace_until: datetime | None = None


# ---------------------------------------------------------------------------
# Valid status transitions
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[Status, set[Status]] = {
    "idle_blocked": {"idle_ready"},
    "idle_ready": {"idle_blocked", "listening"},
    "listening": {"reconnecting", "session_ended"},
    "reconnecting": {"listening", "session_ended"},
    "session_ended": {"idle_blocked"},
}


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------

EventListener = Callable[[dict[str, Any]], Any]


class SessionManager:
    """Central authority for session state, events, and lifecycle."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.session = Session()
        self.checks: list[ReadinessCheck] = []
        self.recovery_notice: RecoveryNotice | None = None
        self._listeners: list[EventListener] = []
        self._elapsed_task: asyncio.Task[None] | None = None
        self._grace_task: asyncio.Task[None] | None = None
        self._on_grace_expiry: Callable[[], Awaitable[None]] | None = None

    # -- event system -------------------------------------------------------

    def _emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"type": event_type}
        if data:
            payload.update(data)
        for listener in list(self._listeners):
            try:
                listener(payload)
            except Exception:
                logger.exception("Event listener error for %s", event_type)

    def subscribe(self, callback: EventListener) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unsubscribe(self, callback: EventListener) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    # -- partial / segment --------------------------------------------------

    def update_partial(self, text: str) -> None:
        self.session.source_partial = text
        self._emit("source_partial", {"text": text})

    def finalize_segment(self, text: str) -> None:
        seg = Segment(
            seq=self.session.next_seq,
            source_text=text,
            segment_kind="complete",
        )
        self.session.next_seq += 1
        self.session.segments.append(seg)
        self.session.source_partial = ""
        logger.info("Finalized segment #%d: %s", seg.seq, text[:60])
        self._emit("source_partial", {"text": ""})
        self._try_deliver()

    def finalize_reconnect_fragment(self, text: str) -> None:
        seg = Segment(
            seq=self.session.next_seq,
            source_text=text,
            segment_kind="reconnect_fragment",
        )
        self.session.next_seq += 1
        self.session.segments.append(seg)
        self.session.source_partial = ""
        logger.info("Finalized reconnect fragment #%d: %s", seg.seq, text[:60])
        self._emit("source_partial", {"text": ""})
        self._try_deliver()

    # -- translation marks (dormant in this ticket) -------------------------

    def _find_segment(self, seq: int) -> Segment | None:
        for seg in self.session.segments:
            if seg.seq == seq:
                return seg
        return None

    def mark_translated(self, seq: int, english_text: str) -> None:
        seg = self._find_segment(seq)
        if seg is None:
            logger.warning("mark_translated: segment #%d not found", seq)
            return
        seg.english_text = english_text
        seg.translation_status = "done"
        seg.translated_at = _utcnow()
        self._try_deliver()

    def mark_translation_timed_out(self, seq: int) -> None:
        seg = self._find_segment(seq)
        if seg is None:
            logger.warning("mark_translation_timed_out: segment #%d not found", seq)
            return
        seg.translation_status = "timed_out"
        seg.translated_at = _utcnow()
        self._try_deliver()

    def mark_translation_failed(self, seq: int) -> None:
        seg = self._find_segment(seq)
        if seg is None:
            logger.warning("mark_translation_failed: segment #%d not found", seq)
            return
        seg.translation_status = "failed"
        seg.translated_at = _utcnow()
        self._try_deliver()

    # -- delivery gate ------------------------------------------------------

    def _try_deliver(self) -> None:
        """Walk segments in order and emit caption events for deliverable ones.

        A segment is deliverable when its translation_status is not "pending".
        We emit in strict seq order; a pending segment blocks all after it.
        In this ticket no translations happen, so this never fires.
        """
        while True:
            next_seq = self.session.highest_pushed_seq + 1
            seg = self._find_segment(next_seq)
            if seg is None:
                break
            if seg.translation_status == "pending":
                break
            self.session.highest_pushed_seq = seg.seq
            self._emit(
                "caption",
                {
                    "seq": seg.seq,
                    "source_text": seg.source_text,
                    "english_text": seg.english_text,
                    "translation_status": seg.translation_status,
                    "segment_kind": seg.segment_kind,
                },
            )

    # -- status transitions -------------------------------------------------

    def set_status(self, status: Status) -> None:
        current = self.session.status
        if status not in _VALID_TRANSITIONS.get(current, set()):
            logger.warning(
                "Invalid status transition %s → %s; ignoring", current, status
            )
            return

        self.session.status = status

        if status == "listening" and self.session.started_at is None:
            self.session.started_at = _utcnow()

        if status == "listening":
            self._start_elapsed_ticker()

        if status == "session_ended":
            self.session.ended_at = _utcnow()
            self._cancel_elapsed_ticker()
            self._cancel_grace_task()

        self._emit("status", {"status": status})

    # -- readiness ----------------------------------------------------------

    def set_readiness(self, checks: list[ReadinessCheck]) -> None:
        self.checks = checks
        all_ready = all(c.ready for c in checks)

        if all_ready and self.session.status == "idle_blocked":
            self.set_status("idle_ready")
        elif not all_ready and self.session.status == "idle_ready":
            self.set_status("idle_blocked")

        self._emit(
            "readiness",
            {"checks": [c.model_dump(mode="json") for c in checks]},
        )

    # -- export (stub) ------------------------------------------------------

    def export(self) -> dict[str, Any]:
        return {"success": False, "error": "Export not yet implemented"}

    # -- reset --------------------------------------------------------------

    def reset(self) -> None:
        self._cancel_elapsed_ticker()
        self._cancel_grace_task()
        self.session = Session()
        self._emit("session_snapshot", self.get_snapshot())

    # -- snapshot -----------------------------------------------------------

    def get_snapshot(self) -> dict[str, Any]:
        s = self.session
        return {
            "status": s.status,
            "checks": [c.model_dump(mode="json") for c in self.checks],
            "source_partial": s.source_partial,
            "segments": [seg.model_dump(mode="json") for seg in s.segments],
            "exported": s.exported,
            "export_path": s.export_path,
            "recovery_notice": (
                self.recovery_notice.model_dump(mode="json")
                if self.recovery_notice
                else None
            ),
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        }

    # -- elapsed ticker -----------------------------------------------------

    def _start_elapsed_ticker(self) -> None:
        self._cancel_elapsed_ticker()
        self._elapsed_task = asyncio.ensure_future(self._elapsed_loop())

    def _cancel_elapsed_ticker(self) -> None:
        if self._elapsed_task is not None:
            self._elapsed_task.cancel()
            self._elapsed_task = None

    async def _elapsed_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(1)
                if self.session.started_at is None:
                    continue
                elapsed = int(
                    (_utcnow() - self.session.started_at).total_seconds()
                )
                self._emit("elapsed", {"seconds": elapsed})
        except asyncio.CancelledError:
            pass

    # -- grace period -------------------------------------------------------

    def on_client_connect(self) -> None:
        self.session.client_connected = True
        self._cancel_grace_task()
        self.session.disconnect_grace_until = None

    def on_client_disconnect(self) -> None:
        self.session.client_connected = False
        if self.session.status in ("listening", "reconnecting"):
            grace_ms = self.config.client_disconnect_grace_ms
            self.session.disconnect_grace_until = _utcnow() + timedelta(
                milliseconds=grace_ms
            )
            self._cancel_grace_task()
            self._grace_task = asyncio.ensure_future(
                self._grace_countdown(grace_ms / 1000)
            )

    def set_grace_expiry_hook(
        self, callback: Callable[[], Awaitable[None]]
    ) -> None:
        self._on_grace_expiry = callback

    def _cancel_grace_task(self) -> None:
        if self._grace_task is not None:
            self._grace_task.cancel()
            self._grace_task = None

    async def _grace_countdown(self, seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)
            if not self.session.client_connected:
                logger.warning(
                    "Grace period expired — ending session %s", self.session.id
                )
                if self._on_grace_expiry is not None:
                    await self._on_grace_expiry()
                else:
                    self.set_status("session_ended")
        except asyncio.CancelledError:
            pass
