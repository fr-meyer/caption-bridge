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
    expect(idle_model).to_have_value("mistral-medium-latest")
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
    assert start["translation_model"] == "mistral-medium-latest"
    assert start["translation_reasoning_effort"] == "high"

    page.get_by_role("button", name="Settings").click()
    drawer_thinking = page.locator("#drawer-thinking-select")
    expect(drawer_thinking).to_have_value("high")
    drawer_thinking.select_option("default")
    message = browser_harness.wait_for_message("set_translation_model")
    assert message["model"] == "mistral-medium-latest"
    assert message["reasoning_effort"] == "default"


@pytest.mark.parametrize("scenario,expected", [
    ("idle_ready", "mistral-medium-latest"),
    ("model_override", "mistral-small-latest"),
])
def test_startup_override_live_choice_refresh_and_new_session(
    page: Page, browser_harness: BrowserHarness, scenario: str, expected: str,
) -> None:
    browser_harness.configure(scenario)
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    browser_harness.wait_for_connections(1)
    expect(page.locator("#idle-model-select")).to_have_value(expected)
    expect(page.locator("#idle-model-help")).to_be_hidden()
    page.get_by_role("button", name="Start", exact=True).click()
    assert browser_harness.wait_for_message("start")["translation_model"] == expected
    expect(page.locator("#translation-model-status")).to_be_visible()

    page.get_by_role("button", name="Settings").click()
    page.locator("#drawer-model-select").select_option("zai-glm-5-3")
    browser_harness.wait_for_message("set_translation_model")
    expect(page.locator("#translation-model-status")).to_contain_text("GLM 5.3 (experimental")
    expect(page.locator("#drawer-model-help")).to_contain_text("may miss or delay captions")
    page.reload(wait_until="domcontentloaded")
    browser_harness.wait_for_connections(2)
    expect(page.locator("#translation-model-status")).to_contain_text("GLM 5.3 (experimental")
    page.get_by_role("button", name="Settings").click()
    expect(page.locator("#drawer-model-select")).to_have_value("zai-glm-5-3")
    page.get_by_role("button", name="Close settings").click()
    page.get_by_role("button", name="Stop", exact=True).click()
    browser_harness.wait_for_message("stop")
    page.get_by_role("button", name="New Session", exact=True).click()
    page.get_by_role("button", name="Discard & start new").click()
    browser_harness.wait_for_message("new_session")
    expect(page.locator("#idle-model-select")).to_have_value(expected)
    expect(page.locator("#translation-model-status")).to_be_hidden()
    expect(page.locator("#idle-model-help")).to_be_hidden()


def test_explicit_glm_before_start_shows_reliability_note(
    page: Page, browser_harness: BrowserHarness,
) -> None:
    browser_harness.configure("idle_ready")
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    browser_harness.wait_for_connections(1)
    page.locator("#idle-model-select").select_option("zai-glm-5-3")
    expect(page.locator("#idle-model-help")).to_be_visible()
    expect(page.locator("#idle-model-help")).to_contain_text("Experimental")
    page.get_by_role("button", name="Start", exact=True).click()
    assert browser_harness.wait_for_message("start")["translation_model"] == "zai-glm-5-3"
    expect(page.locator("#translation-model-status")).to_contain_text("GLM 5.3")



def test_large4_preview_selection_live_ack_refresh_and_medium_new_session(
    page: Page, browser_harness: BrowserHarness,
) -> None:
    browser_harness.configure("idle_ready")
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    browser_harness.wait_for_connections(1)
    idle = page.locator("#idle-model-select")
    expect(idle).to_have_value("mistral-medium-latest")
    expect(idle.locator("option[value='mistral-large-4']")).to_have_text("Mistral Large 4")
    page.locator("#idle-thinking-select").select_option("high")
    idle.select_option("mistral-large-4")
    expect(page.locator("#idle-thinking-select")).to_have_value("default")
    expect(page.locator("#idle-thinking-select option[value='high']")).to_be_disabled()
    page.get_by_role("button", name="Start", exact=True).click()
    start = browser_harness.wait_for_message("start")
    assert start["translation_model"] == "mistral-large-4"
    assert start["translation_reasoning_effort"] == "default"
    expect(page.locator("#translation-model-status")).to_contain_text("Large 4")
    page.get_by_role("button", name="Settings").click()
    drawer = page.locator("#drawer-model-select")
    drawer.select_option("mistral-medium-latest")
    expect(page.locator("#translation-model-status")).to_contain_text("Medium (latest)")
    page.locator("#drawer-thinking-select").select_option("high")
    expect(page.locator("#drawer-thinking-select")).to_have_value("high")
    drawer.select_option("mistral-large-4")
    expect(page.locator("#translation-model-status")).to_contain_text("Large 4")
    expect(page.locator("#drawer-thinking-select")).to_have_value("default")
    changes = [m for m in browser_harness.messages if m.get("type") == "set_translation_model"]
    assert [(m["model"], m["reasoning_effort"]) for m in changes] == [
        ("mistral-medium-latest", "default"),
        ("mistral-medium-latest", "high"),
        ("mistral-large-4", "default"),
    ]
    page.reload(wait_until="domcontentloaded")
    browser_harness.wait_for_connections(2)
    expect(page.locator("#translation-model-status")).to_contain_text("Large 4")
    page.get_by_role("button", name="Stop", exact=True).click()
    browser_harness.wait_for_message("stop")
    page.get_by_role("button", name="New Session", exact=True).click()
    page.get_by_role("button", name="Discard & start new").click()
    browser_harness.wait_for_message("new_session")
    expect(page.locator("#idle-model-select")).to_have_value("mistral-medium-latest")
