"""Exercise receipt generation in isolation, without rerunning the selected suite."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def main():
    root, receipt_dir = (Path(value).resolve() for value in sys.argv[1:])
    sys.path.insert(0, str(root))
    import pytest

    spec = importlib.util.spec_from_file_location(
        "offline_receipt_runner", root / "evaluations/reliability_v050/run_offline.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    original_install = runner.install_guards

    def install_without_os_version_probe():
        guard = original_install()

        def forbidden_version_probe():
            raise AssertionError("receipt must not probe the OS version")

        runner.platform.system = forbidden_version_probe
        return guard

    selections = []

    def selected_suite_stub(args, plugins):
        # This fixture checks reporting only; it must not claim any suite execution.
        selections.append(args)
        assert plugins[0].passed == 0
        return 0

    runner.install_guards = install_without_os_version_probe
    pytest.main = selected_suite_stub
    sys.argv = [str(spec.origin), "--receipt-dir", str(receipt_dir)]
    assert runner.main() == 0
    receipt = json.loads((receipt_dir / "focused-receipt.json").read_text())
    assert len(selections) == 1
    assert receipt["status"] == "passed"
    assert receipt["passed"] == receipt["failed"] == 0
    assert receipt["denied_boundary_calls"] == []
    print(json.dumps({"host_platform": receipt["host_platform"], "suite_executed": False}))


if __name__ == "__main__":
    main()
