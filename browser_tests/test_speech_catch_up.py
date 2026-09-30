"""Production frontend with fake Web Audio: no audio device or provider is used."""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from browser_tests.conftest import BrowserHarness

pytestmark = pytest.mark.browser

_FAKE_AUDIO = """
window.__nodes = [];
window.__resumeResolvers = [];
const NativeWebSocket = window.WebSocket;
window.WebSocket = class extends NativeWebSocket {
    constructor(...args) { super(...args); window.__socket = this; }
};
window.__emit = msg => window.__socket.dispatchEvent(
    new MessageEvent("message", {data: JSON.stringify(msg)}));
window.AudioContext = class {
    resume() {
        return window.__deferResume
            ? new Promise(resolve => window.__resumeResolvers.push(resolve))
            : Promise.resolve();
    }
    createBuffer(_channels, length) {
        const samples = new Float32Array(length);
        return {getChannelData: () => samples};
    }
    createBufferSource() {
        const node = {connect() {}, start() {this.started = true;},
            stop() {this.stopped = true;}};
        window.__nodes.push(node);
        return node;
    }
};
"""


def _open(page: Page, harness: BrowserHarness) -> None:
    page.add_init_script(_FAKE_AUDIO)
    harness.configure("restored")
    page.goto(harness.url, wait_until="domcontentloaded")
    expect(page.locator(".caption-entry")).to_have_count(1)


def _emit(page: Page, event: dict) -> None:
    page.evaluate("msg => window.__emit(msg)", event)


def _clip(page: Page, seq: int, epoch: int) -> None:
    _emit(page, {"type": "tts_speaking", "seq": seq, "tts_epoch": epoch})
    _emit(page, {"type": "tts_audio", "seq": seq, "tts_epoch": epoch,
                 "is_last": True, "data": "AAAAAA=="})  # One silent float32 sample.


def test_catch_up_stops_current_and_queued_speech_keeps_caption_and_replay(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness)
    page.locator("#enable-audio-btn").click()
    browser_harness.wait_for_message("tts_audio_enabled")
    _emit(page, {"type": "tts_queue", "tts_epoch": 0, "pending_count": 3})
    _clip(page, 1, 0)
    page.wait_for_function("window.__nodes.length === 1 && window.__nodes[0].started")
    _clip(page, 2, 0)
    expect(page.locator("#speech-backlog-status")).to_contain_text("3 clip(s) pending")
    control = page.get_by_role("button", name="Catch up", exact=True)
    control.focus()
    page.keyboard.press("Enter")
    assert browser_harness.wait_for_message("tts_catch_up")["tts_epoch"] == 0
    expect(page.locator("#catch-up-notice")).to_contain_text("All captions kept and replayable")
    assert page.evaluate("window.__nodes[0].stopped") is True
    _clip(page, 3, 0)  # Late chunks/speaking from the cancelled epoch.
    assert page.evaluate("window.__nodes.length") == 1
    expect(page.locator(".caption-entry")).to_have_count(1)
    page.locator(".replay-btn").click()
    assert browser_harness.wait_for_message("tts_replay")["seq"] == 1
    _emit(page, {"type": "tts_queue", "tts_epoch": 1, "pending_count": 1})
    _clip(page, 1, 1)
    page.wait_for_function("window.__nodes.length === 2 && window.__nodes[1].started")
    page.evaluate("window.__nodes[1].onended()")
    assert browser_harness.wait_for_message("tts_playback_complete")["tts_epoch"] == 1


def test_catch_up_invalidates_pending_resume_and_refresh_relocks_audio(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness)
    page.locator("#enable-audio-btn").click()
    browser_harness.wait_for_message("tts_audio_enabled")
    page.evaluate("window.__deferResume = true")
    _emit(page, {"type": "tts_queue", "tts_epoch": 0, "pending_count": 3})
    _clip(page, 1, 0)
    page.wait_for_function("window.__resumeResolvers.length === 1")
    page.locator("#catch-up-btn").click()
    expect(page.locator("#catch-up-notice")).to_contain_text("Speech caught up")
    page.evaluate("window.__resumeResolvers[0]()")
    assert page.evaluate("window.__nodes.length") == 0
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#audio-enable-banner")).to_be_visible()
    expect(page.locator("#speech-backlog-status")).to_contain_text("0 clip(s)")
    expect(page.locator("#catch-up-btn")).to_be_disabled()


