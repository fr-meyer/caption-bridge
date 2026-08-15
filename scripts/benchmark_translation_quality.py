#!/usr/bin/env python3
"""Benchmark deterministic translation checks without printing caption text."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.translation_quality import check

DEFAULT_FIXTURES = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "translation_quality_cases.json"
)


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported fixture schema")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("fixtures must contain a non-empty cases list")

    seen_ids: set[str] = set()
    required = {
        "id",
        "target_language",
        "source_text",
        "translated_text",
        "expected_reasons",
    }
    for case in cases:
        if not isinstance(case, dict) or not required.issubset(case):
            raise ValueError("fixture case has an invalid shape")
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id or case_id in seen_ids:
            raise ValueError("fixture case identifiers must be unique non-empty strings")
        seen_ids.add(case_id)
        if not isinstance(case["expected_reasons"], list):
            raise ValueError(f"fixture {case_id} expected_reasons must be a list")
    return cases


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    confusion = Counter(
        {
            "true_positive": 0,
            "false_positive": 0,
            "true_negative": 0,
            "false_negative": 0,
        }
    )
    expected_reason_counts: Counter[str] = Counter()
    actual_reason_counts: Counter[str] = Counter()
    mismatched_case_ids: list[str] = []
    reason_mismatch_case_ids: list[str] = []

    for case in cases:
        expected_reasons = set(case["expected_reasons"])
        expected_flagged = bool(expected_reasons)
        result = check(
            case["translated_text"],
            case["source_text"],
            case["target_language"],
        )
        actual_reasons = set(result.reasons)
        expected_reason_counts.update(expected_reasons)
        actual_reason_counts.update(actual_reasons)

        if expected_flagged and result.flagged:
            confusion["true_positive"] += 1
        elif expected_flagged:
            confusion["false_negative"] += 1
            mismatched_case_ids.append(case["id"])
        elif result.flagged:
            confusion["false_positive"] += 1
            mismatched_case_ids.append(case["id"])
        else:
            confusion["true_negative"] += 1

        if actual_reasons != expected_reasons:
            reason_mismatch_case_ids.append(case["id"])

    positives = confusion["true_positive"] + confusion["false_negative"]
    negatives = confusion["true_negative"] + confusion["false_positive"]
    predicted_positive = confusion["true_positive"] + confusion["false_positive"]
    total = len(cases)

    return {
        "total_cases": total,
        **dict(confusion),
        "flag_rate": predicted_positive / total,
        "false_positive_rate": (
            confusion["false_positive"] / negatives if negatives else 0.0
        ),
        "recall": confusion["true_positive"] / positives if positives else 1.0,
        "precision": (
            confusion["true_positive"] / predicted_positive
            if predicted_positive
            else 1.0
        ),
        "expected_reason_counts": dict(sorted(expected_reason_counts.items())),
        "actual_reason_counts": dict(sorted(actual_reason_counts.items())),
        "mismatched_case_ids": sorted(mismatched_case_ids),
        "reason_mismatch_case_ids": sorted(reason_mismatch_case_ids),
    }


def print_report(report: dict[str, Any]) -> None:
    print("Translation quality benchmark (content-free)")
    for key in (
        "total_cases",
        "true_positive",
        "false_positive",
        "true_negative",
        "false_negative",
    ):
        print(f"{key}: {report[key]}")
    for key in ("flag_rate", "false_positive_rate", "recall", "precision"):
        print(f"{key}: {report[key]:.3f}")
    print(
        "actual_reason_counts: "
        + json.dumps(report["actual_reason_counts"], sort_keys=True)
    )
    print(
        "classification_mismatches: "
        + (
            ", ".join(report["mismatched_case_ids"])
            if report["mismatched_case_ids"]
            else "none"
        )
    )
    print(
        "reason_mismatches: "
        + (
            ", ".join(report["reason_mismatch_case_ids"])
            if report["reason_mismatch_case_ids"]
            else "none"
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--max-false-positive-rate", type=float)
    parser.add_argument("--min-recall", type=float)
    parser.add_argument("--require-exact-reasons", action="store_true")
    args = parser.parse_args()

    report = evaluate_cases(load_cases(args.fixtures))
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_report(report)

    failed = False
    if (
        args.max_false_positive_rate is not None
        and report["false_positive_rate"] > args.max_false_positive_rate
    ):
        failed = True
    if args.min_recall is not None and report["recall"] < args.min_recall:
        failed = True
    if args.require_exact_reasons and report["reason_mismatch_case_ids"]:
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
