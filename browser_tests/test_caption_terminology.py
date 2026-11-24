"""Synthetic live caption correction against the production terminology service."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from pathlib import Path

import httpx
import orjson
import pytest
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from playwright.sync_api import Page, expect

from app import terminology
from app.config import AppConfig
from app.journal import SessionJournal
from app.state import Segment, SessionManager

pytestmark = pytest.mark.browser
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


@pytest.fixture(autouse=True)
def fake_browser_media(page: Page) -> None:
    page.add_init_script("""
        Object.defineProperty(navigator, 'mediaDevices', {value: {
            enumerateDevices: async () => [], addEventListener() {},
            getUserMedia() { throw Error('Real browser capture forbidden'); },
        }});
        window.AudioContext = class {
            constructor() { throw Error('Real browser audio forbidden'); }
            setSinkId() {}
        };
        const NativeSocket = window.WebSocket;
        window.WebSocket = class extends NativeSocket {
            constructor(...args) { super(...args); window.__termSocket = this; }
        };
    """)


@pytest.fixture
def term_controls():
    """Record every inbound frame before the fixture dispatch/ignore filter."""
    return []


@pytest.fixture
def term_reply_gate():
    gate = threading.Event()
    gate.set()
    return gate


@pytest.fixture
def term_rendered():
    return threading.Event()


def _initial_messages(manager):
    """Restore the room, then send a genuine numeric-seq production caption.

    Snapshot history deliberately has no render acknowledgement. The real
    delivery gate emits the live event; only the UI may originate render_ack.
    """
    assert not manager.config.tts_enabled and manager._tts_dispatcher is None
    snapshot = {"type": "session_snapshot", **manager.get_snapshot(), "segments": [],
                "connection_lifecycle": {"connection_id": "conn-000001", "state": "admitted",
                                         "reason": "owner_admitted"}}
    events = []
    listener = events.append
    manager.subscribe(listener)
    try:
        manager.session.highest_pushed_seq = 0
        manager._try_deliver()
    finally:
        manager.unsubscribe(listener)
    assert len(events) == 1 and events[0]["type"] == "caption" and events[0]["seq"] == 1
    return [snapshot, *events]


@pytest.fixture
def term_server(tmp_path, term_controls, term_reply_gate, term_rendered):
    config = AppConfig(_env_file=None, MISTRAL_TTS_ENABLED=False,
                       journal_dir=str(tmp_path / "journal"), reliability_dir=str(tmp_path / "reliability"))
    manager = SessionManager(config)
    terminology.initialize(manager.session, None)
    manager.session.status = "listening"
    segment = Segment(seq=1, source_text="A misheard protocol term.", segment_kind="complete",
                      translated_text="Original translation.", translation_status="done")
    manager.session.segments = [segment]
    manager.session.highest_pushed_seq = 1
    manager.set_journal(SessionJournal(manager.session.id, config))
    manager._journal.record_session_started()
    manager._journal.record_terminology(manager.session.terminology_history[0], [])
    app = FastAPI()

    @app.get("/healthz")
    async def health():
        return Response(status_code=204)

    @app.get("/{filename:path}")
    async def frontend(filename: str):
        return FileResponse(STATIC / (filename or "index.html"))

    @app.websocket("/ws")
    async def websocket(connection: WebSocket):
        await connection.accept()
        for message in _initial_messages(manager):
            await connection.send_bytes(orjson.dumps(message))
        try:
            while True:
                message = orjson.loads(await connection.receive_text())
                term_controls.append(message)
                if message.get("type") == "render_ack" and message.get("seq") == 1:
                    term_rendered.set()
                if message.get("type") not in {"update_terminology", "undo_terminology"}:
                    continue
                if not await asyncio.to_thread(term_reply_gate.wait, 10):
                    raise TimeoutError("synthetic terminology reply gate timed out")
                try:
                    terminology.change(manager, message, undo=message["type"] == "undo_terminology")
                    event = {"type": "terminology_updated", **terminology.state(manager.session)}
                except ValueError as exc:
                    event = {"type": "terminology_error", "message": str(exc), **terminology.state(manager.session)}
                await connection.send_bytes(orjson.dumps(event))
        except WebSocketDisconnect:
            return

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                          log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            if httpx.get(url + "/healthz", timeout=.2).status_code == 204:
                break
        except httpx.HTTPError:
            time.sleep(.02)
    else:
        raise RuntimeError("Synthetic terminology server did not start")
    try:
        yield url, manager
    finally:
        term_reply_gate.set()
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()
        with socket.socket() as probe:
            probe.settimeout(.2)
            assert probe.connect_ex(("127.0.0.1", port)) != 0, "Synthetic listener must close"


def open_caption(page: Page, url: str):
    page.goto(url, wait_until="domcontentloaded")
    page.get_by_role("button", name="Correct term in caption 1", exact=True).click()
    expect(page.locator("#term-dialog")).to_be_visible()
    expect(page.locator("#term-source")).to_be_focused()


def test_caption_save_inspect_edit_remove_undo_and_focus_without_stopping(page: Page, term_server):
    url, manager = term_server
    open_caption(page, url)
    page.locator("#term-source").fill("misheard")
    page.locator("#term-preferred").fill("corrected")
    page.locator("#term-kind").select_option("source")
    assert manager.session.terminology_version == 0
    page.locator("#term-save").click()
    expect(page.locator("#term-version")).to_contain_text("v1")
    expect(page.locator("#term-list")).to_contain_text("misheard → corrected (source correction)")
    expect(page.locator(".caption-translated")).to_have_text("Original translation.")
    expect(page.locator(".caption-terms-version")).to_have_text("Terms v0")
    page.get_by_role("button", name="Edit term: misheard", exact=True).click()
    page.locator("#term-preferred").fill("edited")
    page.locator("#term-save").click()
    expect(page.locator("#term-version")).to_contain_text("v2")
    page.get_by_role("button", name="Remove term: misheard", exact=True).click()
    expect(page.locator("#term-list .term-row")).to_have_count(0)
    page.locator("#term-undo").click()
    expect(page.locator("#term-list")).to_contain_text("edited")
    assert manager.session.status == "listening"
    assert manager.session.terminology_history[1].caption_seq == 1
    page.keyboard.press("Escape")
    expect(page.locator("#term-dialog")).not_to_be_visible()
    expect(page.get_by_role("button", name="Correct term in caption 1", exact=True)).to_be_focused()


def test_confirmation_cancel_refresh_and_literal_rendering(page: Page, term_server):
    url, manager = term_server
    open_caption(page, url)
    page.locator("#term-source").fill("protocol")
    page.locator("#term-preferred").fill("cancelled")
    page.locator("#term-close").click()
    assert manager.session.glossary is None
    page.get_by_role("button", name="Correct term in caption 1", exact=True).click()
    page.locator("#term-source").fill("protocol")
    page.locator("#term-preferred").fill('<img src=x onerror="window.termXss=1">')
    page.locator("#term-save").click()
    expect(page.locator("#term-version")).to_contain_text("v1")
    expect(page.locator("#term-list img")).to_have_count(0)
    assert page.evaluate("window.termXss") is None
    assert page.evaluate("localStorage.getItem('captionBridge.glossary')") is None
    page.reload(wait_until="domcontentloaded")
    page.get_by_role("button", name="Settings", exact=True).click()
    page.locator("#session-terms").click()
    expect(page.locator("#term-list")).to_contain_text("<img")
    expect(page.locator("#term-version")).to_contain_text("v1")
    expect(page.locator("#term-undo")).to_be_enabled()
    expect(page.locator(".caption-translated")).to_have_text("Original translation.")


def test_invalid_terms_and_caption_mismatch_leave_listening_unchanged(page: Page, term_server):
    url, manager = term_server
    open_caption(page, url)
    page.locator("#term-source").fill("protocol")
    page.locator("#term-preferred").fill("x" * 81)
    page.locator("#term-save").click()
    expect(page.locator("#term-error")).to_contain_text("1–80")
    assert manager.session.terminology_version == 0
    page.locator("#term-source").fill("absent")
    page.locator("#term-preferred").fill("X")
    page.locator("#term-save").click()
    expect(page.locator("#term-error")).to_contain_text("occurs in the displayed caption")
    expect(page.locator("#term-save")).to_be_enabled()
    assert manager.session.status == "listening"
    assert manager.session.terminology_version == 0


def test_term_focus_updates_read_only_inspection_and_hidden_opener(page: Page, term_server):
    url, manager = term_server
    open_caption(page, url)
    page.locator("#term-source").fill("misheard")
    page.locator("#term-preferred").fill("corrected")
    page.locator("#term-save").click()
    expect(page.locator("#term-version")).to_contain_text("v1")

    def emit(message):
        page.evaluate(
            "message => window.__termSocket.onmessage({data: JSON.stringify(message)})", message,
        )

    edit = page.get_by_role("button", name="Edit term: misheard", exact=True)
    edit.focus()
    emit({"type": "terminology_updated", **terminology.state(manager.session)})
    expect(edit).to_be_focused()
    remove = page.get_by_role("button", name="Remove term: misheard", exact=True)
    remove.focus()
    emit({"type": "terminology_updated", **terminology.state(manager.session)})
    expect(remove).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator("#term-list .term-row")).to_have_count(0)
    expect(page.locator("#term-close")).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Correct term in caption 1", exact=True)).to_be_focused()

    page.get_by_role("button", name="Settings", exact=True).click()
    terms = page.get_by_role("button", name="Session terminology", exact=True)
    terms.focus()
    page.keyboard.press("Enter")
    page.keyboard.press("Escape")
    expect(terms).to_be_focused()

    emit({"type": "terminology_updated", **terminology.state(manager.session),
          "terminology_changes": 100})
    page.keyboard.press("Enter")
    expect(page.locator("#term-save")).to_be_disabled()
    expect(page.locator("#term-undo")).to_be_disabled()
    expect(page.locator("#term-close")).to_be_focused()
    emit({"type": "session_snapshot", **manager.get_snapshot(), "status": "session_ended"})
    page.keyboard.press("Escape")
    expect(page.locator("#term-dialog")).not_to_be_visible()
    expect(page.locator("#status-label")).to_be_focused()
    assert manager.session.status == "listening"  # Only synthetic UI state was changed.



def _assert_focus_cycle(page):
    for key in ["Tab"] * 10 + ["Shift+Tab"] * 10:
        page.keyboard.press(key)
        assert page.evaluate("document.querySelector('#term-dialog').contains(document.activeElement)")
        assert page.evaluate("!document.activeElement.disabled")


def test_keyboard_dialog_labels_traversal_pending_save_and_undo(
    page: Page, term_server, term_reply_gate,
):
    """Keyboard/focus software contract only, not human assistive-tech acceptance."""
    url, manager = term_server
    page.goto(url, wait_until="domcontentloaded")
    opener = page.get_by_role("button", name="Correct term in caption 1", exact=True)
    opener.focus()  # Explicit test anchor, not evidence of uncoached discoverability.
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name="Correct a term", exact=True)
    expect(dialog).to_be_visible()
    expect(page.get_by_label("Source term", exact=True)).to_be_focused()
    _assert_focus_cycle(page)
    page.keyboard.press("Shift+Tab")
    expect(page.get_by_label("Correction type", exact=True)).to_be_focused()
    page.keyboard.press("Tab")
    page.keyboard.insert_text("misheard")
    page.keyboard.press("Tab")
    expect(page.get_by_label("Correct term or preferred rendering", exact=True)).to_be_focused()
    page.keyboard.insert_text("corrected")
    page.keyboard.press("Tab")
    expect(page.get_by_role("button", name="Save for future captions", exact=True)).to_be_focused()
    term_reply_gate.clear()
    page.keyboard.press("Enter")
    expect(page.locator("#term-save")).to_be_disabled()
    expect(page.locator("#term-close")).to_be_focused()
    _assert_focus_cycle(page)
    assert manager.session.terminology_version == 0
    term_reply_gate.set()
    expect(page.locator("#term-version")).to_contain_text("v1")
    expect(page.locator("#term-close")).to_be_focused()
    _assert_focus_cycle(page)
    page.keyboard.press("Shift+Tab")
    expect(page.get_by_role("button", name="Undo last change", exact=True)).to_be_focused()
    term_reply_gate.clear()
    page.keyboard.press("Enter")
    expect(page.locator("#term-undo")).to_be_disabled()
    expect(page.locator("#term-close")).to_be_focused()
    _assert_focus_cycle(page)
    assert manager.session.terminology_version == 1
    term_reply_gate.set()
    expect(page.locator("#term-version")).to_contain_text("v2")
    expect(page.locator("#term-close")).to_be_focused()
    # Retain the original full forward/backward containment assertion after undo.
    for key in ["Tab"] * 10 + ["Shift+Tab"] * 10:
        page.keyboard.press(key)
        assert page.evaluate("document.querySelector('#term-dialog').contains(document.activeElement)")
    expect(page.locator(".caption-translated")).to_have_text("Original translation.")
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    expect(opener).to_be_focused()
    assert manager.session.status == "listening"


def test_keyboard_editor_does_not_trigger_session_shortcuts(
    page: Page, term_server, term_controls, term_rendered,
):
    url, manager = term_server
    # Capture synchronous sends as well: a server/event-loop race cannot hide an
    # accidental Stop behind the fixture's intentionally inert backend.
    page.add_init_script("""(() => {
        window.termShortcutFrames = [];
        const send = WebSocket.prototype.send;
        WebSocket.prototype.send = function(payload) {
            window.termShortcutFrames.push(JSON.parse(payload));
            return send.call(this, payload);
        };
    })();""")
    page.goto(url, wait_until="domcontentloaded")
    opener = page.get_by_role("button", name="Correct term in caption 1", exact=True)
    expect(page.locator(".caption-translated")).to_have_text("Original translation.")
    page.wait_for_function("window.termShortcutFrames.some(message => message.type === 'render_ack' && message.seq === 1)")
    assert term_rendered.wait(timeout=5), "real render_ack must reach the WebSocket fixture"
    opener.focus()
    page.keyboard.press("Enter")
    # type()/press() dispatch real keydown/keyup. Explicit Space exercises the
    # global Stop binding; letter/font bindings are checked on modal controls.
    page.keyboard.type("protocol")
    page.keyboard.press("Space")
    page.keyboard.type("term")
    expect(page.locator("#term-source")).to_have_value("protocol term")
    page.keyboard.press("Tab")
    page.keyboard.type("clear")
    page.keyboard.press("Space")
    page.keyboard.type("rendering")
    expect(page.locator("#term-preferred")).to_have_value("clear rendering")
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Shift+Tab")
    expect(page.locator("#term-kind")).to_be_focused()
    for key in ["f", "s", "+", "-"]:
        page.keyboard.press(key)
    page.locator("#term-close").focus()
    for key in ["f", "s", "+", "-"]:
        page.keyboard.press(key)
    # Anchor focus on modal help content, as assistive navigation can. This is
    # deliberately not an input/button: removing the modal-level guard must
    # expose Space -> Stop even when the ordinary text-field guard remains.
    page.locator("#term-help").evaluate("element => { element.tabIndex = -1; element.focus(); }")
    expect(page.locator("#term-help")).to_be_focused()
    for key in ["Space", "f", "s", "+", "-"]:
        page.keyboard.press(key)
    assert page.evaluate("document.fullscreenElement === null")
    page.keyboard.press("Escape")
    expect(opener).to_be_focused()
    expect(page.locator("#status-label")).to_contain_text("Listening")
    expect(page.locator(".caption-translated")).to_have_text("Original translation.")
    # The positive acknowledgement proves capture is live. No session/control
    # sends are permitted, even if the backend ignores them without changing state.
    sent = page.evaluate("window.termShortcutFrames")
    assert any(message["type"] == "render_ack" and message["seq"] == 1 for message in sent)
    assert any(message["type"] == "render_ack" and message["seq"] == 1 for message in term_controls)
    assert [message for message in sent if message["type"] != "render_ack"] == []
    assert [message for message in term_controls if message["type"] != "render_ack"] == []
    assert manager.session.status == "listening"
    assert manager.session.terminology_version == 0
    assert manager.session.glossary is None
