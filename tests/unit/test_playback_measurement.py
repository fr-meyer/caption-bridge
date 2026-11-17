import unittest

from scripts.playback_measurement import correlate, marker, onset, summarize


def row(pair="0", mode="buffered", **changes):
    result = dict(pair_id=pair, mode=mode, browser="synthetic-not-native",
                  scope="digital_loopback", fixture_id="marker-v1", valid=True,
                  reason="ok", latency_ms=50, gap_ms=0, overlap_ms=0, underruns=0)
    return result | changes


class MeasurementTests(unittest.TestCase):
    def test_offset_gain_dc_and_polarity(self):
        ref = marker()
        for gain in (0.5, -0.5, 1):
            capture = [0.01]*80 + [x*gain+0.01 for x in ref] + [0.01]*40
            self.assertEqual(correlate(ref, capture)["offset_samples"], 80)

    def test_missing_and_ambiguous(self):
        ref = marker()
        self.assertEqual(correlate(ref, [0]*300)["reason"], "marker_missing")
        self.assertEqual(correlate(ref, ref+[0]*30+ref)["reason"], "ambiguous_marker")

    def test_bad_pcm(self):
        for captured in ([], [float("nan")]*200, [2]*200, [0]*24001):
            with self.assertRaises(ValueError):
                correlate(marker(), captured)
        with self.assertRaises(ValueError):
            correlate([0]*127, [0]*200)

    def test_clock_and_scope(self):
        args = dict(sample_rate=8000, capture_start_ms=100, request_ms=90,
                    clock_uncertainty_ms=0.5, scope="digital_loopback")
        result = onset(marker(), [0]*80+marker(), **args)
        self.assertEqual(result["request_to_output_ms"], 20)
        self.assertEqual(result["scope"], "digital_loopback")
        with self.assertRaises(ValueError):
            onset(marker(), marker(), **(args | dict(scope="scheduling")))
        self.assertFalse(onset(marker(), marker(), **(args | dict(request_ms=200)))["valid"])

    def test_denominators_and_pairing(self):
        rows = [row(str(i), mode, latency_ms=50 if mode == "buffered" else 30)
                for i in range(30) for mode in ("buffered", "progressive")]
        result = summarize(rows)
        self.assertTrue(result["minimum_met"])
        self.assertEqual(result["paired_delta_ms"]["p95_ms"], -20)
        rows.append(row("failed", "progressive", valid=False, reason="timeout", latency_ms=None))
        result = summarize(rows)
        self.assertEqual(result["progressive"]["attempts"], 31)
        self.assertEqual(result["progressive"]["invalid"], 1)
        self.assertEqual(result["unpaired_attempts"], 1)
        self.assertEqual(result["acceptance"], "not_evaluated")

    def test_reject_mixed_duplicate_malformed(self):
        cases = [[row(), row()], [row(), row("1", scope="acoustic")],
                 [row(latency_ms=float("inf"))], [row(underruns=True)],
                 [row(valid=False)], [row(private_text="no")], []]
        for rows in cases:
            with self.assertRaises(ValueError):
                summarize(rows)

    def test_all_invalid_no_fake_percentiles(self):
        result = summarize([row(valid=False, reason="cancelled", latency_ms=None)])
        self.assertIsNone(result["buffered"]["latency"]["p95_ms"])
        self.assertFalse(result["minimum_met"])
