"""Synthetic loopback/protocol probes; NOT actual Chromium or human acceptance."""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import orjson
import pytest
from websockets.sync.client import connect

from app import terminology
from app.config import AppConfig
from app.state import Segment, SessionManager

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def browser_module(monkeypatch):
    # Child test process only. Do not load .env or use a provider/proxy route.
    for name in list(os.environ):
        if name.upper().startswith(("MISTRAL_", "OPENAI_")) or "PROXY" in name.upper():
            monkeypatch.delenv(name)
    spec = importlib.util.spec_from_file_location(
        "terminology_browser_contract", ROOT / "browser_tests/test_caption_terminology.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def synthetic_manager(tmp_path):
    config = AppConfig(_env_file=None, MISTRAL_TTS_ENABLED=False,
                       journal_dir=str(tmp_path / "journal"),
                       reliability_dir=str(tmp_path / "reliability"))
    manager = SessionManager(config)
    terminology.initialize(manager.session, None)
    manager.session.status = "listening"
    manager.session.segments = [Segment(seq=1, source_text="A misheard protocol term.",
        segment_kind="complete", translated_text="Original translation.", translation_status="done")]
    return manager


def test_initial_wire_sequence_uses_real_delivery_gate(browser_module, synthetic_manager):
    snapshot, caption = browser_module._initial_messages(synthetic_manager)
    assert snapshot["type"] == "session_snapshot" and snapshot["segments"] == []
    assert snapshot["connection_lifecycle"]["state"] == "admitted"
    assert caption["type"] == "caption" and type(caption["seq"]) is int and caption["seq"] == 1
    assert caption["translated_text"] == "Original translation."
    assert caption["source_text"] == "A misheard protocol term."
    assert caption["translation_status"] == "done"
    assert caption["created_at"]
    assert synthetic_manager.session.highest_pushed_seq == 1
    assert synthetic_manager._listeners == []
    assert synthetic_manager._tts_dispatcher is None


def test_fixture_refuses_an_audio_capable_manager(browser_module, synthetic_manager):
    synthetic_manager._tts_dispatcher = object()  # Sentinel, never a real dispatcher.
    with pytest.raises(AssertionError):
        browser_module._initial_messages(synthetic_manager)
    assert synthetic_manager._listeners == []
    assert synthetic_manager.session.highest_pushed_seq == 0


def test_actual_loopback_room_sends_snapshot_then_numeric_caption(browser_module, tmp_path):
    controls, rendered, gate = [], threading.Event(), threading.Event()
    gate.set()
    fixture = browser_module.term_server.__wrapped__(tmp_path, controls, gate, rendered)
    url, manager = next(fixture)
    try:
        with connect(url.replace("http://", "ws://") + "/ws", open_timeout=3, close_timeout=3) as ws:
            snapshot = orjson.loads(ws.recv(timeout=3))
            caption = orjson.loads(ws.recv(timeout=3))
            assert snapshot["type"] == "session_snapshot" and snapshot["segments"] == []
            assert caption["type"] == "caption" and type(caption["seq"]) is int and caption["seq"] == 1
            assert caption["translated_text"] == "Original translation."
            assert manager.session.highest_pushed_seq == 1
            # This socket has no UI: it must not invent an acknowledgement.
            assert controls == [] and not rendered.is_set()
    finally:
        with pytest.raises(StopIteration):
            next(fixture)  # Includes original listener-closed and thread-release assertions.


def test_production_caption_handler_calls_renderer_before_observed_send(browser_module, synthetic_manager):
    node = shutil.which("node")
    assert node is not None, "Existing Node is required; no install/download route"
    _, caption = browser_module._initial_messages(synthetic_manager)
    source = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    start, end = source.index("    function handleCaption(msg)"), source.index("    function handleExportResult(")
    browser_source = (ROOT / "browser_tests/test_caption_terminology.py").read_text(encoding="utf-8")
    test = next(item for item in ast.parse(browser_source).body if isinstance(item, ast.FunctionDef)
                and item.name == "test_keyboard_editor_does_not_trigger_session_shortcuts")
    init = next(call.args[0].value for call in ast.walk(test) if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute) and call.func.attr == "add_init_script")
    result = subprocess.run([node, "-e", r"""
const vm=require('node:vm'), assert=require('node:assert/strict');
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const order=[], forwarded=[];
class Socket {send(payload) {order.push('wire');forwarded.push(JSON.parse(payload));}}
const context={window:{},WebSocket:Socket,appState:{captions:[],autoScroll:false},els:{},
    prependCaptionEntry(entry) {assert.equal(entry.seq,1);order.push('renderer');}};
vm.createContext(context);vm.runInContext(input.init,context);
const socket=new Socket();context.send=message=>socket.send(JSON.stringify(message));
vm.runInContext(input.handler,context);context.handleCaption(input.caption);
assert.deepEqual(order,['renderer','wire']);assert.equal(forwarded.length,1);
assert.equal(forwarded[0].type,'render_ack');assert.equal(forwarded[0].seq,1);
assert.equal(context.window.termShortcutFrames.length,1);
assert.equal(context.window.termShortcutFrames[0].seq,1);
assert.equal(context.appState.captions[0].translatedText,input.caption.translated_text);
console.log(JSON.stringify({model_only:true,actual_browser:false,dom_renderer_stub:true,
    production_ack_observed:true,seq:forwarded[0].seq}));
"""], input=json.dumps({"caption": caption, "handler": source[start:end], "init": init}),
        capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"model_only": True, "actual_browser": False,
        "dom_renderer_stub": True, "production_ack_observed": True, "seq": 1}


