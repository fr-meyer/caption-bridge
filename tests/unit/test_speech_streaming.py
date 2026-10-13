"""Synthetic clip identity, reconnect, memory and content-free metrics contracts."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import orjson

from app.reliability import ReliabilityTracker, validate_session_record
from app.state import Session
from tests.unit.test_tts import _dispatcher, _ProviderError, _segment, _Stream


def test_reconnect_retires_browser_audio_preserves_unsynthesized_queue() -> None:
    async def run():
        dispatcher, manager, speech = _dispatcher([_Stream([SimpleNamespace(audio_data="AAAAAA==")]), _Stream([])])
        dispatcher.set_audio_unlocked(True)
        dispatcher.enqueue_live(_segment(1))
        await dispatcher.start()
        await asyncio.wait_for(dispatcher._queue.join(), 1)
        sent = next(e for e in manager.events if e["type"] == "tts_audio")
        dispatcher.enqueue_live(_segment(2))  # No await: remains on the server.
        dispatcher.set_audio_unlocked(False)
        assert dispatcher.get_speech_state() == {"pending_count": 1, "playing_seq": None, "tts_epoch": 1}
        assert not dispatcher.acknowledge_playback(1, 0, clip_id=sent["clip_id"], complete=True)
        assert dispatcher._queue._queue[0].tts_epoch == 1
        dispatcher.set_audio_unlocked(True)
        await asyncio.wait_for(dispatcher._queue.join(), 1)
        assert speech.calls == 2
        assert any(e["type"] == "tts_skipped" and e["reason"] == "browser_replaced" for e in manager.events)
        await dispatcher.stop()
    asyncio.run(run())


def test_failed_same_caption_replay_and_duplicate_completion_are_isolated() -> None:
    async def run():
        dispatcher, manager, _ = _dispatcher([_Stream([]), _ProviderError(400), _Stream([])])
        dispatcher.set_audio_unlocked(True)
        dispatcher.enqueue_live(_segment(1))
        await dispatcher.start()
        await asyncio.wait_for(dispatcher._queue.join(), 1)
        first_id = next(iter(dispatcher._pending_clips))
        dispatcher.enqueue_replay(1, "synthetic", "en")
        await asyncio.wait_for(dispatcher._queue.join(), 1)
        error = next(e for e in manager.events if e["type"] == "tts_error")
        assert error["clip_id"] != first_id and error["audio_emitted"] is False
        assert dispatcher.get_speech_state()["pending_count"] == 1
        assert dispatcher.acknowledge_playback(1, 0, clip_id=first_id, complete=True)
        dispatcher.enqueue_replay(1, "synthetic", "en")
        await asyncio.wait_for(dispatcher._queue.join(), 1)
        assert not dispatcher.acknowledge_playback(1, 0, clip_id=first_id, complete=True)
        assert dispatcher.get_speech_state()["pending_count"] == 1
        await dispatcher.stop()
    asyncio.run(run())


def test_pending_browser_clips_have_a_fixed_cap() -> None:
    dispatcher, manager, _ = _dispatcher([], tts_queue_max=100)
    for seq in range(70):
        dispatcher.enqueue_live(_segment(seq))
    assert len(dispatcher._pending_clips) == 64
    assert dispatcher.get_speech_state()["pending_count"] == 64
    assert manager.events[-1]["reason"] == "browser_backlog_full"


def test_browser_stats_are_bounded_idempotent_private_and_history_compatible() -> None:
    dispatcher, manager, _ = _dispatcher([])
    manager._reliability = ReliabilityTracker()
    dispatcher.enqueue_live(_segment(1))
    clip_id = next(iter(dispatcher._pending_clips))
    assert dispatcher.acknowledge_first_chunk(1, 0, clip_id)
    assert not dispatcher.acknowledge_first_chunk(1, 0, clip_id)
    msg = {"type": "tts_playback_stats", "seq": 1, "tts_epoch": 0, "clip_id": clip_id,
           "mode": "streaming", "first_chunk_to_playback_ms": 160, "initial_buffer_ms": 150,
           "underruns": 1, "gap_ms": 20, "data": "private audio", "text": "private caption"}
    assert not dispatcher.acknowledge_browser_result({**msg, "initial_buffer_ms": True})
    assert dispatcher.acknowledge_browser_result(msg)
    assert not dispatcher.acknowledge_browser_result(msg)
    tracker = manager._reliability
    for _ in range(2100):
        tracker.speech_playback.observe_request_to_chunk(0.5)
    record = tracker.build_session_record(Session(status="session_ended"))
    assert validate_session_record(record)
    stats = record["speech_playback"]
    assert stats["request_to_first_browser_chunk"]["count"] == 2048
    assert stats["modes"]["streaming"]["clips"] == 1
    assert b"private" not in orjson.dumps(record)
    for version in (1, 2, 3):
        old = deepcopy(record)
        old.pop("speech_playback")
        old.pop("pipeline")
        old["schema_version"] = version
        if version < 3:
            old["queues"]["tts"].pop("catch_up_actions")
            old["queues"]["tts"].pop("catch_up_skipped")
        if version == 1:
            old.pop("latency")
        assert validate_session_record(old)


def test_streaming_config_is_explicit_opt_in(monkeypatch) -> None:
    from app.config import AppConfig
    monkeypatch.delenv("MISTRAL_TTS_STREAMING_PLAYBACK", raising=False)
    assert not AppConfig(_env_file=None).tts_streaming_playback
    monkeypatch.setenv("MISTRAL_TTS_STREAMING_PLAYBACK", "true")
    assert AppConfig(_env_file=None).tts_streaming_playback


def test_repeated_refresh_preserves_consumer_held_unsynthesized_job() -> None:
    async def run():
        dispatcher, manager, speech = _dispatcher([_Stream([])])
        dispatcher.set_audio_unlocked(True)
        await dispatcher.start()
        await asyncio.sleep(0)  # Consumer passes initial unlock, waiting for queue.get().
        dispatcher.set_audio_unlocked(False)
        dispatcher.enqueue_live(_segment(1))
        await asyncio.sleep(0)  # Consumer holds the job while its second unlock gate waits.
        assert dispatcher._queue.qsize() == 0 and speech.calls == 0
        dispatcher.set_audio_unlocked(False)
        assert dispatcher.get_speech_state()["pending_count"] == 1
        dispatcher.set_audio_unlocked(True)
        await asyncio.wait_for(dispatcher._queue.join(), 1)
        assert speech.calls == 1
        assert next(e for e in manager.events if e["type"] == "tts_audio")["tts_epoch"] == 2
        await dispatcher.stop()
    asyncio.run(run())
