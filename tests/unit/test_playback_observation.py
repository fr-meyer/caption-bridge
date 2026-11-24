"""Real monotonic software execution, with a modeled sink, never physical acceptance."""
from __future__ import annotations

import importlib.util
import itertools
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "software_observation", ROOT / "evaluations/speech_timing/run_software_observation.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ObservationTests(unittest.TestCase):
    def test_production_scheduler_receipt_and_existing_comparator(self):
        report = MODULE.collect()
        self.assertFalse(report["real_browser"])
        self.assertFalse(report["digital_output_measured"])
        self.assertFalse(report["acoustic_measured"])
        self.assertEqual(report["acceptance"], "not_evaluated")
        self.assertEqual(report["physical_streams"], 0)
        self.assertEqual(report["provider_requests"], 0)
        self.assertEqual(len(report["source_sha256"]), 7)
        self.assertEqual(len(report["observations"]), 4)
        self.assertEqual(report["fixture"]["samples"], 15840)
        self.assertEqual(report["scheduler_comparison"]["baseline"]["clips"], 2)
        self.assertEqual(report["scheduler_comparison"]["candidate"]["clips"], 2)
        for row in report["observations"]:
            self.assertEqual(row["exact_pcm_samples"], 15840)
            self.assertEqual(row["starts"], 1)
            self.assertEqual(row["completions"], 1)
            self.assertEqual(row["remaining_bytes"], 0)
            self.assertEqual(row["remaining_clips"], 0)
            self.assertEqual(row["live_sink_nodes"], 0)
            self.assertEqual(row["probe"]["rejected"], 0)
            self.assertTrue(row["timing_classification"]["complete"])
            self.assertFalse(row["timing_classification"]["cause_assigned"])
            self.assertEqual(len(row["deliveries"]), 7)
            self.assertEqual(row["deliveries"][-1]["nominal_offset_ms"], 600)
        # Content-free receipts never contain a PCM/base64 payload.
        self.assertNotIn('"data"', json.dumps(report))

    def test_listener_packet_is_counterbalanced_and_not_a_go(self):
        packet = json.loads((ROOT / "speed-evaluation/listener-programme.json").read_text(
            encoding="utf-8",
        ))
        self.assertEqual(packet["default_rate"], 1)
        self.assertEqual(set(map(tuple, packet["rate_orders"])),
                         set(itertools.permutations([1, 1.15, 1.3])))
        self.assertEqual(len(packet["rate_orders"]), 6)
        self.assertEqual({row["language"] for row in packet["samples"]}, {"en", "ko"})
        self.assertIn("not_run", packet["verdicts"])
        self.assertIn("no synthesis", packet["scope"])
        self.assertIn("software success never implies GO", packet["go_authority"])

    def test_pending_action_focus_software_regression(self):
        result = subprocess.run(
            [shutil.which("node"), "--test",
             str(ROOT / "evaluations/speech_timing/test_terminology_keyboard.cjs")],
            capture_output=True, text=True, timeout=5, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
