"""Software/AST mutation checks only; actual key/browser behavior needs hosted CI."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import subprocess
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BROWSER_SOURCE = (ROOT / "browser_tests/test_caption_terminology.py").read_text(encoding="utf-8")
TREE = ast.parse(BROWSER_SOURCE)
KEYBOARD_TEST = next(node for node in TREE.body if isinstance(node, ast.FunctionDef)
                     and node.name == "test_keyboard_editor_does_not_trigger_session_shortcuts")


NODE_DIAGNOSTIC_PREFIX = "SHORTCUT_NODE_TRANSPORT "
NODE_STAGES = (
    "ENTRY", "STDIN_READ_BEGIN", "STDIN_READ_END", "JSON_PARSED",
    "ORIGINAL_BEGIN", "ORIGINAL_DONE", "MUTANT_BEGIN", "MUTANT_DONE",
    "FORWARD_BEGIN", "FORWARD_DONE", "RESULT_WRITE_BEGIN", "RESULT_ENQUEUED", "EXIT_EVENT",
)


def _node_diagnostic(stderr, *, outcome, returncode, payload, started):
    # Parse only bounded fixed markers, never publish raw stderr/paths/source.
    # A timeout snapshot can be incomplete; absence of a marker proves no cause.
    observed = stderr or ""
    sample = observed[:4096]
    if isinstance(sample, bytes):
        sample = sample.decode("ascii", errors="replace")
    stages, received = [], None
    valid = True
    for line in sample.splitlines():
        if not line.startswith("CB_SHORTCUT_NODE:"):
            continue
        match = re.fullmatch(r"CB_SHORTCUT_NODE:([0-9]{1,2})(?::([0-9]{1,10}))?", line)
        if match is None:
            valid = False
            continue
        stage = int(match[1])
        if stage >= len(NODE_STAGES) or (match[2] is not None) != (stage == 2):
            valid = False
            continue
        if stage != len(stages) and stage != 12:
            valid = False
        if stage in stages:
            valid = False
        stages.append(stage)
        if stage == 2:
            received = int(match[2])
    error = re.search(r"\b(AssertionError|SyntaxError|TypeError|ReferenceError|RangeError|Error)"
                      r"(?: \[(ERR_ASSERTION|EPIPE|EBADF|EINVAL|EAGAIN|ENOENT|EACCES)\])?:", sample)
    valid = valid and bool(stages) and len(stages) <= 13
    stages = stages[:13]
    value = {
        "schema": 1, "kind": "NODE_SHORTCUT_TRANSPORT_DIAGNOSTIC", "model_only": True,
        "cause": "UNKNOWN", "outcome": outcome, "returncode": returncode,
        "timeout_seconds": 5, "elapsed_ms": (time.monotonic_ns() - started) // 1_000_000,
        "input_bytes": len(payload.encode("ascii")),
        "input_sha256": hashlib.sha256(payload.encode("ascii")).hexdigest(),
        "stdin_bytes_observed": received, "stages_observed": stages,
        "last_stage": NODE_STAGES[stages[-1]] if stages else "NO_STAGE_OBSERVED",
        "stage_protocol_valid": valid,
        "stderr_scan_truncated": len(observed) > 4096,
        "node_error_class": error[1] if error else None,
        "node_error_code": error[2] if error else None,
    }
    line = NODE_DIAGNOSTIC_PREFIX + json.dumps(value, sort_keys=True, separators=(",", ":"))
    print(line)
    return line


class ShortcutContractTests(unittest.TestCase):
    def test_real_key_events_and_both_frame_observers_are_asserted(self):
        calls = [node for node in ast.walk(KEYBOARD_TEST) if isinstance(node, ast.Call)]
        methods = [node.func.attr for node in calls if isinstance(node.func, ast.Attribute)]
        self.assertNotIn("insert_text", methods)
        self.assertIn("type", methods)
        self.assertTrue(any(isinstance(node.func, ast.Attribute) and node.func.attr == "press"
                            and node.args and isinstance(node.args[0], ast.Constant)
                            and node.args[0].value == "Space" for node in calls))
        assertions = [ast.get_source_segment(BROWSER_SOURCE, node)
                      for node in ast.walk(KEYBOARD_TEST) if isinstance(node, ast.Assert)]
        self.assertTrue(any("term_controls" in source for source in assertions))
        phase_calls = [tuple(ast.unparse(arg) for arg in node.args) for node in calls
                       if isinstance(node.func, ast.Name) and node.func.id == "_assert_shortcut_phase"]
        self.assertEqual(phase_calls, [("sent", "sent_baseline"), ("received", "received_baseline")])
        # Immutable integer indices are each bound once, before opener/key actions.
        for name in ["sent_baseline", "received_baseline"]:
            bindings = [node for node in ast.walk(KEYBOARD_TEST) if isinstance(node, ast.Name)
                        and node.id == name and isinstance(node.ctx, ast.Store)]
            self.assertEqual(len(bindings), 1)
        self.assertNotIn("clear", methods)
        self.assertNotIn("sleep", methods)
        self.assertIn('term_controls.append(message)', BROWSER_SOURCE)
        self.assertLess(BROWSER_SOURCE.index('term_controls.append(message)'),
                        BROWSER_SOURCE.index('if message.get("type") not in'))

    def test_edited_browser_selectors_match_real_markup(self):
        markup = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        for call in ast.walk(KEYBOARD_TEST):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "locator" and call.args
                    and isinstance(call.args[0], ast.Constant)):
                selector = call.args[0].value
                if selector.startswith("#"):
                    self.assertIn('id="' + selector[1:] + '"', markup)

    def test_capture_forwards_and_modal_guard_mutation_is_detectable(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Existing Node runtime required; no install requested")
        init = next(call.args[0].value for call in ast.walk(KEYBOARD_TEST)
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "add_init_script")
        source = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        start = source.index("    function setupKeyboard() {")
        end = source.index("    // ===== Terminology preferences =====", start)
        payload = json.dumps({"keyboard": source[start:end], "init": init})
        started = time.monotonic_ns()
        try:
            result = subprocess.run([node, "-e", r"""
