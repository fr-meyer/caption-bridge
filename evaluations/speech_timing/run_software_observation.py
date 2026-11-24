"""Provider-free software observation. Never opens a device or browser."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from evaluations.speech_timing.timeline import classify  # noqa: E402
from scripts.playback_timing_compare import compare  # noqa: E402


def collect():
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("existing_node_required")
    completed = subprocess.run(
        [node, "--max-old-space-size=128",
         str(ROOT / "evaluations/speech_timing/observe_scheduling.cjs")],
        cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
    )
    if completed.returncode:
        raise RuntimeError("scheduling_observation_failed")
    report = json.loads(completed.stdout)
    # Reuse the existing interval-frontier comparator without changing its algorithm.
    report["scheduler_comparison"] = compare(report["comparison"])
    for row in report["observations"]:
        row["timing_classification"] = classify(row["source_trace"], row["probe"])
        if not row["timing_classification"]["complete"]:
            raise RuntimeError("incomplete_software_observation")
    paths = ["app/static/pcm-player.js", "evaluations/speech_timing/browser_probe.cjs",
             "evaluations/speech_timing/generated_fixture.cjs",
             "evaluations/speech_timing/observe_scheduling.cjs",
             "evaluations/speech_timing/run_software_observation.py",
             "evaluations/speech_timing/timeline.py",
             "scripts/playback_timing_compare.py"]
    report["source_sha256"] = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths
    }
    report["node_version"] = subprocess.run(
        [node, "--version"], capture_output=True, text=True, timeout=5, check=True,
    ).stdout.strip()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True,
                        help="new private output file; parent directory must exist")
    args = parser.parse_args()
    report = collect()
    # Exclusive write prevents accidentally rewriting a failed/historical attempt.
    with args.receipt.open("x", encoding="utf-8") as destination:
        json.dump(report, destination, allow_nan=False, sort_keys=True, indent=2)
        destination.write("\n")
    print(json.dumps({"scope": report["scope"], "clips": len(report["observations"]),
                      "acceptance": report["acceptance"]}))


if __name__ == "__main__":
    main()
