"""Hosted-macOS-only noaudio budget suite. No physical capture authority.
Run as a module from the reviewed checkout; caller verifies exact signed images.
"""
from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from native.caption_helper.qualify_budget import BoundedLines, validate_budget_terminal
from scripts.attended_acceptance import hex_id
from scripts.attended_helper_budget import Custody
from scripts.attended_journal import Journal

SCENARIOS = ('valid', 'wrong_challenge', 'replayed_challenge', 'truncated', 'trailing',
             'missing_eof', 'writer_death', 'nonpipe', 'late_response', 'suspend_expiry')
STAGES = ('COMPLETE', 'PLATFORM', 'SETUP', 'SPAWN', 'CHALLENGE', 'DEBIT', 'INJECT',
          'WAIT', 'OUTPUT', 'TERMINAL', 'HOLD', 'CLEANUP')


def row(name, passed=False, stage='SETUP', charged_ms=0):
    return dict(scenario=name, result='PASS' if passed else 'FAIL', stage=stage,
                capture=False, terminal='HOLD', charged_ms=charged_ms)


def validate_receipt(value):
    """Exact content-free projection. Never echo foreign dictionaries."""
    if (type(value) is not dict or set(value) != {'schema', 'qualification', 'capture',
            'terminal', 'result', 'passed', 'failed', 'rows'}
            or type(value['schema']) is not int or value['schema'] != 1
            or value['qualification'] != 'NO_AUDIO_BUDGET_SUITE_ONLY'
            or value['capture'] is not False or value['terminal'] != 'HOLD'
            or type(value['rows']) is not list or len(value['rows']) != len(SCENARIOS)):
        return None
    projected = []
    for name, item in zip(SCENARIOS, value['rows']):
        if (type(item) is not dict or set(item) != {'scenario', 'result', 'stage',
                'capture', 'terminal', 'charged_ms'} or item['scenario'] != name
                or item['result'] not in ('PASS', 'FAIL') or item['stage'] not in STAGES
                or item['capture'] is not False or item['terminal'] != 'HOLD'
                or type(item['charged_ms']) is not int or item['charged_ms'] not in (0, 2000)
                or (item['result'] == 'PASS' and
                    (item['stage'] != 'COMPLETE' or item['charged_ms'] != 2000))
                or (item['result'] == 'FAIL' and item['stage'] == 'COMPLETE')):
            return None
        projected.append(row(name, item['result'] == 'PASS', item['stage'], item['charged_ms']))
    passed = sum(item['result'] == 'PASS' for item in projected)
    if (type(value['passed']) is not int or value['passed'] != passed
            or type(value['failed']) is not int or value['failed'] != len(SCENARIOS)-passed
            or value['result'] != ('PASS' if passed == len(SCENARIOS) else 'FAIL')):
        return None
    return dict(schema=1, qualification='NO_AUDIO_BUDGET_SUITE_ONLY', capture=False,
                terminal='HOLD', result=value['result'], passed=passed,
                failed=len(SCENARIOS)-passed, rows=projected)


def parse_receipt(raw):
    """Bounded JSON decoder for CI consumers; duplicate keys are invalid."""
    if type(raw) is not bytes or len(raw) > 4096:
        return None
    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate_key')
            value[key] = item
        return value
    try:
        return validate_receipt(json.loads(raw, object_pairs_hook=unique))
    except (ValueError, TypeError, RecursionError):
        return None


def receipt(rows):
    passed = sum(item['result'] == 'PASS' for item in rows)
    value = dict(schema=1, qualification='NO_AUDIO_BUDGET_SUITE_ONLY', capture=False,
                 terminal='HOLD', result='PASS' if passed == len(SCENARIOS) else 'FAIL',
                 passed=passed, failed=len(SCENARIOS)-passed, rows=rows)
    projected = validate_receipt(value)
    if projected is None:
        raise RuntimeError('invalid_internal_projection')
    return projected


def drain(child, reader):
    """Bound EOF even if a descendant unexpectedly retained stdout."""
    chunks = [reader.pending]
    total = reader.total
    with selectors.DefaultSelector() as selector:
        selector.register(child.stdout, selectors.EVENT_READ)
        while True:
            remaining = reader.deadline-time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise TimeoutError('eof')
            chunk = os.read(child.stdout.fileno(), 512)
            total += len(chunk)
            if total > 4096:
                raise RuntimeError('output_limit')
            if not chunk:
                return b''.join(chunks)
            chunks.append(chunk)


