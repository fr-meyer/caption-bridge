"""Offline provider establishment, supervision and privacy regressions."""

from __future__ import annotations

import asyncio
import json
import logging
import struct
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.main as main
import app.ws as ws
from app.audio import AudioCapture
from app.config import AppConfig
from app.journal import SessionJournal, run_recovery
from app.pipeline_diagnostics import (
    AsrProtocolDiagnostics,
    PipelineDiagnostics,
    pcm16_metrics,
    validate_pipeline_snapshot,
)
from app.reconnect import ReconnectionManager
from app.reliability import (
    ReliabilityTracker,
    load_history,
    validate_session_record,
    write_session_record,
)
from app.state import Session, SessionManager
from app.transcribe import AsrStreamError


class FakeAudio:
    instances: list[FakeAudio] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.queue = asyncio.Queue()
        self.started = False
        self.stopped = False
        self.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        self.queue.put_nowait(None)

    def finish_input(self):
        self.stop()

    async def stream(self):
        while True:
            value = await self.queue.get()
            if value is None:
                return
            yield value


class Drain:
    async def drain(self):
        pass


def config_at(tmp_path, **extra):
    return AppConfig(
        _env_file=None, MISTRAL_TTS_ENABLED=False, asr_initial_timeout_ms=100,
        journal_dir=str(tmp_path / "journal"), export_dir=str(tmp_path / "exports"),
        recovery_export_dir=str(tmp_path / "recovered"),
        RELIABILITY_DIR=str(tmp_path / "reliability"), **extra,
    )


def install_pipeline(monkeypatch, tmp_path, transcribe):
    config = config_at(tmp_path)
    manager = SessionManager(config)
    manager.session.status = "idle_ready"
    manager.set_journal(SessionJournal(manager.session.id, config))
    reconnect = ReconnectionManager(manager, config)
    monkeypatch.setattr(main, "settings", config)
    monkeypatch.setattr(main, "manager", manager)
    monkeypatch.setattr(main, "reconnect_manager", reconnect)
    monkeypatch.setattr(main, "AudioCapture", FakeAudio)
    monkeypatch.setattr(main, "dispatcher", Drain())
    monkeypatch.setattr(main, "tts_dispatcher", Drain())
    monkeypatch.setattr(main, "transcribe", transcribe)
    monkeypatch.setattr(main, "_stream_ready", asyncio.Event())
    monkeypatch.setattr(main, "_audio", None)
    monkeypatch.setattr(main, "_transcribe_task", None)
    monkeypatch.setattr(main, "_initial_establishment_task", None)
    monkeypatch.setattr(ws, "manager", manager)
    monkeypatch.setattr(ws, "start_pipeline", main._start_pipeline)
    monkeypatch.setattr(ws, "stop_pipeline", main._stop_pipeline)
    monkeypatch.setattr(ws, "finish_input", main._finish_input)
    FakeAudio.instances = []
    return manager, reconnect


