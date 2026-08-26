"""Build a content-free Caption Bridge support bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.identity import REPO_ROOT, runtime_identity
from app.lifecycle import LifecycleController
from app.reliability import load_history
from scripts.reliability_report import build_report
from scripts.runtime_preflight import evaluate

_CONTROLLER_KEEP = (
    "status",
    "message",
    "exit_code",
    "running",
    "healthy",
    "pid",
    "host",
    "port",
)


def _controller_status(repo_root: Path) -> dict[str, Any]:
    result = LifecycleController(repo_root).execute("status")
    payload = result.public_dict()
    return {key: payload[key] for key in _CONTROLLER_KEEP if key in payload}


def _reliability(repo_root: Path) -> dict[str, Any] | None:
    history_dir = repo_root / "runs" / "reliability"
    if not history_dir.is_dir():
        return None
    sessions, soaks, skipped = load_history(history_dir)
    return build_report(sessions, soaks, skipped=skipped)


def build_bundle(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    preflight, _exit_code = evaluate(mode="software")
    return {
        "schema_version": 1,
        "identity": runtime_identity(repo_root),
        "preflight": preflight,
        "controller": _controller_status(repo_root),
        "reliability": _reliability(repo_root),
    }


def assert_content_free(payload: dict[str, Any]) -> None:
    dumped = json.dumps(payload)
    forbidden = (
        "MISTRAL_API_KEY",
        "runtime.json",
        "caption-bridge.log",
        "/Users/",
        "/home/",
        "Library/Caches",
        "Library/Logs",
    )
    for token in forbidden:
        if token in dumped:
            raise ValueError(f"support bundle leaked {token}")


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
            f"{identity['package_version']} {identity['git_sha'] or 'unknown'}"
        )
        print(f"preflight: {payload['preflight']['reason']}")
        print(f"controller: {payload['controller']['status']}")
        reliability = payload["reliability"]
        if reliability is None:
            print("reliability: none")
        else:
            print(f"reliability_sessions: {reliability['sessions']['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
