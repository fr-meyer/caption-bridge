"""Numeric speech-timing regressions; generated fixtures and fake audio nodes only."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from evaluations.speech_timing.timeline import FixtureDelivery, classify


def source_fixture(*, stall=0):
    async def scenario():
        now = 123456.0  # Its origin is never exported or mixed with the browser clock.

        async def sleep(seconds):
            nonlocal now
            now += seconds + .0005

        data = bytes(296640 * 4)
        delivery = FixtureDelivery(data, clock=lambda: now, sleep=sleep)
        received = []
        async with delivery as events:
            async for event in events:
                received.append(base64.b64decode(event.audio_data))
                now += stall if stall and len(received) == 31 else .001
        assert b"".join(received) == data
        assert delivery._pcm == b""
        return delivery.report()

    return asyncio.run(scenario())


def browser_fixture(source):
    return {
        "schema_version": 1, "clock_domain": "browser_monotonic_offsets",
        "audio_clock_domain": "audio_schedule_durations", "completed": True, "rejected": 0,
        "chunks": [{"chunk_index": r["chunk_index"], "receive_offset_ms": r["yield_offset_ms"] + 9000,
                    "receive_processing_ms": .01} for r in source["chunks"]],
        "schedules": [{"schedule_index": 0, "covered_through_chunk_index": len(source["chunks"]) - 1,
                       "submitted_offset_ms": 21500, "scheduled_ahead_ms": 20,
                       "schedule_gap_ms": 0, "duration_ms": 12360}],
        "ready_to_first_schedule_ms": .01,
    }


def test_anchored_v3_formula_records_work_without_accumulating_it():
    source = source_fixture()
    assert len(source["chunks"]) == 124
    assert sum(r["samples"] for r in source["chunks"]) == 296640
    assert source["chunks"][-1]["samples"] == 1440
    assert source["chunks"][-1]["nominal_offset_ms"] == 12300
    assert max(r["deadline_lateness_ms"] for r in source["chunks"]) < .501
    assert source["chunks"][0]["consumer_work_ms"] == pytest.approx(1)
    report = classify(source, browser_fixture(source))
    assert report["complete"]
    assert not any(report["evidence"].values())
    assert not report["cross_clock_origins_subtracted"]


def test_source_stall_remains_measured_and_classifier_does_not_assign_a_cause():
    source = source_fixture(stall=.350)
    assert source["chunks"][30]["consumer_work_ms"] == pytest.approx(350)
    assert max(r["deadline_lateness_ms"] for r in source["chunks"]) >= 249
    report = classify(source, browser_fixture(source))
    assert report["evidence"]["source_deadline_late"]
    assert not report["cause_assigned"]
    assert not report["audible_onset_measured"]


def test_domains_are_separate_and_only_intervals_are_compared():
    source = source_fixture()
    browser = browser_fixture(source)
    first = classify(source, browser)
    for row in browser["chunks"]:
        row["receive_offset_ms"] += 17000
    for row in browser["schedules"]:
        row["submitted_offset_ms"] += 17000
    second = classify(source, browser)
    assert first == second  # A different browser origin is not a transport delay.
    browser["chunks"][35]["receive_processing_ms"] = 120
    browser["ready_to_first_schedule_ms"] = 250
    result = classify(source, browser)
    assert result["evidence"]["browser_receive_work_slow"]
    assert result["evidence"]["ready_to_schedule_hold"]


@pytest.mark.parametrize("mutation", [
    lambda s, b: b.update(audio="private payload must never be admitted"),
    lambda s, b: s["chunks"][0].update(text="private text"),
    lambda s, b: b["chunks"][0].update(receive_processing_ms=float("nan")),
    lambda s, b: b["chunks"][0].update(chunk_index=True),
    lambda s, b: s["chunks"][0].update(chunk_index=0.0),
    lambda s, b: s.update(clock_domain="browser_monotonic_offsets"),
    lambda s, b: s["chunks"][1].update(deadline_lateness_ms=999),
    lambda s, b: b["schedules"][0].update(covered_through_chunk_index=124),
    lambda s, b: b["schedules"][0].update(duration_ms=999),
])
def test_unknown_content_nonfinite_values_and_wrong_identity_fail_closed(mutation):
    source = source_fixture()
    browser = browser_fixture(source)
    mutation(source, browser)
    with pytest.raises(ValueError) as failure:
        classify(source, browser)
    assert "private" not in str(failure.value)


def test_rejected_or_uncompleted_trace_is_not_certified():
    source = source_fixture()
    browser = browser_fixture(source)
    browser["rejected"] = 1
    assert not classify(source, browser)["complete"]
    browser["rejected"] = 0
    source["completed"] = False
    source["chunks"][-1]["consumer_work_ms"] = None
    assert not classify(source, browser)["complete"]
    assert "data" not in json.dumps(source)


@pytest.mark.parametrize("reported_duration", [12360, 100])
def test_completed_report_cannot_omit_final_chunk_coverage(reported_duration):
    source = source_fixture()
    browser = browser_fixture(source)
    browser["schedules"][0]["covered_through_chunk_index"] = 0
    browser["schedules"][0]["duration_ms"] = reported_duration
    with pytest.raises(ValueError, match="coverage"):
        classify(source, browser)


def test_schedule_coverage_and_submission_must_advance_after_receive():
    source = source_fixture()
    browser = browser_fixture(source)
    first = {"schedule_index": 0, "covered_through_chunk_index": 0,
             "submitted_offset_ms": 10000, "scheduled_ahead_ms": 20,
             "schedule_gap_ms": 0, "duration_ms": 100}
    last = {**first, "schedule_index": 1, "covered_through_chunk_index": 123,
            "submitted_offset_ms": 21500, "duration_ms": 12260}
    browser["schedules"] = [first, last]
    assert classify(source, browser)["complete"]
    last["submitted_offset_ms"] = 9000
    with pytest.raises(ValueError, match="nonmonotonic"):
        classify(source, browser)
    last["submitted_offset_ms"] = 20000
    with pytest.raises(ValueError, match="before_receive"):
        classify(source, browser)
    last["submitted_offset_ms"] = 21500
    last["covered_through_chunk_index"] = 0
    with pytest.raises(ValueError, match="nonmonotonic"):
        classify(source, browser)


def test_context_exit_after_break_releases_pcm_without_finishing_the_trace():
    async def scenario():
        delivery = FixtureDelivery(bytes(4800 * 4), clock=lambda: 0)
        async with delivery as events:
            async for _event in events:
                break
        assert delivery._pcm == b""
        assert not delivery.complete
        with pytest.raises(ValueError, match="fixture_single_use"):
            delivery.__aiter__()
    asyncio.run(scenario())


def test_bounded_shape_and_inert_import():
    with pytest.raises(ValueError, match="fixture_limit"):
        FixtureDelivery(bytes(307201 * 4))
    with pytest.raises(ValueError, match="fixture_shape"):
        FixtureDelivery(b"x")
    untouched = []
    delivery = FixtureDelivery(bytes(4), clock=lambda: untouched.append(1),
                               sleep=lambda _: untouched.append(2))
    assert untouched == []
    assert delivery.rows == []


def test_context_close_without_iteration_releases_fixture_and_cannot_restart():
    async def scenario():
        delivery = FixtureDelivery(bytes(4), clock=lambda: (_ for _ in ()).throw(AssertionError()))
        async with delivery:
            pass
        assert delivery._pcm == b""
        assert not delivery.complete
        assert delivery.rows == []
        with pytest.raises(ValueError, match="fixture_single_use"):
            delivery.__aiter__()
    asyncio.run(scenario())


ROOT = Path(__file__).resolve().parents[2]


def test_probe_separates_timing_evidence_without_changing_player(tmp_path):
    async def short():
        now = 0.0

        async def sleep(seconds):
            nonlocal now
            now += seconds

        delivery = FixtureDelivery(bytes(2640 * 4), clock=lambda: now, sleep=sleep)
        async with delivery as events:
            async for _event in events:
                pass
        return delivery.report()

    fixture = {"normal": source_fixture(), "stalled": source_fixture(stall=.350),
               "short": asyncio.run(short())}
    path = tmp_path / "numeric-traces.json"
    path.write_text(json.dumps(fixture))
    node = shutil.which("node")
    assert node, "Existing Node required; no installation performed"
    result = subprocess.run([
        node, "--max-old-space-size=128", str(ROOT / "evaluations/speech_timing/probe_contract.cjs"),
        str(ROOT / "app/static/pcm-player.js"), str(path),
    ], capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode == 0, result.stderr
    raw = json.loads(result.stdout)
    assert raw["passed"] and not raw["real_audio"] and not raw["real_browser"]
    reports = []
    for case in raw["cases"]:
        if case["case"] in {"observer_failure", "readonly_start"}:
            assert case["browser"]["rejected"] > 0
            with pytest.raises(ValueError, match="invalid_timing_trace"):
                classify(case["source"], case["browser"])
            continue
        report = classify(case["source"], case["browser"])
        assert report["complete"]
        assert not report["cause_assigned"] and not report["cross_clock_origins_subtracted"]
        if case["case"] == "anchored":
            assert not any(report["evidence"].values())
        if case["case"] == "controller_stall":
            assert report["evidence"]["source_deadline_late"]
            assert report["source_max_consumer_work_ms"] > 349
        if case["case"] == "resume_delay":
            assert report["evidence"]["ready_to_schedule_hold"]
            assert report["ready_to_first_schedule_ms"] == 250
        if case["case"] == "receive_work":
            assert report["evidence"]["browser_receive_work_slow"]
            assert report["browser_max_receive_work_ms"] == 120
        reports.append({"case": case["case"], **report})
    assert len(raw["cases"]) == 7
    assert raw["attachment_lifecycle_checks"] == 3
    receipt_dir = os.environ.get("SPEECH_TIMING_RECEIPT_DIR")
    if receipt_dir:
        target = Path(receipt_dir)
        target.mkdir(parents=True, exist_ok=True)
        (target / "per-chunk-model-results.json").write_text(json.dumps({
            "schema_version": 1, "classifications": reports, "raw_numeric_cases": raw,
            "physical_or_provider_acceptance": False,
        }, indent=2) + "\n")
