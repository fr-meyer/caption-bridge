"""Provider-free bounded native launcher. Importing never opens audio.

Physical launch has NO CLI, defaults or UI enable flag. It requires exact reviewed
external evidence and a one-use explicit runtime permit. Hosted qualification uses
only --capture-noinput-budget, a separate wire domain and a disposable ledger.
All attempts retain debit/HOLD; independent physical closure review owns release.
"""
from __future__ import annotations

import os
import selectors
import subprocess
import sys
import threading
import time
from pathlib import Path

from native.caption_helper.capture_diagnostics import CaptureDiagnostics
from native.caption_helper.qualify_assembly import validate_startup
from native.caption_helper.qualify_budget import BoundedLines
from scripts.attended_native_admission import MIN_CAPTURE_MS, CaptureAdmission
from scripts.attended_native_clock import continuous_ns


class EmergencyStop:
    """Owned private pipe; close-only terminal stop, no resume/restart operation.

    Keep this object in the independent coordinator, not a websocket/worker. Parent
    exit closes the writer too. Native controller also monitors parent and deadline.
    """
    def __init__(self):
        self.reader, self._writer = os.pipe()  # Python creates non-inheritable ends.
        os.set_inheritable(self.reader, False)
        os.set_inheritable(self._writer, False)
        self._pid = os.getpid()
        self._lock = threading.Lock()

    def stop(self):
        with self._lock:
            if self._writer is not None:
                os.close(self._writer)
                self._writer = None

    def close(self):
        self.stop()
        with self._lock:
            if self.reader is not None:
                os.close(self.reader)
                self.reader = None

    def ready(self):
        if os.getpid() != self._pid or self.reader is None or self._writer is None:
            raise RuntimeError('emergency_stop_not_live')
        return self.reader


def _terminal(started, terminal, code, *, no_input):
    keys = {'schema', 'capture_exit', 'capture', 'terminal', 'pids', 'wait_status', 'cleanup_killed'}
    if (type(terminal) is not dict or set(terminal) != keys
            or type(terminal['schema']) is not int or terminal['schema'] != 1
            or type(terminal['capture']) is not bool or terminal['capture'] is no_input
            or type(terminal['capture_exit']) is not int
            or type(code) is not int or terminal['capture_exit'] != code or code != 0
            or terminal['terminal'] != 'HOLD' or terminal['pids'] != started['pids']
            or type(terminal['pids']) is not list
            or any(type(pid) is not int for pid in terminal['pids'])
            or type(terminal['cleanup_killed']) is not list
            or len(terminal['cleanup_killed']) != 3
            or any(type(value) is not int or value != 0 for value in terminal['cleanup_killed'])
            or type(terminal['wait_status']) is not list or len(terminal['wait_status']) != 3):
        raise RuntimeError('capture_terminal_unknown_hold')
    for index, status in enumerate(terminal['wait_status']):
        if (type(status) is not int or status < 0 or not os.WIFEXITED(status)
                or os.WEXITSTATUS(status) not in ((71, 72) if index == 2 else (72,))):
            raise RuntimeError('capture_termination_unknown_hold')
    return terminal


def capture_valid_until(challenge, expires_unix_ns, milliseconds, valid_until_continuous_ns=None):
    """Conservative anchor-before-wall mapping, fixed BEFORE durable debit.

    Native anchor precedes challenge publication and this wall measurement. Adding
    only the wall-remaining validity to that earlier native anchor cannot refresh
    validity after scheduling/fsync. Native takes min(anchor+debit, this absolute
    deadline); subsequent wall rollback/sleep cannot extend the pinned deadline.
    """
    required = {'event', 'challenge', 'ceiling_ms', 'anchor_continuous_ticks',
                'timebase_numer', 'timebase_denom'}
    if (type(challenge) is not dict or set(challenge) != required
            or type(challenge['anchor_continuous_ticks']) is not int
            or not 0 < challenge['anchor_continuous_ticks'] < 2**64
            or any(type(challenge[k]) is not int or not 0 < challenge[k] < 2**32
                   for k in ('timebase_numer', 'timebase_denom'))):
        raise RuntimeError('capture_native_clock_challenge')
    ns = milliseconds * 1_000_000
    if expires_unix_ns is not None:
        if type(expires_unix_ns) is not int:
            raise RuntimeError('runtime_expiry_required')
        if type(valid_until_continuous_ns) is not int:
            raise RuntimeError('runtime_continuous_validity_required')
        remaining = min(expires_unix_ns - time.time_ns(), valid_until_continuous_ns - continuous_ns() - 1)
        if remaining < ns:
            raise RuntimeError('runtime_validity_too_short')
        ns = remaining
    deadline = challenge['anchor_continuous_ticks'] + ns * challenge['timebase_denom'] // challenge['timebase_numer']
    if not 0 < deadline < 2**64:
        raise RuntimeError('capture_native_deadline_overflow')
    return deadline


