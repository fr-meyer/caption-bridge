"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {Worker} = require("node:worker_threads");
const Client = require("./transform-client.js");
const Budget = Client.MemoryBudget;
const identity = clipId => ({epoch: 4, clipId});
const input = () => new Float32Array(2600);
function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return {promise, resolve, reject};
}
function fake(termination) {
    return {
        terminated: 0,
        postMessage(message, transfer) {
            this.message = structuredClone(message, {transfer});
            this.detachedTransferBytes = transfer[0].byteLength;
            this.oldHandler = this.onmessage;
        },
        terminate() { this.terminated++; return termination && termination.promise; },
        reply(extra = {}, handler = this.onmessage) {
            handler({data: {id: this.message.id, epoch: this.message.epoch, clipId: this.message.clipId,
                pcm: new Float32Array(Math.floor(this.message.pcm.length / this.message.rate)), ...extra}});
        }
    };
}
function fixture(limit, termination) {
    const worker = fake(termination);
    const budget = new Budget(limit);
    const client = new Client(() => worker, 1000, budget);
    return {worker, budget, client};
}
test("memory contract reserves shared queued PCM and rejects before worker/copy allocation", async () => {
    const pcm = input();
    const cost = Client.estimateMemory(pcm, 1.3);
    const budget = new Budget(cost.peakBytes);
    const queue = budget.reserve(4);
    let factories = 0;
    const client = new Client(() => { factories++; return fake(); }, 1000, budget);
    await assert.rejects(client.run(pcm, 1.3, identity(1)), /memory_limit/);
    assert.equal(factories, 0);
    assert.equal(budget.snapshot().usedBytes, 4);
    queue.release();
    const pending = client.run(pcm, 1.3, identity(2));
    assert.equal(budget.snapshot().usedBytes, cost.peakBytes);
    const cancelled = assert.rejects(pending, error => error.name === "AbortError");
    await client.cancel();
    await cancelled;
    assert.equal(budget.snapshot().usedBytes, cost.callerBytes);
    pending.releaseInput();
    assert.equal(budget.snapshot().usedBytes, 0);
});
test("memory contract accounts the entire input backing and maximum known WSOLA allocations", async () => {
    const pcm = new Float32Array(1440000);
    const cost = Client.estimateMemory(pcm, 1.15);
    assert.equal(cost.callerBytes, 5760000);
    assert.equal(cost.transferBytes, 5760000);
    assert.equal(cost.outputBytes, 5008692);
    assert.equal(cost.weightsBytes, 5008692);
    assert.equal(cost.windowBytes, 3840);
    assert.equal(cost.peakBytes, 22589800);
    const view = new Float32Array(new ArrayBuffer(4 * 1024 * 1024), 16, 2600);
    const {client, budget} = fixture(2 * 1024 * 1024);
    await assert.rejects(client.run(view, 1.3, identity(1)), /memory_limit/);
    assert.equal(budget.snapshot().usedBytes, 0);
    assert.equal(Client.estimateMemory(view, 1.3).callerBytes, view.buffer.byteLength);
});
test("memory contract retains detached transfer charge and returned PCM until owner release", async () => {
    const pcm = input();
    pcm[4] = 0.25;
    const cost = Client.estimateMemory(pcm, 1.3);
    const {worker, client, budget} = fixture(cost.peakBytes);
    const pending = client.run(pcm, 1.3, identity(1));
    assert.equal(worker.detachedTransferBytes, 0);
    assert.equal(pcm.byteLength, 10400);
    assert.equal(pcm[4], 0.25);
    assert.equal(budget.snapshot().usedBytes, cost.peakBytes);
    worker.reply();
    const result = await pending;
    assert.equal(budget.snapshot().usedBytes, cost.callerBytes + cost.outputBytes);
    result.releaseInput();
    pending.releaseInput(); // Same idempotent owner acknowledgment is exposed on both handles.
    assert.equal(budget.snapshot().usedBytes, cost.outputBytes);
    const scheduledCopy = budget.reserve(cost.outputBytes);
    assert.equal(budget.snapshot().usedBytes, 2 * cost.outputBytes);
    result.release();
    result.release();
    assert.equal(budget.snapshot().usedBytes, cost.outputBytes);
    scheduledCopy.release();
    assert.deepEqual(budget.snapshot(), {limitBytes: cost.peakBytes, usedBytes: 0,
        availableBytes: cost.peakBytes, reservations: 0});
});
test("memory contract enforces one aggregate limit across independent client instances", async () => {
    const pcm = input();
    const cost = Client.estimateMemory(pcm, 1.3);
    const budget = new Budget(cost.peakBytes);
    const worker = fake();
    let secondFactories = 0;
    const one = new Client(() => worker, 1000, budget);
    const two = new Client(() => { secondFactories++; return fake(); }, 1000, budget);
    const pending = one.run(pcm, 1.3, identity(1));
    await assert.rejects(two.run(pcm, 1.3, identity(2)), /memory_limit/);
    assert.equal(secondFactories, 0);
    const rejection = assert.rejects(pending, /cancelled/);
    await one.cancel();
    await rejection;
    pending.releaseInput();
    const next = two.run(pcm, 1.3, identity(3));
    const nextRejection = assert.rejects(next, /cancelled/);
    await two.cancel();
    await nextRejection;
    next.releaseInput();
    assert.equal(secondFactories, 1);
    assert.equal(budget.snapshot().usedBytes, 0);
});
test("memory contract async reset keeps cancelled transfer charged until worker acknowledgment", async () => {
    const pcm = input();
    const cost = Client.estimateMemory(pcm, 1.3);
    const termination = deferred();
    const {worker, budget, client} = fixture(cost.peakBytes, termination);
    const pending = client.run(pcm, 1.3, identity(1));
    const rejection = assert.rejects(pending, /cancelled/);
    const reset = client.reset();
    await rejection;
    pending.releaseInput();
    assert.equal(client.memorySnapshot().terminating, 1);
    assert.equal(budget.snapshot().usedBytes, cost.peakBytes);
    await assert.rejects(client.run(pcm, 1.3, identity(2)), /memory_limit/);
    worker.reply({}, worker.oldHandler);
    assert.equal(budget.snapshot().usedBytes, cost.peakBytes);
    let resetDone = false;
    reset.then(() => { resetDone = true; });
    await Promise.resolve();
    assert.equal(resetDone, false);
    termination.resolve(0);
    await reset;
    assert.equal(client.memorySnapshot().terminating, 0);
    assert.equal(budget.snapshot().usedBytes, 0);
});
test("memory contract late old reply cannot finish or release a newer worker reservation", async () => {
    const pcm = input();
    const cost = Client.estimateMemory(pcm, 1.3);
    const oldTermination = deferred();
    const workers = [fake(oldTermination), fake()];
    const budget = new Budget(2 * cost.peakBytes);
    let count = 0;
    const client = new Client(() => workers[count++], 1000, budget);
    const old = client.run(pcm, 1.3, identity(1));
    const oldRejection = assert.rejects(old, /cancelled/);
    const cleanup = client.cancel();
    await oldRejection;
    old.releaseInput();
    const next = client.run(pcm, 1.3, identity(2));
    assert.equal(budget.snapshot().usedBytes, 2 * cost.peakBytes);
    workers[0].reply({}, workers[0].oldHandler);
    assert.equal(client.active.clipId, 2);
    assert.equal(budget.snapshot().usedBytes, 2 * cost.peakBytes);
    oldTermination.resolve(0);
    await cleanup;
    assert.equal(budget.snapshot().usedBytes, cost.peakBytes);
    workers[1].reply();
    const result = await next;
    assert.equal(result.clipId, 2);
    result.releaseInput();
    assert.equal(budget.snapshot().usedBytes, cost.outputBytes);
    result.release();
    assert.equal(budget.snapshot().usedBytes, 0);
});
test("memory contract output released before async termination remains charged until reap", async () => {
    const pcm = input();
    const cost = Client.estimateMemory(pcm, 1.3);
    const termination = deferred();
    const {worker, budget, client} = fixture(cost.peakBytes, termination);
    const pending = client.run(pcm, 1.3, identity(1));
    worker.reply();
    const result = await pending;
    result.release();
    result.releaseInput();
    assert.equal(budget.snapshot().usedBytes, cost.peakBytes);
    termination.resolve(0);
    await client.drain();
    assert.equal(budget.snapshot().usedBytes, 0);
});
test("memory contract repeated cancellation is bounded while earlier worker resets are pending", async () => {
    const pcm = input();
    const cost = Client.estimateMemory(pcm, 1.3);
    const terminations = [deferred(), deferred()];
    const workers = terminations.map(fake);
    const budget = new Budget(2 * cost.peakBytes);
    let count = 0;
    const client = new Client(() => workers[count++], 1000, budget);
    for (let i = 0; i < workers.length; i++) {
        const pending = client.run(pcm, 1.3, identity(i + 1));
        const rejection = assert.rejects(pending, /cancelled/);
        client.cancel();
        await rejection;
        pending.releaseInput();
    }
    assert.equal(client.memorySnapshot().terminating, 2);
    assert.equal(budget.snapshot().usedBytes, 2 * cost.peakBytes);
    await assert.rejects(client.run(pcm, 1.3, identity(3)), /memory_limit/);
    assert.equal(count, 2);
    const reset = client.reset();
    terminations[0].resolve(0);
    await Promise.resolve();
    assert.equal(budget.snapshot().usedBytes, cost.peakBytes);
    workers[0].reply({}, workers[0].oldHandler);
    assert.equal(budget.snapshot().usedBytes, cost.peakBytes);
    terminations[1].resolve(0);
    await reset;
    assert.equal(budget.snapshot().usedBytes, 0);
});
test("memory contract failed termination quarantines in-flight bytes and reset reports fixed error", async () => {
    for (const synchronous of [false, true]) {
        const pcm = input();
        const cost = Client.estimateMemory(pcm, 1.3);
        const termination = deferred();
        const {worker, budget, client} = fixture(cost.peakBytes, termination);
        if (synchronous) worker.terminate = () => { throw new Error("synthetic termination failure"); };
        const pending = client.run(pcm, 1.3, identity(1));
        const rejection = assert.rejects(pending, /cancelled/);
        const reset = client.reset();
        if (!synchronous) termination.reject(new Error("synthetic termination failure"));
        await rejection;
        pending.releaseInput();
        await assert.rejects(reset, /^Error: transform_termination_failed$/);
        assert.equal(client.memorySnapshot().quarantined, 1);
        assert.equal(budget.snapshot().usedBytes, cost.peakBytes);
        await assert.rejects(client.run(pcm, 1.3, identity(2)), /memory_limit/);
    }
});
test("memory contract factory, post, timeout and oversized result backing preserve bounded cleanup", async () => {
    const pcm = input();
    const cost = Client.estimateMemory(pcm, 1.3);
    for (const failure of ["factory", "post", "worker_error", "timeout", "backing"]) {
        const budget = new Budget(cost.peakBytes);
        const worker = fake();
        if (failure === "post") worker.postMessage = () => { throw new Error("synthetic post failure"); };
        const client = new Client(() => {
            if (failure === "factory") throw new Error("synthetic factory failure");
            return worker;
        }, failure === "timeout" ? 5 : 1000, budget);
        const pending = client.run(pcm, 1.3, identity(1));
        if (failure === "worker_error") worker.onerror();
        if (failure === "backing") worker.reply({pcm: new Float32Array(new ArrayBuffer(2000 * 4 + 4), 0, 2000)});
        await assert.rejects(pending, /failed|timeout|rejected/);
        await client.drain();
        assert.equal(budget.snapshot().usedBytes, cost.callerBytes, failure);
        pending.releaseInput();
        assert.equal(budget.snapshot().usedBytes, 0, failure);
        assert.equal(client.active, null, failure);
    }
});
test("memory contract reservation resize and release cannot underflow or overcommit", () => {
    const budget = new Budget(64);
    assert.equal(Object.isFrozen(budget), true);
    for (const bytes of [-1, 0.5, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
        assert.throws(() => budget.reserve(bytes), /memory_bytes_rejected/);
    }
    const lease = budget.reserve(32);
    assert.throws(() => lease.resize(65), /memory_limit/);
    assert.equal(lease.bytes, 32);
    lease.resize(64);
    assert.equal(budget.snapshot().availableBytes, 0);
    lease.resize(8);
    lease.release();
    lease.release();
    assert.equal(budget.snapshot().usedBytes, 0);
    assert.equal(budget.snapshot().reservations, 0);
    assert.throws(() => lease.resize(1), /released/);
});
test("memory contract real Node worker reset awaits asynchronous transferred-buffer termination", async () => {
    const started = deferred();
    const raw = new Worker(`
        const {parentPort} = require('node:worker_threads');
        parentPort.once('message', message => {
            parentPort.postMessage({started: true, samples: message.pcm.length});
            Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 5000);
        });
    `, {eval: true});
    const worker = {
        postMessage(message, transfer) {
            raw.postMessage(message, transfer);
            this.detachedTransferBytes = transfer[0].byteLength;
        },
        terminate: () => raw.terminate()
    };
    raw.on("message", message => {
        if (message.started) started.resolve(message.samples);
        else worker.onmessage({data: message});
    });
    raw.on("error", error => started.reject(error));
    const pcm = input();
    const cost = Client.estimateMemory(pcm, 1.3);
    const budget = new Budget(cost.peakBytes);
    const client = new Client(() => worker, 1000, budget);
    try {
        const pending = client.run(pcm, 1.3, identity(1));
        const rejection = assert.rejects(pending, /cancelled/);
        assert.equal(await started.promise, 2600);
        assert.equal(worker.detachedTransferBytes, 0);
        const reset = client.reset();
        pending.releaseInput();
        assert.equal(client.memorySnapshot().terminating, 1);
        assert.equal(budget.snapshot().usedBytes, cost.peakBytes);
        await rejection;
        await reset;
        assert.equal(client.memorySnapshot().terminating, 0);
        assert.equal(budget.snapshot().usedBytes, 0);
        assert.equal(pcm.byteLength, 10400);
    } finally { await raw.terminate(); }
});
