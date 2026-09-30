"""Text-to-speech dispatcher — sequential Mistral Voxtral streaming tasks per caption."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from mistralai.client import Mistral

from app.config import AppConfig
from app.errors import (
    extract_provider_error_info,
    is_transient_provider_error,
    is_transient_transport_error,
    is_tts_guardrail_violation,
)

if TYPE_CHECKING:
    from app.state import SessionManager

logger = logging.getLogger(__name__)


@dataclass
class TTSJob:
    seq: int
    text: str
    language: str
    kind: Literal["live", "replay"]
    priority: int
    session_id: str
    tts_epoch: int
    enqueued_mono: float = 0.0
    clip_id: int = 0


class _TTSAttemptError(Exception):
    def __init__(self, cause: Exception, chunks_emitted: int) -> None:
        super().__init__(type(cause).__name__)
        self.cause = cause
        self.info = extract_provider_error_info(cause)
        self.chunks_emitted = chunks_emitted


VOICE_MAP: dict[str, str] = {
    "en": "neutral_male",
    "fr": "fr_male",
    "de": "de_male",
    "es": "es_male",
    "nl": "nl_male",
    "pt": "pt_male",
    "it": "it_male",
    "hi": "hi_male",
    "ar": "ar_male",
}


class TTSDispatcher:
    """Serial TTS queue with unlock/mute gates and epoch isolation."""

    def __init__(
        self,
        client: Mistral,
        session_manager: SessionManager,
        config: AppConfig,
    ) -> None:
        self._client = client
        self._session_manager = session_manager
        self._config = config
        self._queue: asyncio.Queue[TTSJob] = asyncio.Queue(
            maxsize=config.tts_queue_max
        )
        self._muted: bool = False
        self._audio_unlocked: bool = False
        self._tts_epoch: int = 0
        self._consumer_task: asyncio.Task[None] | None = None
        self._synth_task: asyncio.Task[None] | None = None
        self._active_synth_kind: Literal["live", "replay"] | None = None
        self._active_clip_id: int | None = None
        self._held_job: TTSJob | None = None
        self._unmute_event: asyncio.Event = asyncio.Event()
        self._unlock_event: asyncio.Event = asyncio.Event()
        self._unmute_event.set()
        self._voice_invalid: bool = False
        # Counts include synthesized clips until the browser acknowledges playback.
        # Only sequence numbers/counts are retained here, never text or audio.
        self._pending_speech: Counter[int] = Counter()
        self._playing_seq: int | None = None
        self._playing_clip: int | None = None
        self._next_clip_id = 0
        self._pending_clips: dict[int, tuple[int, float]] = {}
        self._received_clips: set[int] = set()
        self._started_clips: set[int] = set()
        self._stats_clips: set[int] = set()

    def get_speech_state(self) -> dict[str, Any]:
        return {
            "tts_epoch": self._tts_epoch,
            "pending_count": self._pending_speech.total(),
            "playing_seq": self._playing_seq,
        }

    def _emit_speech_state(self) -> None:
        self._session_manager._emit("tts_queue", self.get_speech_state())

    def _register_pending(self, job: TTSJob) -> None:
        self._next_clip_id += 1
        job.clip_id = self._next_clip_id
        job.enqueued_mono = time.monotonic()
        self._pending_clips[job.clip_id] = (job.seq, job.enqueued_mono)
        self._pending_speech[job.seq] += 1

    def _matching_clip(self, seq: int, epoch: int, clip_id: int | None) -> int | None:
        if epoch != self._tts_epoch:
            return None
        if clip_id is None:  # Compatibility for older callers, only if unambiguous.
            matches = [key for key, item in self._pending_clips.items() if item[0] == seq]
            return matches[0] if len(matches) == 1 else None
        item = self._pending_clips.get(clip_id)
        return clip_id if item is not None and item[0] == seq else None

    def acknowledge_playback(
        self, seq: int, epoch: int, *, complete: bool, clip_id: int | None = None,
    ) -> bool:
        matched = self._matching_clip(seq, epoch, clip_id)
        if matched is None:
            return False
        if complete:
            self._forget_pending(seq, matched)
        else:
            if matched in self._started_clips:
                return False
            self._started_clips.add(matched)
            self._playing_seq = seq
            self._playing_clip = matched
        self._emit_speech_state()
        return True

    def acknowledge_first_chunk(self, seq: int, epoch: int, clip_id: int) -> bool:
        matched = self._matching_clip(seq, epoch, clip_id)
        if matched is None or matched in self._received_clips:
            return False
        self._received_clips.add(matched)
        metrics = getattr(self._session_manager, "_reliability", None)
        if metrics is not None:
            metrics.speech_playback.observe_request_to_chunk(
                time.monotonic() - self._pending_clips[matched][1],
            )
        return True

    def acknowledge_browser_result(self, msg: dict[str, Any]) -> bool:
        seq, epoch, clip_id = msg.get("seq"), msg.get("tts_epoch"), msg.get("clip_id")
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (seq, epoch, clip_id)):
            return False
        if self._matching_clip(seq, epoch, clip_id) is None:
            return False
        metrics = getattr(self._session_manager, "_reliability", None)
        if msg.get("type") == "tts_playback_error":
            from app.speech_metrics import FAILURE_REASONS
            if msg.get("reason") not in FAILURE_REASONS:
                return False
            if metrics is not None:
                metrics.speech_playback.observe_failure(msg["reason"])
            self._forget_pending(seq, clip_id)
            if self._synth_task is not None and self._active_clip_id == clip_id:
                self._synth_task.cancel()
            self._emit_speech_state()
            return True
        if metrics is not None and clip_id not in self._stats_clips:
            if metrics.speech_playback.observe_browser(msg):
                self._stats_clips.add(clip_id)
                return True
        return False

    def _forget_pending(self, seq: int, clip_id: int = 0) -> None:
        if clip_id:
            if self._pending_clips.pop(clip_id, None) is None:
                return
            self._received_clips.discard(clip_id)
            self._started_clips.discard(clip_id)
            self._stats_clips.discard(clip_id)
        if self._pending_speech[seq] > 1:
            self._pending_speech[seq] -= 1
        else:
            self._pending_speech.pop(seq, None)
        if self._playing_clip == clip_id:
            self._playing_clip = None
            self._playing_seq = None

    def _clear_pending(self) -> None:
        self._pending_speech.clear()
        self._pending_clips.clear()
        self._received_clips.clear()
        self._started_clips.clear()
        self._stats_clips.clear()
        self._playing_clip = None
        self._playing_seq = None

    def catch_up(self) -> None:
        """An explicit user action stops current speech and skips all pending clips."""
        previous_epoch = self._tts_epoch
        self._tts_epoch += 1
        pending = self._pending_speech.copy()
        self._clear_pending()
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
        task = self._synth_task
        if task is not None and not task.done():
            task.cancel()
        for seq, count in pending.items():
            self._session_manager._emit(
                "tts_skipped",
                {"seq": seq, "reason": "user_catch_up", "count": count,
                 "tts_epoch": previous_epoch},
            )
        self._record_queue_depth()
        self._session_manager._emit(
            "tts_caught_up",
            {**self.get_speech_state(), "skipped_count": pending.total()},
        )


    def _record_queue_depth(self) -> None:
        callback = getattr(self._session_manager, "record_tts_queue", None)
        if callable(callback):
            callback(self._queue.qsize())

    def _emit_queue_skip(self, job: TTSJob, reason: str, *, pending: bool = True) -> None:
        if pending and job.tts_epoch == self._tts_epoch:
            self._forget_pending(job.seq, job.clip_id)
        self._session_manager._emit(
            "tts_skipped",
            {
                "seq": job.seq,
                "clip_id": job.clip_id,
                "kind": job.kind,
                "reason": reason,
                # A never-synthesized queue job cannot cancel a different clip
                # for the same caption that is already buffered in the browser.
                "audio_emitted": False,
                "tts_epoch": job.tts_epoch,
            },
        )


    def enqueue_live(self, seg: Any) -> None:
        if self._muted:
            self._session_manager._emit(
                "tts_skipped",
                {
                    "seq": seg.seq,
                    "reason": "muted",
                    "audio_emitted": False,
                    "tts_epoch": self._tts_epoch,
                },
            )
            return
        lang = seg.target_language or ""
        if lang not in VOICE_MAP:
            self._session_manager._emit(
                "tts_skipped",
                {
                    "seq": seg.seq,
                    "reason": "unsupported_language",
                    "audio_emitted": False,
                    "tts_epoch": self._tts_epoch,
                },
            )
            return

        if len(self._pending_clips) >= 64:
            self._session_manager._emit("tts_skipped", {
                "seq": seg.seq, "reason": "browser_backlog_full", "audio_emitted": False,
                "tts_epoch": self._tts_epoch,
            })
            return
        if self._queue.qsize() >= self._config.tts_queue_max:
            items: list[TTSJob] = []
            while not self._queue.empty():
                items.append(self._queue.get_nowait())
                self._queue.task_done()
            drop_idx = next((i for i, j in enumerate(items) if j.kind == "replay"), None)
            if drop_idx is None:
                drop_idx = next((i for i, j in enumerate(items) if j.kind == "live"), None)
            if drop_idx is not None:
                dropped = items.pop(drop_idx)
                self._emit_queue_skip(dropped, "queue_pressure")
            else:
                self._session_manager._emit(
                    "tts_skipped",
                    {
                        "seq": seg.seq,
                        "reason": "queue_full",
                        "audio_emitted": False,
                        "tts_epoch": self._tts_epoch,
                    },
                )
                for j in items:
                    self._queue.put_nowait(j)
                self._record_queue_depth()
                return
            for j in items:
                self._queue.put_nowait(j)

        job = TTSJob(
            seq=seg.seq,
            text=seg.translated_text or "",
            language=lang,
            kind="live",
            priority=0,
            session_id=self._session_manager.session.id,
            tts_epoch=self._tts_epoch,
        )
        self._register_pending(job)
        self._queue.put_nowait(job)
        self._record_queue_depth()
        self._emit_speech_state()

    def enqueue_replay(self, seq: int, text: str, language: str) -> None:
        if self._muted:
            self._session_manager._emit(
                "tts_skipped",
                {
                    "seq": seq,
                    "kind": "replay",
                    "reason": "muted",
                    "audio_emitted": False,
                    "tts_epoch": self._tts_epoch,
                },
            )
            return
        if language not in VOICE_MAP:
            self._session_manager._emit(
                "tts_skipped",
                {
                    "seq": seq,
                    "reason": "unsupported_language",
                    "audio_emitted": False,
                    "tts_epoch": self._tts_epoch,
                },
            )
            return

        if len(self._pending_clips) >= 64:
            self._session_manager._emit("tts_skipped", {
                "seq": seq, "reason": "browser_backlog_full", "audio_emitted": False,
                "tts_epoch": self._tts_epoch,
            })
            return
        items: list[TTSJob] = []
        while not self._queue.empty():
            items.append(self._queue.get_nowait())
            self._queue.task_done()
        superseded = [j for j in items if j.kind == "replay"]
        items = [j for j in items if j.kind != "replay"]
        for skipped in superseded:
            self._emit_queue_skip(skipped, "replay_superseded")
        job = TTSJob(
            seq=seq,
            text=text,
            language=language,
            kind="replay",
            priority=1,
            session_id=self._session_manager.session.id,
            tts_epoch=self._tts_epoch,
        )
        if len(items) >= self._config.tts_queue_max:
            for queued in items:
                self._queue.put_nowait(queued)
            self._emit_queue_skip(job, "queue_full", pending=False)
            self._record_queue_depth()
            return
        self._register_pending(job)
        items.insert(0, job)
        for j in items:
            self._queue.put_nowait(j)
        self._record_queue_depth()
        self._emit_speech_state()

    def set_muted(self, muted: bool) -> None:
        was_muted = self._muted
        self._muted = muted
        if not muted:
            self._unmute_event.set()
        else:
            self._unmute_event.clear()
            if not was_muted:
                self._tts_epoch += 1
            while not self._queue.empty():
                job = self._queue.get_nowait()
                self._queue.task_done()
                self._emit_queue_skip(job, "muted")
            self._record_queue_depth()
            task = self._synth_task
            if task is not None and not task.done():
                task.cancel()
            self._clear_pending()
        self._emit_speech_state()

    def set_audio_unlocked(self, unlocked: bool) -> None:
        self._audio_unlocked = unlocked
        if unlocked:
            self._unlock_event.set()
        else:
            self._unlock_event.clear()
            # Browser audio is document-local and cannot survive a reconnect.
            # Preserve jobs still in the server queue; retire already dispatched clips.
            queued = list(self._queue._queue)
            # queue.get() may already have completed before a disconnect relocks
            # the second unlock gate. That consumer-held job is still unsynthesized.
            if (self._held_job is not None and self._active_clip_id is None
                    and self._held_job.clip_id in self._pending_clips):
                queued.append(self._held_job)
            queued_ids = {job.clip_id for job in queued}
            retired = [(key, item[0]) for key, item in self._pending_clips.items()
                       if key not in queued_ids]
            previous_epoch = self._tts_epoch
            self._tts_epoch += 1
            self._clear_pending()
            for job in queued:
                job.tts_epoch = self._tts_epoch
                self._pending_clips[job.clip_id] = (job.seq, job.enqueued_mono)
                self._pending_speech[job.seq] += 1
            if self._synth_task is not None and not self._synth_task.done():
                self._synth_task.cancel()
            for clip_id, seq in retired:
                self._session_manager._emit("tts_skipped", {
                    "seq": seq, "clip_id": clip_id, "tts_epoch": previous_epoch,
                    "reason": "browser_replaced",
                })
            self._emit_speech_state()

    def _job_stale(self, job: TTSJob) -> bool:
        if job.tts_epoch != self._tts_epoch:
            return True
        if job.clip_id and job.clip_id not in self._pending_clips:
            return True
        if job.session_id != self._session_manager.session.id:
            return True
        return False

    async def _consumer(self) -> None:
        try:
            while True:
                await self._unlock_event.wait()
                job = await self._queue.get()
                self._held_job = job
                try:
                    now = time.monotonic()
                    wait_cb = getattr(self._session_manager, "observe_tts_queue_wait", None)
                    if self._job_stale(job):
                        logger.debug(
                            "Skipping stale TTS job seq=%s epoch=%s (current=%s)",
                            job.seq,
                            job.tts_epoch,
                            self._tts_epoch,
                        )
                        continue
                    if job.enqueued_mono and callable(wait_cb):
                        wait_cb(job.seq, now - job.enqueued_mono)
                    if self._job_stale(job):
                        logger.debug(
                            "Skipping stale TTS job seq=%s epoch=%s (current=%s)",
                            job.seq,
                            job.tts_epoch,
                            self._tts_epoch,
                        )
                        continue
                    if self._muted:
                        await self._unmute_event.wait()
                    if self._job_stale(job):
                        logger.debug(
                            "Skipping stale TTS job seq=%s epoch=%s (current=%s)",
                            job.seq,
                            job.tts_epoch,
                            self._tts_epoch,
                        )
                        continue
                    if not self._audio_unlocked:
                        await self._unlock_event.wait()
                    if self._job_stale(job):
                        logger.debug(
                            "Skipping stale TTS job seq=%s epoch=%s (current=%s)",
                            job.seq,
                            job.tts_epoch,
                            self._tts_epoch,
                        )
                        continue
                    self._active_synth_kind = job.kind
                    self._active_clip_id = job.clip_id
                    self._synth_task = asyncio.ensure_future(self._synthesise(job))
                    try:
                        await self._synth_task
                    except asyncio.CancelledError:
                        pass
                    finally:
                        self._emit_speech_state()
                        self._synth_task = None
                        self._active_synth_kind = None
                        self._active_clip_id = None
                finally:
                    self._held_job = None
                    self._queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _synthesise(self, job: TTSJob) -> None:
        max_attempts = self._config.tts_transient_max_retries + 1
        for attempt in range(1, max_attempts + 1):
            try:
                completed = await self._synthesise_once(job)
                if completed and attempt > 1:
                    self._session_manager._emit(
                        "tts_recovered",
                        {
                            "seq": job.seq,
                "clip_id": job.clip_id,
                            "kind": job.kind,
                            "attempts": attempt,
                            "tts_epoch": job.tts_epoch,
                        },
                    )
                return
            except asyncio.CancelledError:
                raise
            except _TTSAttemptError as failure:
                if self._job_stale(job):
                    return
                info = failure.info
                error_text = str(failure.cause)
                invalid_voice = (
                    "invalid_voice" in error_text or "Voice '" in error_text
                )
                transient = is_transient_provider_error(
                    info
                ) or is_transient_transport_error(failure.cause)
                can_retry = (
                    transient
                    and failure.chunks_emitted == 0
                    and attempt < max_attempts
                )

                if can_retry:
                    base_delay_ms = min(
                        self._config.tts_retry_base_delay_ms * (2 ** (attempt - 1)),
                        self._config.tts_retry_max_delay_ms,
                    )
                    jitter = random.uniform(
                        -self._config.tts_retry_jitter_factor,
                        self._config.tts_retry_jitter_factor,
                    )
                    delay_ms = max(0, int(base_delay_ms * (1 + jitter)))
                    logger.warning(
                        "TTS transient failure: seq=%s attempt=%s status_code=%s",
                        job.seq,
                        attempt,
                        info.status_code if info is not None else None,
                    )
                    self._session_manager._emit(
                        "tts_retrying",
                        {
                            "seq": job.seq,
                "clip_id": job.clip_id,
                            "kind": job.kind,
                            "attempt": attempt,
                            "next_attempt": attempt + 1,
                            "delay_ms": delay_ms,
                            "status_code": (
                                info.status_code if info is not None else None
                            ),
                            "tts_epoch": job.tts_epoch,
                        },
                    )
                    await asyncio.sleep(delay_ms / 1000)
                    continue

                if invalid_voice:
                    self._voice_invalid = True
                    reason = "invalid_voice_config"
                elif transient and failure.chunks_emitted > 0:
                    reason = "partial_audio_interrupted"
                elif transient:
                    reason = "provider_transient_exhausted"
                else:
                    reason = "provider_failure"

                logger.warning(
                    "TTS synthesis failed: seq=%s reason=%s attempts=%s status_code=%s",
                    job.seq,
                    reason,
                    attempt,
                    info.status_code if info is not None else None,
                )
                if job.tts_epoch == self._tts_epoch:
                    self._forget_pending(job.seq, job.clip_id)
                self._session_manager._emit(
                    "tts_error",
                    {
                        "seq": job.seq,
                "clip_id": job.clip_id,
                        "kind": job.kind,
                        "reason": reason,
                        "attempts": attempt,
                        "status_code": (
                            info.status_code if info is not None else None
                        ),
                        "chunks_emitted": failure.chunks_emitted,
                        "audio_emitted": failure.chunks_emitted > 0,
                        "tts_epoch": job.tts_epoch,
                    },
                )
                return

    async def _synthesise_once(self, job: TTSJob) -> bool:
        chunk_index = 0
        try:
            if self._job_stale(job):
                return False
            if self._voice_invalid:
                self._forget_pending(job.seq, job.clip_id)
                self._session_manager._emit(
                    "tts_skipped",
                    {
                        "seq": job.seq,
                "clip_id": job.clip_id,
                        "reason": "invalid_voice_config",
                        "audio_emitted": False,
                        "tts_epoch": job.tts_epoch,
                    },
                )
                return False
            voice_id = self._config.tts_voice_id or VOICE_MAP[job.language]
            self._session_manager._emit(
                "tts_speaking",
                {
                    "seq": job.seq,
                "clip_id": job.clip_id,
                    "kind": job.kind,
                    "tts_epoch": job.tts_epoch,
                },
            )
            start_cb = getattr(self._session_manager, "observe_tts_synth_start", None)
            if callable(start_cb):
                start_cb(job.seq)
            stream = await self._client.audio.speech.complete_async(
                model=self._config.tts_model,
                input=job.text,
                voice_id=voice_id,
                response_format="pcm",
                stream=True,
            )
            async with stream as events:
                async for event in events:
                    if self._job_stale(job):
                        return False
                    audio_data = getattr(event, "audio_data", None)
                    if audio_data is None:
                        payload = getattr(event, "data", None)
                        if payload is not None:
                            audio_data = getattr(payload, "audio_data", None)
                            if audio_data is None and isinstance(payload, dict):
                                audio_data = payload.get("audio_data")
                    if audio_data is None:
                        continue
                    self._session_manager._emit(
                        "tts_audio",
                        {
                            "seq": job.seq,
                "clip_id": job.clip_id,
                            "kind": job.kind,
                            "chunk_index": chunk_index,
                            "is_last": False,
                            "data": audio_data,
                            "tts_epoch": job.tts_epoch,
                        },
                    )
                    if chunk_index == 0:
                        first_cb = getattr(self._session_manager, "observe_tts_first_audio", None)
                        if callable(first_cb):
                            first_cb(job.seq)
                    chunk_index += 1
            self._session_manager._emit(
                "tts_audio",
                {
                    "seq": job.seq,
                "clip_id": job.clip_id,
                    "kind": job.kind,
                    "chunk_index": chunk_index,
                    "is_last": True,
                    "data": "",
                    "tts_epoch": job.tts_epoch,
                },
            )
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _info = extract_provider_error_info(exc)
            if is_tts_guardrail_violation(_info):
                if job.tts_epoch == self._tts_epoch:
                    self._forget_pending(job.seq, job.clip_id)
                logger.warning(
                    "TTS guardrail rejection seq=%s type=%s code=%s status=%s",
                    job.seq,
                    _info.error_type,
                    _info.code,
                    _info.status_code,
                )
                self._session_manager._emit(
                    "tts_skipped",
                    {
                        "seq": job.seq,
                "clip_id": job.clip_id,
                        "reason": "guardrail_violation",
                        "audio_emitted": chunk_index > 0,
                        "provider": "mistral",
                        "provider_code": _info.code,
                        "status_code": _info.status_code,
                        "tts_epoch": job.tts_epoch,
                    },
                )
                return False
            raise _TTSAttemptError(exc, chunk_index) from None

    async def drain(self) -> None:
        if self._synth_task is not None and not self._synth_task.done():
            self._synth_task.cancel()
            await asyncio.shield(
                asyncio.wait([self._synth_task], timeout=2.0),
            )
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
        was_muted = self._muted
        self._tts_epoch += 1
        self._clear_pending()
        self._emit_speech_state()
        # Unlock is scoped to the browser/WebSocket connection: drain() runs on
        # stop/reset/new_session within the same connection, so we do not clear
        # _unlock_event or _audio_unlocked here. Re-gating happens only in ws.py
        # on WebSocket disconnect or connection replacement via set_audio_unlocked(False).
        self._unmute_event.set()
        if was_muted:
            self._unmute_event.clear()

    async def start(self) -> None:
        if self._consumer_task is not None and not self._consumer_task.done():
            return
        self._consumer_task = asyncio.create_task(self._consumer())

    async def stop(self) -> None:
        if self._synth_task is not None and not self._synth_task.done():
            self._synth_task.cancel()
            try:
                await self._synth_task
            except asyncio.CancelledError:
                pass
        self._synth_task = None
        if self._consumer_task is not None and not self._consumer_task.done():
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        self._consumer_task = None
