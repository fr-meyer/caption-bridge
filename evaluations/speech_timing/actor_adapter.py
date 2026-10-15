"""Opt-in bridge for an existing offline actor and the same TimedFixture.

Import/construction are inert. This does not create a browser, SDK, device,
server or launcher. Only the owner invokes the original actor operations.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit
from weakref import WeakKeyDictionary, WeakSet

_OWNERS = WeakKeyDictionary()
_USED_ACTORS, _USED_PAGES = WeakSet(), WeakSet()
_DISABLE_SCRIPT = """(() => {
  window.__fixtureTimingDisabled=true;
  window.__fixtureChunkTiming?.dispose();
  return true;
})()"""


def browser_init_script(base_url):
    try:
        url = urlsplit(base_url)
        valid = (url.scheme == "http" and url.hostname == "127.0.0.1" and url.port
                 and not url.username and not url.password and not url.query
                 and not url.fragment and url.path in {"", "/"})
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("fixture_attachment_scope")
    root = Path(__file__).resolve().parent
    return ("\nif (!window.__fixtureTimingDisabled) {\n"
            + (root / "browser_probe.cjs").read_text()
            + "\n" + (root / "browser_attachment.cjs").read_text()
            + "\nwindow.__fixtureChunkTiming = window.CaptionFixtureTiming.installFixtureTiming("
            + "window," + json.dumps({"baseUrl": base_url}) + ");\n}\n")


class ActorTimingBridge:
    """Attach before actor.install_observers; preserve original helper bytes.

    Supported here only for the offline actor. Source/player contracts do not
    authorize or qualify attended use. The caller supplies the same TimedFixture
    object to the existing fake SDK runtime and this bridge.
    """

    def __init__(self, actor, fixture, *, receipt_dir=None):
        self.actor, self.fixture = actor, fixture
        self.receipt_dir = Path(receipt_dir) if receipt_dir is not None else None
        self.reports = {}
        self.numeric_traces = {}
        self.attached = False
        self.used = False

    def attach(self):
        if (self.used or self.actor in _USED_ACTORS or self.actor.page in _USED_PAGES
                or self.actor in _OWNERS or not self.actor.offline):
            raise ValueError("offline_fixture_attachment_required")
        self.original_install = self.actor.install_observers
        self.original_observe = self.actor.observe

        async def install(*args, **kwargs):
            await self.original_install(*args, **kwargs)
            await self.actor.page.add_init_script(browser_init_script(self.actor.base_url))

        async def observe(*args, **kwargs):
            value = await self.original_observe(*args, **kwargs)
            snapshot = await self.actor.page.evaluate(
                "() => window.__fixtureChunkTiming?.snapshot()"
            )
            if (not isinstance(snapshot, dict) or snapshot.keys() != {
                    "schema_version", "completed", "rejected", "clips"}
                    or type(snapshot["schema_version"]) is not int
                    or snapshot["schema_version"] != 1
                    or type(snapshot["completed"]) is not bool
                    or type(snapshot["rejected"]) is not int or snapshot["rejected"] != 0
                    or not isinstance(snapshot["clips"], dict) or len(snapshot["clips"]) > 4):
                raise ValueError("fixture_attachment_snapshot")
            if not all(isinstance(row, dict) for row in snapshot["clips"].values()):
                raise ValueError("fixture_attachment_snapshot")
            if snapshot["completed"] and len(snapshot["clips"]) != 4:
                raise ValueError("fixture_attachment_snapshot")
            deliveries = self.fixture.deliveries
            if not deliveries or not all(d.complete and d._closed for d in deliveries):
                return value
            if len(snapshot["clips"]) != len(deliveries):
                return value  # The browser has not reached this source generation yet.
            if not all(row.get("completed") is True for row in snapshot["clips"].values()):
                return value
            reports = self.fixture.pair(snapshot["clips"])
            if not all(report["complete"] for report in reports.values()):
                raise ValueError("fixture_attachment_incomplete")
            if len(reports) == 4 and not snapshot["completed"]:
                raise ValueError("fixture_attachment_incomplete")
            if len(reports) > len(self.reports):
                self.reports = reports
                self.numeric_traces = {
                    key: {"source": delivery.report(), "browser": snapshot["clips"][key],
                          "classification": reports[key]}
                    for key, delivery in zip(sorted(reports), deliveries, strict=True)
                }
                if self.receipt_dir is not None:
                    (self.receipt_dir / "per-chunk-timing.json").write_text(
                        json.dumps({"schema_version": 1, "clips": self.numeric_traces}, indent=2)
                        + "\n"
                    )
            return value

        self.install_wrapper, self.observe_wrapper = install, observe
        self.actor.install_observers, self.actor.observe = install, observe
        self.attached = True
        self.used = True
        _OWNERS[self.actor] = self
        _USED_ACTORS.add(self.actor)
        _USED_PAGES.add(self.actor.page)
        return self

    async def close(self):
        if not self.attached:
            return
        try:
            # Init scripts have no individual removal API. On any later
            # navigation, either order is safe: disable runs first and the
            # installer skips, or runs second and immediately disposes it.
            await self.actor.page.add_init_script(_DISABLE_SCRIPT)
            await self.actor.page.evaluate(_DISABLE_SCRIPT)
        finally:
            if self.actor.install_observers is self.install_wrapper:
                self.actor.install_observers = self.original_install
            if self.actor.observe is self.observe_wrapper:
                self.actor.observe = self.original_observe
            self.attached = False
            if _OWNERS.get(self.actor) is self:
                del _OWNERS[self.actor]

    def require_quartet(self):
        if len(self.reports) != 4 or not all(r["complete"] for r in self.reports.values()):
            raise ValueError("fixture_attachment_quartet_incomplete")
        return dict(self.reports)
