from __future__ import annotations

import json
import os
import signal
from pathlib import Path
from typing import Any

import pytest

from app.lifecycle import (
    LOOPBACK_HOST,
    ExitCode,
    LifecycleController,
    Preflight,
    ProcessSnapshot,
    RuntimePaths,
    RuntimeState,
    env_file_has_required_key,
)


class FakeProcess:
    def __init__(self, pid: int = 43210) -> None:
        self.pid = pid
        self.return_code: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.return_code

    def terminate(self) -> None:
        self.terminated = True
        self.return_code = 0


class Harness(LifecycleController):
    def __init__(self, repo_root: Path, paths: RuntimePaths) -> None:
        super().__init__(
            repo_root,
            paths=paths,
            start_timeout=0.1,
            stop_timeout=0.1,
            poll_interval=0.001,
        )
        self.preflight = Preflight(True, "ready", LOOPBACK_HOST, 8765)
        self.snapshot: ProcessSnapshot | None = None
        self.healthy = True
        self.port_is_free = True
        self.process = FakeProcess()
        self.spawn_count = 0
        self.signals: list[tuple[int, signal.Signals]] = []

    def _preflight(self) -> Preflight:
        return self.preflight

    def _probe(self, pid: int) -> ProcessSnapshot | None:
        if pid != self.process.pid:
            return None
        return self.snapshot

    def _health(self, host: str, port: int) -> bool:
        return self.healthy

    def _port_free(self, host: str, port: int) -> bool:
        return self.port_is_free

    def _spawn(self, argv: tuple[str, ...], log_handle: Any) -> FakeProcess:
        self.spawn_count += 1
        self.snapshot = ProcessSnapshot("Fri Aug 15 12:00:00 2026", argv)
        return self.process

    def _signal(self, pid: int, sig: signal.Signals) -> None:
        self.signals.append((pid, sig))
        self.snapshot = None
        self.process.return_code = 0


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    repo = tmp_path / "repo"
    python = repo / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o700)
    (repo / ".env").write_text("MISTRAL_API_KEY=test-only-secret\n", encoding="utf-8")
    paths = RuntimePaths(
        state=tmp_path / "cache" / "runtime.json",
        log=tmp_path / "logs" / "caption-bridge.log",
    )
    return Harness(repo, paths)


def runtime_state(controller: Harness) -> RuntimeState:
    argv = (
        str(controller.python_path),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        LOOPBACK_HOST,
        "--port",
        "8765",
    )
    return RuntimeState(
        pid=controller.process.pid,
        start_token="Fri Aug 15 12:00:00 2026",
        repo_root=str(controller.repo_root),
        python_path=str(controller.python_path),
        host=LOOPBACK_HOST,
        port=8765,
        argv=argv,
        started_at="2026-08-15T12:00:00Z",
    )


def test_start_status_stop_status_twice(harness: Harness) -> None:
    started = harness.start()
    assert started.status == "started"
    assert started.exit_code == ExitCode.OK
    assert started.running is True

    running = harness.status()
    assert running.status == "running"
    assert running.healthy is True

    stopped = harness.stop()
    assert stopped.status == "stopped"
    assert harness.signals == [(harness.process.pid, signal.SIGTERM)]
    assert not harness.paths.state.exists()

    assert harness.status().status == "stopped"
    assert harness.status().status == "stopped"


def test_repeated_start_is_idempotent(harness: Harness) -> None:
    assert harness.start().status == "started"
    result = harness.start()
    assert result.status == "already_running"
    assert result.exit_code == ExitCode.OK
    assert harness.spawn_count == 1


def test_repeated_stop_is_idempotent(harness: Harness) -> None:
    assert harness.stop().status == "stopped"
    assert harness.stop().status == "stopped"
    assert harness.signals == []


def test_execute_uses_private_command_lock(harness: Harness) -> None:
    assert harness.execute("status").status == "stopped"
    lock_path = harness.paths.state.with_suffix(".lock")
    assert os.stat(lock_path).st_mode & 0o777 == 0o600


def test_stale_pid_never_signals_process(harness: Harness) -> None:
    state = runtime_state(harness)
    harness._write_state(state)
    harness.snapshot = ProcessSnapshot("DIFFERENT START TOKEN", state.argv)

    result = harness.stop()

    assert result.status == "stale_state_not_signalled"
    assert result.exit_code == ExitCode.STALE_STATE
    assert harness.signals == []
    assert harness.paths.state.exists()


def test_matching_start_token_but_wrong_command_is_not_owned(harness: Harness) -> None:
    state = runtime_state(harness)
    harness._write_state(state)
    harness.snapshot = ProcessSnapshot(state.start_token, ("/usr/bin/python3", "unrelated.py"))

    result = harness.stop()

    assert result.status == "stale_state_not_signalled"
    assert harness.signals == []


