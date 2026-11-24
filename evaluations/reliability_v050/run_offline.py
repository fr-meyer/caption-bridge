"""Bounded local-only reliability checks; deny native/provider/browser IO by default."""

from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
import platform
import posixpath
import stat
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path
from types import ModuleType

try:
    import resource
except ImportError:  # Windows has no resource module.
    resource = None

ROOT = Path(__file__).resolve().parents[2]
DENIED = []


def forbidden(label):
    def deny(*_args, **_kwargs):
        DENIED.append(label)
        raise AssertionError("offline_external_io_denied")

    return deny


def source_file_value(root, name):
    """Expose only a stable error code, never filesystem filenames or causes."""
    try:
        return _source_file_value(root, name)
    except OSError:
        raise ValueError("source_io_unavailable") from None


def _source_file_value(root, name):
    """Read source only beneath a frozen root; never resolve an ancestor alias.

    A direct leaf symlink binds link TEXT only (the existing digest contract),
    not resolved executable bytes. Other reparse points, including junctions,
    fail closed. Windows component checks are not native/race qualification.
    """
    root, relative = Path(root).absolute(), Path(name)
    if relative.is_absolute() or relative.drive or not relative.parts or ".." in relative.parts:
        raise ValueError("source_path_outside_root")
    path = root
    components = [root]
    for part in relative.parts:
        path = path / part
        components.append(path)
    leaf_link = False
    for index, component in enumerate(components):
        try:
            metadata = component.lstat()  # Inspect each component before reading any bytes.
        except FileNotFoundError:
            return b"missing"
        last = index == len(components) - 1
        if stat.S_ISLNK(metadata.st_mode):
            if not last:
                raise ValueError("source_ancestor_alias")
            leaf_link = True
        elif getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("source_reparse_alias")
        elif not last and not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("source_ancestor_not_directory")
        elif last and not stat.S_ISREG(metadata.st_mode):
            raise ValueError("source_not_regular_file")
    # POSIX descriptor-relative reads also close the check/read replacement gap.
    # Windows has no equivalent stdlib dir_fd route: all components above are
    # checked fail-closed, without claiming native Windows atomic/race proof.
    if os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open(root, flags)
        try:
            for part in relative.parts[:-1]:
                child = os.open(part, flags, dir_fd=directory)
                os.close(directory)
                directory = child
            if leaf_link:
                return b"symlink\0" + os.fsencode(os.readlink(relative.name, dir_fd=directory))
            descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=directory)
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise ValueError("source_not_regular_file")
                with os.fdopen(descriptor, "rb", closefd=False) as source:
                    return b"file\0" + source.read()
            finally:
                os.close(descriptor)
        finally:
            os.close(directory)
    if leaf_link:
        return b"symlink\0" + os.fsencode(os.readlink(path))
    return b"file\0" + path.read_bytes()


def permitted_subprocess_argv(argv, *, windows=None):
    """Keep the existing names; only Windows filename casing is equivalent.

    Do not consult PATHEXT, strip suffixes, parse a shell command or resolve a
    new executable. Full paths retain the existing basename-only policy.
    """
    if not isinstance(argv, (list, tuple)) or not argv:
        return False
    try:
        program = os.fspath(argv[0])
    except TypeError:
        return False
    if not isinstance(program, str) or not program:
        return False
    windows = os.name == "nt" if windows is None else windows
    name = ntpath.basename(program) if windows else posixpath.basename(program)
    # Approved names are ASCII; Unicode folds must not introduce new names.
    name = name.lower() if windows and name.isascii() else name
    return name in {"git", "node", "node.exe", "pwsh"}


def guarded_subprocess_popen(original, argv, *args, **kwargs):
    # Popen positional order after argv: bufsize, executable, stdin, stdout,
    # stderr, preexec_fn, close_fds, shell. No override may bypass argv checks.
    shell_override = kwargs.get("shell") or (len(args) > 7 and args[7])
    executable_override = (kwargs.get("executable") is not None
                           or (len(args) > 1 and args[1] is not None))
    if shell_override or executable_override or not permitted_subprocess_argv(argv):
        return forbidden("unapproved_process")(argv)
    return original(argv, *args, **kwargs)


def install_guards():
    for key in list(os.environ):
        if key.upper().startswith(("MISTRAL_", "OPENAI_")) or "PROXY" in key.upper():
            os.environ.pop(key)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    sys.path.insert(0, str(ROOT))
    from pydantic_settings.sources import DotEnvSettingsSource

    from scripts.software_network_guard import SoftwareNetworkGuard

    DotEnvSettingsSource._read_env_files = lambda _self: {}
    sd = ModuleType("sounddevice")
    for name in (
        "RawInputStream",
        "InputStream",
        "OutputStream",
        "RawOutputStream",
        "play",
        "query_devices",
    ):
        setattr(sd, name, forbidden("native_device"))
    sys.modules["sounddevice"] = sd
    network_guard = SoftwareNetworkGuard(forbidden("network")).install()
    original_popen = subprocess.Popen

    def popen(argv, *args, **kwargs):
        return guarded_subprocess_popen(original_popen, argv, *args, **kwargs)

    subprocess.Popen = popen
    return network_guard


