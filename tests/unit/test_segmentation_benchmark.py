"""Tests for the deterministic semantic segmentation benchmark."""

from __future__ import annotations

import asyncio
import json

from scripts.benchmark_segmentation import run_benchmark


def test_segmentation_benchmark_matches_exact_policy() -> None:
    report = asyncio.run(run_benchmark())

    assert report.passed is True
    assert report.cases == 10
    assert report.expected_deferred == 4
    assert report.expected_first_pause_finalized == 6
    assert report.immediate_partial_cases == 10
    assert report.correctly_deferred == 4
    assert report.correctly_first_pause_finalized == 6
    assert report.correctly_merged == 3
    assert report.forced_releases == 1
    assert report.unexpected_standalone_fragments == 0
    assert report.delayed_clear_boundaries == 0
    assert report.finalization_mismatches == ()
    assert report.policy_max_translation_boundary_delay_ms == 4500


def test_segmentation_benchmark_report_is_content_free() -> None:
    output = json.dumps(
        asyncio.run(run_benchmark()).to_dict(),
        ensure_ascii=False,
        sort_keys=True,
    )

    assert "유의미" not in output
    assert "인공지능" not in output
    assert "statistically significant" not in output
    assert "source_text" not in output
    assert "translated_text" not in output
    assert "MISTRAL_API_KEY" not in output


def test_segmentation_benchmark_enforces_latency_ceiling() -> None:
    report = asyncio.run(run_benchmark(max_policy_delay_ms=4499))

    assert report.policy_max_translation_boundary_delay_ms == 4500
    assert report.passed is False
