"""Offline application-hook tests. No SDK/provider/native process is started."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import app.main as main
from app.native_capture import NativeCaptureFactory
from app.state import SessionManager
from scripts.attended_native_launch import EmergencyStop
from test_caption_native_pcm import make_capture


def test_default_remains_legacy_but_selected_unadmitted_native_never_falls_back():
    async def scenario():
        manager = SessionManager(main.settings)
        legacy = object()
        manager.input_devices = legacy
        with patch.object(main, "manager", manager), patch.object(main, "_audio", None), \
             patch.object(main, "_transcribe_task", None), \
             patch.object(main, "_native_capture_factory", None), \
             patch.object(main, "_legacy_input_devices", None), \
             patch.object(main.tts_dispatcher, "_muted", True), \
             patch.object(main, "AudioCapture") as legacy_capture, \
             patch.object(main, "transcribe", new_callable=AsyncMock) as provider:
            assert main.native_capture_status()["status"] == "disabled"
            main.configure_native_capture(NativeCaptureFactory())
            assert main.native_capture_status()["physical_acceptance"] is False
            with pytest.raises(RuntimeError, match="not_admitted"):
                await main._start_pipeline()
            legacy_capture.assert_not_called()
            provider.assert_not_called()
            assert main._audio is None
            main.configure_native_capture(None)
            assert manager.input_devices is legacy
    asyncio.run(scenario())


def test_unmuted_native_cannot_consume_or_capture():
    with patch.object(main, "_native_capture_factory", NativeCaptureFactory()), \
         patch.object(main.tts_dispatcher, "_muted", False), \
         patch.object(main, "AudioCapture") as legacy:
        with pytest.raises(RuntimeError, match="requires_muted_output"):
            main._make_capture(1, None, {})
        legacy.assert_not_called()


def test_native_wait_is_owned_by_transcription_task_not_start_handler():
    async def scenario():
        emergency = EmergencyStop()
        capture = make_capture(asyncio.get_running_loop(), emergency)
        ready = asyncio.Event()
        errors = []
        async def wait_started():
            await ready.wait()
        with patch.object(capture, "wait_started", wait_started), \
             patch.object(main, "_pipeline_generation", 10), \
             patch.object(main, "_pipeline_stopping", False), \
             patch.object(main, "transcribe", new_callable=AsyncMock) as provider:
            task = asyncio.create_task(main._transcribe_capture(capture, 10, on_error=errors.append))
            await asyncio.sleep(0)
            provider.assert_not_called()
            ready.set()
            await task
            provider.assert_awaited_once()
            assert errors == []
        emergency.close()
    asyncio.run(scenario())


def test_failed_or_stale_native_start_never_reaches_provider():
    async def scenario():
        emergency = EmergencyStop()
        capture = make_capture(asyncio.get_running_loop(), emergency)
        for stale in (True, False):
            errors = []
            with patch.object(capture, "wait_started", new_callable=AsyncMock,
                              side_effect=RuntimeError("PRIVATE-NATIVE-DETAIL")), \
                 patch.object(main, "_pipeline_generation", 11 if stale else 10), \
                 patch.object(main, "_pipeline_stopping", False), \
                 patch.object(main, "transcribe", new_callable=AsyncMock) as provider:
                await main._transcribe_capture(capture, 10, on_error=errors.append)
                provider.assert_not_called()
                assert len(errors) == (0 if stale else 1)
                assert not errors or errors[0].reason == "microphone_error"
        emergency.close()
    asyncio.run(scenario())


def test_transport_selection_requires_idle_exact_factory():
    with patch.object(main, "_audio", object()):
        with pytest.raises(RuntimeError, match="requires_idle"):
            main.configure_native_capture(NativeCaptureFactory())
    with patch.object(main, "_audio", None), patch.object(main, "_transcribe_task", None):
        with pytest.raises(TypeError):
            main.configure_native_capture(object())
