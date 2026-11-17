"""Provider-free catalogue contracts, runnable with stdlib unittest."""
import asyncio
import unittest

from app.translation_catalogue import ModelCatalogue, reconcile


def row(model, chat=True):
    return {"id": model, "capabilities": {"completion_chat": chat}}


def active(family="family", release=1, alias=None):
    return dict(status="active", family=family, release=release, alias=alias)


class CatalogueTests(unittest.TestCase):
    def test_lifecycle_capabilities_and_missing_policy(self):
        for status, chat, policy, expected in [
            ("active", True, True, None),
            ("retired", True, True, "lifecycle_retired"),
            ("deprecated", True, True, "lifecycle_deprecated"),
            ("conflicting", True, True, "lifecycle_conflicting"),
            ("unknown", True, True, "lifecycle_unknown"),
            ("active", False, True, "text_chat_not_supported"),
            ("active", True, False, "execution_policy_unverified"),
        ]:
            with self.subTest(status=status, chat=chat, policy=policy):
                result = reconcile([row("hosted", chat)], {"hosted": {"status": status}},
                                   {"hosted": {}} if policy else {})[0]
                self.assertEqual(result["reason"], expected)
                self.assertEqual(result["enabled"], expected is None)

    def test_official_alias_wins_only_when_account_available(self):
        evidence = {"dated": active(release=2),
                    "official": active(alias="official"), "old": active()}
        policies = {key: {} for key in evidence}
        result = reconcile([row(key) for key in evidence], evidence, policies)
        self.assertEqual([item["id"] for item in result], ["official"])
        result = reconcile([row("dated"), row("old")], evidence, policies)
        self.assertEqual([item["id"] for item in result], ["dated"])
        self.assertEqual(result[0]["version_policy"], "versioned")

    def test_corroborating_alias_cards_are_not_conflicting(self):
        version = dict(row("snapshot"), aliases=["official"])
        alias = dict(row("official"), name="Alias display name")
        evidence = {"snapshot": active(), "official": active(alias="official")}
        result = reconcile([version, alias], evidence, {"snapshot": {}, "official": {}})
        self.assertEqual([item["id"] for item in result], ["official"])
        self.assertTrue(result[0]["enabled"])

    def test_alias_list_requires_verified_target(self):
        account = dict(row("snapshot"), aliases=["official", "invented-latest"])
        evidence = {"snapshot": active(), "official": active(alias="official")}
        result = reconcile([account], evidence, {"snapshot": {}, "official": {}})
        self.assertEqual([item["id"] for item in result], ["official"])
        self.assertEqual(result[0]["catalogue_target"], "snapshot")
        result = reconcile([account], {"official": active(alias="official")}, {"official": {}})
        self.assertEqual(next(item for item in result if item["id"] == "official")["reason"],
                         "alias_target_unverified")

    def test_variants_not_conflated(self):
        evidence = {"glm": active("glm"), "glm-flash": active("glm-flash")}
        self.assertEqual(len(reconcile([row(key) for key in evidence], evidence,
                                       {key: {} for key in evidence})), 2)

    def test_duplicate_and_conflicting_metadata(self):
        evidence, policies = {"x": active()}, {"x": {}}
        self.assertEqual(len(reconcile([row("x"), row("x")], evidence, policies)), 1)
        self.assertEqual(reconcile([row("x"), row("x", False)], evidence, policies)[0]["reason"],
                         "conflicting_account_metadata")

    def test_unknown_new_hosted_family_is_visible_not_guessed(self):
        result = reconcile([row("new-hosted-model")], {}, {})[0]
        self.assertFalse(result["enabled"])
        self.assertEqual(result["reason"], "lifecycle_unknown")
        self.assertEqual(result["id"], "new-hosted-model")

    def test_cache_rate_limit_expiry_failure_and_retirement(self):
        async def scenario():
            now = [0]
            cache = ModelCatalogue(ttl=10, clock=lambda: now[0])
            calls = []
            async def loader():
                calls.append(True)
                return [row("x")]
            await cache.refresh(loader, {"x": active()}, {"x": {}})
            await cache.refresh(loader, {}, {})
            self.assertEqual(len(calls), 1)
            self.assertTrue(cache.snapshot()["models"][0]["enabled"])
            now[0] = 11
            self.assertFalse(cache.snapshot()["models"][0]["enabled"])
            async def fail():
                raise ValueError("not retained")
            await cache.refresh(fail, {}, {})
            self.assertEqual(cache.error, "catalogue_refresh_failed")
            self.assertFalse(cache.snapshot()["models"][0]["enabled"])
            now[0] = 22
            await cache.refresh(loader, {"x": {"status": "retired"}}, {"x": {}})
            self.assertEqual(cache.snapshot()["models"][0]["reason"], "lifecycle_retired")
        asyncio.run(scenario())

    def test_cancellation_propagates_without_publication(self):
        async def scenario():
            cache = ModelCatalogue()
            async def loader():
                raise asyncio.CancelledError()
            with self.assertRaises(asyncio.CancelledError):
                await cache.refresh(loader, {}, {})
            self.assertIsNone(cache.verified_at)
        asyncio.run(scenario())

    def test_timeout_is_bounded(self):
        async def scenario():
            cache = ModelCatalogue(timeout=0.001)
            async def loader():
                await asyncio.sleep(60)
            await cache.refresh(loader, {}, {})
            self.assertEqual(cache.error, "catalogue_refresh_failed")
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
