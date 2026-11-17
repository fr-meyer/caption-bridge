"""Deterministic, content-free full-pipeline product scenario."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import orjson

import app.reconnect as reconnect_module
import app.ws as ws_module
from app import translation_models
from app.boundary import BoundaryDetector
from app.config import AppConfig
from app.journal import SessionJournal
from app.reconnect import ReconnectionManager, ReconnectMetrics
from app.reliability import write_soak_record
from app.state import ReadinessCheck, SessionManager
from app.translate import TranslationDispatcher
from app.tts import TTSDispatcher
from app.ws import _enqueue_outbound, _OutboundObsState
from scripts.synthetic_translation_catalogue import SYNTHETIC_MODEL, synthetic_translation_catalogue

_SEGMENT_ID = re.compile(r"(?:segment|caption|fragment) (\d+)", re.IGNORECASE)


class _CapacityError(Exception):
    status_code = 429
    body = json.dumps(
        {
            "type": "service_tier_capacity_exceeded",
            "code": "3505",
            "raw_status_code": 429,
        }
    )


class _ProviderError(Exception):
    def __init__(
        self,
        status_code: int,
        *,
        error_type: str | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__("synthetic provider failure")
        self.status_code = status_code
        body: dict[str, Any] = {"raw_status_code": status_code}
        if error_type is not None:
            body["type"] = error_type
        if code is not None:
            body["code"] = code
        self.body = json.dumps(body)


class _CloseError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__("synthetic close")
        self.code = code


class _TranslationProvider:
    name = "synthetic"

    def __init__(self) -> None:
        self.attempts: dict[int, int] = defaultdict(int)

    async def translate(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        del model, temperature, max_tokens
        user_content = next(
            message["content"]
            for message in messages
            if message.get("role") == "user"
        )
        segment_block = user_content.rsplit("<segment_to_translate>", 1)[-1]
        match = _SEGMENT_ID.search(segment_block)
        if match is None:
            raise RuntimeError("synthetic segment id missing")
        seq = int(match.group(1))
        self.attempts[seq] += 1
        if seq == 3:
            await asyncio.sleep(0.2)
        if seq == 6:
            raise _CapacityError("synthetic capacity limit")
        return f"Synthetic translated caption {seq:06d}."


class _AudioStream:
    def __init__(self) -> None:
        self._remaining = 1

    async def __aenter__(self) -> _AudioStream:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False

    def __aiter__(self) -> _AudioStream:
        return self

    async def __anext__(self) -> SimpleNamespace:
        if self._remaining == 0:
            raise StopAsyncIteration
        self._remaining -= 1
        return SimpleNamespace(audio_data="synthetic-audio")


class _SpeechProvider:
    def __init__(self) -> None:
        self.attempts: dict[int, int] = defaultdict(int)

    async def complete_async(self, **kwargs: Any) -> _AudioStream:
        match = _SEGMENT_ID.search(str(kwargs.get("input", "")))
        if match is None:
            raise RuntimeError("synthetic TTS segment id missing")
        seq = int(match.group(1))
        self.attempts[seq] += 1
        if seq == 1 and self.attempts[seq] == 1:
            raise _ProviderError(503)
        if seq == 2:
            raise _ProviderError(
                403,
                error_type="guardrail_violation",
                code="1920",
            )
        return _AudioStream()


class _FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = asyncio.Event()
        self.snapshot_sent = asyncio.Event()
        self.disconnected = asyncio.Event()
        self.sent: list[dict[str, Any]] = []
        self.close_code: int | None = None
        self.close_reason: str | None = None

    async def accept(self) -> None:
        self.accepted.set()

    async def close(self, code: int, reason: str) -> None:
        self.close_code = code
        self.close_reason = reason
        self.disconnected.set()

    async def send_bytes(self, payload: bytes) -> None:
        event = orjson.loads(payload)
        self.sent.append(event)
        if event.get("type") == "session_snapshot":
            self.snapshot_sent.set()

    async def iter_text(self):
        await self.disconnected.wait()
        if False:
            yield ""


@dataclass(frozen=True)
class FullPipelineReport:
    segments: int
    done: int
    timed_out: int
    failed: int
    pending: int
    captions: int
    duplicates: int
    ordered: bool
    reconnect_fragments: int
    reconnect_attempts: int
    reconnect_recovered: int
    capacity_warnings: int
    translation_provider_calls: int
    tts_provider_calls: int
    tts_retries: int
    tts_recovered: int
    tts_guardrail_skips: int
    tts_audio_completed: int
    browser_queue_depth: int
    browser_queue_bounded: bool
    browser_queue_coalesced: int
    browser_queue_dropped: int
    browser_critical_preserved: bool
    owner_conflict_rejected: bool
    owner_retained_on_conflict: bool
    reconnect_audio_relocked: bool
    reconnect_snapshot_preserved: bool
    export_files: int
    export_statuses_preserved: bool
    journal_stopped: bool
    journal_exported: bool
    remaining_translation_tasks: int
    remaining_tts_jobs: int
    remaining_tts_tasks: int
    remaining_browser_tasks: int
    remaining_lifecycle_tasks: int
    temporary_artifacts_removed: bool
    duration_ms: int
    passed: bool

    def to_dict(self) -> dict[str, int | bool]:
        return asdict(self)


def _event_count(events: list[dict[str, Any]], event_type: str) -> int:
    return sum(1 for event in events if event.get("type") == event_type)


def _test_bounded_browser_queue() -> tuple[int, bool, int, int, bool]:
    queue: asyncio.Queue[tuple[dict[str, Any], float]] = asyncio.Queue(maxsize=4)
    obs = _OutboundObsState()
    _enqueue_outbound(queue, {"type": "source_partial", "text": "old"}, obs)
    _enqueue_outbound(queue, {"type": "elapsed", "seconds": 1}, obs)
    _enqueue_outbound(
        queue,
        {"type": "tts_audio", "data": "synthetic", "is_last": False},
        obs,
    )
    _enqueue_outbound(queue, {"type": "readiness", "checks": []}, obs)
    _enqueue_outbound(queue, {"type": "source_partial", "text": "new"}, obs)
    _enqueue_outbound(queue, {"type": "status", "status": "session_ended"}, obs)
    queued = [item[0] for item in list(queue._queue)]
    critical_preserved = any(
        event.get("type") == "status" and event.get("status") == "session_ended"
        for event in queued
    )
    return (
        queue.qsize(),
        queue.qsize() <= queue.maxsize,
        ws_module._ws_metrics.coalesced_events,
        ws_module._ws_metrics.dropped_events,
        critical_preserved,
    )


async def _test_websocket_ownership(
    manager: SessionManager,
    tts: TTSDispatcher,
) -> tuple[bool, bool, bool, bool, int]:
    first = _FakeWebSocket()
    second = _FakeWebSocket()
    reconnect = _FakeWebSocket()
    first_task = asyncio.create_task(ws_module.websocket_endpoint(first))  # type: ignore[arg-type]
    second_task: asyncio.Task[None] | None = None
    reconnect_task: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(first.accepted.wait(), timeout=1)
        await asyncio.wait_for(first.snapshot_sent.wait(), timeout=1)
        tts.set_audio_unlocked(True)

        second_task = asyncio.create_task(ws_module.websocket_endpoint(second))  # type: ignore[arg-type]
        await asyncio.wait_for(second.accepted.wait(), timeout=1)
        await asyncio.wait_for(second_task, timeout=1)
        conflict_rejected = (
            second.close_code == ws_module.OWNER_CONFLICT_CODE
            and second.close_reason == ws_module.OWNER_CONFLICT_REASON
            and not second.snapshot_sent.is_set()
            and any(
                event.get("type") == "connection_lifecycle"
                and event.get("state") == "rejected"
                and event.get("reason") == ws_module.OWNER_CONFLICT_REASON
                for event in second.sent
            )
        )
        owner_retained = (
            not first.disconnected.is_set()
            and not first_task.done()
            and ws_module._active_connection is not None
            and ws_module._active_connection.websocket is first
            and tts._audio_unlocked
        )

        first.disconnected.set()
        await asyncio.wait_for(first_task, timeout=1)
        audio_relocked = not tts._audio_unlocked
        reconnect_task = asyncio.create_task(ws_module.websocket_endpoint(reconnect))  # type: ignore[arg-type]
        await asyncio.wait_for(reconnect.snapshot_sent.wait(), timeout=1)

        first_snapshot = next(
            event for event in first.sent if event.get("type") == "session_snapshot"
        )
        reconnect_snapshot = next(
            event for event in reconnect.sent if event.get("type") == "session_snapshot"
        )
        expected_seq = list(range(1, 7))
        snapshots_preserved = all(
            [segment["seq"] for segment in snapshot["segments"]] == expected_seq
            for snapshot in (first_snapshot, reconnect_snapshot)
        )
        reconnect.disconnected.set()
        await asyncio.wait_for(reconnect_task, timeout=1)
        remaining = sum(not task.done() for task in (first_task, second_task, reconnect_task))
        return conflict_rejected, owner_retained, audio_relocked, snapshots_preserved, remaining
    finally:
        first.disconnected.set()
        second.disconnected.set()
        reconnect.disconnected.set()
        tasks = [first_task]
        if second_task is not None:
            tasks.append(second_task)
        if reconnect_task is not None:
            tasks.append(reconnect_task)
        await asyncio.gather(*tasks, return_exceptions=True)
        manager.on_client_connect()
        await asyncio.sleep(0)


@synthetic_translation_catalogue()
async def run_full_pipeline_scenario() -> FullPipelineReport:
    started = time.perf_counter()
    old_health_timeout = reconnect_module._POST_HANDSHAKE_HEALTH_TIMEOUT_S
    old_reconnect_metrics = reconnect_module._reconnect_metrics
    old_ws_metrics = ws_module._ws_metrics
    old_ws_manager = ws_module.manager
    old_ws_settings = ws_module.settings
    old_ws_catalogue = ws_module.catalogue
    ws_module.catalogue = translation_models.catalogue
    old_active_connection = ws_module._active_connection
    old_connection_counter = ws_module._connection_counter
    temp_path = ""
    values: dict[str, Any] = {}

    reconnect_module._POST_HANDSHAKE_HEALTH_TIMEOUT_S = 0.001
    reconnect_module._reconnect_metrics = ReconnectMetrics()
    ws_module._ws_metrics = ws_module._WsMetrics()

    dispatcher: TranslationDispatcher | None = None
    tts: TTSDispatcher | None = None
    manager: SessionManager | None = None
    detector: BoundaryDetector | None = None
    try:
        with tempfile.TemporaryDirectory(
            prefix="caption-bridge-full-pipeline-"
        ) as temp_dir:
            temp_path = temp_dir
            root = Path(temp_dir)
            config = AppConfig(
                _env_file=None,
                MISTRAL_TRANSLATE_MODEL=SYNTHETIC_MODEL,
                MISTRAL_TTS_ENABLED=True,
                MISTRAL_TTS_QUEUE_MAX=8,
                MISTRAL_TTS_TRANSIENT_MAX_RETRIES=2,
                MISTRAL_TTS_RETRY_BASE_DELAY_MS=0,
                MISTRAL_TTS_RETRY_MAX_DELAY_MS=1,
                MISTRAL_TTS_RETRY_JITTER_FACTOR=0.0,
                TRANSLATION_TIMEOUT_MS=100,
                TRANSLATION_GLM_TIMEOUT_MS=100,
                TRANSLATION_DRAIN_TIMEOUT_MS=5000,
                TRANSLATION_MAX_CONCURRENCY=4,
                TRANSLATION_REPAIR_MAX_ATTEMPTS=0,
                TRANSLATION_429_MAX_RETRIES=1,
                TRANSLATION_429_BASE_DELAY_MS=0,
                TRANSLATION_429_MAX_DELAY_MS=1,
                TRANSLATION_429_JITTER_FACTOR=0.0,
                reconnect_base_backoff_ms=0,
                reconnect_max_backoff_ms=1,
                reconnect_max_attempts=3,
                reconnect_max_elapsed_ms=1000,
                reconnect_jitter_factor=0.0,
                client_disconnect_grace_ms=1000,
                journal_dir=str(root / "journal"),
                export_dir=str(root / "exports"),
                recovery_export_dir=str(root / "recovered"),
                reliability_dir=str(root / "reliability"),
            )
            manager = SessionManager(config)
            journal = SessionJournal(manager.session.id, config)
            manager.set_journal(journal)
            events: list[dict[str, Any]] = []
            manager.subscribe(events.append)

            translation_provider = _TranslationProvider()
            dispatcher = TranslationDispatcher(
                manager,
                config,
                provider=translation_provider,
            )
            manager.set_dispatcher(dispatcher)

            speech = _SpeechProvider()
            tts_client = SimpleNamespace(audio=SimpleNamespace(speech=speech))
            tts = TTSDispatcher(tts_client, manager, config)
            manager.set_tts_dispatcher(tts)
            await tts.start()
            tts.set_audio_unlocked(True)

            manager.set_readiness(
                [
                    ReadinessCheck(
                        name="synthetic provider",
                        key="synthetic",
                        ready=True,
                        detail="ready",
                    )
                ]
            )
            manager.set_status("listening")
            detector = BoundaryDetector(
                pause_timeout_s=60,
                on_partial=manager.update_partial,
                on_finalize=manager.finalize_segment,
            )

            detector.push("Synthetic segment 000001.")
            detector.push(" Synthetic segment 000002.")
            detector.push(" Synthetic segment 000003.")
            detector.push(" Synthetic reconnect fragment 000004")

            reconnect = ReconnectionManager(manager, config)
            reconnect.get_detector = lambda: detector
            reconnect.finalize_reconnect_fragment = manager.finalize_reconnect_fragment
            teardown_calls = 0
            reconnect_start_calls = 0

            async def teardown_pipeline() -> None:
                nonlocal teardown_calls
                teardown_calls += 1

            async def start_pipeline() -> None:
                nonlocal reconnect_start_calls
                reconnect_start_calls += 1
                if reconnect_start_calls == 1:
                    raise OSError("synthetic reconnect failure")

            reconnect.teardown_pipeline = teardown_pipeline
            reconnect.start_pipeline = start_pipeline
            await reconnect._reconnect_loop(_CloseError(1012))

            detector.push(" Synthetic segment 000005.")
            detector.push(" Synthetic segment 000006.")
            await dispatcher.drain()
            await asyncio.wait_for(tts._queue.join(), timeout=2)
            await asyncio.sleep(0)

            queue_result = _test_bounded_browser_queue()

            ws_module.manager = manager
            ws_module.settings = config
            ws_module._active_connection = None
            ws_module._connection_counter = 0
            ownership_result = await _test_websocket_ownership(manager, tts)

            manager.set_status("session_ended")
            manager.on_client_disconnect()
            export_result = manager.export()
            if not export_result["success"]:
                raise RuntimeError("synthetic export failed")
            export_path = Path(export_result["path"])
            export_files = sorted(path.name for path in export_path.iterdir())
            export_payload = orjson.loads(
                (export_path / "transcript.json").read_bytes()
            )
            export_statuses = [
                segment["translation_status"]
                for segment in export_payload["segments"]
            ]
            journal_records = [
                orjson.loads(line)
                for line in journal._path.read_bytes().splitlines()
                if line.strip()
            ]

            status_counts = Counter(
                segment.translation_status for segment in manager.session.segments
            )
            captions = [event for event in events if event.get("type") == "caption"]
            delivered_seq = [int(event["seq"]) for event in captions]
            delivered_duplicates = len(delivered_seq) - len(set(delivered_seq))
            reconnect_fragments = sum(
                segment.segment_kind == "reconnect_fragment"
                for segment in manager.session.segments
            )
            tts_guardrail_skips = sum(
                event.get("type") == "tts_skipped"
                and event.get("reason") == "guardrail_violation"
                for event in events
            )
            tts_audio_completed = sum(
                event.get("type") == "tts_audio" and event.get("is_last") is True
                for event in events
            )
            remaining_lifecycle = sum(
                task is not None and not task.done()
                for task in (manager._elapsed_task, manager._grace_task)
            )
            values = {
                "segments": len(manager.session.segments),
                "done": status_counts["done"],
                "timed_out": status_counts["timed_out"],
                "failed": status_counts["failed"],
                "pending": status_counts["pending"],
                "captions": len(captions),
                "duplicates": delivered_duplicates,
                "ordered": delivered_seq == list(range(1, 7)),
                "reconnect_fragments": reconnect_fragments,
                "reconnect_attempts": reconnect_start_calls,
                "reconnect_recovered": _event_count(events, "recovered"),
                "capacity_warnings": _event_count(
                    events, "provider_capacity_warning"
                ),
                "translation_provider_calls": sum(
                    translation_provider.attempts.values()
                ),
                "tts_provider_calls": sum(speech.attempts.values()),
                "tts_retries": _event_count(events, "tts_retrying"),
                "tts_recovered": _event_count(events, "tts_recovered"),
                "tts_guardrail_skips": tts_guardrail_skips,
                "tts_audio_completed": tts_audio_completed,
                "browser_queue_depth": queue_result[0],
                "browser_queue_bounded": queue_result[1],
                "browser_queue_coalesced": queue_result[2],
                "browser_queue_dropped": queue_result[3],
                "browser_critical_preserved": queue_result[4],
                "owner_conflict_rejected": ownership_result[0],
                "owner_retained_on_conflict": ownership_result[1],
                "reconnect_audio_relocked": ownership_result[2],
                "reconnect_snapshot_preserved": ownership_result[3],
                "export_files": len(export_files),
                "export_statuses_preserved": export_statuses
                == ["done", "done", "timed_out", "done", "done", "failed"],
                "journal_stopped": any(
                    record.get("type") == "session_stopped"
                    for record in journal_records
                ),
                "journal_exported": any(
                    record.get("type") == "session_exported"
                    for record in journal_records
                ),
                "remaining_translation_tasks": len(dispatcher._in_flight),
                "remaining_tts_jobs": tts._queue.qsize(),
                "remaining_browser_tasks": ownership_result[4],
                "remaining_lifecycle_tasks": remaining_lifecycle,
            }
            values["passed"] = all(
                (
                    values["segments"] == 6,
                    values["done"] == 4,
                    values["timed_out"] == 1,
                    values["failed"] == 1,
                    values["pending"] == 0,
                    values["captions"] == 6,
                    values["duplicates"] == 0,
                    values["ordered"],
                    values["reconnect_fragments"] == 1,
                    values["reconnect_attempts"] == 2,
                    values["reconnect_recovered"] == 1,
                    teardown_calls == 2,
                    values["capacity_warnings"] == 1,
                    values["translation_provider_calls"] == 7,
                    values["tts_provider_calls"] == 5,
                    values["tts_retries"] == 1,
                    values["tts_recovered"] == 1,
                    values["tts_guardrail_skips"] == 1,
                    values["tts_audio_completed"] == 3,
                    values["browser_queue_depth"] == 4,
                    values["browser_queue_bounded"],
                    values["browser_queue_coalesced"] == 1,
                    values["browser_queue_dropped"] == 2,
                    values["browser_critical_preserved"],
                    values["owner_conflict_rejected"],
                    values["owner_retained_on_conflict"],
                    values["reconnect_audio_relocked"],
                    values["reconnect_snapshot_preserved"],
                    export_files == ["transcript.json", "transcript.txt"],
                    values["export_statuses_preserved"],
                    values["journal_stopped"],
                    values["journal_exported"],
                    values["remaining_translation_tasks"] == 0,
                    values["remaining_tts_jobs"] == 0,
                    values["remaining_browser_tasks"] == 0,
                    values["remaining_lifecycle_tasks"] == 0,
                )
            )
    finally:
        if detector is not None:
            detector.reset()
        if dispatcher is not None:
            await dispatcher.drain()
        if tts is not None:
            await tts.stop()
        if manager is not None:
            manager._cancel_elapsed_ticker()
            manager._cancel_grace_task()
        reconnect_module._POST_HANDSHAKE_HEALTH_TIMEOUT_S = old_health_timeout
        reconnect_module._reconnect_metrics = old_reconnect_metrics
        ws_module._ws_metrics = old_ws_metrics
        ws_module.manager = old_ws_manager
        ws_module.settings = old_ws_settings
        ws_module.catalogue = old_ws_catalogue
        ws_module._active_connection = old_active_connection
        ws_module._connection_counter = old_connection_counter

    temporary_artifacts_removed = bool(temp_path) and not Path(temp_path).exists()
    remaining_tts_tasks = 0
    if tts is not None:
        remaining_tts_tasks = sum(
            task is not None and not task.done()
            for task in (tts._consumer_task, tts._synth_task)
        )
    values["remaining_tts_tasks"] = remaining_tts_tasks
    values["temporary_artifacts_removed"] = temporary_artifacts_removed
    values["duration_ms"] = round((time.perf_counter() - started) * 1000)
    values["passed"] = (
        bool(values.get("passed"))
        and remaining_tts_tasks == 0
        and temporary_artifacts_removed
    )
    return FullPipelineReport(**values)


def _render_human(report: FullPipelineReport) -> None:
    print("Full pipeline scenario (content-free)")
    for key, value in report.to_dict().items():
        print(f"  {key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--record-history",
        type=Path,
        metavar="DIRECTORY",
        help="explicitly persist an aggregate-only scenario record",
    )
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    report = asyncio.run(run_full_pipeline_scenario())
    if args.record_history is not None:
        write_soak_record(
            args.record_history,
            run_type="full_pipeline",
            passed=report.passed,
            duration_ms=report.duration_ms,
            case_count=report.segments,
        )
    if args.json:
        print(json.dumps(report.to_dict(), sort_keys=True))
    else:
        _render_human(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
