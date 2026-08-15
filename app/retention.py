"""Fail-closed retention planning for transcript-bearing local artifacts."""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

_EXPORT_DIRECTORY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}$")
_EXPECTED_EXPORT_FILES = frozenset({"transcript.json", "transcript.txt"})
Category = Literal["export", "archived_journal"]


@dataclass(frozen=True)
class RetentionCandidate:
    category: Category
    files: tuple[Path, ...]
    size_bytes: int
    directory: Path | None = None


@dataclass
class RetentionReport:
    applied: bool
    retention_days: int
    eligible_export_directories: int = 0
    eligible_archived_journals: int = 0
    eligible_files: int = 0
    eligible_bytes: int = 0
    deleted_files: int = 0
    deleted_bytes: int = 0
    removed_directories: int = 0
    skipped_unsafe: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, bool | int]:
        return asdict(self)


def _safe_root(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError("unsafe_root")
    if expanded.exists() and not expanded.is_dir():
        raise ValueError("unsafe_root")
    resolved = expanded.resolve(strict=False)
    blocked = {
        Path("/"),
        Path.home().resolve(strict=False),
        Path.cwd().resolve(strict=False),
    }
    if resolved in blocked or len(resolved.parts) < 3:
        raise ValueError("unsafe_root")
    return resolved


def _older_than(paths: tuple[Path, ...], cutoff_epoch: float) -> bool:
    try:
        newest_mtime = max(
            path.stat(follow_symlinks=False).st_mtime for path in paths
        )
    except OSError:
        return False
    return newest_mtime < cutoff_epoch


def _scan_export_root(
    root: Path,
    cutoff_epoch: float,
) -> tuple[list[RetentionCandidate], int]:
    candidates: list[RetentionCandidate] = []
    skipped_unsafe = 0
    if not root.exists():
        return candidates, skipped_unsafe
    if not root.is_dir() or root.is_symlink():
        return candidates, 1

    try:
        children = list(root.iterdir())
    except OSError:
        return candidates, 1

    for child in children:
        if not _EXPORT_DIRECTORY_PATTERN.fullmatch(child.name):
            continue
        if child.is_symlink() or not child.is_dir():
            skipped_unsafe += 1
            continue
        try:
            entries = tuple(child.iterdir())
        except OSError:
            skipped_unsafe += 1
            continue
        if (
            {entry.name for entry in entries} != _EXPECTED_EXPORT_FILES
            or any(entry.is_symlink() or not entry.is_file() for entry in entries)
        ):
            skipped_unsafe += 1
            continue
        files = tuple(sorted(entries))
        if not _older_than(files, cutoff_epoch):
            continue
        try:
            size_bytes = sum(
                path.stat(follow_symlinks=False).st_size for path in files
            )
        except OSError:
            skipped_unsafe += 1
            continue
        candidates.append(
            RetentionCandidate(
                category="export",
                files=files,
                size_bytes=size_bytes,
                directory=child,
            )
        )
    return candidates, skipped_unsafe


def _scan_archived_journals(
    journal_root: Path,
    cutoff_epoch: float,
) -> tuple[list[RetentionCandidate], int]:
    candidates: list[RetentionCandidate] = []
    archive_root = journal_root / "_archived"
    if not archive_root.exists():
        return candidates, 0
    if archive_root.is_symlink() or not archive_root.is_dir():
        return candidates, 1

    skipped_unsafe = 0
    try:
        entries = list(archive_root.iterdir())
    except OSError:
        return candidates, 1
    for entry in entries:
        if entry.suffix != ".jsonl":
            continue
        if entry.is_symlink() or not entry.is_file():
            skipped_unsafe += 1
            continue
        files = (entry,)
        if not _older_than(files, cutoff_epoch):
            continue
        try:
            size_bytes = entry.stat(follow_symlinks=False).st_size
        except OSError:
            skipped_unsafe += 1
            continue
        candidates.append(
            RetentionCandidate(
                category="archived_journal",
                files=files,
                size_bytes=size_bytes,
            )
        )
    return candidates, skipped_unsafe


def _delete_candidate(candidate: RetentionCandidate, report: RetentionReport) -> None:
    for path in candidate.files:
        try:
            if path.is_symlink() or not path.is_file():
                report.errors += 1
                return
            size_bytes = path.stat(follow_symlinks=False).st_size
            path.unlink()
        except OSError:
            report.errors += 1
            return
        report.deleted_files += 1
        report.deleted_bytes += size_bytes

    if candidate.directory is not None:
        try:
            candidate.directory.rmdir()
        except OSError:
            report.errors += 1
        else:
            report.removed_directories += 1


def run_retention(
    *,
    export_roots: list[Path],
    journal_root: Path,
    retention_days: int,
    apply: bool = False,
    now_epoch: float | None = None,
) -> RetentionReport:
    """Plan or apply retention without reading transcript contents."""
    if retention_days < 1:
        raise ValueError("invalid_retention_days")
    current_epoch = time.time() if now_epoch is None else now_epoch
    cutoff_epoch = current_epoch - retention_days * 24 * 60 * 60
    report = RetentionReport(applied=apply, retention_days=retention_days)

    unique_export_roots: list[Path] = []
    seen_roots: set[Path] = set()
    for root in export_roots:
        safe = _safe_root(root)
        if safe not in seen_roots:
            seen_roots.add(safe)
            unique_export_roots.append(safe)
    safe_journal_root = _safe_root(journal_root)

    candidates: list[RetentionCandidate] = []
    for root in unique_export_roots:
        found, skipped = _scan_export_root(root, cutoff_epoch)
        candidates.extend(found)
        report.skipped_unsafe += skipped
    archived, skipped = _scan_archived_journals(
        safe_journal_root,
        cutoff_epoch,
    )
    candidates.extend(archived)
    report.skipped_unsafe += skipped

    report.eligible_export_directories = sum(
        candidate.category == "export" for candidate in candidates
    )
    report.eligible_archived_journals = sum(
        candidate.category == "archived_journal" for candidate in candidates
    )
    report.eligible_files = sum(len(candidate.files) for candidate in candidates)
    report.eligible_bytes = sum(candidate.size_bytes for candidate in candidates)

    if apply:
        for candidate in candidates:
            _delete_candidate(candidate, report)
    return report
