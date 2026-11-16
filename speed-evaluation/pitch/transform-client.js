/* Evaluation-only complete-clip adapter; no player/audio interfaces. */
(function (root) {
    "use strict";
    const MAX_SAMPLES = 60 * 24000;
    const FRAME_SAMPLES = 960;
    const MIN_OUTPUT_SAMPLES = 1440;
    const DEFAULT_LIMIT_BYTES = 32 * 1024 * 1024;
    const WORKER_ALLOWANCE_BYTES = 1024 * 1024;
    const ignoreLateReply = () => {};
    const budgetStates = new WeakMap();
    function byteCount(bytes) {
        if (!Number.isSafeInteger(bytes) || bytes < 0) throw new RangeError("memory_bytes_rejected");
    }
    class CaptionSpeedMemoryBudget {
        constructor(limitBytes = DEFAULT_LIMIT_BYTES) {
            byteCount(limitBytes);
            budgetStates.set(this, {limitBytes, usedBytes: 0, reservations: 0});
            Object.freeze(this);
        }
        reserve(bytes) {
            byteCount(bytes);
            const state = budgetStates.get(this);
            if (bytes > state.limitBytes - state.usedBytes) throw new Error("transform_memory_limit");
            state.usedBytes += bytes;
            state.reservations++;
            let held = bytes, released = false;
            return Object.freeze({
                get bytes() { return held; },
                resize(nextBytes) {
                    byteCount(nextBytes);
                    if (released) throw new Error("memory_reservation_released");
                    if (nextBytes - held > state.limitBytes - state.usedBytes) {
                        throw new Error("transform_memory_limit");
                    }
                    state.usedBytes += nextBytes - held;
                    held = nextBytes;
                },
                release() {
                    if (released) return;
                    released = true;
                    state.usedBytes -= held;
                    state.reservations--;
                    held = 0;
                }
            });
        }
        snapshot() {
            const state = budgetStates.get(this);
            return Object.freeze({limitBytes: state.limitBytes, usedBytes: state.usedBytes,
                availableBytes: state.limitBytes - state.usedBytes, reservations: state.reservations});
        }
    }
    const sharedBudget = new CaptionSpeedMemoryBudget();
    function estimateMemory(pcm, rate) {
        if (!(pcm instanceof Float32Array) || pcm.length > MAX_SAMPLES || ![1, 1.15, 1.3].includes(rate)) {
            throw new Error("transform_rejected");
        }
        const outputSamples = rate === 1 ? pcm.length : Math.floor(pcm.length / rate);
        if (rate !== 1 && pcm.length && outputSamples < MIN_OUTPUT_SAMPLES) {
            throw new Error("transform_rejected");
        }
        // A small view can keep its entire caller backing buffer alive.
        const callerBytes = pcm.buffer.byteLength;
        const transferBytes = pcm.length * Float32Array.BYTES_PER_ELEMENT;
        const outputBytes = outputSamples * Float32Array.BYTES_PER_ELEMENT;
        const hasOverlap = rate !== 1 && pcm.length !== 0;
        const weightsBytes = hasOverlap ? outputBytes : 0;
        const windowBytes = hasOverlap ? FRAME_SAMPLES * Float32Array.BYTES_PER_ELEMENT : 0;
        const peakBytes = callerBytes + transferBytes + outputBytes + weightsBytes + windowBytes +
            WORKER_ALLOWANCE_BYTES;
        return Object.freeze({callerBytes, transferBytes, outputBytes, weightsBytes, windowBytes,
            workerAllowanceBytes: WORKER_ALLOWANCE_BYTES, peakBytes, outputSamples});
    }
    function updateRetention(job) {
        if (!job.reaped || job.leaseReleased) return;
        const retained = (job.inputReleased ? 0 : job.callerBytes) +
            (job.outputAccepted && !job.outputReleased ? job.outputBytes : 0);
        if (retained) job.lease.resize(retained);
        else {
            job.lease.release();
            job.leaseReleased = true;
        }
    }
    function releaseInput(job) {
        if (job.inputReleased) return;
        job.inputReleased = true;
        updateRetention(job);
    }
    function rejectedOperation(error) {
        const operation = Promise.reject(error);
        operation.releaseInput = ignoreLateReply;
        return operation;
    }
    function resultFor(job, pcm) {
        return {epoch: job.epoch, clipId: job.clipId, pcm,
            // Release only after dropping this PCM or reserving its next owner/copy.
            release() {
                if (job.outputReleased) return;
                job.outputReleased = true;
                updateRetention(job);
            },
            releaseInput() { releaseInput(job); }};
    }
    class CaptionSpeedTransformClient {
        constructor(workerFactory, timeoutMs = 10000, memoryBudget = sharedBudget) {
            if (!(memoryBudget instanceof CaptionSpeedMemoryBudget)) throw new TypeError("memory_budget_required");
            this.factory = workerFactory;
            this.timeoutMs = timeoutMs;
            this.memoryBudget = memoryBudget;
            this.serial = 0;
            this.active = null;
            this.terminating = new Set();
            this.quarantined = new Set();
        }
        run(pcm, rate, identity) {
            if (this.active) return rejectedOperation(new Error("transform_busy"));
            if (!identity || !Number.isSafeInteger(identity.epoch) || identity.epoch < 0 ||
                !Number.isSafeInteger(identity.clipId) || identity.clipId < 1 ||
                this.serial === Number.MAX_SAFE_INTEGER) {
                return rejectedOperation(new Error("transform_rejected"));
            }
            let memory, lease;
            try {
                memory = estimateMemory(pcm, rate);
                lease = this.memoryBudget.reserve(memory.peakBytes);
            } catch (error) { return rejectedOperation(error); }
            const job = {id: ++this.serial, epoch: identity.epoch, clipId: identity.clipId,
                expectedLength: memory.outputSamples, outputBytes: memory.outputBytes,
                callerBytes: memory.callerBytes, lease, worker: null, timer: null,
                finished: false, reaped: false, leaseReleased: false,
                inputReleased: false, outputAccepted: false, outputReleased: false};
            const operation = new Promise((resolve, reject) => {
                job.resolve = resolve;
                job.reject = reject;
                this.active = job;
                try {
                    job.worker = this.factory();
                    this.attach(job);
                    job.timer = setTimeout(() => this.finish(job, new Error("transform_timeout")), this.timeoutMs);
                    // Reserve the transfer and worker peak before this copy allocates.
                    const copy = pcm.slice();
                    job.worker.postMessage({id: job.id, epoch: job.epoch, clipId: job.clipId,
                        rate, pcm: copy}, [copy.buffer]);
                } catch (_) { this.finish(job, new Error("transform_failed")); }
            });
            // A failure/cancellation has no result object; its caller still owns the source PCM.
            operation.releaseInput = () => releaseInput(job);
            return operation;
        }
        attach(job) {
            job.worker.onmessage = event => {
                if (this.active !== job || job.finished) return;
                const result = event && event.data;
                if (!result || result.id !== job.id || result.epoch !== job.epoch || result.clipId !== job.clipId) return;
                if (result.error || !(result.pcm instanceof Float32Array) ||
                    result.pcm.length !== job.expectedLength || result.pcm.byteOffset !== 0 ||
                    result.pcm.buffer.byteLength !== job.outputBytes ||
                    !result.pcm.every(x => Number.isFinite(x) && Math.abs(x) <= 1.000001)) {
                    this.finish(job, new Error("transform_rejected")); return;
                }
                this.finish(job, null, result.pcm);
            };
            job.worker.onerror = () => this.finish(job, new Error("transform_failed"));
        }
        finish(job, error, output) {
            if (this.active !== job || job.finished) return;
            job.finished = true;
            this.active = null;
            clearTimeout(job.timer);
            job.outputAccepted = !error;
            // A captured queued handler still checks job.finished; installed handlers hold no job/PCM.
            if (job.worker) {
                job.worker.onmessage = ignoreLateReply;
                job.worker.onerror = ignoreLateReply;
            }
            this.reap(job);
            if (error) job.reject(error);
            else job.resolve(resultFor(job, output));
            job.resolve = job.reject = null;
        }
        reap(job) {
            let termination;
            try { termination = job.worker ? job.worker.terminate() : undefined; }
            catch (_) { termination = Promise.reject(new Error("transform_termination_failed")); }
            if (termination && typeof termination.then === "function") {
                this.terminating.add(job);
                job.cleanup = Promise.resolve(termination).then(() => this.reaped(job), () => {
                    this.terminating.delete(job);
                    this.quarantined.add(job);
                    job.worker = null;
                    throw new Error("transform_termination_failed");
                });
                // cancel/run callers may ignore cleanup, but reset/drain can still observe its failure.
                job.cleanup.catch(ignoreLateReply);
            } else {
                this.reaped(job);
                job.cleanup = Promise.resolve();
            }
        }
        reaped(job) {
            this.terminating.delete(job);
            job.worker = null;
            job.reaped = true;
            updateRetention(job);
        }
        cancel() {
            if (!this.active) return this.drain();
            const job = this.active;
            const error = new Error("transform_cancelled");
            error.name = "AbortError";
            this.finish(job, error);
            return job.cleanup;
        }
        drain() {
            const cleanup = Promise.all([...this.terminating].map(job => job.cleanup)).then(() => {
                if (this.quarantined.size) throw new Error("transform_termination_failed");
            });
            cleanup.catch(ignoreLateReply);
            return cleanup;
        }
        reset() {
            this.cancel();
            return this.drain();
        }
        memorySnapshot() {
            return Object.freeze({budget: this.memoryBudget.snapshot(), active: Boolean(this.active),
                terminating: this.terminating.size, quarantined: this.quarantined.size});
        }
    }
    CaptionSpeedTransformClient.MemoryBudget = CaptionSpeedMemoryBudget;
    CaptionSpeedTransformClient.estimateMemory = estimateMemory;
    if (typeof module !== "undefined" && module.exports) module.exports = CaptionSpeedTransformClient;
    else {
        root.CaptionSpeedMemoryBudget = CaptionSpeedMemoryBudget;
        root.CaptionSpeedTransformClient = CaptionSpeedTransformClient;
    }
})(typeof globalThis === "undefined" ? this : globalThis);
