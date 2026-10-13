from __future__ import annotations

import asyncio
from types import SimpleNamespace

import app.transcribe as transcribe_module


class _ProviderEvent:
    def __str__(self) -> str:
        return "sensitive provider response body"


class _Events:
    def __init__(self) -> None:
        self._sent = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return _ProviderEvent()


class _Realtime:
    async def connect(self, **_kwargs):
        return _Connection()


class _Connection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def __aiter__(self):
        return _Events()

    async def flush_audio(self):
        pass

    async def end_audio(self):
        pass

    async def close(self):
        pass


class _Client:
    def __init__(self, **_kwargs) -> None:
        self.audio = SimpleNamespace(realtime=_Realtime())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


async def _empty_audio():
    if False:
        yield b""


def test_provider_error_event_is_normalized_to_exception(monkeypatch) -> None:
    monkeypatch.setattr(transcribe_module, "Mistral", _Client)
    monkeypatch.setattr(
        transcribe_module, "RealtimeTranscriptionError", _ProviderEvent
    )
    config = SimpleNamespace(
        mistral_api_key="test",
        realtime_base_url=None,
        audio_sample_rate=16000,
        transcribe_model="test-model",
        target_streaming_delay_ms=1000,
        asr_initial_timeout_ms=100,
    )
    errors: list[Exception] = []

    asyncio.run(
        transcribe_module.transcribe(
            audio_stream=_empty_audio(),
            config=config,
            on_delta=lambda _text: None,
            on_error=errors.append,
        )
    )

    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert str(errors[0]) == "Realtime transcription provider error"
    assert "sensitive provider response body" not in str(errors[0])
