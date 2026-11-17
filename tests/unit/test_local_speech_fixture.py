import importlib.util
import struct
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / "speed-evaluation/fixtures/prepare_local_macos.py"
SPEC = importlib.util.spec_from_file_location("local_fixture", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FixtureTests(unittest.TestCase):
    def test_numeric_pcm(self):
        result = MODULE.validate_pcm(struct.pack("<ff", .25, -.25))
        self.assertEqual(result["samples"], 2)
        self.assertEqual(result["peak"], .25)
        self.assertEqual(len(result["sha256"]), 64)

    def test_reject_malformed_silence_nonfinite(self):
        for data in (b"", b"x", struct.pack("<f", 0), struct.pack("<f", float("nan")),
                     struct.pack("<f", 2)):
            with self.assertRaises(ValueError):
                MODULE.validate_pcm(data)
