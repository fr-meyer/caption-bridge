"""Installed SDK connection exercised against fake, in-memory WebSocket IO."""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from mistralai.client.models import (
    AudioFormat,
    RealtimeTranscriptionSession,
    RealtimeTranscriptionSessionCreated,
)
from mistralai.extra.realtime import RealtimeConnection

import app.transcribe as module
from app.config import AppConfig
from app.pipeline_diagnostics import PipelineDiagnostics, validate_pipeline_snapshot


class FakeSocket:
    def __init__(self, fail_send=False):
        self.queue = asyncio.Queue()
        self.closed = False
        self.fail_send = fail_send
        self.sent = []

    async def send(self, frame):
        if self.fail_send:
            raise OSError("SECRET send response, key, and device identifier")
        self.sent.append(json.loads(frame))
        if self.sent[-1]["type"] == "input_audio.end":
            self.queue.put_nowait(json.dumps({"type": "transcription.done", "model": "fake",
                "text": "synthetic", "language": "en", "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}))

    async def close(self, **_kwargs):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.queue.get()


def connection_for(socket):
    socket.queue._queue.appendleft(json.dumps({"type": "session.updated", "session": {
        "request_id": "PRIVATE-ID", "model": "voxtral-mini-transcribe-realtime-2602",
        "audio_format": {"encoding": "pcm_s16le", "sample_rate": 16000},
        "target_streaming_delay_ms": 1000,
    }}))
    session = RealtimeTranscriptionSession(request_id="PRIVATE-ID", model="fake",
                audio_format=AudioFormat(encoding="pcm_s16le", sample_rate=16000))
    return RealtimeConnection(socket, session, initial_events=[RealtimeTranscriptionSessionCreated(session=session)])


def install_client(monkeypatch, connect):
    class FakeClient:
        def __init__(self, **_kwargs):
            self.audio = SimpleNamespace(realtime=SimpleNamespace(connect=connect))
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return False
    monkeypatch.setattr(module, "Mistral", FakeClient)


@pytest.mark.parametrize("callback_owner", [True, False])
def test_transcribe_failure_has_one_log_owner_without_provider_details(monkeypatch, caplog, callback_owner):
    caplog.set_level(logging.INFO)

    async def scenario():
        socket = FakeSocket(fail_send=True)

        async def connect(**_kwargs):
            return connection_for(socket)

        install_client(monkeypatch, connect)
        errors = []

        async def audio():
            yield b"\x00\x00"

        await asyncio.wait_for(module.transcribe(audio(), AppConfig(_env_file=None),
            on_delta=lambda _text: None, on_error=errors.append if callback_owner else None), 0.2)
        assert socket.closed
        assert len(errors) == (1 if callback_owner else 0)

    asyncio.run(scenario())
    assert not any("Transcription failed:" in r.getMessage() for r in caplog.records)
    events = [json.loads(r.getMessage().split(" ", 1)[1]) for r in caplog.records
              if r.name == "app.asr_diagnostics"]
    assert len(events) == (0 if callback_owner else 1)
    if events:
        assert events[0]["event"] == "stream_failure" and events[0]["reason"] == "send_failed"
    assert "SECRET" not in caplog.text and "PRIVATE-ID" not in caplog.text


def test_successful_sdk_send_byte_accounting_and_content_free_event_types(monkeypatch):
    async def scenario():
        socket = FakeSocket()
        socket.queue.put_nowait(json.dumps({"type": "transcription.text.delta", "text": "SECRET transcript"}))
        socket.queue.put_nowait(json.dumps({"type": "provider.SECRET.event", "secret_body": "SECRET"}))
        socket.queue.put_nowait("invalid SECRET provider JSON")
        connect_kwargs = []
        async def connect(**kwargs):
            connect_kwargs.append(kwargs)
            return connection_for(socket)
        install_client(monkeypatch, connect)
        pipeline = PipelineDiagnostics()
        pipeline.set_state("connecting")
        deltas, errors, done = [], [], []
        async def audio():
            yield b"\x00\x00" * 3
            yield b"\x01\x02" * 2
        await asyncio.wait_for(module.transcribe(audio(), AppConfig(_env_file=None, asr_initial_timeout_ms=100),
            on_delta=deltas.append, on_done=lambda: done.append(True), on_error=errors.append,
            on_session_created=lambda: pipeline.set_state("ready"),
            on_sent=pipeline.record_sent, on_event=pipeline.record_event), 0.5)
        assert errors == [] and done == [True] and deltas == ["SECRET transcript"]
        assert connect_kwargs[0]["timeout_ms"] == 100
        diag = pipeline.snapshot()
        assert diag["asr"]["sent_frames"] == 2 and diag["asr"]["sent_bytes"] == 10
        assert diag["asr"]["events"] == 6
        assert diag["asr"]["event_types"] == {"session_created": 1, "session_updated": 1,
            "text_delta": 1, "done": 1, "provider_error": 0, "unknown": 2, "other": 0}
        assert validate_pipeline_snapshot(diag)
        assert "SECRET" not in json.dumps(diag) and "PRIVATE-ID" not in json.dumps(diag)
        assert socket.closed
    asyncio.run(scenario())


@pytest.mark.parametrize("frame, expected", [(b"\x00\x00", "send_failed"), (b"\x00", "invalid_audio")])
def test_sdk_send_failure_interrupts_waiting_receiver_promptly(monkeypatch, caplog, frame, expected):
    async def scenario():
        socket = FakeSocket(fail_send=True)
        async def connect(**_kwargs):
            return connection_for(socket)
        install_client(monkeypatch, connect)
        errors, done, sent = [], [], []
        async def audio():
            yield frame
            await asyncio.Event().wait()
        await asyncio.wait_for(module.transcribe(audio(), AppConfig(_env_file=None), on_delta=lambda _text: None,
            on_error=errors.append, on_done=lambda: done.append(True), on_sent=sent.append), 0.2)
        assert len(errors) == 1 and errors[0].reason == expected
        assert "SECRET" not in str(errors[0]) and "SECRET" not in caplog.text
        assert done == [] and sent == [] and socket.closed
    asyncio.run(scenario())


def test_stop_during_connect_closes_late_sdk_connection_without_ready_or_audio(monkeypatch):
    async def scenario():
        release = asyncio.Event()
        socket = FakeSocket()
        async def connect(**_kwargs):
            await release.wait()
            return connection_for(socket)
        install_client(monkeypatch, connect)
        ready, errors = [], []
        async def audio():
            yield b"\x00\x00"
        task = asyncio.create_task(module.transcribe(audio(), AppConfig(_env_file=None), on_delta=lambda _text: None,
            on_session_created=lambda: ready.append(True), on_error=errors.append))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.2)
        assert ready == [] and errors == [] and socket.sent == []
        release.set()
        async with asyncio.timeout(0.2):
            while module._pending_connection_cleanup:
                await asyncio.sleep(0)
        assert socket.closed and socket.sent == [] and ready == []
    asyncio.run(scenario())


def test_wrapped_sdk_handshake_timeout_gets_safe_initial_timeout_reason(monkeypatch, caplog):
    async def scenario():
        async def connect(**_kwargs):
            try:
                raise TimeoutError("SECRET socket details")
            except TimeoutError as cause:
                raise RuntimeError("SECRET SDK response") from cause
        install_client(monkeypatch, connect)
        errors = []
        async def audio():
            if False:
                yield b""
        await module.transcribe(audio(), AppConfig(_env_file=None), on_delta=lambda _text: None, on_error=errors.append)
        assert errors[0].reason == "initial_timeout"
        assert "SECRET" not in str(errors[0]) and "SECRET" not in caplog.text
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not module._pending_connection_cleanup
    asyncio.run(scenario())
