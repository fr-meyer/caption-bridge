"""Browser contract for translation model selection and live acknowledgement."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from browser_tests.conftest import BrowserHarness

pytestmark = pytest.mark.browser


def test_select_before_start_and_change_live(
    page: Page, browser_harness: BrowserHarness
) -> None:
    browser_harness.configure("idle_ready")
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    browser_harness.wait_for_connections(1)

    idle_model = page.locator("#idle-model-select")
    expect(idle_model).to_have_value("zai-glm-5-3")
    idle_model.select_option("mistral-small-latest")
    page.get_by_role("button", name="Start", exact=True).click()
    assert browser_harness.wait_for_message("start")["translation_model"] == "mistral-small-latest"

    page.get_by_role("button", name="Settings").click()
    drawer_model = page.locator("#drawer-model-select")
    expect(drawer_model).to_have_value("mistral-small-latest")
    drawer_model.select_option("mistral-medium-latest")
    assert browser_harness.wait_for_message("set_translation_model")["model"] == "mistral-medium-latest"
    expect(drawer_model).to_have_value("mistral-medium-latest")


def test_thinking_setting_before_start_and_live(
    page: Page, browser_harness: BrowserHarness
) -> None:
    browser_harness.configure("idle_ready")
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    browser_harness.wait_for_connections(1)
    idle_thinking = page.locator("#idle-thinking-select")
    expect(idle_thinking).to_have_value("default")
    idle_thinking.select_option("high")
    page.get_by_role("button", name="Start", exact=True).click()
    start = browser_harness.wait_for_message("start")
    assert start["translation_model"] == "zai-glm-5-3"
    assert start["translation_reasoning_effort"] == "high"

    page.get_by_role("button", name="Settings").click()
    drawer_thinking = page.locator("#drawer-thinking-select")
    expect(drawer_thinking).to_have_value("high")
    drawer_thinking.select_option("default")
    message = browser_harness.wait_for_message("set_translation_model")
    assert message["model"] == "zai-glm-5-3"
    assert message["reasoning_effort"] == "default"
