"""Explicit noaudio qualification driver, never an operational admission adapter.

No CLI or import-time execution. Caller owns the locked programme Journal and must
arrange later authorized hosted-macOS qualification. All debits remain HOLD even
when this noaudio protocol succeeds. No JSON or helper exit releases a debit.
"""
from __future__ import annotations

import json
import os
import selectors
import subprocess
import time
from pathlib import Path

from native.caption_helper.qualify_assembly import validate_startup, validate_terminal


class BoundedLines:
    """Nonblocking bounded reader, partial lines cannot bypass the deadline."""
    def __init__(self, stream, deadline):
        self.stream = stream
        self.deadline = deadline
        self.pending = b''
        self.total = 0

    def line(self):
        with selectors.DefaultSelector() as selector:
            selector.register(self.stream, selectors.EVENT_READ)
            while True:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('noaudio_budget_timeout')
                if b'\n' in self.pending:
                    row, self.pending = self.pending.split(b'\n', 1)
                    return json.loads(row)
                if not selector.select(remaining):
                    raise TimeoutError('noaudio_budget_timeout')
                chunk = os.read(self.stream.fileno(), 512)
                self.total += len(chunk)
                if self.total > 4096:
                    raise RuntimeError('noaudio_budget_output_limit')
                if not chunk:
                    raise RuntimeError('noaudio_budget_eof')
                self.pending += chunk


def validate_budget_terminal(started, terminal, returncode):
    """Qualification consistency only, not independent physical closure proof."""
    started = validate_startup(started)
    terminal = validate_terminal(terminal)
    if (started is None or terminal is None or returncode != 0
            or terminal['pids'] != started['pids']
            or terminal['noaudio_exit'] != 0 or terminal['failure_stage'] != 'NONE'
            or terminal['failure_role'] != 0 or terminal['failure_code'] != 0
            or terminal['cleanup_killed'] != [0, 0, 0]):
        raise RuntimeError('noaudio_budget_terminal')
    for role, status in enumerate(terminal['wait_status']):
        if not os.WIFEXITED(status) or os.WEXITSTATUS(status) not in ((71, 72) if role == 2 else (72,)):
            raise RuntimeError('noaudio_budget_wait_status')
    return terminal


def qualify(root, custody, candidate, *, milliseconds=2000):
    """Run only the fixed noaudio controller, after caller's exact-image review.

    This driver adds no trust root. Existing native strict disk/live role pins and
    suspended spawn are still enforced inside the controller. Caller must qualify
    its own controller image before invoking this harness; image selection here is
    NOT capture authority. Controller's stdin is the sole inherited budget reader.
    No other descriptor is passed. A new session/challenge is required per attempt.
    """
    if type(milliseconds) is not int or not 1 <= milliseconds <= 2000:
        raise ValueError('noaudio_budget_duration')
    root = Path(root).resolve(strict=True)
    capability, channel, peer = custody.session(candidate)
    child = None
    try:
        child = subprocess.Popen([str(root / 'NoAudioController'), '--noaudio-budget', str(root)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, close_fds=True, env={}, bufsize=0)
        reader = BoundedLines(child.stdout, time.monotonic() + 7)
        challenge = reader.line()
        receipt = custody.offer(capability, channel, milliseconds)
        reservation, wire = custody.prepare_noaudio_budget(capability, channel, receipt, challenge)
        # 56 bytes fit the minimum PIPE_BUF. Short write is failure, never retry a
        # partially committed message through a fresh controller/session.
        if child.stdin.write(wire) != len(wire):
            raise RuntimeError('noaudio_budget_short_write')
        child.stdin.close()  # native requires EOF and rejects trailing data
        started = validate_startup(reader.line())
        if started is None:
            raise RuntimeError('noaudio_budget_startup')
        terminal = reader.line()
        remaining = reader.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('noaudio_budget_timeout')
        code = child.wait(timeout=remaining)
        if reader.pending:
            raise RuntimeError('noaudio_budget_trailing_output')
        # Even after controller exit, a malformed inherited writer must not hang.
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            remaining = reader.deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise TimeoutError('noaudio_budget_eof_timeout')
            if os.read(child.stdout.fileno(), 1):
                raise RuntimeError('noaudio_budget_trailing_output')
        terminal = validate_budget_terminal(started, terminal, code)
        return {'qualification': 'NO_AUDIO_BUDGET_ONLY', 'native_admission': False,
                'sequence': reservation.sequence, 'reserved_ms': reservation.reserved_ms,
                'terminal': terminal}
    finally:
        # Reap only our direct owned controller. Never signal reported child PIDs:
        # on failure descendants rely on their independent parent/deadline monitors.
        # Their closure is UNKNOWN here, and the Journal retains the debit/hold.
        try:
            if child is not None:
                try:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=2)
                finally:
                    try:
                        if child.stdin is not None:
                            child.stdin.close()
                    finally:
                        if child.stdout is not None:
                            child.stdout.close()
        finally:
            custody.revoke(capability)
            peer.close()
