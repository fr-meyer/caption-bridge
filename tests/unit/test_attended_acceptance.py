"""Pure admission checks, not device or watchdog evidence."""
import unittest

from scripts.attended_acceptance import CAP_MS, PROOFS, validate


def packet():
    return {
        'schema': 'caption-attended-v1', 'candidate_sha': 'a' * 40,
        'meeting_ended': True, 'participant_ready': True, 'private_quiet': True,
        'proofs': {k: {'sha256': 'b' * 64, 'candidate_sha': 'a' * 40} for k in PROOFS},
        'ledger': [], 'requested_ms': 1000,
    }


class AdmissionTests(unittest.TestCase):
    def test_valid_plan(self):
        self.assertEqual(validate(packet()), [])

    def test_readiness(self):
        for key in ('meeting_ended', 'participant_ready', 'private_quiet'):
            for value in (False, 1, 'true', None):
                p = packet()
                p[key] = value
                self.assertIn(key, validate(p))

    def test_proofs_required_and_bound(self):
        for key in PROOFS:
            p = packet()
            del p['proofs'][key]
            self.assertIn('proofs_shape', validate(p))
            p = packet()
            p['proofs'][key]['candidate_sha'] = 'c' * 40
            self.assertIn('proof_' + key, validate(p))

    def test_cap_no_refund(self):
        p = packet()
        p['ledger'] = [{'sequence': 1, 'reserved_ms': CAP_MS - 1000,
                        'elapsed_ms': 1, 'closed': True}]
        self.assertEqual(validate(p), [])
        p['requested_ms'] = 1001
        self.assertIn('programme_cap', validate(p))

    def test_interruption(self):
        p = packet()
        p['ledger'] = [{'sequence': 1, 'reserved_ms': CAP_MS,
                        'elapsed_ms': 0, 'closed': False}]
        self.assertEqual(validate(p), ['programme_cap', 'unclosed_capture'])

    def test_overrun(self):
        p = packet()
        p['ledger'] = [{'sequence': 1, 'reserved_ms': 100,
                        'elapsed_ms': CAP_MS, 'closed': True}]
        self.assertEqual(validate(p), ['programme_cap', 'watchdog_overrun'])

    def test_invalid_private_fields_and_durations(self):
        for value in (None, [], {}, {'transcript': 'private'}):
            self.assertEqual(validate(value), ['packet_shape'])
        p = packet()
        p['participant_name'] = 'not retained'
        self.assertEqual(validate(p), ['packet_shape'])
        for value in (True, -1, 0, 0.5, '100', None):
            p = packet()
            p['requested_ms'] = value
            self.assertIn('requested_ms', validate(p))

    def test_duplicate_sequence(self):
        p = packet()
        row = {'sequence': 1, 'reserved_ms': 100, 'elapsed_ms': 50, 'closed': True}
        p['ledger'] = [row, dict(row)]
        self.assertIn('ledger_sequence', validate(p))
        p['ledger'][1]['sequence'] = 3
        self.assertIn('ledger_sequence', validate(p))

    def test_malformed_nested(self):
        for key, value, error in [('proofs', None, 'proofs_shape'),
                                  ('ledger', {}, 'ledger_shape'),
                                  ('ledger', [None], 'ledger_row'),
                                  ('candidate_sha', [], 'candidate_sha')]:
            p = packet()
            p[key] = value
            self.assertIn(error, validate(p))


if __name__ == '__main__':
    unittest.main()
