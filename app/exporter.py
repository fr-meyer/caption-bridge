"""Transcript exporter."""

from __future__ import annotations

from collections import Counter
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

    if recovery:
        for seg in session.segments:
            if seg.translation_status == "pending":
                seg.translation_status = "failed"
                seg.failure_reason = "recovered_pending"

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
    if session.glossary is not None:
        lines.append(f"Terminology preferences ({session.glossary.target_language}):")
        lines.extend(
            f"  {entry.source} => {entry.preferred}"
            for entry in session.glossary.entries
        )
        lines.append("")
    for seg in session.segments:
        ts = _format_relative_timestamp(session, seg)
        prefix = f"[{ts}] "
        indent = " " * len(prefix)

        korean_line = (
            f"[incomplete fragment] {seg.source_text}"
            if seg.segment_kind == "reconnect_fragment"
            else seg.source_text
        )

        translated_line = (
            seg.translated_text
            if seg.translated_text is not None and seg.translation_status == "done"
            else "[translation unavailable]"
        )

        lines.append(f"{prefix}{korean_line}\n{indent}{translated_line}\n")

    (export_dir / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")


def _compute_quality_summary(session: Session) -> dict:
    qualities = [seg.quality for seg in session.segments if seg.quality is not None]
    initial_reason_counts = Counter(
        reason for quality in qualities for reason in quality.reasons
    )
    final_reason_counts = Counter(
        reason for quality in qualities for reason in quality.final_reasons
    )
    repair_latencies = [
        quality.repair_latency_ms
        for quality in qualities
        if quality.repair_latency_ms is not None
    ]
    repair_attempts = sum(quality.repair_attempts for quality in qualities)
    repair_latency_total = sum(repair_latencies)

    return {
        "total_segments": len(session.segments),
        "done": sum(1 for seg in session.segments if seg.translation_status == "done"),
        "failed": sum(1 for seg in session.segments if seg.translation_status == "failed"),
        "timed_out": sum(
            1 for seg in session.segments if seg.translation_status == "timed_out"
        ),
        "quality_checked": len(qualities),
        "retried": sum(1 for quality in qualities if quality.retried),
        "quality_flagged": sum(1 for quality in qualities if quality.flagged),
        "repair_attempts": repair_attempts,
        "repair_succeeded": sum(
            1 for quality in qualities if quality.repair_succeeded is True
        ),
        "quality_still_flagged": sum(
            1 for quality in qualities if quality.final_flagged
        ),
        "initial_reason_counts": dict(sorted(initial_reason_counts.items())),
        "final_reason_counts": dict(sorted(final_reason_counts.items())),
        "repair_latency_samples": len(repair_latencies),
        "repair_latency_ms_total": repair_latency_total,
        "repair_latency_ms_average": (
            round(repair_latency_total / len(repair_latencies), 1)
            if repair_latencies
            else None
        ),
        "repair_latency_ms_max": max(repair_latencies, default=None),
    }


def _write_transcript_json(export_dir: Path, session: Session, config: AppConfig) -> None:
    data = {
        "session_id": session.id,
        "source_language": session.source_language,
        "target_language": session.target_language,
        "glossary": session.glossary.model_dump(mode="json") if session.glossary else None,
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
                "translated_text": seg.translated_text,
                "target_language": seg.target_language,
                "translation_status": seg.translation_status,
                "quality": seg.quality.model_dump(mode="json") if seg.quality is not None else None,
                "failure_reason": seg.failure_reason,
            }
            for seg in session.segments
        ],
        "quality_summary": _compute_quality_summary(session),
    }
    (export_dir / "transcript.json").write_bytes(
        orjson.dumps(data, option=orjson.OPT_INDENT_2)
    )
