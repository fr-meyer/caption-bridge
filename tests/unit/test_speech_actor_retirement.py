"""Faulted observer retirement with inert actor/page objects only."""
from __future__ import annotations

import asyncio
import unittest

from evaluations.speech_timing.actor_adapter import ActorTimingBridge


class RetirementFailure(RuntimeError):
    pass


class Page:
    def __init__(self, *, fail_registration=False, fail_disposal=False):
        self.fail_registration = fail_registration
        self.fail_disposal = fail_disposal
        self.actions = []
        self.disabled = False

    async def add_init_script(self, script):
        self.actions.append("register")
        assert "__fixtureTimingDisabled=true" in script
        if self.fail_registration:
            raise RetirementFailure("registration_failed")

    async def evaluate(self, script):
        self.actions.append("dispose")
        assert "__fixtureTimingDisabled=true" in script
        if self.fail_disposal:
            raise RetirementFailure("disposal_failed")
        self.disabled = True
        return True


class Actor:
    offline = True
    base_url = "http://127.0.0.1:55555/"

    def __init__(self, page):
        self.page = page
        self.operations = []

    async def install_observers(self):
        self.operations.append("install")

    async def observe(self):
        self.operations.append("observe")


class ActorRetirementTests(unittest.IsolatedAsyncioTestCase):
    def attach(self, page):
        actor = Actor(page)
        originals = actor.install_observers, actor.observe
        bridge = ActorTimingBridge(actor, object()).attach()
        return actor, originals, bridge

    async def finish_retry(self, actor, originals, bridge):
        self.assertEqual((actor.install_observers, actor.observe), originals)
        actor.page.fail_registration = actor.page.fail_disposal = False
        await bridge.close()
        self.assertEqual(actor.page.actions, ["register", "dispose"] * 2)
        self.assertTrue(actor.page.disabled)
        await bridge.close()
        self.assertEqual(actor.page.actions, ["register", "dispose"] * 2)
        self.assertEqual(actor.operations, [])

    async def test_registration_failure_still_disposes_current_page_and_can_retry(self):
        actor, originals, bridge = self.attach(Page(fail_registration=True))
        with self.assertRaises(RetirementFailure):
            await bridge.close()
        self.assertEqual(actor.page.actions, ["register", "dispose"])
        self.assertTrue(actor.page.disabled)
        await self.finish_retry(actor, originals, bridge)

    async def test_disposal_failure_can_retry_after_python_methods_are_restored(self):
        actor, originals, bridge = self.attach(Page(fail_disposal=True))
        with self.assertRaises(RetirementFailure):
            await bridge.close()
        self.assertEqual(actor.page.actions, ["register", "dispose"])
        await self.finish_retry(actor, originals, bridge)

    async def test_registration_cancellation_remains_primary_when_disposal_also_fails(self):
        page = Page(fail_disposal=True)
        original_registration = page.add_init_script

        async def cancelled_registration(_script):
            page.actions.append("register")
            raise asyncio.CancelledError

        page.add_init_script = cancelled_registration
        actor, originals, bridge = self.attach(page)
        with self.assertRaises(asyncio.CancelledError):
            await bridge.close()
        self.assertEqual(page.actions, ["register", "dispose"])
        page.add_init_script = original_registration
        await self.finish_retry(actor, originals, bridge)

    async def test_both_failures_remain_retryable_and_preserve_newer_method_owners(self):
        actor, _originals, bridge = self.attach(Page(
            fail_registration=True, fail_disposal=True,
        ))

        async def replacement():
            return None

        actor.install_observers = actor.observe = replacement
        with self.assertRaises(RetirementFailure):
            await bridge.close()
        self.assertEqual(actor.page.actions, ["register", "dispose"])
        self.assertIs(actor.install_observers, replacement)
        self.assertIs(actor.observe, replacement)
        with self.assertRaisesRegex(ValueError, "offline_fixture_attachment"):
            ActorTimingBridge(actor, object()).attach()
        await self.finish_retry(actor, (replacement, replacement), bridge)

    async def test_successful_close_is_idempotent_without_starting_actor_operations(self):
        actor, originals, bridge = self.attach(Page())
        await bridge.close()
        await bridge.close()
        self.assertEqual(actor.page.actions, ["register", "dispose"])
        self.assertTrue(actor.page.disabled)
        self.assertEqual((actor.install_observers, actor.observe), originals)
        self.assertEqual(actor.operations, [])
