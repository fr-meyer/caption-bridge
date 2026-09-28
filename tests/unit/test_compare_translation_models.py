"""Budget and durable-reservation contracts for the public model comparison."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from scripts.compare_translation_models import (
    MODELS,
    EvaluationError,
    build_plan,
    run_live,
    validate_budget,
)

PRIOR = Decimal("0.9779064")


def test_three_model_plan_fits_remaining_project_ceiling() -> None:
    plan = build_plan()
    assert tuple(item["model"] for item in plan) == MODELS
    total = validate_budget(plan, PRIOR, Decimal("0.02"))
    assert total <= Decimal("0.02")
    assert PRIOR + total <= Decimal("1")
    with pytest.raises(EvaluationError, match="insufficient_project_allowance"):
        validate_budget(plan, Decimal("0.99"), Decimal("0.02"))


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

    state = run_live(plan, "test-key", ledger, PRIOR, Decimal("0.02"), request)
    saved = json.loads(ledger.read_text())
    assert state["phase"] == saved["phase"] == "stopped"
    assert state["requests_reserved"] == 2
    assert state["requests_completed"] == 1
    assert calls == list(MODELS[:2])
    assert ledger.stat().st_mode & 0o077 == 0
    with pytest.raises(EvaluationError, match="ledger_exists_no_automatic_replay"):
        run_live(plan, "test-key", ledger, PRIOR, Decimal("0.02"), request)
    assert calls == list(MODELS[:2])