def _run(root, custody, candidate, milliseconds, emergency, *, no_input, device_id=0,
         check_grant=None, pcm=None, expires_unix_ns=None, expected_tail=None, valid_until_continuous_ns=None,
         _diagnostics=None):
    diagnostics = _diagnostics if _diagnostics is not None else CaptureDiagnostics()
    if type(diagnostics) is not CaptureDiagnostics:
        raise ValueError("capture_diagnostics_type")
    if sys.platform != 'darwin':
        raise RuntimeError('macos_native_only')
    if type(milliseconds) is not int or not MIN_CAPTURE_MS <= milliseconds <= 2000:
        raise ValueError('native_capture_duration')
    if type(no_input) is not bool or (no_input and device_id != 0):
        raise ValueError('native_capture_mode')
    if type(emergency) is not EmergencyStop:
        raise RuntimeError('owned_emergency_stop_required')
    if pcm is not None and (no_input or len(pcm) != 3):
        raise ValueError('native_pcm_mode')
    pcm_owned = list(pcm[:2]) if pcm is not None else []
    child = None
    capability = peer = None
    try:
        stop_fd = emergency.ready()
        root = Path(root).resolve(strict=True)
        capability, channel, peer = custody.session(candidate)
        arguments = [str(root / 'CaptureController'),
                     '--capture-noinput-budget' if no_input else '--capture-budget', str(root)]
        if not no_input:
            arguments.append(str(device_id))
        arguments.append(str(stop_fd))
        if pcm is not None:
            arguments[1] = '--capture-pcm-budget'
            arguments.extend((str(pcm[0]), str(pcm[1]), pcm[2]))
        if check_grant is not None:
            check_grant()
        diagnostics.stage = "spawn"
        child = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, close_fds=True, pass_fds=(stop_fd, *pcm_owned),
                                 env={}, bufsize=0)
        for fd in pcm_owned:
            os.close(fd)
        pcm_owned.clear()
        reader = BoundedLines(child.stdout, time.monotonic() + 7)
        diagnostics.stage = "challenge"
        challenge = reader.line()
        emergency.ready()
        if check_grant is not None:
            check_grant()
        if expected_tail is not None and custody._journal.tail != expected_tail:
            raise RuntimeError('runtime_ledger_changed')
        valid_until = capture_valid_until(challenge, expires_unix_ns, milliseconds, valid_until_continuous_ns)
        diagnostics.stage = "debit"
        receipt = custody.offer(capability, channel, milliseconds)
        reservation, wire = (custody.prepare_pcm_budget(capability, channel, receipt, challenge, valid_until_ticks=valid_until, expires_unix_ns=expires_unix_ns or 0)
                             if pcm is not None else custody.prepare_capture_budget(
                                 capability, channel, receipt, challenge, no_input=no_input, valid_until_ticks=valid_until, expires_unix_ns=expires_unix_ns or 0))
        # fsync/debit can cross expiry. Revalidate immediately before delivery;
        # failure retains the durable debit/HOLD and sends NO native budget.
        custody.launch_remaining_ns(capability, channel, reservation)
        if check_grant is not None:
            check_grant()
        if expires_unix_ns is not None and (time.time_ns() >= expires_unix_ns or continuous_ns() >= valid_until_continuous_ns):
            raise RuntimeError('runtime_grant_expired_after_debit_hold')
        diagnostics.stage = "budget_delivery"
        if child.stdin.write(wire) != len(wire):
            raise RuntimeError('capture_budget_short_write_hold')
        child.stdin.close()  # Exact message + EOF; fsync/debit precedes any native opener.
        diagnostics.stage = "startup"
        diagnostics.startup = reader.line()
        started = validate_startup(diagnostics.startup)
        if started is None:
            raise RuntimeError('capture_startup_unknown_hold')
        diagnostics.stage = "terminal_read"
        terminal = reader.line()
        diagnostics.terminal = terminal
        remaining = reader.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('capture_terminal_timeout_hold')
        diagnostics.stage = "controller_wait"
        code = child.wait(timeout=remaining)
        diagnostics.returncode = code
        diagnostics.stage = "eof"
        if reader.pending:
            raise RuntimeError('capture_trailing_output_hold')
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            remaining = reader.deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise TimeoutError('capture_eof_timeout_hold')
            if os.read(child.stdout.fileno(), 1):
                raise RuntimeError('capture_trailing_output_hold')
        diagnostics.stage = "terminal_validate"
        terminal = _terminal(started, terminal, code, no_input=no_input)
        diagnostics.stage = "complete"
        return dict(qualification='NATIVE_CAPTURE_NOINPUT_ONLY' if no_input else 'PHYSICAL_ATTEMPT',
                    physical_acceptance=False, native_admission=False, terminal=terminal,
                    sequence=reservation.sequence, reserved_ms=reservation.reserved_ms)
    finally:
        # Never signal reported role PIDs. Native owns them; Python owns this child.
        emergency.stop()
        diagnostics.cleanup["emergency_closed"] = True
        for fd in pcm_owned:
            os.close(fd)
        try:
            if child is not None:
                polled = child.poll()
                if polled is None:
                    try:
                        diagnostics.returncode = child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        diagnostics.cleanup["kill_sent"] = True
                        diagnostics.returncode = child.wait(timeout=3)
                else:
                    diagnostics.returncode = polled
                diagnostics.cleanup["wait_completed"] = True
                for stream in (child.stdin, child.stdout):
                    if stream is not None:
                        stream.close()
                diagnostics.cleanup["streams_closed"] = True
        finally:
            if peer is not None:
                peer.close()
                diagnostics.cleanup["peer_closed"] = True
            if capability is not None:
                custody.revoke(capability)
                diagnostics.cleanup["custody_revoked"] = True


