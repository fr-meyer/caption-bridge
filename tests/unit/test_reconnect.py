from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import app.reconnect as reconnect_module
from app.reconnect import ReconnectionManager, classify_reconnect_failure


class _FakeSessionManager:
    def __init__(self) -> None:
        self.session = SimpleNamespace(status="listening")
        self.events: list[dict] = []
        self.partials: list[str] = []

    def set_status(self, status: str) -> None:
        self.session.status = status
        self._emit("status", {"status": status})

    def _emit(self, event_type: str, data: dict | None = None) -> None:
        self.events.append({"type": event_type, **(data or {})})

    def update_partial(self, text: str) -> None:
        self.partials.append(text)


class _Detector:
    def __init__(self, fragment: str | None = None) -> None:
        self.fragment = fragment
        self.flushes = 0

    def flush_reconnect_fragment(self) -> str | None:
        self.flushes += 1
        return self.fragment


class _CloseError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__("provider details must not be emitted")
        self.rcvd = SimpleNamespace(code=code)


def _config(**overrides):
    values = {
        "reconnect_base_backoff_ms": 1,
        "reconnect_max_backoff_ms": 2,
        "reconnect_max_attempts": 3,
        "reconnect_max_elapsed_ms": 1000,
        "reconnect_jitter_factor": 0.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _run(coro):
    return asyncio.run(coro)


def test_classifies_provider_restart_1012_as_recoverable() -> None:
    info = classify_reconnect_failure(_CloseError(1012))

    assert info.category == "provider_restart"
    assert info.recoverable is True
    assert info.close_code == 1012


def test_classifies_policy_close_as_permanent() -> None:
    info = classify_reconnect_failure(_CloseError(1008))

    assert info.category == "websocket_close"
    assert info.recoverable is False


def test_reconnect_recovers_without_duplicate_fragment(monkeypatch) -> None:
    monkeypatch.setattr(reconnect_module, "_POST_HANDSHAKE_HEALTH_TIMEOUT_S", 0.001)
    monkeypatch.setattr(reconnect_module.random, "uniform", lambda *_args: 0.0)
    sm = _FakeSessionManager()
    manager = ReconnectionManager(sm, _config())
    detector = _Detector("partial fragment")
    finalized: list[str] = []
    starts = 0
    teardowns = 0

    async def start_pipeline() -> None:
        nonlocal starts
        starts += 1
        if starts == 1:
            raise OSError("temporary transport failure")

    async def teardown_pipeline() -> None:
        nonlocal teardowns
        teardowns += 1

    manager.get_detector = lambda: detector
    manager.finalize_reconnect_fragment = finalized.append
    manager.start_pipeline = start_pipeline
    manager.teardown_pipeline = teardown_pipeline
    manager.wait_for_stream = None

    _run(manager._reconnect_loop(_CloseError(1012)))

    assert sm.session.status == "listening"
    assert starts == 2
    assert teardowns == 2
    assert detector.flushes == 1
    assert finalized == ["partial fragment"]
    recovered = [event for event in sm.events if event["type"] == "recovered"]
    assert recovered == [
        {
            "type": "recovered",
            "service": "transcription",
            "attempts": 2,
            "downtime_ms": recovered[0]["downtime_ms"],
        }
    ]


def test_reconnect_stops_at_attempt_ceiling(monkeypatch) -> None:
    monkeypatch.setattr(reconnect_module.random, "uniform", lambda *_args: 0.0)
    sm = _FakeSessionManager()
    manager = ReconnectionManager(sm, _config(reconnect_max_attempts=2))
    starts = 0

    async def start_pipeline() -> None:
        nonlocal starts
        starts += 1
        raise OSError("provider still unavailable")

    async def teardown_pipeline() -> None:
        return None

    manager.start_pipeline = start_pipeline
    manager.teardown_pipeline = teardown_pipeline

    _run(manager._reconnect_loop(_CloseError(1012)))

    assert starts == 2
    assert sm.session.status == "session_ended"
    unavailable = [
        event
        for event in sm.events
        if event["type"] == "provider_temporarily_unavailable"
    ]
    assert unavailable[-1]["outcome"] == "exhausted"
    assert unavailable[-1]["attempts"] == 2
    assert unavailable[-1]["manual_recovery_available"] is True
    assert "provider details" not in str(unavailable)


def test_permanent_failure_does_not_retry() -> None:
    sm = _FakeSessionManager()
    manager = ReconnectionManager(sm, _config())
    starts = 0

    async def start_pipeline() -> None:
        nonlocal starts
        starts += 1

    async def teardown_pipeline() -> None:
        return None

    manager.start_pipeline = start_pipeline
    manager.teardown_pipeline = teardown_pipeline

    _run(manager._reconnect_loop(_CloseError(1008)))

    assert starts == 0
    assert sm.session.status == "session_ended"
    assert sm.events[-2]["outcome"] == "permanent"


def test_cancellation_interrupts_backoff(monkeypatch) -> None:
    monkeypatch.setattr(reconnect_module.random, "uniform", lambda *_args: 0.0)

    async def scenario() -> tuple[_FakeSessionManager, asyncio.Task]:
        sm = _FakeSessionManager()
        manager = ReconnectionManager(
            sm,
            _config(
                reconnect_base_backoff_ms=10_000,
                reconnect_max_backoff_ms=10_000,
                reconnect_max_elapsed_ms=20_000,
            ),
        )

        async def start_pipeline() -> None:
            raise AssertionError("backoff should be cancelled before start")

        async def teardown_pipeline() -> None:
            return None

        manager.start_pipeline = start_pipeline
        manager.teardown_pipeline = teardown_pipeline
        task = asyncio.create_task(manager._reconnect_loop(_CloseError(1012)))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return sm, task

    sm, task = _run(scenario())

    assert task.cancelled()
    assert any(event["type"] == "reconnect_cancelled" for event in sm.events)
