"""Text-to-speech dispatcher — sequential Mistral Voxtral streaming tasks per caption."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from mistralai.client import Mistral

from app.config import AppConfig

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
        self._queue: asyncio.Queue[TTSJob] = asyncio.Queue()
        self._muted: bool = False
        self._audio_unlocked: bool = False
        self._tts_epoch: int = 0
        self._consumer_task: asyncio.Task[None] | None = None
        self._synth_task: asyncio.Task[None] | None = None
        self._active_synth_kind: Literal["live", "replay"] | None = None
        self._unmute_event: asyncio.Event = asyncio.Event()
        self._unlock_event: asyncio.Event = asyncio.Event()
        self._unmute_event.set()

    def enqueue_live(self, seg: Any) -> None:
        lang = seg.target_language or ""
        if lang not in VOICE_MAP:
            self._session_manager._emit(
                "tts_skipped",
                {
                    "seq": seg.seq,
                    "reason": "unsupported_language",
                    "tts_epoch": self._tts_epoch,
                },
            )
            return

        if self._queue.qsize() >= self._config.tts_queue_max:
            items: list[TTSJob] = []
            while not self._queue.empty():
                items.append(self._queue.get_nowait())
                self._queue.task_done()
            drop_idx = next((i for i, j in enumerate(items) if j.kind == "live"), None)
            if drop_idx is not None:
                items.pop(drop_idx)
            else:
                self._session_manager._emit(
                    "tts_skipped",
                    {
                        "seq": seg.seq,
                        "reason": "queue_full",
                        "tts_epoch": self._tts_epoch,
                    },
                )
                for j in items:
                    self._queue.put_nowait(j)
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
        self._queue.put_nowait(job)

    def enqueue_replay(self, seq: int, text: str, language: str) -> None:
        if language not in VOICE_MAP:
            self._session_manager._emit(
                "tts_skipped",
                {
                    "seq": seq,
                    "reason": "unsupported_language",
                    "tts_epoch": self._tts_epoch,
                },
            )
            return

        items: list[TTSJob] = []
        while not self._queue.empty():
            items.append(self._queue.get_nowait())
            self._queue.task_done()
        items = [j for j in items if j.kind != "replay"]
        job = TTSJob(
            seq=seq,
            text=text,
            language=language,
            kind="replay",
            priority=1,
            session_id=self._session_manager.session.id,
            tts_epoch=self._tts_epoch,
        )
        items.insert(0, job)
        for j in items:
            self._queue.put_nowait(j)

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        if not muted:
            self._unmute_event.set()
        else:
            self._unmute_event.clear()
            task = self._synth_task
            if (
                task is not None
                and not task.done()
                and self._active_synth_kind == "live"
            ):
                task.cancel()

    def set_audio_unlocked(self, unlocked: bool) -> None:
        self._audio_unlocked = unlocked
        if unlocked:
            self._unlock_event.set()
        else:
            self._unlock_event.clear()

    def reset_mute(self) -> None:
        self._muted = False
        self._unmute_event.set()

    def _job_stale(self, job: TTSJob) -> bool:
        if job.tts_epoch != self._tts_epoch:
            return True
        if job.session_id != self._session_manager.session.id:
            return True
        return False

    async def _consumer(self) -> None:
        try:
            while True:
                await self._unlock_event.wait()
                job = await self._queue.get()
                try:
                    if self._job_stale(job):
                        logger.debug(
                            "Skipping stale TTS job seq=%s epoch=%s (current=%s)",
                            job.seq,
                            job.tts_epoch,
                            self._tts_epoch,
                        )
                        continue
                    if job.kind == "live" and self._muted:
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
                    self._synth_task = asyncio.ensure_future(self._synthesise(job))
                    try:
                        await self._synth_task
                    except asyncio.CancelledError:
                        pass
                    finally:
                        self._synth_task = None
                        self._active_synth_kind = None
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _synthesise(self, job: TTSJob) -> None:
        try:
            self._session_manager._emit(
                "tts_speaking",
                {
                    "seq": job.seq,
                    "kind": job.kind,
                    "tts_epoch": job.tts_epoch,
                },
            )
            stream = await self._client.audio.speech.complete_async(
                model=self._config.tts_model,
                input=job.text,
                voice_id=VOICE_MAP[job.language],
                response_format="pcm",
                stream=True,
            )
            chunk_index = 0
            async with stream as events:
                async for event in events:
                    audio_data = getattr(event, "audio_data", None)
                    if audio_data is None:
                        continue
                    self._session_manager._emit(
                        "tts_audio",
                        {
                            "seq": job.seq,
                            "kind": job.kind,
                            "chunk_index": chunk_index,
                            "is_last": False,
                            "data": audio_data,
                            "tts_epoch": job.tts_epoch,
                        },
                    )
                    chunk_index += 1
            self._session_manager._emit(
                "tts_audio",
                {
                    "seq": job.seq,
                    "kind": job.kind,
                    "chunk_index": chunk_index,
                    "is_last": True,
                    "data": "",
                    "tts_epoch": job.tts_epoch,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("TTS synthesis failed for seq=%s", job.seq)
            self._session_manager._emit(
                "tts_error",
                {
                    "seq": job.seq,
                    "kind": job.kind,
                    "tts_epoch": job.tts_epoch,
                },
            )

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
