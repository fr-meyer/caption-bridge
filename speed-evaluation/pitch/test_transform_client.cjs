"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const Client = require("./transform-client.js");
function fake() {
    return {terminated: 0, postMessage(message, transfer) { this.message = message; this.transfer = transfer; },
        terminate() { this.terminated++; },
        reply(extra = {}) { this.onmessage({data: {...this.message, pcm: new Float32Array(2000), ...extra}}); }};
}
test("worker success preserves identity and leaves caller PCM unchanged", async () => {
    const worker = fake();
    const client = new Client(() => worker);
    const input = new Float32Array(2600);
    input[5] = 0.35;
    const pending = client.run(input, 1.3, {epoch: 3, clipId: 10});
    assert.notEqual(worker.message.pcm, input);
    assert.deepEqual(worker.message.pcm, input);
    assert.equal(worker.transfer[0], worker.message.pcm.buffer);
    worker.reply();
    const result = await pending;
    assert.equal(result.epoch, 3);
    assert.equal(result.clipId, 10);
    assert.equal(result.pcm.length, 2000);
    assert.equal(input[5], Math.fround(0.35));
    assert.equal(worker.terminated, 1);
    assert.equal(client.active, null);
});
test("only one transform can be pending; wrong identity cannot complete it", async () => {
    const worker = fake();
    const client = new Client(() => worker);
    const pending = client.run(new Float32Array(2600), 1.3, {epoch: 3, clipId: 10});
    await assert.rejects(client.run(new Float32Array(2600), 1.3, {epoch: 3, clipId: 11}), /busy/);
    for (const extra of [{id: 2}, {epoch: 4}, {clipId: 11}]) worker.reply(extra);
    assert.notEqual(client.active, null);
    worker.reply();
    await pending;
});
test("Catch-up/epoch cancellation terminates work and ignores its late success", async () => {
    const workers = [fake(), fake()];
    let count = 0;
    const client = new Client(() => workers[count++]);
    const old = client.run(new Float32Array(2600), 1.3, {epoch: 3, clipId: 10});
    const rejection = assert.rejects(old, error => error.name === "AbortError");
    client.cancel();
    await rejection;
    assert.equal(workers[0].terminated, 1);
    const next = client.run(new Float32Array(2600), 1.3, {epoch: 4, clipId: 11});
    workers[0].reply();
    assert.equal(client.active.clipId, 11);
    workers[1].reply();
    assert.equal((await next).epoch, 4);
});
test("malformed, failed and timed-out results release the bounded worker", async () => {
    for (const extra of [{pcm: new Float32Array(1)}, {pcm: Float32Array.from({length: 2000}, () => NaN)},
        {error: "transform_rejected"}]) {
        const worker = fake();
        const client = new Client(() => worker);
        const pending = client.run(new Float32Array(2600), 1.3, {epoch: 0, clipId: 1});
        worker.reply(extra);
        await assert.rejects(pending, /rejected/);
        assert.equal(worker.terminated, 1);
    }
    const worker = fake();
    const client = new Client(() => worker, 1);
    await assert.rejects(client.run(new Float32Array(2600), 1.3, {epoch: 0, clipId: 1}), /timeout/);
    assert.equal(worker.terminated, 1);
    assert.equal(client.active, null);
});
test("bad input and factory failures create no persistent pending state", async () => {
    const client = new Client(() => { throw new Error("synthetic factory failure"); });
    await assert.rejects(client.run(new Float32Array(2600), 1.3, {epoch: 0, clipId: 1}), /failed/);
    assert.equal(client.active, null);
    for (const identity of [null, undefined, {epoch: -1, clipId: 1}, {epoch: 0, clipId: 0}, {epoch: 0.1, clipId: 1}]) {
        await assert.rejects(client.run(new Float32Array(2600), 1.3, identity), /rejected/);
    }
});
test("the actual worker entry point transforms once and echoes only content-free identity", () => {
    const messages = [];
    const context = vm.createContext({Float32Array, module: undefined,
        self: {postMessage: message => messages.push(message)}});
    context.importScripts = () => vm.runInContext(fs.readFileSync(__dirname + "/wsola.js", "utf8"), context);
    vm.runInContext(fs.readFileSync(__dirname + "/wsola-worker.js", "utf8"), context);
    const pcm = new Float32Array(2600);
    const event = {data: {id: 1, epoch: 2, clipId: 3, rate: 1.3, pcm}};
    context.self.onmessage(event);
    context.self.onmessage(event);
    assert.equal(messages.length, 1);
    assert.deepEqual(Object.keys(messages[0]).sort(), ["clipId", "epoch", "id", "pcm"]);
    assert.equal(messages[0].pcm.length, 2000);
});
