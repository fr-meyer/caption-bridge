"""A dead server must not leave a green Listening label or an enabled Start button."""

import pytest
from playwright.sync_api import expect

from browser_tests.conftest import _snapshot

pytestmark = pytest.mark.browser

SOCKET = """(() => {
    window.syntheticSockets = []; window.sentCommands = [];
    class Socket {
        static OPEN = 1;
        constructor() { this.readyState = 0; syntheticSockets.push(this); }
        send(data) { sentCommands.push(JSON.parse(data)); }
        open() { this.readyState = 1; this.onopen(); }
        emit(data) { this.onmessage({data: JSON.stringify(data)}); }
        close() { this.readyState = 3; this.onclose(); }
    }
    window.WebSocket = Socket;
})();"""


@pytest.mark.parametrize("scenario", ["restored", "idle_ready"])
def test_disconnect_is_visible_until_fresh_snapshot_without_automatic_start(
    page, browser_harness, scenario,
):
    page.add_init_script(SOCKET)
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    expect(page.locator("#start-btn")).to_be_disabled()
    page.evaluate("syntheticSockets[0].open()")
    page.evaluate("data => syntheticSockets[0].emit(data)", _snapshot(scenario))
    expected = "Listening" if scenario == "restored" else "Ready"
    expect(page.locator("#status-label")).to_have_text(expected)

    page.evaluate("syntheticSockets[0].close()")
    expect(page.locator("#status-label")).to_have_text("Connection lost · reconnecting…")
    expect(page.locator("#status-dot")).not_to_have_class("status-dot green")
    expect(page.locator("#start-btn")).to_be_disabled()
    if scenario == "restored":
        expect(page.locator(".caption-entry")).to_have_count(1)
    page.wait_for_function("syntheticSockets.length === 2")
    page.evaluate("syntheticSockets[1].open()")
    expect(page.locator("#status-label")).to_have_text("Connection lost · reconnecting…")
    # A retired socket cannot supply the authoritative recovery snapshot.
    page.evaluate("data => syntheticSockets[0].emit(data)", _snapshot("idle_ready"))
    expect(page.locator("#status-label")).to_have_text("Connection lost · reconnecting…")
    page.keyboard.press("Space")
    assert page.evaluate("sentCommands.filter(x => x.type === 'start').length") == 0

    page.evaluate("data => syntheticSockets[1].emit(data)", _snapshot(scenario))
    expect(page.locator("#status-label")).to_have_text(expected)
    assert page.evaluate("sentCommands.filter(x => ['start','tts_audio_enabled'].includes(x.type)).length") == 0
    if scenario == "idle_ready":
        expect(page.locator("#start-btn")).to_be_enabled()
        page.locator("#start-btn").click()
        assert page.evaluate("sentCommands.filter(x => x.type === 'start').length") == 1


def test_initial_connection_waits_for_authoritative_session_snapshot(page, browser_harness):
    page.add_init_script(SOCKET)
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    expect(page.locator("#status-label")).to_have_text("Connecting…")
    expect(page.locator("#start-btn")).to_be_disabled()
    page.evaluate("syntheticSockets[0].open()")
    expect(page.locator("#status-label")).to_have_text("Connecting…")
    expect(page.locator("#start-btn")).to_be_disabled()
    page.evaluate("data => syntheticSockets[0].emit(data)", _snapshot("idle_ready"))
    expect(page.locator("#status-label")).to_have_text("Ready")
    expect(page.locator("#start-btn")).to_be_enabled()
    assert page.evaluate("sentCommands.filter(x => x.type === 'start').length") == 0


def test_provider_reconnect_remains_distinct_from_page_connection_loss(page, browser_harness):
    page.add_init_script(SOCKET)
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    page.evaluate("syntheticSockets[0].open()")
    page.evaluate("data => syntheticSockets[0].emit(data)", _snapshot("restored"))
    page.evaluate("syntheticSockets[0].emit({type:'status',status:'reconnecting'})")
    expect(page.locator("#status-label")).to_have_text("Reconnecting…")
    page.evaluate("syntheticSockets[0].close()")
    expect(page.locator("#status-label")).to_have_text("Connection lost · reconnecting…")
