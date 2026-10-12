"""Run actual production JS callbacks under Node's bounded in-memory VM."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def test_production_connection_policy_with_fake_socket_clock_and_dom():
    root = Path(__file__).resolve().parents[2]
    node = shutil.which("node")
    assert node is not None, "Node is required for the offline production-JS callback check"
    result = subprocess.run(
        [node, str(root / "tests/fixtures/connection_ownership_node.cjs"), str(root / "app/static/app.js")],
        text=True, capture_output=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "tests": 7, "passed": True, "real_browser": False,
        "network": False, "audio": False, "storage": False,
    }
