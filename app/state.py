"""Session state management."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import AppConfig
from app.glossary import Glossary
from app.languages import is_valid_target_language
from app.profiles import CaptionProfile, available_profiles, resolve_profile
from app.reliability import ReliabilityTracker, write_session_record

if TYPE_CHECKING:
    from app.journal import SessionJournal
    from app.translate import TranslationDispatcher
    from app.tts import TTSDispatcher

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


class SegmentQuality(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    flagged: bool
    reasons: list[str]
    retried: bool
    repair_succeeded: bool | None
    final_flagged: bool = False
    final_reasons: list[str] = Field(default_factory=list)
    repair_attempts: int = 0
    repair_latency_ms: int | None = None

    @model_validator(mode="before")
    @classmethod
    def backfill_final_state(cls, data: Any) -> Any:
        """Infer new fields when loading quality metadata from older journals."""
        if not isinstance(data, dict):
            return data
        values = dict(data)
        if "final_flagged" not in values:
            values["final_flagged"] = bool(
                values.get("flagged")
                and values.get("repair_succeeded") is not True
            )
        if "final_reasons" not in values:
            values["final_reasons"] = (
                list(values.get("reasons") or []) if values["final_flagged"] else []
            )
        if "repair_attempts" not in values:
            values["repair_attempts"] = int(bool(values.get("retried")))
        return values


class Segment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=_uuid)
    seq: int
    created_at: datetime = Field(default_factory=_utcnow)
    source_text: str
    segment_kind: SegmentKind
    translated_text: str | None = None
    target_language: str | None = None
    translation_status: TranslationStatus = "pending"
    translated_at: datetime | None = None
    quality: SegmentQuality | None = None
    failure_reason: str | None = None


class ReadinessCheck(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    key: str
    ready: bool
    detail: str


class ExportFailure(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    error: str
    created_at: datetime = Field(default_factory=_utcnow)


class RecoveryNotice(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recovered_session_id: str
    status: Literal["success", "failed"]
    export_path: str | None = None
    error: str | None = None
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
    export_failure: ExportFailure | None = None
    journal_path: str | None = None
    source_language: str = "auto"
    target_language: str = "en"
    glossary: Glossary | None = None
    caption_profile: CaptionProfile | None = None
    client_connected: bool = False
    disconnect_grace_until: datetime | None = None


class RecoveryState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recovered_session_id: str
    session_payload: Session
    journal_path: str
    last_error: str
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Valid status transitions
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[Status, set[Status]] = {
    "idle_blocked": {"idle_ready"},
    "idle_ready": {"idle_blocked", "listening"},
    "listening": {"reconnecting", "session_ended"},
    "reconnecting": {"listening", "session_ended"},
    "session_ended": {"idle_blocked", "idle_ready"},
}


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------

EventListener = Callable[[dict[str, Any]], Any]


class SessionManager:
    """Central authority for session state, events, and lifecycle."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.session = self._new_session()
        self.checks: list[ReadinessCheck] = []
        self.recovery_notice: RecoveryNotice | None = None
        self.recovery_state: RecoveryState | None = None
        self._listeners: list[EventListener] = []
        self._elapsed_task: asyncio.Task[None] | None = None
        self._grace_task: asyncio.Task[None] | None = None
        self._on_grace_expiry: Callable[[], Awaitable[None]] | None = None
        self._dispatcher: TranslationDispatcher | None = None
        self._tts_dispatcher: TTSDispatcher | None = None
        self._journal: SessionJournal | None = None
        self._reliability = ReliabilityTracker()

    def set_dispatcher(self, dispatcher: TranslationDispatcher) -> None:
        self._dispatcher = dispatcher

    def set_tts_dispatcher(self, dispatcher: TTSDispatcher) -> None:
        self._tts_dispatcher = dispatcher

    def set_journal(self, journal: SessionJournal) -> None:
        self._journal = journal

    def _new_session(self) -> Session:
        target = self.config.default_target_language
        if not is_valid_target_language(target):
            logger.warning(
                "Configured default_target_language %r is not a supported "
                "language code; falling back to 'en'",
                target,
            )
            target = "en"
        return Session(
            source_language=self.config.default_source_language,
            target_language=target,
            caption_profile=resolve_profile("current", self.config),
        )

    # -- event system -------------------------------------------------------

    def _emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"type": event_type}
        if data:
            payload.update(data)
        self._reliability.observe_event(payload)
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

    def record_audio_queue(self, depth: int, dropped: int) -> None:
        self._reliability.record_audio_queue(depth, dropped)

    def record_websocket_queue(
        self,
        depth: int,
        *,
        dropped: int = 0,
        coalesced: int = 0,
        critical_drops: int = 0,
    ) -> None:
        self._reliability.record_websocket_queue(
            depth,
            dropped=dropped,
            coalesced=coalesced,
            critical_drops=critical_drops,
        )

    def record_tts_queue(self, depth: int) -> None:
        self._reliability.record_tts_queue(depth)

    def observe_speech_pcm(self, chunk: bytes) -> None:
        self._reliability.latency.observe_pcm16(chunk)

    def observe_render_ack(self, seq: int) -> None:
        self._reliability.latency.observe_render_ack(seq)

    def observe_tts_playback_start(self, seq: int) -> None:
        self._reliability.latency.observe_tts_playback_start(seq)

    def observe_tts_playback_complete(self, seq: int) -> None:
        self._reliability.latency.observe_tts_playback_complete(seq)

    def observe_tts_queue_wait(self, seq: int, duration_s: float) -> None:
        self._reliability.latency.observe_tts_queue_wait(seq, duration_s)

    def observe_tts_synth_start(self, seq: int) -> None:
        self._reliability.latency.observe_tts_synth_start(seq)

    def observe_tts_first_audio(self, seq: int) -> None:
        self._reliability.latency.observe_tts_first_audio(seq)

    def note_browser_replacement(self) -> None:
        self._reliability.latency.mark_browser_replacement()

    def _write_reliability_record(self) -> None:
        try:
            record = self._reliability.build_session_record(self.session)
            write_session_record(Path(self.config.reliability_dir), record)
        except Exception as exc:
            logger.error(
                "Reliability record write failed: error_type=%s", type(exc).__name__
            )

    # -- partial / segment --------------------------------------------------

    def update_partial(self, text: str) -> None:
        if text:
            self._reliability.latency.observe_first_partial()
        self.session.source_partial = text
        self._emit("source_partial", {"text": text})

    def finalize_segment(self, text: str) -> None:
        seg = Segment(
            seq=self.session.next_seq,
            source_text=text,
            segment_kind="complete",
            target_language=self.session.target_language,
        )
        self.session.next_seq += 1
        self.session.segments.append(seg)
        if self._journal is not None:
            self._journal.record_segment_created(seg)
        self.session.source_partial = ""
        logger.info("Finalized segment: seq=%d chars=%d", seg.seq, len(text))
        self._reliability.latency.observe_final_source(seg.seq)
        self._emit("source_partial", {"text": ""})
        self._dispatch_translation(seg)
        self._try_deliver()

    def finalize_reconnect_fragment(self, text: str) -> None:
        seg = Segment(
            seq=self.session.next_seq,
            source_text=text,
            segment_kind="reconnect_fragment",
            target_language=self.session.target_language,
        )
        self.session.next_seq += 1
        self.session.segments.append(seg)
        if self._journal is not None:
            self._journal.record_segment_created(seg)
        self.session.source_partial = ""
        logger.info(
            "Finalized reconnect fragment: seq=%d chars=%d", seg.seq, len(text)
        )
        self._reliability.latency.observe_final_source(seg.seq, reconnect=True)
        self._emit("source_partial", {"text": ""})
        self._dispatch_translation(seg)
        self._try_deliver()

    def _dispatch_translation(self, seg: Segment) -> None:
        if self._dispatcher is None:
            return
        n = self.config.translation_context_segments
        context = self.session.segments[-(n + 1):-1]
        self._reliability.latency.observe_translation_dispatch(seg.seq)
        self._dispatcher.dispatch(seg, context, self.session.id, seg.target_language)

    # -- translation marks (dormant in this ticket) -------------------------

    def _find_segment(self, seq: int) -> Segment | None:
        for seg in self.session.segments:
            if seg.seq == seq:
                return seg
        return None

    def mark_translated(
        self,
        seq: int,
        translated_text: str,
        target_language: str,
        session_id: str,
        quality: SegmentQuality | None = None,
    ) -> None:
        if session_id != self.session.id:
            logger.warning(
                "mark_translated: ignoring stale callback for seq #%d "
                "(session %s, current %s)",
                seq, session_id, self.session.id,
            )
            return
        seg = self._find_segment(seq)
        if seg is None:
            logger.warning("mark_translated: segment #%d not found", seq)
            return
        seg.translated_text = translated_text
        seg.target_language = target_language
        seg.translation_status = "done"
        seg.translated_at = _utcnow()
        seg.quality = quality
        repaired = bool(
            quality is not None
            and (quality.repair_attempts or quality.repair_succeeded)
        )
        self._reliability.latency.observe_translation_complete(
            seq, repaired=repaired
        )
        if self._journal is not None:
            self._journal.record_translation_updated(seg)
        self._try_deliver()

    def mark_translation_timed_out(self, seq: int, session_id: str) -> None:
        if session_id != self.session.id:
            logger.warning(
                "mark_translation_timed_out: ignoring stale callback for seq #%d "
                "(session %s, current %s)",
                seq, session_id, self.session.id,
            )
            return
        seg = self._find_segment(seq)
        if seg is None:
            logger.warning("mark_translation_timed_out: segment #%d not found", seq)
            return
        seg.translation_status = "timed_out"
        seg.translated_at = _utcnow()
        if self._journal is not None:
            self._journal.record_translation_updated(seg)
        self._try_deliver()

    def mark_translation_failed(self, seq: int, session_id: str) -> None:
        if session_id != self.session.id:
            logger.warning(
                "mark_translation_failed: ignoring stale callback for seq #%d "
                "(session %s, current %s)",
                seq, session_id, self.session.id,
            )
            return
        seg = self._find_segment(seq)
        if seg is None:
            logger.warning("mark_translation_failed: segment #%d not found", seq)
            return
        seg.translation_status = "failed"
        seg.translated_at = _utcnow()
        if self._journal is not None:
            self._journal.record_translation_updated(seg)
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
                    "translated_text": seg.translated_text,
                    "target_language": seg.target_language,
                    "created_at": seg.created_at.isoformat(),
                    "translation_status": seg.translation_status,
                    "segment_kind": seg.segment_kind,
                },
            )
            self._reliability.latency.observe_render_dispatch(seg.seq)
            if (
                self._tts_dispatcher is not None
                and self.config.tts_enabled
                and seg.translation_status == "done"
            ):
                self._reliability.latency.observe_tts_request(seg.seq)
                self._tts_dispatcher.enqueue_live(seg)

    # -- status transitions -------------------------------------------------

    def set_status(self, status: Status) -> None:
        current = self.session.status
        if status not in _VALID_TRANSITIONS.get(current, set()):
            logger.warning(
                "Invalid status transition %s → %s; ignoring", current, status
            )
            return

        self.session.status = status
        if status == "reconnecting":
            self._reliability.latency.mark_reconnect_period(True)
        elif status == "listening":
            self._reliability.latency.mark_reconnect_period(False)

        if status == "listening" and self.session.started_at is None:
            self.session.started_at = _utcnow()
            if self._journal is not None:
                self._journal.record_session_started()
                if self.session.caption_profile is not None:
                    self._journal.record_caption_profile(self.session.caption_profile)
                if self.session.glossary is not None:
                    self._journal.record_glossary(self.session.glossary)

        if status == "listening":
            self._start_elapsed_ticker()

        if status == "session_ended":
            self.session.ended_at = _utcnow()
            self._cancel_elapsed_ticker()
            self._cancel_grace_task()
            if self._journal is not None:
                self._journal.record_session_stopped()

        status_data: dict[str, Any] = {"status": status}
        if status == "listening" and self.session.started_at is not None:
            status_data["started_at"] = self.session.started_at.isoformat()
        self._emit("status", status_data)

    # -- readiness ----------------------------------------------------------

    def set_readiness(self, checks: list[ReadinessCheck]) -> None:
        self.checks = checks
        all_ready = all(c.ready for c in checks)

        if self.recovery_state is not None:
            if self.session.status == "idle_ready":
                self.set_status("idle_blocked")
        elif all_ready and self.session.status == "idle_blocked":
            self.set_status("idle_ready")
        elif not all_ready and self.session.status == "idle_ready":
            self.set_status("idle_blocked")

        self._emit(
            "readiness",
            {"checks": [c.model_dump(mode="json") for c in checks]},
        )

    # -- export -------------------------------------------------------------

    def export(self) -> dict[str, Any]:
        from app.exporter import export_session

        try:
            path = export_session(self.session, self.config, recovery=False)
        except Exception as exc:
            self._reliability.set_export_outcome("failed")
            self.session.export_failure = ExportFailure(error=str(exc))
            self._write_reliability_record()
            return {"success": False, "path": None, "error": str(exc)}
        self.session.exported = True
        self.session.export_path = path
        self.session.export_failure = None
        self._reliability.set_export_outcome("succeeded")
        if self._journal is not None:
            self._journal.record_session_exported(path)
        self._write_reliability_record()
        return {"success": True, "path": path, "error": None}

    # -- reset --------------------------------------------------------------

    async def reset(self, *, emit_snapshot: bool = True) -> None:
        should_record_discard = not self.session.exported
        if should_record_discard and self._journal is not None:
            self._journal.record_session_discarded()
        self._cancel_elapsed_ticker()
        self._cancel_grace_task()
        if self._tts_dispatcher is not None:
            await self._tts_dispatcher.drain()
        if should_record_discard:
            self._reliability.set_export_outcome("discarded")
            self._write_reliability_record()
        self.session = self._new_session()
        self._journal = None
        self._reliability = ReliabilityTracker()
        if emit_snapshot:
            self._emit("session_snapshot", self.get_snapshot())

    # -- snapshot -----------------------------------------------------------

    def get_snapshot(self) -> dict[str, Any]:
        from app.exporter import _compute_quality_summary
        from app.languages import get_available_target_languages
        from app.reconnect import get_reconnect_metrics
        from app.ws import get_ws_metrics

        s = self.session
        return {
            "status": s.status,
            "checks": [c.model_dump(mode="json") for c in self.checks],
            "source_partial": s.source_partial,
            "segments": [seg.model_dump(mode="json") for seg in s.segments],
            "exported": s.exported,
            "export_path": s.export_path,
            "export_failure": (
                s.export_failure.model_dump(mode="json")
                if s.export_failure
                else None
            ),
            "recovery_notice": (
                self.recovery_notice.model_dump(mode="json")
                if self.recovery_notice
                else None
            ),
            "source_language": s.source_language,
            "target_language": s.target_language,
            "glossary": s.glossary.model_dump(mode="json") if s.glossary else None,
            "caption_profile": s.caption_profile.model_dump(mode="json") if s.caption_profile else None,
            "available_caption_profiles": available_profiles(self.config),
            "available_target_languages": get_available_target_languages(),
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "runtime_metrics": {
                "reconnect": get_reconnect_metrics(),
                "outbound_websocket": get_ws_metrics(),
                "translation_quality": _compute_quality_summary(s),
                "session_reliability": self._reliability.snapshot(),
            },
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        }

    # -- language -------------------------------------------------------------

    def set_target_language(self, language: str) -> None:
        self.session.target_language = language
        logger.info("Target language set to %s", language)

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
