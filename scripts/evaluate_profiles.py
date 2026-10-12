"""Bounded profile comparison with public synthetic ASR events and optional live translation.

Offline mode makes no provider calls. Live mode stores only content-free metrics in
an exclusive ledger and reserves every request before sending it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.boundary import BoundaryDetector
from app.config import AppConfig
from app.profiles import resolve_profile
from app.state import SessionManager
from app.translate import TranslationDispatcher
from app.translation_quality import check
from scripts.evaluate_glossary import (
    ALLOWED_MODELS,
    INPUT_USD_PER_MILLION,
    MAX_INPUT_BYTES,
    MAX_OUTPUT_TOKENS,
    OUTPUT_USD_PER_MILLION,
    PRICING_SOURCE,
    ROLE_TOKEN_ALLOWANCE,
    EvaluationError,
    request_translation,
    validate_allowance,
    write_ledger,
)

PROFILES = ("current", "shorter", "longer")
PAUSE_S = 1.1
CASES = (
    ("two_clauses", "이 결과는 통계적으로 유의미합니다", " 추가 검증이 필요합니다."),
    ("single_sentence", "이 모형은 정확도를 높입니다", None),
)


async def replay(profile_id: str, case: tuple[str, str, str | None], config: AppConfig) -> dict:
    profile = resolve_profile(profile_id, config)
    finalized: list[tuple[str, int]] = []
    started = time.monotonic()
    detector = BoundaryDetector(
        pause_timeout_s=profile.pause_timeout_ms / 1000,
        fragment_max_hold_s=profile.fragment_max_hold_ms / 1000,
        on_finalize=lambda value: finalized.append(
            (value, round((time.monotonic() - started) * 1000))
        ),
    )
    detector.push(case[1])
    if case[2] is None:
        await asyncio.sleep(profile.pause_timeout_ms / 1000 + 0.08)
    else:
        await asyncio.sleep(PAUSE_S)
        detector.push(case[2])
        await asyncio.sleep(0.08)
    detector.reset()
    expected = 2 if profile_id == "shorter" and case[2] is not None else 1
    if len(finalized) != expected:
        raise EvaluationError("profile_replay_boundary_mismatch")
    return {"profile": profile_id, "case": case[0], "finalized": finalized}


async def build_plan() -> tuple[list[dict], list[dict]]:
    config = AppConfig(_env_file=None, MISTRAL_TTS_ENABLED=False)
    manager = SessionManager(config)
    dispatcher = TranslationDispatcher(manager, config, provider=SimpleNamespace(name="offline"))
    replays = await asyncio.gather(
        *(replay(profile, case, config) for profile in PROFILES for case in CASES)
    )
    plan: list[dict] = []
    for run in replays:
        for source, finalized_ms in run["finalized"]:
            segment = SimpleNamespace(source_text=source, segment_kind="complete")
            messages = dispatcher._build_messages(segment, [], "en", None)
            content_bytes = sum(len(m["content"].encode("utf-8")) for m in messages)
            if content_bytes > MAX_INPUT_BYTES:
                raise EvaluationError("public_fixture_input_budget_exceeded")
            input_bound = content_bytes + ROLE_TOKEN_ALLOWANCE
            upper = (
                Decimal(input_bound) * INPUT_USD_PER_MILLION
                + Decimal(MAX_OUTPUT_TOKENS) * OUTPUT_USD_PER_MILLION
            ) / Decimal(1_000_000)
            plan.append(
                {
                    "profile": run["profile"],
                    "case": run["case"],
                    "source": source,
                    "messages": messages,
                    "finalized_ms": finalized_ms,
                    "input_token_bound": input_bound,
                    "max_tokens": MAX_OUTPUT_TOKENS,
                    "temperature": 0.2,
                    "reserved_usd": str(upper),
                }
            )
    if len(plan) != 7:
        raise EvaluationError("profile_replay_request_count_mismatch")
    return plan, replays


def run_live(
    plan: list[dict], key: str, model: str, ledger: Path, added: Decimal, prior: Decimal
) -> dict:
    if model not in ALLOWED_MODELS or not key:
        raise EvaluationError("approved_mistral_model_and_connection_required")
    total = validate_allowance(plan, added, prior)
    public_digest = hashlib.sha256(
        json.dumps(
            [(x["profile"], x["case"], x["source"]) for x in plan],
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    state = {
        "schema_version": 1,
        "phase": "prepared",
        "model": model,
        "public_fixture_sha256": public_digest,
        "pricing_source": PRICING_SOURCE,
        "prior_usage_equivalent_upper_usd": str(prior),
        "planned_added_usage_equivalent_upper_usd": str(total),
        "reserved_added_usage_equivalent_usd": "0",
        "requests_reserved": 0,
        "requests_completed": 0,
        "results": [],
        "actual_billing_available": False,
        "provider_request_kind": "public_synthetic_asr_text_translation",
    }
    write_ledger(ledger, state, create=True)
    reserved = Decimal(0)
    with httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False) as client:
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
                output, usage = request_translation(client, key, model, item)
            except EvaluationError as exc:
                state.update(phase="stopped", error_code=str(exc))
                write_ledger(ledger, state)
                return state
            quality = check(output, item["source"], "en")
            result = {
                "profile": item["profile"],
                "case": item["case"],
                "boundary_ms": item["finalized_ms"],
                "translation_latency_ms": round((time.monotonic() - started) * 1000),
                "output_chars": len(output),
                "quality_reasons": list(quality.reasons),
                "passed": not quality.flagged and bool(output),
                **usage,
            }
            state["results"].append(result)
            state["requests_completed"] += 1
            state["phase"] = "response_checked"
            write_ledger(ledger, state)
    state.update(
        phase="complete",
        passed=all(r["passed"] for r in state["results"]),
    )
    write_ledger(ledger, state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--key-stdin", action="store_true")
    parser.add_argument("--model", choices=sorted(ALLOWED_MODELS), default="mistral-small-latest")
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--prior-cost-upper-usd")
    parser.add_argument("--max-spend-usd", default="0.01")
    args = parser.parse_args()
    try:
        plan, replays = asyncio.run(build_plan())
        total = sum((Decimal(x["reserved_usd"]) for x in plan), Decimal(0))
        if not args.live:
            print(
                json.dumps(
                    {
                        "mode": "offline",
                        "paid_requests": 0,
                        "public_cases": len(CASES),
                        "profiles": list(PROFILES),
                        "planned_requests": len(plan),
                        "planned_usage_equivalent_upper_usd": str(total),
                        "boundaries": [
                            {
                                "profile": x["profile"],
                                "case": x["case"],
                                "finalization_ms": [t for _, t in x["finalized"]],
                                "translation_request_count": len(x["finalized"]),
                            }
                            for x in replays
                        ],
                    }
                )
            )
            return 0
        if args.ledger is None or args.prior_cost_upper_usd is None:
            raise EvaluationError("ledger_and_prior_bound_required")
        added = Decimal(args.max_spend_usd)
        prior = Decimal(args.prior_cost_upper_usd)
        validate_allowance(plan, added, prior)
        key = (
            sys.stdin.readline(1024).strip()
            if args.key_stdin
            else os.environ.get("MISTRAL_API_KEY", "")
        )
        if not key or len(key) >= 1024:
            raise EvaluationError("gcp_mistral_connection_missing")
        state = run_live(plan, key, args.model, args.ledger, added, prior)
        print(json.dumps(state))
        return 0 if state.get("passed") else 1
    except (EvaluationError, InvalidOperation) as exc:
        code = str(exc) if isinstance(exc, EvaluationError) else "invalid_budget"
        print(json.dumps({"phase": "stopped", "error_code": code, "paid_requests": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
