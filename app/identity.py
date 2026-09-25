"""Content-free package and checkout identity."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PACKAGE_VERSION = "0.2.1"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_git(*args: str, cwd: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def read_git_sha(repo_root: Path = REPO_ROOT) -> str | None:
    sha = _run_git("rev-parse", "HEAD", cwd=repo_root)
    if sha is None or len(sha) != 40 or any(char not in "0123456789abcdef" for char in sha):
        return None
    return sha


def read_git_dirty(repo_root: Path = REPO_ROOT) -> bool | None:
    output = _run_git("status", "--porcelain", cwd=repo_root)
    if output is None:
        return None
    return bool(output)


def runtime_identity(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Return versions and checkout hashes only. Never include paths or env."""
    return {
        "service": "caption-bridge",
        "package_version": PACKAGE_VERSION,
        "git_sha": read_git_sha(repo_root),
        "git_dirty": read_git_dirty(repo_root),
        "python": sys.version.split()[0],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()
    payload = runtime_identity()
    if args.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        sha = payload["git_sha"] or "unknown"
        dirty = " dirty" if payload["git_dirty"] else ""
        print(f"{payload['package_version']} {sha}{dirty} py{payload['python']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
