"""Offline parent budget seam only. No native process, inference or device access."""
import dataclasses
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from scripts.attended_helper_budget import Custody, admit_helper
from scripts.attended_journal import Journal
from scripts.attended_macos_profile import native_launch


class LaunchBudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.directory.name) / 'journal'
        self.programme = 'a' * 64
        Journal.initialize(self.path, self.programme)
        self.journal = Journal(self.path, self.programme)
        self.custody = Custody(self.journal)
        self.cap, self.channel, self.peer = self.custody.session('b' * 40)

    def tearDown(self):
        self.custody.revoke(self.cap)
        self.peer.close()
        self.journal.close()
        self.directory.cleanup()

    def prepare(self):
        receipt = self.custody.offer(self.cap, self.channel, 100)
        return self.custody.prepare_launch(self.cap, self.channel, receipt)

    def test_durable_debit_and_false_admission(self):
        lease = self.prepare()
        self.assertEqual(self.journal.charged, 100)
        self.assertEqual(lease.sequence, self.journal.active['sequence'])
        self.assertFalse(lease.native_admission)
        self.assertGreater(self.custody.launch_remaining_ns(self.cap, self.channel, lease), 0)
        for function in (admit_helper, native_launch):
            with self.assertRaises(RuntimeError):
                function(lease)

    def test_copy_not_capability(self):
        lease = self.prepare()
        with self.assertRaisesRegex(RuntimeError, 'launch_binding'):
            self.custody.launch_remaining_ns(self.cap, self.channel, dataclasses.replace(lease))

    def test_expired_debit_not_refunded(self):
        lease = self.prepare()
        with patch('scripts.attended_helper_budget.time.monotonic_ns', return_value=lease.deadline_ns):
            with self.assertRaisesRegex(RuntimeError, 'expired_hold'):
                self.custody.launch_remaining_ns(self.cap, self.channel, lease)
        self.assertEqual(self.journal.charged, 100)
        self.assertIsNotNone(self.journal.active)

    def test_journal_latency_does_not_extend_deadline(self):
        receipt = self.custody.offer(self.cap, self.channel, 100)
        original = self.custody.reserve
        def slow_reserve(*args):
            result = original(*args)
            clock.return_value += 100_000_000
            return result
        with patch('scripts.attended_helper_budget.time.monotonic_ns', return_value=1_000_000_000) as clock:
            with patch.object(self.custody, 'reserve', side_effect=slow_reserve):
                with self.assertRaisesRegex(RuntimeError, 'expired_hold'):
                    self.custody.prepare_launch(self.cap, self.channel, receipt)
        self.assertEqual(self.journal.charged, 100)
        self.assertIsNotNone(self.journal.active)

    def test_second_session_cannot_reserve(self):
        self.prepare()
        cap, channel, peer = self.custody.session('c' * 40)
        try:
            receipt = self.custody.offer(cap, channel, 100)
            with self.assertRaisesRegex(RuntimeError, 'unclosed_reservation'):
                self.custody.prepare_launch(cap, channel, receipt)
            self.assertEqual(self.journal.charged, 100)
        finally:
            self.custody.revoke(cap)
            peer.close()

    def test_revoke_does_not_clear_restart_hold(self):
        self.prepare()
        self.custody.revoke(self.cap)
        self.journal.close()
        self.journal = Journal(self.path, self.programme)
        self.assertEqual(self.journal.charged, 100)
        with self.assertRaisesRegex(RuntimeError, 'custody_unclosed'):
            Custody(self.journal)

    def test_wrong_process_rejected(self):
        lease = self.prepare()
        with patch('scripts.attended_helper_budget.os.getpid', return_value=-1):
            with self.assertRaisesRegex(RuntimeError, 'wrong_process'):
                self.custody.launch_remaining_ns(self.cap, self.channel, lease)

    def test_clock_regression_rejected(self):
        lease = self.prepare()
        with patch('scripts.attended_helper_budget.time.monotonic_ns', return_value=0):
            with self.assertRaisesRegex(RuntimeError, 'clock_regressed_hold'):
                self.custody.launch_remaining_ns(self.cap, self.channel, lease)

    def test_closed_journal_rejected(self):
        lease = self.prepare()
        self.journal.close()
        with self.assertRaisesRegex(RuntimeError, 'launch_binding'):
            self.custody.launch_remaining_ns(self.cap, self.channel, lease)

    def test_receipt_replay_rejected(self):
        receipt = self.custody.offer(self.cap, self.channel, 100)
        self.custody.prepare_launch(self.cap, self.channel, receipt)
        with self.assertRaisesRegex(RuntimeError, 'stale_or_replayed'):
            self.custody.prepare_launch(self.cap, self.channel, receipt)


if __name__ == '__main__':
    unittest.main()
