"""New integration only; no device/SDK/browser/server or qualified launcher."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluations.speech_timing.fixture_adapter import (
    QUALIFIED_APP_TREE,
    QUALIFIED_HEAD,
    QUALIFIED_PINS,
    TimedFixture,
    load_qualified_fixture,
)

ROOT = Path(__file__).resolve().parents[2]


def four_clips(fixture):
    async def collect():
        now = 123456.0

        async def sleep(seconds):
            nonlocal now
            now += seconds

        adapted = TimedFixture(fixture, clock=lambda: now, sleep=sleep)
        assert adapted.pcm is fixture.pcm
        assert adapted.sample_count == fixture.sample_count
        clips = []
        for _ in range(4):
            stream = adapted.stream(cadence_seconds=.1)
            chunks = []
            async with stream as sdk_stream:
                async for event in sdk_stream:
                    chunks.append(event.audio_data)
                    now += .001  # Synchronous dispatcher/consumer work.
            assert b"".join(base64.b64decode(c) for c in chunks) == fixture.pcm
            assert stream._pcm == b""
            assert stream.report()["completed"]
            clips.append({"chunks": chunks, "source": stream.report()})
        with pytest.raises(ValueError, match="clip_limit"):
            adapted.stream()
        return adapted, clips

    return asyncio.run(collect())


def player_contract(fixture):
    adapted, clips = four_clips(fixture)
    node = shutil.which("node")
    assert node, "Existing Node required; no installation"
    result = subprocess.run([
        node, "--max-old-space-size=128", str(ROOT / "evaluations/speech_timing/fixture_contract.cjs"),
        str(ROOT / "app/static/pcm-player.js"),
    ], input=json.dumps({"clips": clips}), capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode == 0, result.stderr
    browser = json.loads(result.stdout)
    assert browser["starts"] == browser["completes"] == 4
    assert browser["context_count"] == 1 and browser["remaining_bytes"] == 0
    assert browser["modes"] == ["buffered", "streaming", "streaming", "buffered"]
    assert not any(browser[k] for k in ("real_audio", "real_browser", "provider", "network"))
    paired = adapted.pair(browser["clips"])
    assert len(paired) == 4 and all(report["complete"] for report in paired.values())
    assert all(not any(report["evidence"].values()) for report in paired.values())
    assert paired["0:1"]["chunk_count"] == fixture.chunk_count
    assert "audio_data" not in json.dumps(browser)
    assert "excluded-caption" not in json.dumps(browser)
    with pytest.raises(ValueError, match="clip_identity"):
        adapted.pair({**browser["clips"], "1:1": browser["clips"]["0:1"]})
    return {"classifications": paired, "browser": browser}


def test_sdk_adapter_and_shared_player_buffered_progressive_quartet():
    fixture = SimpleNamespace(pcm=bytes(296640 * 4), sample_count=296640, chunk_count=124)
    player_contract(fixture)


def test_serial_context_and_cadence_fail_before_reading_or_starting_media():
    calls = []
    adapted = TimedFixture(SimpleNamespace(pcm=bytes(4)), clock=lambda: calls.append(1))
    for cadence in (True, 0, .2, float("nan")):
        with pytest.raises(ValueError, match="cadence"):
            adapted.stream(cadence_seconds=cadence)
    first = adapted.stream()
    assert not calls
    with pytest.raises(ValueError, match="serial_context"):
        adapted.stream()
    asyncio.run(first.__aexit__())
    assert not calls
    adapted.stream()
    with pytest.raises(ValueError, match="clip_identity"):
        adapted.pair({})


def test_qualified_loader_rejects_unavailable_and_untrusted_pack(tmp_path):
    with pytest.raises(ValueError, match="unavailable"):
        load_qualified_fixture(tmp_path)
    (tmp_path / "readiness.json").write_text(json.dumps({"status": "QUALIFIED_REVIEWED"}))
    with pytest.raises(ValueError, match="receipt_mismatch"):
        load_qualified_fixture(tmp_path)
    (tmp_path / "readiness.json").write_text("[]")
    with pytest.raises(ValueError, match="receipt_mismatch"):
        load_qualified_fixture(tmp_path)
    (tmp_path / "readiness.json").write_text(json.dumps({
        "status": "QUALIFIED_REVIEWED", "head": QUALIFIED_HEAD,
        "app_tree": QUALIFIED_APP_TREE, "helper_sha256": QUALIFIED_PINS,
    }))
    (tmp_path / "routing_runtime.py").write_text("raise AssertionError('must not execute')")
    with pytest.raises(ValueError, match="pin_mismatch"):
        load_qualified_fixture(tmp_path)


def test_retained_public_fixture_exact_qualified_bytes_and_sdk_compatibility():
    pack = os.environ.get("SPEECH_TIMING_QUALIFIED_PACK")
    if not pack:
        pytest.skip("Retained public pack not published; synthetic contract runs in ordinary CI")
    fixture = load_qualified_fixture(pack)
    assert fixture.sample_count == 296640 and fixture.duration_seconds == 12.36
    assert fixture.chunk_count == 124 and fixture.manifest["delivery"]["tail_samples"] == 1440
    assert hashlib.sha256(fixture.pcm).hexdigest() == QUALIFIED_PINS[
        "fixtures/fleurs-ko-test-offset-100-24k-f32le-v1.pcm"
    ]
    result = player_contract(fixture)
    target = os.environ.get("SPEECH_TIMING_RECEIPT_DIR")
    if target:
        (Path(target) / "qualified-fixture-numeric-results.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
