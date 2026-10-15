"""Composed production frontend callbacks with fake transport, clock and silent PCM."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def test_same_document_reconnect_pcm_and_virtual_accumulation_contracts():
    root = Path(__file__).resolve().parents[2]
    node = shutil.which("node")
    assert node is not None, "Node is required for the offline production-JS composition"
    result = subprocess.run(
        [node, "--max-old-space-size=128", str(root / "tests/fixtures/reconnect_pcm_node.cjs"),
         str(root / "app/static/app.js"), str(root / "app/static/pcm-player.js")],
        text=True, capture_output=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["passed"] and report["tests"] == 6
    assert report["virtualCycles"] == 24 and report["virtual_elapsed_ms"] == 7_200_000
    assert report["reconnects"] == 28 and report["staleCallbacks"] == 55
    assert report["timerPeak"] <= 2 and report["clipPeak"] <= 3 and report["bytePeak"] <= 48
    assert report["nodePeak"] <= 1 and report["retiredPeak"] <= 4
    assert not any(report[key] for key in ("network", "real_browser", "real_elapsed_endurance"))
    assert report["remaining"] == {
        "pcm_bytes": 0, "pcm_clips": 0, "pcm_queue": 0, "audio_nodes": 0,
        "timers": 0, "resume_promises": 0,
    }
