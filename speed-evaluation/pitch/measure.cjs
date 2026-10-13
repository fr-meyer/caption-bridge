"use strict";
const {performance} = require("node:perf_hooks");
const {stretch, sampleRate: SR, frameSamples, maxSamples} = require("./wsola.js");

function tone(hz, seconds = 2) {
    return Float32Array.from({length: Math.round(seconds * SR)}, (_, i) =>
        0.4 * Math.sin(2 * Math.PI * hz * i / SR));
}
function harmonic(seconds = 2) {
    return Float32Array.from({length: Math.round(seconds * SR)}, (_, i) => {
        const phase = 2 * Math.PI * 160 * i / SR;
        return 0.3 * Math.sin(phase) + 0.12 * Math.sin(2 * phase) + 0.07 * Math.sin(3 * phase);
    });
}
function chirp(seconds = 2) {
    return Float32Array.from({length: Math.round(seconds * SR)}, (_, i) => {
        const time = i / SR;
        return 0.4 * Math.sin(2 * Math.PI * (220 * time + 110 * time * time));
    });
}
function frequency(input, trimSeconds = 0.15) {
    const trim = Math.round(trimSeconds * SR);
    let first = null, last = null, count = 0;
    for (let i = trim + 1; i < input.length - trim; i++) {
        if (input[i - 1] <= 0 && input[i] > 0) {
            const crossing = i - 1 + (-input[i - 1]) / (input[i] - input[i - 1]);
            if (first === null) first = crossing;
            last = crossing;
            count++;
        }
    }
    return (count - 1) * SR / (last - first);
}
function rms(input) {
    let energy = 0;
    for (const sample of input) energy += sample * sample;
    return Math.sqrt(energy / input.length);
}
function measure(input, rate, expectedHz, label) {
    const start = performance.now();
    const output = stretch(input, rate);
    const elapsed = performance.now() - start;
    const hz = expectedHz === null ? null : frequency(output);
    return {fixture: label, rate, sample_rate: SR, input_samples: input.length,
        output_samples: output.length, input_seconds: input.length / SR,
        output_seconds: output.length / SR, duration_saved_percent: 100 * (1 - output.length / input.length),
        expected_frequency_hz: expectedHz, measured_frequency_hz: hz,
        pitch_shift_semitones: hz === null ? null : 12 * Math.log2(hz / expectedHz),
        rms_ratio: rms(input) ? rms(output) / rms(input) : null,
        processing_ms: elapsed, allocated_pcm_bytes: rate === 1 ? input.byteLength + output.byteLength :
            input.byteLength + 2 * output.byteLength + 4 * frameSamples,
        audible_output: false, provider_requests: 0, microphone_capture: false};
}
module.exports = {tone, harmonic, chirp, frequency, rms, measure, SR};
if (require.main === module) {
    const rows = [];
    for (const rate of [1, 1.15, 1.3]) {
        for (const hz of [110, 160, 220, 440, 880]) rows.push(measure(tone(hz), rate, hz, "tone"));
        rows.push(measure(harmonic(), rate, 160, "harmonics"));
    }
    rows.push(measure(tone(160, maxSamples / SR), 1.3, 160, "maximum-60-second-clip"));
    process.stdout.write(JSON.stringify({schema_version: 1, mechanism: "complete-clip mono WSOLA",
        generated_at_utc: new Date().toISOString(), runtime: process.version, platform: process.platform,
        architecture: process.arch, scope: "generated buffers only, no browser or device",
        measurements: rows}, null, 2) + "\n");
}
