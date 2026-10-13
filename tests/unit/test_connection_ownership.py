"""Fake socket ownership races; no server, browser, microphone or provider IO."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

import pytest

import app.ws as ws
from app.config import AppConfig
from app.reliability import validate_session_record
from app.state import SessionManager


class FakeTTS:
    _tts_epoch = 0

    def __init__(self):
        self.unlocked = True
        self.unlock_calls = []
        self.mute_calls = []
        self.acks = []

    def set_audio_unlocked(self, value):
        self.unlocked = value
        self.unlock_calls.append(value)

    def set_muted(self, value):
        self.mute_calls.append(value)

    def get_speech_state(self):
        return {"tts_epoch": 0, "pending_count": 0, "playing_seq": None}

    def on_playback_complete(self, seq, epoch, clip_id):
        self.acks.append((seq, epoch, clip_id))


class FakeSocket:
    def __init__(self, *, accept_gate=None, fail_send=False, cleanup_gate=None):
        self.accept_gate = accept_gate
        self.fail_send = fail_send
        self.cleanup_gate = cleanup_gate
        self.accepted = asyncio.Event()
        self.cleanup_started = asyncio.Event()
        self.messages = asyncio.Queue()
        self.sent = []
        self.close_calls = []
        self.send_started = asyncio.Event()
        # These private client details are never read by endpoint telemetry.
        self.url = "PRIVATE-URL"
        self.client = "PRIVATE-CLIENT"

    async def accept(self):
        self.accepted.set()
        if self.accept_gate is not None:
            await self.accept_gate.wait()

    async def send_bytes(self, raw):
        self.send_started.set()
        if self.fail_send:
            raise RuntimeError("PRIVATE-URL PRIVATE-CLIENT SECRET provider body")
        if self.cleanup_gate is not None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cleanup_started.set()
                await self.cleanup_gate.wait()
                raise
        self.sent.append(json.loads(raw))

    async def close(self, code, reason):
        self.close_calls.append((code, reason))
        self.messages.put_nowait(None)

    async def iter_text(self):
        while True:
            message = await self.messages.get()
            if isinstance(message, Exception):
                raise message
            if message is None:
                return
            yield message

    def command(self, **message):
        self.messages.put_nowait(json.dumps(message))

    def disconnect(self):
        self.messages.put_nowait(None)

    def lifecycle(self):
        return next((m for m in self.sent if m["type"] == "connection_lifecycle"), None)


async def wait_for(predicate):
    async with asyncio.timeout(0.5):
        while not predicate():
            await asyncio.sleep(0)


def setup(monkeypatch, tmp_path, status="idle_ready"):
    config = AppConfig(_env_file=None, MISTRAL_TTS_ENABLED=False,
        export_dir=str(tmp_path / "exports"), journal_dir=str(tmp_path / "journal"),
        RELIABILITY_DIR=str(tmp_path / "reliability"))
    manager = SessionManager(config)
    manager.session.status = status
    tts = FakeTTS()
    manager.set_tts_dispatcher(tts)
    monkeypatch.setattr(ws, "manager", manager)
    monkeypatch.setattr(ws, "settings", config)
    monkeypatch.setattr(ws, "_active_connection", None)
    monkeypatch.setattr(ws, "_connection_counter", 0)
    monkeypatch.setattr(ws, "_ws_metrics", ws._WsMetrics())
    calls = []
    async def start():
        calls.append("start")
        manager.set_status("listening")
    async def stop():
        calls.append("stop")
    monkeypatch.setattr(ws, "start_pipeline", start)
    monkeypatch.setattr(ws, "stop_pipeline", stop)
    return manager, tts, calls


async def finish(socket, task, manager):
    socket.disconnect()
    await asyncio.wait_for(task, 0.5)
    manager._cancel_grace_task()
    manager._cancel_elapsed_ticker()


@pytest.mark.parametrize("status", ["idle_ready", "listening", "reconnecting", "session_ended"])
def test_attached_owner_is_protected_from_newcomer_without_any_owner_effect(monkeypatch, tmp_path, status):
    async def scenario():
        manager, tts, calls = setup(monkeypatch, tmp_path, status)
        owner = FakeSocket()
        task = asyncio.create_task(ws.websocket_endpoint(owner))
        await wait_for(lambda: any(m["type"] == "session_snapshot" for m in owner.sent))
        listener = manager._listeners[0]
        newcomer = FakeSocket()
        for kind in ["start", "stop", "finish_input", "new_session", "tts_audio_enabled", "tts_mute", "tts_playback_complete"]:
            newcomer.command(type=kind, muted=True, seq=1, tts_epoch=0, clip_id=1)
        await ws.websocket_endpoint(newcomer)
        assert newcomer.close_calls == [(4409, "owner_active")]
        assert owner.close_calls == []
        assert ws._active_connection.websocket is owner
        assert manager._listeners == [listener]
        assert manager.session.client_connected and manager._grace_task is None
        assert tts.unlocked and tts.unlock_calls == [] and tts.mute_calls == [] and tts.acks == []
        assert calls == []
        assert newcomer.lifecycle() == {"type": "connection_lifecycle", "connection_id": "conn-000002", "state": "rejected", "reason": "owner_active"}
        assert len(newcomer.sent) == 1  # No transcript snapshot or application events.
        assert owner.lifecycle()["connection_id"] == "conn-000001"
        assert next(m for m in owner.sent if m["type"] == "session_snapshot")["connection_lifecycle"] == {
            "connection_id": "conn-000001", "state": "admitted", "reason": "owner_admitted"}
        manager._emit("status", {"status": status})
        await wait_for(lambda: any(m["type"] == "status" for m in owner.sent))
        assert len(newcomer.sent) == 1
        snapshots_before = sum(m["type"] == "session_snapshot" for m in owner.sent)
        clean_snapshot = manager.get_snapshot()
        manager._emit("session_snapshot", clean_snapshot)
        await wait_for(lambda: sum(m["type"] == "session_snapshot" for m in owner.sent) > snapshots_before)
        assert "connection_lifecycle" not in clean_snapshot
        assert owner.sent[-1]["connection_lifecycle"]["connection_id"] == "conn-000001"
        assert owner.sent[-1]["connection_lifecycle"]["state"] == "admitted"
        await finish(owner, task, manager)
    asyncio.run(scenario())


def test_simultaneous_initial_connections_reserve_exactly_one_owner_and_one_start(monkeypatch, tmp_path):
    async def scenario():
        manager, tts, calls = setup(monkeypatch, tmp_path)
        gate = asyncio.Event()
        sockets = [FakeSocket(accept_gate=gate), FakeSocket(accept_gate=gate)]
        for socket in sockets:
            socket.command(type="start")
        tasks = [asyncio.create_task(ws.websocket_endpoint(s)) for s in sockets]
        await asyncio.gather(*(s.accepted.wait() for s in sockets))
        gate.set()
        await wait_for(lambda: ws._ws_metrics.connections_rejected == 1 and calls == ["start"])
        owner = ws._active_connection.websocket
        rejected = next(s for s in sockets if s is not owner)
        await wait_for(lambda: rejected.close_calls == [(4409, "owner_active")])
        assert ws._ws_metrics.connections_admitted == 1
        assert len(manager._listeners) == 1 and tts.unlock_calls == []
        owner.disconnect()
        await asyncio.wait_for(asyncio.gather(*tasks), 0.5)
        assert calls == ["start"] and ws._active_connection is None
        manager._cancel_grace_task()
        manager._cancel_elapsed_ticker()
    asyncio.run(scenario())


def test_true_owner_disconnect_releases_before_old_writer_cleanup_and_cannot_relock_new_owner(monkeypatch, tmp_path):
    async def scenario():
        manager, tts, calls = setup(monkeypatch, tmp_path, "listening")
        cleanup_gate = asyncio.Event()
        old = FakeSocket(cleanup_gate=cleanup_gate)
        old_task = asyncio.create_task(ws.websocket_endpoint(old))
        await old.send_started.wait()
        old_listener = manager._listeners[0]
        old.disconnect()
        await old.cleanup_started.wait()
        assert ws._active_connection is None and manager._listeners == []
        assert tts.unlock_calls == [False]
        assert manager._grace_task is not None
        new = FakeSocket()
        new_task = asyncio.create_task(ws.websocket_endpoint(new))
        await wait_for(lambda: new.lifecycle() is not None)
        new.command(type="tts_audio_enabled")
        await wait_for(lambda: tts.unlock_calls == [False, True])
        new_listener = manager._listeners[0]
        old_listener({"type": "tts_audio", "data": "PRIVATE AUDIO", "seq": 4})
        old.command(type="stop")
        old.command(type="start")
        cleanup_gate.set()
        await asyncio.wait_for(old_task, 0.5)
        assert ws._active_connection.websocket is new and manager._listeners == [new_listener]
        assert tts.unlock_calls == [False, True] and tts.unlocked
        assert manager.session.client_connected and manager._grace_task is None
        assert calls == [] and all(m.get("data") != "PRIVATE AUDIO" for m in new.sent)
        assert new.lifecycle()["connection_id"] == "conn-000002"
        await finish(new, new_task, manager)
    asyncio.run(scenario())


def test_writer_failure_releases_owner_and_next_connection_can_recover_without_secret_logs(monkeypatch, tmp_path, caplog):
    async def scenario():
        caplog.set_level(logging.INFO)
        manager, tts, _calls = setup(monkeypatch, tmp_path)
        failed = FakeSocket(fail_send=True)
        await asyncio.wait_for(ws.websocket_endpoint(failed), 0.5)
        assert failed.close_calls == [(1011, "writer_failed")]
        assert ws._active_connection is None and manager._listeners == []
        assert tts.unlock_calls == [False]
        new = FakeSocket()
        task = asyncio.create_task(ws.websocket_endpoint(new))
        await wait_for(lambda: new.lifecycle() is not None)
        assert new.lifecycle()["state"] == "admitted"
        assert ws._ws_metrics.connections_admitted == 2
        await finish(new, task, manager)
        assert "PRIVATE" not in caplog.text and "SECRET" not in caplog.text
        assert "reason=writer_failed" in caplog.text
    asyncio.run(scenario())


def test_connection_lifecycle_is_transient_and_absent_from_journal_export_and_reliability(monkeypatch, tmp_path):
    async def scenario():
        manager, _tts, _calls = setup(monkeypatch, tmp_path)
        socket = FakeSocket()
        task = asyncio.create_task(ws.websocket_endpoint(socket))
        await wait_for(lambda: socket.lifecycle() is not None)
        connection_id = socket.lifecycle()["connection_id"]
        assert re.fullmatch(r"conn-[0-9]{6,}", connection_id)
        assert set(socket.lifecycle()) == {"type", "connection_id", "state", "reason"}
        assert "connection_lifecycle" not in manager.get_snapshot()
        manager.session.status = "session_ended"
        assert manager.export()["success"]
        record = manager._reliability.build_session_record(manager.session)
        assert validate_session_record(record)
        assert connection_id not in json.dumps(record)
        for path in Path(tmp_path).rglob("*"):
            if path.is_file():
                assert connection_id.encode() not in path.read_bytes()
        await finish(socket, task, manager)
    asyncio.run(scenario())


class BrokenCloseSocket(FakeSocket):
    """ASGI-like reader stays blocked even if sending and closing fail."""

    def __init__(self, close_mode, **kwargs):
        super().__init__(**kwargs)
        self.close_mode = close_mode
        self.reader_waiting = asyncio.Event()
        self.reader_cancelled = False

    async def close(self, code, reason):
        self.close_calls.append((code, reason))
        if self.close_mode == "raise":
            raise OSError("SECRET close failure PRIVATE-URL PRIVATE-CLIENT")
        if self.close_mode == "wait":
            await asyncio.Event().wait()
        # Never signal EOF to the read loop, even if close returns normally.

    async def iter_text(self):
        try:
            self.reader_waiting.set()
            async for message in super().iter_text():
                yield message
        except asyncio.CancelledError:
            self.reader_cancelled = True
            raise


@pytest.mark.parametrize("close_mode", ["raise", "return_no_eof", "wait"])
def test_writer_failure_releases_owner_without_reader_eof_or_working_close(monkeypatch, tmp_path, caplog, close_mode):
    async def scenario():
        caplog.set_level(logging.INFO)
        manager, tts, _calls = setup(monkeypatch, tmp_path, "listening")
        disconnects = []
        original_disconnect = manager.on_client_disconnect
        def disconnect():
            disconnects.append(True)
            original_disconnect()
        monkeypatch.setattr(manager, "on_client_disconnect", disconnect)
        broken = BrokenCloseSocket(close_mode, fail_send=True)
        task = asyncio.create_task(ws.websocket_endpoint(broken))
        await broken.reader_waiting.wait()
        await asyncio.wait_for(task, 0.2)
        assert broken.reader_cancelled
        assert broken.close_calls == [(1011, "writer_failed")]
        assert ws._active_connection is None and manager._listeners == []
        assert disconnects == [True] and tts.unlock_calls == [False]
        assert ws._ws_metrics.connections_closed == 1
        assert "reason=writer_failed" in caplog.text and "reason=cancelled" not in caplog.text
        assert "SECRET" not in caplog.text and "PRIVATE" not in caplog.text
        newcomer = FakeSocket()
        new_task = asyncio.create_task(ws.websocket_endpoint(newcomer))
        await wait_for(lambda: newcomer.lifecycle() is not None)
        assert newcomer.lifecycle()["state"] == "admitted"
        assert newcomer.close_calls == []
        newcomer.command(type="tts_audio_enabled")
        await wait_for(lambda: tts.unlock_calls == [False, True])
        assert manager.session.client_connected and manager._grace_task is None
        await finish(newcomer, new_task, manager)
    asyncio.run(scenario())


@pytest.mark.parametrize("close_mode", ["raise", "wait"])
def test_writer_failure_cancels_in_progress_reader_command_and_preserves_next_owner(monkeypatch, tmp_path, caplog, close_mode):
    async def scenario():
        caplog.set_level(logging.INFO)
        manager, tts, _calls = setup(monkeypatch, tmp_path, "listening")
        command_started, command_cancelled = asyncio.Event(), asyncio.Event()
        command_calls = []
        async def blocked_stop():
            command_calls.append("stop")
            command_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                command_cancelled.set()
        monkeypatch.setattr(ws, "_handle_stop", blocked_stop)
        broken = BrokenCloseSocket(close_mode)
        task = asyncio.create_task(ws.websocket_endpoint(broken))
        await wait_for(lambda: any(m["type"] == "session_snapshot" for m in broken.sent))
        old_listener = manager._listeners[0]
        broken.command(type="stop")
        await command_started.wait()
        broken.fail_send = True
        manager._emit("status", {"status": "listening"})
        await asyncio.wait_for(task, 0.2)
        assert command_cancelled.is_set() and command_calls == ["stop"]
        assert ws._active_connection is None and manager._listeners == []
        assert tts.unlock_calls == [False]
        assert "reason=writer_failed" in caplog.text and "reason=cancelled" not in caplog.text
        newcomer = FakeSocket()
        new_task = asyncio.create_task(ws.websocket_endpoint(newcomer))
        await wait_for(lambda: newcomer.lifecycle() is not None)
        newcomer.command(type="tts_audio_enabled")
        await wait_for(lambda: tts.unlock_calls == [False, True])
        old_listener({"type": "status", "status": "session_ended"})
        broken.command(type="stop")
        broken.command(type="tts_audio_enabled")
        await asyncio.sleep(0)
        assert command_calls == ["stop"]
        assert ws._active_connection.websocket is newcomer and tts.unlocked
        assert tts.unlock_calls == [False, True]
        assert manager.session.client_connected
        await finish(newcomer, new_task, manager)
    asyncio.run(scenario())
