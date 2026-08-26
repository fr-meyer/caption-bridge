from __future__ import annotations

import json
import re
from pathlib import Path

from app.identity import PACKAGE_VERSION, runtime_identity

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_package_version_matches_pyproject() -> None:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, re.MULTILINE)
    assert match is not None
    assert match.group(1) == PACKAGE_VERSION


def test_runtime_identity_is_content_free() -> None:
    payload = runtime_identity(REPO_ROOT)
    dumped = json.dumps(payload)
    assert payload["service"] == "caption-bridge"
    assert payload["package_version"] == PACKAGE_VERSION
    assert payload["git_sha"] is None or len(payload["git_sha"]) == 40
    assert "/Users/" not in dumped
    assert "MISTRAL" not in dumped
    assert "runtime.json" not in dumped
