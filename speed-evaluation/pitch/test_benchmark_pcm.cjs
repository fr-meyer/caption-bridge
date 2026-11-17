"use strict";
const assert = require("node:assert/strict");
const {benchmark} = require("./benchmark_pcm.cjs");
const pcm = Float32Array.from({length: 4800}, (_, i) => .2*Math.sin(i*.1));
const before = pcm.slice();
const result = benchmark(pcm, 2);
assert.deepEqual(pcm, before);
assert.deepEqual(result.rows.map(r => r.rate), [1, 1.15, 1.3]);
for (const row of result.rows) {
    assert.equal(row.output_samples, Math.floor(pcm.length/row.rate));
    assert.ok(row.processing_p95_ms >= row.processing_p50_ms);
}
assert.equal(result.human_quality, "pending");
for (const bad of [[], new Float32Array(2), new Float32Array(4800).fill(NaN)]) {
    assert.throws(() => benchmark(bad, 1));
}
assert.throws(() => benchmark(pcm, 31));
console.log("benchmark PCM contracts passed");
const balanced = benchmark(pcm, 6);
assert.equal(balanced.order_balanced, true);
assert.equal(result.order_balanced, false);
assert.equal(new Set(balanced.trial_order.map(order => order.join(','))).size, 6);
for (const rate of [1, 1.15, 1.3]) {
    for (let position = 0; position < 3; position++) {
        assert.equal(balanced.trial_order.filter(order => order[position] === rate).length, 2);
    }
}
assert.equal(balanced.human_quality, 'pending');
