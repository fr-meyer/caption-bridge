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

const deferred = () => {
    let resolve, reject;
    const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
    return {promise, resolve, reject};
};
const flush = () => new Promise(resolve => setImmediate(resolve));

test("successful older sink stays truthful when the later New Session reset fails", async () => {
    const first = deferred();
    const context = {sinkId: "", async setSinkId(id) {
        if (!id) throw Error("PRIVATE_RESET_FAILURE");
        await first.promise;
        this.sinkId = id;
    }};
    const devices = new AudioDevices({media: {}, canRoute: () => true,
        context: () => context, send() {}, unavailable() {}});
    devices.snapshot({available: [], selected: "default"}, "listening", "older");
    const old = devices.setOutput("synthetic-sink", "Synthetic chosen output");
    await flush();
    devices.snapshot({available: [], selected: "default"}, "idle_ready", "newer");
    first.resolve();
    await old;
    await devices.sinkQueue.catch(() => {});
    await flush();
    assert.equal(devices.output, context.sinkId);
    assert.equal(devices.outputLabel, "Synthetic chosen output");
    assert.match(devices.notice, /Output change failed/);
    assert.doesNotMatch(devices.notice, /PRIVATE/);
});

test("pre-chooser empty inventory cannot mute a newly granted connected sink", async () => {
    const stale = deferred();
    const permitted = {kind: "audiooutput", deviceId: "granted", label: "Synthetic permitted output"};
    let enumerations = 0, muteCalls = 0;
    const devices = new AudioDevices({media: {
        enumerateDevices: () => ++enumerations === 1 ? stale.promise : Promise.resolve([permitted]),
        selectAudioOutput: async () => permitted,
    }, canRoute: () => true, context: () => ({setSinkId: async () => {}}),
    send() {}, unavailable() {muteCalls++;}});
    const older = devices.refreshOutputs();
    await devices.chooseOutput();
    stale.resolve([]);
    await older;
    await flush();
    assert.equal(devices.output, "granted");
    assert.equal(devices.outputUnavailable, false);
    assert.equal(muteCalls, 0);
    assert.ok(enumerations >= 2, "Transition must request fresh post-permission inventory");
});

test("removal during a pending sink change is checked again after the transition", async () => {
    const pending = deferred();
    let muteCalls = 0, enumerations = 0;
    const devices = new AudioDevices({media: {enumerateDevices: async () => {enumerations++; return []; }},
        canRoute: () => true, context: () => ({setSinkId: () => pending.promise}),
        send() {}, unavailable() {muteCalls++;}});
    const change = devices.setOutput("removed", "Synthetic removed output");
    await devices.refreshOutputs(); // Device-change notification while switching.
    assert.equal(enumerations, 0);
    pending.resolve();
    await change;
    await flush();
    assert.equal(enumerations, 1);
    assert.equal(muteCalls, 1);
    assert.equal(devices.outputUnavailable, true);
});
