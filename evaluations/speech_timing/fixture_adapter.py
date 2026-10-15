"""Explicit, offline adapter for the retained public-fixture SDK interface.

Import is inert. Loading reads existing pinned files; it never prepares audio,
starts the qualified launcher, imports the application or opens a device.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from types import ModuleType

from evaluations.speech_timing.timeline import FixtureDelivery, classify

QUALIFIED_HEAD = "a746f9aff65ee40ff3943d1137127378e744fae2"
QUALIFIED_APP_TREE = "bc00dc015d58374ec579b9ce6063df8635567197"
QUALIFIED_PINS = {
    "routing_runtime.py": "80026e8300498390691a91fe9a1dea11a898c82a597c4346ccf11da9bfc64b66",
    "browser_actor.py": "8983aded4fe7096c7f72ad23a6e82338f046193257689bfd330c547f3a8f047b",
    "launch_trial.py": "fbfe7d8f4edcfbef07d59c2ff9959d1c6d02d6b49b00fe5ea0ba5a880327c729",
    "routing_view.py": "c93c82b46ec5dd03ef791f9ebe582e3d4bdeb43663d710e8eba50917147bd9ff",
    "fixture_and_measurements.py": "21018728772f94284f131eb3a72468b441d59af65d62e27267013562b11902e5",
    "fixtures/manifest.json": "f7e9be4feff764c3a419e9b571f7adb45f3832018c7cdedd0df168e8d1f7e8be",
    "fixtures/fleurs-ko-test-offset-100-24k-f32le-v1.pcm":
        "b30f5ce9ef826d1b6f2b0dd5f9b80c514493547d9f130fc4fefc47a296282b14",
}


def load_qualified_fixture(root):
    """Read the exact retained pack, without executing its launcher or runtime."""
    root = Path(root).resolve()
    try:
        if not 0 < (root / "readiness.json").stat().st_size <= 32768:
            raise ValueError("qualified_fixture_receipt_limit")
        receipt = json.loads((root / "readiness.json").read_text())
        if (not isinstance(receipt, dict) or receipt.get("status") != "QUALIFIED_REVIEWED"
                or receipt.get("head") != QUALIFIED_HEAD
                or receipt.get("app_tree") != QUALIFIED_APP_TREE
                or receipt.get("helper_sha256") != QUALIFIED_PINS):
            raise ValueError("qualified_fixture_receipt_mismatch")
        verified = {}
        for name, expected in QUALIFIED_PINS.items():
            path = root / name
            if not 0 < path.stat().st_size <= 2 * 1024 * 1024:
                raise ValueError("qualified_fixture_file_limit")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("qualified_fixture_pin_mismatch")
            verified[name] = data
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        raise ValueError("qualified_fixture_pack_unavailable") from None
    # The hash-verified, inert fixture module uses dataclasses. Register only
    # during execution, and compile verified bytes rather than import/pycache.
    name = "_caption_verified_public_fixture"
    if name in sys.modules:
        raise ValueError("qualified_fixture_load_in_progress")
    module = ModuleType(name)
    module.__file__ = str(root / "fixture_and_measurements.py")
    sys.modules[name] = module
    try:
        exec(compile(verified["fixture_and_measurements.py"], module.__file__, "exec"), module.__dict__)
        fixture = module.load_fixture(root / "fixtures")
        # Recheck the returned bytes: load_fixture performs a second filesystem
        # read, so a changed pack between verification and loading is rejected.
        if hashlib.sha256(fixture.pcm).hexdigest() != QUALIFIED_PINS[
            "fixtures/fleurs-ko-test-offset-100-24k-f32le-v1.pcm"
        ]:
            raise ValueError("qualified_fixture_pin_mismatch")
        for filename, expected in QUALIFIED_PINS.items():
            if hashlib.sha256((root / filename).read_bytes()).hexdigest() != expected:
                raise ValueError("qualified_fixture_pin_mismatch")
        return fixture
    finally:
        del sys.modules[name]


class TimedFixture:
    """Drop-in fixture.stream adapter for four serial B/P/P/B public clips.

    The caller still owns fake SDK installation and the existing player. This
    class creates neither. Only cadence changes; fixture bytes/properties stay
    those of the supplied immutable fixture. Clip ordinal is valid only for
    the qualified serial protocol, before refresh (epoch zero).
    """

    def __init__(self, fixture, *, clock=time.monotonic, sleep=asyncio.sleep):
        self.fixture, self.clock, self.sleep = fixture, clock, sleep
        self.deliveries = []

    def __getattr__(self, name):
        return getattr(self.fixture, name)

    def stream(self, cadence_seconds=.1):
        if type(cadence_seconds) not in (int, float) or cadence_seconds != .1:
            raise ValueError("qualified_fixture_cadence_required")
        if len(self.deliveries) >= 4:
            raise ValueError("qualified_fixture_clip_limit")
        if self.deliveries and not self.deliveries[-1]._closed:
            raise ValueError("qualified_fixture_serial_context_required")
        delivery = FixtureDelivery(self.fixture.pcm, clock=self.clock, sleep=self.sleep)
        self.deliveries.append(delivery)
        return delivery

    def pair(self, browser_clips):
        """Validate ordinal/epoch scope and allowlisted numeric traces only."""
        expected = {f"0:{index + 1}" for index in range(len(self.deliveries))}
        if (not expected or not isinstance(browser_clips, dict)
                or browser_clips.keys() != expected):
            raise ValueError("qualified_fixture_clip_identity")
        return {key: classify(delivery.report(), browser_clips[key])
                for key, delivery in zip(sorted(expected), self.deliveries, strict=True)}
