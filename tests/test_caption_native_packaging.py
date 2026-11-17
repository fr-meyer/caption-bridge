"""Source-only role identity packaging regression."""
import unittest
from pathlib import Path


class PackagingTests(unittest.TestCase):
    def test_fixed_role_has_embedded_matching_identity(self):
        build = (Path(__file__).resolve().parents[1] / 'scripts/build_caption_helper.sh').read_text()
        self.assertIn('-Wl,-sectcreate,__TEXT,__info_plist,', build)
        self.assertIn('<key>CFBundleIdentifier</key><string>local.captionbridge.$2</string>', build)
        self.assertIn('--identifier "local.captionbridge.$2"', build)
        self.assertIn('--entitlements "$ROOT/native/caption_helper/entitlements.plist"', build)
        self.assertNotIn('com.apple.security.inherit', build)
