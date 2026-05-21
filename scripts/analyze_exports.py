"""Analyze transcript export quality summaries without reading segment text."""

from __future__ import annotations

import json
import sys
import warnings
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


def print_run_summary(path: Path, data: dict) -> dict | None:
    quality_summary = data["quality_summary"]

    print(f"\n=== Run: {path} ===")
    for key in (
        "total_segments",
        "done",
        "failed",
        "timed_out",
        "retried",
        "quality_flagged",
    ):
        print(f"  {key}: {quality_summary.get(key, 0)}")

    print(f"\n{'seq':>4}  {'status':<12}  {'flagged':<8}  {'reasons':<30}  retried")
    print("-" * 70)
    for seg in data.get("segments", []):
        quality = seg.get("quality") or {}
        seq = seg.get("seq", "?")
        status = seg.get("translation_status", "?")
        flagged = quality.get("flagged", False)
        reasons = ", ".join(quality.get("reasons") or [])
        retried = quality.get("retried", False)
        print(f"{seq:>4}  {status:<12}  {str(flagged):<8}  {reasons:<30}  {retried}")

    return quality_summary


def main() -> None:
    aggregate = {
        "total_segments": 0,
        "done": 0,
        "failed": 0,
        "timed_out": 0,
        "retried": 0,
        "quality_flagged": 0,
    }

    paths = sorted(Path("runs").glob("**/transcript.json"))
    if not paths:
        print("No transcript.json files found under runs/", file=sys.stderr)

    for path in paths:
        data = load_transcript(path)
        if data is None:
            continue
        summary = print_run_summary(path, data)
        if summary is None:
            continue
        for key in aggregate:
            aggregate[key] += summary.get(key, 0)

    print("\n=== Aggregate totals ===")
    for key, value in aggregate.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
