"use strict";
// Evaluation only. Float32 little-endian mono 24 kHz public/local PCM, no playback.
const fs = require("node:fs");
const crypto = require("node:crypto");
const {performance} = require("node:perf_hooks");
const {stretch, sampleRate, maxSamples} = require("./wsola.js");
function benchmark(pcm, repetitions = 30) {
    if (!(pcm instanceof Float32Array) || pcm.length < 1872 || pcm.length > maxSamples ||
        !Number.isInteger(repetitions) || repetitions < 1 || repetitions > 30) {
        throw new RangeError("invalid bounded fixture");
    }
    const bytes = Buffer.alloc(pcm.length * 4);
    pcm.forEach((value, i) => bytes.writeFloatLE(value, i * 4));
    // Rotate all six permutations: every rate occupies every position equally
    // in the default 30 repetitions. Avoid rate-blocked warm-up/thermal bias.
    const orders = [[1, 1.15, 1.3], [1.3, 1.15, 1], [1.15, 1.3, 1],
        [1, 1.3, 1.15], [1.3, 1, 1.15], [1.15, 1, 1.3]];
    const measurements = new Map([1, 1.15, 1.3].map(rate => [rate, []]));
    const outputLengths = new Map();
    const trialOrder = [];
    for (let i = 0; i < repetitions; i++) {
        const order = orders[i % orders.length];
        trialOrder.push(order.slice());
        for (const rate of order) {
            const start = performance.now();
            const output = stretch(pcm, rate);
            measurements.get(rate).push(performance.now() - start);
            outputLengths.set(rate, output.length);
        }
    }
    const rows = [1, 1.15, 1.3].map(rate => {
        const times = measurements.get(rate).sort((a, b) => a - b);
        const mid = Math.floor(times.length / 2);
        const length = outputLengths.get(rate);
        return {rate, repetitions, output_samples: length,
            duration_ms: length * 1000 / sampleRate,
            processing_p50_ms: times.length % 2 ? times[mid] : (times[mid-1]+times[mid])/2,
            processing_p95_ms: times[Math.ceil(times.length * .95)-1],
            pcm_input_output_bytes: pcm.byteLength + length * 4};
    });
    return {scope: "offline Node transform only", fixture_sha256:
        crypto.createHash("sha256").update(bytes).digest("hex"), sample_rate: sampleRate,
        input_samples: pcm.length, trial_order: trialOrder,
        order_balanced: repetitions % 6 === 0, human_quality: "pending", browser_startup: "unmeasured", rows};
}
module.exports = {benchmark};
if (require.main === module) {
    try {
        const path = process.argv[2];
        const size = fs.statSync(path).size;
        if (size > maxSamples * 4 || size % 4) throw new Error("invalid PCM file");
        const bytes = fs.readFileSync(path);
        const pcm = Float32Array.from({length: bytes.length/4}, (_, i) => bytes.readFloatLE(i*4));
        console.log(JSON.stringify(benchmark(pcm)));
    } catch (_) {
        console.error("fixture_rejected");
        process.exitCode = 1;
    }
}
