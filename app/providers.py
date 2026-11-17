"""Translation provider interface and production Mistral adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mistralai.client import Mistral


@dataclass(frozen=True)
class TranslationResponse:
    text: str
    resolved_model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None


def extract_translation_text(content: object) -> str:
    """Use answer text, excluding provider thinking and non-text chunks."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for chunk in content:
            kind = chunk.get("type") if isinstance(chunk, dict) else getattr(chunk, "type", None)
            if kind != "text":
                continue
            value = chunk.get("text") if isinstance(chunk, dict) else getattr(chunk, "text", None)
            if isinstance(value, str):
                parts.append(value)
        return "".join(parts).strip()
    return ""


class TranslationProvider(Protocol):
    """Narrow seam used by the dispatcher and deterministic resilience tests."""

    name: str

    async def translate(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        reasoning_effort: str | None = None,
    ) -> str | TranslationResponse:
        """Return translated text and optional response metadata, or raise."""


class MistralTranslationProvider:
    name = "mistral"

    def __init__(self, api_key: str) -> None:
        self._client = Mistral(api_key=api_key)
        self._metadata_key = api_key

    async def list_models(self) -> list[dict]:
        """Metadata only. Invoked explicitly, never an inference probe."""
        import httpx
        import orjson

        if not self._metadata_key:
            raise ValueError("Account metadata credential unavailable")
        async with httpx.AsyncClient(timeout=4, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", "https://api.mistral.ai/v1/models",
                                     headers={"Authorization": "Bearer " + self._metadata_key}) as response:
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000:
                        raise ValueError("Account metadata exceeds byte ceiling")
        payload = orjson.loads(content)
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or len(rows) > 2000:
            raise ValueError("Invalid account metadata")
        return rows

    async def translate(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        reasoning_effort: str | None = None,
    ) -> TranslationResponse:
        request = dict(
            model=model, messages=messages, temperature=temperature,
            max_tokens=max_tokens,
        )
        if reasoning_effort is not None:
            request["reasoning_effort"] = reasoning_effort
        response = await self._client.chat.complete_async(**request)
        usage = getattr(response, "usage", None)
        if not response.choices:
            return TranslationResponse(text="", resolved_model=None)
        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        text = extract_translation_text(choice.message.content)
        content = choice.message.content
        if not text and finish_reason != "length" and isinstance(content, list):
            types = {(chunk.get("type") if isinstance(chunk, dict) else getattr(chunk, "type", None))
                     for chunk in content}
            if "refusal" in types:
                finish_reason = "refusal"
            elif "thinking" in types:
                finish_reason = "reasoning_only"
        return TranslationResponse(
            text=text,
            resolved_model=getattr(response, "model", None),
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        )
