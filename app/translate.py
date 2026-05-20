"""Translation dispatcher — fires async Mistral chat tasks per segment."""

from __future__ import annotations

import asyncio
import logging
import random

from mistralai.client import Mistral

from app.config import AppConfig
from app.errors import extract_provider_error_info, is_capacity_exceeded

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

    def _handle_translation_timeout(
        self, seq: int, target_language: str, session_id: str
    ) -> None:
        logger.warning(
            "Translation timed out for segment #%d: budget=%dms, lang=%s, model=%s, provider=%s",
            seq,
            self._config.translation_timeout_ms,
            target_language,
            self._config.translate_model,
            "mistral",
        )
        self._session_manager.mark_translation_timed_out(seq, session_id)

    async def _await_translation(self, messages: list[dict], timeout_s: float) -> str:
        return await asyncio.wait_for(self._call_api(messages), timeout=timeout_s)

    async def _generic_one_second_retry(
        self,
        messages: list[dict],
        timeout_s: float,
        seq: int,
        session_id: str,
        target_language: str,
        cause_exc: Exception,
    ) -> str | None:
        """Fixed one-second sleep retry for non-429 errors. Returns text or None if settled."""
        logger.warning(
            "Translation API error for segment #%d: %s", seq, cause_exc
        )
        await asyncio.sleep(1)
        try:
            return await self._await_translation(messages, timeout_s)
        except asyncio.TimeoutError:
            self._handle_translation_timeout(seq, target_language, session_id)
            return None
        except Exception as retry_exc:
            retry_info = extract_provider_error_info(retry_exc)
            if is_capacity_exceeded(retry_info):
                raise
            logger.error(
                "Translation retry failed for segment #%d: %s",
                seq,
                retry_exc,
            )
            self._session_manager.mark_translation_failed(seq, session_id)
            return None

    async def _retry_translation_on_capacity(
        self,
        messages: list[dict],
        timeout_s: float,
        seq: int,
        session_id: str,
        target_language: str,
    ) -> str | None:
        """Exponential backoff retry for 429 capacity errors. Returns text or None if settled."""
        base_ms = self._config.translation_429_base_delay_ms
        max_delay_ms = self._config.translation_429_max_delay_ms
        jitter_factor = self._config.translation_429_jitter_factor
        max_retries = self._config.translation_429_max_retries
        for attempt in range(max_retries):
            raw_delay_ms = min(base_ms * (2**attempt), max_delay_ms)
            delay_ms = raw_delay_ms * random.uniform(
                1 - jitter_factor, 1 + jitter_factor
            )
            delay_s = delay_ms / 1000
            logger.warning(
                "Translation 429 capacity error for segment #%d: "
                "attempt %d/%d, retrying in %.0fms",
                seq,
                attempt + 1,
                max_retries,
                delay_ms,
            )
            await asyncio.sleep(delay_s)
            try:
                return await self._await_translation(messages, timeout_s)
            except asyncio.TimeoutError:
                self._handle_translation_timeout(seq, target_language, session_id)
                return None
            except Exception as retry_exc:
                retry_info = extract_provider_error_info(retry_exc)
                if is_capacity_exceeded(retry_info):
                    continue
                try:
                    translated = await self._generic_one_second_retry(
                        messages,
                        timeout_s,
                        seq,
                        session_id,
                        target_language,
                        retry_exc,
                    )
                except Exception as nested_exc:
                    nested_info = extract_provider_error_info(nested_exc)
                    if is_capacity_exceeded(nested_info):
                        continue
                    raise
                if translated is None:
                    return None
                return translated
        else:
            logger.warning(
                "Translation provider capacity exhausted for "
                "segment #%d after %d retries",
                seq,
                max_retries,
            )
            self._session_manager._emit(
                "provider_capacity_warning",
                {
                    "provider": "mistral",
                    "model": self._config.translate_model,
                    "reason": "service_tier_capacity_exceeded",
                    "status_code": 429,
                    "segment_seq": seq,
                    "recoverable": True,
                },
            )
            self._session_manager.mark_translation_failed(seq, session_id)
            return None

    async def _translate_task(
        self, segment, context_segments: list, session_id: str, target_language: str
    ) -> None:
        seq = segment.seq
        try:
            messages = self._build_messages(segment, context_segments, target_language)
            timeout_s = self._config.translation_timeout_ms / 1000

            try:
                translated = await self._await_translation(messages, timeout_s)
            except asyncio.TimeoutError:
                self._handle_translation_timeout(seq, target_language, session_id)
                return
            except Exception as first_exc:
                info = extract_provider_error_info(first_exc)
                if is_capacity_exceeded(info):
                    translated = await self._retry_translation_on_capacity(
                        messages, timeout_s, seq, session_id, target_language
                    )
                    if translated is None:
                        return
                else:
                    try:
                        translated = await self._generic_one_second_retry(
                            messages,
                            timeout_s,
                            seq,
                            session_id,
                            target_language,
                            first_exc,
                        )
                    except Exception as nested_exc:
                        nested_info = extract_provider_error_info(nested_exc)
                        if is_capacity_exceeded(nested_info):
                            translated = await self._retry_translation_on_capacity(
                                messages, timeout_s, seq, session_id, target_language
                            )
                            if translated is None:
                                return
                        else:
                            raise
                    if translated is None:
                        return

            logger.info(
                "Translated segment #%d: %s", seq, translated[:80] if translated else ""
            )
            self._session_manager.mark_translated(seq, translated, target_language, session_id)

        except asyncio.CancelledError:
            logger.warning(
                "Translation task cancelled for segment #%d (shutdown/drain)", seq
            )
            self._session_manager.mark_translation_failed(seq, session_id)
            raise

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