def software_source_identity(root=ROOT):
    """Bind software evidence to actual bytes, including an uncommitted candidate."""
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, check=True
        ).stdout

    names = git(
        "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--",
        "app", "scripts", "tests", "evaluations/reliability_v050", "pyproject.toml", "uv.lock",
    ).split(b"\0")
    digest = hashlib.sha256()
    paths = sorted(set(name for name in names if name))
    for name in paths:
        value = source_file_value(root, os.fsdecode(name))
        digest.update(name + b"\0" + hashlib.sha256(value).hexdigest().encode("ascii") + b"\n")
    return {
        "source_head": git("rev-parse", "HEAD").decode("ascii").strip(),
        "source_dirty": bool(git("status", "--porcelain=v1", "-z")),
        "software_source_sha256": digest.hexdigest(),
        "software_source_files": len(paths),
    }


NODE_DIAGNOSTIC_PREFIX = "SHORTCUT_NODE_TRANSPORT "
NODE_STAGES = (
    "ENTRY", "STDIN_READ_BEGIN", "STDIN_READ_END", "JSON_PARSED",
    "ORIGINAL_BEGIN", "ORIGINAL_DONE", "MUTANT_BEGIN", "MUTANT_DONE",
    "FORWARD_BEGIN", "FORWARD_DONE", "RESULT_WRITE_BEGIN", "RESULT_ENQUEUED", "EXIT_EVENT",
)


