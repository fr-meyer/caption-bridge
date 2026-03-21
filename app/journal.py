"""Session journal & recovery loader."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import orjson

from app.config import AppConfig
from app.exporter import export_session
from app.state import RecoveryNotice, Segment, Session

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

    def record_segment_created(self, seg: Segment) -> None:
        self._write({
            "type": "segment_created",
            "seq": seg.seq,
            "source_text": seg.source_text,
            "segment_kind": seg.segment_kind,
            "created_at": seg.created_at.isoformat(),
        })

    def record_translation_updated(self, seg: Segment) -> None:
        self._write({
            "type": "translation_updated",
            "seq": seg.seq,
            "english_text": seg.english_text,
            "translation_status": seg.translation_status,
        })

    def record_session_stopped(self) -> None:
        self._write({"type": "session_stopped"})

    def record_session_exported(self, export_path: str) -> None:
        self._write({"type": "session_exported", "export_path": export_path})

    def record_session_discarded(self) -> None:
        self._write({"type": "session_discarded"})


def run_recovery(config: AppConfig) -> RecoveryNotice | None:
    """Scan journal directory for incomplete sessions, export them, and return a notice."""
    journal_dir = Path(config.journal_dir)
    if not journal_dir.exists():
        return None

    terminal_types = {"session_exported", "session_discarded"}
    notices: list[RecoveryNotice] = []

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

            elif rec_type == "session_stopped":
                session.ended_at = datetime.fromisoformat(rec["ts"])
                session.status = "session_ended"

            elif rec_type == "segment_created":
                seg = Segment(
                    seq=rec["seq"],
                    source_text=rec["source_text"],
                    segment_kind=rec["segment_kind"],
                    created_at=datetime.fromisoformat(rec["created_at"]),
                    translation_status="pending",
                )
                segments_by_seq[seg.seq] = seg

            elif rec_type == "translation_updated":
                seg = segments_by_seq.get(rec["seq"])
                if seg is not None:
                    seg.english_text = rec.get("english_text")
                    seg.translation_status = rec.get("translation_status", "pending")

        session.segments = [segments_by_seq[k] for k in sorted(segments_by_seq)]
        if session.segments:
            session.next_seq = max(s.seq for s in session.segments) + 1
        else:
            session.next_seq = 1

        latest_ts = max(
            (datetime.fromisoformat(r["ts"]) for r in records if "ts" in r),
            default=datetime.fromtimestamp(journal_file.stat().st_mtime, tz=timezone.utc),
        )

        try:
            export_path = export_session(session, config, recovery=True)
        except Exception:
            logger.exception("Recovery export failed for session %s", session_id)
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

        notices.append(RecoveryNotice(
            recovered_session_id=session_id,
            export_path=export_path,
            created_at=latest_ts,
        ))

    if not notices:
        return None

    notices.sort(key=lambda n: n.created_at, reverse=True)
    return notices[0]
