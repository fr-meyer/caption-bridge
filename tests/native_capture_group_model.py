"""Linux POSIX mechanism model ONLY. No native build/HAL/physical acceptance.

Isolated subprocess becomes subreaper so every stopped/killed model descendant is
owned and reaped. Numeric stop/kill targets are never reaped before final cleanup.
"""
import ctypes
import json
import os
import select
import signal
import sys
import time


def main(scenario):
    if not sys.platform.startswith("linux"):
        return 77
    if ctypes.CDLL(None).prctl(36, 1, 0, 0, 0):  # PR_SET_CHILD_SUBREAPER
        raise RuntimeError("model_subreaper_required")
    report_read, report_write = os.pipe()
    emergency_read, emergency_write = os.pipe()
    controller = os.fork()
    if controller == 0:
        controller_pid = os.getpid()
        os.close(report_read)
        os.close(emergency_write)
        parent_read, parent_write = os.pipe()
        deadline = time.monotonic() + 0.5
        group = None
        roles = []
        for role in (1, 2, 3):
            pid = os.fork()
            if pid == 0:
                os.close(parent_write)
                os.close(report_write)
                os.setpgid(0, 0 if role == 1 else group)
                if role == 3:
                    while True:
                        signal.pause()  # Synthetic sleeper, NOT audio capture.
                while True:
                    if os.getppid() != controller_pid or time.monotonic() >= deadline:
                        if scenario == "legacy_gap":
                            os._exit(72)  # Frozen guardians only exited/closed.
                        os.kill(0, signal.SIGKILL)
                    readable, _, _ = select.select([parent_read, emergency_read], [], [], 0.005)
                    if readable:
                        os.kill(0, signal.SIGKILL)
            if role == 1:
                group = pid
            os.setpgid(pid, group)
            roles.append(pid)
        os.write(report_write, (json.dumps(dict(group=group, roles=roles)) + "\n").encode())
        os.close(report_write)
        # Retain ALL direct children, especially the group leader, until cleanup.
        if scenario == "controller_owns_stopped_group":
            time.sleep(0.55)
            info = os.waitid(os.P_PID, group, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            assert info is None or info.si_pid == group
            os.killpg(group, signal.SIGKILL)
        while True:
            signal.pause()
    os.close(report_write)
    os.close(emergency_read)
    roles = []
    reaped = []
    try:
        with os.fdopen(report_read, "r") as stream:
            report = json.loads(stream.readline())
        roles = report["roles"]
        # C never reaps; if C dies, subreaper ownership retains the same children.
        os.kill(roles[2], signal.SIGSTOP)
        if scenario == "controller_death":
            os.kill(controller, signal.SIGKILL)
        elif scenario == "controller_owns_stopped_group":
            os.kill(roles[0], signal.SIGSTOP)
            os.kill(roles[1], signal.SIGSTOP)
        else:
            os.kill(controller, signal.SIGSTOP)
            if scenario == "guardian_a_stopped":
                os.kill(roles[0], signal.SIGSTOP)
            if scenario == "guardian_b_stopped":
                os.kill(roles[1], signal.SIGSTOP)
            if scenario == "emergency":
                os.close(emergency_write)
                emergency_write = None
        limit = time.monotonic() + 2
        observed = []
        while time.monotonic() < limit:
            # /proc state reads do NOT signal an unowned numeric PID. Direct
            # controller/subreaper custody prevents PID reuse until final reap.
            observed = []
            for pid in roles:
                try:
                    with open("/proc/%d/stat" % pid) as file:
                        state = file.read().split(") ", 1)[1].split()[0]
                except FileNotFoundError:
                    state = "gone"
                observed.append(state)
            if all(state in ("Z", "gone") for state in observed):
                break
            if scenario == "legacy_gap" and observed[:2] == ["Z", "Z"]:
                break
            time.sleep(0.01)
        if scenario == "legacy_gap":
            assert observed[2] == "T", observed
        else:
            assert all(state in ("Z", "gone") for state in observed), observed
        print(json.dumps(dict(scenario=scenario, synthetic_only=True, closed_states=observed,
                              legacy_gap_survives=scenario == "legacy_gap")))
    finally:
        # Controller is our retained child; adoption then gives us every role.
        try:
            os.kill(controller, signal.SIGKILL)
        except ProcessLookupError:
            pass
        # Wait for adoption WITHOUT reaping C or any role. Every later numeric
        # cleanup kill is then our own retained direct child, not borrowed PID.
        os.waitid(os.P_PID, controller, os.WEXITED | os.WNOWAIT)
        for pid in roles:
            os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        end = time.monotonic() + 2
        while time.monotonic() < end:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid:
                reaped.append(pid)
            else:
                time.sleep(0.005)
        if emergency_write is not None:
            os.close(emergency_write)
        assert set(reaped) == set([controller] + roles), (reaped, roles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
