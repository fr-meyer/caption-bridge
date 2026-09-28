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
    ) -> str | TranslationResponse:
        """Return translated text and optional response metadata, or raise."""


class MistralTranslationProvider:
    name = "mistral"

    def __init__(self, api_key: str) -> None:
        self._client = Mistral(api_key=api_key)

    async def translate(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> TranslationResponse:
        response = await self._client.chat.complete_async(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        usage = getattr(response, "usage", None)
        return TranslationResponse(
            text=extract_translation_text(response.choices[0].message.content),
            resolved_model=getattr(response, "model", None),
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )
