"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const AudioDevices = require("../app/static/audio-devices.js");

function fixture({supported = true, fail = false} = {}) {
    const calls = [];
    const outputs = [{kind: "audiooutput", deviceId: "synthetic-sink", label: "Synthetic output"}];
    const media = {enumerateDevices: async () => outputs,
        selectAudioOutput: async () => outputs[0]};
    const context = {setSinkId: async id => {calls.push(id); if (fail) throw Error("PRIVATE_DETAIL");}};
    const options = {media, canRoute: () => supported, context: () => context,
        send: message => calls.push(message), unavailable: () => calls.push("muted")};
    const devices = new AudioDevices(options);
    return {devices, calls, outputs, context, media};
}

test("output routes the shared context and carries no browser capture", async () => {
    const {devices, calls, media} = fixture();
    media.getUserMedia = () => assert.fail("Never open a browser microphone");
    await devices.refreshOutputs();
    assert.equal(await devices.setOutput("synthetic-sink"), true);
    assert.deepEqual(calls, ["synthetic-sink"]);
    assert.equal(devices.outputLabel, "Synthetic output");
});

test("unsupported output does not claim or call a sink change", async () => {
    const {devices, calls} = fixture({supported: false});
    assert.equal(await devices.setOutput("synthetic-sink"), false);
    assert.equal(devices.output, "");
    assert.equal(calls.length, 0);
    assert.match(devices.notice, /system\/browser default/);
});

test("denied routing retains prior route with a generic notice", async () => {
    const {devices} = fixture({fail: true});
    assert.equal(await devices.setOutput("synthetic-sink"), false);
    assert.equal(devices.output, "");
    assert.match(devices.notice, /Output change failed/);
    assert.doesNotMatch(devices.notice, /PRIVATE/);
});

test("removed selected output mutes speech without pretending to reroute", async () => {
    const {devices, calls, outputs} = fixture();
    await devices.refreshOutputs();
    await devices.setOutput("synthetic-sink");
    outputs.length = 0;
    await devices.refreshOutputs();
    assert.equal(devices.output, "synthetic-sink");
    assert.equal(calls.at(-1), "muted");
    assert.match(devices.notice, /unavailable/);
});

test("slow old sink change cannot override a New Session default reset", async () => {
    const {devices, calls, context} = fixture();
    let release;
    context.setSinkId = id => {calls.push(id); return id ? new Promise(resolve => {release = resolve;}) : Promise.resolve();};
    devices.snapshot({available: [], selected: "default"}, "listening", "session-one");
    const older = devices.setOutput("synthetic-sink");
    await Promise.resolve();
    await Promise.resolve();
    devices.snapshot({available: [], selected: "default"}, "idle_ready", "session-two");
    release();
    await older;
    await devices.sinkQueue;
    await Promise.resolve();
    assert.deepEqual(calls, ["synthetic-sink", ""]);
    assert.equal(devices.output, "");
    assert.equal(devices.outputBusy, false);
});

test("native choice refresh is separate from browser outputs and active snapshot restores input", async () => {
    const {devices, calls} = fixture();
    devices.snapshot({available: [{id: "native-token", label: "Native input"}],
        selected: "native-token", active_label: "Native input"}, "listening", "session");
    assert.equal(devices.input, "native-token");
    assert.equal(devices.activeInput, "Native input");
    await devices.refresh();
    assert.deepEqual(calls, [{type: "refresh_input_devices"}]);
    assert.equal(devices.output, "");
});

test("chooser cancellation retains route and never exposes exception contents", async () => {
    const {devices, media} = fixture();
    media.selectAudioOutput = async () => {throw Error("PRIVATE_PERMISSION_DETAIL");};
    await devices.chooseOutput();
    assert.equal(devices.output, "");
    assert.match(devices.notice, /not granted/);
    assert.doesNotMatch(devices.notice, /PRIVATE/);
});
