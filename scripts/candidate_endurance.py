"""Provider-free bounded application fault cycles, never physical acceptance."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import subprocess
import time
from pathlib import Path


async def endurance(cycles, cycle, *, clock=time.monotonic,
                    cycle_timeout=45, total_timeout=240):
    if type(cycles) is not int or not 1 <= cycles <= 100:
        raise ValueError("cycles must be an integer in [1,100]")
    for bound in (cycle_timeout, total_timeout):
        if not math.isfinite(bound) or bound <= 0:
            raise ValueError("timeouts must be finite and positive")
    started = clock()
    report = dict(passed=False, expected_cycles=cycles, completed_cycles=0,
                  cycles=0, wall_seconds=0.0, max_cycle_seconds=0.0)
    for _ in range(cycles):
        before = clock()
        remaining = total_timeout - (before - started)
        if remaining <= 0:
            report["failure_type"] = "TimeoutError"
            break
        try:
            passed = await asyncio.wait_for(cycle(), timeout=min(cycle_timeout, remaining))
            report["completed_cycles"] += 1
            if not passed:
                report["failure_type"] = "CycleFailed"
        except Exception as exc:
            # Do not retain exception messages, which might contain runtime content.
            report["failure_type"] = type(exc).__name__
        finally:
            after = clock()
            report["max_cycle_seconds"] = max(report["max_cycle_seconds"], after - before)
            report["wall_seconds"] = after - started
            report["cycles"] = report["completed_cycles"]
        # wait_for may return normally if cancellation is suppressed, or if a
        # blocking cycle prevents delivery. Elapsed deadlines still fail closed.
        if after - before >= cycle_timeout or report["wall_seconds"] >= total_timeout:
            report["failure_type"] = "TimeoutError"
        if "failure_type" in report:
            break
    report["wall_seconds"] = clock() - started
    report["passed"] = report["completed_cycles"] == cycles and "failure_type" not in report
    return report


async def application_cycle():
    # wait_for runs this cycle in a child task; its supervising task is not a leak.
    baseline = asyncio.all_tasks()
    from scripts.full_pipeline_scenario import run_full_pipeline_scenario

    report = await asyncio.wait_for(run_full_pipeline_scenario(), timeout=45)
    # Check for leaked tasks after each application teardown, not just at exit.
    await asyncio.sleep(0)
    live = [task for task in asyncio.all_tasks()
            if task not in baseline and not task.done()]
    return report.passed and not live


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.cycles <= 100:
        parser.error("cycles must be in [1,100]")
    logging.disable(logging.CRITICAL)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    from evaluations.reliability_v050.run_offline import DENIED, install_guards

    report = dict(passed=False, expected_cycles=args.cycles, completed_cycles=0,
                  cycles=0, wall_seconds=0.0, max_cycle_seconds=0.0)
    guard = None
    try:
        guard = install_guards()
        report = asyncio.run(endurance(args.cycles, application_cycle))
        report["passed"] = report["passed"] and not DENIED
    except Exception as exc:
        report.update(passed=False, failure_type=type(exc).__name__)
    finally:
        if guard is not None:
            guard.close()
        report["denied_io_attempts"] = len(DENIED)
    report.update(commit=sha, requested_cycles=args.cycles,
                  scope="provider-free repeated application fault cycles",
                  physical_acceptance=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
