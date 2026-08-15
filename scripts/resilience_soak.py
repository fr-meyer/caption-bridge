"""Deterministic, content-free translation resilience soak."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Literal

from app.config import AppConfig
from app.state import SessionManager
from app.translate import TranslationDispatcher

Outcome = Literal["success", "timeout", "capacity_recover", "capacity_exhaust"]
_SEGMENT_ID = re.compile(
    r"<segment_to_translate>\s*Synthetic segment (\d+)\.",
    re.MULTILINE,
)


class InjectedCapacityError(Exception):
    """Safe synthetic exception shaped like a Mistral capacity response."""

    status_code = 429
    body = json.dumps(
        {
            "type": "service_tier_capacity_exceeded",
            "code": "3505",
            "raw_status_code": 429,
        }
    )


class ScriptedTranslationProvider:
    name = "synthetic"

    def __init__(self, timeout_sleep_s: float = 0.2) -> None:
        self.timeout_sleep_s = timeout_sleep_s
        self.attempts: dict[int, int] = defaultdict(int)
        self.active_calls = 0
        self.peak_concurrency = 0

    @staticmethod
    def outcome_for(seq: int) -> Outcome:
        bucket = seq % 100
        if bucket in {0, 1}:
            return "timeout"
        if bucket == 2:
            return "capacity_exhaust"
        if bucket in {3, 4, 5, 6, 7}:
            return "capacity_recover"
        return "success"

    async def translate(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        del model, temperature, max_tokens
        self.active_calls += 1
        self.peak_concurrency = max(self.peak_concurrency, self.active_calls)
        try:
            user_content = next(
                message["content"]
                for message in messages
                if message.get("role") == "user"
            )
            match = _SEGMENT_ID.search(user_content)
            if match is None:
                raise RuntimeError("synthetic segment id missing")
            seq = int(match.group(1))
            self.attempts[seq] += 1
            outcome = self.outcome_for(seq)
            if outcome == "timeout":
                await asyncio.sleep(self.timeout_sleep_s)
            elif outcome == "capacity_exhaust":
                raise InjectedCapacityError("injected capacity limit")
            elif outcome == "capacity_recover" and self.attempts[seq] <= 2:
                raise InjectedCapacityError("injected capacity limit")
            return f"Synthetic translated caption {seq:06d}."
        finally:
            self.active_calls -= 1


@dataclass(frozen=True)
class SoakReport:
    segments: int
    done: int
    timed_out: int
    failed: int
    pending: int
    delivered: int
    degraded_source_only: int
    duplicates: int
    ordered: bool
    provider_calls: int
    expected_provider_calls: int
    capacity_warnings: int
    peak_provider_concurrency: int
    max_provider_concurrency: int
    active_provider_calls: int
    remaining_tasks: int
    duration_ms: int
    passed: bool

    def to_dict(self) -> dict[str, int | bool]:
        return asdict(self)


async def run_soak(segments: int = 1000) -> SoakReport:
    if segments < 1:
        raise ValueError("segments must be positive")

    config = AppConfig(
        _env_file=None,
        MISTRAL_TTS_ENABLED=False,
        TRANSLATION_TIMEOUT_MS=100,
        TRANSLATION_DRAIN_TIMEOUT_MS=30000,
        TRANSLATION_MAX_CONCURRENCY=8,
        TRANSLATION_REPAIR_MAX_ATTEMPTS=0,
        TRANSLATION_429_MAX_RETRIES=2,
        TRANSLATION_429_BASE_DELAY_MS=0,
        TRANSLATION_429_MAX_DELAY_MS=1,
        TRANSLATION_429_JITTER_FACTOR=0.0,
    )
    manager = SessionManager(config)
    provider = ScriptedTranslationProvider()
    dispatcher = TranslationDispatcher(manager, config, provider=provider)
    manager.set_dispatcher(dispatcher)

    events: list[dict] = []
    manager.subscribe(events.append)
    started = time.perf_counter()
    for seq in range(1, segments + 1):
        manager.finalize_segment(f"Synthetic segment {seq:06d}.")
    await dispatcher.drain()
    await asyncio.sleep(0)
    duration_ms = round((time.perf_counter() - started) * 1000)

    status_counts = Counter(
        segment.translation_status for segment in manager.session.segments
    )
    captions = [event for event in events if event["type"] == "caption"]
    delivered_seq = [int(event["seq"]) for event in captions]
    degraded_source_only = sum(
        1
        for event in captions
        if event["translation_status"] in {"timed_out", "failed"}
        and event["translated_text"] is None
        and bool(event["source_text"])
    )
    warnings = [
        event for event in events if event["type"] == "provider_capacity_warning"
    ]
    expected_outcomes = Counter(
        provider.outcome_for(seq) for seq in range(1, segments + 1)
    )
    expected_done = expected_outcomes["success"] + expected_outcomes["capacity_recover"]
    expected_calls = (
        expected_outcomes["success"]
        + expected_outcomes["timeout"]
        + 3 * expected_outcomes["capacity_recover"]
        + 3 * expected_outcomes["capacity_exhaust"]
    )
    provider_calls = sum(provider.attempts.values())
    ordered = delivered_seq == list(range(1, segments + 1))
    duplicates = len(delivered_seq) - len(set(delivered_seq))
    remaining_tasks = len(dispatcher._in_flight)

    passed = all(
        (
            status_counts["done"] == expected_done,
            status_counts["timed_out"] == expected_outcomes["timeout"],
            status_counts["failed"] == expected_outcomes["capacity_exhaust"],
            status_counts["pending"] == 0,
            len(captions) == segments,
            degraded_source_only
            == expected_outcomes["timeout"] + expected_outcomes["capacity_exhaust"],
            duplicates == 0,
            ordered,
            provider_calls == expected_calls,
            len(warnings) == expected_outcomes["capacity_exhaust"],
            1 <= provider.peak_concurrency <= config.translation_max_concurrency,
            provider.active_calls == 0,
            remaining_tasks == 0,
        )
    )
    return SoakReport(
        segments=segments,
        done=status_counts["done"],
        timed_out=status_counts["timed_out"],
        failed=status_counts["failed"],
        pending=status_counts["pending"],
        delivered=len(captions),
        degraded_source_only=degraded_source_only,
        duplicates=duplicates,
        ordered=ordered,
        provider_calls=provider_calls,
        expected_provider_calls=expected_calls,
        capacity_warnings=len(warnings),
        peak_provider_concurrency=provider.peak_concurrency,
        max_provider_concurrency=config.translation_max_concurrency,
        active_provider_calls=provider.active_calls,
        remaining_tasks=remaining_tasks,
        duration_ms=duration_ms,
        passed=passed,
    )


def _render_human(report: SoakReport) -> None:
    payload = report.to_dict()
    print("Translation resilience soak (content-free)")
    for key in (
        "segments",
        "done",
        "timed_out",
        "failed",
        "pending",
        "delivered",
        "degraded_source_only",
        "duplicates",
        "ordered",
        "provider_calls",
        "expected_provider_calls",
        "capacity_warnings",
        "peak_provider_concurrency",
        "max_provider_concurrency",
        "active_provider_calls",
        "remaining_tasks",
        "duration_ms",
        "passed",
    ):
        print(f"{key}: {payload[key]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--segments", type=int, default=1000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    previous_logging_ceiling = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        report = asyncio.run(run_soak(args.segments))
    except ValueError as exc:
        parser.error(str(exc))
    finally:
        logging.disable(previous_logging_ceiling)
    if args.json:
        print(json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":")))
    else:
        _render_human(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
