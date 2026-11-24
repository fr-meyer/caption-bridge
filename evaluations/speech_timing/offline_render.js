/* Actual OfflineAudioContext rendering only. Never create a realtime AudioContext. */
(function (root) {
    "use strict";
    const fixture = root.CaptionTimingFixture;
    const sleep = ms => new Promise(resolve => setTimeout(resolve, Math.max(0, ms)));
    function encode(pcm) {
        const bytes = new Uint8Array(pcm.length * 4), view = new DataView(bytes.buffer);
        pcm.forEach((value, i) => view.setFloat32(i * 4, value, true));
        return btoa(String.fromCharCode(...bytes));
    }
    root.observeOfflinePlayback = async function () {
        const pcm = fixture.generate(), rows = [];
        try {
            for (const [i, mode] of ["buffered", "streaming", "streaming", "buffered"].entries()) {
                const offline = new OfflineAudioContext(1, fixture.samples + 960, fixture.sampleRate);
                // Offline contexts cannot resume before startRendering. This adapter only
                // acknowledges readiness; the real engine renders AFTER all packet delivery.
                const context = {get currentTime() {return offline.currentTime;},
                    get destination() {return offline.destination;}, resume: () => Promise.resolve(),
                    createBuffer: (...args) => offline.createBuffer(...args),
                    createBufferSource: () => offline.createBufferSource()};
                let starts = 0, completes = 0, failure = false;
                const player = new CaptionPcmPlayer({context: () => context,
                    streaming: () => mode === "streaming", canPlay: () => true,
                    onFirstChunk() {}, onStart() {starts++;}, onComplete() {completes++;},
                    onError() {failure = true;}, onLocked() {failure = true;}});
                const probe = new ChunkTimingProbe({clipId: i + 1, epoch: 0}).attach(player);
                const anchor = performance.now();
                try {
                    let index = 0;
                    for (let offset = 0; offset < pcm.length; offset += fixture.chunkSamples) {
                        await sleep(anchor + offset / fixture.sampleRate * 1000 - performance.now());
                        player.receive({clip_id: i + 1, tts_epoch: 0, chunk_index: index++,
                            data: encode(pcm.subarray(offset, offset + fixture.chunkSamples)), is_last: false});
                    }
                    await sleep(anchor + pcm.length / fixture.sampleRate * 1000 - performance.now());
                    player.receive({clip_id: i + 1, tts_epoch: 0, chunk_index: index, data: "", is_last: true});
                    await Promise.resolve(); await Promise.resolve();
                    const rendered = await offline.startRendering();
                    // startRendering resolves after rendering, not necessarily after all
                    // onended tasks have been delivered. Observe completion explicitly.
                    for (let n = 0; n < 100 && completes === 0 && !failure; n++) await sleep(5);
                    const output = rendered.getChannelData(0);
                    let maxError = 0, outsidePeak = 0;
                    for (let n = 0; n < pcm.length; n++)
                        maxError = Math.max(maxError, Math.abs(output[n + 480] - pcm[n]));
                    for (let n = 0; n < output.length; n++)
                        if (n < 480 || n >= pcm.length + 480)
                            outsidePeak = Math.max(outsidePeak, Math.abs(output[n]));
                    const report = probe.report();
                    rows.push({mode, starts, completes, failure, max_error: maxError,
                        outside_peak: outsidePeak, rendered_samples: output.length,
                        remaining_bytes: player.bytes, remaining_clips: player.clips.size,
                        first_receive_to_submit_ms: report.schedules[0].submitted_offset_ms,
                        probe: report});
                    output.fill(0);
                } finally {player.cancelAll(); probe.detach();}
            }
            return {scope: "offline digital render, not realtime output or loopback",
                fixture_id: fixture.id, sample_rate: fixture.sampleRate, input_samples: pcm.length,
                real_browser: true, acoustic_measured: false, realtime_underruns_measured: false,
                physical_streams: 0, human_quality: "pending", acceptance: "not_evaluated", rows};
        } finally {pcm.fill(0);}
    };
})(globalThis);
