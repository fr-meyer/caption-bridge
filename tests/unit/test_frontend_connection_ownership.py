"""Run actual production JS callbacks under Node's bounded in-memory VM."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/connection_ownership_node.cjs"
# Separate startup/scheduling slack from the fixture's five-second internal
# deadline and 250ms VM-call ceiling. Neither is a live-model latency claim.
OUTER_TIMEOUT_S = 20


def _run_fixture(source, *, fixture=FIXTURE, timeout=OUTER_TIMEOUT_S):
    node = shutil.which("node")
    assert node is not None, "Node is required for the offline production-JS callback check"
    with subprocess.Popen([node, str(fixture), str(source)], text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()  # Reap the owned process before reporting failure.
            raise AssertionError("offline fixture outer deadline; process killed and reaped") from None
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def test_production_connection_policy_with_fake_socket_clock_and_dom():
    result = _run_fixture(ROOT / "app/static/app.js")
    assert result.returncode == 0, result.stderr
    assert result.stderr.splitlines() == ["fixture:started", "fixture:source_read",
        "fixture:cases_started", *[f"fixture:case_{case}" for case in range(1, 8)],
        "fixture:completed"]
    assert json.loads(result.stdout) == {
        "tests": 7, "passed": True, "real_browser": False,
        "network": False, "audio": False, "storage": False,
    }


@pytest.mark.parametrize("payload,_reason", [
    ("while (true) {}", "vm_timeout"),
    ("throw new Error('PRIVATE callback details')", "callback_error"),
    ("appState.ttsAudioUnlocked = false;", "assertion"),
    ("Promise.resolve().then(() => {while (true) {}});", "vm_timeout"),
    ("throw {get stack(){while(true){}}, get message(){return 'PRIVATE stack';}};",
     "stack_getter"),
    ("throw {get message(){while(true){}}, get stack(){return 'PRIVATE message';}};",
     "message_getter"),
    ("Promise.resolve().then(() => {throw {get stack(){while(true){}}, "
     "get message(){return 'PRIVATE microtask';}};});", "microtask_stack_getter"),
    ("Promise.resolve().then(() => {throw new Error('PRIVATE rejection');});",
     "microtask_error"),
])
def test_bad_production_callback_fails_without_success_proof(tmp_path, payload, _reason):
    source = (ROOT / "app/static/app.js").read_text()
    marker = "function connectWebSocket() {"
    assert source.count(marker) == 1
    modified = tmp_path / "synthetic-callback.js"
    modified.write_text(source.replace(marker, marker + payload, 1))
    # Six seconds is an independent safety ceiling, not the twenty-second
    # startup allowance. A kill/reap assertion is a test failure, never a pass.
    result = _run_fixture(modified, timeout=6)
    assert result.returncode != 0
    assert result.stdout == ""
    cases = range(1, 8) if _reason.startswith("microtask_") else range(1, 2)
    assert result.stderr.splitlines() == ["fixture:started", "fixture:source_read",
        "fixture:cases_started", *[f"fixture:case_{case}" for case in cases], "fixture:failed"]
    assert "PRIVATE" not in result.stderr


def test_outer_deadline_kills_and_reaps_unresponsive_owned_process(tmp_path, monkeypatch):
    fixture = tmp_path / "synthetic-hang.cjs"
    fixture.write_text("while (true) {}")
    original = subprocess.Popen
    processes = []
    def record(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(subprocess, "Popen", record)
    with pytest.raises(AssertionError, match="process killed and reaped"):
        _run_fixture(ROOT / "app/static/app.js", fixture=fixture, timeout=.2)
    assert len(processes) == 1
    assert processes[0].poll() is not None
    assert processes[0].returncode != 0
    assert processes[0].stdout.closed and processes[0].stderr.closed


def test_captured_reconnect_callback_is_still_vm_bounded(tmp_path):
    source = (ROOT / "app/static/app.js").read_text()
    marker = "reconnectTimer = setTimeout(function () {"
    assert source.count(marker) == 1
    modified = tmp_path / "synthetic-timer.js"
    modified.write_text(source.replace(marker, marker +
        "if (appState.ownershipBlocked) {while (true) {}}", 1))
    result = _run_fixture(modified)
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr.splitlines() == ["fixture:started", "fixture:source_read",
        "fixture:cases_started", *[f"fixture:case_{case}" for case in range(1, 7)],
        "fixture:failed"]
