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
    const rows = [];
    for (const rate of [1, 1.15, 1.3]) {
        const times = [];
        let output;
        for (let i = 0; i < repetitions; i++) {
            const start = performance.now();
            output = stretch(pcm, rate);
            times.push(performance.now() - start);
        }
        times.sort((a, b) => a - b);
        const mid = Math.floor(times.length / 2);
        rows.push({rate, repetitions, output_samples: output.length,
            duration_ms: output.length * 1000 / sampleRate,
            processing_p50_ms: times.length % 2 ? times[mid] : (times[mid-1]+times[mid])/2,
            processing_p95_ms: times[Math.ceil(times.length * .95)-1],
            pcm_input_output_bytes: pcm.byteLength + output.byteLength});
    }
    return {scope: "offline Node transform only", fixture_sha256:
        crypto.createHash("sha256").update(bytes).digest("hex"), sample_rate: sampleRate,
        input_samples: pcm.length, human_quality: "pending", browser_startup: "unmeasured", rows};
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
