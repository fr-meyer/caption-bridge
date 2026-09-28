"""One-case public Korean-English availability check across translation models.

Offline by default. Live mode durably reserves a conservative cost bound before
each request, has no retries, and keeps public outputs in a private GCP ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import httpx

from app.config import AppConfig
from app.state import SessionManager
from app.translate import TranslationDispatcher
from app.translation_quality import check
from scripts.evaluate_glossary import EvaluationError, write_ledger

SOURCE = "이 결과는 통계적으로 유의미하지만 추가 검증이 필요합니다."
MODELS = (
    "mistral-small-latest",
    "mistral-medium-latest",
    "zai-glm-5-3",
)
# Twice the published standard input/output USD per million token rates
# checked on 2026-09-28; fail closed if prices or request settings change.
RATES = {
    "mistral-small-latest": (Decimal("0.30"), Decimal("1.20")),
    "mistral-medium-latest": (Decimal("3.00"), Decimal("15.00")),
    "zai-glm-5-3": (Decimal("2.80"), Decimal("8.80")),
}
PRICING_SOURCE = "https://docs.mistral.ai/inference/pricing"
ENDPOINT = "https://api.mistral.ai/v1/chat/completions"
MAX_INPUT_BYTES = 2048
ROLE_TOKEN_ALLOWANCE = 1024
MAX_OUTPUT_TOKENS = 200
MAX_ADDED_USD = Decimal("0.02")
PROJECT_CEILING_USD = Decimal("1")


def build_plan() -> list[dict]:
    config = AppConfig(_env_file=None, MISTRAL_TTS_ENABLED=False)
    manager = SessionManager(config)
    dispatcher = TranslationDispatcher(
        manager, config, provider=SimpleNamespace(name="offline")
    )
    segment = SimpleNamespace(source_text=SOURCE, segment_kind="complete")
    messages = dispatcher._build_messages(segment, [], "en", None)
    content_bytes = sum(len(msg["content"].encode("utf-8")) for msg in messages)
    if content_bytes > MAX_INPUT_BYTES:
        raise EvaluationError("public_fixture_input_budget_exceeded")
    input_bound = content_bytes + ROLE_TOKEN_ALLOWANCE
    plan = []
    for model in MODELS:
        in_rate, out_rate = RATES[model]
        reserve = (
            Decimal(input_bound) * in_rate
            + Decimal(MAX_OUTPUT_TOKENS) * out_rate
        ) / Decimal(1_000_000)
        plan.append({
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "input_token_bound": input_bound,
            "reserved_usd": str(reserve),
        })
    return plan


def validate_budget(plan: list[dict], prior: Decimal, added: Decimal) -> Decimal:
    if not prior.is_finite() or not added.is_finite():
        raise EvaluationError("finite_budget_required")
    if prior < 0 or not 0 < added <= MAX_ADDED_USD:
        raise EvaluationError("invalid_budget")
    if len(plan) != len(MODELS) or tuple(x["model"] for x in plan) != MODELS:
        raise EvaluationError("request_plan_changed")
    total = sum((Decimal(x["reserved_usd"]) for x in plan), Decimal(0))
    if total > added or prior + total > PROJECT_CEILING_USD:
        raise EvaluationError("insufficient_project_allowance")
    return total


def request_translation(
    client: httpx.Client, key: str, item: dict
) -> tuple[str, dict]:
    try:
        response = client.post(
            ENDPOINT,
            headers={"Authorization": "Bearer " + key},
            json={
                "model": item["model"],
                "messages": item["messages"],
                "temperature": item["temperature"],
                "max_tokens": item["max_tokens"],
            },
        )
    except Exception:
        raise EvaluationError("provider_transport_uncertain_no_retry") from None
    if response.status_code != 200:
        raise EvaluationError("provider_http_failure_no_retry")
    try:
        data = response.json()
        output = data["choices"][0]["message"]["content"]
        usage = data["usage"]
        prompt = usage["prompt_tokens"]
        completion = usage["completion_tokens"]
        resolved = data.get("model")
        if (
            not isinstance(output, str)
            or type(prompt) is not int
            or type(completion) is not int
            or not 0 <= prompt <= item["input_token_bound"]
            or not 0 <= completion <= MAX_OUTPUT_TOKENS
            or not isinstance(resolved, str)
        ):
            raise ValueError
    except Exception:
        raise EvaluationError("provider_response_or_usage_invalid_no_retry") from None
    return output.strip(), {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "resolved_model": resolved,
    }


def run_live(
    plan: list[dict], key: str, ledger: Path, prior: Decimal, added: Decimal,
    request: Callable[[dict], tuple[str, dict]],
) -> dict:
    if not key or len(key) >= 1024:
        raise EvaluationError("gcp_mistral_connection_missing")
    total = validate_budget(plan, prior, added)
    if ledger.exists():
        raise EvaluationError("ledger_exists_no_automatic_replay")
    digest = hashlib.sha256(
        json.dumps({"source": SOURCE, "plan": plan}, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    state = {
        "schema_version": 1,
        "phase": "prepared",
        "public_fixture_sha256": digest,
        "pricing_source": PRICING_SOURCE,
        "prior_usage_equivalent_upper_usd": str(prior),
        "planned_added_usage_equivalent_upper_usd": str(total),
        "reserved_added_usage_equivalent_usd": "0",
        "requests_reserved": 0,
        "requests_completed": 0,
        "results": [],
        "actual_billing_available": False,
    }
    write_ledger(ledger, state, create=True)
    reserved = Decimal(0)
    for item in plan:
        reserved += Decimal(item["reserved_usd"])
        state.update(
            phase="request_reserved",
            reserved_added_usage_equivalent_usd=str(reserved),
            requests_reserved=state["requests_reserved"] + 1,
        )
        write_ledger(ledger, state)
        started = time.monotonic()
        try:
            output, usage = request(item)
        except EvaluationError as exc:
            state.update(phase="stopped", error_code=str(exc))
            write_ledger(ledger, state)
            return state
        quality = check(output, SOURCE, "en")
        semantic_terms = bool(re.search(r"statistic", output, re.I)) and bool(
            re.search(r"significan", output, re.I)
        ) and bool(re.search(r"validat|verif|confirm|test", output, re.I))
        state["results"].append({
            "model": item["model"],
            "source_text": SOURCE,
            "translated_text": output,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "quality_reasons": list(quality.reasons),
            "semantic_terms_present": semantic_terms,
            "provider_reported": usage,
            "reserved_usd": item["reserved_usd"],
        })
        state["requests_completed"] += 1
        state["phase"] = "response_checked"
        write_ledger(ledger, state)
    state["phase"] = "complete"
    write_ledger(ledger, state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--key-stdin", action="store_true")
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--prior-cost-upper-usd")
    parser.add_argument("--max-spend-usd", default="0.02")
    args = parser.parse_args()
    try:
        plan = build_plan()
        if not args.live:
            print(json.dumps({
                "mode": "offline",
                "paid_requests": 0,
                "models": list(MODELS),
                "planned_requests": len(plan),
                "planned_usage_equivalent_upper_usd": str(sum(
                    (Decimal(item["reserved_usd"]) for item in plan), Decimal(0)
                )),
            }))
            return 0
        if args.ledger is None or args.prior_cost_upper_usd is None:
            raise EvaluationError("ledger_and_prior_bound_required")
        prior = Decimal(args.prior_cost_upper_usd)
        added = Decimal(args.max_spend_usd)
        validate_budget(plan, prior, added)
        key = (
            sys.stdin.readline(1024).strip()
            if args.key_stdin else os.environ.get("MISTRAL_API_KEY", "")
        )
        with httpx.Client(timeout=20.0, follow_redirects=False, trust_env=False) as client:
            state = run_live(
                plan, key, args.ledger, prior, added,
                request=lambda item: request_translation(client, key, item),
            )
        print(json.dumps({
            "phase": state["phase"],
            "requests_reserved": state["requests_reserved"],
            "requests_completed": state["requests_completed"],
            "reserved_added_usage_equivalent_usd": state[
                "reserved_added_usage_equivalent_usd"
            ],
            "ledger": str(args.ledger),
            "error_code": state.get("error_code"),
        }))
        return 0 if state["phase"] == "complete" else 1
    except (EvaluationError, InvalidOperation) as exc:
        code = str(exc) if isinstance(exc, EvaluationError) else "invalid_budget"
        print(json.dumps({"phase": "stopped", "error_code": code, "paid_requests": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
