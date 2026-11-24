"""Real POSIX wait/group/reap observations; NOT native/HAL/root-cause proof.

Three directly owned software children exit 72 behind a private pipe barrier.
No signal is sent after any target is reaped. No native executable/device opens.
"""
import json
import os
import signal
import time


def main():
    if not all(hasattr(os, name) for name in ('fork', 'waitid', 'WNOWAIT')):
        print(json.dumps(dict(status='UNAVAILABLE', native_capture_executed=False)))
        return 77
    read_fd, write_fd = os.pipe()
    retained, group = [], None
    try:
        for _ in range(3):
            pid = os.fork()
            if pid == 0:
                try:
                    os.close(write_fd)
                    os.setpgid(0, 0 if group is None else group)
                    token = os.read(read_fd, 1)
                    os.close(read_fd)
                    os._exit(72 if token == b'X' else 99)
                except BaseException:
                    os._exit(99)
            retained.append(pid)
            if group is None:
                group = pid
            os.setpgid(pid, group)
        os.close(read_fd)
        read_fd = None
        assert os.write(write_fd, b'XXX') == 3
        os.close(write_fd)
        write_fd = None
        statuses = {}
        limit = time.monotonic() + 2
        while len(statuses) != 3 and time.monotonic() < limit:
            for pid in retained:
                if pid in statuses:
                    continue
                info = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if info is not None:
                    assert info.si_pid == pid and info.si_code == os.CLD_EXITED
                    statuses[pid] = info.si_status
            time.sleep(0.001)
        assert len(statuses) == 3 and list(statuses.values()) == [72] * 3
        # Same observable group-signal predicate as C, with leader STILL retained.
        assert group == retained[0]
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        reaped = []
        for pid in list(retained):
            owner, status = os.waitpid(pid, 0)
            assert owner == pid
            retained.remove(pid)
            reaped.append(status)
        assert reaped == [72 << 8] * 3
        print(json.dumps(dict(status='MECHANISM_OBSERVED_NOT_NATIVE',
              native_capture_executed=False, hosted_root_cause_reproduced=False,
              observed_exit_codes=list(statuses.values()), reaped_wait_status=reaped,
              group_signal_accepted_while_custody_retained=True, all_owned_reaped=not retained)))
        return 0
    finally:
        for fd in (read_fd, write_fd):
            if fd is not None:
                os.close(fd)
        for pid in retained:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)


if __name__ == '__main__':
    raise SystemExit(main())
