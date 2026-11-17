"""Stdlib-only, no audio or permissions."""
import pathlib
import plistlib
import unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]

class NativeSourceTests(unittest.TestCase):
    def test_entitlements(self):
        self.assertEqual(plistlib.loads((ROOT / 'native/caption_helper/entitlements.plist').read_bytes()),
                         {'com.apple.security.app-sandbox': True})

    def test_no_audio_or_dynamic_execution(self):
        source = (ROOT / 'native/caption_helper/main.c').read_text()
        for forbidden in ('AudioUnit', 'CoreAudio', 'AVFoundation', 'execve(', 'system(', 'dlopen('):
            self.assertNotIn(forbidden, source)

    def test_capture_absent(self):
        source = (ROOT / 'native/caption_helper/main.c').read_text()
        self.assertIn('return 64; /* Includes --capture', source)
        self.assertIn('alarm((unsigned)seconds)', source)

if __name__ == '__main__':
    unittest.main()
