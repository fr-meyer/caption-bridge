"""DOM contracts use synthetic native inventory and fake browser audio APIs only."""

import pytest
from playwright.sync_api import Page, expect

from browser_tests.conftest import BrowserHarness

pytestmark = pytest.mark.browser


def test_native_selection_start_lock_refresh_and_new_session(page: Page, browser_harness: BrowserHarness):
    browser_harness.configure("audio_devices")
    page.add_init_script("""
        window.AudioContext = class {
            setSinkId(id) { return Promise.resolve(); }
            resume() { return Promise.resolve(); }
        };
        Object.defineProperty(navigator, 'mediaDevices', {value: {
            enumerateDevices: async () => [{kind: 'audiooutput', deviceId: 'sink', label: 'Synthetic output'}],
            addEventListener() {},
            getUserMedia() { throw new Error('Browser capture forbidden'); },
        }});
    """)
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    browser_harness.wait_for_connections(1)
    selector = page.locator("#idle-input-device")
    expect(selector).to_be_enabled()
    selector.select_option("native-b")
    page.locator("#idle-output-device").select_option("sink")
    expect(page.locator("[data-audio-device-status]").first).to_contain_text("Synthetic output")
    page.get_by_role("button", name="Start", exact=True).click()
    assert browser_harness.wait_for_message("start")["input_device"] == "native-b"
    expect(selector).to_be_disabled()
    page.reload(wait_until="domcontentloaded")
    browser_harness.wait_for_connections(2)
    page.get_by_role("button", name="Settings", exact=True).click()
    expect(page.locator("#drawer-input-device")).to_have_value("native-b")
    expect(page.locator("#drawer-input-device")).to_be_disabled()
    expect(page.locator("#drawer-output-device")).to_have_value("")
    expect(page.locator("[data-audio-device-status]").last).to_contain_text("Capture input: Synthetic input B")
    page.get_by_role("button", name="Close settings").click()
    page.get_by_role("button", name="Stop", exact=True).click()
    page.get_by_role("button", name="New Session", exact=True).click()
    page.get_by_role("button", name="Discard & start new").click()
    browser_harness.wait_for_message("new_session")
    expect(selector).to_be_enabled()
    expect(selector).to_have_value("default")


def test_unsupported_output_has_explicit_default_guidance(page: Page, browser_harness: BrowserHarness):
    browser_harness.configure("audio_devices")
    page.add_init_script("""
        window.AudioContext = class {};
        Object.defineProperty(navigator, 'mediaDevices', {value: {
            enumerateDevices: async () => [], addEventListener() {},
            getUserMedia() { throw new Error('Browser capture forbidden'); },
        }});
    """)
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    expect(page.locator("#idle-output-device")).to_be_disabled()
    expect(page.locator("[data-audio-device-status]").first).to_contain_text("cannot select an output here")
    expect(page.locator("[data-choose-audio-output]").first).to_be_hidden()
