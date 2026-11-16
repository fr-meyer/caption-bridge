"""The guarded receipt writer must not spawn an OS-version command on Windows."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/offline_receipt_metadata.py"


def test_guarded_receipt_without_os_version_probe(tmp_path):
    env = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("MISTRAL_", "OPENAI_"))
        and "PROXY" not in key.upper()
    }
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(FIXTURE), str(ROOT), str(tmp_path)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    expected = {"win32": "Windows", "darwin": "Darwin", "linux": "Linux"}.get(
        sys.platform, sys.platform
    )
    assert json.loads(result.stdout) == {
        "host_platform": expected, "suite_executed": False,
    }
