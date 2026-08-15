"""Translation provider interface and production Mistral adapter."""

from __future__ import annotations

from typing import Protocol

from mistralai.client import Mistral


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
    ) -> str:
        """Return only translated text or raise a provider exception."""


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
    ) -> str:
        response = await self._client.chat.complete_async(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
