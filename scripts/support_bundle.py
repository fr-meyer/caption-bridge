"""Build a content-free Caption Bridge support bundle."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

from app.identity import REPO_ROOT, runtime_identity
from app.lifecycle import LifecycleController
from app.reliability import load_history
from scripts.reliability_report import build_report
from scripts.runtime_preflight import evaluate

_TOKEN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_VERSION = re.compile(r"^[0-9]+(\.[0-9]+){1,3}([a-zA-Z0-9._-]{0,32})?$")
_PY_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_TREND_KEYS = (
    "sessions",
    "average_duration_ms",
    "reconnect_cycles_per_session",
    "reconnect_downtime_ms_per_session",
    "queue_loss_events_per_session",
    "translation_degraded_rate",
    "export_success_rate",
)
_FORBIDDEN_SNIPPETS = (
    "MISTRAL_API_KEY",
    "sk-",
    "runtime.json",
    "caption-bridge.log",
    "/Users/",
    "/home/",
    "/private/",
    "C:\\",
    "C:/",
    "Library/Caches",
    "Library/Logs",
)


def _token(value: Any) -> str | None:
    if isinstance(value, str) and _TOKEN.fullmatch(value):
        return value
    return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _token_number_map(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, int | float] = {}
    for key, item in value.items():
        token = _token(key)
        number = _number(item)
        if token is not None and number is not None:
            cleaned[token] = number
    return cleaned


def _trend_window(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, int | float] = {}
    for key in _TREND_KEYS:
        number = _number(value.get(key))
        if number is not None:
            cleaned[key] = number
    return cleaned


def sanitize_identity(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"service": "caption-bridge"}
    payload: dict[str, Any] = {"service": "caption-bridge"}
    version = raw.get("package_version")
    if isinstance(version, str) and _VERSION.fullmatch(version):
        payload["package_version"] = version
    sha = raw.get("git_sha")
    if isinstance(sha, str) and _SHA.fullmatch(sha):
        payload["git_sha"] = sha
    dirty = _bool(raw.get("git_dirty"))
    if dirty is not None:
        payload["git_dirty"] = dirty
    python = raw.get("python")
    if isinstance(python, str) and _PY_VERSION.fullmatch(python):
        payload["python"] = python
    return payload


def sanitize_preflight(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"ok": False, "reason": "invalid_configuration"}
    payload: dict[str, Any] = {}
    ok = _bool(raw.get("ok"))
    if ok is not None:
        payload["ok"] = ok
    reason = _token(raw.get("reason"))
    if reason is not None:
        payload["reason"] = reason
    mode = _token(raw.get("mode"))
    if mode is not None:
        payload["mode"] = mode
    if raw.get("host") == "127.0.0.1":
        payload["host"] = "127.0.0.1"
    port = _int(raw.get("port"))
    if port is not None and 1 <= port <= 65535:
        payload["port"] = port
    if "identity" in raw:
        payload["identity"] = sanitize_identity(raw.get("identity"))
    return payload


def sanitize_controller(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"status": "unknown"}
    payload: dict[str, Any] = {}
    status = _token(raw.get("status"))
    payload["status"] = status or "unknown"
    exit_code = _int(raw.get("exit_code"))
    if exit_code is not None:
        payload["exit_code"] = exit_code
    running = _bool(raw.get("running"))
    if running is not None:
        payload["running"] = running
    healthy = _bool(raw.get("healthy"))
    if healthy is not None:
        payload["healthy"] = healthy
    pid = _int(raw.get("pid"))
    if pid is not None and pid > 0:
        payload["pid"] = pid
    if raw.get("host") == "127.0.0.1":
        payload["host"] = "127.0.0.1"
    port = _int(raw.get("port"))
    if port is not None and 1 <= port <= 65535:
        payload["port"] = port
    return payload


def sanitize_reliability(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return {"schema_version": 1, "sessions": {"total": 0}, "skipped_records": 0}
    sessions_raw = raw.get("sessions") if isinstance(raw.get("sessions"), dict) else {}
    soaks_raw = raw.get("soaks") if isinstance(raw.get("soaks"), dict) else {}
    trend_raw = raw.get("trend") if isinstance(raw.get("trend"), dict) else {}
    queues_raw = (
        sessions_raw.get("queues") if isinstance(sessions_raw.get("queues"), dict) else {}
    )
    payload = {
        "schema_version": 1,
        "sessions": {
            "total": _int(sessions_raw.get("total")) or 0,
            "duration_ms_total": _int(sessions_raw.get("duration_ms_total")) or 0,
            "translation": _token_number_map(sessions_raw.get("translation")),
            "reconnect": _token_number_map(sessions_raw.get("reconnect")),
            "queues": {
                "totals": _token_number_map(queues_raw.get("totals")),
                "peak_depth": _token_number_map(queues_raw.get("peak_depth")),
            },
            "export_outcomes": _token_number_map(sessions_raw.get("export_outcomes")),
        },
        "trend": {
            "window_size": _int(trend_raw.get("window_size")) or 0,
            "recent": _trend_window(trend_raw.get("recent")),
            "previous": _trend_window(trend_raw.get("previous")),
            "delta": _trend_window(trend_raw.get("delta")),
        },
        "soaks": {
            "total": _int(soaks_raw.get("total")) or 0,
            "by_type": _token_number_map(soaks_raw.get("by_type")),
            "passed_by_type": _token_number_map(soaks_raw.get("passed_by_type")),
        },
        "skipped_records": _int(raw.get("skipped_records")) or 0,
    }
    return payload


def _controller_status(repo_root: Path) -> dict[str, Any]:
    result = LifecycleController(repo_root).execute("status")
    return sanitize_controller(result.public_dict())


def _reliability(repo_root: Path) -> dict[str, Any] | None:
    history_dir = repo_root / "runs" / "reliability"
    if not history_dir.is_dir():
        return None
    sessions, soaks, skipped = load_history(history_dir)
    return sanitize_reliability(
        build_report(sessions, soaks, skipped=skipped)
    )


def build_bundle(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    preflight, _exit_code = evaluate(mode="software")
    return {
        "schema_version": 1,
        "identity": sanitize_identity(runtime_identity(repo_root)),
        "preflight": sanitize_preflight(preflight),
        "controller": _controller_status(repo_root),
        "reliability": _reliability(repo_root),
    }


def assert_content_free(payload: dict[str, Any]) -> None:
    dumped = json.dumps(payload)
    for token in _FORBIDDEN_SNIPPETS:
        if token in dumped:
            raise ValueError("support bundle leaked forbidden token")
    if isinstance(payload.get("controller"), dict) and "message" in payload["controller"]:
        raise ValueError("support bundle leaked controller message")
    reliability = payload.get("reliability") or {}
    sessions = reliability.get("sessions") if isinstance(reliability, dict) else None
    if isinstance(sessions, dict) and "recent" in sessions:
        raise ValueError("support bundle leaked recent session records")
    soaks = reliability.get("soaks") if isinstance(reliability, dict) else None
    if isinstance(soaks, dict) and "recent" in soaks:
        raise ValueError("support bundle leaked recent soak records")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()
    payload = build_bundle()
    assert_content_free(payload)
    if args.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        identity = payload["identity"]
        print(
            "Caption Bridge support bundle (content-free) "
            f"{identity.get('package_version', 'unknown')} "
            f"{identity.get('git_sha', 'unknown')}"
        )
        print(f"preflight: {payload['preflight'].get('reason', 'unknown')}")
        print(f"controller: {payload['controller']['status']}")
        reliability = payload["reliability"]
        if reliability is None:
            print("reliability: none")
        else:
            print(f"reliability_sessions: {reliability['sessions']['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
