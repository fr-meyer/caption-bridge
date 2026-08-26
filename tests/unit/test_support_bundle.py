from __future__ import annotations

from pathlib import Path

from scripts.support_bundle import assert_content_free, build_bundle

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_support_bundle_is_content_free() -> None:
    payload = build_bundle(REPO_ROOT)
    assert payload["schema_version"] == 1
    assert payload["identity"]["service"] == "caption-bridge"
    assert payload["controller"]["status"]
    assert "runtime_state_path" not in payload["controller"]
    assert "log_path" not in payload["controller"]
    assert_content_free(payload)
