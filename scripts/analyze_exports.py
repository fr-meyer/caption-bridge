"""Analyze transcript export quality summaries without reading segment text."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import warnings
from collections import Counter
from pathlib import Path

try:
    import orjson

    def _loads(raw: bytes) -> dict:
        return orjson.loads(raw)

except ImportError:
    def _loads(raw: bytes) -> dict:
        return json.loads(raw.decode("utf-8"))


def _warn_skip(path: Path, detail: str) -> None:
    message = f"Skipping malformed transcript {path}: {detail}"
    warnings.warn(message, stacklevel=2)
    print(f"WARNING: {message}", file=sys.stderr)


def _validate_transcript_shape(path: Path, data: object) -> bool:
    if not isinstance(data, dict):
        _warn_skip(path, "top-level payload is not a JSON object")
        return False

    quality_summary = data.get("quality_summary")
    if not isinstance(quality_summary, dict):
        _warn_skip(path, "quality_summary is missing or not an object")
        return False

    segments = data.get("segments")
    if not isinstance(segments, list):
        _warn_skip(path, "segments is missing or not a list")
        return False

    if not all(isinstance(segment, dict) for segment in segments):
        _warn_skip(path, "segments contains non-object entries")
        return False

    return True


def load_transcript(path: Path) -> dict | None:
    try:
        data = _loads(path.read_bytes())
    except Exception as exc:
        warnings.warn(f"Failed to load {path}: {exc}", stacklevel=2)
        print(f"WARNING: Failed to load {path}: {exc}", file=sys.stderr)
        return None

    if not _validate_transcript_shape(path, data):
        return None

    return data


_SUMMABLE_KEYS = (
    "total_segments",
    "done",
    "failed",
    "timed_out",
    "quality_checked",
    "retried",
    "quality_flagged",
    "repair_attempts",
    "repair_succeeded",
    "quality_still_flagged",
    "repair_latency_samples",
    "repair_latency_ms_total",
)


def collect_transcripts(roots: list[Path]) -> tuple[list[tuple[Path, dict]], int]:
    """Read each export once, skipping exact repeated snapshots without deleting files."""
    paths: set[Path] = set()
    for root in roots:
        if root.is_file():
            paths.add(root.resolve())
        else:
            paths.update(path.resolve() for path in root.rglob("transcript.json"))

    loaded: list[tuple[Path, dict]] = []
    seen: set[bytes] = set()
    duplicates = 0
    for path in sorted(paths):
        data = load_transcript(path)
        if data is None:
            continue
        digest = hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
        ).digest()
        if digest in seen:
            duplicates += 1
            continue
        seen.add(digest)
        loaded.append((path, data))
    return loaded, duplicates


def print_run_summary(path: Path, data: dict, *, include_segments: bool = True) -> dict | None:
    quality_summary = data["quality_summary"]

    print(f"\n=== Run: {path} ===")
    for key in (*_SUMMABLE_KEYS, "repair_latency_ms_average", "repair_latency_ms_max"):
        print(f"  {key}: {quality_summary.get(key, 0)}")
    for key in ("initial_reason_counts", "final_reason_counts"):
        counts = quality_summary.get(key) or {}
        print(f"  {key}: {json.dumps(counts, sort_keys=True)}")

    if not include_segments:
        return quality_summary

    print(
        f"\n{'seq':>4}  {'status':<12}  {'initial':<7}  {'final':<7}  "
        f"{'initial reasons':<28}  {'final reasons':<28}  attempts"
    )
    print("-" * 110)
    for seg in data.get("segments", []):
        quality = seg.get("quality") or {}
        seq = seg.get("seq", "?")
        status = seg.get("translation_status", "?")
        initial_flagged = quality.get("flagged", False)
        initial_reasons = quality.get("reasons") or []
        repair_succeeded = quality.get("repair_succeeded")
        final_flagged = quality.get(
            "final_flagged",
            initial_flagged and repair_succeeded is not True,
        )
        final_reasons = quality.get("final_reasons")
        if final_reasons is None:
            final_reasons = initial_reasons if final_flagged else []
        attempts = quality.get("repair_attempts", int(quality.get("retried", False)))
        print(
            f"{seq:>4}  {status:<12}  {str(initial_flagged):<7}  "
            f"{str(final_flagged):<7}  {', '.join(initial_reasons):<28}  "
            f"{', '.join(final_reasons):<28}  {attempts}"
        )

    return quality_summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path, default=[Path("runs")])
    parser.add_argument("--summary-only", action="store_true", help="Omit per-caption metadata rows")
    args = parser.parse_args(argv)
    aggregate = dict.fromkeys(_SUMMABLE_KEYS, 0)
    initial_reason_counts: Counter[str] = Counter()
    final_reason_counts: Counter[str] = Counter()
    repair_latency_max: int | None = None

    transcripts, duplicates = collect_transcripts(args.roots)
    if not transcripts:
        print("No valid transcript.json files found in the supplied paths", file=sys.stderr)

    for path, data in transcripts:
        summary = print_run_summary(path, data, include_segments=not args.summary_only)
        if summary is None:
            continue
        for key in _SUMMABLE_KEYS:
            aggregate[key] += summary.get(key, 0)
        initial_reason_counts.update(summary.get("initial_reason_counts") or {})
        final_reason_counts.update(summary.get("final_reason_counts") or {})
        run_max = summary.get("repair_latency_ms_max")
        if run_max is not None:
            repair_latency_max = max(repair_latency_max or 0, run_max)

    latency_samples = aggregate["repair_latency_samples"]
    latency_average = (
        round(aggregate["repair_latency_ms_total"] / latency_samples, 1)
        if latency_samples
        else None
    )

    print("\n=== Aggregate totals ===")
    print(f"  unique_exports: {len(transcripts)}")
    print(f"  duplicate_exports_skipped: {duplicates}")
    for key, value in aggregate.items():
        print(f"  {key}: {value}")
    print(f"  repair_latency_ms_average: {latency_average}")
    print(f"  repair_latency_ms_max: {repair_latency_max}")
    print(
        "  initial_reason_counts: "
        + json.dumps(dict(sorted(initial_reason_counts.items())))
    )
    print(
        "  final_reason_counts: "
        + json.dumps(dict(sorted(final_reason_counts.items())))
    )


if __name__ == "__main__":
    main()