def _startup_frames():
    return [
        {"type": "refresh_input_devices"},
        {"type": "tts_mute", "muted": False},
        {"type": "render_ack", "seq": 1},
    ]


@pytest.mark.parametrize("remove_guard", [False, True])
def test_source_startup_and_removed_guard_observed_in_both_phases(browser_module, synthetic_manager, remove_guard):
    """Production source model; not Chromium, native focus or actual browser proof."""
    browser = browser_module
    tree = ast.parse((ROOT / "browser_tests/test_caption_terminology.py").read_text())
    keyboard = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "test_keyboard_editor_does_not_trigger_session_shortcuts")
    observer = next(node.args[0].value for node in ast.walk(keyboard) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == "add_init_script")
    messages = browser._initial_messages(synthetic_manager)
    result = subprocess.run(
        ["node", str(ROOT / "tests/fixtures/terminology_shortcut_node.cjs")],
        input=json.dumps({"observer": observer, "initial_messages": messages, "remove_guard": remove_guard}),
        check=False, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    trace = json.loads(result.stdout)
    assert trace["model_only"] is True and trace["actual_browser"] is False
    assert trace["rendered"] == [1]
    for observer_name in ["client", "server"]:
        initial = trace["startup_" + observer_name]
        final = trace["final_" + observer_name]
        baseline = browser._assert_startup_baseline(initial)
        assert baseline == 3 and initial == _startup_frames()
        # Reproduce the hosted line404 error without pretending to run Chromium:
        # the former whole-history assertion rejects these genuine source sends.
        with pytest.raises(AssertionError):
            assert [message for message in initial if message["type"] != "render_ack"] == []
        if remove_guard:
            assert final[baseline:] == [{"type": "stop"}]
            with pytest.raises(AssertionError, match="after keyboard baseline"):
                browser._assert_shortcut_phase(final, baseline)
        else:
            browser._assert_shortcut_phase(final, baseline)


@pytest.mark.parametrize("late_frame", [
    {"type": "refresh_input_devices"},
    {"type": "tts_mute", "muted": False},
    {"type": "stop"},
    {"type": "render_ack", "seq": 1},
])
def test_late_startup_or_control_frames_never_get_a_noise_exemption(browser_module, late_frame):
    browser = browser_module
    baseline = browser._assert_startup_baseline(_startup_frames())
    for _observer_name in ["client", "server"]:
        with pytest.raises(AssertionError, match="after keyboard baseline"):
            browser._assert_shortcut_phase(_startup_frames() + [late_frame], baseline)


@pytest.mark.parametrize("bad_frames", [
    [], _startup_frames()[:-1], _startup_frames()[1:],
    _startup_frames() + [{"type": "stop"}], list(reversed(_startup_frames())),
    [_startup_frames()[0], {"type": "tts_mute", "muted": 0}, _startup_frames()[2]],
    [_startup_frames()[0], _startup_frames()[1], {"type": "render_ack", "seq": True}],
    [_startup_frames()[0], _startup_frames()[1], {"type": "render_ack", "seq": 2}],
])
def test_startup_count_order_payload_and_ack_are_verified_not_filtered(browser_module, bad_frames):
    with pytest.raises(AssertionError):
        browser_module._assert_startup_baseline(bad_frames)


def test_receive_checkpoint_waits_for_the_observed_send_count(browser_module):
    frames = browser_module._ControlFrames()
    assert not frames.wait_for_count(1, timeout=0)
    release = threading.Event()

    def receive():
        assert release.wait(timeout=5)
        frames.append({"type": "stop"})

    worker = threading.Thread(target=receive)
    worker.start()
    release.set()
    assert frames.wait_for_count(1)
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert frames.snapshot() == [{"type": "stop"}]
    snapshot = frames.snapshot()
    snapshot[0]["type"] = "mutated-copy"
    assert frames.snapshot() == [{"type": "stop"}]
