"""Meaningful spend/uncertain-call/privacy gates for the public glossary check."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from scripts.evaluate_glossary import (
    EvaluationError,
    build_plan,
    cases,
    evaluate_output,
    main,
    run_live,
    validate_allowance,
)


def test_public_suite_is_offline_and_bounded(capsys) -> None:
    assert main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["paid_requests"] == 0
    assert report["public_cases"] == 8
    assert report["passed"]
    assert Decimal(report["planned_added_upper_usd"]) < Decimal("0.01")
    for case in cases():
        assert case.source not in json.dumps(report)
        assert case.synthetic_output not in json.dumps(report)


@pytest.mark.parametrize("added,prior", [
    ("0.02", "0"), ("0", "0"), ("NaN", "0"), ("0.01", "NaN"),
    ("0.01", "-0.01"), ("0.01", "0.9999"),
])
def test_invalid_or_insufficient_allowance_blocks_paid_calls(added, prior) -> None:
    with pytest.raises(EvaluationError):
        validate_allowance(build_plan(), Decimal(added), Decimal(prior))


def test_live_requires_prior_bound_before_reading_key(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr("sys.stdin", None)
    assert main(["--live", "--key-stdin", "--ledger", str(tmp_path / "ledger.json")]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["error_code"] == "ledger_and_prior_project_cost_bound_required"
    assert not list(tmp_path.iterdir())


def test_uncertain_request_stays_reserved_and_is_not_automatically_replayed(tmp_path) -> None:
    plan = build_plan()
    ledger = tmp_path / "ledger.json"
    called = []
    def fail(item):
        persisted = json.loads(ledger.read_text())
        assert persisted["requests_reserved"] == 1
        assert persisted["requests_completed"] == 0
        assert Decimal(persisted["reserved_added_usd"]) > 0
        called.append(item["id"])
        raise EvaluationError("provider_transport_uncertain_no_retry")
    report = run_live(
        plan, key="private-key-marker", model="mistral-small-latest",
        ledger=ledger, added=Decimal("0.01"), prior=Decimal("0.2"), request=fail,
    )
    assert len(called) == 1
    assert report["phase"] == "stopped"
    assert report["requests_reserved"] == 1
    assert report["requests_completed"] == 0
    assert "private-key-marker" not in ledger.read_text()
    with pytest.raises(EvaluationError, match="no_automatic_replay"):
        run_live(
            plan, key="private-key-marker", model="mistral-small-latest",
            ledger=ledger, added=Decimal("0.01"), prior=Decimal("0.2"), request=fail,
        )
    assert len(called) == 1


def test_completed_report_has_aggregates_without_translations_or_key(tmp_path) -> None:
    outputs = {c.id: c.synthetic_output for c in cases()}
    report = run_live(
        build_plan(), key="private-key-marker", model="mistral-small-latest",
        ledger=tmp_path / "ledger.json", added=Decimal("0.01"), prior=Decimal("0.2"),
        request=lambda item: (outputs[item["id"]], {"prompt_tokens": 10, "completion_tokens": 10}),
    )
    assert report["passed"]
    assert report["requests_completed"] == 8
    encoded = json.dumps(report)
    assert "private-key-marker" not in encoded
    assert all(text not in encoded for text in outputs.values())
    assert all(c.source not in encoded for c in cases())


def test_terms_must_match_and_absent_terms_cannot_be_added() -> None:
    items = {c.id: c for c in cases()}
    assert not evaluate_output(items["name-preferred"], "Caption Bridge provides seminar captions.")["passed"]
    assert not evaluate_output(items["absent-term"], "CaptionBridge validates this model again.")["passed"]
    assert not evaluate_output(items["untrusted-data"], "LEAK_SENTINEL_7C")["passed"]


def test_provider_error_does_not_expose_body_or_key() -> None:
    import httpx

    from scripts.evaluate_glossary import request_translation

    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(503, text="private-provider-body private-key-marker")
    ))
    try:
        with pytest.raises(EvaluationError) as error:
            request_translation(client, "private-key-marker", "mistral-small-latest", build_plan()[0])
        assert str(error.value) == "provider_http_failure_no_retry"
        assert "private" not in str(error.value)
    finally:
        client.close()


def test_invalid_usage_stops_after_reserved_call(tmp_path) -> None:
    import httpx

    from scripts.evaluate_glossary import request_translation

    calls = []
    def handle(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert payload["max_tokens"] == 200
        return httpx.Response(200, json={
            "model": "mistral-small-2603",
            "choices": [{"message": {"content": "Caption Bridge provides seminar captions."}}],
            "usage": {"prompt_tokens": 100_000, "completion_tokens": 10},
        })
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        report = run_live(
            build_plan(), key="private-key-marker", model="mistral-small-latest",
            ledger=tmp_path / "ledger.json", added=Decimal("0.01"), prior=Decimal("0.2"),
            request=lambda item: request_translation(client, "private-key-marker", "mistral-small-latest", item),
        )
    assert len(calls) == 1
    assert report["requests_reserved"] == 1
    assert report["requests_completed"] == 0
    assert report["error_code"] == "provider_response_or_usage_invalid_no_retry"
