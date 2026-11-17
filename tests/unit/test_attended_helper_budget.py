"""Offline stdlib fixtures only. No helper launch, devices or provider calls."""
import concurrent.futures
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.attended_helper_budget import Custody, Receipt, admit_helper
from scripts.attended_journal import Journal


class CustodyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'budget'
        Journal.initialize(self.path, 'a' * 64)
        self.j = Journal(self.path, 'a' * 64)
        self.addCleanup(self.j.close)
        self.c = Custody(self.j)
        self.cap, self.channel, self.peer = self.session()

    def session(self):
        cap, channel, peer = self.c.session('b' * 40)
        self.addCleanup(peer.close)
        self.addCleanup(self.c.revoke, cap)
        return cap, channel, peer

    def offer(self, ms=100):
        return self.c.offer(self.cap, self.channel, ms)

    def test_tamper_and_unregistered_receipts(self):
        r = self.offer()
        for forged in (Receipt(r.payload + b'x', r.mac), Receipt(r.payload, '0' * 64)):
            with self.assertRaisesRegex(RuntimeError, 'authentication'):
                self.c.reserve(self.cap, self.channel, forged)
        self.assertEqual(self.j.charged, 0)
        self.c.reserve(self.cap, self.channel, r)
        with self.assertRaisesRegex(RuntimeError, 'replayed'):
            self.c.reserve(self.cap, self.channel, r)
        self.assertEqual(self.j.charged, 100)

    def test_wrong_capability_and_duplicated_channel(self):
        r = self.offer()
        duplicate = socket.socket(fileno=os.dup(self.channel.fileno()))
        self.addCleanup(duplicate.close)
        for cap, channel in ((object(), self.channel), (self.cap, duplicate)):
            with self.assertRaisesRegex(RuntimeError, 'binding'):
                self.c.reserve(cap, channel, r)
        self.assertEqual(self.j.charged, 0)

    def test_wrong_session_burns_receipt(self):
        r = self.offer()
        cap, channel, _ = self.session()
        with self.assertRaises(RuntimeError):
            self.c.reserve(cap, channel, r)
        with self.assertRaises(RuntimeError):
            self.c.reserve(self.cap, self.channel, r)

    def test_expiry_and_tail_binding(self):
        with patch('scripts.attended_helper_budget.time.monotonic_ns', return_value=1):
            r = self.offer()
        with patch('scripts.attended_helper_budget.time.monotonic_ns', return_value=1000000001):
            with self.assertRaisesRegex(RuntimeError, 'stale'):
                self.c.reserve(self.cap, self.channel, r)
        r = self.offer()
        self.j.reserve(1, 'b' * 40, 'c' * 64)
        self.j.finish('exit')
        with self.assertRaisesRegex(RuntimeError, 'stale'):
            self.c.reserve(self.cap, self.channel, r)

    def test_concurrent_one_shot(self):
        r = self.offer()
        def attempt(_):
            try:
                return self.c.reserve(self.cap, self.channel, r)
            except RuntimeError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(16)))
        self.assertEqual(results.count(1), 1)
        self.assertEqual(self.j.charged, 100)

    def test_shared_cap_and_permanent_unknown_hold(self):
        self.c.reserve(self.cap, self.channel, self.offer(599999))
        self.c.revoke(self.cap)
        self.assertIsNotNone(self.j.active)
        with self.assertRaisesRegex(RuntimeError, 'unclosed'):
            Custody(self.j)
        self.j.finish('stop')  # fixture terminal state only, not exposed by custody
        cap, channel, _ = self.session()
        with self.assertRaises(ValueError):
            self.c.reserve(cap, channel, self.c.offer(cap, channel, 2))
        self.c.reserve(cap, channel, self.c.offer(cap, channel, 1))
        self.assertEqual(self.j.charged, 600000)

    def test_restart_cannot_authenticate_prior_receipt(self):
        r = self.offer()
        other = Custody(self.j)
        with self.assertRaises(RuntimeError):
            other.reserve(self.cap, self.channel, r)

    def test_fsync_failure_poison_and_no_reuse(self):
        r = self.offer()
        with patch('scripts.attended_journal.os.fsync', side_effect=OSError):
            with self.assertRaises(OSError):
                self.c.reserve(self.cap, self.channel, r)
        self.assertTrue(self.j.poisoned)
        with self.assertRaises(RuntimeError):
            self.c.reserve(self.cap, self.channel, r)

    def test_fork_identity_and_native_refusal(self):
        with patch('scripts.attended_helper_budget.os.getpid', return_value=-1):
            with self.assertRaisesRegex(RuntimeError, 'wrong_process'):
                self.offer()
        with self.assertRaisesRegex(RuntimeError, 'verifier_unavailable'):
            admit_helper(receipt=self.offer(), identity=True, kernel=True, readiness=True)

class JournalAnchorTests(unittest.TestCase):
    def test_live_rollback_refused_and_poisoned(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'journal'
            Journal.initialize(path, 'a' * 64)
            initial = path.read_bytes()
            j = Journal(path, 'a' * 64)
            try:
                j.reserve(1, 'b' * 40, 'c' * 64)
                j.finish('exit')
                path.write_bytes(initial)
                with self.assertRaisesRegex(RuntimeError, 'anchor_changed'):
                    j.reserve(1, 'b' * 40, 'c' * 64)
                self.assertTrue(j.poisoned)
            finally:
                j.close()
                j.close()  # idempotent close cannot close a reused descriptor
