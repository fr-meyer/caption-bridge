"""Source and mocked-driver tests only. Never runs a native executable."""
import copy
import pathlib
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

from native.caption_helper import qualify_budget as q
from scripts.attended_helper_budget import Custody, admit_helper
from scripts.attended_journal import Journal

ROOT = pathlib.Path(__file__).resolve().parents[1]
EVENT = dict(event='noaudio_budget_ready', challenge='ab' * 32, ceiling_ms=2000)
START = dict(event='started', pids=[101, 102, 103])
TERMINAL = dict(schema=6, noaudio_exit=0, terminal='HOLD', pids=[101, 102, 103],
                wait_status=[72 << 8, 72 << 8, 71 << 8], failure_stage='NONE',
                failure_role=0, failure_code=0, cleanup_killed=[0, 0, 0])


class BudgetWireTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / 'ledger'
        Journal.initialize(self.path, 'a' * 64)
        self.journal = Journal(self.path, 'a' * 64)
        self.custody = Custody(self.journal)
        self.cap, self.channel, self.peer = self.custody.session('b' * 40)

    def tearDown(self):
        self.custody.revoke(self.cap)
        self.peer.close()
        self.journal.close()
        self.tmp.cleanup()

    def reply(self, event=EVENT, milliseconds=2000):
        receipt = self.custody.offer(self.cap, self.channel, milliseconds)
        return self.custody.prepare_noaudio_budget(self.cap, self.channel, receipt, event)

    def test_exact_fixed_wire_after_fsync(self):
        lease, wire = self.reply()
        self.assertEqual(len(wire), 56)
        self.assertEqual(wire[:8], b'CBNA0001')
        self.assertEqual(wire[8:40], bytes.fromhex(EVENT['challenge']))
        self.assertEqual(int.from_bytes(wire[40:48], 'big'), 2_000_000_000)
        self.assertEqual(int.from_bytes(wire[48:], 'big'), lease.sequence)
        self.assertEqual(self.journal.active['ms'], 2000)
        self.assertFalse(lease.native_admission)
        with self.assertRaises(RuntimeError):
            admit_helper(wire)

    def test_invalid_challenges_do_not_debit(self):
        cases = [None, {}, dict(EVENT, extra=True), dict(EVENT, ceiling_ms=True),
                 dict(EVENT, challenge='AB' * 32), dict(EVENT, challenge='x'),
                 dict(EVENT, event='started'), dict(EVENT, ceiling_ms=600000)]
        for event in cases:
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.reply(event)
            self.assertIsNone(self.journal.active)

    def test_oversize_duration_keeps_debit_hold(self):
        with self.assertRaisesRegex(RuntimeError, 'limit_hold'):
            self.reply(milliseconds=2001)
        self.assertEqual(self.journal.charged, 2001)
        self.assertIsNotNone(self.journal.active)

    def test_durable_failure_emits_no_wire(self):
        with patch.object(self.journal, 'reserve', side_effect=OSError('fsync_failed')):
            with self.assertRaises(OSError):
                self.reply()
        self.assertFalse(self.custody._launches)

    def run_driver(self, *, write_count=56, events=None, fail_wait=False):
        child = MagicMock()
        def write(wire):
            # This check executes at the exact external-send boundary, after fsync.
            self.assertIsNotNone(self.journal.active)
            self.assertEqual(self.journal.active['ms'], 2000)
            return write_count
        child.stdin.write.side_effect = write
        child.poll.return_value = None if write_count != 56 else 0
        child.wait.return_value = 0
        if fail_wait:
            child.wait.side_effect = TimeoutError('wait')
        reader = MagicMock()
        reader.deadline = q.time.monotonic() + 7
        reader.pending = b''
        reader.line.side_effect = events or [EVENT, START, TERMINAL]
        selector = MagicMock()
        selector.__enter__.return_value.select.return_value = [object()]
        fake_os = types.SimpleNamespace(read=lambda *a: b'', WIFEXITED=q.os.WIFEXITED,
                                       WEXITSTATUS=q.os.WEXITSTATUS)
        with patch.object(q.subprocess, 'Popen', return_value=child) as spawn, \
             patch.object(q, 'BoundedLines', return_value=reader), \
             patch.object(q.selectors, 'DefaultSelector', return_value=selector), \
             patch.object(q, 'os', fake_os):
            try:
                return q.qualify(self.tmp.name, self.custody, 'b' * 40), child, spawn
            finally:
                self.assertTrue(child.stdin.close.called)
                self.assertTrue(child.stdout.close.called)
                self.assertTrue(child.wait.called)

    def test_driver_uses_fixed_private_pipes_and_retains_hold(self):
        result, child, spawn = self.run_driver()
        args, kwargs = spawn.call_args
        self.assertEqual(args[0][1], '--noaudio-budget')
        self.assertEqual(kwargs['env'], {})
        self.assertTrue(kwargs['close_fds'])
        self.assertEqual(kwargs['stdin'], q.subprocess.PIPE)
        self.assertNotIn('pass_fds', kwargs)
        self.assertFalse(result['native_admission'])
        self.assertEqual(result['qualification'], 'NO_AUDIO_BUDGET_ONLY')
        self.assertIsNotNone(self.journal.active)
        child.kill.assert_not_called()

    def test_short_write_preserves_hold_and_reaps_controller(self):
        with self.assertRaisesRegex(RuntimeError, 'short_write'):
            self.run_driver(write_count=55)
        self.assertIsNotNone(self.journal.active)
        self.assertEqual(len(self.custody._sessions), 1)  # only setUp's session

    def test_early_terminal_not_startup_does_not_release(self):
        with self.assertRaisesRegex(RuntimeError, 'startup'):
            self.run_driver(events=[EVENT, TERMINAL])
        self.assertIsNotNone(self.journal.active)

    def test_wait_failure_retains_hold(self):
        with self.assertRaises(TimeoutError):
            self.run_driver(fail_wait=True)
        self.assertIsNotNone(self.journal.active)

    def test_no_driver_spawn_on_invalid_duration(self):
        with patch.object(q.subprocess, 'Popen') as spawn:
            with self.assertRaises(ValueError):
                q.qualify(self.tmp.name, self.custody, 'b' * 40, milliseconds=True)
            spawn.assert_not_called()


