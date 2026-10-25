"""Bounded Chrome checks of production UI against synthetic WS state only."""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from browser_tests.conftest import _snapshot

pytestmark = pytest.mark.browser


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    return {**browser_type_launch_args, "channel": "chrome", "chromium_sandbox": True}


def diagnostics(state, *, active=True, reason="none"):
    return {"capture": {"active": active}, "asr": {"state": state, "reason": reason}}


def test_connecting_is_visible_before_real_readiness_and_stop_stays_enabled(page, browser_harness):
    messages, sockets = [], []
    snapshot = _snapshot("idle_ready")
    snapshot["pipeline_diagnostics"] = diagnostics("idle", active=False)
    def connect(route):
        sockets.append(route)
        route.send(json.dumps(snapshot))
        def receive(raw):
            message = json.loads(raw)
            messages.append(message)
            if message["type"] == "start":
                route.send(json.dumps({"type": "asr_state", **diagnostics("connecting")}))
                route.send(json.dumps({"type": "status", "status": "listening", "started_at": "2026-01-01T00:00:00Z"}))
            elif message["type"] == "stop":
                route.send(json.dumps({"type": "asr_state", **diagnostics("stopped", active=False, reason="user_stop")}))
                route.send(json.dumps({"type": "status", "status": "session_ended"}))
        route.on_message(receive)
    page.add_init_script("window.captureCalls=0; navigator.mediaDevices.getUserMedia=()=>{window.captureCalls++;throw Error('unexpected capture');};")
    page.route_web_socket("**/ws", connect)
    page.goto(browser_harness.url)
    expect(page.locator("#start-btn")).to_be_enabled()
    page.locator("#captions-only-idle").check()
    page.locator("#start-btn").click()
    expect(page.locator("#status-label")).to_have_text("Connecting transcription…")
    expect(page.locator("#asr-notice")).to_contain_text("Microphone active · connecting")
    expect(page.locator("#stop-btn")).to_be_enabled()
    expect(page.locator("#status-dot")).not_to_have_class("status-dot green")
    sockets[-1].send(json.dumps({"type": "asr_state", **diagnostics("ready")}))
    expect(page.locator("#status-label")).to_have_text("Listening · transcription ready")
    expect(page.locator("#asr-notice")).to_have_text("Microphone active · transcription ready.")
    sockets[-1].send(json.dumps({"type": "asr_state", **diagnostics("draining", active=False)}))
    expect(page.locator("#status-label")).to_have_text("Finishing transcription…")
    expect(page.locator("#asr-notice")).to_contain_text("Microphone stopped")
    expect(page.locator("#stop-btn")).to_be_enabled()
    sockets[-1].send(json.dumps({"type": "asr_state", **diagnostics("stopped", active=False, reason="input_finished")}))
    expect(page.locator("#status-label")).to_have_text("Input finished · completing captions")
    expect(page.locator("#asr-notice")).to_contain_text("Microphone stopped · input finished")
    page.locator("#stop-btn").click()
    expect(page.locator("#status-label")).to_have_text("Session ended")
    assert [m["type"] for m in messages].count("start") == 1
    assert [m["type"] for m in messages].count("stop") == 1
    assert page.evaluate("window.captureCalls") == 0


def test_failed_snapshot_survives_reload_with_manual_recovery_and_stopped_capture(page, browser_harness):
    snapshot = _snapshot("idle_ready")
    snapshot.update(status="session_ended", started_at="2026-01-01T00:00:00Z", ended_at="2026-01-01T00:00:10Z",
                    pipeline_diagnostics=diagnostics("failed", active=False, reason="initial_timeout"))
    def connect(route):
        route.send(json.dumps(snapshot))
    page.route_web_socket("**/ws", connect)
    page.goto(browser_harness.url)
    expect(page.locator("#asr-notice")).to_contain_text("startup deadline")
    expect(page.locator("#asr-notice")).to_contain_text("Microphone capture stopped")
    expect(page.locator("#asr-notice")).to_contain_text("retry manually")
    expect(page.locator("#status-label")).to_have_text("Transcription failed · session ended")
    page.reload()
    expect(page.locator("#asr-notice")).to_contain_text("Microphone capture stopped")
    expect(page.locator("#status-label")).to_have_text("Transcription failed · session ended")


def test_provider_retry_notices_preserve_captions_and_distinguish_recovery_from_browser_loss(page, browser_harness):
    sockets = []
    snapshot = _snapshot("restored")
    snapshot["pipeline_diagnostics"] = diagnostics("ready")

    def connect(route):
        sockets.append(route)
        route.send(json.dumps(snapshot))

    page.add_init_script("""window.mediaCalls=0;
        navigator.mediaDevices.getUserMedia=()=>{mediaCalls++;throw Error('unexpected media');};
        window.AudioContext=window.webkitAudioContext=function(){mediaCalls++;throw Error('unexpected media');};
    """)
    page.route_web_socket("**/ws", connect)
    page.goto(browser_harness.url)
    expect(page.locator("#asr-notice")).to_have_text("Microphone active · transcription ready.")
    expect(page.locator(".caption-entry")).to_have_count(1)
    # A quiet/pending-caption interval does not itself announce an outage.
    sockets[-1].send(json.dumps({"type": "source_partial", "text": "Synthetic pending phrase"}))
    expect(page.locator("#asr-notice")).to_have_text("Microphone active · transcription ready.")
    sockets[-1].send(json.dumps({"type": "asr_state", **diagnostics("failed", active=False, reason="provider_error")}))
    sockets[-1].send(json.dumps({"type": "status", "status": "reconnecting"}))
    sockets[-1].send(json.dumps({"type": "provider_temporarily_unavailable", "service": "transcription", "outcome": "retrying"}))
    expect(page.locator("#asr-notice")).to_contain_text("Microphone stopped · transcription interrupted; reconnecting automatically")
    expect(page.locator("#asr-notice")).not_to_contain_text("retry manually")
    expect(page.locator("#stop-btn")).to_be_enabled()
    expect(page.locator(".caption-entry")).to_have_count(1)
    sockets[-1].send(json.dumps({"type": "asr_state", **diagnostics("ready")}))
    expect(page.locator("#asr-notice")).to_contain_text("verifying recovery")
    sockets[-1].send(json.dumps({"type": "status", "status": "listening"}))
    sockets[-1].send(json.dumps({"type": "recovered", "service": "transcription", "attempts": 1, "downtime_ms": 30}))
    expect(page.locator("#asr-notice")).to_have_text("Microphone active · transcription ready.")
    expect(page.locator(".caption-entry")).to_have_count(1)
    sockets[-1].send(json.dumps({"type": "asr_state", **diagnostics("failed", active=False, reason="provider_error")}))
    sockets[-1].send(json.dumps({"type": "status", "status": "reconnecting"}))
    sockets[-1].send(json.dumps({"type": "provider_temporarily_unavailable", "service": "transcription", "outcome": "exhausted", "attempts": 2}))
    sockets[-1].send(json.dumps({"type": "status", "status": "session_ended"}))
    expect(page.locator("#asr-notice")).to_contain_text("retry manually")
    expect(page.locator("#status-label")).to_have_text("Transcription failed · session ended")
    assert page.evaluate("mediaCalls") == 0
