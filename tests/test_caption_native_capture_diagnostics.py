"""Mocked software observations only: never native/physical qualification."""
import io
import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from native.caption_helper import qualify_capture_noinput as cli
from native.caption_helper.capture_diagnostics import CaptureDiagnostics, validated_terminal
from scripts.attended_helper_budget import Custody
from scripts.attended_journal import Journal
from scripts.attended_native_launch import _terminal, qualify_noinput

PRIVATE = "PRIVATE_AUDIO_TRANSCRIPT_ENV_ARGV_PATH_SECRET"
STARTUP = dict(event="started", pids=[10, 11, 12])


def terminal(**changes):
    return dict(dict(schema=1, capture_exit=0, capture=False, terminal="HOLD",
                     pids=[10, 11, 12], wait_status=[72 << 8] * 3,
                     cleanup_killed=[0] * 3), **changes)


def serialized(diagnostics, error=None):
    receipt = diagnostics.receipt(error or RuntimeError(PRIVATE), journal_hold=True)
    text = json.dumps(receipt, sort_keys=True)
    assert PRIVATE not in text
    assert len(text) < 1600
    assert receipt["result"] == "FAIL" and receipt["terminal"] == "HOLD"
    assert not receipt["native_admission"] and not receipt["physical_acceptance"]
    assert not receipt["independent_closure_verified"]
    return receipt


def test_normal_terminal_shape_is_observation_not_acceptance_and_is_copied():
    value = terminal()
    diagnostics = CaptureDiagnostics()
    diagnostics.startup = STARTUP
    diagnostics.terminal = value
    diagnostics.returncode = 0
    receipt = serialized(diagnostics)
    assert receipt["terminal_shape_valid"]
    assert receipt["native_terminal"] == value
    assert receipt["pids_match_startup"] is True
    value["wait_status"][0] = 9
    assert receipt["native_terminal"]["wait_status"][0] == 72 << 8


@pytest.mark.parametrize("changes", [dict(capture_exit=70), dict(cleanup_killed=[0, 0, 1]),
    dict(wait_status=[-1, 72 << 8, 9]), dict(pids=[10, 11, 13])])
def test_failed_or_unknown_observation_preserved_but_strict_success_still_refuses(changes):
    value = terminal(**changes)
    diagnostics = CaptureDiagnostics()
    diagnostics.startup, diagnostics.terminal = STARTUP, value
    diagnostics.returncode = value["capture_exit"]
    assert serialized(diagnostics)["native_terminal"] == value
    with pytest.raises(RuntimeError):
        _terminal(STARTUP, value, value["capture_exit"], no_input=True)


@pytest.mark.parametrize("value", [None, [], PRIVATE, dict(stdout=PRIVATE),
    terminal(schema=True), terminal(capture_exit=True), terminal(capture_exit=2**32),
    terminal(capture=PRIVATE), terminal(terminal=PRIVATE), terminal(extra=PRIVATE),
    terminal(pids=[10, 11, PRIVATE]), terminal(pids=[10, 10, 12]),
    terminal(pids=[-2, 11, 12]), terminal(pids=[2**31, 11, 12]),
    terminal(wait_status=[72 << 8, PRIVATE, -1]), terminal(wait_status=[-2, 0, 0]),
    terminal(wait_status=[65536, 0, 0]), terminal(wait_status=[False, 0, 0]),
    terminal(cleanup_killed=[0, 0, PRIVATE]), terminal(cleanup_killed=[0, 0, 2]),
    terminal(cleanup_killed=[False, 0, 0])])
def test_malformed_or_malicious_terminal_is_not_emitted(value):
    diagnostics = CaptureDiagnostics()
    diagnostics.terminal = value
    diagnostics.startup = dict(STARTUP, extra=PRIVATE)
    diagnostics.stage = PRIVATE
    diagnostics.returncode = PRIVATE
    receipt = serialized(diagnostics, OSError(PRIVATE))
    assert not receipt["terminal_shape_valid"] and receipt["native_terminal"] is None
    assert not receipt["startup_valid"] and receipt["pids_match_startup"] is None
    assert receipt["stage"] == "unknown" and receipt["controller_returncode"] is None
    assert receipt["error_class"] == "OSError" and receipt["reason"] == "capture_failure"
    assert receipt["terminal_shape_error"] in {"type", "fields", "schema", "capture",
           "capture_exit", "terminal", "pids", "wait_status", "cleanup_killed"}


