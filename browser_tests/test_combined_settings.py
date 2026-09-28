"""A single session can use a timing profile and selected translation model."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from browser_tests.conftest import BrowserHarness

pytestmark = pytest.mark.browser


def test_start_sends_both_settings(page: Page, browser_harness: BrowserHarness) -> None:
    browser_harness.configure("glossary_idle")
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    browser_harness.wait_for_connections(1)
    page.locator("#idle-model-select").select_option("mistral-medium-latest")
    page.locator("#caption-profile-editor summary").click()
    page.locator("#caption-timing").select_option("shorter")
    page.get_by_role("button", name="Start", exact=True).click()
    message = browser_harness.wait_for_message("start")
    assert message["translation_model"] == "mistral-medium-latest"
    assert message["caption_profile"] == "shorter"
