// Original public test signal, not speech or a human quality fixture.
(function (root) {
    "use strict";
    const sampleRate = 24000, samples = 15840, chunkSamples = 2400;
    function generate() {
        const pcm = new Float32Array(samples);
        for (let i = 0; i < samples; i++) {
            const t = i / sampleRate;
            // Pauses and changing harmonics exercise nonzero PCM and a 60 ms tail.
            const voiced = (t < .18 || (t >= .24 && t < .47) || t >= .53);
            const envelope = Math.min(1, (i % 2400) / 120, (2400 - i % 2400) / 120);
            pcm[i] = voiced ? envelope * (.25 * Math.sin(2 * Math.PI * 173 * t) +
                .07 * Math.sin(2 * Math.PI * 397 * t)) : 0;
        }
        return pcm;
    }
    root.CaptionTimingFixture = Object.freeze({id: "generated-harmonics-pauses-v1",
        sampleRate, samples, chunkSamples, generate});
})(typeof module === "object" ? module.exports : globalThis);
