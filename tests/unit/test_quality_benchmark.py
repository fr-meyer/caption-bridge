"""Tests for the content-free synthetic translation-quality benchmark."""

from __future__ import annotations

from scripts.benchmark_translation_quality import (
    DEFAULT_FIXTURES,
    evaluate_cases,
    load_cases,
    print_report,
)


def test_synthetic_quality_benchmark_is_exact() -> None:
    report = evaluate_cases(load_cases(DEFAULT_FIXTURES))

    assert report["total_cases"] == 26
    assert report["false_positive"] == 0
    assert report["false_negative"] == 0
    assert report["false_positive_rate"] == 0.0
    assert report["recall"] == 1.0
    assert report["mismatched_case_ids"] == []
    assert report["reason_mismatch_case_ids"] == []


def test_quality_benchmark_report_excludes_fixture_text(capsys) -> None:
    cases = load_cases(DEFAULT_FIXTURES)
    print_report(evaluate_cases(cases))
    output = capsys.readouterr().out

    for case in cases:
        for field in ("source_text", "translated_text"):
            text = case[field]
            if len(text) >= 5:
                assert text not in output
