"""Independent POSIX watchdog. Fixed harmless child only, NEVER native admission."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path

from scripts.attended_acceptance import hex_id
from scripts.attended_journal import Journal

CHILD = 'import time; time.sleep(2)'  # No network/devices; finite orphan survival.


def bind_proof(path, digest, candidate):
    if not hex_id(digest, 64) or not hex_id(candidate, 40):
        raise ValueError('proof_identity')
    with Path(path).open('rb') as source:
        raw = source.read(4097)
    if len(raw) > 4096 or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('proof_digest')
    proof = json.loads(raw)
    if (not isinstance(proof, dict)
            or type(proof.get('schema')) is not int
            or type(proof.get('provider_calls')) is not int
            or proof.get('native_admission') is not False
            or proof != {'schema': 1, 'candidate': candidate,
                         'profile': 'offline-fixed-child-v1',
                         'native_admission': False, 'provider_calls': 0}):
        raise ValueError('proof_binding')
    return digest


def supervise(journal, candidate, proof, ms, controller_fd):
    if type(ms) is not int or not 1 <= ms <= 1000:
        raise ValueError('offline_duration')
    journal.reserve(ms, candidate, proof)
    child = None
    outcome = 'error'
    terminal = False
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + ms / 1000
    try:
        selector.register(controller_fd, selectors.EVENT_READ)
        child = subprocess.Popen(
            [sys.executable, '-I', '-S', '-c', CHILD], env={}, close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        while True:
            if child.poll() is not None:
                outcome = 'exit' if child.returncode == 0 else 'error'
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                outcome = 'deadline'
                break
            if selector.select(min(remaining, 0.02)):
                outcome = 'stop' if os.read(controller_fd, 16) else 'controller_eof'
                break
    finally:
        selector.close()
        if child is None:
            terminal = True
        else:
            if child.poll() is None:
                child.kill()
            try:
                child.wait(timeout=1)
                terminal = True
            except subprocess.TimeoutExpired:
                terminal = False
        if terminal:
            journal.finish(outcome)
    return {'outcome': outcome, 'child_terminal': terminal, 'native_admission': False,
            'provider_calls': 0, 'reserved_ms': ms}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--programme', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--proof', type=Path, required=True)
    parser.add_argument('--proof-sha256', required=True)
    parser.add_argument('--milliseconds', type=int, default=100)
    args = parser.parse_args()
    journal = None
    try:
        digest = bind_proof(args.proof, args.proof_sha256, args.candidate)
        journal = Journal(args.journal, args.programme)
        result = supervise(journal, args.candidate, digest, args.milliseconds, sys.stdin.fileno())
        print(json.dumps(result))
        return 0 if result['child_terminal'] and result['outcome'] != 'error' else 1
    except Exception:
        print(json.dumps({'error': 'offline_supervisor_failed', 'native_admission': False}))
        return 1
    finally:
        if journal is not None:
            journal.close()


if __name__ == '__main__':
    raise SystemExit(main())