def test_corrupt_state_never_signals_process(harness: Harness) -> None:
    harness.paths.state.parent.mkdir(parents=True)
    harness.paths.state.write_text("{not json", encoding="utf-8")

    result = harness.stop()

    assert result.status == "stale_state_not_signalled"
    assert harness.signals == []


def test_unhealthy_owned_process_is_distinct(harness: Harness) -> None:
    state = runtime_state(harness)
    harness._write_state(state)
    harness.snapshot = ProcessSnapshot(state.start_token, state.argv)
    harness.healthy = False

    result = harness.status()

    assert result.status == "running_unhealthy"
    assert result.running is True
    assert result.healthy is False
    assert result.exit_code == ExitCode.STARTUP


def test_missing_venv_is_distinct(harness: Harness) -> None:
    harness.python_path.unlink()

    result = harness.start()

    assert result.status == "venv_missing"
    assert result.exit_code == ExitCode.CONFIGURATION
    assert harness.spawn_count == 0


def test_missing_configuration_is_distinct(harness: Harness) -> None:
    harness.env_path.write_text("HOST=127.0.0.1\n", encoding="utf-8")

    result = harness.start()

    assert result.status == "configuration_missing"
    assert harness.spawn_count == 0


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("venv_incomplete", "venv_incomplete"),
        ("microphone_unavailable", "microphone_unavailable"),
        ("microphone_permission", "microphone_permission"),
        ("invalid_configuration", "invalid_configuration"),
    ],
)
def test_preflight_failures_are_distinct(
    harness: Harness, reason: str, expected: str
) -> None:
    harness.preflight = Preflight(False, reason)

    result = harness.start()

    assert result.status == expected
    assert result.exit_code == ExitCode.CONFIGURATION
    assert harness.spawn_count == 0


def test_non_loopback_host_is_refused(harness: Harness) -> None:
    harness.preflight = Preflight(True, "ready", "0.0.0.0", 8765)

    result = harness.start()

    assert result.status == "non_loopback_refused"
    assert harness.spawn_count == 0


def test_occupied_port_is_distinct(harness: Harness) -> None:
    harness.port_is_free = False

    result = harness.start()

    assert result.status == "port_in_use"
    assert result.exit_code == ExitCode.PORT_IN_USE
    assert harness.spawn_count == 0


def test_runtime_state_and_log_are_private(harness: Harness) -> None:
    result = harness.start()

    assert result.status == "started"
    assert os.stat(harness.paths.state).st_mode & 0o777 == 0o600
    assert os.stat(harness.paths.log).st_mode & 0o777 == 0o600
    assert os.stat(harness.paths.state.parent).st_mode & 0o777 == 0o700
    assert os.stat(harness.paths.log.parent).st_mode & 0o777 == 0o700


def test_public_output_contains_no_command_or_credentials(harness: Harness) -> None:
    result = harness.start()
    output = json.dumps(result.public_dict())

    assert "test-only-secret" not in output
    assert "MISTRAL_API_KEY" not in output
    assert "argv" not in output
    assert "uvicorn" not in output


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("MISTRAL_API_KEY=value\n", True),
        (" export MISTRAL_API_KEY = 'value' \n", True),
        ("MISTRAL_API_KEY=\n", False),
        ("MISTRAL_API_KEY=\"\"\n", False),
        ("# MISTRAL_API_KEY=value\n", False),
        ("HOST=127.0.0.1\n", False),
    ],
)
def test_required_key_presence_check(
    tmp_path: Path, body: str, expected: bool
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(body, encoding="utf-8")
    assert env_file_has_required_key(env_file) is expected


def test_identity_failure_never_signals_or_terminates(harness: Harness) -> None:
    def mismatched_spawn(argv: tuple[str, ...], log_handle: Any) -> FakeProcess:
        harness.spawn_count += 1
        harness.snapshot = ProcessSnapshot("TOKEN", ("/usr/bin/unrelated",))
        return harness.process

    harness._spawn = mismatched_spawn  # type: ignore[method-assign]

    result = harness.start()

    assert result.status == "identity_failed"
    assert harness.signals == []
    assert harness.process.terminated is False


def test_start_safely_recovers_stale_state_when_port_is_free(
    harness: Harness,
) -> None:
    stale = runtime_state(harness)
    harness._write_state(stale)
    harness.snapshot = ProcessSnapshot("REUSED PID", ("/usr/bin/other",))

    result = harness.start()

    assert result.status == "started"
    assert harness.signals == []
    assert harness.spawn_count == 1
