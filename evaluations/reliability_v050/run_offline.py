"""Bounded local-only reliability checks; deny native/provider/browser IO by default."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
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
        allowed = {"git", "node", "node.exe", "pwsh"}
        if not isinstance(argv, (list, tuple)) or Path(str(argv[0])).name not in allowed:
            return forbidden("unapproved_process")(argv)
        return original_popen(argv, *args, **kwargs)

    subprocess.Popen = popen
    return network_guard


class Outcome:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = []
        self.xfailed = []

    def pytest_runtest_logreport(self, report):
        if report.when == "call" and report.passed:
            self.passed += 1
        if report.failed:
            self.failed += 1
        if report.skipped:
            (self.xfailed if hasattr(report, "wasxfail") else self.skipped).append(report.nodeid)


def main():
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

    selected = [
        "tests/unit/test_software_network_guard.py",
        "evaluations/reliability_v050/test_endurance.py",
        "evaluations/reliability_v050/test_windows_software.py",
        "tests/unit/test_reconnect.py",
        "tests/unit/test_reliability.py",
        "tests/unit/test_windows_v020_acceptance_harness.py",
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
    status = pytest.main(["-q", "-p", "no:cacheprovider", *selected], plugins=[outcome])
    from app import pipeline_diagnostics

    assert Path(pipeline_diagnostics.__file__).resolve().is_relative_to(ROOT)
    result = {
        "status": "passed" if status == 0 and not DENIED else "failed",
        "pytest_exit_code": int(status),
        "passed": outcome.passed,
        "failed": outcome.failed,
        "skipped": outcome.skipped,
        "xfailed": outcome.xfailed,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "python_version": platform.python_version(),
        "sdk_version": version("mistralai"),
        "package_version": "0.5.0",
        "host_platform": platform.system(),
        "source_head": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
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


if __name__ == "__main__":
    raise SystemExit(main())