class BoundedReaderTests(unittest.TestCase):
    def reader(self, chunks, *, ready=True):
        stream = MagicMock()
        reader = q.BoundedLines(stream, q.time.monotonic() + 1)
        selector = MagicMock()
        selector.__enter__.return_value.select.return_value = [object()] if ready else []
        return reader, selector, types.SimpleNamespace(read=MagicMock(side_effect=chunks))

    def test_fragmented_line_and_coalesced_next_line(self):
        reader, selector, fake_os = self.reader([b'{"a":', b'1}\n{"b":2}\n'])
        with patch.object(q.selectors, 'DefaultSelector', return_value=selector), patch.object(q, 'os', fake_os):
            self.assertEqual(reader.line(), {'a': 1})
            self.assertEqual(reader.line(), {'b': 2})
        self.assertEqual(fake_os.read.call_count, 2)

    def test_partial_eof_rejected(self):
        reader, selector, fake_os = self.reader([b'{', b''])
        with patch.object(q.selectors, 'DefaultSelector', return_value=selector), patch.object(q, 'os', fake_os):
            with self.assertRaisesRegex(RuntimeError, 'eof'):
                reader.line()

    def test_partial_stall_rejected(self):
        reader, selector, fake_os = self.reader([], ready=False)
        reader.pending = b'{'
        with patch.object(q.selectors, 'DefaultSelector', return_value=selector), patch.object(q, 'os', fake_os):
            with self.assertRaises(TimeoutError):
                reader.line()
        fake_os.read.assert_not_called()

    def test_oversized_output_rejected(self):
        reader, selector, fake_os = self.reader([b'x' * 512] * 9)
        with patch.object(q.selectors, 'DefaultSelector', return_value=selector), patch.object(q, 'os', fake_os):
            with self.assertRaisesRegex(RuntimeError, 'output_limit'):
                reader.line()

    def test_expired_clock_even_with_buffered_line_rejected(self):
        reader, selector, fake_os = self.reader([])
        reader.pending = b'{}\n'
        reader.deadline = 0
        with patch.object(q.selectors, 'DefaultSelector', return_value=selector), patch.object(q, 'os', fake_os):
            with self.assertRaises(TimeoutError):
                reader.line()


class NativeBudgetSourceTests(unittest.TestCase):
    def test_anchor_before_publication_and_spawn(self):
        header = (ROOT / 'native/caption_helper/budget.h').read_text()
        assembly = (ROOT / 'native/caption_helper/assembly.c').read_text()
        self.assertLess(header.index('anchor=mach_continuous_time()'), header.index('if(printf('))
        self.assertIn('*deadline=anchor+ticks;', header)
        self.assertLess(assembly.index('cb_budget_deadline(&end,tb)'), assembly.index('if(pipe(lifelines[i]))'))
        self.assertIn('i+1,end)', assembly)
        self.assertIn(',3,end)', assembly)

    def test_strict_native_wire_and_closure_contract(self):
        source = (ROOT / 'native/caption_helper/budget.h').read_text()
        for invariant in ('#define CB_BUDGET_BYTES 56', '#define CB_BUDGET_FD 0',
                          'S_ISFIFO(st.st_mode)', 'O_NONBLOCK', 'FD_CLOEXEC',
                          'memcmp(wire,"CBNA0001",8)', 'memcmp(wire+8,challenge,32)',
                          'ns>CB_BUDGET_NS', 'received>CB_BUDGET_BYTES',
                          'count==0', 'if(close(fd)<0)ok=0', 'anchor>UINT64_MAX-ticks'):
            self.assertIn(invariant, source)
        self.assertIn('mach_continuous_time()>=*deadline', source)
        admission = (ROOT / 'native/caption_helper/input_state.h').read_text()
        self.assertIn('cb_capture_admitted(void) { return false; }', admission)

    def test_terminal_fixtures_are_only_consistency_not_admission(self):
        self.assertEqual(q.validate_budget_terminal(START, TERMINAL, 0), TERMINAL)
        for change in (dict(pids=[201, 202, 203]), dict(cleanup_killed=[1, 0, 0]),
                       dict(wait_status=[0, 72 << 8, 71 << 8]), dict(terminal='CLOSED'),
                       dict(failure_stage='OWNED_REAP')):
            value = copy.deepcopy(TERMINAL)
            value.update(change)
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                q.validate_budget_terminal(START, value, 0)
        with self.assertRaises(RuntimeError):
            q.validate_budget_terminal(START, TERMINAL, -9)


if __name__ == '__main__':
    unittest.main()
