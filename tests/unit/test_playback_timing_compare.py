import unittest

from scripts.playback_timing_compare import compare, metrics


def row(clip, ready, start, end):
    return dict(clip_id=clip, ready_ms=ready, start_ms=start, end_ms=end)


class TimingTests(unittest.TestCase):
    def test_known_gaps_overlap_waits(self):
        result = metrics([row(1, 0, 2, 5), row(2, 1, 4, 6), row(3, 6, 8, 10)])
        self.assertEqual(result["overlap_ms"], 1)
        self.assertEqual(result["gap_ms"], 2)
        self.assertEqual(result["median_wait_ms"], 2)
        self.assertEqual(result["p95_wait_ms"], 3)

    def test_mismatched_inputs_rejected(self):
        with self.assertRaises(ValueError):
            compare(dict(fixture_id="public-v1", baseline=[row(1, 0, 0, 1)],
                         candidate=[row(2, 0, 0, 1)]))

    def test_private_fields_rejected(self):
        observation = row(1, 0, 0, 1)
        observation["text"] = "not permitted"
        with self.assertRaises(ValueError):
            metrics([observation])

    def test_nonfinite_and_backwards_rejected(self):
        for observation in [row(1, 0, float("nan"), 1), row(1, 2, 1, 3)]:
            with self.assertRaises(ValueError):
                metrics([observation])