def test_partial_spawn_and_unknown_status_are_explicit_diagnostic_hold():
    value = terminal(capture_exit=70, pids=[10, -1, -1], wait_status=[-1] * 3)
    assert validated_terminal(value) == value
    with pytest.raises(RuntimeError):
        _terminal(STARTUP, value, 70, no_input=True)


@pytest.mark.parametrize("hang", [False, True])
def test_real_private_pipe_driver_records_actual_owned_cleanup_and_durable_hold(tmp_path, hang):
    path = tmp_path / "ledger"
    Journal.initialize(path, "a" * 64)
    journal = Journal(path, "a" * 64)
    custody = Custody(journal)
    diagnostics = CaptureDiagnostics()
    children = []
    value = terminal(capture_exit=70, wait_status=[72 << 8, -1, 9], cleanup_killed=[0, 0, 1])
    class BudgetWriter(io.BytesIO):
        def write(self, wire):
            assert journal.active is not None and journal.charged == 2000
            assert len(wire) == 72 and wire.startswith(b"CBNC0002")
            return super().write(wire)
    class Child:
        def __init__(self, arguments, **kwargs):
            assert arguments[1] == "--capture-noinput-budget"
            assert kwargs["stderr"] == subprocess.DEVNULL and kwargs["env"] == {}
            self.killed = False
            self.stdin = BudgetWriter()
            r, w = os.pipe()
            self.stdout = os.fdopen(r, "rb", buffering=0)
            lines = [dict(event="capture_noinput_budget_ready", challenge="d" * 64,
                          ceiling_ms=2000, anchor_continuous_ticks=1000000000,
                          timebase_numer=1, timebase_denom=1), STARTUP, value]
            os.write(w, b"".join(json.dumps(line).encode() + b"\n" for line in lines))
            os.close(w)
            children.append(self)
        def wait(self, **kwargs):
            if hang and not self.killed:
                raise subprocess.TimeoutExpired(PRIVATE, 3)
            return -9 if self.killed else 70
        def poll(self):
            return None if hang and not self.killed else (-9 if self.killed else 70)
        def kill(self):
            self.killed = True
    try:
        with patch("scripts.attended_native_launch.sys.platform", "darwin"), \
             patch("scripts.attended_native_launch.subprocess.Popen", Child):
            with pytest.raises((RuntimeError, subprocess.TimeoutExpired)) as error:
                qualify_noinput(tmp_path, custody, "b" * 40, _diagnostics=diagnostics)
        receipt = serialized(diagnostics, error.value)
        assert receipt["controller_returncode"] == (-9 if hang else 70)
        assert receipt["native_terminal"] == value and receipt["pids_match_startup"]
        assert receipt["stage"] == ("controller_wait" if hang else "terminal_validate")
        assert receipt["parent_cleanup"] == dict(emergency_closed=True, wait_completed=True,
               kill_sent=hang, streams_closed=True, peer_closed=True, custody_revoked=True)
        assert children[0].stdin.closed and children[0].stdout.closed
        assert children[0].killed is hang
        assert journal.active is not None and journal.charged == 2000
        with pytest.raises(RuntimeError):
            Custody(journal)
    finally:
        journal.close()


def test_cli_failure_outputs_one_bounded_receipt_without_traceback_or_raw_error(capsys):
    def failure(*args, _diagnostics, **kwargs):
        _diagnostics.startup = STARTUP
        _diagnostics.terminal = terminal(capture_exit=70, cleanup_killed=[0, 0, 1])
        _diagnostics.returncode = 70
        _diagnostics.stage = "terminal_validate"
        raise RuntimeError(PRIVATE)
    with patch.object(cli.sys, "platform", "darwin"), \
         patch.object(cli.sys, "argv", [PRIVATE, PRIVATE]), \
         patch.object(cli, "qualify_noinput", failure):
        assert cli.main() == 1
    captured = capsys.readouterr()
    assert captured.err == "" and PRIVATE not in captured.out and "Traceback" not in captured.out
    assert len(captured.out.splitlines()) == 1
    receipt = json.loads(captured.out)
    assert receipt["result"] == "FAIL" and receipt["terminal"] == "HOLD"
    assert receipt["controller_returncode"] == 70 and receipt["terminal_shape_valid"]
    assert receipt["parent_cleanup"]["kill_sent"] is False  # Not manufactured by CLI.


