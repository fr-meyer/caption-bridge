"""New hook/actor contracts with fake pages, clocks and nodes only."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluations.speech_timing.actor_adapter import ActorTimingBridge, browser_init_script
from evaluations.speech_timing.fixture_adapter import TimedFixture, load_qualified_fixture

ROOT = Path(__file__).resolve().parents[2]


def source_quartet(pcm):
    async def collect():
        now = 123456.0

        async def sleep(seconds):
            nonlocal now
            now += seconds

        import base64

        fixture = TimedFixture(SimpleNamespace(pcm=pcm), clock=lambda: now, sleep=sleep)
        clips = []
        for _ in range(4):
            stream = fixture.stream()
            chunks = []
            async with stream as events:
                async for event in events:
                    chunks.append(event.audio_data)
                    now += .001
            assert b"".join(base64.b64decode(c) for c in chunks) == pcm
            clips.append({"chunks": chunks, "source": stream.report()})
        return fixture, clips

    return asyncio.run(collect())


def attachment_contract(pcm):
    fixture, clips = source_quartet(pcm)
    actor = FakeActor(None)
    bridge = ActorTimingBridge(actor, fixture).attach()

    async def scripts():
        await actor.install_observers()
        await bridge.close()
    asyncio.run(scripts())
    node = shutil.which("node")
    assert node, "Existing Node required; no installation"
    run = subprocess.run([
        node, "--max-old-space-size=128", str(ROOT / "evaluations/speech_timing/attachment_contract.cjs"),
        str(ROOT / "app/static/pcm-player.js"),
    ], input=json.dumps({"clips": clips, "init_script": actor.scripts[0],
                        "disable_script": actor.scripts[1]}),
        capture_output=True, text=True, timeout=5, check=False)
    assert run.returncode == 0, run.stderr
    browser = json.loads(run.stdout)
    reports = fixture.pair(browser["clips"])
    assert all(r["complete"] and not any(r["evidence"].values()) for r in reports.values())
    assert browser["starts"] == browser["completes"] == 4
    assert browser["modes"] == ["buffered", "streaming", "streaming", "buffered"]
    assert browser["lifecycle_negative_contracts"] == 3
    assert browser["refresh_retirement_orders"] == 2
    return fixture, browser


def test_deferred_factory_and_existing_player_observer_keep_first_chunk_and_quartet():
    attachment_contract(bytes(6240 * 4))


def test_exact_public_pack_through_new_browser_attachment():
    pack = os.environ.get("SPEECH_TIMING_QUALIFIED_PACK")
    if not pack:
        pytest.skip("Retained public fixture is local; synthetic hook case runs in CI")
    fixture = load_qualified_fixture(pack)
    _, result = attachment_contract(fixture.pcm)
    assert all(len(r["chunks"]) == 124 for r in result["clips"].values())
    target = os.environ.get("SPEECH_TIMING_RECEIPT_DIR")
    if target:
        (Path(target) / "browser-attachment-public-numeric.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )


class FakeActor:
    offline = True
    base_url = "http://127.0.0.1:55555/"

    def __init__(self, snapshot):
        self.snapshot, self.scripts, self.events = snapshot, [], []
        class Page:
            pass
        self.page = Page()
        self.page.add_init_script, self.page.evaluate = self.add_script, self.evaluate
        self.disabled = False

    async def add_script(self, value):
        self.scripts.append(value)

    async def evaluate(self, _script):
        if "__fixtureTimingDisabled=true" in _script:
            self.disabled = True
            return True
        return self.snapshot

    async def install_observers(self, **kwargs):
        self.events.append(("original_install", kwargs))

    async def observe(self):
        self.events.append(("original_observe", {}))
        return {"original_observation": True}


def test_actor_bridge_collects_only_complete_numeric_data_and_restores_owned_methods(tmp_path):
    fixture, browser = attachment_contract(bytes(6240 * 4))
    actor = FakeActor({"schema_version": 1, "completed": True, "rejected": 0, "clips": browser["clips"]})
    bridge = ActorTimingBridge(actor, fixture, receipt_dir=tmp_path)
    assert actor.scripts == [] and not bridge.reports
    bridge.attach()
    with pytest.raises(ValueError, match="offline_fixture_attachment"):
        ActorTimingBridge(actor, fixture).attach()

    async def scenario():
        await actor.install_observers(fixture_script="fake media only")
        assert actor.events == [("original_install", {"fixture_script": "fake media only"})]
        assert len(actor.scripts) == 1 and "installFixtureTiming" in actor.scripts[0]
        assert await actor.observe() == {"original_observation": True}
    asyncio.run(scenario())
    assert len(bridge.require_quartet()) == 4
    saved = json.loads((tmp_path / "per-chunk-timing.json").read_text())
    assert len(saved["clips"]) == 4 and "audio_data" not in json.dumps(saved)
    assert all(row["classification"]["complete"] and len(row["source"]["chunks"]) == 3
               and len(row["browser"]["chunks"]) == 3 for row in saved["clips"].values())
    def replacement():
        return None
    actor.observe = replacement
    asyncio.run(bridge.close())
    asyncio.run(bridge.close())
    assert actor.observe is replacement
    assert actor.disabled and len(actor.scripts) == 2
    with pytest.raises(ValueError, match="offline_fixture_attachment"):
        bridge.attach()
    with pytest.raises(ValueError, match="offline_fixture_attachment"):
        ActorTimingBridge(actor, fixture).attach()
    same_page_actor = FakeActor(None)
    same_page_actor.page = actor.page
    with pytest.raises(ValueError, match="offline_fixture_attachment"):
        ActorTimingBridge(same_page_actor, fixture).attach()


@pytest.mark.parametrize("snapshot", [None, {}, {"audio_data": "must never persist"},
    {"schema_version": 1, "completed": False, "rejected": 1, "clips": {}}])
def test_actor_bridge_rejects_missing_or_content_bearing_snapshot(snapshot, tmp_path):
    actor = FakeActor(snapshot)
    bridge = ActorTimingBridge(actor, SimpleNamespace(deliveries=[]), receipt_dir=tmp_path).attach()
    with pytest.raises(ValueError, match="fixture_attachment_snapshot"):
        asyncio.run(actor.observe())
    assert list(tmp_path.iterdir()) == []
    asyncio.run(bridge.close())


def test_scope_and_attended_mode_do_not_start_any_operation():
    for url in ("https://127.0.0.1:55555/", "http://localhost:55555/", "http://127.0.0.1/",
                "http://127.0.0.1:55555/?secret=x"):
        with pytest.raises(ValueError, match="fixture_attachment_scope"):
            browser_init_script(url)
    actor = FakeActor(None)
    actor.offline = False
    bridge = ActorTimingBridge(actor, SimpleNamespace(deliveries=[]))
    with pytest.raises(ValueError, match="offline_fixture_attachment"):
        bridge.attach()
    assert actor.events == actor.scripts == []
    with pytest.raises(ValueError, match="quartet_incomplete"):
        bridge.require_quartet()
