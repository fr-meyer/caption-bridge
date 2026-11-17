"""Deterministic fixtures. All subprocesses/signals/native observations mocked."""
import io
import json
import pathlib
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest.mock import MagicMock, patch

from native.caption_helper import newqualifysuite as s

EVENT = dict(event='noaudio_budget_ready', challenge='ab' * 32, ceiling_ms=2000)
START = dict(event='started', pids=[101, 102, 103])
TERMINAL = dict(schema=6, noaudio_exit=0, terminal='HOLD', pids=[101, 102, 103],
    wait_status=[72 << 8, 72 << 8, 71 << 8], failure_stage='NONE', failure_role=0,
    failure_code=0, cleanup_killed=[0, 0, 0])


def passing():
    return s.receipt([s.row(name, True, 'COMPLETE', 2000) for name in s.SCENARIOS])


class ProjectionTests(unittest.TestCase):
    def test_roundtrip_and_fresh_projection(self):
        value = passing()
        result = s.validate_receipt(json.loads(json.dumps(value)))
        self.assertEqual(result, value)
        self.assertIsNot(result['rows'], value['rows'])

    def test_bounded_decoder_rejects_duplicates_and_foreign_data(self):
        raw = json.dumps(passing()).encode()
        self.assertLess(len(raw), 4096)
        self.assertEqual(s.parse_receipt(raw), passing())
        for bad in (b'x', b'x' * 4097, raw.decode(), b'{"schema":1,"schema":1}',
                    b'\xff', b'[' * 1000):
            with self.subTest(kind=type(bad)):
                self.assertIsNone(s.parse_receipt(bad))
        duplicate = raw.replace(b'"schema": 1', b'"schema": 1,"schema": 1')
        self.assertIsNone(s.parse_receipt(duplicate))

    def test_top_level_negatives(self):
        changes = [dict(secret='PRIVATE'), dict(schema=True), dict(capture=True),
                   dict(terminal='CLOSED'), dict(passed=True), dict(failed=1),
                   dict(result='FAIL'), dict(qualification='OPERATIONAL'), dict(rows=[])]
        for change in changes:
            value = passing()
            value.update(change)
            with self.subTest(change=change):
                self.assertIsNone(s.validate_receipt(value))

    def test_row_negatives_and_order(self):
        changes = [dict(secret='PRIVATE'), dict(scenario='UNKNOWN'), dict(result='SKIP'),
                   dict(stage='PRIVATE'), dict(capture=True), dict(terminal='CLOSED'),
                   dict(charged_ms=True), dict(charged_ms=1), dict(charged_ms=0),
                   dict(stage='TERMINAL')]
        for change in changes:
            value = passing()
            value['rows'][0].update(change)
            with self.subTest(change=change):
                self.assertIsNone(s.validate_receipt(value))
        value = passing()
        value['rows'].reverse()
        self.assertIsNone(s.validate_receipt(value))

    def test_failed_rows_cannot_claim_complete(self):
        value = passing()
        value.update(result='FAIL', passed=9, failed=1)
        value['rows'][0]['result'] = 'FAIL'
        self.assertIsNone(s.validate_receipt(value))
        value['rows'][0]['stage'] = 'TERMINAL'
        self.assertIsNotNone(s.validate_receipt(value))

    def test_nonhosted_never_launches(self):
        with patch.object(s.sys, 'platform', 'linux'), patch.object(s, 'attempt') as launch:
            value = s.run('/PRIVATE')
        launch.assert_not_called()
        self.assertEqual(value['failed'], 10)
        self.assertEqual({r['stage'] for r in value['rows']}, {'PLATFORM'})
        self.assertNotIn('PRIVATE', json.dumps(value))

    def test_cli_one_json_failure_no_error_content(self):
        stream = io.StringIO()
        with patch.object(s, 'run', side_effect=RuntimeError('PRIVATE argv stderr')), redirect_stdout(stream):
            code = s.main(['/PRIVATE'])
        self.assertEqual(code, 1)
        self.assertEqual(len(stream.getvalue().splitlines()), 1)
        self.assertIsNotNone(s.validate_receipt(json.loads(stream.getvalue())))
        self.assertNotIn('PRIVATE', stream.getvalue())

    def test_cli_success(self):
        stream = io.StringIO()
        with patch.object(s, 'run', return_value=passing()), redirect_stdout(stream):
            self.assertEqual(s.main(['unused']), 0)

    def test_suite_order_and_live_replay_not_output(self):
        with tempfile.TemporaryDirectory() as root:
            (pathlib.Path(root)/'NoAudioController').write_text('not executed')
            def fake_attempt(root, name, previous):
                if name == 'replayed_challenge':
                    self.assertEqual(previous, EVENT['challenge'])
                return s.row(name, True, 'COMPLETE', 2000), EVENT['challenge']
            with patch.object(s.sys, 'platform', 'darwin'), \
                 patch.dict(s.os.environ, GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted'), \
                 patch.object(s, 'attempt', side_effect=fake_attempt) as attempt:
                value = s.run(root)
        self.assertEqual([call.args[1] for call in attempt.call_args_list], list(s.SCENARIOS))
        self.assertEqual(value['result'], 'PASS')
        self.assertNotIn(EVENT['challenge'], json.dumps(value))


class OutputBoundsTests(unittest.TestCase):
    def test_drain_eof_and_pending_projection(self):
        reader = MagicMock(pending=b'prefix', total=6)
        reader.deadline = s.time.monotonic()+1
        selector = MagicMock()
        selector.__enter__.return_value.select.return_value = [object()]
        with patch.object(s.selectors, 'DefaultSelector', return_value=selector), \
             patch.object(s.os, 'read', side_effect=[b'suffix', b'']):
            self.assertEqual(s.drain(MagicMock(), reader), b'prefixsuffix')

    def test_drain_caps_output_and_wait(self):
        reader = MagicMock(pending=b'', total=4096)
        reader.deadline = s.time.monotonic()+1
        selector = MagicMock()
        selector.__enter__.return_value.select.return_value = [object()]
        with patch.object(s.selectors, 'DefaultSelector', return_value=selector), \
             patch.object(s.os, 'read', return_value=b'x'):
            with self.assertRaises(RuntimeError):
                s.drain(MagicMock(), reader)
        selector.__enter__.return_value.select.return_value = []
        with patch.object(s.selectors, 'DefaultSelector', return_value=selector):
            with self.assertRaises(TimeoutError):
                s.drain(MagicMock(), reader)


class AttemptFixtures(unittest.TestCase):
    def run_attempt(self, name, *, output=b'', code=None, write_error=False,
                    challenge=EVENT, cleanup_error=False):
        child = MagicMock()
        child.pid = 3001
        child.poll.return_value = 0
        child.wait.return_value = (0 if name == 'valid' else 70) if code is None else code
        if cleanup_error:
            child.stdout.close.side_effect = OSError('PRIVATE cleanup')
        if name == 'nonpipe':
            child.stdin = None
        elif write_error:
            child.stdin.write.side_effect = BrokenPipeError('PRIVATE pipe')
        else:
            child.stdin.write.side_effect = len
        reader = MagicMock()
        reader.deadline = s.time.monotonic()+7
        reader.line.side_effect = [challenge, START, TERMINAL]
        with ExitStack() as stack:
            spawn = stack.enter_context(patch.object(s.subprocess, 'Popen', return_value=child))
            stack.enter_context(patch.object(s, 'BoundedLines', return_value=reader))
            stack.enter_context(patch.object(s, 'drain', return_value=output))
            sleep = stack.enter_context(patch.object(s.time, 'sleep'))
            kill = stack.enter_context(patch.object(s.os, 'kill'))
            stopped = stack.enter_context(patch.object(s.os, 'waitpid', return_value=(3001, (s.signal.SIGSTOP << 8) | 0x7f)))
            result, nonce = s.attempt(pathlib.Path('/not-executed'), name, 'cd' * 32)
        self.assertTrue(child.stdout.close.called)
        if child.stdin is not None:
            self.assertTrue(child.stdin.close.called)
        self.assertTrue(child.wait.called)
        return result, child, nonce, spawn, sleep, kill, stopped

    def test_all_scenarios_and_exact_injections(self):
        for name in s.SCENARIOS:
            with self.subTest(name=name):
                result, child, _, spawn, sleep, kill, stopped = self.run_attempt(name)
                self.assertEqual(result, s.row(name, True, 'COMPLETE', 2000))
                self.assertTrue(spawn.call_args.kwargs['close_fds'])
                self.assertEqual(spawn.call_args.kwargs['env'], {})
                if name == 'nonpipe':
                    self.assertEqual(spawn.call_args.kwargs['stdin'], s.subprocess.DEVNULL)
                elif name == 'writer_death':
                    child.stdin.write.assert_not_called()
                else:
                    wire = child.stdin.write.call_args.args[0]
                    self.assertEqual(len(wire), 55 if name == 'truncated' else 57 if name == 'trailing' else 56)
                    if name == 'wrong_challenge':
                        self.assertNotEqual(wire[8:40], bytes.fromhex(EVENT['challenge']))
                    elif name == 'replayed_challenge':
                        self.assertEqual(wire[8:40], bytes.fromhex('cd' * 32))
                if name in ('late_response', 'suspend_expiry'):
                    sleep.assert_any_call(2.2)
                if name == 'suspend_expiry':
                    stopped.assert_called_once()
                    self.assertEqual([c.args for c in kill.call_args_list],
                        [(3001, s.signal.SIGSTOP), (3001, s.signal.SIGCONT)])
                else:
                    kill.assert_not_called()

    def test_native_unexpected_output_never_passes_or_leaks(self):
        result, *_ = self.run_attempt('wrong_challenge', output=b'PRIVATE')
        self.assertEqual(result['result'], 'FAIL')
        self.assertEqual(result['stage'], 'OUTPUT')
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_wrong_native_exit_fails(self):
        result, *_ = self.run_attempt('truncated', code=0)
        self.assertEqual(result['result'], 'FAIL')
        self.assertEqual(result['stage'], 'TERMINAL')

    def test_late_epipe_allowed_but_ordinary_epipe_not_allowed(self):
        late, *_ = self.run_attempt('late_response', write_error=True)
        ordinary, *_ = self.run_attempt('trailing', write_error=True)
        self.assertEqual(late['result'], 'PASS')
        self.assertEqual(ordinary['result'], 'FAIL')

    def test_cleanup_error_overrides_success(self):
        result, *_ = self.run_attempt('valid', cleanup_error=True)
        self.assertEqual(result['stage'], 'CLEANUP')
        self.assertEqual(result['result'], 'FAIL')

    def test_malformed_challenge_has_no_debit(self):
        result, *_ = self.run_attempt('valid', challenge=dict(EVENT, secret='PRIVATE'))
        self.assertEqual(result['charged_ms'], 0)
        self.assertEqual(result['result'], 'FAIL')
        self.assertNotIn('PRIVATE', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