def test_recovered_stream_preserves_order_and_rejects_old_attempt_callbacks(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    import app.reconnect as reconnect_module

    monkeypatch.setattr(reconnect_module, "_POST_HANDSHAKE_HEALTH_TIMEOUT_S", 0.001)
    callbacks = []

    async def fake_transcribe(**kwargs):
        callbacks.append(kwargs)
        kwargs["on_session_created"]()
        async for _ in kwargs["audio_stream"]:
            pass

    async def scenario():
        manager, reconnect = install_pipeline(monkeypatch, tmp_path, fake_transcribe)
        monkeypatch.setattr(manager.config, "reconnect_base_backoff_ms", 0)
        reconnect.get_detector = lambda: main._detector
        reconnect.finalize_reconnect_fragment = manager.finalize_reconnect_fragment
        reconnect.start_pipeline = main._start_pipeline
        reconnect.teardown_pipeline = main._teardown_pipeline
        reconnect.wait_for_stream = main._wait_for_stream_established
        await main._start_pipeline()
        await wait_for(lambda: len(callbacks) == 1)
        callbacks[0]["on_delta"]("SYNTHETIC first caption.")
        callbacks[0]["on_delta"]("SYNTHETIC partial fragment")
        callbacks[0]["on_error"](AsrStreamError("provider_error"))
        task = reconnect._retry_task
        assert task is not None
        await asyncio.wait_for(task, 0.5)
        assert manager.session.status == "listening" and len(callbacks) == 2
        callbacks[0]["on_delta"]("SYNTHETIC stale caption.")
        callbacks[0]["on_error"](AsrStreamError("provider_error"))
        callbacks[1]["on_delta"]("SYNTHETIC next caption.")
        assert [s.seq for s in manager.session.segments] == [1, 2, 3]
        assert [s.segment_kind for s in manager.session.segments] == ["complete", "reconnect_fragment", "complete"]
        assert [s.source_text for s in manager.session.segments] == [
            "SYNTHETIC first caption.", "SYNTHETIC partial fragment", "SYNTHETIC next caption.",
        ]
        assert manager._reliability.pipeline.errors == 1
        await ws._handle_stop()
        assert main._audio is main._transcribe_task is None
        assert all(a.stopped for a in FakeAudio.instances)
        assert reconnect._retry_task is None and not manager._reliability.pipeline.capture_active

    asyncio.run(scenario())
    events = [json.loads(r.getMessage().split(" ", 1)[1]) for r in caplog.records
              if r.name == "app.asr_diagnostics"]
    assert len({e["run_id"] for e in events}) == 1
    assert len([e for e in events if e["event"] == "stream_failure"]) == 1
    assert any(e["event"] == "recovered" for e in events)
    assert "SYNTHETIC" not in caplog.text


def test_silence_and_pending_fragment_do_not_report_a_transcription_outage(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO)

    async def fake_transcribe(**kwargs):
        kwargs["on_session_created"]()
        kwargs["on_delta"]("SYNTHETIC pending phrase")
        async for _ in kwargs["audio_stream"]:
            pass

    async def scenario():
        manager, reconnect = install_pipeline(monkeypatch, tmp_path, fake_transcribe)
        await main._start_pipeline()
        await wait_for(lambda: manager._reliability.pipeline.state == "ready")
        await asyncio.sleep(0)
        assert not manager.session.segments
        assert manager.session.status == "listening" and reconnect._retry_task is None
        assert manager._reliability.pipeline.errors == 0
        await ws._handle_stop()

    asyncio.run(scenario())
    events = [json.loads(r.getMessage().split(" ", 1)[1]) for r in caplog.records
              if r.name == "app.asr_diagnostics"]
    assert not any(e["event"] in {"stream_failure", "reconnect_started"} for e in events)
    assert "SYNTHETIC" not in caplog.text


async def wait_for(predicate, timeout=0.5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("failure", ["timeout", "provider_error", "done"])
def test_initial_failure_stops_capture_once_without_retry_and_exports(monkeypatch, tmp_path, failure):
    async def scenario():
        async def fake_transcribe(**kwargs):
            if failure == "provider_error":
                kwargs["on_error"](AsrStreamError("provider_error"))
            elif failure == "done":
                kwargs["on_done"]()
            else:
                await asyncio.Event().wait()

        manager, reconnect = install_pipeline(monkeypatch, tmp_path, fake_transcribe)
        await ws._handle_start({"type": "start"}, asyncio.Queue(), ws._OutboundObsState())
        assert manager.session.status == "listening"
        assert manager.get_snapshot()["pipeline_diagnostics"]["asr"]["state"] == "connecting"
        assert manager.get_snapshot()["pipeline_diagnostics"]["capture"]["active"]
        await wait_for(lambda: manager.session.status == "session_ended")
        diag = manager.get_snapshot()["pipeline_diagnostics"]
        expected = {"timeout": "initial_timeout", "provider_error": "provider_error", "done": "closed_before_ready"}[failure]
        assert diag["asr"]["state"] == "failed"
        assert diag["asr"]["reason"] == expected
        assert diag["asr"]["errors"] == 1
        assert diag["asr"]["handshakes"] == 0
        assert not diag["capture"]["active"]
        assert len(FakeAudio.instances) == 1 and FakeAudio.instances[0].stopped
        assert main._audio is None and main._transcribe_task is None
        assert reconnect._retry_task is None
        assert manager.session.translation_model == "mistral-medium-latest"
        sessions, _, skipped = load_history(Path(manager.config.reliability_dir))
        assert skipped == 0 and sessions[0]["pipeline"] == diag
        assert manager.export()["success"]
        assert json.loads((Path(manager.session.export_path) / "transcript.json").read_text())["segments"] == []

    asyncio.run(scenario())


def test_ready_means_verified_handshake_and_deadline_is_only_for_startup(monkeypatch, tmp_path):
    async def scenario():
        release = asyncio.Event()
        async def fake_transcribe(**kwargs):
            await release.wait()
            kwargs["on_session_created"]()
            kwargs["on_event"]("session_created", 0)
            async for chunk in kwargs["audio_stream"]:
                kwargs["on_sent"](len(chunk))

        manager, reconnect = install_pipeline(monkeypatch, tmp_path, fake_transcribe)
        await main._start_pipeline()
        await asyncio.sleep(0)
        assert manager._reliability.pipeline.state == "connecting"
        release.set()
        await wait_for(lambda: manager._reliability.pipeline.state == "ready")
        audio = FakeAudio.instances[0]
        audio.kwargs["ingress_callback"](pcm16_metrics(struct.pack("<hh", 8192, -8192), 2))
        audio.queue.put_nowait(struct.pack("<hh", 8192, -8192))
        await asyncio.sleep(0.15)  # Past establishment deadline, without a session cutoff.
        diag = manager.get_snapshot()["pipeline_diagnostics"]
        assert manager.session.status == "listening" and diag["capture"]["active"]
        assert diag["asr"]["state"] == "ready" and diag["asr"]["handshakes"] == 1
        assert diag["asr"]["sent_frames"] == 1 and diag["asr"]["sent_bytes"] == 4
        assert diag["capture"]["rms"] == diag["capture"]["peak"] == 0.25
        assert reconnect._retry_task is None
        await ws._handle_stop()
        assert manager.session.status == "session_ended"
        assert not manager._reliability.pipeline.capture_active

    asyncio.run(scenario())


def test_stop_while_connecting_is_responsive_and_late_callbacks_cannot_revive(monkeypatch, tmp_path):
    async def scenario():
        callbacks = []
        async def fake_transcribe(**kwargs):
            callbacks.append(kwargs)
            await asyncio.Event().wait()

        manager, reconnect = install_pipeline(monkeypatch, tmp_path, fake_transcribe)
        await asyncio.wait_for(ws._handle_start({"type": "start"}, asyncio.Queue(), ws._OutboundObsState()), 0.2)
        await asyncio.sleep(0)
        old = callbacks[0]
        await asyncio.wait_for(ws._handle_stop(), 0.2)
        assert FakeAudio.instances[0].stopped
        before = deepcopy(manager.get_snapshot()["pipeline_diagnostics"])
        old["on_session_created"]()
        old["on_error"](RuntimeError("SECRET provider details"))
        old["on_done"]()
        old["on_sent"](4)
        old["on_event"]("text_delta", 20)
        old["on_delta"]("SECRET transcript")
        old["on_final_text"]("SECRET final transcript")
        old["on_protocol"](AsrProtocolDiagnostics().snapshot())
        FakeAudio.instances[0].kwargs["ingress_callback"](pcm16_metrics(b"\x00\x00"))
        assert manager.get_snapshot()["pipeline_diagnostics"] == before
        assert manager.session.segments == [] and manager.session.source_partial == ""
        await manager.reset()
        manager.session.status = "idle_ready"
        await main._start_pipeline()
        await asyncio.sleep(0)
        newer = deepcopy(manager.get_snapshot()["pipeline_diagnostics"])
        old["on_session_created"]()
        old["on_error"](RuntimeError("SECRET"))
        old["on_done"]()
        old["on_final_text"]("SECRET stale final transcript")
        old["on_protocol"](AsrProtocolDiagnostics().snapshot())
        assert manager.get_snapshot()["pipeline_diagnostics"] == newer
        assert manager._reliability.pipeline.state == "connecting"
        assert reconnect._retry_task is None
        await ws._handle_stop()

    asyncio.run(scenario())


def test_capture_numeric_metrics_include_chunks_dropped_at_queue_pressure():
    async def scenario():
        pipeline = PipelineDiagnostics()
        capture = AudioCapture(16000, asyncio.get_running_loop(), max_queue_chunks=1,
                               ingress_callback=pipeline.record_capture)
        capture._enqueue_chunk(b"\x00\x00" * 4, 4)
        capture._enqueue_chunk(struct.pack("<hh", -32768, 16384), 2)
        capture._enqueue_chunk(b"\x01", 0)
        snapshot = pipeline.snapshot()
        assert snapshot["capture"]["chunks"] == 3
        assert snapshot["capture"]["bytes"] == 13
        assert snapshot["capture"]["samples"] == snapshot["capture"]["frames"] == 6
        assert snapshot["capture"]["invalid_chunks"] == 1
        assert snapshot["capture"]["peak"] == 1
        assert snapshot["capture"]["rms"] == round((1.25 / 6) ** 0.5, 6)
        assert capture._dropped_chunks == 2
        capture.stop()
        capture._enqueue_chunk(b"\x00\x00")
        assert pipeline.snapshot() == snapshot
    asyncio.run(scenario())


@pytest.mark.parametrize("value", [-1, True, "private", float("nan")])
def test_invalid_numeric_inputs_rejected(value):
    pipeline = PipelineDiagnostics()
    with pytest.raises(ValueError):
        pipeline.record_sent(value)
    with pytest.raises(ValueError):
        pcm16_metrics(b"\x00\x00", value)


@pytest.mark.parametrize("timeout", [0, 99, 60001, True, "100.5", 100.5])
def test_startup_deadline_configuration_is_bounded(timeout):
    with pytest.raises(ValidationError):
        AppConfig(_env_file=None, asr_initial_timeout_ms=timeout)


def test_content_free_schema_rejects_unsafe_and_nonfinite_values():
    pipeline = PipelineDiagnostics()
    pipeline.record_capture(pcm16_metrics(b"\x00\x00" * 4))
    pipeline.set_state("connecting")
    pipeline.set_state("ready")
    pipeline.record_sent(8)
    pipeline.record_event("text_delta", 42)
    pipeline.record_error()
    snapshot = pipeline.snapshot()
    assert snapshot["capture"]["rms"] == snapshot["capture"]["peak"] == 0
    assert validate_pipeline_snapshot(snapshot)
    serialized = json.dumps(snapshot)
    assert "raw" not in serialized and "SECRET" not in serialized
    for bucket, key, value in [
        ("asr", "reason", "SECRET provider body"), ("capture", "rms", float("nan")),
        ("capture", "peak", True), ("asr", "event_types", {"SECRET": 1}),
        ("asr", "sent_bytes", 1), ("capture", "samples", True),
    ]:
        unsafe = deepcopy(snapshot)
        unsafe[bucket][key] = value
        assert not validate_pipeline_snapshot(unsafe)
    unsafe = deepcopy(snapshot)
    unsafe["asr"]["transcript"] = "SECRET"
    assert not validate_pipeline_snapshot(unsafe)
    with pytest.raises(ValueError):
        pipeline.set_state("failed", "SECRET")
    with pytest.raises(ValueError):
        pipeline.record_event("SECRET")


def test_reliability_v1_to_v5_history_and_legacy_recovery_remain_compatible(tmp_path):
    tracker = ReliabilityTracker()
    for version in range(1, 7):
        record = tracker.build_session_record(Session(id=f"old-{version}"))
        record["schema_version"] = version
        if version < 5:
            record.pop("pipeline")
        elif version == 5:
            record["pipeline"].pop("protocol")
        if version < 4:
            record.pop("speech_playback")
        if version < 2:
            record.pop("latency")
        if version < 3:
            record["queues"]["tts"].pop("catch_up_actions")
            record["queues"]["tts"].pop("catch_up_skipped")
        assert validate_session_record(record)
        write_session_record(tmp_path / "history", record)
    sessions, _, skipped = load_history(tmp_path / "history")
    assert len(sessions) == 6 and skipped == 0
    config = config_at(tmp_path)
    journal = SessionJournal("legacy-session", config)
    journal.record_session_started()
    recovered = run_recovery(config)
    assert recovered.notice.status == "success"
    exported = json.loads((Path(recovered.notice.export_path) / "transcript.json").read_text())
    assert exported["segments"] == [] and exported["config_scope"] == "recovery_runtime"


def test_established_stop_preserves_final_text_and_counters_while_draining(monkeypatch, tmp_path):
    async def scenario():
        async def fake_transcribe(**kwargs):
            kwargs["on_session_created"]()
            async for _chunk in kwargs["audio_stream"]:
                pass
            kwargs["on_delta"]("Final synthetic words without punctuation")
            kwargs["on_event"]("text_delta", 40)
            kwargs["on_sent"](4)
            kwargs["on_done"]()
        manager, _reconnect = install_pipeline(monkeypatch, tmp_path, fake_transcribe)
        await main._start_pipeline()
        await wait_for(lambda: manager._reliability.pipeline.state == "ready")
        await ws._handle_stop()
        assert manager.session.status == "session_ended"
        assert [seg.source_text for seg in manager.session.segments] == ["Final synthetic words without punctuation"]
        assert manager._reliability.pipeline.sent_bytes == 4
        assert manager._reliability.pipeline.text_events == 1
        assert not manager._reliability.pipeline.capture_active
    asyncio.run(scenario())


def test_unobserved_pcm_is_unknown_and_observed_silence_is_numeric_zero():
    pipeline = PipelineDiagnostics()
    unknown = pipeline.snapshot()
    assert unknown["capture"]["rms"] is None and unknown["capture"]["peak"] is None
    assert validate_pipeline_snapshot(unknown)
    wrong = deepcopy(unknown)
    wrong["capture"]["rms"] = 0
    assert not validate_pipeline_snapshot(wrong)
    pipeline.record_capture(pcm16_metrics(b"\x00\x00" * 3))
    observed = pipeline.snapshot()
    assert observed["capture"]["rms"] == observed["capture"]["peak"] == 0
    observed["capture"]["peak"] = None
    assert not validate_pipeline_snapshot(observed)


def test_startup_deadline_accepts_environment_integer(monkeypatch):
    monkeypatch.setenv("ASR_INITIAL_TIMEOUT_MS", "250")
    assert AppConfig(_env_file=None).asr_initial_timeout_ms == 250
    monkeypatch.setenv("ASR_INITIAL_TIMEOUT_MS", "250.5")
    with pytest.raises(ValidationError):
        AppConfig(_env_file=None)


@pytest.mark.parametrize("terminal", ["done", "final_only", "error"])
def test_finish_input_stops_capture_preserves_completion_without_retry(monkeypatch, tmp_path, terminal):
    async def scenario():
        callbacks, events = [], []
        after_eof = asyncio.Event()
        class CountDrain:
            def __init__(self): self.calls = 0
            async def drain(self): self.calls += 1
        async def fake_transcribe(**kwargs):
            callbacks.append(kwargs)
            kwargs["on_session_created"]()
            async for _chunk in kwargs["audio_stream"]:
                pass
            await after_eof.wait()
            text = "Final synthetic words without punctuation"
            if terminal == "final_only":
                kwargs["on_final_text"](text)
                kwargs["on_event"]("done", 0)
                kwargs["on_protocol"](AsrProtocolDiagnostics(
                    requested_sample_rate=16000, requested_pcm_s16le=True,
                    requested_target_delay_ms=1000, ack_sample_rate=16000,
                    ack_pcm_s16le=True, ack_model_matches=True,
                    session_updated_received=True, settings_verified=True,
                    done_received=True, done_text_characters=len(text),
                    done_text_handling="final_only_admitted",
                ).snapshot())
            else:
                kwargs["on_delta"](text)
                kwargs["on_event"]("text_delta", len(text))
            if terminal != "error":
                kwargs["on_done"]()
            else:
                kwargs["on_error"](AsrStreamError("provider_error"))
        manager, reconnect = install_pipeline(monkeypatch, tmp_path, fake_transcribe)
        dispatcher, tts = CountDrain(), CountDrain()
        monkeypatch.setattr(main, "dispatcher", dispatcher)
        monkeypatch.setattr(main, "tts_dispatcher", tts)
        manager.subscribe(events.append)
        await main._start_pipeline()
        await wait_for(lambda: manager._reliability.pipeline.state == "ready")
        await ws._handle_finish_input(asyncio.Queue(), ws._OutboundObsState())
        assert FakeAudio.instances[0].stopped
        assert not manager._reliability.pipeline.capture_active
        assert manager._reliability.pipeline.state == "draining"
        assert manager.session.status == "listening"
        assert dispatcher.calls == tts.calls == 0
        await main._finish_input()  # Idempotent; never starts a capture.
        after_eof.set()
        await wait_for(lambda: main._stream_completed)
        expected_state, expected_reason = ("stopped", "input_finished") if terminal != "error" else ("failed", "provider_error")
        assert manager._reliability.pipeline.state == expected_state
        assert manager._reliability.pipeline.reason == expected_reason
        assert len(manager.session.segments) == 1
        assert dispatcher.calls == tts.calls == 0
        complete = [event for event in events if event["type"] == "finish_input_complete"]
        assert complete == [{"type": "finish_input_complete", "asr_state": expected_state, "reason": expected_reason,
                             "source_count": 1, "translation_pending_count": 1}]
        assert manager.get_snapshot()["segments"][0]["translation_status"] == "pending"
        if terminal == "final_only":
            pipeline = manager.get_snapshot()["pipeline_diagnostics"]
            assert pipeline["asr"]["text_events"] == pipeline["asr"]["text_characters"] == 0
            assert pipeline["protocol"]["done_text_handling"] == "final_only_admitted"
        assert reconnect._retry_task is None and len(FakeAudio.instances) == 1
        before = deepcopy(manager.get_snapshot()["pipeline_diagnostics"])
        callbacks[0]["on_session_created"]()
        callbacks[0]["on_error"](RuntimeError("SECRET"))
        callbacks[0]["on_delta"]("SECRET late text")
        callbacks[0]["on_final_text"]("SECRET late final text")
        callbacks[0]["on_protocol"](AsrProtocolDiagnostics().snapshot())
        callbacks[0]["on_done"]()
        assert manager.get_snapshot()["pipeline_diagnostics"] == before
        assert len(manager.session.segments) == 1
        await ws._handle_stop()
        assert dispatcher.calls == tts.calls == 1
        assert manager.session.status == "session_ended"
        assert main._audio is None and main._transcribe_task is None
        assert manager.export()["success"]
    asyncio.run(scenario())


def test_finish_input_requires_verified_ready_and_stop_still_works_during_drain(monkeypatch, tmp_path):
    async def scenario():
        callbacks = []
        async def fake_transcribe(**kwargs):
            callbacks.append(kwargs)
            await asyncio.Event().wait()
        manager, _reconnect = install_pipeline(monkeypatch, tmp_path, fake_transcribe)
        await main._start_pipeline()
        await asyncio.sleep(0)
        queue = asyncio.Queue()
        await ws._handle_finish_input(queue, ws._OutboundObsState())
        error, _stamp = queue.get_nowait()
        assert error["type"] == "error"
        assert FakeAudio.instances[0].stopped is False
        callbacks[0]["on_session_created"]()
        await main._finish_input()
        assert manager._reliability.pipeline.state == "draining"
        # A hung provider drain remains interruptible by the normal Stop path.
        task = asyncio.create_task(ws._handle_stop())
        await asyncio.sleep(0)
        main._transcribe_task.cancel()
        await asyncio.wait_for(task, 0.2)
        assert manager.session.status == "session_ended"
        assert not manager._reliability.pipeline.capture_active
    asyncio.run(scenario())


def test_capture_finish_input_preserves_full_buffer_through_eof_and_stop_can_interrupt():
    async def scenario():
        pipeline = PipelineDiagnostics()
        capture = AudioCapture(16000, asyncio.get_running_loop(), max_queue_chunks=2,
                               ingress_callback=pipeline.record_capture)
        class Native:
            def __init__(self): self.stops = self.closes = 0
            def stop(self): self.stops += 1
            def close(self): self.closes += 1
        native = Native()
        capture._stream = native
        expected = [b"\x01\x00", b"\x02\x00"]
        for chunk in expected:
            capture._enqueue_chunk(chunk)
        capture.finish_input()
        assert native.stops == native.closes == 1 and capture._stream is None
        assert capture._stopped and capture._input_eof_handle is not None
        capture._enqueue_chunk(b"\x03\x00")  # Late native callback is discarded.
        assert [chunk async for chunk in capture.stream()] == expected
        assert pipeline.capture_chunks == 2
        await asyncio.sleep(0)
        assert capture._sentinel_task.done()
        capture.stop()
        assert capture._sentinel_task is None
        assert [chunk async for chunk in capture.stream()] == []
        interrupted = AudioCapture(16000, asyncio.get_running_loop(), max_queue_chunks=1)
        interrupted._enqueue_chunk(b"\x01\x00")
        interrupted.finish_input()
        await asyncio.sleep(0)
        task = interrupted._sentinel_task
        interrupted.stop()
        assert [chunk async for chunk in interrupted.stream()] == []
        await asyncio.sleep(0)
        assert task.cancelled()
    asyncio.run(scenario())


def test_finish_input_counts_already_accepted_capture_tail_for_current_generation(monkeypatch, tmp_path):
    async def scenario():
        callbacks = {}
        release = asyncio.Event()

        async def transcribe(**kwargs):
            callbacks.update(kwargs)
            kwargs["on_session_created"]()
            await release.wait()

        manager, _ = install_pipeline(monkeypatch, tmp_path, transcribe)
        await main._start_pipeline()
        await wait_for(lambda: bool(callbacks))
        ingress = FakeAudio.instances[-1].kwargs["ingress_callback"]
        chunk = b"\x01\x00" * 1600
        ingress(pcm16_metrics(chunk, 1600))
        callbacks["on_sent"](len(chunk))
        await main._finish_input()
        # The native callback already accepted these bytes before capture closed;
        # AudioCapture's finalization barrier now delivers them during draining.
        ingress(pcm16_metrics(chunk, 1600))
        callbacks["on_sent"](len(chunk))
        pipeline = manager._reliability.pipeline.snapshot()
        assert pipeline["capture"]["bytes"] == pipeline["asr"]["sent_bytes"] == 6400
        assert pipeline["capture"]["chunks"] == 2
        assert not pipeline["capture"]["active"]
        # A replaced pipeline still cannot change the current session's counters.
        main._pipeline_generation += 1
        ingress(pcm16_metrics(chunk, 1600))
        assert manager._reliability.pipeline.snapshot()["capture"]["bytes"] == 6400
        release.set()
        await main._stop_pipeline()
    asyncio.run(scenario())
