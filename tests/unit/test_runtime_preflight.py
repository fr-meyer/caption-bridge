from __future__ import annotations

import json

from scripts.runtime_preflight import evaluate


def test_software_preflight_reports_identity_without_microphone() -> None:
    payload, exit_code = evaluate(mode="software")
    dumped = json.dumps(payload)
    assert payload["mode"] == "software"
    assert "identity" in payload
    assert payload["identity"]["service"] == "caption-bridge"
    assert "/Users/" not in dumped
    assert "MISTRAL_API_KEY" not in dumped
    assert payload["reason"] in {
        "software_ready",
        "configuration_missing",
        "invalid_configuration",
        "venv_incomplete",
        "non_loopback_refused",
    }
    if payload["ok"]:
        assert exit_code == 0
        assert payload["host"] == "127.0.0.1"
    else:
        assert exit_code == 2
