#!/usr/bin/env python3
"""Preview or apply local transcript retention without reading transcript text."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import settings
from app.retention import RetentionReport, run_retention


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview aged transcript exports and archived journals. "
            "Deletion requires --apply."
        )
    )
    parser.add_argument(
        "--days",
        type=int,
        default=settings.transcript_retention_days,
        help="Retain artifacts newer than this many days.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete only artifacts that pass all retention safety checks.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _render_text(report: RetentionReport) -> str:
    mode = "apply" if report.applied else "preview"
    lines = [
        f"Transcript retention {mode} (content-free)",
        f"retention_days: {report.retention_days}",
        f"eligible_export_directories: {report.eligible_export_directories}",
        f"eligible_archived_journals: {report.eligible_archived_journals}",
        f"eligible_files: {report.eligible_files}",
        f"eligible_bytes: {report.eligible_bytes}",
        f"deleted_files: {report.deleted_files}",
        f"deleted_bytes: {report.deleted_bytes}",
        f"removed_directories: {report.removed_directories}",
        f"skipped_unsafe: {report.skipped_unsafe}",
        f"errors: {report.errors}",
    ]
    if not report.applied:
        lines.append("No files changed. Re-run with --apply after reviewing the counts.")
    return "\n".join(lines)


def main() -> int:
    args = _parser().parse_args()
    try:
        report = run_retention(
            export_roots=[
                Path(settings.export_dir),
                Path(settings.recovery_export_dir),
            ],
            journal_root=Path(settings.journal_dir),
            retention_days=args.days,
            apply=args.apply,
        )
    except ValueError:
        if args.as_json:
            print(json.dumps({"error": "retention_refused"}, sort_keys=True))
        else:
            print("Retention refused by a safety check.", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(_render_text(report))
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
