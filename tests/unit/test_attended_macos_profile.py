"""Source-only profile tests. No macOS or native process execution."""
import hashlib
import plistlib
import unittest

from scripts.attended_macos_profile import (
    ENTITLEMENTS,
    ROLES,
    LifetimeModel,
    native_launch,
    preflight,
)


class MacProfileTests(unittest.TestCase):
    def supplied(self):
        raw = b'fake-not-an-executable'
        return {role: {'bytes': raw, 'sha256': hashlib.sha256(raw).hexdigest()}
                for role in ROLES}

    def test_even_matching_source_never_admits(self):
        result = preflight('a' * 40, self.supplied(), plistlib.dumps(ENTITLEMENTS), {})
        self.assertTrue(result.source_bound)
        self.assertFalse(result.native_admission)
        self.assertIn('guardian_death_close', result.missing)
        with self.assertRaisesRegex(RuntimeError, 'disabled'):
            native_launch(ready=True, qualified=True, command=['anything'])

    def test_network_and_extra_entitlements_rejected(self):
        for key in ('com.apple.security.network.client', 'com.apple.security.network.server',
                    'com.apple.security.inherit', 'custom'):
            ent = dict(ENTITLEMENTS, **{key: True})
            result = preflight('a' * 40, self.supplied(), plistlib.dumps(ent), {})
            self.assertFalse(result.source_bound)

    def test_bytes_and_attestation_not_trusted(self):
        supplied = self.supplied()
        supplied['capture']['sha256'] = '0' * 64
        result = preflight('a' * 40, supplied, plistlib.dumps(ENTITLEMENTS), {'pass': True})
        self.assertFalse(result.source_bound)
        self.assertIn('untrusted_attestation', result.missing)
        self.assertFalse(result.native_admission)

    def test_single_open_and_no_restart(self):
        model = LifetimeModel(100)
        self.assertEqual(model.step('open', 1), ('open_single_input',))
        self.assertIn('close_input', model.step('open', 2))
        self.assertEqual(model.step('open', 3), ())

    def test_all_deaths_close_and_cannot_revive(self):
        for event in ('controller_eof', 'guardian_a_eof', 'guardian_b_eof',
                      'backend_error', 'stop'):
            model = LifetimeModel(100)
            model.step('open', 1)
            self.assertEqual(model.step(event, 2), ('mute', 'close_input', 'verify_closed'))
            self.assertEqual(model.step('open', 3), ())

    def test_deadline_and_clock_failure(self):
        for now in (100, 101, -1, True):
            model = LifetimeModel(100)
            self.assertIn('close_input', model.step('tick', now))

    def test_route_change_is_muted_first(self):
        model = LifetimeModel(100)
        model.step('open', 1)
        self.assertEqual(model.step('route_change', 2), ('mute', 'invalidate_route'))
        self.assertTrue(model.muted)
        self.assertIn('close_input', model.step('unmute', 3))


if __name__ == '__main__':
    unittest.main()
