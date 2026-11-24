"""Real asyncio/AnyIO cancellation ordering; no provider or audio operations."""
from __future__ import annotations

import asyncio
import threading

import anyio
import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from app import ws
from app.config import AppConfig
from app.state import SessionManager


class CleanupSocket:
    def __init__(self, *, disconnect=True, delayed_writer_cleanup=False):
        self.disconnect = disconnect
        self.delayed_writer_cleanup = delayed_writer_cleanup
        self.started = asyncio.Event()
        self.cleanup_finished = False

    async def accept(self):
        pass

    async def send_bytes(self, raw):
        self.started.set()
        if self.delayed_writer_cleanup:
            try:
                await asyncio.Event().wait()
            finally:
                # A real cooperative finalizer must survive the host cancel
                # scope firing while the endpoint joins its owned tasks.
                await asyncio.sleep(0)
                self.cleanup_finished = True
        else:
            await asyncio.sleep(0)

    async def iter_text(self):
        await self.started.wait()
        if not self.disconnect:
            await asyncio.Event().wait()
        if False:
            yield ""


def setup(monkeypatch, tmp_path):
    config = AppConfig(
        _env_file=None, MISTRAL_API_KEY="synthetic-local-test-key", MISTRAL_TTS_ENABLED=False,
        JOURNAL_DIR=str(tmp_path / "journal"), RELIABILITY_DIR=str(tmp_path / "reliability"),
    )
    manager = SessionManager(config)
    monkeypatch.setattr(ws, "manager", manager)
    monkeypatch.setattr(ws, "_active_connection", None)
    monkeypatch.setattr(ws, "_connection_counter", 0)
    monkeypatch.setattr(ws, "_ws_metrics", ws._WsMetrics())
    monkeypatch.setattr(ws, "catalogue_loader", None)
    return manager


def pending_endpoint_tasks():
    # The failure supervisor is Event.wait; the other children are nested
    # endpoint coroutines. Each test owns a fresh, otherwise idle asyncio loop.
    return {task for task in asyncio.all_tasks() if
            task.get_coro().__qualname__.startswith("websocket_endpoint.<locals>.")
            or task.get_coro().__qualname__ == "Event.wait"}


@pytest.mark.parametrize("delayed_cleanup", [False, True])
def test_host_scope_cancellation_during_disconnect_joins_owner_tasks(
    monkeypatch, tmp_path, delayed_cleanup,
):
    async def scenario():
        manager = setup(monkeypatch, tmp_path)
        socket = CleanupSocket(delayed_writer_cleanup=delayed_cleanup)
        unsubscribe = manager.unsubscribe
        owned = set()
        with anyio.CancelScope() as scope:
            def on_unsubscribe(listener):
                unsubscribe(listener)
                owned.update(pending_endpoint_tasks())
                # Exact teardown order: reader EOF, synchronous owner release,
                # cancel owner tasks, then ASGI host cancellation at the join.
                asyncio.get_running_loop().call_soon(scope.cancel)
            monkeypatch.setattr(manager, "unsubscribe", on_unsubscribe)
            await ws.websocket_endpoint(socket)
        assert scope.cancel_called
        assert len(owned) == 3  # writer, failure supervisor, renewal; reader reached EOF
        assert all(task.done() for task in owned)
        assert not pending_endpoint_tasks()
        assert ws._active_connection is None
        assert manager._listeners == []
        assert ws._ws_metrics.connections_closed == 1
        if delayed_cleanup:
            assert socket.cleanup_finished
        manager._cancel_grace_task()
        manager._cancel_elapsed_ticker()
    asyncio.run(scenario())


def test_external_endpoint_cancellation_is_not_swallowed(monkeypatch, tmp_path):
    async def scenario():
        manager = setup(monkeypatch, tmp_path)
        socket = CleanupSocket(disconnect=False, delayed_writer_cleanup=True)
        task = asyncio.create_task(ws.websocket_endpoint(socket))
        await socket.started.wait()
        owned = pending_endpoint_tasks()
        task.cancel("external-stop")
        with pytest.raises(asyncio.CancelledError) as failure:
            await task
        assert failure.value.args == ("external-stop",)
        assert task.cancelled()
        assert len(owned) == 4  # reader, writer, failure supervisor, renewal
        assert all(child.done() for child in owned)
        assert socket.cleanup_finished
        assert ws._active_connection is None
        assert manager._listeners == []
        manager._cancel_grace_task()
        manager._cancel_elapsed_ticker()
    asyncio.run(scenario())


def test_real_testclient_disconnect_overlaps_host_scope_cancel(monkeypatch, tmp_path):
    manager = setup(monkeypatch, tmp_path)
    completed = threading.Event()
    owned = set()
    app = FastAPI()

    async def endpoint(websocket: WebSocket):
        with anyio.CancelScope() as host:
            unsubscribe = manager.unsubscribe
            def on_unsubscribe(listener):
                unsubscribe(listener)
                owned.update(pending_endpoint_tasks())
                asyncio.get_running_loop().call_soon(host.cancel)
            monkeypatch.setattr(manager, "unsubscribe", on_unsubscribe)
            try:
                await ws.websocket_endpoint(websocket)
            finally:
                completed.set()

    app.websocket("/ws")(endpoint)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as socket:
            assert socket.receive_json(mode="binary")["type"] == "connection_lifecycle"
            assert socket.receive_json(mode="binary")["type"] == "session_snapshot"
    # The actual synchronous context exit must join its ASGI future, rather
    # than leak concurrent.futures.CancelledError from the endpoint cleanup.
    assert completed.is_set()
    assert len(owned) == 3
    assert all(task.done() for task in owned)
    assert ws._active_connection is None
    assert manager._listeners == []