def _public_node_diagnostic(line: str) -> dict | None:
    """Fixed-shape privacy filter only; neither a gate nor a simulated Node outcome."""
    if not line.startswith(NODE_DIAGNOSTIC_PREFIX) or len(line) > 2048:
        return None
    try:
        value = json.loads(line[len(NODE_DIAGNOSTIC_PREFIX):])
    except (ValueError, TypeError, RecursionError):
        return None
    keys = {"schema", "kind", "model_only", "cause", "outcome", "returncode",
            "timeout_seconds", "elapsed_ms", "input_bytes", "input_sha256",
            "stdin_bytes_observed", "stages_observed", "last_stage", "stage_protocol_valid",
            "stderr_scan_truncated", "node_error_class", "node_error_code"}
    if (type(value) is not dict or set(value) != keys or type(value["schema"]) is not int
            or value["schema"] != 1 or value["kind"] != "NODE_SHORTCUT_TRANSPORT_DIAGNOSTIC"
            or value["model_only"] is not True or value["cause"] != "UNKNOWN"
            or type(value["timeout_seconds"]) is not int or value["timeout_seconds"] != 5):
        return None
    if (type(value["outcome"]) is not str
            or value["outcome"] not in {"EXITED", "NONZERO", "TIMEOUT", "SPAWN_ERROR"}
            or (value["returncode"] is not None and type(value["returncode"]) is not int)):
        return None
    if value["returncode"] is not None and not -(2**31) <= value["returncode"] <= 2**32 - 1:
        return None
    if ((value["outcome"] == "EXITED" and value["returncode"] != 0)
            or (value["outcome"] == "NONZERO" and value["returncode"] in (None, 0))
            or (value["outcome"] in {"TIMEOUT", "SPAWN_ERROR"} and value["returncode"] is not None)):
        return None
    for key in ("elapsed_ms", "input_bytes", "stdin_bytes_observed"):
        number = value[key]
        if number is None and key == "stdin_bytes_observed":
            continue
        if type(number) is not int or not 0 <= number <= 2**63 - 1:
            return None
    if (type(value["input_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", value["input_sha256"]) is None):
        return None
    stages = value["stages_observed"]
    if (type(stages) is not list or len(stages) > 13
            or any(type(stage) is not int or not 0 <= stage < len(NODE_STAGES) for stage in stages)
            or value["last_stage"] != (NODE_STAGES[stages[-1]] if stages else "NO_STAGE_OBSERVED")):
        return None
    if any(type(value[key]) is not bool for key in ("stage_protocol_valid", "stderr_scan_truncated")):
        return None
    for key, allowed in (("node_error_class", {"AssertionError", "SyntaxError", "TypeError",
                                             "ReferenceError", "RangeError", "Error"}),
                         ("node_error_code", {"ERR_ASSERTION", "EPIPE", "EBADF", "EINVAL",
                                            "EAGAIN", "ENOENT", "EACCES"})):
        if value[key] is not None and (type(value[key]) is not str or value[key] not in allowed):
            return None
    return value


class Outcome:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = []
        self.xfailed = []
        self.node_diagnostic: dict | None = None

    def pytest_runtest_logreport(self, report):
        if report.when == "call" and report.passed:
            self.passed += 1
        if report.failed:
            self.failed += 1
        if report.skipped:
            (self.xfailed if hasattr(report, "wasxfail") else self.skipped).append(report.nodeid)
        if (report.when == "call" and getattr(report, "nodeid", "") ==
                "evaluations/reliability_v050/test_keyboard_shortcut_contract.py::"
                "ShortcutContractTests::test_capture_forwards_and_modal_guard_mutation_is_detectable"):
            # Otherwise pytest hides successful-call stdout. Keep only this
            # bounded public diagnostic, even on green; never raw Node logs.
            for line in getattr(report, "capstdout", "")[:8192].splitlines():
                value = _public_node_diagnostic(line)
                if value is not None:
                    self.node_diagnostic = value
                    break

    def pytest_terminal_summary(self, terminalreporter):
        if self.node_diagnostic is not None:
            terminalreporter.write_line(NODE_DIAGNOSTIC_PREFIX + json.dumps(
                self.node_diagnostic, sort_keys=True, separators=(",", ":")))


def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt-dir", type=Path, required=True)
    parser.add_argument("--focused-only", action="store_true")
    args = parser.parse_args()
    args.receipt_dir.mkdir(parents=True, exist_ok=True)
    os.environ["RELIABILITY_V050_RECEIPTS"] = str(args.receipt_dir.resolve())
    if resource is not None:
        resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    network_guard = install_guards()
    import pytest

    source_before = software_source_identity()
    selected = [
        "evaluations/reliability_v050/test_source_identity.py",
        "evaluations/reliability_v050/test_source_path_safety.py",
        "evaluations/reliability_v050/test_subprocess_guard.py",
        "evaluations/reliability_v050/test_keyboard_shortcut_contract.py",
        "tests/unit/test_software_network_guard.py",
        "evaluations/reliability_v050/test_endurance.py",
        "evaluations/reliability_v050/test_windows_software.py",
        "tests/unit/test_reconnect.py",
        "tests/unit/test_reliability.py",
        "tests/unit/test_windows_v020_acceptance_harness.py",
        "tests/test_lifecycle.py::test_start_status_stop_status_twice",
        "tests/test_lifecycle.py::test_repeated_start_is_idempotent",
        "tests/test_lifecycle.py::test_repeated_stop_is_idempotent",
        "tests/test_lifecycle.py::test_stale_pid_never_signals_process",
        "tests/test_lifecycle.py::test_matching_start_token_but_wrong_command_is_not_owned",
        "tests/test_lifecycle.py::test_corrupt_state_never_signals_process",
        "tests/test_lifecycle.py::test_identity_failure_never_signals_or_terminates",
        "tests/test_lifecycle.py::test_windows_command_lock_initializes_empty_file",
        "tests/test_lifecycle.py::test_windows_command_lock_retries_contention_until_acquired",
        "tests/test_lifecycle.py::test_windows_command_lock_propagates_non_contention_errors",
    ]
    if not args.focused_only:
        selected += [
            "tests/unit/test_full_pipeline_scenario.py::test_deterministic_full_pipeline_scenario",
            "tests/unit/test_resilience_soak.py::test_deterministic_soak_reaches_all_terminal_states",
        ]
    outcome = Outcome()
    started = time.perf_counter()
    status = pytest.main(["-q", "-ra", "-p", "no:cacheprovider", *selected], plugins=[outcome])
    from app import pipeline_diagnostics
    from app.identity import PACKAGE_VERSION

    assert Path(pipeline_diagnostics.__file__).resolve().is_relative_to(ROOT)
    source_after = software_source_identity()
    source_unchanged = source_before == source_after
    result = {
        **source_before,
        "source_unchanged": source_unchanged,
        "status": "passed" if status == 0 and not DENIED and source_unchanged else "failed",
        "pytest_exit_code": int(status),
        "passed": outcome.passed,
        "failed": outcome.failed,
        "skipped": outcome.skipped,
        "xfailed": outcome.xfailed,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "python_version": platform.python_version(),
        "sdk_version": version("mistralai"),
        "package_version": PACKAGE_VERSION,
        # platform.system() may spawn an OS-version command on Windows.
        # This receipt needs only the host family, without probing the system.
        "host_platform": {"win32": "Windows", "darwin": "Darwin", "linux": "Linux"}.get(
            sys.platform, sys.platform
        ),
        "pipeline_module_sha256": hashlib.sha256(
            Path(pipeline_diagnostics.__file__).read_bytes()
        ).hexdigest(),
        "denied_boundary_calls": DENIED,
        "owned_fallback_ipc_pairs": network_guard.fallback_pairs_created,
        "real_provider_calls": 0,
        "native_device_calls": 0,
        "browser_processes": 0,
        "gcp_operations": 0,
        "github_or_ci_operations": 0,
        "physical_windows_pass": False,
        "two_hour_endurance_pass": False,
        "selected_tests": selected,
    }
    (args.receipt_dir / "focused-receipt.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    return 0 if result["status"] == "passed" else 1


def main():
    try:
        return _main()
    except (OSError, ValueError, subprocess.SubprocessError):
        # Source/receipt failures must never emit raw paths, exception text or
        # chained tracebacks into shareable CI logs. A failure is not a receipt.
        print(json.dumps({"status": "failed", "error": "software_evidence_unavailable"}),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