def launch_capture(admission, permit, custody, emergency):
    """Explicit runtime only; NEVER called by qualification or application defaults.

    Source availability is not source review approval or physical acceptance.
    No provider, PCM egress, route modification or audible path is implemented.
    """
    if sys.platform != 'darwin':
        raise RuntimeError('macos_native_only')
    if type(admission) is not CaptureAdmission:
        raise RuntimeError('exact_review_authority_required')
    from scripts.attended_helper_budget import admit_helper
    launch = admit_helper(admission=admission, permit=permit, custody=custody)

    def check_grant():
        admission._verify_images()
        if time.time_ns() >= launch['expires_unix_ns'] or continuous_ns() >= launch['valid_until_continuous_ns']:
            raise RuntimeError('runtime_grant_expired_or_ledger_changed')

    return _run(launch['root'], custody, launch['candidate'], launch['milliseconds'], emergency,
                no_input=False, device_id=launch['device_id'], check_grant=check_grant,
                expires_unix_ns=launch['expires_unix_ns'], expected_tail=launch['ledger_tail'], valid_until_continuous_ns=launch['valid_until_continuous_ns'])


def qualify_noinput(root, custody, candidate, *, milliseconds=2000, _diagnostics=None):
    """Caller-reviewed fixed image, software ledger only. No physical path/permit.

    Do not pass a real programme ledger: even this deliberately retains HOLD.
    """
    emergency = EmergencyStop()
    try:
        return _run(root, custody, candidate, milliseconds, emergency, no_input=True,
                    _diagnostics=_diagnostics)
    finally:
        emergency.close()


def launch_pcm(launch, admission, custody, emergency, pcm_fd, finish_fd):
    """Internal already-consumed PCM permit handoff; no stdout PCM or file path.

    Caller owns the read end and emergency controller; this function takes sole
    ownership of both passed descriptors, including every launch-failure path.
    The retained journal debit stays HOLD even on a clean framing/terminal result.
    """
    from scripts.attended_pcm_admission import PcmAdmission
    handed_off = False
    try:
        if type(admission) is not PcmAdmission:
            raise RuntimeError('native_pcm_not_admitted')
        def check_grant():
            admission.base._verify_images()
            if (time.time_ns() >= min(launch['expires_unix_ns'], launch['pcm_expires_unix_ns'])
                    or continuous_ns() >= launch['valid_until_continuous_ns']):
                raise RuntimeError('runtime_grant_expired_or_ledger_changed')
        check_grant()
        if sys.platform != 'darwin' or type(emergency) is not EmergencyStop:
            raise RuntimeError('macos_native_only_or_emergency_missing')
        emergency.ready()
        if type(launch['milliseconds']) is not int or not MIN_CAPTURE_MS <= launch['milliseconds'] <= 2000:
            raise ValueError('native_capture_duration')
        Path(launch['root']).resolve(strict=True)
        handed_off = True
        return _run(launch['root'], custody, launch['candidate'], launch['milliseconds'], emergency,
                    no_input=False, device_id=launch['device_id'], check_grant=check_grant,
                    pcm=(pcm_fd, finish_fd, launch['epoch']),
                    expires_unix_ns=min(launch['expires_unix_ns'], launch['pcm_expires_unix_ns']),
                    expected_tail=launch['ledger_tail'], valid_until_continuous_ns=launch['valid_until_continuous_ns'])
    finally:
        if not handed_off:
            os.close(pcm_fd)
            os.close(finish_fd)