def test_muting_clears_audio_and_new_session_clears_catch_up_status(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness)
    page.locator("#enable-audio-btn").click()
    browser_harness.wait_for_message("tts_audio_enabled")
    _emit(page, {"type": "tts_queue", "tts_epoch": 0, "pending_count": 3})
    _clip(page, 1, 0)
    page.wait_for_function("window.__nodes.length === 1")
    page.locator("#tts-toggle-btn").click()
    expect(page.locator("#speech-backlog-status")).to_have_text("Speech muted.")
    expect(page.locator("#catch-up-btn")).to_be_disabled()
    assert page.evaluate("window.__nodes[0].stopped") is True
    _emit(page, {"type": "session_snapshot", "status": "idle_ready",
                 "tts_epoch": 2, "segments": [], "target_language": "en",
                 "available_target_languages": [{"code": "en", "label": "English"}]})
    expect(page.locator("#speech-backlog")).to_be_hidden()
    expect(page.locator("#catch-up-notice")).to_have_text("")


def test_queue_rejection_does_not_remove_a_different_buffered_clip_for_same_caption(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness)
    page.locator("#enable-audio-btn").click()
    browser_harness.wait_for_message("tts_audio_enabled")
    _clip(page, 1, 0)
    page.wait_for_function("window.__nodes.length === 1 && window.__nodes[0].started")
    _clip(page, 2, 0)
    _emit(page, {"type": "tts_skipped", "seq": 2, "tts_epoch": 0,
                 "kind": "replay", "reason": "queue_full", "audio_emitted": False})
    page.evaluate("window.__nodes[0].onended()")
    page.wait_for_function("window.__nodes.length === 2 && window.__nodes[1].started")


def test_failed_replay_id_keeps_successful_same_caption_clip(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness)
    page.locator("#enable-audio-btn").click()
    browser_harness.wait_for_message("tts_audio_enabled")
    for clip_id in (10, 11):
        _emit(page, {"type": "tts_speaking", "seq": 1, "clip_id": clip_id, "tts_epoch": 0})
        _emit(page, {"type": "tts_audio", "seq": 1, "clip_id": clip_id, "tts_epoch": 0,
                     "chunk_index": 0, "is_last": True, "data": "AAAAAA=="})
    page.wait_for_function("window.__nodes.length === 1")
    _emit(page, {"type": "tts_speaking", "seq": 1, "clip_id": 12, "tts_epoch": 0})
    _emit(page, {"type": "tts_error", "seq": 1, "clip_id": 12, "tts_epoch": 0,
                 "audio_emitted": False, "chunks_emitted": 0})
    page.evaluate("window.__nodes[0].onended()")
    page.wait_for_function("window.__nodes.length === 2 && window.__nodes[1].started")
    assert browser_harness.wait_for_message("tts_playback_complete")["clip_id"] == 10


def test_fresh_snapshot_can_restart_clip_ids_after_server_restart(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness)
    page.locator("#enable-audio-btn").click()
    browser_harness.wait_for_message("tts_audio_enabled")
    def clip():
        _emit(page, {"type": "tts_audio", "seq": 1, "clip_id": 10, "tts_epoch": 0,
                     "chunk_index": 0, "is_last": True, "data": "AAAAAA=="})
    clip()
    page.wait_for_function("window.__nodes.length === 1")
    page.evaluate("window.__nodes[0].onended()")
    _emit(page, {"type": "session_snapshot", "status": "listening", "tts_epoch": 0,
                 "segments": [], "target_language": "en"})
    clip()
    page.wait_for_function("window.__nodes.length === 2 && window.__nodes[1].started")


def test_deferred_blob_from_closed_socket_cannot_restart_audio(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness)
    page.locator("#enable-audio-btn").click()
    browser_harness.wait_for_message("tts_audio_enabled")
    count = page.evaluate("""async () => {
        const text = JSON.stringify({type:'tts_audio',seq:1,clip_id:10,tts_epoch:0,
            chunk_index:0,is_last:true,data:'AAAAAA=='});
        const blob = new Blob([text]);
        let resolve;
        blob.text = () => new Promise(r=>resolve=r);
        window.__socket.dispatchEvent(new MessageEvent('message',{data:blob}));
        window.__socket.onclose();
        resolve(text);
        await Promise.resolve();
        await Promise.resolve();
        return window.__nodes.length;
    }""")
    assert count == 0


def test_native_binary_frames_preserve_large_pcm_then_eos_order(
    page: Page, browser_harness: BrowserHarness
) -> None:
    _open(page, browser_harness)
    page.locator("#enable-audio-btn").click()
    browser_harness.wait_for_message("tts_audio_enabled")
    assert page.evaluate("window.__socket.binaryType") == "arraybuffer"
    page.evaluate("""() => {
        window.__binaryTypes = [];
        window.__socket.addEventListener('message', e=>window.__binaryTypes.push(e.data instanceof ArrayBuffer));
        window.__socket.send(JSON.stringify({type:'synthetic_tts_binary'}));
    }""")
    page.wait_for_function("window.__nodes.length === 1 && window.__nodes[0].started")
    assert page.evaluate("window.__nodes[0].buffer.getChannelData(0).length") == 98304
    assert page.evaluate("window.__binaryTypes") == [True, True, True]
    assert browser_harness.wait_for_message("tts_playback_start")["clip_id"] == 90
