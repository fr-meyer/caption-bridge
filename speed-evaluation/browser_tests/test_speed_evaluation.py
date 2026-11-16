"""Bounded, provider-free browser measurements; emits aggregate numbers only."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest
from playwright.sync_api import Page

HARNESS = Path(__file__).with_name("speed_harness.js")
EVIDENCE = Path(os.environ.get("SPEED_EVIDENCE_DIR", "/tmp/speed-evaluation-evidence"))
RATES = (1.0, 1.15, 1.3)


def _open(page: Page) -> None:
    # No application endpoint, external requests, provider, microphone or real audio.
    page.route("**/*", lambda route: route.abort())
    page.set_content("<!doctype html><title>Silent speed evaluation</title>")
    page.add_script_tag(content=HARNESS.read_text())


def _record(browser_name: str, measurement: dict) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    pitch = measurement.get("requested_preserves_pitch", "offline")
    label = f"{browser_name}-{measurement['mechanism'].split('.')[0]}-{measurement['rate']}-{pitch}"
    (EVIDENCE / f"{label}.json").write_text(json.dumps(measurement, indent=2) + "\n")


@pytest.mark.parametrize("rate", RATES)
def test_offline_resampling_duration_and_pitch(
    page: Page, browser_name: str, rate: float
) -> None:
    _open(page)
    result = page.evaluate("rate => speedEvaluation.resampling(rate)", rate)
    result["browser"] = browser_name
    result["user_agent"] = page.evaluate("navigator.userAgent")
    _record(browser_name, result)
    # One render quantum accommodates implementation-specific interpolation tails.
    assert abs(result["measured_duration_seconds"] - 1 / rate) <= 128 / 24000
    assert abs(result["measured_frequency_hz"] - 440 * rate) < 0.25
    assert abs(result["measured_pitch_shift_semitones"] - 12 * math.log2(rate)) < 0.02
    assert result["has_preserves_pitch_property"] is False
    assert result["audible_output"] is False


@pytest.mark.parametrize("rate", RATES)
def test_muted_media_alternative_api_and_duration(
    page: Page, browser_name: str, rate: float
) -> None:
    _open(page)
    result = page.evaluate("rate => speedEvaluation.media(rate, true)", rate)
    result["browser"] = browser_name
    result["user_agent"] = page.evaluate("navigator.userAgent")
    _record(browser_name, result)
    if not result["media_playback_supported"]:
        assert result["media_error_code"] == 4
        assert result["muted"] is True and result["volume"] == 0
        pytest.skip(result["limitation"])
    assert result["pitch_property"] is not None
    assert result["default_preserves_pitch"] is True
    assert result["observed_preserves_pitch"] is True
    assert result["actual_playback_rate"] == rate
    assert result["playing_events"] == 1
    assert result["monotonic_media_time"] is True
    assert abs(result["input_duration_seconds"] - 1) < 0.001
    assert abs(result["final_media_time_seconds"] - 1) < 0.001
    # Wall-time observation includes browser scheduling; it is not a latency SLA.
    assert abs(result["measured_playing_to_ended_seconds"] - 1 / rate) < 0.35
    assert result["pitch_frequency_measured"] is False
    assert result["muted"] is True and result["volume"] == 0
    assert result["audible_output"] is False


def test_media_pitch_preservation_switch_is_exposed(page: Page, browser_name: str) -> None:
    _open(page)
    result = page.evaluate("() => speedEvaluation.mediaSupport()")
    result["browser"] = browser_name
    result["user_agent"] = page.evaluate("navigator.userAgent")
    _record(browser_name, result)
    assert result["pitch_property"] is not None
    assert result["default_preserves_pitch"] is True
    assert result["property_after_disabled"] is False
    assert result["property_after_enabled"] is True
    assert result["media_source_pcm_wav"] is False
    assert result["audible_output"] is False
