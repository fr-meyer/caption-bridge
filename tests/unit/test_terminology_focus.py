"""Bounded offline checks of production terminology focus callbacks."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def test_terminology_focus_with_synthetic_dom() -> None:
    root = Path(__file__).resolve().parents[2]
    node = shutil.which("node")
    assert node is not None, "Node is required for the offline terminology-focus check"
    result = subprocess.run(
        [node, str(root / "tests/fixtures/terminology_focus_node.cjs")],
        text=True, capture_output=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "tests": 18, "passed": True, "real_browser": False, "network": False,
        "audio": False, "permissions": False, "storage": False,
    }
