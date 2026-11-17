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


class PublicFixtureTests(unittest.TestCase):
    def test_provisioned_originals_match_manifest(self):
        import hashlib
        import json

        root = PATH.parent
        manifest = json.loads((root / 'manifest.json').read_text())
        self.assertEqual({f['language'] for f in manifest['fixtures']}, {'ko', 'en-US'})
        for fixture in manifest['fixtures']:
            with self.subTest(fixture=fixture['id']):
                self.assertEqual(Path(fixture['path']).name, fixture['path'])
                data = (root / fixture['path']).read_bytes()
                self.assertTrue(data.startswith(b'OggS'))
                self.assertLessEqual(len(data), 65536)
                self.assertEqual(len(data), fixture['bytes'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), fixture['sha256'])
                self.assertTrue(fixture['source'].startswith('https://commons.wikimedia.org/wiki/File:'))
                self.assertTrue(fixture['license'])
                self.assertIsNone(fixture['pcm_sha256'])
