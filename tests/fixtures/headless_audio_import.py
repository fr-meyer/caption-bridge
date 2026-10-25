"""Fresh-process audio import regression; no native devices or outbound IO."""

from __future__ import annotations

import asyncio
import builtins
import json
import os
import socket
import subprocess
import sys
from types import ModuleType

sys.path.insert(0, sys.argv[1])
mode = sys.argv[2]
assert mode in {"portaudio_unavailable", "backend_missing", "no_devices"}
for key in list(os.environ):
    if key.upper().startswith(("MISTRAL_", "OPENAI_")) or "PROXY" in key.upper():
        os.environ.pop(key)

from pydantic_settings.sources import DotEnvSettingsSource  # noqa: E402

DotEnvSettingsSource._read_env_files = lambda _self: {}
external_calls = []


def forbidden(*_args, **_kwargs):
    external_calls.append("external_io")
    raise AssertionError("external_io_denied")


socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.socket.sendto = forbidden
subprocess.Popen = forbidden


class PortAudioError(RuntimeError):
    pass


native_error = PortAudioError("Synthetic PulseAudio unavailable or no input device")
missing_error = ModuleNotFoundError("Synthetic missing sounddevice", name="sounddevice")
backend = ModuleType("sounddevice")
backend.query_devices = lambda: []
backend.default = type("Default", (), {"device": (-1, -1)})()
backend.check_input_settings = forbidden


def fail_stream(**_kwargs):
    raise native_error


backend.RawInputStream = fail_stream
import_attempts = []
original_import = builtins.__import__


def guarded_import(name, *args, **kwargs):
    if name == "sounddevice":
        import_attempts.append(name)
        if mode == "portaudio_unavailable":
            raise native_error
        if mode == "backend_missing":
            raise missing_error
        return backend
    return original_import(name, *args, **kwargs)


builtins.__import__ = guarded_import

from app import audio, audio_devices, main, readiness  # noqa: E402

catalog = audio_devices.native_input_devices()
loop = asyncio.new_event_loop()
capture = audio.AudioCapture(16000, loop)
assert import_attempts == [], "Import/construction must not initialize native audio"
assert asyncio.run(main.healthz())["status"] == "ok"
assert not readiness._check_mic_available().ready
snapshot = catalog.refresh()
assert snapshot["available"] == []
assert snapshot["unavailable"] is (mode != "no_devices")
try:
    catalog.capture_device()
except ValueError as exc:
    assert str(exc) == audio_devices.SELECTION_ERROR
else:
    raise AssertionError("Unavailable input must prevent capture selection")

expected = missing_error if mode == "backend_missing" else native_error
try:
    capture.start()
except Exception as exc:
    assert exc is expected, "Capture must propagate the original backend failure"
else:
    raise AssertionError("Unavailable native capture must fail")
capture.stop()
loop.close()


async def failed_pipeline():
    # Isolate the capture-open failure after selection validation.
    main.manager.input_devices = None
    try:
        await main._start_pipeline()
    except Exception as exc:
        assert exc is expected
    else:
        raise AssertionError("Pipeline must propagate native capture failure")
    diagnostics = main.manager.get_snapshot()["pipeline_diagnostics"]
    assert diagnostics["asr"]["state"] == "failed"
    assert diagnostics["asr"]["reason"] == "microphone_error"
    assert not diagnostics["capture"]["active"]
    assert main._audio is None and main._transcribe_task is None


asyncio.run(failed_pipeline())
assert import_attempts and external_calls == []
print(json.dumps({"mode": mode, "import_without_native_audio": True,
                  "runtime_failure_preserved": True, "external_calls": external_calls}))
