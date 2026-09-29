"""Budget and durable-reservation contracts for the public model comparison."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from scripts.compare_translation_models import (
    MODELS,
    EvaluationError,
    build_plan,
    request_translation,
    run_live,
    validate_budget,
)

PRIOR = Decimal("0.9779064")


def test_three_model_plan_fits_remaining_project_ceiling() -> None:
    plan = build_plan()
    assert tuple(item["model"] for item in plan) == MODELS
    assert [item["max_tokens"] for item in plan] == [200, 200, 1024]
    total = validate_budget(plan, PRIOR, Decimal("0.03"), Decimal("1.25"))
    assert total <= Decimal("0.03")
    assert PRIOR + total <= Decimal("1.25")
    with pytest.raises(EvaluationError, match="insufficient_project_allowance"):
        validate_budget(plan, Decimal("0.995"), Decimal("0.03"))


def test_reservations_are_durable_and_never_replayed(tmp_path) -> None:
    plan = build_plan()
    ledger = tmp_path / "ledger.json"
    calls = []

    def request(item):
        calls.append(item["model"])
        if len(calls) == 2:
            raise EvaluationError("provider_transport_uncertain_no_retry")
        return "These results are statistically significant, but require further validation.", {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "resolved_model": item["model"],
        }

    state = run_live(
        plan, "test-key", ledger, PRIOR, Decimal("0.03"), request,
        ceiling=Decimal("1.25"),
    )
    saved = json.loads(ledger.read_text())
    assert state["phase"] == saved["phase"] == "stopped"
    assert state["project_ceiling_usd"] == "1.25"
    assert state["requests_reserved"] == 2
    assert state["requests_completed"] == 1
    assert calls == list(MODELS[:2])
    assert ledger.stat().st_mode & 0o077 == 0
    with pytest.raises(EvaluationError, match="ledger_exists_no_automatic_replay"):
        run_live(
            plan, "test-key", ledger, PRIOR, Decimal("0.03"), request,
            ceiling=Decimal("1.25"),
        )
    assert calls == list(MODELS[:2])


def test_chunked_public_response_uses_text_and_rejects_thinking_only() -> None:
    class Client:
        def __init__(self, content, completion_tokens=20) -> None:
            self.content = content
            self.completion_tokens = completion_tokens

        def post(self, *args, **kwargs):
            class Response:
                status_code = 200

                def __init__(self, content, completion_tokens) -> None:
                    self.content = content
                    self.completion_tokens = completion_tokens

                def json(self):
                    return {
                        "model": "zai-glm-5-3",
                        "choices": [{"message": {"content": self.content}}],
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": self.completion_tokens,
                        },
                    }

            return Response(self.content, self.completion_tokens)

    item = build_plan()[2]
    answer, usage = request_translation(
        Client([
            {"type": "thinking", "thinking": "not a caption"},
            {"type": "text", "text": "Further validation is needed."},
        ]), "test-key", item
    )
    assert answer == "Further validation is needed."
    assert usage["resolved_model"] == "zai-glm-5-3"
    _, larger_usage = request_translation(
        Client([{"type": "text", "text": "Further validation is needed."}], 372),
        "test-key", item,
    )
    assert larger_usage["completion_tokens"] == 372
    with pytest.raises(EvaluationError, match="provider_usage_invalid_no_retry"):
        request_translation(
            Client([{"type": "text", "text": "Too long."}], 1025),
            "test-key", item,
        )
    with pytest.raises(EvaluationError, match="provider_no_answer_text_no_retry"):
        request_translation(
            Client([{"type": "thinking", "thinking": "still reasoning"}]),
            "test-key", item,
        )
