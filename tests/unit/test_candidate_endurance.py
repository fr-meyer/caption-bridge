import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from scripts.candidate_endurance import application_cycle, endurance, main


class EnduranceTests(unittest.TestCase):
    def test_exactly_100_without_intercycle_pause(self):
        now = [0.0]

        async def cycle():
            now[0] += 0.01
            return True

        with patch("scripts.candidate_endurance.asyncio.sleep", new_callable=AsyncMock) as sleep:
            report = asyncio.run(endurance(100, cycle, clock=lambda: now[0]))
        sleep.assert_not_called()
        self.assertTrue(report["passed"])
        self.assertEqual(report["completed_cycles"], 100)
        self.assertEqual(report["expected_cycles"], 100)
        self.assertAlmostEqual(report["wall_seconds"], 1)
        self.assertAlmostEqual(report["max_cycle_seconds"], 0.01)

    def test_failed_cycle_fails_immediately(self):
        cycle = AsyncMock(side_effect=[True, False, True])
        report = asyncio.run(endurance(100, cycle))
        self.assertFalse(report["passed"])
        self.assertEqual(report["completed_cycles"], 2)
        self.assertEqual(cycle.await_count, 2)

    def test_exception_preserves_progress_not_message(self):
        cycle = AsyncMock(side_effect=[True, RuntimeError("private payload")])
        report = asyncio.run(endurance(100, cycle))
        self.assertFalse(report["passed"])
        self.assertEqual(report["completed_cycles"], 1)
        self.assertEqual(report["failure_type"], "RuntimeError")
        self.assertNotIn("private payload", json.dumps(report))

    def test_application_assertions_and_leak_detection_under_supervisor(self):
        for passed, leak in ((True, False), (False, False), (True, True)):
            async def run():
                tasks = []

                async def scenario():
                    if leak:
                        tasks.append(asyncio.create_task(asyncio.Event().wait()))
                    return SimpleNamespace(passed=passed)

                module = SimpleNamespace(run_full_pipeline_scenario=scenario)
                with patch.dict("sys.modules", {"scripts.full_pipeline_scenario": module}):
                    try:
                        return await endurance(1, application_cycle)
                    finally:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)

            with self.subTest(passed=passed, leak=leak):
                self.assertEqual(asyncio.run(run())["passed"], passed and not leak)

    def test_invalid_counts(self):
        for count in (0, -1, 101, 1.5, 1.0, "100", True, None):
            with self.subTest(count=count), self.assertRaises(ValueError):
                asyncio.run(endurance(count, None))

    def test_invalid_timeouts(self):
        for bound in (0, -1, float("inf"), float("nan")):
            for name in ("cycle_timeout", "total_timeout"):
                with self.subTest(bound=bound, name=name), self.assertRaises(ValueError):
                    asyncio.run(endurance(100, None, **{name: bound}))

    def test_cycle_timeout_cancels_and_stops(self):
        cancelled = []

        async def cycle():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

        report = asyncio.run(endurance(100, cycle, cycle_timeout=0.01))
        self.assertFalse(report["passed"])
        self.assertEqual(report["completed_cycles"], 0)
        self.assertEqual(report["failure_type"], "TimeoutError")
        self.assertEqual(cancelled, [True])

    def test_suppressed_cancellation_still_fails_before_next_cycle(self):
        calls = []

        async def cycle():
            calls.append(True)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return True

        report = asyncio.run(endurance(100, cycle, cycle_timeout=0.01, total_timeout=1))
        self.assertFalse(report["passed"])
        self.assertEqual(report["failure_type"], "TimeoutError")
        self.assertEqual(report["completed_cycles"], 1)
        self.assertEqual(calls, [True])

    def test_slow_normal_return_still_fails_cycle_deadline(self):
        now = [0.0]
        calls = []

        async def cycle():
            calls.append(True)
            now[0] += 2
            return True

        report = asyncio.run(endurance(100, cycle, clock=lambda: now[0],
                                       cycle_timeout=1, total_timeout=100))
        self.assertFalse(report["passed"])
        self.assertEqual(report["failure_type"], "TimeoutError")
        self.assertEqual(report["completed_cycles"], 1)
        self.assertEqual(report["max_cycle_seconds"], 2)
        self.assertEqual(calls, [True])

    def test_total_timeout_bounds_current_cycle(self):
        async def cycle():
            await asyncio.Event().wait()
        report = asyncio.run(endurance(100, cycle, total_timeout=0.01))
        self.assertEqual(report["failure_type"], "TimeoutError")
        self.assertEqual(report["completed_cycles"], 0)

    def test_total_timeout_stops_before_next_cycle(self):
        now = [0.0]

        async def cycle():
            now[0] += 2
            return True
        report = asyncio.run(endurance(100, cycle, clock=lambda: now[0], total_timeout=3))
        self.assertFalse(report["passed"])
        self.assertEqual(report["completed_cycles"], 2)
        self.assertEqual(report["failure_type"], "TimeoutError")

    def test_cli_rejects_invalid_counts_and_old_duration(self):
        for value in ("0", "-1", "101", "1.5", "abc"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(["--cycles", value, "--output", "unused.json"])
                self.assertEqual(error.exception.code, 2)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--minutes", "120", "--output", "unused.json"])

    def test_cli_default_report_and_io_failure(self):
        from evaluations.reliability_v050 import run_offline

        for denied in ([], ["network"]):
            with self.subTest(denied=denied), tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
                output = Path(tmp) / "report.json"
                guard = Mock()
                cycle = AsyncMock(return_value=True)
                with patch.object(run_offline, "install_guards", return_value=guard), \
                     patch.object(run_offline, "DENIED", denied), \
                     patch("scripts.candidate_endurance.application_cycle", cycle), \
                     patch("scripts.candidate_endurance.subprocess.check_output", return_value="a" * 40), \
                     patch("scripts.candidate_endurance.logging.disable"), \
                     contextlib.redirect_stdout(io.StringIO()):
                    code = main(["--output", str(output)])
                report = json.loads(output.read_text())
                self.assertEqual(code, 1 if denied else 0)
                self.assertEqual(report["commit"], "a" * 40)
                self.assertEqual(report["completed_cycles"], 100)
                self.assertEqual(report["expected_cycles"], 100)
                self.assertEqual(report["denied_io_attempts"], len(denied))
                self.assertFalse(report["physical_acceptance"])
                guard.close.assert_called_once()


class WorkflowContractTests(unittest.TestCase):
    def test_exact_commit_automatic_and_reusable_contract(self):
        workflow = (Path(__file__).resolve().parents[2] /
                    ".github/workflows/candidate-endurance.yml").read_text()
        self.assertIn("  pull_request:\n    branches: [main]", workflow)
        self.assertIn("  push:\n    branches: [main]", workflow)
        self.assertIn("  workflow_call:", workflow)
        self.assertIn("  workflow_dispatch:", workflow)
        self.assertIn("name: candidate-100-cycles", workflow)
        self.assertIn("timeout-minutes: 10", workflow)
        self.assertIn("inputs.sha || github.event.pull_request.head.sha || github.sha", workflow)
        self.assertIn("ref: $" + "{{ env.EXPECTED_SHA }}", workflow)
        self.assertIn('test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"', workflow)
        self.assertIn("^[0-9a-f]{40}$", workflow)
        self.assertEqual(workflow.count("--cycles 100"), 1)
        self.assertNotIn("--minutes", workflow)
        self.assertNotIn("[endurance]", workflow)
        self.assertNotIn("agent/caption-unified", workflow)
