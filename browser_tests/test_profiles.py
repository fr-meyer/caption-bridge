"""Synthetic browser contracts for remembered language/caption timing choices."""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.browser
KEY = "captionBridge.sessionProfile"


def open_profile(page: Page, harness) -> None:
    harness.configure("glossary_idle")
    page.goto(harness.url, wait_until="domcontentloaded")
    harness.wait_for_connections(1)
    page.locator("#caption-profile-editor summary").click()


def test_unremembered_selection_is_sent_and_resets_on_refresh(page: Page, browser_harness) -> None:
    open_profile(page, browser_harness)
    expect(page.locator("#caption-profile-remember")).not_to_be_checked()
    expect(page.locator("#caption-timing")).to_have_value("current")
    page.locator("#idle-target-select").select_option("fr")
    page.get_by_label("Caption timing", exact=True).select_option("shorter")
    assert page.evaluate("(key) => localStorage.getItem(key)", KEY) is None
    page.get_by_role("button", name="Start", exact=True).click()
    message = browser_harness.wait_for_message("start")
    assert message["target_language"] == "fr"
    assert message["caption_profile"] == "shorter"
    expect(page.locator("#caption-profile-session-note")).to_contain_text("Shorter pauses")
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#idle-target-select")).to_have_value("en")
    expect(page.locator("#caption-timing")).to_have_value("current")


def test_explicit_remember_restores_pair_and_unchecking_forgets(page: Page, browser_harness) -> None:
    open_profile(page, browser_harness)
    page.locator("#idle-target-select").select_option("fr")
    page.locator("#caption-timing").select_option("longer")
    page.locator("#caption-profile-remember").check()
    assert json.loads(page.evaluate("(key) => localStorage.getItem(key)", KEY)) == {
        "version": 1, "targetLanguage": "fr", "id": "longer",
    }
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#idle-target-select")).to_have_value("fr")
    expect(page.locator("#caption-timing")).to_have_value("longer")
    page.locator("#caption-profile-editor summary").click()
    page.locator("#caption-profile-remember").uncheck()
    assert page.evaluate("(key) => localStorage.getItem(key)", KEY) is None
    expect(page.locator("#caption-timing")).to_have_value("longer")
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#idle-target-select")).to_have_value("en")
    expect(page.locator("#caption-timing")).to_have_value("current")


def test_forget_saved_profile_keeps_other_browser_data(page: Page, browser_harness) -> None:
    open_profile(page, browser_harness)
    page.evaluate("localStorage.setItem('unrelatedPreference', 'keep')")
    page.locator("#idle-target-select").select_option("fr")
    page.locator("#caption-timing").select_option("longer")
    page.locator("#caption-profile-remember").check()
    page.get_by_role("button", name="Forget saved profile", exact=True).click()
    assert page.evaluate("(key) => localStorage.getItem(key)", KEY) is None
    assert page.evaluate("localStorage.getItem('unrelatedPreference')") == "keep"
    expect(page.locator("#idle-target-select")).to_have_value("en")
    expect(page.locator("#caption-timing")).to_have_value("current")
    expect(page.locator("#caption-profile-remember")).not_to_be_checked()


def test_active_session_snapshot_wins_over_saved_choice(page: Page, browser_harness) -> None:
    open_profile(page, browser_harness)
    page.locator("#idle-target-select").select_option("fr")
    page.locator("#caption-timing").select_option("shorter")
    page.locator("#caption-profile-remember").check()
    browser_harness.configure("profiles_restored")
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#caption-profile-session-note")).to_contain_text("Longer pauses")
    expect(page.locator("#header-lang")).to_contain_text("English")
    saved = json.loads(page.evaluate("(key) => localStorage.getItem(key)", KEY))
    assert saved["targetLanguage"] == "fr" and saved["id"] == "shorter"


@pytest.mark.parametrize("bad", [
    {"version": 1, "targetLanguage": "fr", "id": "private-invalid-profile"},
    {"version": 1, "targetLanguage": "unsupported", "id": "longer"},
])
def test_invalid_saved_choices_are_ignored(page: Page, browser_harness, bad) -> None:
    open_profile(page, browser_harness)
    page.evaluate("([key, value]) => localStorage.setItem(key, value)", [KEY, json.dumps(bad)])
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#idle-target-select")).to_have_value("en")
    expect(page.locator("#caption-timing")).to_have_value("current")
    expect(page.locator("#caption-profile-remember")).not_to_be_checked()


def test_unavailable_storage_does_not_block_start(page: Page, browser_harness) -> None:
    open_profile(page, browser_harness)
    page.evaluate("() => { Storage.prototype.setItem = function () { throw new Error('storage blocked'); }; }")
    page.locator("#idle-target-select").select_option("fr")
    page.locator("#caption-timing").select_option("longer")
    page.locator("#caption-profile-remember").click()
    expect(page.locator("#caption-profile-remember")).not_to_be_checked()
    expect(page.locator("#caption-profile-help")).to_contain_text("Could not remember")
    page.get_by_role("button", name="Start", exact=True).click()
    assert browser_harness.wait_for_message("start")["caption_profile"] == "longer"
