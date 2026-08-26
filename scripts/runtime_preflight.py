"""Content-free dependency, configuration, and microphone preflight."""

from __future__ import annotations

import argparse
import json
from typing import Any

from app.identity import runtime_identity


def evaluate(*, mode: str = "full") -> tuple[dict[str, Any], int]:
    if mode not in {"full", "software"}:
        raise ValueError("mode must be full or software")

    identity = runtime_identity()
    try:
        from app.config import settings
    except ModuleNotFoundError:
        return {"ok": False, "reason": "venv_incomplete", "identity": identity}, 2
    except Exception:
        return {"ok": False, "reason": "invalid_configuration", "identity": identity}, 2

    base: dict[str, Any] = {
        "host": settings.host,
        "port": settings.port,
        "identity": identity,
        "mode": mode,
    }
    if settings.host != "127.0.0.1":
        return {**base, "ok": False, "reason": "non_loopback_refused"}, 2
    if not settings.mistral_api_key:
        return {**base, "ok": False, "reason": "configuration_missing"}, 2
    if mode == "software":
        return {**base, "ok": True, "reason": "software_ready"}, 0

    try:
        from app.readiness import _check_mic_available, _check_mic_permission
    except ModuleNotFoundError:
        return {**base, "ok": False, "reason": "venv_incomplete"}, 2
    except Exception:
        return {**base, "ok": False, "reason": "invalid_configuration"}, 2

    if not _check_mic_available().ready:
        return {**base, "ok": False, "reason": "microphone_unavailable"}, 2
    if not _check_mic_permission().ready:
        return {**base, "ok": False, "reason": "microphone_permission"}, 2
    return {**base, "ok": True, "reason": "ready"}, 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument(
        "--software",
        action="store_true",
        help="Skip microphone checks for GCP or support-bundle use",
    )
    args = parser.parse_args()

    payload, exit_code = evaluate(mode="software" if args.software else "full")
    if args.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        print("ready" if payload["ok"] else f"not ready: {payload['reason']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
