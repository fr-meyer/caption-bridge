import unittest

from scripts.playback_capture_adapter import analyze_window, calibrate, capture_budget, continuity
from scripts.playback_measurement import correlate, marker, summarize


class AdapterTests(unittest.TestCase):
    def test_calibration(self):
        clock = calibrate([(0, 100, .1), (1000, 225, .1), (2000, 350, .1)], 8000)
        self.assertAlmostEqual(clock["offset_ms"], 100)
        with self.assertRaises(ValueError):
            calibrate([(0, 100, .1), (1000, 230, .1), (2000, 350, .1)], 8000)

    def test_consume_and_erase(self):
        pcm = [0]*80+marker()
        clock = calibrate([(0, 100, .1), (1000, 225, .1), (2000, 350, .1)], 8000)
        result = analyze_window(marker(), pcm, window_start_sample=0, request_ms=90,
                                clock=clock, blocks=[dict(start_sample=0, samples=207,
                                                         underruns=0)], scope="digital_loopback")
        self.assertEqual(result["request_to_output_ms"], 20)
        self.assertEqual(result["continuity_scope"], "capture_transport_only")
        self.assertEqual(pcm, [0]*207)

    def test_error_erases(self):
        pcm = marker()
        with self.assertRaises(ValueError):
            analyze_window(marker(), pcm, window_start_sample=0, request_ms=0,
                           clock=None, blocks=None, scope="acoustic")
        self.assertEqual(pcm, [0]*127)

    def test_continuity(self):
        result = continuity([dict(start_sample=0, samples=100, underruns=0),
                             dict(start_sample=120, samples=100, underruns=1),
                             dict(start_sample=210, samples=20, underruns=0)], 8000)
        self.assertEqual(result["gap_ms"], 2.5)
        self.assertEqual(result["overlap_ms"], 1.25)
        self.assertEqual(result["underruns"], 1)
        for blocks in (None, [], [dict(start_sample=0, samples=100, underruns=None)]):
            with self.assertRaises(ValueError):
                continuity(blocks, 8000)

    def test_budget_not_authority(self):
        args = dict(remaining_seconds=600, window_seconds=2, calibration_seconds=20,
                    other_lanes_seconds=60, retry_seconds=40)
        result = capture_budget(**args)
        self.assertTrue(result["fits"])
        self.assertEqual(result["planned_seconds"], 600)
        self.assertFalse(result["capture_authorized"])
        self.assertFalse(capture_budget(**(args | dict(window_seconds=2.1)))["fits"])

    def test_malformed_bounds(self):
        for rows in (None, [None], [dict()], [None]*10001):
            with self.assertRaises(ValueError):
                summarize(rows)
        for pcm in (None, "bad", iter([0]*200)):
            with self.assertRaises(ValueError):
                correlate(marker(), pcm)
