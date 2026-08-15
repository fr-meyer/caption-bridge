"""On-demand start, status, and stop commands for Caption Bridge."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.lifecycle import LifecycleController


def _render_human(payload: dict[str, object]) -> None:
    print(f"{payload['status']}: {payload['message']}")
    details = [
        f"state={payload['runtime_state_path']}",
        f"log={payload['log_path']}",
    ]
    if "pid" in payload:
        details.append(f"pid={payload['pid']}")
    if "host" in payload and "port" in payload:
        details.append(f"endpoint=http://{payload['host']}:{payload['port']}/")
    print(" ".join(details))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "status", "stop"))
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--start-timeout", type=float, default=15.0)
    parser.add_argument("--stop-timeout", type=float, default=10.0)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    controller = LifecycleController(
        repo_root,
        start_timeout=max(0.1, args.start_timeout),
        stop_timeout=max(0.1, args.stop_timeout),
    )
    result = controller.execute(args.command)
    payload = result.public_dict()
    if args.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        _render_human(payload)
    return int(result.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
