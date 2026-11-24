"use strict";
// Actual wall-clock execution of the production player into an IN-MEMORY sink.
// The sink models Web Audio. It is not a browser, digital loopback or acoustic output.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const crypto = require("node:crypto");
const {performance} = require("node:perf_hooks");
const {CaptionTimingFixture: fixture} = require("./generated_fixture.cjs");
const {ChunkTimingProbe} = require("./browser_probe.cjs");
const root = path.resolve(__dirname, "../..");
const sandbox = {window: {}, performance, setTimeout, clearTimeout, atob,
    Float32Array, Uint8Array, DataView, Map, Set, Number};
vm.runInNewContext(fs.readFileSync(path.join(root, "app/static/pcm-player.js"), "utf8"),
    sandbox, {timeout: 1000});
const sleep = ms => new Promise(resolve => setTimeout(resolve, Math.max(0, ms)));
async function sleepUntil(deadline, clock) {
    // Native timers may wake slightly early. Never label that as on-time delivery.
    while (clock() < deadline) await sleep(deadline - clock());
}
const encode = pcm => {
    const bytes = Buffer.alloc(pcm.length * 4);
    pcm.forEach((value, i) => bytes.writeFloatLE(value, i * 4));
    return bytes.toString("base64");
};
async function observe(mode, clipId, origin, pcm) {
    const nodes = new Set(), scheduled = [], deliveries = [];
    let starts = 0, completions = 0, stats, readyMs = null, resolveDone, rejectDone;
    const done = new Promise((resolve, reject) => {resolveDone = resolve; rejectDone = reject;});
    const clock = () => performance.now() - origin;
    const destination = {};
    const audio = {get currentTime() {return clock() / 1000;}, destination,
        resume: () => Promise.resolve(),
        createBuffer: (_channels, length, rate) => {
            const data = new Float32Array(length);
            return {duration: length / rate, getChannelData: () => data};
        },
        createBufferSource: () => {
            const node = {buffer: null, timer: null,
                connect(target) {assert.equal(target, destination);}, disconnect() {},
                start(at) {
                    const data = this.buffer.getChannelData(0);
                    scheduled.push({start_ms: at * 1000,
                        end_ms: (at + this.buffer.duration) * 1000, data});
                    nodes.add(this);
                    this.timer = setTimeout(() => {nodes.delete(this); this.onended?.();},
                        Math.max(0, (at + this.buffer.duration) * 1000 - clock()));
                },
                stop() {clearTimeout(this.timer); nodes.delete(this);}
            };
            return node;
        }};
    const player = new sandbox.window.CaptionPcmPlayer({context: () => audio, clock,
        streaming: () => mode === "streaming", canPlay: () => true,
        onFirstChunk() {}, onStart() {starts++;}, onComplete(_msg, value) {
            stats = value; completions++; resolveDone();
        }, onError() {rejectDone(Error("player_failed"));}, onLocked() {rejectDone(Error("player_locked"));}});
    const probe = new ChunkTimingProbe({clipId, epoch: 0}).attach(player);
    const watchdog = setTimeout(() => rejectDone(Error("observation_deadline")), 4000);
    // Register a rejection handler before delivery so errors cannot go unhandled.
    done.catch(() => {});
    try {
        const anchor = clock();
        let index = 0;
        for (let offset = 0; offset < pcm.length; offset += fixture.chunkSamples) {
            const nominal = offset / fixture.sampleRate * 1000;
            await sleepUntil(anchor + nominal, clock);
            const before = clock(), data = encode(pcm.subarray(offset, offset + fixture.chunkSamples));
            player.receive({clip_id: clipId, tts_epoch: 0, chunk_index: index++, data, is_last: false});
            deliveries.push({chunk_index: index - 1, samples: Math.min(fixture.chunkSamples, pcm.length - offset),
                nominal_offset_ms: nominal, yield_offset_ms: before - anchor,
                deadline_lateness_ms: Math.max(0, before - anchor - nominal),
                consumer_work_ms: clock() - before});
            const clip = player.clips.get("0:" + clipId);
            if (clip?.readyAt !== null && clip?.readyAt !== undefined) readyMs ??= clip.readyAt;
        }
        await sleepUntil(anchor + pcm.length / fixture.sampleRate * 1000, clock);
        player.receive({clip_id: clipId, tts_epoch: 0, chunk_index: index, data: "", is_last: true});
        readyMs ??= player.clips.get("0:" + clipId)?.readyAt;
        await done;
        const report = probe.report();
        assert.equal(starts, 1); assert.equal(completions, 1);
        assert.equal(report.completed, true); assert.equal(report.rejected, 0);
        assert.equal(report.chunks.length, Math.ceil(pcm.length / fixture.chunkSamples));
        assert.equal(player.bytes, 0); assert.equal(player.clips.size, 0); assert.equal(nodes.size, 0);
        let offset = 0;
        for (const row of scheduled) {
            assert.deepEqual(row.data, pcm.subarray(offset, offset + row.data.length));
            offset += row.data.length;
        }
        assert.equal(offset, pcm.length);
        return {clip_id: clipId, mode, deliveries, probe: report, production_stats: stats,
            probe_runtime: "node_vm_with_modeled_audio",
            source_trace: {schema_version: 1, clock_domain: "source_monotonic_offsets",
                completed: true, chunks: deliveries},
            comparator_row: {clip_id: clipId <= 2 ? 1 : 2, ready_ms: readyMs,
                start_ms: scheduled[0].start_ms, end_ms: scheduled.at(-1).end_ms},
            starts, completions, exact_pcm_samples: offset, remaining_bytes: player.bytes,
            remaining_clips: player.clips.size, live_sink_nodes: nodes.size};
    } finally {
        clearTimeout(watchdog); player.cancelAll(); probe.detach();
        for (const node of nodes) node.stop();
        for (const row of scheduled) row.data.fill(0);
    }
}
async function main() {
    const pcm = fixture.generate(), bytes = Buffer.from(encode(pcm), "base64");
    const identity = crypto.createHash("sha256").update(bytes).digest("hex");
    const origin = performance.now(), observations = [];
    try {
        for (const [i, mode] of ["buffered", "streaming", "streaming", "buffered"].entries())
            observations.push(await observe(mode, i + 1, origin, pcm));
    } finally {pcm.fill(0); bytes.fill(0);}
    const comparison = {fixture_id: identity,
        baseline: observations.filter(row => row.mode === "buffered").map(row => row.comparator_row),
        candidate: observations.filter(row => row.mode === "streaming").map(row => row.comparator_row)};
    console.log(JSON.stringify({schema_version: 1,
        scope: "actual software scheduling with modeled in-memory sink",
        clock: "real monotonic performance.now; no fake clock advancement",
        fixture: {id: fixture.id, sha256: identity, sample_rate: fixture.sampleRate,
            samples: fixture.samples, chunk_samples: fixture.chunkSamples, content: "generated signal, not speech"},
        order: ["buffered", "streaming", "streaming", "buffered"], observations, comparison,
        real_browser: false, digital_output_measured: false, acoustic_measured: false,
        human_quality: "pending", provider_requests: 0, physical_streams: 0,
        comparator_gap_scope: "includes intentional inter-trial idle, not output continuity",
        acceptance: "not_evaluated"}));
}
main().catch(() => {console.error("scheduling_observation_failed"); process.exitCode = 1;});
