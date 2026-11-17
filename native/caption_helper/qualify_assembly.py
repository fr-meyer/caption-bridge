"""Noaudio only. Parent-death injection proves aggregate closure, not unique cause."""

import hashlib
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

MODES = ("deadline", "guardian_a", "guardian_b", "helper", "suspend", "parent_death")
ERRORS = {
    "AssertionError",
    "TimeoutExpired",
    "JSONDecodeError",
    "RuntimeError",
    "CalledProcessError",
    "OSError",
}


def valid_pids(value, partial=False):
    return (
        isinstance(value, list)
        and len(value) == 3
        and all(type(p) is int and (p > 1 or (partial and p == -1)) for p in value)
    )


def validate_startup(value):
    if (
        isinstance(value, dict)
        and set(value) == {"event", "pids"}
        and value["event"] == "started"
        and valid_pids(value["pids"])
        and len(set(value["pids"])) == 3
    ):
        return value
    return None


def validate_terminal(value):
    keys = {"schema", "noaudio_exit", "terminal", "pids", "wait_status"}
    if not isinstance(value, dict) or set(value) != keys:
        return None
    if (
        type(value["schema"]) is not int
        or value["schema"] != 5
        or type(value["noaudio_exit"]) is not int
        or value["terminal"] != "HOLD"
        or not valid_pids(value["pids"], True)
    ):
        return None
    if (
        not isinstance(value["wait_status"], list)
        or len(value["wait_status"]) != 3
        or not all(type(n) is int and -1 <= n <= 65535 for n in value["wait_status"])
    ):
        return None
    return value


def execute(root_arg, state):
    root = Path(root_arg).resolve()
    receipt = state["receipt"]
    state["stage"] = "signature"
    for name in ("GuardianA", "GuardianB", "SyntheticHelper", "NoAudioController"):
        p = root / name
        subprocess.run(
            ["/usr/bin/codesign", "--verify", "--strict", str(p)],
            check=True,
            timeout=2,
            capture_output=True,
        )
        receipt["images"][name] = hashlib.sha256(p.read_bytes()).hexdigest()
    state["stage"] = "state_matrix"
    subprocess.run([str(root / "StateMatrix")], check=True, timeout=2, capture_output=True)
    state["stage"] = "capture_reject"
    assert (
        subprocess.run(
            [str(root / "NoAudioController"), "--capture"], timeout=2, capture_output=True
        ).returncode
        == 64
    )
    for mode in ("deadline", "guardian_a", "guardian_b", "helper", "suspend", "parent_death"):
        state.update(mode=mode, stage="startup", startup=None, terminal=None, child=None)
        child = subprocess.Popen(
            [str(root / "NoAudioController"), "--noaudio", str(root), mode],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        state["child"] = child
        owned = []
        try:
            selector = selectors.DefaultSelector()
            selector.register(child.stdout, selectors.EVENT_READ)
            try:
                if not selector.select(3):
                    raise RuntimeError("start_timeout")
                first = child.stdout.readline(1024)
            finally:
                selector.close()
            started = json.loads(first)
            early = validate_terminal(started)
            if early is not None:
                state["terminal"] = early
                owned = [p for p in early["pids"] if p > 1]
                raise RuntimeError()
            started = validate_startup(started)
            if started is None:
                raise RuntimeError()
            state["startup"] = started
            owned = started["pids"]
            if mode == "parent_death":
                child.kill()  # only our direct controller; roles must self-close
            state["stage"] = "communicate"
            out, err = child.communicate(timeout=7)
            assert len(out) <= 4096 and len(err) <= 4096
            if mode == "parent_death":
                assert child.returncode == -signal.SIGKILL
                end = time.monotonic() + 3
                pending = set(owned)
                while pending and time.monotonic() < end:
                    for pid in list(pending):
                        try:
                            os.kill(pid, 0)
                        except ProcessLookupError:
                            pending.remove(pid)
                    time.sleep(0.01)
                assert not pending, "OS reaper did not retire descendants"
                row = dict(
                    mode=mode,
                    pids=owned,
                    observation="ESRCH_AFTER_OS_REAPER_PARENT_OR_DEADLINE",
                    controller_wait=child.returncode,
                )
            else:
                terminal = validate_terminal(json.loads(out))
                if terminal is None:
                    raise RuntimeError()
                state["terminal"] = terminal
                state["stage"] = "wait_status"
                assert child.returncode == 0 and terminal["noaudio_exit"] == 0
                assert terminal["terminal"] == "HOLD" and terminal["pids"] == owned
                statuses = terminal["wait_status"]
                for i, status in enumerate(statuses):
                    injected = (
                        (mode == "guardian_a" and i == 0)
                        or (mode == "guardian_b" and i == 1)
                        or (mode == "helper" and i == 2)
                    )
                    if injected:
                        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
                    else:
                        expected = 71 if i == 2 and mode in ("guardian_a", "guardian_b") else 72
                        assert os.WIFEXITED(status) and (
                            os.WEXITSTATUS(status) == expected
                            or (i == 2 and expected == 72 and os.WEXITSTATUS(status) == 71)
                        )
                row = dict(mode=mode, terminal=terminal)
            receipt["rows"].append(row)
            owned = []  # verified retired; never signal a potentially recycled PID
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=2)
            # Grandchildren cannot be safely signalled by stale PID after controller reaping.
            # Roles self-close on parent change/deadline. Observe ESRCH, never claim wait ownership.
            pending = set(owned)
            until = time.monotonic() + 3
            while pending and time.monotonic() < until:
                for pid in list(pending):
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        pending.remove(pid)
                time.sleep(0.01)
            if pending:
                state["stage"] = "retirement"
                raise RuntimeError()


def run(root_arg):
    state = dict(
        receipt=dict(schema=5, qualification="NO_AUDIO_ONLY", images={}, rows=[]),
        mode=None,
        stage="signature",
        startup=None,
        terminal=None,
        child=None,
    )
    try:
        execute(root_arg, state)
        return state["receipt"], 0
    except Exception as error:
        child = state["child"]
        observed = child.returncode if child is not None else None
        name = type(error).__name__
        failure = dict(
            mode=state["mode"],
            stage=state["stage"],
            error_class=(
                "OSError" if isinstance(error, OSError) else name if name in ERRORS else "Other"
            ),
            controller_wait=observed,
            startup=state["startup"],
            terminal=state["terminal"],
        )
        return dict(
            schema=5,
            qualification="NO_AUDIO_ONLY",
            failure=failure,
            images=state["receipt"]["images"],
            rows=state["receipt"]["rows"],
        ), 1


if __name__ == "__main__":
    result, code = run(sys.argv[1] if len(sys.argv) == 2 else "")
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(code)
