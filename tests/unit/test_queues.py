from __future__ import annotations

import asyncio

import app.ws as ws_module
from app.audio import AudioCapture
from app.ws import _enqueue_outbound, _OutboundObsState


def _queued_events(queue):
    return [item[0] for item in list(queue._queue)]


def test_audio_queue_drops_oldest_chunk_when_full() -> None:
    loop = asyncio.new_event_loop()
    try:
        capture = AudioCapture(sample_rate=16000, loop=loop, max_queue_chunks=2)
        capture._enqueue_chunk(b"oldest")
        capture._enqueue_chunk(b"middle")
        capture._enqueue_chunk(b"newest")

        assert list(capture._queue._queue) == [b"middle", b"newest"]
        assert capture._dropped_chunks == 1
        capture.stop()
        assert list(capture._queue._queue) == [None]
    finally:
        loop.close()


def test_outbound_queue_coalesces_partial_updates(monkeypatch) -> None:
    monkeypatch.setattr(ws_module, "_ws_metrics", ws_module._WsMetrics())
    queue = asyncio.Queue(maxsize=2)
    obs = _OutboundObsState()
    _enqueue_outbound(queue, {"type": "source_partial", "text": "old"}, obs)
    _enqueue_outbound(queue, {"type": "elapsed", "seconds": 1}, obs)

    accepted = _enqueue_outbound(
        queue, {"type": "source_partial", "text": "new"}, obs
    )

    assert accepted is True
    events = _queued_events(queue)
    assert len(events) == 2
    assert {event["type"] for event in events} == {"elapsed", "source_partial"}
    assert next(event for event in events if event["type"] == "source_partial")["text"] == "new"
    assert ws_module._ws_metrics.coalesced_events == 1


def test_critical_event_displaces_disposable_event(monkeypatch) -> None:
    monkeypatch.setattr(ws_module, "_ws_metrics", ws_module._WsMetrics())
    queue = asyncio.Queue(maxsize=2)
    obs = _OutboundObsState()
    _enqueue_outbound(queue, {"type": "source_partial", "text": "partial"}, obs)
    _enqueue_outbound(
        queue,
        {"type": "tts_audio", "data": "chunk", "is_last": False},
        obs,
    )

    accepted = _enqueue_outbound(queue, {"type": "caption", "seq": 10}, obs)

    assert accepted is True
    events = _queued_events(queue)
    assert len(events) == 2
    assert any(event["type"] == "caption" for event in events)
    assert ws_module._ws_metrics.critical_drops == 0


def test_disposable_event_is_rejected_when_full(monkeypatch) -> None:
    monkeypatch.setattr(ws_module, "_ws_metrics", ws_module._WsMetrics())
    queue = asyncio.Queue(maxsize=2)
    obs = _OutboundObsState()
    _enqueue_outbound(queue, {"type": "status", "status": "listening"}, obs)
    _enqueue_outbound(queue, {"type": "caption", "seq": 1}, obs)

    accepted = _enqueue_outbound(
        queue,
        {"type": "tts_audio", "data": "chunk", "is_last": False},
        obs,
    )

    assert accepted is False
    assert [event["type"] for event in _queued_events(queue)] == ["status", "caption"]
    assert queue.qsize() == queue.maxsize


def test_latest_critical_state_is_kept_under_total_pressure(monkeypatch) -> None:
    monkeypatch.setattr(ws_module, "_ws_metrics", ws_module._WsMetrics())
    queue = asyncio.Queue(maxsize=2)
    obs = _OutboundObsState()
    _enqueue_outbound(queue, {"type": "caption", "seq": 1}, obs)
    _enqueue_outbound(queue, {"type": "error", "message": "safe"}, obs)

    accepted = _enqueue_outbound(
        queue, {"type": "status", "status": "session_ended"}, obs
    )

    assert accepted is True
    assert _queued_events(queue)[-1]["type"] == "status"
    assert queue.qsize() == queue.maxsize
    assert ws_module._ws_metrics.critical_drops == 1
