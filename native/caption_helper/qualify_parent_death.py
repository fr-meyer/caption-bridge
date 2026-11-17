"""Controller death closes its sole capability; outer harness owns/reaps all children."""
import os
import signal
import subprocess
import time
import json
from pathlib import Path
# Reuse definitions only, not the prior matrix driver.
scope = {}
exec(Path('qualify_supervision.py').read_text().split("for mode in ('controller_capability_close'")[0], scope)
pipes = [os.pipe() for _ in range(3)]
controller = os.fork()
if controller == 0:
    for i, (rd, wr) in enumerate(pipes):
        os.close(rd)
        if i != 0:
            os.close(wr)
    time.sleep(3)
    os._exit(0)
guardians = []
for index in (1, 2):
    pid = os.fork()
    if pid == 0:
        for i, (rd, wr) in enumerate(pipes):
            os.close(rd)
            if i != index:
                os.close(wr)
        time.sleep(3)
        os._exit(0)
    guardians.append(pid)
deadline = scope['LIB'].mach_continuous_time() + 2_000_000_000 * scope['tb'].denom // scope['tb'].numer
child = subprocess.Popen([str(scope['IMAGE']), '--probe-supervised', str(deadline)],
                         stdin=pipes[0][0], stdout=pipes[1][0], stderr=pipes[2][0], close_fds=True)
for rd, wr in pipes:
    os.close(rd)
    os.close(wr)
identity = scope['stamp'](child.pid)
start = time.monotonic()
os.kill(controller, signal.SIGKILL)
try:
    result = child.wait(timeout=2)
finally:
    if child.poll() is None:
        child.kill()
        child.wait()
    os.waitpid(controller, 0)
    for pid in guardians:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
checks = []
for pid in [child.pid, controller] + guardians:
    try:
        os.kill(pid, 0)
        outcome = 'EXISTS'
    except ProcessLookupError:
        outcome = 'ESRCH'
    checks.append(dict(pid=pid, result=outcome))
r = dict(probe='sole_controller_process_death', exit=result, identity=identity,
         elapsed_seconds=time.monotonic()-start, pid_checks=checks,
         semantics='controller role is a dedicated capability holder, not helper parent')
Path('parent-death.json').write_text(json.dumps(r, indent=2))
print(json.dumps(r, indent=2))
assert result == 71 and identity['exit'] == 0
assert all(x['result'] == 'ESRCH' for x in checks)
