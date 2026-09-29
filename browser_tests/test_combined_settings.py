"""A single session can use a timing profile and selected translation model and thinking level."""

from __future__ import annotations

import time

import pytest
from playwright.sync_api import Page

from browser_tests.conftest import BrowserHarness

pytestmark = pytest.mark.browser


def test_start_sends_both_settings(page: Page, browser_harness: BrowserHarness) -> None:
    browser_harness.configure("glossary_idle")
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    browser_harness.wait_for_connections(1)
    page.locator("#idle-model-select").select_option("mistral-medium-latest")
    page.locator("#idle-thinking-select").select_option("high")
    page.locator("#caption-profile-editor summary").click()
    page.locator("#caption-timing").select_option("shorter")
    page.get_by_role("button", name="Start", exact=True).click()
    message = browser_harness.wait_for_message("start")
    assert message["translation_model"] == "mistral-medium-latest"
    assert message["translation_reasoning_effort"] == "high"
    assert message["caption_profile"] == "shorter"


def test_fast_live_model_and_thinking_changes_keep_selected_model(
    page: Page, browser_harness: BrowserHarness
) -> None:
    browser_harness.configure("idle_ready")
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    browser_harness.wait_for_connections(1)
    page.locator("#idle-model-select").select_option("zai-glm-5-3")
    page.locator("#idle-thinking-select").select_option("high")
    page.get_by_role("button", name="Start", exact=True).click()
    browser_harness.wait_for_message("start")
    page.get_by_role("button", name="Settings").click()
    page.evaluate("""() => {
        const model = document.getElementById('drawer-model-select');
        model.value = 'mistral-small-latest';
        model.dispatchEvent(new Event('change', { bubbles: true }));
        const thinking = document.getElementById('drawer-thinking-select');
        thinking.value = 'default';
        thinking.dispatchEvent(new Event('change', { bubbles: true }));
    }""")
    deadline = time.monotonic() + 2
    while browser_harness.message_count("set_translation_model") < 2:
        assert time.monotonic() < deadline, "both live settings were not sent"
        time.sleep(0.01)
    with browser_harness._lock:
        changes = [m for m in browser_harness.messages
                   if m.get("type") == "set_translation_model"]
    assert [(m["model"], m["reasoning_effort"]) for m in changes] == [
        ("mistral-small-latest", "high"),
        ("mistral-small-latest", "default"),
    ]
