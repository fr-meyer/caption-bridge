from __future__ import annotations

import json
from pathlib import Path

from scripts.support_bundle import (
    assert_content_free,
    build_bundle,
    sanitize_controller,
    sanitize_reliability,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_support_bundle_is_content_free() -> None:
    payload = build_bundle(REPO_ROOT)
    assert payload["schema_version"] == 1
    assert payload["identity"]["service"] == "caption-bridge"
    assert payload["controller"]["status"]
    assert "runtime_state_path" not in payload["controller"]
    assert "log_path" not in payload["controller"]
    assert "message" not in payload["controller"]
    assert_content_free(payload)


def test_controller_omits_message_paths_and_foreign_hosts() -> None:
    cleaned = sanitize_controller(
        {
            "status": "stopped",
            "message": "failed at /Users/frmeyer/secret caption hello",
            "runtime_state_path": "/Users/frmeyer/Library/Caches/CaptionBridge/runtime.json",
            "log_path": "C:\\Users\\frmeyer\\caption-bridge.log",
            "running": False,
            "exit_code": 0,
            "host": "0.0.0.0",
            "port": 8765,
            "pid": 4321,
        }
    )
    dumped = json.dumps(cleaned)
    assert cleaned == {
        "status": "stopped",
        "exit_code": 0,
        "running": False,
        "pid": 4321,
        "port": 8765,
    }
    assert "message" not in cleaned
    assert "/Users/" not in dumped
    assert "C:\\\\" not in dumped
    assert "hello" not in dumped


def test_reliability_allowlist_drops_content_and_recent_records() -> None:
    cleaned = sanitize_reliability(
        {
            "schema_version": 1,
            "sessions": {
                "total": 2,
                "duration_ms_total": 5000,
                "translation": {
                    "total": 4,
                    "failed": 1,
                    "secret": "sk-live-not-a-real-key",
                },
                "reconnect": {"cycles": 1},
                "queues": {
                    "totals": {"audio_dropped": 0},
                    "peak_depth": {"audio": 2},
                },
                "export_outcomes": {"succeeded": 2, "note": "keep this caption"},
                "recent": [
                    {
                        "session_id": "sess-1",
                        "caption": "bonjour le monde",
                        "path": "/private/var/tmp/leak",
                    }
                ],
            },
            "trend": {
                "window_size": 5,
                "recent": {"sessions": 2, "export_success_rate": 1.0},
                "previous": {"sessions": 1},
                "delta": {"export_success_rate": 0.0},
            },
            "soaks": {
                "total": 1,
                "by_type": {"optional_endurance": 1},
                "passed_by_type": {"optional_endurance": 0},
                "recent": [
                    {
                        "transcript": "secret talk",
                        "path": "/private/var/tmp/x",
                    }
                ],
            },
            "skipped_records": 0,
        }
    )
    assert cleaned is not None
    dumped = json.dumps(cleaned)
    assert cleaned["sessions"]["total"] == 2
    assert cleaned["sessions"]["translation"] == {"total": 4, "failed": 1}
    assert "recent" not in cleaned["sessions"]
    assert "recent" not in cleaned["soaks"]
    assert "sk-live" not in dumped
    assert "bonjour" not in dumped
    assert "/private/" not in dumped
    assert "caption" not in dumped
    assert "secret talk" not in dumped
    assert_content_free(
        {
            "schema_version": 1,
            "identity": {"service": "caption-bridge"},
            "preflight": {"ok": True, "reason": "software_ready"},
            "controller": {"status": "stopped"},
            "reliability": cleaned,
        }
    )


def test_mac_cli_preflight_uses_make() -> None:
    text = (REPO_ROOT / "docs" / "mac-cli.md").read_text(encoding="utf-8")
    assert "python3 -m scripts.runtime_preflight" not in text
    assert "make preflight" in text
