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


def _allow_full_preflight_config(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "host", "127.0.0.1")
    monkeypatch.setattr(settings, "mistral_api_key", "dummy")


def test_full_preflight_maps_readiness_import_errors(monkeypatch) -> None:
    import builtins

    _allow_full_preflight_config(monkeypatch)
    real_import = builtins.__import__

    def boom(name, *args, **kwargs):
        if name == "app.readiness":
            raise RuntimeError("native boom")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", boom)
    payload, exit_code = evaluate(mode="full")
    assert payload["ok"] is False
    assert payload["reason"] == "invalid_configuration"
    assert exit_code == 2


def test_full_preflight_maps_missing_readiness_module(monkeypatch) -> None:
    import builtins

    _allow_full_preflight_config(monkeypatch)
    real_import = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "app.readiness":
            raise ModuleNotFoundError("app.readiness")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    payload, exit_code = evaluate(mode="full")
    assert payload["ok"] is False
    assert payload["reason"] == "venv_incomplete"
    assert exit_code == 2
