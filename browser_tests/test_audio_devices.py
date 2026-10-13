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
    start = browser_harness.wait_for_message("start")
    assert start["translation_model"] == "mistral-medium-latest"
    assert start["translation_reasoning_effort"] == "default"
    assert start["caption_profile"] == "current"
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


_SHARED_PCM_CONTEXT = """
window.__contexts = []; window.__nodes = [];
window.__outputs = [{kind:'audiooutput', deviceId:'sink', label:'Synthetic output'}];
const NativeWebSocket = window.WebSocket;
window.WebSocket = class extends NativeWebSocket {
    constructor(...args) { super(...args); window.__socket = this; }
};
window.__emit = msg => window.__socket.dispatchEvent(
    new MessageEvent('message', {data:JSON.stringify(msg)}));
window.AudioContext = class {
    constructor() {
        this.currentTime = 0; this.destination = {context:this}; this.sinkId = '';
        window.__contexts.push(this);
    }
    setSinkId(id) { this.sinkId = id; return Promise.resolve(); }
    resume() { return Promise.resolve(); }
    createBuffer(_channels, length) {
        const samples = new Float32Array(length);
        return {getChannelData:()=>samples, length};
    }
    createBufferSource() {
        const node = {context:this, connect(destination) {this.destination=destination;},
            start() {this.started=true;}, stop() {this.stopped=true;}};
        window.__nodes.push(node); return node;
    }
};
Object.defineProperty(navigator, 'mediaDevices', {value:{
    enumerateDevices:async ()=>window.__outputs,
    addEventListener(_type, callback) {window.__devicechange=callback;},
    getUserMedia() {throw new Error('Browser capture forbidden');},
}});
"""


def _emit(page, event):
    page.evaluate("msg => window.__emit(msg)", event)


def _pcm_clip(page, clip_id, epoch, *, last=True):
    _emit(page, {"type": "tts_speaking", "seq": 1, "clip_id": clip_id, "tts_epoch": epoch})
    _emit(page, {"type": "tts_audio", "seq": 1, "clip_id": clip_id, "tts_epoch": epoch,
                 "chunk_index": 0, "is_last": last, "data": "AAAA" * 4800})


@pytest.mark.parametrize("streaming", [False, True])
def test_selected_sink_routes_pcm_replay_and_removal_cancels_every_source(
    page: Page, browser_harness: BrowserHarness, streaming: bool,
):
    browser_harness.configure("restored")
    browser_harness._settings["tts_streaming_playback"] = streaming
    page.add_init_script(_SHARED_PCM_CONTEXT)
    page.goto(browser_harness.url, wait_until="domcontentloaded")
    expect(page.locator(".caption-entry")).to_have_count(1)
    page.locator("#enable-audio-btn").click()
    browser_harness.wait_for_message("tts_audio_enabled")
    page.get_by_role("button", name="Settings", exact=True).click()
    page.locator("#drawer-output-device").select_option("sink")
    expect(page.locator("[data-audio-device-status]").last).to_contain_text("Synthetic output")
    page.get_by_role("button", name="Close settings").click()
    _emit(page, {"type": "tts_queue", "tts_epoch": 0, "pending_count": 1})
    _pcm_clip(page, 101, 0, last=not streaming)
    page.wait_for_function("window.__nodes.length===1 && window.__nodes[0].started")
    if streaming:
        _emit(page, {"type": "tts_audio", "seq": 1, "clip_id": 101, "tts_epoch": 0,
                     "chunk_index": 1, "is_last": True, "data": "AAAA" * 4800})
        page.wait_for_function("window.__nodes.length===2")
    assert page.evaluate("__contexts.length") == 1
    assert page.evaluate("__nodes.every(n=>n.context===__contexts[0] && n.destination===__contexts[0].destination)")
    assert page.evaluate("__contexts[0].sinkId") == "sink"
    starts = [m for m in browser_harness.messages if m.get("type") == "tts_playback_start"]
    assert [(m["clip_id"], m["tts_epoch"]) for m in starts] == [(101, 0)]

    before_removal = len(browser_harness.messages)
    page.evaluate("__outputs=[]; __devicechange()")
    page.wait_for_function("__nodes.every(n=>n.stopped)")
    assert browser_harness.wait_for_message("tts_mute", after=before_removal)["muted"] is True
    expect(page.locator(".caption-entry")).to_have_count(1)
    assert browser_harness.message_count("tts_playback_complete") == 0

    page.get_by_role("button", name="Settings", exact=True).click()
    page.locator("#drawer-output-device").select_option("")
    expect(page.locator("[data-audio-device-status]").last).to_contain_text("System/browser default")
    page.get_by_role("button", name="Close settings").click()
    page.locator("#tts-toggle-btn").click()
    page.get_by_role("button", name="Catch up", exact=True).click()
    browser_harness.wait_for_message("tts_catch_up")
    expect(page.locator("#catch-up-notice")).to_contain_text("All captions kept")
    count = page.evaluate("__nodes.length")
    _pcm_clip(page, 102, 0)  # Removed route cannot revive cancelled epoch audio.
    assert page.evaluate("__nodes.length") == count
    page.locator(".replay-btn").click()
    assert browser_harness.wait_for_message("tts_replay")["seq"] == 1
    _pcm_clip(page, 103, 1)
    page.wait_for_function(f"__nodes.length==={count + 1}")
    assert page.evaluate("__contexts.length===1 && __contexts[0].sinkId===''")
    page.evaluate("__nodes.at(-1).onended()")
    complete = browser_harness.wait_for_message("tts_playback_complete")
    assert (complete["clip_id"], complete["tts_epoch"], complete["seq"]) == (103, 1, 1)
