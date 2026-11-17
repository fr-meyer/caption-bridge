"""Controller-role death only; outer harness owns and reaps every child."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from owned_resources import OwnedResources

# Reuse Mac definitions, but never execute the prior matrix driver.
scope = {}
exec(Path('qualify_supervision.py').read_text().split(
    "for mode in ('controller_capability_close'")[0], scope)


def scenario_parent_death():
    with OwnedResources() as owned:
        pipes = [owned.pipe() for _ in range(3)]
        roles = []
        for index in (0, 1, 2):
            pid = os.fork()
            if pid == 0:
                try:
                    for i, (rd, wr) in enumerate(pipes):
                        os.close(rd)
                        if i != index:
                            os.close(wr)
                    time.sleep(3)
                finally:
                    os._exit(0)
            roles.append(owned.own_role(pid))
        controller, *guardians = roles
        deadline = (scope['LIB'].mach_continuous_time()
                    + 2_000_000_000 * scope['tb'].denom // scope['tb'].numer)
        child = owned.spawn([str(scope['IMAGE']), '--probe-supervised', str(deadline)],
                            stdin=pipes[0][0], stdout=pipes[1][0], stderr=pipes[2][0],
                            close_fds=True)
        for rd, wr in pipes:
            owned.close(rd)
            owned.close(wr)
        identity = scope['stamp'](child.pid)
        expected = subprocess.run(['/usr/bin/codesign', '-dv', '--verbose=4',
                                   str(scope['IMAGE'])], capture_output=True, text=True,
                                  timeout=2).stderr
        cdhash = next(line.split('=', 1)[1] for line in expected.splitlines()
                      if line.startswith('CDHash='))
        assert identity['exit'] == 0 and 'cdhash=' + cdhash in identity['stdout'], identity
        start = time.monotonic()
        os.kill(controller, signal.SIGKILL)
        result = child.wait(timeout=2)
    checks = []
    for pid in [child.pid, controller] + guardians:
        try:
            os.kill(pid, 0)
            outcome = 'EXISTS'
        except ProcessLookupError:
            outcome = 'ESRCH'
        checks.append(dict(pid=pid, result=outcome))
    row = dict(probe='sole_controller_process_death', exit=result, identity=identity,
               expected_cdhash=cdhash, elapsed_seconds=time.monotonic()-start,
               pid_checks=checks,
               semantics='controller role is a dedicated capability holder, not helper parent')
    assert result == 71 and all(check['result'] == 'ESRCH' for check in checks)
    return row


if __name__ == '__main__':
    receipt = scenario_parent_death()
    with Path('parent-death.json').open('x') as output:
        json.dump(receipt, output, indent=2)
    print(json.dumps(receipt, indent=2))
