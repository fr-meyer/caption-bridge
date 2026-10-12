"""Provider/device-free contracts for transient native input selection."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.audio_devices import SELECTION_ERROR, InputDevices
from app.config import AppConfig
from app.state import ReadinessCheck, SessionManager


def device(name, inputs=1):
    return {"name": name, "hostapi": 0, "max_input_channels": inputs,
            "default_samplerate": 48000}


def catalog():
    inventory = [device("Synthetic built-in"), device("Synthetic headset"), device("Output", 0)]
    default = [0]
    checks = []
    selection = InputDevices(lambda: inventory, lambda: default[0], lambda **kw: checks.append(kw))
    return selection, inventory, default, checks


def test_listing_does_not_open_or_check_input_and_tokens_are_transient():
    selection, _, _, checks = catalog()
    first = selection.refresh()
    assert len(first["available"]) == 2
    assert checks == []
    assert selection.refresh() == first
    other, _, _, _ = catalog()
    assert other.refresh()["available"][0]["id"] != first["available"][0]["id"]


def test_explicit_device_and_format_are_used_and_reconnect_freezes_input():
    selection, _, default, checks = catalog()
    token = selection.refresh()["available"][1]["id"]
    selection.choose(token)
    assert checks == []
    assert selection.capture_device() == 1
    assert checks == [{"device": 1, "channels": 1, "dtype": "int16", "samplerate": 16000}]
    default[0] = 0
    assert selection.capture_device() == 1
    assert selection.snapshot()["active_label"] == "Synthetic headset"


def test_default_resolves_at_start_then_keeps_original_device():
    selection, _, default, _ = catalog()
    selection.refresh()
    default[0] = 1
    selection.choose("default")
    assert selection.capture_device() == 1
    default[0] = 0
    assert selection.capture_device() == 1
    selection.reset()
    assert selection.snapshot()["selected"] == "default"
    assert selection.snapshot()["active_label"] is None
    assert selection.capture_device() == 0


@pytest.mark.parametrize("change", ["remove", "reindex", "replace"])
def test_stale_explicit_device_never_silently_routes_elsewhere(change):
    selection, inventory, _, _ = catalog()
    token = selection.refresh()["available"][1]["id"]
    if change == "remove":
        inventory.pop(1)
    elif change == "reindex":
        inventory[0], inventory[1] = inventory[1], inventory[0]
    else:
        inventory[1] = device("Different synthetic input")
    with pytest.raises(ValueError, match="Microphone selection is unavailable"):
        selection.choose(token)


def test_active_removed_input_and_metadata_failure_fail_closed():
    selection, inventory, _, _ = catalog()
    selection.choose(selection.refresh()["available"][1]["id"])
    selection.capture_device()
    inventory.pop(1)
    with pytest.raises(ValueError, match="Microphone selection is unavailable"):
        selection.capture_device()

    def fail():
        raise OSError("PRIVATE_DEVICE_ERROR")
    selection = InputDevices(fail, fail, fail)
    assert selection.refresh()["unavailable"] is True
    with pytest.raises(ValueError) as error:
        selection.capture_device()
    assert str(error.value) == SELECTION_ERROR


def test_unsupported_format_has_content_free_failure():
    def fail(**_kwargs):
        raise OSError("PRIVATE_FORMAT_DETAIL")
    selection = InputDevices(lambda: [device("Private device")], lambda: 0, fail)
    with pytest.raises(ValueError) as error:
        selection.capture_device()
    assert str(error.value) == "Selected microphone does not support the required input format."


def test_session_refresh_metadata_is_not_exported_or_journaled(tmp_path):
    from app.exporter import _write_transcript_json

    config = AppConfig(_env_file=None)
    manager = SessionManager(config)
    selection, _, _, _ = catalog()
    manager.input_devices = selection
    selection.choose(selection.refresh()["available"][1]["id"])
    selection.capture_device()
    assert manager.get_snapshot()["input_devices"]["active_label"] == "Synthetic headset"
    _write_transcript_json(tmp_path, manager.session, config)
    export = (tmp_path / "transcript.json").read_text()
    assert "Synthetic headset" not in export
    assert "input_devices" not in export
    assert selection.snapshot()["selected"] not in export
    assert "Synthetic headset" not in manager.session.model_dump_json()
    manager.session.exported = True
    asyncio.run(manager.reset())
    assert manager.get_snapshot()["input_devices"]["selected"] == "default"


@pytest.mark.parametrize("status,ready", [(0, False), (1, False), (2, False), (3, True), (99, False)])
def test_permission_readiness_is_getter_only(monkeypatch, status, ready):
    from app import audio_devices, readiness

    monkeypatch.setattr(readiness.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(audio_devices, "microphone_authorization", lambda: status)
    monkeypatch.setattr(readiness.sd, "RawInputStream", lambda **_: pytest.fail("No input before Start"))
    assert readiness._check_mic_permission().ready is ready


def test_permission_getter_exception_is_closed_without_exception_body(monkeypatch):
    from app import audio_devices, readiness

    monkeypatch.setattr(readiness.platform, "system", lambda: "Darwin")
    def fail():
        raise RuntimeError("PRIVATE_PERMISSION_DETAIL")
    monkeypatch.setattr(audio_devices, "microphone_authorization", fail)
    result = readiness._check_mic_permission()
    assert not result.ready
    assert "PRIVATE" not in result.detail


def test_capture_receives_selected_native_index_with_one_original_stream(monkeypatch):
    from app import audio

    calls = []
    stream = SimpleNamespace(start=lambda: calls.append("start"), stop=lambda: None, close=lambda: None)
    monkeypatch.setattr(audio.sd, "RawInputStream", lambda **kw: (calls.append(kw), stream)[1])
    loop = asyncio.new_event_loop()
    try:
        capture = audio.AudioCapture(16000, loop, device=7)
        capture.start()
        assert calls[0]["device"] == 7
        assert calls[0]["channels"] == 1 and calls[0]["dtype"] == "int16"
        assert calls[1:] == ["start"]
        capture.stop()
    finally:
        loop.close()


def test_invalid_start_selection_cannot_start_pipeline_or_change_session(monkeypatch):
    import app.ws as ws

    manager = SessionManager(AppConfig(_env_file=None))
    manager.input_devices = catalog()[0]
    manager.set_readiness([ReadinessCheck(name="Synthetic", key="synthetic", ready=True, detail="Ready")])
    monkeypatch.setattr(ws, "manager", manager)
    async def forbidden():
        pytest.fail("Invalid selection cannot start capture/provider pipeline")
    monkeypatch.setattr(ws, "start_pipeline", forbidden)
    queue = asyncio.Queue()
    asyncio.run(ws._handle_start({"input_device": "missing", "target_language": "fr"}, queue, ws._OutboundObsState()))
    event = queue.get_nowait()[0]
    assert event["type"] == "error" and event["message"] == SELECTION_ERROR
    assert manager.session.target_language == "en"
    assert manager.session.status == "idle_ready"
    assert "missing" not in json.dumps(event)