def attempt(root, name, previous=None):
    """Fresh DISPOSABLE qualification ledger, never an actual programme ledger.

    Internal challenge is returned only in memory to exercise replay; it is never
    included in the public receipt. No journal finish/refund occurs on any path.
    """
    result = row(name)
    challenge = None
    child = custody = journal = peer = capability = channel = None
    stopped = False
    temporary = None
    try:
        temporary = tempfile.TemporaryDirectory(prefix='cb-noaudio-qualification-')
        path = Path(temporary.name) / 'qualification-only.journal'
        programme = os.urandom(32).hex()
        Journal.initialize(path, programme)
        journal = Journal(path, programme)
        custody = Custody(journal)
        capability, channel, peer = custody.session('b' * 40)
        result['stage'] = 'SPAWN'
        child = subprocess.Popen([str(root / 'NoAudioController'), '--noaudio-budget', str(root)],
            stdin=subprocess.DEVNULL if name == 'nonpipe' else subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            close_fds=True, env={}, bufsize=0)
        reader = BoundedLines(child.stdout, time.monotonic()+7)
        result['stage'] = 'CHALLENGE'
        event = None if name == 'nonpipe' else reader.line()
        result['stage'] = 'DEBIT'
        offered = custody.offer(capability, channel, 2000)
        if event is None:
            custody.prepare_launch(capability, channel, offered)
            wire = b''
        else:
            _, wire = custody.prepare_noaudio_budget(capability, channel, offered, event)
            challenge = event['challenge']
        result['charged_ms'] = journal.charged
        result['stage'] = 'INJECT'
        if name == 'wrong_challenge':
            wire = wire[:8] + bytes([wire[8] ^ 1]) + wire[9:]
        elif name == 'replayed_challenge':
            if not hex_id(previous, 64) or previous == challenge:
                raise RuntimeError('replay_setup')
            wire = wire[:8] + bytes.fromhex(previous) + wire[40:]
        elif name == 'truncated':
            wire = wire[:-1]
        elif name == 'trailing':
            wire += b'X'
        elif name == 'writer_death':
            wire = b''
        if name == 'suspend_expiry':
            os.kill(child.pid, signal.SIGSTOP)  # direct owned controller only
            stopped = True
            stop_deadline = time.monotonic()+.5
            while True:
                observed, status = os.waitpid(child.pid, os.WUNTRACED | os.WNOHANG)
                if observed:
                    if not os.WIFSTOPPED(status):
                        raise RuntimeError('controller_not_stopped')
                    break
                if time.monotonic() >= stop_deadline:
                    raise TimeoutError('controller_stop')
                time.sleep(.005)
        if name == 'late_response':
            time.sleep(2.2)
        if name != 'nonpipe':
            try:
                if wire and child.stdin.write(wire) != len(wire):
                    raise RuntimeError('short_write')
            except BrokenPipeError:
                if name != 'late_response':
                    raise
            if name != 'missing_eof':
                child.stdin.close()
        if name == 'suspend_expiry':
            time.sleep(2.2)
            os.kill(child.pid, signal.SIGCONT)
            stopped = False
        result['stage'] = 'WAIT'
        if name == 'valid':
            started, terminal = reader.line(), reader.line()
        code = child.wait(timeout=max(.001, reader.deadline-time.monotonic()))
        result['stage'] = 'OUTPUT'
        extra = drain(child, reader)
        if extra:
            raise RuntimeError('unexpected_output')
        result['stage'] = 'TERMINAL'
        if name == 'valid':
            validate_budget_terminal(started, terminal, code)
        elif code != 70:
            raise RuntimeError('expected_rejection')
        result['stage'] = 'HOLD'
        if journal.charged != 2000 or journal.active is None or journal.poisoned:
            raise RuntimeError('debit_hold')
        # Direct controller is reaped before this qualification-only reopen. Check
        # actual persisted debit and restart rejection, never refund or reset.
        journal.close()
        journal = Journal(path, programme)
        if journal.charged != 2000 or journal.active is None:
            raise RuntimeError('persisted_hold')
        try:
            Custody(journal)
        except RuntimeError as error:
            if error.args != ('custody_unclosed',):
                raise
        else:
            raise RuntimeError('restart_bypass')
        result.update(result='PASS', stage='COMPLETE')
    except Exception:
        # Do not stringify exceptions: paths, argv, stderr and journal contents
        # are not permitted receipt fields.
        result['result'] = 'FAIL'
    finally:
        try:
            if child is not None:
                try:
                    if child.poll() is None:
                        child.kill()  # SIGKILL also retires a stopped owned process
                    child.wait(timeout=2)
                finally:
                    try:
                        if child.stdin is not None:
                            child.stdin.close()
                    finally:
                        child.stdout.close()
        except Exception:
            result.update(result='FAIL', stage='CLEANUP')
        if journal is not None:
            result['charged_ms'] = 2000 if journal.charged == 2000 else 0
        actions = []
        if custody is not None and capability is not None:
            actions.append(lambda: custody.revoke(capability))
        if channel is not None:
            actions.append(channel.close)
        if peer is not None:
            actions.append(peer.close)
        if journal is not None:
            actions.append(journal.close)
        if temporary is not None:
            actions.append(temporary.cleanup)
        for action in actions:
            try:
                action()
            except Exception:
                result.update(result='FAIL', stage='CLEANUP')
    return result, challenge


def run(root):
    if sys.platform != 'darwin' or os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        return receipt([row(name, stage='PLATFORM') for name in SCENARIOS])
    try:
        root = Path(root).resolve(strict=True)
        if not (root / 'NoAudioController').is_file():
            raise ValueError('controller')
    except Exception:
        return receipt([row(name) for name in SCENARIOS])
    rows, previous = [], None
    for name in SCENARIOS:
        result, challenge = attempt(root, name, previous)
        rows.append(result)
        if name == 'valid':
            previous = challenge
    return receipt(rows)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        value = run(argv[0]) if len(argv) == 1 else receipt([row(name) for name in SCENARIOS])
    except Exception:
        value = receipt([row(name) for name in SCENARIOS])
    print(json.dumps(value, separators=(',', ':'), sort_keys=True))
    return 0 if value['result'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
