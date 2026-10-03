"""Session journal & recovery loader."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import orjson

from app.config import AppConfig
from app.exporter import export_session
from app.glossary import Glossary, TerminologyRevision, parse_glossary
from app.state import RecoveryNotice, RecoveryState, Segment, SegmentQuality, Session
from app.terminology import restore_revision

logger = logging.getLogger(__name__)


class SessionJournal:
    """Append-only JSONL journal that records every session lifecycle event."""

    def __init__(self, session_id: str, config: AppConfig) -> None:
        self._session_id = session_id
        self._config = config
        self._path = Path(config.journal_dir) / f"{session_id}.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, record: dict) -> None:
        record["ts"] = datetime.now(timezone.utc).isoformat()
        record["session_id"] = self._session_id
        with self._path.open("ab") as f:
            f.write(orjson.dumps(record) + b"\n")

    def record_session_started(self) -> None:
        self._write({"type": "session_started"})

    def record_glossary(self, glossary: Glossary) -> None:
        self._write({"type": "session_glossary", "glossary": glossary.model_dump(mode="json", exclude_defaults=True)})

    def record_segment_created(self, seg: Segment) -> None:
        self._write({
            "type": "segment_created",
            "seq": seg.seq,
            "source_text": seg.source_text,
            "segment_kind": seg.segment_kind,
            "created_at": seg.created_at.isoformat(),
            "target_language": seg.target_language,
        })

    def record_terminology(self, revision: TerminologyRevision, undo_versions: list[int]) -> None:
        self._write({"type": "terminology_revision",
                     "revision": revision.model_dump(mode="json"), "undo_versions": undo_versions})

    def record_translation_requested(self, seg: Segment) -> None:
        self._write({"type": "translation_requested", "seq": seg.seq,
                     "effective_source_text": seg.effective_source_text,
                     "terminology_version": seg.terminology_version,
                     "terminology_status": seg.terminology_status,
                     "terminology": seg.terminology.model_dump(mode="json") if seg.terminology else None})

    def record_translation_updated(self, seg: Segment) -> None:
        self._write({
            "type": "translation_updated",
            "seq": seg.seq,
            "translated_text": seg.translated_text,
            "target_language": seg.target_language,
            "translation_status": seg.translation_status,
            "quality": seg.quality.model_dump(mode="json") if seg.quality is not None else None,
            "failure_reason": seg.failure_reason,
        })

    def record_session_stopped(self) -> None:
        self._write({"type": "session_stopped"})

    def record_session_exported(self, export_path: str) -> None:
        self._write({"type": "session_exported", "export_path": export_path})

    def record_session_discarded(self) -> None:
        self._write({"type": "session_discarded"})


@dataclass
class RecoveryResult:
    notice: RecoveryNotice | None
    recovery_state: RecoveryState | None


def run_recovery(config: AppConfig) -> RecoveryResult:
    """Scan journal directory for incomplete sessions, export them, and return a result."""
    journal_dir = Path(config.journal_dir)
    if not journal_dir.exists():
        return RecoveryResult(notice=None, recovery_state=None)

    terminal_types = {"session_exported", "session_discarded"}
    candidates: list[tuple[RecoveryNotice, RecoveryState | None]] = []

    for journal_file in journal_dir.glob("*.jsonl"):
        try:
            records = [
                orjson.loads(line)
                for line in journal_file.read_bytes().splitlines()
                if line.strip()
            ]
        except Exception:
            logger.warning("Failed to parse journal %s — skipping", journal_file)
            continue

        if not records:
            continue

        if any(r.get("type") in terminal_types for r in records):
            continue

        session_id = records[0].get("session_id", journal_file.stem)
        session = Session(id=session_id)
        segments_by_seq: dict[int, Segment] = {}

        for rec in records:
            rec_type = rec.get("type")

            if rec_type == "session_started":
                session.started_at = datetime.fromisoformat(rec["ts"])

            elif rec_type == "session_glossary":
                value = rec.get("glossary")
                try:
                    if not isinstance(value, dict) or set(value) != {"entries", "target_language"}:
                        raise ValueError("Invalid glossary record.")
                    session.glossary = parse_glossary(
                        value["entries"], value["target_language"], historical=True
                    )
                except (ValueError, TypeError):
                    logger.warning("Invalid recovery glossary metadata — ignored")

            elif rec_type == "terminology_revision":
                try:
                    restore_revision(session, rec.get("revision"), rec.get("undo_versions"))
                except (ValueError, TypeError):
                    logger.warning("Invalid recovery terminology metadata — ignored")

            elif rec_type == "translation_requested":
                seg = segments_by_seq.get(rec.get("seq"))
                if seg is not None:
                    try:
                        metadata = Segment.model_validate({
                            **seg.model_dump(),
                            "effective_source_text": rec.get("effective_source_text"),
                            "terminology_version": rec.get("terminology_version", 0),
                            "terminology_status": rec.get("terminology_status", "empty"),
                            "terminology": rec.get("terminology"),
                        })
                        seg.effective_source_text = metadata.effective_source_text
                        seg.terminology_version = metadata.terminology_version
                        seg.terminology_status = metadata.terminology_status
                        seg.terminology = metadata.terminology
                    except (ValueError, TypeError):
                        logger.warning("Invalid recovery translation terminology — ignored")

            elif rec_type == "session_stopped":
                session.ended_at = datetime.fromisoformat(rec["ts"])
                session.status = "session_ended"

            elif rec_type == "segment_created":
                seg = Segment(
                    seq=rec["seq"],
                    source_text=rec["source_text"],
                    segment_kind=rec["segment_kind"],
                    created_at=datetime.fromisoformat(rec["created_at"]),
                    target_language=rec.get("target_language"),
                    translation_status="pending",
                )
                segments_by_seq[seg.seq] = seg

            elif rec_type == "translation_updated":
                seg = segments_by_seq.get(rec["seq"])
                if seg is not None:
                    seg.translated_text = rec.get("translated_text")
                    seg.target_language = rec.get("target_language")
                    seg.translation_status = rec.get("translation_status", "pending")
                    quality_data = rec.get("quality")
                    if quality_data is not None and isinstance(quality_data, dict):
                        try:
                            seg.quality = SegmentQuality.model_validate(quality_data)
                        except Exception:
                            seg.quality = None
                    else:
                        seg.quality = None
                    seg.failure_reason = rec.get("failure_reason")

        session.segments = [segments_by_seq[k] for k in sorted(segments_by_seq)]
        if session.segments:
            session.next_seq = max(s.seq for s in session.segments) + 1
        else:
            session.next_seq = 1

        for seg in session.segments:
            if seg.translation_status == "pending":
                seg.translation_status = "failed"
                seg.failure_reason = "recovered_pending"

        latest_ts = max(
            (datetime.fromisoformat(r["ts"]) for r in records if "ts" in r),
            default=datetime.fromtimestamp(journal_file.stat().st_mtime, tz=timezone.utc),
        )

        try:
            export_path = export_session(session, config, recovery=True)
        except Exception as exc:
            logger.exception("Recovery export failed for session %s", session_id)
            notice = RecoveryNotice(
                recovered_session_id=session_id,
                status="failed",
                error=str(exc),
                created_at=latest_ts,
            )
            state = RecoveryState(
                recovered_session_id=session_id,
                session_payload=session,
                journal_path=str(journal_file),
                last_error=str(exc),
                created_at=latest_ts,
            )
            candidates.append((notice, state))
            continue

        journal = SessionJournal(session_id=session_id, config=config)
        journal.record_session_exported(export_path)

        archive_dir = journal_dir / "_archived"
        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            journal_file.rename(archive_dir / journal_file.name)
        except Exception:
            logger.warning(
                "Failed to archive journal %s — session_exported record "
                "prevents re-recovery",
                journal_file,
            )

        notice = RecoveryNotice(
            recovered_session_id=session_id,
            status="success",
            export_path=export_path,
            created_at=latest_ts,
        )
        candidates.append((notice, None))

    if not candidates:
        return RecoveryResult(notice=None, recovery_state=None)

    candidates.sort(key=lambda c: c[0].created_at, reverse=True)
    best_notice, best_state = candidates[0]
    return RecoveryResult(notice=best_notice, recovery_state=best_state)


def retry_recovery(
    recovery_state: RecoveryState, config: AppConfig
) -> tuple[str, None] | tuple[None, str]:
    """Re-attempt export of a failed recovery session.

    Returns ``(export_path, None)`` on success or ``(None, error)`` on failure.
    """
    try:
        export_path = export_session(
            recovery_state.session_payload, config, recovery=True
        )
    except Exception as exc:
        return None, str(exc)

    journal = SessionJournal(
        session_id=recovery_state.recovered_session_id, config=config
    )
    journal.record_session_exported(export_path)

    journal_file = Path(recovery_state.journal_path)
    journal_dir = journal_file.parent
    archive_dir = journal_dir / "_archived"
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        journal_file.rename(archive_dir / journal_file.name)
    except Exception:
        logger.warning(
            "Failed to archive journal %s after retry",
            journal_file,
        )

    return export_path, None


def discard_recovery(recovery_state: RecoveryState, config: AppConfig) -> None:
    """Discard a failed recovery session by recording it and archiving the journal."""
    journal = SessionJournal(
        session_id=recovery_state.recovered_session_id, config=config
    )
    journal.record_session_discarded()

    journal_file = Path(recovery_state.journal_path)
    journal_dir = journal_file.parent
    archive_dir = journal_dir / "_archived"
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        journal_file.rename(archive_dir / journal_file.name)
    except Exception:
        logger.warning(
            "Failed to archive journal %s after discard",
            journal_file,
        )
