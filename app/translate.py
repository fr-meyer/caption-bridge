"""Translation dispatcher — fires async Mistral chat tasks per segment."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from contextvars import ContextVar

from app import translation_quality
from app.config import AppConfig
from app.errors import extract_provider_error_info, is_capacity_exceeded
from app.glossary import Glossary, add_to_messages
from app.languages import get_language_label
from app.providers import MistralTranslationProvider, TranslationProvider, TranslationResponse
from app.state import SegmentQuality
from app.translation_models import translation_output_limit

logger = logging.getLogger(__name__)

_RECONNECT_ADDENDUM = (
    "\n\nNote: The following text may be incomplete or cut off "
    "mid-sentence due to a connection interruption."
)


def _build_system_prompt(target_language: str) -> str:
    label = get_language_label(target_language)
    return (
        f"Translate spoken academic seminar text into concise, natural "
        f"{label} captions. Preserve names, code identifiers, equations, "
        f"technical terms, and acronyms. Output only the translated caption "
        f"text with no wrapper phrases (e.g. \"Caption:\", \"Here's the "
        f"translation:\", \"Translation:\"), no multiple alternatives or "
        f"options, no markdown formatting, bullets, or numbering, and no "
        f"explanations, summaries, or commentary beyond the spoken content. "
        f"Do not translate or echo any context block. If the source text is "
        f"fragmentary, produce the best readable caption possible."
    )


class TranslationDispatcher:
    """Fires one bounded-provider translation task per finalized segment."""

    def __init__(
        self,
        session_manager,
        config: AppConfig,
        provider: TranslationProvider | None = None,
    ) -> None:
        from app.state import SessionManager

        provider_name = getattr(config, "translation_provider", "mistral")
        if isinstance(provider_name, str) and provider_name != "mistral":
            raise ValueError("unsupported translation provider")
        self._session_manager: SessionManager = session_manager
        self._config = config
        self._provider = provider or MistralTranslationProvider(
            api_key=config.mistral_api_key
        )
        max_concurrency = getattr(config, "translation_max_concurrency", 8)
        if not isinstance(max_concurrency, int):
            max_concurrency = 8
        self._provider_slots = asyncio.Semaphore(max_concurrency)
        self._in_flight: set[asyncio.Task] = set()
        # Each task keeps its dispatch-time model through retries and repair.
        self._request_model: ContextVar[str | None] = ContextVar(
            "caption_translation_model", default=None
        )
        self._request_effort: ContextVar[str] = ContextVar(
            "caption_translation_reasoning_effort", default="default"
        )
        self._request_segment: ContextVar[object | None] = ContextVar(
            "caption_translation_segment", default=None
        )

    # -- public API ---------------------------------------------------------

    def dispatch(self, segment, context_segments: list, session_id: str, target_language: str) -> None:
        # Capture before scheduling: reset/language changes cannot leak new terms
        # into work already dispatched for an earlier session.
        session = self._session_manager.session
        glossary = getattr(session, "glossary", None)
        if getattr(session, "id", None) != session_id or not isinstance(glossary, Glossary):
            glossary = None
        model = getattr(segment, "translation_model", None) or self._config.translate_model
        task = asyncio.ensure_future(
            self._translate_task(
                segment, context_segments, session_id, target_language, glossary,
                model, getattr(segment, "translation_reasoning_effort", None) or "default",
            )
        )
        self._in_flight.add(task)
        task.add_done_callback(self._in_flight.discard)

    async def drain(self) -> None:
        """Wait for in-flight tasks to settle, then cancel any remaining."""
        if not self._in_flight:
            return
        tasks = list(self._in_flight)
        timeout_s = self._config.translation_drain_timeout_ms / 1000
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
            self._translation_timeout_ms(),
            target_language,
            self._request_model.get() or self._config.translate_model,
            self._provider.name,
        )
        self._session_manager.mark_translation_timed_out(seq, session_id)

    def _translation_timeout_ms(self) -> int:
        model = self._request_model.get() or self._config.translate_model
        if model == "zai-glm-5-3":
            return self._config.translation_glm_timeout_ms
        return self._config.translation_timeout_ms

    async def _await_translation(self, messages: list[dict], timeout_s: float) -> str:
        async with self._provider_slots:
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
        cause_info = extract_provider_error_info(cause_exc)
        logger.warning(
            "Translation API error: seq=%d error_type=%s status_code=%s",
            seq,
            type(cause_exc).__name__,
            cause_info.status_code if cause_info is not None else None,
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
                "Translation retry failed: seq=%d error_type=%s status_code=%s",
                seq,
                type(retry_exc).__name__,
                retry_info.status_code if retry_info is not None else None,
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
                    "provider": self._provider.name,
                    "model": self._request_model.get() or self._config.translate_model,
                    "reason": "service_tier_capacity_exceeded",
                    "status_code": 429,
                    "segment_seq": seq,
                    "recoverable": True,
                },
            )
            self._session_manager.mark_translation_failed(seq, session_id)
            return None

    async def _translate_task(
        self, segment, context_segments: list, session_id: str, target_language: str,
        glossary: Glossary | None = None,
        model: str | None = None,
        effort: str = "default",
    ) -> None:
        seq = segment.seq
        token = self._request_model.set(model or self._config.translate_model)
        effort_token = self._request_effort.set(effort)
        segment_token = self._request_segment.set(segment)
        try:
            messages = self._build_messages(segment, context_segments, target_language, glossary)
            timeout_s = self._translation_timeout_ms() / 1000

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

            if not translated or not translated.strip():
                logger.warning("Translation provider returned no answer text for segment #%d", seq)
                self._session_manager.mark_translation_failed(
                    seq, session_id, reason="provider_no_text"
                )
                return

            if getattr(segment, "translation_finish_reason", None) == "length":
                logger.warning("Translation output limit reached for segment #%d", seq)
                self._session_manager.mark_translation_failed(
                    seq, session_id, reason="provider_output_limit"
                )
                return

            translated, quality = await self._check_and_repair(
                translated, segment, target_language, glossary
            )
            logger.info(
                "Translated segment: seq=%d chars=%d", seq, len(translated or "")
            )
            self._session_manager.mark_translated(
                seq, translated, target_language, session_id, quality=quality
            )

        except asyncio.CancelledError:
            logger.warning(
                "Translation task cancelled for segment #%d (shutdown/drain)", seq
            )
            self._session_manager.mark_translation_failed(seq, session_id)
            raise

        except Exception as exc:
            logger.error(
                "Unhandled translation failure: seq=%d error_type=%s",
                seq,
                type(exc).__name__,
            )
            self._session_manager.mark_translation_failed(seq, session_id)
        finally:
            self._request_segment.reset(segment_token)
            self._request_effort.reset(effort_token)
            self._request_model.reset(token)

    def _record_response(self, response: str | TranslationResponse) -> str:
        if isinstance(response, str):
            return response
        segment = self._request_segment.get()
        if segment is not None:
            if response.resolved_model:
                segment.translation_model_resolved = response.resolved_model
            if response.prompt_tokens is not None:
                segment.translation_prompt_tokens = (
                    (segment.translation_prompt_tokens or 0) + response.prompt_tokens
                )
            if response.completion_tokens is not None:
                segment.translation_completion_tokens = (
                    (segment.translation_completion_tokens or 0) + response.completion_tokens
                )
            if response.finish_reason is not None:
                segment.translation_finish_reason = response.finish_reason
        return response.text

    async def _request_translation(
        self, messages: list[dict], temperature: float
    ) -> str:
        effort = self._request_effort.get()
        model = self._request_model.get() or self._config.translate_model
        request = dict(
            model=model, messages=messages, temperature=temperature,
            max_tokens=translation_output_limit(model, effort),
        )
        if effort == "high":
            request["reasoning_effort"] = "high"
        response = await self._provider.translate(**request)
        return self._record_response(response)

    async def _call_api(self, messages: list[dict]) -> str:
        return await self._request_translation(messages, 0.2)

    async def _call_repair_api(self, messages: list[dict]) -> str:
        return await self._request_translation(messages, 0.0)

    async def _check_and_repair(
        self, raw_text: str, segment, target_language: str,
        glossary: Glossary | None = None,
    ) -> tuple[str, SegmentQuality]:
        result = translation_quality.check(
            raw_text, segment.source_text, target_language
        )
        if not result.flagged:
            return raw_text, SegmentQuality(
                flagged=False,
                reasons=[],
                retried=False,
                repair_succeeded=None,
                final_flagged=False,
                final_reasons=[],
                repair_attempts=0,
                repair_latency_ms=None,
            )

        initial_reasons = list(result.reasons)
        if self._config.translation_repair_max_attempts == 0:
            return raw_text, SegmentQuality(
                flagged=True,
                reasons=initial_reasons,
                retried=False,
                repair_succeeded=None,
                final_flagged=True,
                final_reasons=initial_reasons,
                repair_attempts=0,
                repair_latency_ms=None,
            )

        label = get_language_label(target_language)
        repair_messages = translation_quality.build_repair_prompt(
            segment.source_text, label, initial_reasons
        )
        repair_messages = add_to_messages(
            repair_messages, glossary, target_language,
            source_text=segment.source_text,
        )
        repair_timeout_s = min(
            self._config.translation_timeout_ms / 2, 5000
        ) / 1000

        repair_started = time.monotonic()
        try:
            async with self._provider_slots:
                repair_text = await asyncio.wait_for(
                    self._call_repair_api(repair_messages),
                    timeout=repair_timeout_s,
                )
                if getattr(segment, "translation_finish_reason", None) == "length":
                    # A fluent partial repair can omit a qualification or negation.
                    # Keep the original flagged answer instead of accepting it.
                    raise ValueError("translation_repair_output_limit")
        except Exception:
            return raw_text, SegmentQuality(
                flagged=True,
                reasons=initial_reasons,
                retried=True,
                repair_succeeded=False,
                final_flagged=True,
                final_reasons=initial_reasons,
                repair_attempts=1,
                repair_latency_ms=max(
                    0, round((time.monotonic() - repair_started) * 1000)
                ),
            )

        repair_result = translation_quality.check(
            repair_text, segment.source_text, target_language
        )
        if not repair_result.flagged:
            return repair_text, SegmentQuality(
                flagged=True,
                reasons=initial_reasons,
                retried=True,
                repair_succeeded=True,
                final_flagged=False,
                final_reasons=[],
                repair_attempts=1,
                repair_latency_ms=max(
                    0, round((time.monotonic() - repair_started) * 1000)
                ),
            )

        best_text = translation_quality.choose_better_translation(
            raw_text, repair_text, segment.source_text, target_language
        )
        final_result = translation_quality.check(
            best_text, segment.source_text, target_language
        )
        return best_text, SegmentQuality(
            flagged=True,
            reasons=initial_reasons,
            retried=True,
            repair_succeeded=False,
            final_flagged=final_result.flagged,
            final_reasons=list(final_result.reasons),
            repair_attempts=1,
            repair_latency_ms=max(
                0, round((time.monotonic() - repair_started) * 1000)
            ),
        )

    def _build_messages(
        self, segment, context_segments: list, target_language: str,
        glossary: Glossary | None = None,
    ) -> list[dict]:
        system_content = _build_system_prompt(target_language)
        if segment.segment_kind == "reconnect_fragment":
            system_content += _RECONNECT_ADDENDUM

        if context_segments:
            context_lines = "\n".join(
                f"{i}. {seg.source_text}"
                for i, seg in enumerate(context_segments, 1)
            )
            user_content = (
                f"<context_do_not_translate>\n"
                f"{context_lines}\n"
                f"</context_do_not_translate>\n\n"
                f"<segment_to_translate>\n"
                f"{segment.source_text}\n"
                f"</segment_to_translate>"
            )
        else:
            user_content = (
                f"<segment_to_translate>\n"
                f"{segment.source_text}\n"
                f"</segment_to_translate>"
            )

        return add_to_messages([
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ], glossary, target_language, source_text=segment.source_text)
