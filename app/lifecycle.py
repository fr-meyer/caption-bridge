"""Safe, on-demand lifecycle control for the local Caption Bridge service."""

from __future__ import annotations

import fcntl
import json
import os
import platform
import re
import shlex
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Iterator

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
_REQUIRED_ENV_KEY = re.compile(
    r"^\s*(?:export\s+)?MISTRAL_API_KEY\s*=\s*(.*?)\s*$"
)


class ExitCode(IntEnum):
    """Stable command exit codes for automation."""

    OK = 0
    CONFIGURATION = 2
    STALE_STATE = 3
    PORT_IN_USE = 4
    STARTUP = 5
    STOP = 6


@dataclass(frozen=True)
class RuntimePaths:
    state: Path
    log: Path


@dataclass(frozen=True)
class ProcessSnapshot:
    start_token: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeState:
    pid: int
    start_token: str
    repo_root: str
    python_path: str
    host: str
    port: int
    argv: tuple[str, ...]
    started_at: str

    @classmethod
    def from_json(cls, raw: str) -> "RuntimeState":
        data = json.loads(raw)
        argv = data.get("argv")
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            raise ValueError("invalid argv")
        state = cls(
            pid=data["pid"],
            start_token=data["start_token"],
            repo_root=data["repo_root"],
            python_path=data["python_path"],
            host=data["host"],
            port=data["port"],
            argv=tuple(argv),
            started_at=data["started_at"],
        )
        if (
            not isinstance(state.pid, int)
            or state.pid <= 1
            or not isinstance(state.port, int)
            or not 1 <= state.port <= 65535
            or not all(
                isinstance(value, str) and value
                for value in (
                    state.start_token,
                    state.repo_root,
                    state.python_path,
                    state.host,
                    state.started_at,
                )
            )
        ):
            raise ValueError("invalid runtime state")
        return state

    def to_json(self) -> str:
        payload = asdict(self)
        payload["argv"] = list(self.argv)
        return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


@dataclass(frozen=True)
class Preflight:
    ok: bool
    reason: str
    host: str = LOOPBACK_HOST
    port: int = DEFAULT_PORT


