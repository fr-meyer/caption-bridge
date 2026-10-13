/* Evaluation-only complete-clip adapter. Cancellation terminates pending work. */
(function (root) {
    "use strict";
    const MAX_SAMPLES = 60 * 24000;
    class CaptionSpeedTransformClient {
        constructor(workerFactory, timeoutMs = 10000) {
            this.factory = workerFactory;
            this.timeoutMs = timeoutMs;
            this.serial = 0;
            this.active = null;
        }
        run(pcm, rate, identity) {
            if (this.active) return Promise.reject(new Error("transform_busy"));
            if (!(pcm instanceof Float32Array) || pcm.length > MAX_SAMPLES ||
                ![1, 1.15, 1.3].includes(rate) || !identity || !Number.isInteger(identity.epoch) || identity.epoch < 0 ||
                !Number.isInteger(identity.clipId) || identity.clipId < 1) {
                return Promise.reject(new Error("transform_rejected"));
            }
            return new Promise((resolve, reject) => {
                const job = {id: ++this.serial, epoch: identity.epoch, clipId: identity.clipId,
                    expectedLength: rate === 1 ? pcm.length : Math.floor(pcm.length / rate),
                    worker: null, timer: null, resolve, reject};
                function finish(error, output) {
                    if (this.active !== job) return;
                    this.active = null;
                    clearTimeout(job.timer);
                    if (job.worker) job.worker.terminate();
                    if (error) reject(error);
                    else resolve({epoch: job.epoch, clipId: job.clipId, pcm: output});
                }
                job.finish = finish.bind(this);
                this.active = job;
                try {
                    job.worker = this.factory();
                    job.worker.onmessage = event => {
                        if (this.active !== job) return;
                        const result = event.data;
                        if (!result || result.id !== job.id || result.epoch !== job.epoch ||
                            result.clipId !== job.clipId) return;
                        if (result.error || !(result.pcm instanceof Float32Array) ||
                            result.pcm.length !== job.expectedLength ||
                            !result.pcm.every(x => Number.isFinite(x) && Math.abs(x) <= 1.000001)) {
                            job.finish(new Error("transform_rejected")); return;
                        }
                        job.finish(null, result.pcm);
                    };
                    job.worker.onerror = () => job.finish(new Error("transform_failed"));
                    job.timer = setTimeout(() => job.finish(new Error("transform_timeout")), this.timeoutMs);
                    // Copy before transfer: callers retain their canonical/transient input buffer.
                    const copy = pcm.slice();
                    job.worker.postMessage({id: job.id, epoch: job.epoch, clipId: job.clipId,
                        rate, pcm: copy}, [copy.buffer]);
                } catch (_) { job.finish(new Error("transform_failed")); }
            });
        }
        cancel() {
            if (!this.active) return;
            const error = new Error("transform_cancelled");
            error.name = "AbortError";
            this.active.finish(error);
        }
    }
    if (typeof module !== "undefined" && module.exports) module.exports = CaptionSpeedTransformClient;
    else root.CaptionSpeedTransformClient = CaptionSpeedTransformClient;
})(typeof globalThis === "undefined" ? this : globalThis);