const fs = require('node:fs');
function nodeStage(stage, bytes) {
    fs.writeSync(2, 'CB_SHORTCUT_NODE:' + stage + (bytes === undefined ? '' : ':' + bytes) + '\n');
}
nodeStage(0);
process.once('exit', () => nodeStage(12));
const assert = require('node:assert/strict'), vm = require('node:vm');
nodeStage(1);
const inputText = fs.readFileSync(0, 'utf8');
nodeStage(2, Buffer.byteLength(inputText, 'utf8'));
const input = JSON.parse(inputText);
nodeStage(3);
function run(source) {
    let handler;
    const frames = [], effects = [];
    const context = {els: {termDialog: {open: true},
        discardModal: {classList: {contains: () => false}},
        exportFailureModal: {classList: {contains: () => false}}},
        appState: {status: 'listening', drawerOpen: false},
        document: {addEventListener(_type, callback) {handler = callback;}},
        send: message => frames.push(message), toggleFullscreen: () => effects.push('fullscreen'),
        stepFontSize: () => effects.push('font'), toggleDrawer: () => effects.push('drawer')};
    vm.createContext(context); vm.runInContext(source + '\nsetupKeyboard();', context);
    for (const key of [' ', 'f', 's', '+', '-'])
        handler({key, code: key === ' ' ? 'Space' : '', target: {tagName: 'P'}, preventDefault() {}});
    return {frames, effects};
}
nodeStage(4);
const original = run(input.keyboard);
assert.deepEqual(original.frames, []); assert.deepEqual(original.effects, []);
nodeStage(5);
const guard = 'if (els.termDialog.open) return;';
assert(input.keyboard.includes(guard));
nodeStage(6);
const mutant = run(input.keyboard.replace(guard, ''));
assert.equal(mutant.frames[0].type, 'stop');
assert(mutant.effects.includes('fullscreen'));
nodeStage(7);
nodeStage(8);
const forwarded = [];
class Socket {send(payload) {forwarded.push(payload);}}
const context = {window: {}, WebSocket: Socket};
vm.createContext(context); vm.runInContext(input.init, context);
const socket = new Socket();
for (const type of ['render_ack', 'stop']) socket.send(JSON.stringify({type}));
assert.deepEqual(Array.from(context.window.termShortcutFrames, row => row.type), ['render_ack', 'stop']);
assert.equal(forwarded.length, 2);
nodeStage(9);
nodeStage(10);
console.log(JSON.stringify({model_only: true, original_controls: original.frames.length,
    removed_guard_emits_stop: true, capture_forwarded: forwarded.length}));
nodeStage(11);
"""], input=payload, capture_output=True, text=True, timeout=5, check=False)
        except subprocess.TimeoutExpired as error:
            diagnostic = _node_diagnostic(error.stderr, outcome="TIMEOUT", returncode=None,
                                          payload=payload, started=started)
            raise AssertionError(diagnostic) from None
        except OSError:
            diagnostic = _node_diagnostic(None, outcome="SPAWN_ERROR", returncode=None,
                                          payload=payload, started=started)
            raise AssertionError(diagnostic) from None
        diagnostic = _node_diagnostic(result.stderr,
                                      outcome="EXITED" if result.returncode == 0 else "NONZERO",
                                      returncode=result.returncode, payload=payload, started=started)
        self.assertEqual(result.returncode, 0, diagnostic)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt["model_only"])
        self.assertEqual(receipt["original_controls"], 0)
        self.assertTrue(receipt["removed_guard_emits_stop"])
        self.assertEqual(receipt["capture_forwarded"], 2)
