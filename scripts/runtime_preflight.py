"""Content-free dependency, configuration, and microphone preflight."""

from __future__ import annotations

import argparse
import json
from typing import Any


def evaluate() -> tuple[dict[str, Any], int]:
    try:
        from app.config import settings
        from app.readiness import _check_mic_available, _check_mic_permission
    except ModuleNotFoundError:
        return {"ok": False, "reason": "venv_incomplete"}, 2
    except Exception:
        return {"ok": False, "reason": "invalid_configuration"}, 2

    base = {"host": settings.host, "port": settings.port}
    if not settings.mistral_api_key:
        return {**base, "ok": False, "reason": "configuration_missing"}, 2
    if not _check_mic_available().ready:
        return {**base, "ok": False, "reason": "microphone_unavailable"}, 2
    if not _check_mic_permission().ready:
        return {**base, "ok": False, "reason": "microphone_permission"}, 2
    return {**base, "ok": True, "reason": "ready"}, 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    payload, exit_code = evaluate()
    if args.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        print("ready" if payload["ok"] else f"not ready: {payload['reason']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
