"""Mac-only harmless direct-child custody proof, never capture authority."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

LIB = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
LIB.mach_continuous_time.restype = ctypes.c_uint64
class Timebase(ctypes.Structure):
    _fields_ = [('numer', ctypes.c_uint32), ('denom', ctypes.c_uint32)]
tb = Timebase()
assert LIB.mach_timebase_info(ctypes.byref(tb)) == 0
IMAGE = Path('build/CaptionHelper.app/Contents/MacOS/CaptionHelper').resolve()
IDENTITY = Path('identity').resolve()
ROWS = []

def stamp(pid):
    r = subprocess.run([str(IDENTITY), str(pid), str(IMAGE)], capture_output=True, text=True,
                       timeout=2)
    return dict(exit=r.returncode, stdout=r.stdout, stderr=r.stderr)

def scenario(mode):
    # Three pipes created before fork. Only the assigned role retains each writer.
    pipes = [os.pipe() for _ in range(3)]
    for pair in pipes:
        for fd in pair:
            os.set_inheritable(fd, False)
    guardians = []
    for index in (1, 2):
        pid = os.fork()
        if pid == 0:
            for i, (rd, wr) in enumerate(pipes):
                os.close(rd)
                if i != index:
                    os.close(wr)
            # No children, no descriptor duplication. Bounded emergency self-exit.
            time.sleep(4)
            os._exit(0)
        guardians.append(pid)
    deadline = LIB.mach_continuous_time() + 500_000_000 * tb.denom // tb.numer
    child = subprocess.Popen([str(IMAGE), '--probe-supervised', str(deadline)],
                             stdin=pipes[0][0], stdout=pipes[1][0], stderr=pipes[2][0],
                             close_fds=True)
    for rd, _ in pipes:
        os.close(rd)
    for _, wr in pipes[1:]:
        os.close(wr)
    # Direct child remains owned/unreaped. PID cannot recycle while it is our child.
    identity = stamp(child.pid)
    expected = subprocess.run(['/usr/bin/codesign', '-dv', '--verbose=4', str(IMAGE)],
                              capture_output=True, text=True, timeout=2).stderr
    cdhash = next(x.split('=', 1)[1] for x in expected.splitlines() if x.startswith('CDHash='))
    assert identity['exit'] == 0 and 'cdhash=' + cdhash in identity['stdout'], identity
    before = time.monotonic()
    if mode == 'controller_capability_close':
        os.close(pipes[0][1])
    elif mode in ('guardian_a_death', 'guardian_b_death'):
        os.kill(guardians[0 if mode == 'guardian_a_death' else 1], signal.SIGKILL)
    elif mode == 'suspend_past_deadline':
        os.kill(child.pid, signal.SIGSTOP)
        time.sleep(.7)
        os.kill(child.pid, signal.SIGCONT)
    try:
        result = child.wait(timeout=2)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        if mode != 'controller_capability_close':
            os.close(pipes[0][1])
        for pid in guardians:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
    checks = []
    for pid in [child.pid] + guardians:
        try:
            os.kill(pid, 0)
            outcome = 'EXISTS'
        except ProcessLookupError:
            outcome = 'ESRCH'
        checks.append(dict(pid=pid, result=outcome))
    row = dict(mode=mode, helper_pid=child.pid, guardian_pids=guardians, identity=identity,
               expected_cdhash=cdhash, deadline_ticks=deadline, exit=result,
               elapsed_seconds=time.monotonic()-before, pid_checks=checks)
    ROWS.append(row)
    assert result == (71 if mode in ('controller_capability_close', 'guardian_a_death',
                                    'guardian_b_death') else 72), row
    assert all(x['result'] == 'ESRCH' for x in checks)

for mode in ('controller_capability_close', 'guardian_a_death', 'guardian_b_death',
             'absolute_deadline', 'suspend_past_deadline'):
    scenario(mode)
receipt = dict(schema=2, image_sha256=hashlib.sha256(IMAGE.read_bytes()).hexdigest(),
               timebase=dict(numer=tb.numer, denom=tb.denom), rows=ROWS,
               authority='NO_AUDIO_QUALIFICATION_ONLY',
               residuals=['controller process death not yet exercised',
                          'guardian code identity not authenticated',
                          'identity interrogation not atomic exec prevention'])
Path('supervision.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt, indent=2))
