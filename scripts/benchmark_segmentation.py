"""Deterministic, content-free semantic segmentation benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Literal

from app.boundary import BoundaryDetector

ExpectedBoundary = Literal["defer", "finalize"]


@dataclass(frozen=True)
class SegmentationCase:
    case_id: str
    first_delta: str
    expected_first_pause: ExpectedBoundary
    continuation: str | None = None
    force_hold_ceiling: bool = False


_CASES = (
    SegmentationCase(
        "korean_connective",
        "이 결과는 통계적으로 유의미하지만",
        "defer",
        " 추가 검증이 필요합니다.",
    ),
    SegmentationCase(
        "korean_noun_phrase",
        "인공지능의 발전과 조직의 변화",
        "defer",
        "를 분석합니다.",
    ),
    SegmentationCase(
        "short_english_fragment",
        "the model",
        "defer",
        " improves accuracy.",
    ),
    SegmentationCase(
        "bounded_forced_release",
        "추가 설명을 위한 구절",
        "defer",
        force_hold_ceiling=True,
    ),
    SegmentationCase(
        "korean_formal_final",
        "이 결과는 통계적으로 유의미합니다",
        "finalize",
    ),
    SegmentationCase(
        "korean_polite_final",
        "맞아요",
        "finalize",
    ),
    SegmentationCase(
        "korean_final_with_quote",
        "이 결과는 통계적으로 유의미합니다”",
        "finalize",
    ),
    SegmentationCase(
        "mixed_latin_tail",
        "이 모델 is statistically significant",
        "finalize",
    ),
    SegmentationCase(
        "long_english_clause",
        "one two three four five",
        "finalize",
    ),
    SegmentationCase(
        "short_punctuated_sentence",
        "네.",
        "finalize",
    ),
)


@dataclass(frozen=True)
class SegmentationReport:
    cases: int
    expected_deferred: int
    expected_first_pause_finalized: int
    immediate_partial_cases: int
    correctly_deferred: int
    correctly_first_pause_finalized: int
    correctly_merged: int
    forced_releases: int
    unexpected_standalone_fragments: int
    delayed_clear_boundaries: int
    finalization_mismatches: tuple[str, ...]
    pause_timeout_ms: int
    additional_hold_ms: int
    policy_max_translation_boundary_delay_ms: int
    passed: bool

    def to_dict(self) -> dict:
        return asdict(self)


async def run_benchmark(
    *,
    pause_timeout_ms: int = 1500,
    additional_hold_ms: int = 3000,
    min_chars: int = 15,
    min_tokens: int = 3,
    max_unexpected_standalone: int = 0,
    max_delayed_clear: int = 0,
    max_policy_delay_ms: int = 4500,
) -> SegmentationReport:
    """Exercise actual boundary callbacks without audio, providers, or content output."""
    immediate_partial_cases = 0
    correctly_deferred = 0
    correctly_first_pause_finalized = 0
    correctly_merged = 0
    forced_releases = 0
    unexpected_standalone = 0
    delayed_clear = 0
    mismatches: list[str] = []

    for case in _CASES:
        partials: list[str] = []
        finalized: list[str] = []
        detector = BoundaryDetector(
            pause_timeout_s=pause_timeout_ms / 1000,
            on_partial=partials.append,
            on_finalize=finalized.append,
            fragment_merge_enabled=True,
            fragment_max_hold_s=additional_hold_ms / 1000,
            min_segment_chars=min_chars,
            min_segment_tokens=min_tokens,
        )

        detector.push(case.first_delta)
        if partials and partials[0] == case.first_delta:
            immediate_partial_cases += 1

        if not finalized:
            detector._on_pause_timeout()
        finalized_at_first_pause = bool(finalized)

        if case.expected_first_pause == "defer":
            if finalized_at_first_pause:
                unexpected_standalone += 1
                mismatches.append(case.case_id)
            else:
                correctly_deferred += 1

            if case.continuation is not None and not finalized:
                detector.push(case.continuation)
                if not finalized:
                    detector._on_pause_timeout()
                expected_text = case.first_delta + case.continuation
                if finalized == [expected_text]:
                    correctly_merged += 1
                else:
                    mismatches.append(case.case_id)
            elif case.force_hold_ceiling and not finalized:
                detector._hold_started_at = time.monotonic() - (
                    additional_hold_ms / 1000 + 1
                )
                detector._on_pause_timeout()
                if finalized == [case.first_delta]:
                    forced_releases += 1
                else:
                    mismatches.append(case.case_id)
        else:
            if finalized_at_first_pause and finalized == [case.first_delta]:
                correctly_first_pause_finalized += 1
            else:
                delayed_clear += 1
                mismatches.append(case.case_id)

        detector.reset()

    expected_deferred = sum(
        case.expected_first_pause == "defer" for case in _CASES
    )
    expected_finalized = len(_CASES) - expected_deferred
    policy_max_delay_ms = pause_timeout_ms + additional_hold_ms
    passed = all(
        (
            immediate_partial_cases == len(_CASES),
            correctly_deferred == expected_deferred,
            correctly_first_pause_finalized == expected_finalized,
            correctly_merged
            == sum(case.continuation is not None for case in _CASES),
            forced_releases
            == sum(case.force_hold_ceiling for case in _CASES),
            unexpected_standalone <= max_unexpected_standalone,
            delayed_clear <= max_delayed_clear,
            policy_max_delay_ms <= max_policy_delay_ms,
            not mismatches,
        )
    )

    return SegmentationReport(
        cases=len(_CASES),
        expected_deferred=expected_deferred,
        expected_first_pause_finalized=expected_finalized,
        immediate_partial_cases=immediate_partial_cases,
        correctly_deferred=correctly_deferred,
        correctly_first_pause_finalized=correctly_first_pause_finalized,
        correctly_merged=correctly_merged,
        forced_releases=forced_releases,
        unexpected_standalone_fragments=unexpected_standalone,
        delayed_clear_boundaries=delayed_clear,
        finalization_mismatches=tuple(sorted(set(mismatches))),
        pause_timeout_ms=pause_timeout_ms,
        additional_hold_ms=additional_hold_ms,
        policy_max_translation_boundary_delay_ms=policy_max_delay_ms,
        passed=passed,
    )


def _render_human(report: SegmentationReport) -> None:
    print("Semantic segmentation benchmark (content-free)")
    for key, value in report.to_dict().items():
        print(f"{key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-unexpected-standalone", type=int, default=0)
    parser.add_argument("--max-delayed-clear", type=int, default=0)
    parser.add_argument("--max-policy-delay-ms", type=int, default=4500)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    previous_logging_ceiling = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        report = asyncio.run(
            run_benchmark(
                max_unexpected_standalone=args.max_unexpected_standalone,
                max_delayed_clear=args.max_delayed_clear,
                max_policy_delay_ms=args.max_policy_delay_ms,
            )
        )
    finally:
        logging.disable(previous_logging_ceiling)

    if args.json:
        print(json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":")))
    else:
        _render_human(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
