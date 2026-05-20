"""Translation dispatcher — fires async Mistral chat tasks per segment."""

from __future__ import annotations

import asyncio
import logging

from mistralai.client import Mistral

from app.config import AppConfig

logger = logging.getLogger(__name__)

from app.languages import get_language_label

_RECONNECT_ADDENDUM = (
    "\n\nNote: The following text may be incomplete or cut off "
    "mid-sentence due to a connection interruption."
)


def _build_system_prompt(target_language: str) -> str:
    label = get_language_label(target_language)
    return (
        f"Translate spoken academic seminar text into concise, natural "
        f"{label} captions. Preserve names, code identifiers, equations, "
        f"technical terms, and acronyms. Do not explain or summarize beyond "
        f"the spoken content. If the source text is fragmentary, produce the "
        f"best readable caption possible."
    )


class TranslationDispatcher:
    """Fires one asyncio task per segment to translate via Mistral chat."""

    def __init__(self, session_manager, config: AppConfig) -> None:
        from app.state import SessionManager

        self._session_manager: SessionManager = session_manager
        self._config = config
        self._client = Mistral(api_key=config.mistral_api_key)
        self._in_flight: set[asyncio.Task] = set()

    # -- public API ---------------------------------------------------------

    def dispatch(self, segment, context_segments: list, session_id: str, target_language: str) -> None:
        task = asyncio.ensure_future(
            self._translate_task(segment, context_segments, session_id, target_language)
        )
        self._in_flight.add(task)
        task.add_done_callback(self._in_flight.discard)

    async def drain(self) -> None:
        """Wait for in-flight tasks to settle, then cancel any remaining."""
        if not self._in_flight:
            return
        tasks = list(self._in_flight)
        timeout_s = self._config.translation_timeout_ms / 1000
        _done, pending = await asyncio.wait(tasks, timeout=timeout_s)
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.wait(pending, timeout=2.0)
        self._in_flight.clear()

    # -- internals ----------------------------------------------------------

    async def _translate_task(
        self, segment, context_segments: list, session_id: str, target_language: str
    ) -> None:
        seq = segment.seq
        try:
            messages = self._build_messages(segment, context_segments, target_language)
            timeout_s = self._config.translation_timeout_ms / 1000

            try:
                translated = await asyncio.wait_for(
                    self._call_api(messages), timeout=timeout_s
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Translation timed out for segment #%d: budget=%dms, lang=%s, model=%s, provider=%s",
                    seq,
                    self._config.translation_timeout_ms,
                    target_language,
                    self._config.translate_model,
                    "mistral",
                )
                self._session_manager.mark_translation_timed_out(seq, session_id)
                return
            except Exception as first_exc:
                logger.warning(
                    "Translation API error for segment #%d: %s", seq, first_exc
                )
                await asyncio.sleep(1)
                try:
                    translated = await asyncio.wait_for(
                        self._call_api(messages), timeout=timeout_s
                    )
                except Exception as retry_exc:
                    logger.error(
                        "Translation retry failed for segment #%d: %s",
                        seq,
                        retry_exc,
                    )
                    self._session_manager.mark_translation_failed(seq, session_id)
                    return

            logger.info(
                "Translated segment #%d: %s", seq, translated[:80] if translated else ""
            )
            self._session_manager.mark_translated(seq, translated, target_language, session_id)

        except Exception:
            logger.exception(
                "Unhandled error in translation task for segment #%d", seq
            )
            self._session_manager.mark_translation_failed(seq, session_id)

    async def _call_api(self, messages: list[dict]) -> str:
        response = await self._client.chat.complete_async(
            model=self._config.translate_model,
            messages=messages,
            temperature=0.2,
            max_tokens=200,
        )
        return response.choices[0].message.content.strip()

    def _build_messages(self, segment, context_segments: list, target_language: str) -> list[dict]:
        system_content = _build_system_prompt(target_language)
        if segment.segment_kind == "reconnect_fragment":
            system_content += _RECONNECT_ADDENDUM

        label = get_language_label(target_language)
        if context_segments:
            context_lines = "\n".join(
                f"{i}. {seg.source_text}"
                for i, seg in enumerate(context_segments, 1)
            )
            user_content = (
                f"Context (previous segments):\n{context_lines}\n\n"
                f"Translate the following segment into {label}:\n"
                f"{segment.source_text}"
            )
        else:
            user_content = (
                f"Translate the following segment into {label}:\n"
                f"{segment.source_text}"
            )

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
