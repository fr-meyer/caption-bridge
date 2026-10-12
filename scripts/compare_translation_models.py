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
from app.providers import extract_translation_text
from app.state import SessionManager
from app.translate import TranslationDispatcher
from app.translation_models import translation_output_limit
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
MAX_ADDED_USD = Decimal("0.05")
DEFAULT_PROJECT_CEILING_USD = Decimal("1")


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
        output_limit = translation_output_limit(model, "default")
        reserve = (
            Decimal(input_bound) * in_rate
            + Decimal(output_limit) * out_rate
        ) / Decimal(1_000_000)
        plan.append({
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": output_limit,
            "input_token_bound": input_bound,
            "reserved_usd": str(reserve),
        })
    return plan


def validate_budget(
    plan: list[dict], prior: Decimal, added: Decimal,
    ceiling: Decimal = DEFAULT_PROJECT_CEILING_USD,
) -> Decimal:
    if not prior.is_finite() or not added.is_finite() or not ceiling.is_finite():
        raise EvaluationError("finite_budget_required")
    if prior < 0 or ceiling <= 0 or not 0 < added <= MAX_ADDED_USD:
        raise EvaluationError("invalid_budget")
    if len(plan) != len(MODELS) or tuple(x["model"] for x in plan) != MODELS:
        raise EvaluationError("request_plan_changed")
    if any(
        item["max_tokens"] != translation_output_limit(item["model"], "default")
        for item in plan
    ):
        raise EvaluationError("request_plan_changed")
    total = sum((Decimal(x["reserved_usd"]) for x in plan), Decimal(0))
    if total > added or prior + total > ceiling:
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
        content = data["choices"][0]["message"]["content"]
    except Exception:
        raise EvaluationError("provider_response_invalid_no_retry") from None
    output = extract_translation_text(content)
    if not output:
        raise EvaluationError("provider_no_answer_text_no_retry")
    try:
        usage = data["usage"]
        prompt = usage["prompt_tokens"]
        completion = usage["completion_tokens"]
        resolved = data.get("model")
        if (
            type(prompt) is not int
            or type(completion) is not int
            or not 0 <= prompt <= item["input_token_bound"]
            or not 0 <= completion <= item["max_tokens"]
            or not isinstance(resolved, str)
        ):
            raise ValueError
    except Exception:
        raise EvaluationError("provider_usage_invalid_no_retry") from None
    return output.strip(), {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "resolved_model": resolved,
    }


def run_live(
    plan: list[dict], key: str, ledger: Path, prior: Decimal, added: Decimal,
    request: Callable[[dict], tuple[str, dict]],
    ceiling: Decimal = DEFAULT_PROJECT_CEILING_USD,
) -> dict:
    if not key or len(key) >= 1024:
        raise EvaluationError("gcp_mistral_connection_missing")
    total = validate_budget(plan, prior, added, ceiling)
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
        "project_ceiling_usd": str(ceiling),
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
    parser.add_argument("--max-spend-usd", default="0.04")
    parser.add_argument("--project-ceiling-usd", default="1")
    args = parser.parse_args()
    try:
        plan = build_plan()
        if not args.live:
            print(json.dumps({
                "mode": "offline",
                "paid_requests": 0,
                "models": list(MODELS),
                "output_limits": {
                    item["model"]: item["max_tokens"] for item in plan
                },
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
        ceiling = Decimal(args.project_ceiling_usd)
        validate_budget(plan, prior, added, ceiling)
        key = (
            sys.stdin.readline(1024).strip()
            if args.key_stdin else os.environ.get("MISTRAL_API_KEY", "")
        )
        with httpx.Client(timeout=20.0, follow_redirects=False, trust_env=False) as client:
            state = run_live(
                plan, key, args.ledger, prior, added,
                request=lambda item: request_translation(client, key, item),
                ceiling=ceiling,
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