@dataclass(frozen=True)
class ControlResult:
    status: str
    message: str
    exit_code: ExitCode
    running: bool
    paths: RuntimePaths
    healthy: bool | None = None
    pid: int | None = None
    host: str | None = None
    port: int | None = None

    def public_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "message": self.message,
            "exit_code": int(self.exit_code),
            "running": self.running,
            "runtime_state_path": str(self.paths.state),
            "log_path": str(self.paths.log),
        }
        for key in ("healthy", "pid", "host", "port"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result


def default_runtime_paths() -> RuntimePaths:
    home = Path.home()
    if platform.system() == "Darwin":
        runtime_dir = home / "Library" / "Caches" / "CaptionBridge"
        log_dir = home / "Library" / "Logs" / "CaptionBridge"
    else:
        runtime_dir = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache")) / "caption-bridge"
        log_dir = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state")) / "caption-bridge"
    return RuntimePaths(state=runtime_dir / "runtime.json", log=log_dir / "caption-bridge.log")


def env_file_has_required_key(path: Path) -> bool:
    """Check required-key presence without returning or logging its value."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return False
    for line in lines:
        match = _REQUIRED_ENV_KEY.match(line)
        if not match:
            continue
        value = match.group(1).strip()
        if value and not value.startswith("#") and value not in {'""', "''"}:
            return True
    return False


class LifecycleController:
    """Own one local process and refuse to signal anything it cannot identify."""

    def __init__(
        self,
        repo_root: Path,
        *,
        paths: RuntimePaths | None = None,
        start_timeout: float = 15.0,
        stop_timeout: float = 10.0,
        poll_interval: float = 0.1,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.paths = paths or default_runtime_paths()
        self.start_timeout = start_timeout
        self.stop_timeout = stop_timeout
        self.poll_interval = poll_interval

    @contextmanager
    def _command_lock(self) -> Iterator[None]:
        self.paths.state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.paths.state.parent, 0o700)
        lock_path = self.paths.state.with_suffix(".lock")
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, "r+", encoding="utf-8") as handle:
            os.chmod(lock_path, 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def execute(self, command: str) -> ControlResult:
        if command not in {"start", "status", "stop"}:
            raise ValueError("unsupported lifecycle command")
        with self._command_lock():
            return getattr(self, command)()

    @property
    def python_path(self) -> Path:
        return self.repo_root / ".venv" / "bin" / "python"

    @property
    def env_path(self) -> Path:
        return self.repo_root / ".env"

    def _load_state(self) -> tuple[RuntimeState | None, str | None]:
        try:
            raw = self.paths.state.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None, None
        except OSError:
            return None, "unreadable"
        try:
            return RuntimeState.from_json(raw), None
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None, "invalid"

    def _write_state(self, state: RuntimeState) -> None:
        self.paths.state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.paths.state.parent, 0o700)
        temporary = self.paths.state.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(state.to_json())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.paths.state)
            os.chmod(self.paths.state, 0o600)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _remove_state(self) -> None:
        try:
            self.paths.state.unlink()
        except FileNotFoundError:
            pass

    def _probe(self, pid: int) -> ProcessSnapshot | None:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart=", "-o", "command="],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return None
        parts = completed.stdout.strip().split(None, 5)
        if len(parts) != 6:
            return None
        try:
            argv = tuple(shlex.split(parts[5]))
        except ValueError:
            return None
        return ProcessSnapshot(start_token=" ".join(parts[:5]), argv=argv)

    def _is_owned(self, state: RuntimeState) -> bool:
        if (
            Path(state.repo_root) != self.repo_root
            or Path(state.python_path) != self.python_path
            or state.host != LOOPBACK_HOST
        ):
            return False
        snapshot = self._probe(state.pid)
        return bool(
            snapshot
            and snapshot.start_token == state.start_token
            and snapshot.argv == state.argv
        )

    def _health(self, host: str, port: int) -> bool:
        if host != LOOPBACK_HOST:
            return False
        try:
            with urllib.request.urlopen(
                f"http://{host}:{port}/healthz", timeout=1
            ) as response:
                payload = json.loads(response.read(1024))
                return (
                    response.status == 200
                    and payload.get("service") == "caption-bridge"
                    and payload.get("status") == "ok"
                )
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            urllib.error.URLError,
        ):
            return False

    def _port_free(self, host: str, port: int) -> bool:
        if host != LOOPBACK_HOST:
            return False
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            return True
        except OSError:
            return False
        finally:
            sock.close()

    def _preflight(self) -> Preflight:
        try:
            completed = subprocess.run(
                [str(self.python_path), "-m", "scripts.runtime_preflight", "--json"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return Preflight(False, "venv_incomplete")
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, ValueError, json.JSONDecodeError):
            return Preflight(False, "preflight_failed")
        if completed.returncode != 0 or not payload.get("ok"):
            return Preflight(False, str(payload.get("reason", "preflight_failed")))
        host = payload.get("host")
        port = payload.get("port")
        if not isinstance(host, str) or not isinstance(port, int):
            return Preflight(False, "invalid_configuration")
        return Preflight(True, "ready", host=host, port=port)

    def _open_log(self) -> Any:
        self.paths.log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.paths.log.parent, 0o700)
        fd = os.open(self.paths.log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.chmod(self.paths.log, 0o600)
        return os.fdopen(fd, "ab", buffering=0)

    def _spawn(self, argv: tuple[str, ...], log_handle: Any) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            argv,
            cwd=self.repo_root,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def _signal(self, pid: int, sig: signal.Signals) -> None:
        os.kill(pid, sig)

    def _result(
        self,
        status: str,
        message: str,
        exit_code: ExitCode,
        running: bool,
        *,
        state: RuntimeState | None = None,
        healthy: bool | None = None,
        host: str | None = None,
        port: int | None = None,
    ) -> ControlResult:
        return ControlResult(
            status=status,
            message=message,
            exit_code=exit_code,
            running=running,
            paths=self.paths,
            healthy=healthy,
            pid=state.pid if state else None,
            host=state.host if state else host,
            port=state.port if state else port,
        )

    def status(self) -> ControlResult:
        state, error = self._load_state()
        if error:
            return self._result(
                "stale_state",
                "Runtime state is unreadable or invalid; no process was signalled.",
                ExitCode.STALE_STATE,
                False,
            )
        if state is None:
            return self._result(
                "stopped",
                "Caption Bridge is stopped.",
                ExitCode.OK,
                False,
            )
        if not self._is_owned(state):
            return self._result(
                "stale_state",
                "Runtime identity does not match; no process was signalled.",
                ExitCode.STALE_STATE,
                False,
                state=state,
            )
        healthy = self._health(state.host, state.port)
        if healthy:
            return self._result(
                "running",
                "Caption Bridge is running and healthy.",
                ExitCode.OK,
                True,
                state=state,
                healthy=True,
            )
        return self._result(
            "running_unhealthy",
            "Caption Bridge process is running but its local health check failed.",
            ExitCode.STARTUP,
            True,
            state=state,
            healthy=False,
        )

    def start(self) -> ControlResult:
        state, state_error = self._load_state()
        if state is not None and self._is_owned(state):
            return self._result(
                "already_running",
                "Caption Bridge is already running.",
                ExitCode.OK,
                True,
                state=state,
                healthy=self._health(state.host, state.port),
            )
        if state is not None or state_error:
            self._remove_state()

        if not self.python_path.is_file() or not os.access(self.python_path, os.X_OK):
            return self._result(
                "venv_missing",
                "The repository-local virtual environment is missing.",
                ExitCode.CONFIGURATION,
                False,
            )
        if not env_file_has_required_key(self.env_path):
            return self._result(
                "configuration_missing",
                "Required configuration is missing or incomplete.",
                ExitCode.CONFIGURATION,
                False,
            )

        preflight = self._preflight()
        if not preflight.ok:
            messages = {
                "venv_incomplete": "The repository-local virtual environment is incomplete.",
                "configuration_missing": "Required configuration is missing or incomplete.",
                "microphone_unavailable": "No microphone input device is available.",
                "microphone_permission": "Microphone permission is unavailable.",
                "invalid_configuration": "Runtime configuration is invalid.",
            }
            return self._result(
                preflight.reason,
                messages.get(preflight.reason, "Runtime preflight failed."),
                ExitCode.CONFIGURATION,
                False,
            )
        if preflight.host != LOOPBACK_HOST:
            return self._result(
                "non_loopback_refused",
                "Start refused because HOST is not the IPv4 loopback address.",
                ExitCode.CONFIGURATION,
                False,
                host=preflight.host,
                port=preflight.port,
            )
        if not 1 <= preflight.port <= 65535:
            return self._result(
                "invalid_port",
                "Start refused because PORT is invalid.",
                ExitCode.CONFIGURATION,
                False,
                host=LOOPBACK_HOST,
                port=preflight.port,
            )
        if not self._port_free(LOOPBACK_HOST, preflight.port):
            return self._result(
                "port_in_use",
                "The configured loopback port is already in use.",
                ExitCode.PORT_IN_USE,
                False,
                host=LOOPBACK_HOST,
                port=preflight.port,
            )

        argv = (
            str(self.python_path),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            LOOPBACK_HOST,
            "--port",
            str(preflight.port),
        )
        try:
            with self._open_log() as log_handle:
                process = self._spawn(argv, log_handle)
        except OSError:
            return self._result(
                "startup_failed",
                "Caption Bridge could not be started; inspect the local log.",
                ExitCode.STARTUP,
                False,
                host=LOOPBACK_HOST,
                port=preflight.port,
            )

        snapshot = None
        token_deadline = time.monotonic() + 2.0
        while snapshot is None and process.poll() is None and time.monotonic() < token_deadline:
            snapshot = self._probe(process.pid)
            if snapshot is None:
                time.sleep(self.poll_interval)
        if snapshot is None or snapshot.argv != argv:
            return self._result(
                "identity_failed",
                "The new process identity could not be verified; no signal was sent.",
                ExitCode.STARTUP,
                False,
                host=LOOPBACK_HOST,
                port=preflight.port,
            )

        runtime_state = RuntimeState(
            pid=process.pid,
            start_token=snapshot.start_token,
            repo_root=str(self.repo_root),
            python_path=str(self.python_path),
            host=LOOPBACK_HOST,
            port=preflight.port,
            argv=argv,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self._write_state(runtime_state)

        deadline = time.monotonic() + self.start_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self._remove_state()
                return self._result(
                    "startup_failed",
                    "Caption Bridge exited during startup; inspect the local log.",
                    ExitCode.STARTUP,
                    False,
                    host=LOOPBACK_HOST,
                    port=preflight.port,
                )
            if self._health(LOOPBACK_HOST, preflight.port):
                return self._result(
                    "started",
                    "Caption Bridge started and passed its local health check.",
                    ExitCode.OK,
                    True,
                    state=runtime_state,
                    healthy=True,
                )
            time.sleep(self.poll_interval)

        if not self._is_owned(runtime_state):
            if self._probe(runtime_state.pid) is None:
                self._remove_state()
            return self._result(
                "startup_timeout",
                "Startup timed out and process identity changed; no signal was sent.",
                ExitCode.STARTUP,
                False,
                state=runtime_state,
                healthy=False,
            )

        try:
            self._signal(runtime_state.pid, signal.SIGTERM)
        except OSError:
            return self._result(
                "startup_timeout",
                "Startup timed out and the owned process could not be stopped.",
                ExitCode.STARTUP,
                True,
                state=runtime_state,
                healthy=False,
            )

        stop_deadline = time.monotonic() + self.stop_timeout
        while time.monotonic() < stop_deadline:
            current = self._probe(runtime_state.pid)
            if current is None or current.start_token != runtime_state.start_token:
                self._remove_state()
                return self._result(
                    "startup_timeout",
                    "Startup timed out; the owned process was stopped safely.",
                    ExitCode.STARTUP,
                    False,
                    host=runtime_state.host,
                    port=runtime_state.port,
                    healthy=False,
                )
            time.sleep(self.poll_interval)

        return self._result(
            "startup_timeout",
            "Startup timed out; the owned process did not stop and state was retained.",
            ExitCode.STARTUP,
            True,
            state=runtime_state,
            healthy=False,
        )

    def stop(self) -> ControlResult:
        state, error = self._load_state()
        if error:
            return self._result(
                "stale_state_not_signalled",
                "Runtime state is invalid; no process was signalled.",
                ExitCode.STALE_STATE,
                False,
            )
        if state is None:
            return self._result(
                "stopped",
                "Caption Bridge is already stopped.",
                ExitCode.OK,
                False,
            )
        if not self._is_owned(state):
            return self._result(
                "stale_state_not_signalled",
                "Runtime identity does not match; no process was signalled.",
                ExitCode.STALE_STATE,
                False,
                state=state,
            )

        try:
            if not self._is_owned(state):
                return self._result(
                    "stale_state_not_signalled",
                    "Runtime identity changed; no process was signalled.",
                    ExitCode.STALE_STATE,
                    False,
                    state=state,
                )
            self._signal(state.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            if self._probe(state.pid) is None:
                self._remove_state()
                return self._result(
                    "stopped",
                    "Caption Bridge stopped.",
                    ExitCode.OK,
                    False,
                    host=state.host,
                    port=state.port,
                )
            return self._result(
                "stop_failed",
                "Caption Bridge could not be signalled safely.",
                ExitCode.STOP,
                True,
                state=state,
            )

        deadline = time.monotonic() + self.stop_timeout
        while time.monotonic() < deadline:
            snapshot = self._probe(state.pid)
            if snapshot is None or snapshot.start_token != state.start_token:
                self._remove_state()
                return self._result(
                    "stopped",
                    "Caption Bridge stopped.",
                    ExitCode.OK,
                    False,
                    host=state.host,
                    port=state.port,
                )
            time.sleep(self.poll_interval)

        return self._result(
            "stop_timeout",
            "Caption Bridge did not stop before the timeout; state was retained.",
            ExitCode.STOP,
            True,
            state=state,
        )
