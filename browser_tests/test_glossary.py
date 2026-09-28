"""Synthetic browser contracts for explicit terminology choices."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from browser_tests.conftest import BrowserHarness

pytestmark = pytest.mark.browser
KEY = "captionBridge.glossary"
TEXT = "통계적 유의성 => statistical significance"


def open_editor(page: Page, harness: BrowserHarness) -> None:
    harness.configure("glossary_idle")
    page.goto(harness.url, wait_until="domcontentloaded")
    harness.wait_for_connections(1)
    page.locator("#glossary-editor summary").click()


def test_terms_are_saved_only_after_explicit_opt_in(page: Page, browser_harness) -> None:
    open_editor(page, browser_harness)
    expect(page.locator("#glossary-remember")).not_to_be_checked()
    page.locator("#glossary-terms").fill(TEXT)
    assert page.evaluate("(key) => localStorage.getItem(key)", KEY) is None
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#glossary-terms")).to_have_value("")
    page.locator("#glossary-editor summary").click()
    page.locator("#glossary-terms").fill(TEXT)
    page.locator("#glossary-remember").check()
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#glossary-terms")).to_have_value(TEXT)
    page.locator("#glossary-editor summary").click()
    page.locator("#glossary-remember").uncheck()
    assert page.evaluate("(key) => localStorage.getItem(key)", KEY) is None
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#glossary-terms")).to_have_value("")


def test_invalid_terms_block_start_and_valid_terms_stay_text(page: Page, browser_harness) -> None:
    open_editor(page, browser_harness)
    page.locator("#glossary-terms").fill("missing separator")
    page.get_by_role("button", name="Start", exact=True).click()
    expect(page.locator("#glossary-error")).to_be_visible()
    assert browser_harness.message_count("start") == 0
    page.locator("#glossary-terms").fill('term => <img src=x onerror="window.glossaryXss=1">')
    page.get_by_role("button", name="Start", exact=True).click()
    message = browser_harness.wait_for_message("start")
    assert message["glossary"][0]["preferred"].startswith("<img")
    expect(page.locator("#glossary-editor img")).to_have_count(0)
    assert page.evaluate("window.glossaryXss") is None
    expect(page.locator("#glossary-session-note")).to_be_visible()


def test_target_change_uses_its_own_draft_and_clear_removes_saved_copy(page: Page, browser_harness) -> None:
    open_editor(page, browser_harness)
    page.locator("#glossary-terms").fill(TEXT)
    page.locator("#glossary-remember").check()
    page.locator("#idle-target-select").select_option("fr")
    expect(page.locator("#glossary-terms")).to_have_value("")
    page.get_by_role("button", name="Start", exact=True).click()
    message = browser_harness.wait_for_message("start")
    assert message["target_language"] == "fr"
    assert message["glossary"] == []
    browser_harness.configure("glossary_idle")
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#glossary-terms")).to_have_value(TEXT)
    page.locator("#glossary-editor summary").click()
    page.locator("#glossary-clear").click()
    expect(page.locator("#glossary-terms")).to_have_value("")
    assert page.evaluate("(key) => localStorage.getItem(key)", KEY) is None
