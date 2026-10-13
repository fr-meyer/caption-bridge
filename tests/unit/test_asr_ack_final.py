"""ACK admission and final-only text through the installed SDK, using fake IO."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
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
from app.pipeline_diagnostics import AsrProtocolDiagnostics, validate_protocol_snapshot
from app.reliability import ReliabilityTracker, validate_session_record
from app.state import Session

MODEL = "voxtral-mini-transcribe-realtime-2602"


def updated(*, delay="omitted", model=MODEL, rate=16000, encoding="pcm_s16le"):
    session = {
        "request_id": "PRIVATE request identifier",
        "model": model,
        "audio_format": {"encoding": encoding, "sample_rate": rate},
    }
    if delay != "omitted":
        session["target_streaming_delay_ms"] = delay
    return {"type": "session.updated", "session": session}


def done(text="synthetic final result", usage=None):
    return {
        "type": "transcription.done",
        "model": MODEL,
        "text": text,
        "language": None,
        "usage": {} if usage is None else usage,
    }


class Socket:
    def __init__(self, terminal=None):
        self.queue = asyncio.Queue()
        self.frames = []
        self.terminal = [done()] if terminal is None else terminal
        self.closed = False
        self.send_gate = None
        self.late_send_failed = False

    async def send(self, raw):
        payload = json.loads(raw)
        self.frames.append(payload)
        if payload["type"] == "input_audio.append" and self.send_gate is not None:
            await self.send_gate.wait()
            self.late_send_failed = True
            raise OSError("SECRET late send failure")
        if payload["type"] == "input_audio.end":
            for event in self.terminal:
                self.queue.put_nowait(None if event is None else json.dumps(event))

    async def close(self, **_kwargs):
        self.closed = True
        if self.send_gate is not None:
            self.send_gate.set()
            for _ in range(4):
                await asyncio.sleep(0)

    def __aiter__(self):
        return self

    async def __anext__(self):
        raw = await self.queue.get()
        if raw is None:
            raise StopAsyncIteration
        return raw


class HeldConnection(RealtimeConnection):
    def __aiter__(self):
        self.saved_iterator = super().__aiter__()
        return self.saved_iterator


def install(monkeypatch, socket, *, held=False):
    async def connect(**_kwargs):
        session = RealtimeTranscriptionSession(
            request_id="PRIVATE",
            model=MODEL,
            audio_format=AudioFormat(encoding="pcm_s16le", sample_rate=16000),
        )
        cls = HeldConnection if held else RealtimeConnection
        return cls(
            socket, session, initial_events=[RealtimeTranscriptionSessionCreated(session=session)]
        )

    class Client:
        def __init__(self, **_kwargs):
            self.audio = SimpleNamespace(realtime=SimpleNamespace(connect=connect))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(module, "Mistral", Client)


def runner(socket, *, final_callback=True):
    values = {
        "ready": False,
        "delta_chars": 0,
        "final_chars": 0,
        "events": {},
        "protocol": [],
        "done": 0,
        "errors": [],
    }

    async def audio():
        yield b"\x00\x00" * 3

    def ready():
        values["ready"] = True

    def delta(text):
        values["delta_chars"] += len(text)

    def final(text):
        values["final_chars"] += len(text)

    def event(kind, _characters):
        values["events"][kind] = values["events"].get(kind, 0) + 1

    def complete():
        values["done"] += 1
        values["final_chars_at_done"] = values["final_chars"]

    task = asyncio.create_task(
        module.transcribe(
            audio(),
            AppConfig(_env_file=None),
            on_delta=delta,
            on_final_text=final if final_callback else None,
            on_done=complete,
            on_error=values["errors"].append,
            on_session_created=ready,
            on_event=event,
            on_protocol=values["protocol"].append,
        )
    )
    return values, task


@pytest.mark.parametrize("delay", ["omitted", None, 1000])
def test_updated_ack_gates_ready_audio_and_preserves_unknown_optional_delay(monkeypatch, delay):
    async def scenario():
        socket = Socket()
        install(monkeypatch, socket)
        values, task = runner(socket)
        for _ in range(5):
            await asyncio.sleep(0)
        assert not values["ready"] and socket.frames == []
        assert values["protocol"][-1]["ack_target_delay_ms"] is None
        socket.queue.put_nowait(json.dumps(updated(delay=delay)))
        await asyncio.wait_for(task, 0.5)
        meta = values["protocol"][-1]
        assert values["ready"] and values["done"] == 1 and values["errors"] == []
        assert meta["settings_verified"] and meta["session_updated_received"]
        assert meta["requested_target_delay_ms"] == 1000
        assert meta["ack_target_delay_ms"] == (1000 if delay == 1000 else None)
        assert meta["delay_verified"] == (delay == 1000)
        assert meta["input_flushed"] and meta["input_ended"]
        assert all(validate_protocol_snapshot(p) for p in values["protocol"])
        assert "PRIVATE" not in json.dumps(values["protocol"])

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "ack",
    [
        updated(delay=1001),
        updated(model="wrong"),
        updated(rate=8000),
        updated(rate=0),
        updated(encoding="pcm_f32le"),
    ],
)
def test_explicit_ack_mismatch_fails_before_audio_or_ready(monkeypatch, ack):
    async def scenario():
        socket = Socket()
        socket.queue.put_nowait(json.dumps(ack))
        install(monkeypatch, socket)
        values, task = runner(socket)
        await asyncio.wait_for(task, 0.5)
        assert not values["ready"] and socket.frames == [] and values["done"] == 0
        assert values["errors"][0].reason == "settings_mismatch"
        assert not values["protocol"][-1]["settings_verified"]
        assert socket.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "deltas,final,handling,expected_final",
    [
        ([], "synthetic final result", "final_only_admitted", 22),
        ([""], "synthetic final result", "final_only_admitted", 22),
        (["synthetic "], "synthetic final result", "deltas_preserved", 0),
        ([], "", "empty", 0),
    ],
)
def test_final_only_distinct_admission_precedes_done_and_never_invents_delta(
    monkeypatch, deltas, final, handling, expected_final
):
    async def scenario():
        terminal = [{"type": "transcription.text.delta", "text": text} for text in deltas] + [
            done(final)
        ]
        socket = Socket(terminal)
        socket.queue.put_nowait(json.dumps(updated()))
        install(monkeypatch, socket)
        values, task = runner(socket)
        await asyncio.wait_for(task, 0.5)
        assert values["final_chars"] == len(final) if expected_final else values["final_chars"] == 0
        assert values["final_chars_at_done"] == values["final_chars"]
        assert values["delta_chars"] == sum(map(len, deltas))
        assert values["events"].get("text_delta", 0) == len(deltas)
        meta = values["protocol"][-1]
        assert meta["done_text_characters"] == len(final) and meta["done_text_handling"] == handling
        assert meta["done_received"] and values["errors"] == []

    asyncio.run(scenario())


def test_missing_final_callback_is_not_mislabeled_admitted(monkeypatch):
    async def scenario():
        socket = Socket()
        socket.queue.put_nowait(json.dumps(updated()))
        install(monkeypatch, socket)
        values, task = runner(socket, final_callback=False)
        await asyncio.wait_for(task, 0.5)
        assert values["protocol"][-1]["done_text_handling"] == "not_admitted"
        assert values["final_chars"] == values["delta_chars"] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("early", [done(), None])
def test_done_or_eof_before_ack_never_ready_or_admitted(monkeypatch, early):
    async def scenario():
        socket = Socket()
        socket.queue.put_nowait(None if early is None else json.dumps(early))
        install(monkeypatch, socket)
        values, task = runner(socket)
        await asyncio.wait_for(task, 0.5)
        assert not values["ready"] and values["final_chars"] == values["delta_chars"] == 0
        assert values["errors"][0].reason == "closed_before_ready"
        assert values["done"] == 0 and socket.frames == []
        assert values["protocol"][-1]["done_received"] == (early is not None)

    asyncio.run(scenario())


def test_eof_without_typed_done_fails_instead_of_success(monkeypatch):
    async def scenario():
        socket = Socket([None])
        socket.queue.put_nowait(json.dumps(updated()))
        install(monkeypatch, socket)
        values, task = runner(socket)
        await asyncio.wait_for(task, 0.5)
        assert values["ready"] and values["done"] == 0
        assert values["errors"][0].reason == "closed_before_done"
        assert values["protocol"][-1]["done_text_characters"] is None

    asyncio.run(scenario())


def test_stop_before_ack_cancels_without_audio_and_no_late_ready(monkeypatch):
    async def scenario():
        socket = Socket()
        install(monkeypatch, socket)
        values, task = runner(socket)
        for _ in range(5):
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.2)
        socket.queue.put_nowait(json.dumps(updated()))
        await asyncio.sleep(0)
        assert (
            not values["ready"] and values["errors"] == [] and socket.frames == [] and socket.closed
        )

    asyncio.run(scenario())


def test_stop_after_ack_does_not_turn_sdk_cancelled_eof_into_provider_failure(monkeypatch):
    async def scenario():
        socket = Socket([])
        socket.queue.put_nowait(json.dumps(updated()))
        install(monkeypatch, socket)
        values, task = runner(socket)
        async with asyncio.timeout(0.5):
            while not values["protocol"] or not values["protocol"][-1]["input_ended"]:
                await asyncio.sleep(0)
        before = deepcopy(values["protocol"])
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.2)
        socket.queue.put_nowait(json.dumps(done()))
        await asyncio.sleep(0)
        assert values["protocol"] == before
        assert values["done"] == values["final_chars"] == 0
        assert values["errors"] == [] and socket.closed

    asyncio.run(scenario())


def test_receiver_first_late_sender_failure_is_not_silently_successful(monkeypatch):
    async def scenario():
        socket = Socket()
        socket.send_gate = asyncio.Event()
        socket.queue.put_nowait(json.dumps(updated()))
        socket.queue.put_nowait(json.dumps(done()))
        install(monkeypatch, socket, held=True)
        values, task = runner(socket)
        await asyncio.wait_for(task, 0.5)
        assert socket.late_send_failed
        assert values["done"] == 0 and len(values["errors"]) == 1
        assert values["errors"][0].reason == "send_failed"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "usage,expected",
    [
        ({}, None),
        ({"prompt_audio_seconds": None}, None),
        ({"prompt_audio_seconds": 13}, 13),
        ({"prompt_audio_seconds": -1}, None),
    ],
)
def test_done_usage_is_only_a_sanitized_optional_count(monkeypatch, usage, expected):
    async def scenario():
        socket = Socket([done(usage=usage)])
        socket.queue.put_nowait(json.dumps(updated()))
        install(monkeypatch, socket)
        values, task = runner(socket)
        await asyncio.wait_for(task, 0.5)
        assert values["protocol"][-1]["prompt_audio_seconds"] == expected

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "key,value",
    [
        ("ack_sample_rate", True),
        ("done_text_characters", float("nan")),
        ("prompt_audio_seconds", float("inf")),
        ("requested_target_delay_ms", -1),
        ("settings_verified", True),
        ("done_text_handling", "SECRET"),
        ("input_ended", True),
    ],
)
def test_protocol_schema_rejects_bad_types_inconsistency_and_nonfinite(key, value):
    protocol = AsrProtocolDiagnostics().snapshot()
    protocol[key] = value
    assert not validate_protocol_snapshot(protocol)


def test_schema_six_and_exact_legacy_five_reject_cross_version_injection():
    record = ReliabilityTracker().build_session_record(Session())
    assert record["schema_version"] == 6 and validate_session_record(record)
    old = deepcopy(record)
    old["schema_version"] = 5
    old["pipeline"].pop("protocol")
    assert validate_session_record(old)
    old["pipeline"]["asr"]["reason"] = "settings_mismatch"
    assert not validate_session_record(old)
    old["pipeline"]["asr"]["reason"] = "none"
    old["pipeline"]["protocol"] = record["pipeline"]["protocol"]
    assert not validate_session_record(old)


def test_protocol_requires_consistent_requested_acknowledged_and_delay_flags():
    protocol = AsrProtocolDiagnostics(
        requested_sample_rate=16000,
        requested_pcm_s16le=True,
        requested_target_delay_ms=1000,
        ack_sample_rate=16000,
        ack_pcm_s16le=True,
        ack_model_matches=True,
        ack_target_delay_ms=1000,
        session_updated_received=True,
        settings_verified=True,
        delay_verified=True,
    ).snapshot()
    assert validate_protocol_snapshot(protocol)
    for key, value in [
        ("ack_target_delay_ms", 1001),
        ("delay_verified", False),
        ("requested_target_delay_ms", None),
        ("ack_pcm_s16le", None),
    ]:
        invalid = {**protocol, key: value}
        assert not validate_protocol_snapshot(invalid)
