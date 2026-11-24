"""Provider-free handler regressions, not physical/output acceptance."""
import asyncio
from unittest.mock import Mock

import pytest

from app import ws
from app.config import AppConfig
from app.state import SessionManager


@pytest.mark.parametrize("value,closed", [(False, False), (True, True), (None, True), (0, True)])
def test_only_explicit_legacy_state_allows_output(monkeypatch, value, closed):
    monkeypatch.setattr(ws, "native_capture_selected", lambda: value)
    assert ws._native_output_closed() is closed


def test_absent_selector_preserves_legacy_and_errors_fail_closed(monkeypatch):
    monkeypatch.setattr(ws, "native_capture_selected", None)
    assert not ws._native_output_closed()
    def unavailable():
        raise RuntimeError("private detail")
    monkeypatch.setattr(ws, "native_capture_selected", unavailable)
    assert ws._native_output_closed()


def test_selected_native_blocks_every_output_control_but_allows_mute(monkeypatch):
    dispatcher = Mock()
    manager = SessionManager(AppConfig(_env_file=None, MISTRAL_API_KEY=""))
    manager.session.status = "idle_ready"
    manager.checks = []
    manager.set_tts_dispatcher(dispatcher)
    monkeypatch.setattr(ws, "manager", manager)
    monkeypatch.setattr(ws, "native_capture_selected", lambda: True)
    async def scenario():
        queue = asyncio.Queue()
        obs = ws._OutboundObsState()
        await ws._handle_tts_audio_enabled()
        ws._handle_tts_catch_up({"tts_epoch": 1})
        await ws._handle_tts_mute({"muted": False}, queue, obs)
        await ws._handle_tts_replay({"seq": 1}, queue, obs)
        await ws._handle_start({"tts_muted": False}, queue, obs)
        await ws._handle_new_session({"tts_muted": False}, queue, obs)
        dispatcher.set_audio_unlocked.assert_not_called()
        dispatcher.catch_up.assert_not_called()
        dispatcher.set_muted.assert_not_called()
        assert queue.qsize() == 4
        while not queue.empty():
            message, _ = queue.get_nowait()
            assert message == {"type": "error", "message": "Native capture requires muted output."}
        await ws._handle_tts_mute({"muted": True}, queue, obs)
        dispatcher.set_muted.assert_called_once_with(True)
    asyncio.run(scenario())


def test_main_wires_guard_to_actual_factory_selection(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_native_capture_factory", None)
    assert not ws._native_output_closed()
    monkeypatch.setattr(main, "_native_capture_factory", object())
    assert ws._native_output_closed()
