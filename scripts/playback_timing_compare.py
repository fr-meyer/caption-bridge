"""Compare exported software scheduler observations, not audible latency.

Input JSON: {fixture_id, baseline: [...], candidate: [...]}; each ordered row
contains clip_id, ready_ms, start_ms, end_ms. No audio/text/device data allowed.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path


def metrics(rows):
    waits, gaps, overlaps = [], [], []
    frontier = previous_start = None
    for row in rows:
        if set(row) != {"clip_id", "ready_ms", "start_ms", "end_ms"}:
            raise ValueError("unexpected observation fields")
        ready, start, end = (float(row[k]) for k in ("ready_ms", "start_ms", "end_ms"))
        if not all(math.isfinite(v) and v >= 0 for v in (ready, start, end)):
            raise ValueError("invalid timestamp")
        if not ready <= start <= end:
            raise ValueError("invalid event order")
        waits.append(start - ready)
        if previous_start is not None and start < previous_start:
            raise ValueError("observations must be ordered by scheduled start")
        if frontier is not None:
            gaps.append(max(0, start - frontier))
            # Sum excess scheduled duration, including nested/triple overlap,
            # without mistaking an earlier long clip for silence.
            overlaps.append(max(0, min(end, frontier) - start))
        frontier = end if frontier is None else max(frontier, end)
        previous_start = start
    if not waits:
        raise ValueError("empty observations")
    ordered = sorted(waits)
    return dict(clips=len(rows), median_wait_ms=statistics.median(waits),
                p95_wait_ms=ordered[math.ceil(len(ordered) * .95) - 1],
                gap_ms=sum(gaps), overlap_ms=sum(overlaps))


def compare(data):
    if set(data) != {"fixture_id", "baseline", "candidate"} or not data["fixture_id"]:
        raise ValueError("same public fixture identity required")
    first, second = data["baseline"], data["candidate"]
    ids = [row["clip_id"] for row in first]
    if len(set(ids)) != len(ids) or ids != [row["clip_id"] for row in second]:
        raise ValueError("ordered clip identities must match uniquely")
    return dict(scope="software scheduling only", baseline=metrics(first), candidate=metrics(second))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observations", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(json.loads(args.observations.read_text(encoding="utf-8"))),
                     sort_keys=True))


if __name__ == "__main__":
    main()
