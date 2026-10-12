"""Provider-free cancellation, replay, protocol, and privacy checks for Catch up."""
from __future__ import annotations

import asyncio
from copy import deepcopy

import orjson

import app.ws as ws_mod
from app.reliability import ReliabilityTracker, validate_session_record
from app.state import Session
from tests.unit.test_tts import _dispatcher, _segment, _Stream


def test_catch_up_cancels_synthesis_queue_and_browser_pending_then_allows_replay() -> None:
    async def run() -> None:
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        class BlockingStream(_Stream):
            async def __anext__(self):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

        dispatcher, manager, speech = _dispatcher([
            _Stream([]), BlockingStream([]), _Stream([]),
        ])
        dispatcher.set_audio_unlocked(True)
        dispatcher.enqueue_live(_segment(1))
        dispatcher.enqueue_live(_segment(2))
        await dispatcher.start()
        await asyncio.wait_for(entered.wait(), 1)
        dispatcher.enqueue_live(_segment(3))
        assert dispatcher.get_speech_state()["pending_count"] == 3
        assert dispatcher._queue.qsize() == 1  # Clip 1 was already sent to the browser.
        dispatcher.catch_up()
        await asyncio.wait_for(cancelled.wait(), 1)
        await asyncio.wait_for(dispatcher._queue.join(), 1)
        assert dispatcher.get_speech_state() == {
            "tts_epoch": 1, "pending_count": 0, "playing_seq": None,
        }
        skipped = [e for e in manager.events if e["type"] == "tts_skipped"]
        assert [(e["seq"], e["reason"]) for e in skipped] == [
            (1, "user_catch_up"), (2, "user_catch_up"), (3, "user_catch_up"),
        ]
        assert not dispatcher.acknowledge_playback(1, 0, complete=True)
        dispatcher.enqueue_replay(1, "public synthetic replay", "en")
        await asyncio.wait_for(dispatcher._queue.join(), 1)
        assert dispatcher.get_speech_state()["pending_count"] == 1
        assert dispatcher.acknowledge_playback(1, 1, complete=False)
        assert dispatcher.acknowledge_playback(1, 1, complete=True)
        assert dispatcher.get_speech_state()["pending_count"] == 0
        assert speech.calls == 3
        await dispatcher.stop()

    asyncio.run(run())


def test_stale_catch_up_and_playback_ack_cannot_cancel_new_epoch(monkeypatch) -> None:
    dispatcher, manager, _ = _dispatcher([])
    manager._tts_dispatcher = dispatcher
    manager.observe_tts_playback_complete = lambda seq: None
    monkeypatch.setattr(ws_mod, "manager", manager)
    dispatcher.enqueue_live(_segment(1))
    ws_mod._handle_tts_catch_up({"tts_epoch": 0})
    dispatcher.enqueue_live(_segment(2))
    ws_mod._handle_tts_catch_up({"tts_epoch": 0})
    ws_mod._handle_tts_catch_up({"tts_epoch": True})
    ws_mod._handle_latency_ack({"seq": 2, "tts_epoch": 0}, "tts_complete")
    assert dispatcher.get_speech_state()["pending_count"] == 1
    ws_mod._handle_latency_ack({"seq": 2, "tts_epoch": 1}, "tts_complete")
    assert dispatcher.get_speech_state()["pending_count"] == 0
    assert len([e for e in manager.events if e["type"] == "tts_caught_up"]) == 1


def test_mute_and_drain_clear_backlog_and_preserve_unlock_gates() -> None:
    dispatcher, _, _ = _dispatcher([])
    dispatcher.set_audio_unlocked(True)
    dispatcher.enqueue_live(_segment(1))
    dispatcher.set_muted(True)
    assert dispatcher.get_speech_state()["pending_count"] == 0
    dispatcher.set_muted(False)
    dispatcher.enqueue_replay(1, "public synthetic replay", "en")
    asyncio.run(dispatcher.drain())
    assert dispatcher.get_speech_state()["pending_count"] == 0
    assert dispatcher._audio_unlocked
    assert not dispatcher._muted


def test_catch_up_reliability_is_content_free_and_accepts_old_history() -> None:
    tracker = ReliabilityTracker()
    tracker.observe_event({
        "type": "tts_skipped", "reason": "user_catch_up", "count": 3,
        "source_text": "private source", "data": "private audio",
    })
    tracker.observe_event({"type": "tts_caught_up", "skipped_count": 3})
    record = tracker.build_session_record(Session(status="session_ended"))
    assert validate_session_record(record)
    assert record["queues"]["tts"]["catch_up_actions"] == 1
    assert record["queues"]["tts"]["catch_up_skipped"] == 3
    assert record["queues"]["tts"]["skipped"] == 3
    assert b"private" not in orjson.dumps(record)
    for version in (1, 2):
        old = deepcopy(record)
        old["schema_version"] = version
        old.pop("speech_playback")
        old.pop("pipeline")
        old["queues"]["tts"].pop("catch_up_actions")
        old["queues"]["tts"].pop("catch_up_skipped")
        if version == 1:
            old.pop("latency")
        assert validate_session_record(old)


def test_rejected_replay_does_not_remove_an_existing_pending_clip() -> None:
    dispatcher, _, _ = _dispatcher([], tts_queue_max=1)
    dispatcher.enqueue_live(_segment(1))
    dispatcher.enqueue_replay(1, "public replay", "en")
    assert dispatcher.get_speech_state()["pending_count"] == 1
    dispatcher.catch_up()
    assert dispatcher.get_speech_state()["pending_count"] == 0


def test_skipped_speech_does_not_pollute_later_replay_latency() -> None:
    tracker = ReliabilityTracker()
    tracker.latency.observe_tts_request(1)
    tracker.latency.observe_tts_synth_start(1)
    tracker.latency.observe_tts_playback_start(1)
    tracker.observe_event({"type": "tts_skipped", "reason": "user_catch_up", "seq": 1})
    stamps = tracker.latency._stamps.get(1, {})
    assert not any(key.startswith("tts_") for key in stamps)
    # A late completion is already epoch-filtered in ws.py; also no stamp survives.
    tracker.latency.observe_tts_playback_complete(1)
    dimension = tracker.latency.snapshot()["dimensions"]["tts_playback_start_to_completion"]
    assert all(summary["count"] == 0 for summary in dimension.values())
