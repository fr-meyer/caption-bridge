"""Provider-free continuous application fault cycles, never physical acceptance."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import time
from pathlib import Path


async def endurance(seconds, cycle, *, clock=time.monotonic, sleep=asyncio.sleep):
    if seconds <= 0:
        raise ValueError("duration must be positive")
    started = clock()
    cycles = 0
    max_cycle_s = 0.0
    while clock() - started < seconds:
        before = clock()
        passed = await cycle()
        cycles += 1
        max_cycle_s = max(max_cycle_s, clock() - before)
        if not passed:
            return dict(passed=False, cycles=cycles, wall_seconds=clock() - started,
                        max_cycle_seconds=max_cycle_s)
        await sleep(min(0.25, max(0, seconds - (clock() - started))))
    return dict(passed=True, cycles=cycles, wall_seconds=clock() - started,
                max_cycle_seconds=max_cycle_s)


async def application_cycle():
    from scripts.full_pipeline_scenario import run_full_pipeline_scenario

    report = await asyncio.wait_for(run_full_pipeline_scenario(), timeout=45)
    # Check for leaked tasks after each application teardown, not just at exit.
    await asyncio.sleep(0)
    live = [task for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()]
    return report.passed and not live


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=120)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.minutes <= 120:
        parser.error("minutes must be in (0,120]")
    logging.disable(logging.CRITICAL)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    try:
        report = asyncio.run(endurance(args.minutes * 60, application_cycle))
    except Exception as exc:
        # Never retain exception messages, which might include runtime content.
        report = dict(passed=False, failure_type=type(exc).__name__)
    report.update(commit=sha, requested_minutes=args.minutes,
                  scope="provider-free repeated application fault cycles",
                  physical_acceptance=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
