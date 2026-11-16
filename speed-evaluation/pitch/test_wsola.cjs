"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {performance} = require("node:perf_hooks");
const {stretch, maxSamples, sampleRate: SR} = require("./wsola.js");
const {tone, harmonic, chirp, frequency, rms} = require("./measure.cjs");

test("normal speed returns identical, independent PCM without changing the input", () => {
    const input = tone(160);
    const copy = input.slice();
    const output = stretch(input, 1);
    assert.notEqual(output, input);
    assert.deepEqual(output, copy);
    output[5] = 0.75;
    assert.deepEqual(input, copy);
});
for (const rate of [1.15, 1.3]) {
    for (const hz of [110, 160, 220, 440, 880]) {
        test(`${rate}x preserves ${hz} Hz while shortening duration`, () => {
            const input = tone(hz);
            const output = stretch(input, rate);
            assert.equal(output.length, Math.floor(input.length / rate));
            assert.ok(Math.abs(frequency(output) / hz - 1) < 0.003);
            assert.ok(Math.abs(12 * Math.log2(frequency(output) / hz)) < 0.06);
            assert.ok(rms(output) / rms(input) > 0.85);
            assert.ok(rms(output) / rms(input) < 1.05);
            assert.ok(output.every(x => Number.isFinite(x) && Math.abs(x) <= 0.400001));
        });
    }
    test(`${rate}x retains the fundamental of a multi-harmonic voiced fixture`, () => {
        const input = harmonic();
        const output = stretch(input, rate);
        assert.ok(Math.abs(frequency(output) / 160 - 1) < 0.005);
        assert.ok(rms(output) / rms(input) > 0.8);
    });
    test(`${rate}x preserves silence and anchors the final PCM sample`, () => {
        const input = new Float32Array(SR);
        assert.ok(stretch(input, rate).every(x => x === 0));
        input[0] = 0.35;
        input[input.length - 1] = -0.65;
        const output = stretch(input, rate);
        assert.ok(Math.abs(output[0] - input[0]) < 1e-6);
        assert.ok(Math.abs(output[output.length - 1] - input[input.length - 1]) < 1e-6);
    });
    test(`${rate}x is deterministic and does not mutate source PCM`, () => {
        const input = harmonic();
        const copy = input.slice();
        assert.deepEqual(stretch(input, rate), stretch(input, rate));
        assert.deepEqual(input, copy);
    });
    test(`${rate}x preserves the local frequency of a rising-pitch fixture`, () => {
        const output = stretch(chirp(), rate);
        for (const sourceCenter of [0.5, 1, 1.5]) {
            const center = sourceCenter / rate;
            const portion = output.slice(Math.round((center - 0.075) * SR),
                Math.round((center + 0.075) * SR));
            const expectedHz = 220 + 220 * sourceCenter;
            assert.ok(Math.abs(frequency(portion, 0.005) / expectedHz - 1) < 0.025);
        }
    });
    test(`${rate}x anchors both ends at the minimum accepted clip length`, () => {
        const input = tone(160, Math.ceil(1440 * rate) / SR);
        input[0] = 0.35;
        input[input.length - 1] = -0.65;
        const output = stretch(input, rate);
        assert.ok(Math.abs(output[0] - 0.35) < 1e-6);
        assert.ok(Math.abs(output[output.length - 1] + 0.65) < 1e-6);
        assert.ok(output.every(x => Number.isFinite(x) && Math.abs(x) < 1));
        assert.throws(() => stretch(input.slice(1), rate), /short clip/);
    });
    test(`${rate}x maps a voiced pulse envelope onto the shortened content clock`, () => {
        const input = new Float32Array(2 * SR);
        for (const center of [0.4, 0.9, 1.4]) {
            for (let i = Math.round((center - 0.04) * SR); i < Math.round((center + 0.04) * SR); i++) {
                input[i] = 0.4 * Math.sin(2 * Math.PI * 160 * i / SR);
            }
        }
        const output = stretch(input, rate);
        for (const center of [0.4, 0.9, 1.4]) {
            const low = Math.round((center / rate - 0.06) * SR);
            const high = Math.round((center / rate + 0.06) * SR);
            assert.ok(rms(output.slice(low, high)) > 0.1);
        }
        assert.ok(output.every(x => Number.isFinite(x)));
    });
}
test("invalid PCM, unsupported rates and overlong clips are rejected", () => {
    assert.throws(() => stretch([0], 1.15), TypeError);
    for (const rate of [0, 0.5, 1.1, 2, NaN, Infinity]) {
        assert.throws(() => stretch(new Float32Array(2000), rate), RangeError);
    }
    for (const value of [NaN, Infinity, -Infinity, 1.01, -1.01]) {
        assert.throws(() => stretch(Float32Array.of(value), 1), RangeError);
    }
    assert.throws(() => stretch(new Float32Array(maxSamples + 1), 1), RangeError);
    assert.throws(() => stretch(new Float32Array(900), 1.3), /short clip/);
    assert.equal(stretch(new Float32Array(), 1.3).length, 0);
});
test("the 60-second bound remains finite within a conservative 5-second CPU ceiling", () => {
    const input = tone(160, maxSamples / SR);
    const start = performance.now();
    const output = stretch(input, 1.3);
    assert.ok(performance.now() - start < 5000);
    assert.equal(output.length, Math.floor(maxSamples / 1.3));
    assert.ok(output.every(x => Number.isFinite(x)));
    assert.ok(Math.abs(frequency(output) / 160 - 1) < 0.003);
});
