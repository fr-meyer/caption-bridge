"""Check import safety with a genuinely unavailable backend in a fresh process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "headless_audio_import.py"


@pytest.mark.parametrize("mode", ["portaudio_unavailable", "backend_missing", "no_devices"])
def test_import_without_audio_preserves_runtime_failure(mode, tmp_path):
    (tmp_path / "app" / "static").mkdir(parents=True)
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("MISTRAL_", "OPENAI_"))
           and "PROXY" not in key.upper()}
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(FIXTURE), str(ROOT), mode],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "mode": mode, "import_without_native_audio": True,
        "runtime_failure_preserved": True, "external_calls": [],
    }
