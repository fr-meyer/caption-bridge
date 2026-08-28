"""Tests for fail-closed transcript and journal retention."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.retention import run_retention
from scripts.prune_transcripts import _render_text

_NOW = 1_800_000_000.0
_DAY = 24 * 60 * 60
_PRIVATE_FIXTURE_TEXT = "PRIVATE_SYNTHETIC_TRANSCRIPT_DO_NOT_PRINT"


def _aged_file(path: Path, *, age_days: int = 31) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_PRIVATE_FIXTURE_TEXT, encoding="utf-8")
    timestamp = _NOW - age_days * _DAY
    os.utime(path, (timestamp, timestamp))


def _aged_export(root: Path, name: str = "2026-01-02_030405") -> Path:
    export_dir = root / name
    _aged_file(export_dir / "transcript.json")
    _aged_file(export_dir / "transcript.txt")
    return export_dir


def test_preview_then_apply_is_content_free_and_idempotent(tmp_path: Path) -> None:
    export_root = tmp_path / "runs"
    journal_root = export_root / ".journal"
    export_dir = _aged_export(export_root)
    archived_journal = journal_root / "_archived" / "finished.jsonl"
    active_journal = journal_root / "active.jsonl"
    _aged_file(archived_journal)
    _aged_file(active_journal)

    preview = run_retention(
        export_roots=[export_root, export_root],
        journal_root=journal_root,
        retention_days=30,
        now_epoch=_NOW,
    )

    assert preview.applied is False
    assert preview.eligible_export_directories == 1
    assert preview.eligible_archived_journals == 1
    assert preview.eligible_files == 3
    assert preview.deleted_files == 0
    assert export_dir.exists()
    assert archived_journal.exists()
    assert active_journal.exists()
    assert _PRIVATE_FIXTURE_TEXT not in _render_text(preview)
    assert str(export_dir) not in _render_text(preview)

    applied = run_retention(
        export_roots=[export_root],
        journal_root=journal_root,
        retention_days=30,
        apply=True,
        now_epoch=_NOW,
    )

    assert applied.deleted_files == 3
    assert applied.removed_directories == 1
    assert not export_dir.exists()
    assert not archived_journal.exists()
    assert active_journal.exists()

    repeated = run_retention(
        export_roots=[export_root],
        journal_root=journal_root,
        retention_days=30,
        apply=True,
        now_epoch=_NOW,
    )

    assert repeated.eligible_files == 0
    assert repeated.deleted_files == 0
    assert active_journal.exists()


def test_recent_artifacts_are_preserved(tmp_path: Path) -> None:
    export_root = tmp_path / "runs"
    journal_root = export_root / ".journal"
    export_dir = export_root / "2026-01-02_030405"
    for name in ("transcript.json", "transcript.txt"):
        _aged_file(export_dir / name, age_days=29)
    archived_journal = journal_root / "_archived" / "recent.jsonl"
    _aged_file(archived_journal, age_days=29)

    report = run_retention(
        export_roots=[export_root],
        journal_root=journal_root,
        retention_days=30,
        apply=True,
        now_epoch=_NOW,
    )

    assert report.eligible_files == 0
    assert report.deleted_files == 0
    assert export_dir.exists()
    assert archived_journal.exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs an optional Windows capability")
def test_partial_unknown_and_symlinked_exports_fail_closed(tmp_path: Path) -> None:
    export_root = tmp_path / "runs"
    journal_root = export_root / ".journal"

    partial = export_root / "2026-01-02_030405"
    _aged_file(partial / "transcript.json")

    unexpected = _aged_export(export_root, "2026-01-03_030405")
    _aged_file(unexpected / "notes.txt")

    external = tmp_path / "external"
    _aged_export(external, "target")
    symlink = export_root / "2026-01-04_030405"
    export_root.mkdir(parents=True, exist_ok=True)
    symlink.symlink_to(external / "target", target_is_directory=True)

    report = run_retention(
        export_roots=[export_root],
        journal_root=journal_root,
        retention_days=30,
        apply=True,
        now_epoch=_NOW,
    )

    assert report.eligible_files == 0
    assert report.deleted_files == 0
    assert report.skipped_unsafe == 3
    assert (partial / "transcript.json").exists()
    assert (unexpected / "transcript.json").exists()
    assert symlink.is_symlink()


@pytest.mark.parametrize("retention_days", [0, -1])
def test_invalid_retention_days_are_rejected(
    tmp_path: Path,
    retention_days: int,
) -> None:
    with pytest.raises(ValueError, match="invalid_retention_days"):
        run_retention(
            export_roots=[tmp_path / "runs"],
            journal_root=tmp_path / "runs" / ".journal",
            retention_days=retention_days,
            now_epoch=_NOW,
        )


def test_broad_or_current_roots_are_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="unsafe_root"):
        run_retention(
            export_roots=[Path("/")],
            journal_root=tmp_path / ".journal",
            retention_days=30,
            now_epoch=_NOW,
        )

    with pytest.raises(ValueError, match="unsafe_root"):
        run_retention(
            export_roots=[tmp_path],
            journal_root=tmp_path / ".journal",
            retention_days=30,
            now_epoch=_NOW,
        )

    file_root = tmp_path / "journal-file"
    file_root.write_text("not a directory", encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe_root"):
        run_retention(
            export_roots=[tmp_path / "safe-runs"],
            journal_root=file_root,
            retention_days=30,
            now_epoch=_NOW,
        )
