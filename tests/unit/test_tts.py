from __future__ import annotations

import asyncio
from types import SimpleNamespace

import app.tts as tts_module
from app.tts import TTSDispatcher, TTSJob


class _ProviderError(Exception):
    def __init__(
        self,
        status_code: int,
        *,
        error_type: str | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__("sensitive provider detail")
        self.status_code = status_code
        fields = [f'"raw_status_code": {status_code}']
        if error_type is not None:
            fields.append(f'"type": "{error_type}"')
        if code is not None:
            fields.append(f'"code": "{code}"')
        self.body = "{" + ", ".join(fields) + "}"


class _Stream:
    def __init__(self, items: list[object]) -> None:
        self.items = list(items)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.items:
            raise StopAsyncIteration
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _Speech:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    async def complete_async(self, **_kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _SessionManager:
    def __init__(self) -> None:
        self.session = SimpleNamespace(id="session-1", status="listening")
        self.events: list[dict] = []

    def _emit(self, event_type: str, data: dict | None = None) -> None:
        self.events.append({"type": event_type, **(data or {})})


def _config(**overrides):
    values = {
        "tts_queue_max": 50,
        "tts_voice_id": "voice-1",
        "tts_model": "tts-model",
        "tts_transient_max_retries": 2,
        "tts_retry_base_delay_ms": 0,
        "tts_retry_max_delay_ms": 1,
        "tts_retry_jitter_factor": 0.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _job() -> TTSJob:
    return TTSJob(
        seq=7,
        text="translated caption",
        language="en",
        kind="live",
        priority=0,
        session_id="session-1",
        tts_epoch=0,
    )


def _dispatcher(outcomes: list[object]):
    speech = _Speech(outcomes)
    client = SimpleNamespace(audio=SimpleNamespace(speech=speech))
    manager = _SessionManager()
    dispatcher = TTSDispatcher(client, manager, _config())
    return dispatcher, manager, speech


def test_transient_failure_retries_then_recovers(monkeypatch) -> None:
    monkeypatch.setattr(tts_module.random, "uniform", lambda *_args: 0.0)
    dispatcher, manager, speech = _dispatcher(
        [
            _ProviderError(503),
            _Stream([SimpleNamespace(audio_data="audio")]),
        ]
    )

    asyncio.run(dispatcher._synthesise(_job()))

    assert speech.calls == 2
    assert [event["type"] for event in manager.events].count("tts_retrying") == 1
    assert [event["type"] for event in manager.events].count("tts_recovered") == 1
    assert manager.events[-1]["type"] == "tts_recovered"
    assert "sensitive provider detail" not in str(manager.events)


def test_guardrail_is_not_retried() -> None:
    dispatcher, manager, speech = _dispatcher(
        [
            _ProviderError(
                403,
                error_type="guardrail_violation",
                code="1920",
            )
        ]
    )

    asyncio.run(dispatcher._synthesise(_job()))

    assert speech.calls == 1
    skipped = [event for event in manager.events if event["type"] == "tts_skipped"]
    assert skipped[-1]["reason"] == "guardrail_violation"
    assert not any(event["type"] == "tts_retrying" for event in manager.events)


def test_partial_audio_failure_is_not_retried() -> None:
    dispatcher, manager, speech = _dispatcher(
        [
            _Stream(
                [
                    SimpleNamespace(audio_data="audio"),
                    _ProviderError(503),
                ]
            )
        ]
    )

    asyncio.run(dispatcher._synthesise(_job()))

    assert speech.calls == 1
    error = [event for event in manager.events if event["type"] == "tts_error"][-1]
    assert error["reason"] == "partial_audio_interrupted"
    assert error["chunks_emitted"] == 1


def test_transient_retry_budget_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(tts_module.random, "uniform", lambda *_args: 0.0)
    dispatcher, manager, speech = _dispatcher(
        [_ProviderError(503), _ProviderError(503), _ProviderError(503)]
    )

    asyncio.run(dispatcher._synthesise(_job()))

    assert speech.calls == 3
    assert [event["type"] for event in manager.events].count("tts_retrying") == 2
    error = [event for event in manager.events if event["type"] == "tts_error"][-1]
    assert error["reason"] == "provider_transient_exhausted"
    assert error["attempts"] == 3
