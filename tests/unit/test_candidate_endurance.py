import asyncio
import unittest

from scripts.candidate_endurance import endurance


class EnduranceTests(unittest.TestCase):
    def test_real_duration_not_cycle_count(self):
        now = [0.0]

        async def cycle():
            now[0] += 2
            return True

        async def sleep(seconds):
            now[0] += seconds

        report = asyncio.run(endurance(10, cycle, clock=lambda: now[0], sleep=sleep))
        self.assertTrue(report["passed"])
        self.assertGreaterEqual(report["wall_seconds"], 10)
        self.assertEqual(report["cycles"], 5)

    def test_failed_cycle_fails_immediately(self):
        async def cycle():
            return False

        report = asyncio.run(endurance(7200, cycle))
        self.assertFalse(report["passed"])
        self.assertEqual(report["cycles"], 1)

    def test_invalid_duration(self):
        with self.assertRaises(ValueError):
            asyncio.run(endurance(0, None))
