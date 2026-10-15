"""Export small aggregate measurements before the ephemeral container exits."""
from __future__ import annotations

import json
import os
from pathlib import Path


def pytest_sessionfinish(session, exitstatus) -> None:
    directory = Path(os.environ.get("SPEED_EVIDENCE_DIR", "/tmp/speed-evaluation-evidence"))
    measurements = [json.loads(path.read_text()) for path in sorted(directory.glob("*.json"))]
    print("\nSPEED_EVIDENCE_REPORT=" + json.dumps({
        "pytest_exit_status": int(exitstatus),
        "measurements": measurements,
        "constraints": {"provider_requests": 0, "microphone_access": False,
                        "audible_output": False, "raw_audio_saved": False},
    }, sort_keys=True))
