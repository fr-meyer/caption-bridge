"""Render content-free Caption Bridge reliability history and trends."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from app.reliability import load_history


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _queue_loss_events(record: dict[str, Any]) -> int:
    queues = record["queues"]
    return (
        queues["audio"]["dropped"]
        + queues["websocket"]["dropped"]
        + queues["tts"]["skipped"]
    )


def _window_summary(records: list[dict[str, Any]]) -> dict[str, float | int | None]:
    session_count = len(records)
    translation_total = sum(record["translation"]["total"] for record in records)
    degraded = sum(
        record["translation"]["failed"] + record["translation"]["timed_out"]
        for record in records
    )
    export_successes = sum(
        record["export"]["outcome"] == "succeeded" for record in records
    )
    return {
        "sessions": session_count,
        "average_duration_ms": (
            round(sum(record["duration_ms"] for record in records) / session_count, 1)
            if session_count
            else None
        ),
        "reconnect_cycles_per_session": (
            round(
                sum(record["reconnect"]["cycles"] for record in records)
                / session_count,
                4,
            )
            if session_count
            else None
        ),
        "reconnect_downtime_ms_per_session": (
            round(
                sum(record["reconnect"]["downtime_ms"] for record in records)
                / session_count,
                1,
            )
            if session_count
            else None
        ),
        "queue_loss_events_per_session": (
            round(sum(_queue_loss_events(record) for record in records) / session_count, 4)
            if session_count
            else None
        ),
        "translation_degraded_rate": _ratio(degraded, translation_total),
        "export_success_rate": _ratio(export_successes, session_count),
    }


def _delta(
    recent: dict[str, float | int | None],
    previous: dict[str, float | int | None],
) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for key in recent:
        if key == "sessions":
            continue
        current = recent[key]
        prior = previous[key]
        result[key] = (
            round(float(current) - float(prior), 4)
            if current is not None and prior is not None
            else None
        )
    return result


def build_report(
    sessions: list[dict[str, Any]],
    soaks: list[dict[str, Any]],
    *,
    recent_limit: int = 10,
    trend_window: int = 5,
    skipped: int = 0,
) -> dict[str, Any]:
    translation = Counter()
    reconnect = Counter()
    export_outcomes = Counter()
    queue_totals = Counter()
    queue_peaks = Counter()
    for record in sessions:
        translation.update(record["translation"])
        reconnect.update(
            {
                key: value
                for key, value in record["reconnect"].items()
                if key != "last_outcome"
            }
        )
        export_outcomes[record["export"]["outcome"]] += 1
        queues = record["queues"]
        queue_totals.update(
            {
                "audio_dropped": queues["audio"]["dropped"],
                "websocket_dropped": queues["websocket"]["dropped"],
                "websocket_coalesced": queues["websocket"]["coalesced"],
                "websocket_critical_drops": queues["websocket"]["critical_drops"],
                "tts_retries": queues["tts"]["retries"],
                "tts_skipped": queues["tts"]["skipped"],
                "tts_failures": queues["tts"]["failures"],
            }
        )
        queue_peaks["audio"] = max(queue_peaks["audio"], queues["audio"]["peak_depth"])
        queue_peaks["websocket"] = max(
            queue_peaks["websocket"], queues["websocket"]["peak_depth"]
        )
        queue_peaks["tts"] = max(queue_peaks["tts"], queues["tts"]["peak_depth"])

    repair_attempts = translation["repair_attempts"]
    recent_window = sessions[-trend_window:]
    previous_window = sessions[-(trend_window * 2) : -trend_window]
    recent_stats = _window_summary(recent_window)
    previous_stats = _window_summary(previous_window)
    soak_types = Counter(record["run_type"] for record in soaks)
    soak_passes = Counter(
        record["run_type"] for record in soaks if record["passed"]
    )

    return {
        "schema_version": 1,
        "sessions": {
            "total": len(sessions),
            "duration_ms_total": sum(record["duration_ms"] for record in sessions),
            "translation": {
                **dict(sorted(translation.items())),
                "degraded_rate": _ratio(
                    translation["failed"] + translation["timed_out"],
                    translation["total"],
                ),
                "repair_success_rate": _ratio(
                    translation["repair_succeeded"], repair_attempts
                ),
            },
            "reconnect": dict(sorted(reconnect.items())),
            "queues": {
                "totals": dict(sorted(queue_totals.items())),
                "peak_depth": dict(sorted(queue_peaks.items())),
            },
            "export_outcomes": dict(sorted(export_outcomes.items())),
            "recent": [
                {
                    "session_id": record["session_id"],
                    "recorded_at": record["recorded_at"],
                    "duration_ms": record["duration_ms"],
                    "terminal_state": record["terminal_state"],
                    "translation_total": record["translation"]["total"],
                    "translation_degraded": (
                        record["translation"]["failed"]
                        + record["translation"]["timed_out"]
                    ),
                    "reconnect_cycles": record["reconnect"]["cycles"],
                    "reconnect_downtime_ms": record["reconnect"]["downtime_ms"],
                    "queue_loss_events": _queue_loss_events(record),
                    "export_outcome": record["export"]["outcome"],
                }
                for record in sessions[-recent_limit:]
            ],
        },
        "trend": {
            "window_size": trend_window,
            "recent": recent_stats,
            "previous": previous_stats,
            "delta": _delta(recent_stats, previous_stats),
        },
        "soaks": {
            "total": len(soaks),
            "by_type": dict(sorted(soak_types.items())),
            "passed_by_type": dict(sorted(soak_passes.items())),
            "recent": soaks[-recent_limit:],
        },
        "skipped_records": skipped,
    }


def _render_human(report: dict[str, Any]) -> None:
    sessions = report["sessions"]
    print("Caption Bridge reliability history (content-free)")
    print(f"sessions: {sessions['total']}")
    print(f"duration_ms_total: {sessions['duration_ms_total']}")
    print(f"translation: {json.dumps(sessions['translation'], sort_keys=True)}")
    print(f"reconnect: {json.dumps(sessions['reconnect'], sort_keys=True)}")
    print(f"queues: {json.dumps(sessions['queues'], sort_keys=True)}")
    print(f"export_outcomes: {json.dumps(sessions['export_outcomes'], sort_keys=True)}")
    print(f"trend: {json.dumps(report['trend'], sort_keys=True)}")
    print(f"soaks: {json.dumps(report['soaks'], sort_keys=True)}")
    print(f"skipped_records: {report['skipped_records']}")
    if sessions["recent"]:
        print("recent sessions:")
        for record in sessions["recent"]:
            print("  " + json.dumps(record, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-dir", type=Path, default=Path("runs/reliability"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--trend-window", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.limit < 1 or args.trend_window < 1:
        parser.error("--limit and --trend-window must be positive")

    sessions, soaks, skipped = load_history(args.history_dir)
    report = build_report(
        sessions,
        soaks,
        recent_limit=args.limit,
        trend_window=args.trend_window,
        skipped=skipped,
    )
    if skipped:
        print(
            f"WARNING: skipped {skipped} malformed or unknown-schema reliability record(s)",
            file=sys.stderr,
        )
    if args.json:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        _render_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
