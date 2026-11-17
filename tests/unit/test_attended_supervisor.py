"""Offline POSIX ledger/watchdog tests, no native capture."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.attended_journal import Journal
from scripts.attended_supervisor import bind_proof, supervise

CANDIDATE = 'a' * 40
PROGRAMME = 'b' * 64
PROOF = 'c' * 64


@unittest.skipUnless(os.name == 'posix', 'POSIX offline profile only')
class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'journal'
        Journal.initialize(self.path, PROGRAMME)

    def journal(self):
        j = Journal(self.path, PROGRAMME)
        self.addCleanup(j.close)
        return j

    def test_exclusive_and_no_reinitialize(self):
        self.journal()
        with self.assertRaises(BlockingIOError):
            Journal(self.path, PROGRAMME)
        with self.assertRaises(FileExistsError):
            Journal.initialize(self.path, PROGRAMME)

    def test_no_refund_restart_and_cap(self):
        j = Journal(self.path, PROGRAMME)
        j.reserve(599999, CANDIDATE, PROOF)
        j.finish('stop')
        j.close()
        j = self.journal()
        self.assertEqual(j.charged, 599999)
        with self.assertRaises(ValueError):
            j.reserve(2, CANDIDATE, PROOF)
        j.reserve(1, CANDIDATE, PROOF)
        j.finish('exit')
        self.assertEqual(j.charged, 600000)

    def test_unclosed_restart(self):
        j = Journal(self.path, PROGRAMME)
        j.reserve(100, CANDIDATE, PROOF)
        j.close()
        j = self.journal()
        with self.assertRaisesRegex(RuntimeError, 'unclosed'):
            j.reserve(100, CANDIDATE, PROOF)

    def test_truncation_and_wrong_programme(self):
        with self.assertRaises(RuntimeError):
            Journal(self.path, 'd' * 64)
        with self.path.open('ab') as output:
            output.write(b'{')
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            Journal(self.path, PROGRAMME)

    def test_fsync_failure_does_not_spawn(self):
        j = self.journal()
        with patch('scripts.attended_journal.os.fsync', side_effect=OSError),                 patch('scripts.attended_supervisor.subprocess.Popen') as spawn:
            with self.assertRaises(OSError):
                supervise(j, CANDIDATE, PROOF, 100, 0)
            spawn.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, 'uncertain'):
            j.reserve(1, CANDIDATE, PROOF)

    def test_exact_proof_bytes_and_candidate(self):
        p = Path(self.temp.name) / 'proof'
        p.write_text(json.dumps({'schema': 1, 'candidate': CANDIDATE,
                                'profile': 'offline-fixed-child-v1',
                                'native_admission': False, 'provider_calls': 0}))
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(bind_proof(p, digest, CANDIDATE), digest)
        for sha, candidate in [(PROOF, CANDIDATE), (digest, 'd' * 40)]:
            with self.assertRaises(ValueError):
                bind_proof(p, sha, candidate)

    def run_case(self, mode):
        j = self.journal()
        reader, writer = os.pipe()
        try:
            if mode == 'stop':
                os.write(writer, b'STOP')
            if mode == 'controller_eof':
                os.close(writer)
                writer = None
            result = supervise(j, CANDIDATE, PROOF, 50, reader)
            self.assertEqual(result['outcome'], mode)
            self.assertTrue(result['child_terminal'])
            self.assertFalse(result['native_admission'])
            self.assertIsNone(j.active)
            self.assertEqual(j.charged, 50)
        finally:
            os.close(reader)
            if writer is not None:
                os.close(writer)

    def test_real_owned_child_deadline(self):
        self.run_case('deadline')

    def test_real_owned_child_stop(self):
        self.run_case('stop')

    def test_real_owned_child_controller_eof(self):
        self.run_case('controller_eof')

    def test_unknown_cleanup_stays_reserved(self):
        j = self.journal()
        reader, writer = os.pipe()
        try:
            os.write(writer, b'STOP')
            with patch('scripts.attended_supervisor.subprocess.Popen') as spawn:
                spawn.return_value.poll.return_value = None
                spawn.return_value.wait.side_effect = subprocess.TimeoutExpired('owned', 1)
                result = supervise(j, CANDIDATE, PROOF, 100, reader)
                spawn.return_value.kill.assert_called_once()
                self.assertFalse(result['child_terminal'])
                self.assertIsNotNone(j.active)
        finally:
            os.close(reader)
            os.close(writer)

    def test_spawn_error_cleanup(self):
        j = self.journal()
        reader, writer = os.pipe()
        try:
            with patch('scripts.attended_supervisor.subprocess.Popen', side_effect=OSError):
                with self.assertRaises(OSError):
                    supervise(j, CANDIDATE, PROOF, 100, reader)
            self.assertIsNone(j.active)
            self.assertEqual(j.charged, 100)
        finally:
            os.close(reader)
            os.close(writer)

    def test_separate_supervisor_eof(self):
        proof = Path(self.temp.name) / 'proof'
        proof.write_text(json.dumps({'schema': 1, 'candidate': CANDIDATE,
                                    'profile': 'offline-fixed-child-v1',
                                    'native_admission': False, 'provider_calls': 0}))
        digest = hashlib.sha256(proof.read_bytes()).hexdigest()
        command = [sys.executable, '-m', 'scripts.attended_supervisor',
                   '--journal', str(self.path), '--programme', PROGRAMME,
                   '--candidate', CANDIDATE, '--proof', str(proof),
                   '--proof-sha256', digest, '--milliseconds', '500']
        run = subprocess.run(command, input=b'', capture_output=True, timeout=3)
        self.assertEqual(run.returncode, 0, run.stderr)
        receipt = json.loads(run.stdout)
        self.assertEqual(receipt['outcome'], 'controller_eof')
        self.assertFalse(receipt['native_admission'])
        self.assertEqual(receipt['provider_calls'], 0)
        self.assertIsNone(self.journal().active)

    def test_separate_process_concurrent_denial(self):
        self.journal()
        code = ('import sys; from scripts.attended_journal import Journal; '
                'Journal(sys.argv[1],sys.argv[2])')
        run = subprocess.run([sys.executable, '-c', code, str(self.path), PROGRAMME],
                             capture_output=True, timeout=3)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn(b'BlockingIOError', run.stderr)

    def test_real_process_crash_leaves_reservation(self):
        code = ('import os,sys; from scripts.attended_journal import Journal; '
                'j=Journal(sys.argv[1],sys.argv[2]); '
                'j.reserve(100,sys.argv[3],sys.argv[4]); os._exit(7)')
        run = subprocess.run([sys.executable, '-c', code, str(self.path), PROGRAMME,
                              CANDIDATE, PROOF], capture_output=True, timeout=3)
        self.assertEqual(run.returncode, 7)
        j = self.journal()
        with self.assertRaises(RuntimeError):
            j.reserve(1, CANDIDATE, PROOF)


if __name__ == '__main__':
    unittest.main()
