"""Real-browser contracts for critical Caption Bridge user states."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from browser_tests.conftest import BrowserHarness

pytestmark = pytest.mark.browser


def _open(page: Page, harness: BrowserHarness, scenario: str) -> None:
    assert harness.url.startswith("http://127.0.0.1:")
    harness.configure(scenario)
    page.goto(harness.url, wait_until="domcontentloaded")
    harness.wait_for_connections(1)


def test_degraded_captions_and_provider_notices(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness, "degraded")

    expect(page.locator("#status-label")).to_have_text("Session ended")
    expect(page.locator(".caption-entry")).to_have_count(2)
    expect(page.locator(".translation-unavailable")).to_have_count(2)
    expect(page.locator(".caption-source")).to_contain_text(
        ["Synthetic degraded source two.", "Synthetic degraded source one."]
    )
    expect(page.locator("#provider-notice")).to_be_visible()
    expect(page.locator("#provider-notice-title")).to_have_text(
        "Transcription unavailable"
    )
    expect(page.locator("#capacity-notice")).to_be_visible()
    expect(page.locator("#capacity-notice-detail")).to_contain_text(
        "Translation provider capacity is temporarily limited"
    )


def test_reconnect_snapshot_restores_state_and_relocks_audio(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness, "restored")

    expect(page.locator(".caption-entry[data-seq='1']")).to_have_count(1)
    expect(page.locator("#audio-enable-banner")).to_be_visible()
    page.locator("#enable-audio-btn").click()
    browser_harness.wait_for_message("tts_audio_enabled")
    expect(page.locator("#audio-enable-banner")).to_be_hidden()

    page.reload(wait_until="domcontentloaded")
    browser_harness.wait_for_connections(2)
    expect(page.locator(".caption-entry[data-seq='1']")).to_have_count(1)
    expect(page.locator("#audio-enable-banner")).to_be_visible()
    page.wait_for_timeout(100)
    assert browser_harness.message_count("tts_audio_enabled") == 1



def test_captions_only_preference_survives_start_and_reload(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness, "idle_ready")
    choice = page.locator("#captions-only-idle")
    expect(choice).not_to_be_checked()
    choice.check()
    expect(choice).to_be_checked()
    page.get_by_role("button", name="Start", exact=True).click()
    assert browser_harness.wait_for_message("start")["tts_muted"] is True
    expect(page.locator("#audio-enable-banner")).to_be_hidden()

    browser_harness.configure("restored")
    page.reload(wait_until="domcontentloaded")
    browser_harness.wait_for_connections(1)
    expect(page.locator("#audio-enable-banner")).to_be_hidden()
    page.get_by_role("button", name="Settings").click()
    drawer_choice = page.locator("#captions-only-drawer")
    expect(drawer_choice).to_be_checked()
    drawer_choice.uncheck()
    expect(page.locator("#audio-enable-banner")).to_be_visible()

    browser_harness.configure("restored")
    page.reload(wait_until="domcontentloaded")
    browser_harness.wait_for_connections(1)
    expect(page.locator("#audio-enable-banner")).to_be_visible()
    page.get_by_role("button", name="Settings").click()
    expect(page.locator("#captions-only-drawer")).not_to_be_checked()


def test_captions_only_preference_survives_new_session(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness, "idle_ready")
    page.locator("#captions-only-idle").check()
    browser_harness.configure("export")
    page.reload(wait_until="domcontentloaded")
    browser_harness.wait_for_connections(1)
    expect(page.locator(".replay-btn")).to_be_disabled()
    page.get_by_role("button", name="New Session").click()
    page.get_by_role("button", name="Discard & start new").click()
    assert browser_harness.wait_for_message("new_session")["tts_muted"] is True
    expect(page.locator("#captions-only-idle")).to_be_checked()

def test_export_and_new_session_controls(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness, "export")

    expect(page.locator("#export-warning")).to_be_visible()
    page.get_by_role("button", name="Export", exact=True).click()
    browser_harness.wait_for_message("export")
    expect(page.locator("#export-confirm")).to_have_text(
        "Saved to synthetic/export"
    )

    page.get_by_role("button", name="New Session").click()
    browser_harness.wait_for_message("new_session")
    expect(page.locator("#status-label")).to_have_text("Ready")


def test_keyboard_reachability_and_lifecycle_shortcuts(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness, "idle_ready")
    expect(page.locator("#status-label")).to_have_text("Ready")

    for _ in range(12):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement && document.activeElement.id") == "start-btn":
            break
    assert page.evaluate("document.activeElement && document.activeElement.id") == "start-btn"

    page.keyboard.press("Enter")
    start_message = browser_harness.wait_for_message("start")
    assert start_message["target_language"] == "en"
    expect(page.locator("#status-label")).to_have_text("Listening")

    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Space")
    browser_harness.wait_for_message("stop")
    expect(page.locator("#status-label")).to_have_text("Session ended")


def test_discard_dialog_keeps_keyboard_focus_and_restores_trigger(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness, "export")

    page.get_by_role("button", name="New Session").click()
    dialog = page.get_by_role("dialog", name="Discard session?")
    expect(dialog).to_be_visible()
    expect(page.locator("#cancel-discard")).to_be_focused()

    page.keyboard.press("Shift+Tab")
    expect(page.locator("#confirm-discard")).to_be_focused()
    page.keyboard.press("Tab")
    expect(page.locator("#cancel-discard")).to_be_focused()

    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(page.get_by_role("button", name="New Session")).to_be_focused()


def test_export_failure_dialog_confines_focus(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness, "export_failure")

    dialog = page.get_by_role("dialog", name="Transcript not saved")
    expect(dialog).to_be_visible()
    expect(page.locator("#retry-export-btn")).to_be_focused()

    page.keyboard.press("Shift+Tab")
    expect(page.locator("#discard-export-btn")).to_be_focused()
    page.keyboard.press("Tab")
    expect(page.locator("#retry-export-btn")).to_be_focused()

    page.keyboard.press("Enter")
    browser_harness.wait_for_message("export")
    expect(dialog).to_be_hidden()
    expect(page.locator("#status-label")).to_be_focused()


def test_settings_drawer_is_unreachable_while_closed_and_returns_focus(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness, "restored")

    drawer = page.locator("#settings-drawer")
    gear = page.get_by_role("button", name="Settings", exact=True)
    expect(drawer).to_have_attribute("aria-hidden", "true")
    expect(gear).to_have_attribute("aria-expanded", "false")

    gear.click()
    expect(drawer).to_have_attribute("aria-hidden", "false")
    expect(drawer).to_have_attribute("role", "region")
    expect(gear).to_have_attribute("aria-expanded", "true")
    expect(page.locator("#drawer-close")).to_be_focused()

    page.keyboard.press("Escape")
    expect(drawer).to_have_attribute("aria-hidden", "true")
    expect(gear).to_have_attribute("aria-expanded", "false")
    expect(gear).to_be_focused()
    assert page.evaluate("document.querySelector('#settings-drawer').inert")