def test_cli_success_keeps_existing_exact_schema_without_failure_diagnostic(capsys):
    expected = dict(qualification="NATIVE_CAPTURE_NOINPUT_ONLY", physical_acceptance=False,
                    native_admission=False, terminal=terminal(), sequence=1, reserved_ms=2000)
    def success(_root, custody, _candidate, **kwargs):
        custody._journal.reserve(2000, "b" * 40, "c" * 64)  # Software fixture only.
        return expected
    with patch.object(cli.sys, "platform", "darwin"), \
         patch.object(cli.sys, "argv", [PRIVATE, PRIVATE]), \
         patch.object(cli, "qualify_noinput", success):
        assert cli.main() == 0
    captured = capsys.readouterr()
    assert captured.err == "" and json.loads(captured.out) == expected
    assert "DIAGNOSTIC" not in captured.out and PRIVATE not in captured.out


@pytest.mark.parametrize("hang", [False, True])
def test_owned_python_fixture_is_reaped_and_streams_closed_without_native_execution(tmp_path, hang):
    """Real local Python child + pipes, but synthetic protocol; NO native binary/audio."""
    journal_path = tmp_path / "ledger"
    Journal.initialize(journal_path, "a" * 64)
    journal = Journal(journal_path, "a" * 64)
    diagnostics, children = CaptureDiagnostics(), []
    # JSON lines are synthetic observations, not native role/closure evidence.
    lines = [dict(event="capture_noinput_budget_ready", challenge="d" * 64,
                  ceiling_ms=2000, anchor_continuous_ticks=1000000000,
                  timebase_numer=1, timebase_denom=1), STARTUP,
             terminal(capture_exit=70, wait_status=[-1] * 3)]
    code = ("import json,sys,time; "
            + "print(" + repr(json.dumps(lines[0])) + ",flush=True); "
            + "wire=sys.stdin.buffer.read(); assert len(wire)==72; "
            + "print(" + repr(json.dumps(lines[1])) + ",flush=True); "
            + "print(" + repr(json.dumps(lines[2])) + ",flush=True); "
            + ("time.sleep(60)" if hang else "sys.exit(70)"))
    real_process = subprocess.Popen
    class FixtureProcess(real_process):
        def wait(self, timeout=None):
            # Bound only the software fixture; production/native deadlines unchanged.
            return super().wait(timeout=min(timeout, 0.5) if timeout is not None else timeout)
    def spawn(arguments, **kwargs):
        assert arguments[1] == "--capture-noinput-budget"
        child = FixtureProcess([sys.executable, "-I", "-S", "-u", "-c", code], **kwargs)
        children.append(child)
        return child
    try:
        with patch("scripts.attended_native_launch.sys.platform", "darwin"), \
             patch("scripts.attended_native_launch.subprocess.Popen", spawn):
            with pytest.raises((RuntimeError, subprocess.TimeoutExpired)) as error:
                qualify_noinput(tmp_path, Custody(journal), "b" * 40, _diagnostics=diagnostics)
        receipt = serialized(diagnostics, error.value)
        assert receipt["controller_returncode"] == (-9 if hang else 70)
        assert receipt["parent_cleanup"]["kill_sent"] is hang
        assert all(receipt["parent_cleanup"][key] for key in
                   ("wait_completed", "streams_closed", "peer_closed", "custody_revoked"))
        assert children[0].poll() == (-9 if hang else 70)
        assert children[0].stdout.closed and children[0].stdin.closed
        assert journal.active is not None and journal.charged == 2000
        assert sys.executable not in json.dumps(receipt)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=1)
        journal.close()
