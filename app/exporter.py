"""Transcript exporter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import orjson

from app.config import AppConfig
from app.state import Segment, Session


def export_session(session: Session, config: AppConfig, recovery: bool = False) -> str:
    """Export a session to transcript.txt and transcript.json files.

    Returns the export directory path as a string.
    """
    timestamp_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = config.recovery_export_dir if recovery else config.export_dir
    export_dir = Path(base) / timestamp_str
    export_dir.mkdir(parents=True, exist_ok=True)

    _write_transcript_txt(export_dir, session)
    _write_transcript_json(export_dir, session, config)

    return str(export_dir)


def _format_relative_timestamp(session: Session, seg: Segment) -> str:
    if session.started_at is not None:
        delta = seg.created_at - session.started_at
        total_seconds = int(delta.total_seconds())
        hours, remainder = divmod(max(total_seconds, 0), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return seg.created_at.isoformat()


def _write_transcript_txt(export_dir: Path, session: Session) -> None:
    lines: list[str] = []
    for seg in session.segments:
        ts = _format_relative_timestamp(session, seg)
        prefix = f"[{ts}] "
        indent = " " * len(prefix)

        korean_line = (
            f"[incomplete fragment] {seg.source_text}"
            if seg.segment_kind == "reconnect_fragment"
            else seg.source_text
        )

        english_line = (
            seg.english_text
            if seg.english_text is not None and seg.translation_status == "done"
            else "[translation unavailable]"
        )

        lines.append(f"{prefix}{korean_line}\n{indent}{english_line}\n")

    (export_dir / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")


def _write_transcript_json(export_dir: Path, session: Session, config: AppConfig) -> None:
    data = {
        "session_id": session.id,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "config": {
            "transcribe_model": config.transcribe_model,
            "translate_model": config.translate_model,
        },
        "segments": [
            {
                "seq": seg.seq,
                "created_at": seg.created_at.isoformat(),
                "source_text": seg.source_text,
                "segment_kind": seg.segment_kind,
                "english_text": seg.english_text,
                "translation_status": seg.translation_status,
            }
            for seg in session.segments
        ],
    }
    (export_dir / "transcript.json").write_bytes(
        orjson.dumps(data, option=orjson.OPT_INDENT_2)
    )
