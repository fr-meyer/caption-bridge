"""Content-free source fault injection; no native execution or device access."""
import ast
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from native.caption_helper import owned_resources
from native.caption_helper.owned_resources import OwnedResources

ROOT = Path(__file__).resolve().parents[1] / 'native' / 'caption_helper'


@unittest.skipUnless(os.name == 'posix', 'qualification ownership uses POSIX roles')
class CleanupTests(unittest.TestCase):
    def inject(self, parent, fault):
        target = ROOT / ('qualify_parent_death.py' if parent else 'qualify_supervision.py')
        name = 'scenario_parent_death' if parent else 'scenario'
        tree = ast.parse(target.read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == name)
        child = Mock(pid=200)
        child.poll.return_value = None
        child.wait.return_value = 71
        child.kill = Mock()
        fake_os = SimpleNamespace(
            pipe=Mock(side_effect=[(10, 11), (12, 13), (14, 15)]),
            set_inheritable=Mock(), close=Mock(), fork=Mock(side_effect=[100, 101, 102]),
            WNOHANG=os.WNOHANG, waitpid=Mock(side_effect=lambda pid, flags: (pid, 0)),
            kill=Mock(), _exit=Mock())
        fake_process = SimpleNamespace(Popen=Mock(return_value=child),
            run=Mock(return_value=SimpleNamespace(stderr='CDHash=abc\n')),
            TimeoutExpired=subprocess.TimeoutExpired)
        stamp = Mock(return_value={'exit': 0, 'stdout': 'cdhash=abc', 'stderr': ''})
        fake_time = SimpleNamespace(monotonic=time.monotonic, sleep=Mock())
        context = {'os': fake_os, 'signal': signal, 'subprocess': fake_process,
                   'time': fake_time, 'OwnedResources': OwnedResources, 'ROWS': [],
                   'LIB': SimpleNamespace(mach_continuous_time=lambda: 1),
                   'tb': SimpleNamespace(numer=1, denom=1),
                   'IMAGE': Path('/synthetic-image'), 'stamp': stamp}
        context['scope'] = {key: context[key] for key in ('LIB', 'tb', 'IMAGE', 'stamp')}
        if fault == 'identity_reject':
            stamp.return_value['exit'] = 66
        elif fault == 'identity_timeout':
            stamp.side_effect = subprocess.TimeoutExpired('inspector', 2)
        elif fault == 'missing_cdhash':
            fake_process.run.return_value.stderr = ''
        elif fault == 'spawn_failure':
            fake_process.Popen.side_effect = OSError('injected spawn failure')
        elif fault == 'second_fork':
            fake_os.fork.side_effect = [100, OSError('injected fork failure')]
        elif fault == 'partial_pipe':
            fake_os.pipe.side_effect = [(10, 11), OSError('injected pipe failure')]
        elif fault == 'inheritability':
            fake_os.set_inheritable.side_effect = OSError('injected descriptor failure')
        elif fault == 'resume_failure':
            def kill(pid, sig):
                if pid == child.pid and sig == signal.SIGCONT:
                    raise RuntimeError('injected resume failure')
            fake_os.kill.side_effect = kill
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(target), 'exec'),
             context)
        with patch.object(owned_resources, 'os', fake_os), \
                patch.object(owned_resources, 'subprocess', fake_process):
            with self.assertRaises((AssertionError, OSError, StopIteration,
                                    subprocess.TimeoutExpired, RuntimeError)):
                if parent:
                    context[name]()
                else:
                    context[name]('suspend_past_deadline' if fault == 'resume_failure'
                                  else 'absolute_deadline')
        expected_roles = (0 if fault in ('partial_pipe', 'inheritability') else
                          1 if fault == 'second_fork' else 3 if parent else 2)
        self.assertEqual(fake_os.waitpid.call_count, expected_roles)
        for pid in (100, 101, 102)[:expected_roles]:
            fake_os.kill.assert_any_call(pid, signal.SIGKILL)
        expected_fds = (10, 11) if fault in ('partial_pipe', 'inheritability') else range(10, 16)
        closed = [call.args[0] for call in fake_os.close.call_args_list]
        self.assertCountEqual(closed, expected_fds)
        spawned = fault not in ('spawn_failure', 'second_fork', 'partial_pipe', 'inheritability')
        self.assertEqual(child.kill.call_count, int(spawned))
        self.assertEqual(child.wait.call_count, int(spawned))
        if spawned:
            child.wait.assert_called_once_with(timeout=1)

    def test_matrix_inspection_and_spawn_failure_cleanup(self):
        for fault in ('identity_reject', 'identity_timeout', 'missing_cdhash',
                      'spawn_failure', 'second_fork', 'partial_pipe', 'inheritability',
                      'resume_failure'):
            with self.subTest(fault=fault):
                self.inject(False, fault)

    def test_controller_role_inspection_and_spawn_failure_cleanup(self):
        for fault in ('identity_reject', 'identity_timeout', 'missing_cdhash',
                      'spawn_failure', 'second_fork', 'partial_pipe', 'inheritability'):
            with self.subTest(fault=fault):
                self.inject(True, fault)

    def test_actual_owned_process_and_fd_reaped_after_failure(self):
        child = None
        pair = ()
        try:
            with self.assertRaisesRegex(RuntimeError, 'injected identity failure'):
                with OwnedResources() as owned:
                    pair = owned.pipe()
                    child = owned.spawn([sys.executable, '-c',
                                         'import time; time.sleep(30)'])
                    raise RuntimeError('injected identity failure')
            self.assertIsNotNone(child.returncode)
            with self.assertRaises(ChildProcessError):
                os.waitpid(child.pid, os.WNOHANG)
            for fd in pair:
                with self.assertRaises(OSError):
                    os.fstat(fd)
        finally:
            if child is not None and child.poll() is None:
                child.kill()
                child.wait(timeout=1)

    def test_cleanup_failure_does_not_skip_other_owned_roles(self):
        owner = OwnedResources()
        owner.own_role(10)
        owner.own_role(11)
        fake_os = SimpleNamespace(kill=Mock(side_effect=[PermissionError(), None]),
                                  waitpid=Mock(return_value=(11, 0)), WNOHANG=os.WNOHANG)
        with patch.object(owned_resources, 'os', fake_os):
            with self.assertRaisesRegex(RuntimeError, 'cleanup unverified'):
                owner.__exit__(None, None, None)
        fake_os.kill.assert_any_call(11, signal.SIGKILL)
        fake_os.waitpid.assert_called_once_with(11, os.WNOHANG)


if __name__ == '__main__':
    unittest.main()
