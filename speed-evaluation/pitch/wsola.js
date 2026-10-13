/* Evaluation only: complete, mono 24 kHz PCM; no audio or application interfaces. */
(function (root) {
    "use strict";
    const SAMPLE_RATE = 24000;
    const FRAME = 960; // 40 ms; half-frame overlap.
    const HOP = 480;
    const SEARCH = 240; // +/- 10 ms around the fixed analysis clock.
    const MAX_SAMPLES = 60 * SAMPLE_RATE;
    const RATES = [1, 1.15, 1.3];

    function stretch(input, rate) {
        if (!(input instanceof Float32Array)) throw new TypeError("mono Float32Array required");
        if (!RATES.includes(rate)) throw new RangeError("rate must be 1, 1.15 or 1.3");
        if (input.length > MAX_SAMPLES) throw new RangeError("clip exceeds 60 seconds");
        for (let i = 0; i < input.length; i++) {
            if (!Number.isFinite(input[i]) || Math.abs(input[i]) > 1) {
                throw new RangeError("PCM must be finite and within [-1, 1]");
            }
        }
        if (rate === 1 || !input.length) return input.slice();
        const length = Math.floor(input.length / rate);
        if (length < FRAME + HOP) throw new RangeError("short clip requires normal playback");
        const output = new Float32Array(length);
        const weights = new Float32Array(length);
        const window = new Float32Array(FRAME);
        for (let i = 0; i < FRAME; i++) {
            // Nonzero endpoints preserve the first and final sample after normalization.
            window[i] = Math.sin(Math.PI * (i + 0.5) / FRAME) ** 2;
        }

        function add(start, destination) {
            for (let i = 0; i < FRAME; i++) {
                output[destination + i] += input[start + i] * window[i];
                weights[destination + i] += window[i];
            }
        }
        function match(expected, previous, outputHop) {
            const maxStart = input.length - FRAME;
            const low = Math.max(previous + 1, expected - SEARCH, 0);
            const high = Math.min(expected + SEARCH, maxStart);
            const reference = previous + outputHop;
            let referenceEnergy = 0;
            const overlap = FRAME - outputHop;
            for (let i = 0; i < overlap; i += 4) referenceEnergy += input[reference + i] ** 2;
            if (referenceEnergy < 1e-12 || low > high) {
                return Math.max(0, Math.min(maxStart, expected));
            }
            let best = Math.max(low, Math.min(high, expected));
            let bestScore = -Infinity;
            function score(start) {
                let product = 0, energy = 0;
                for (let i = 0; i < overlap; i += 4) {
                    const sample = input[start + i];
                    product += input[reference + i] * sample;
                    energy += sample * sample;
                }
                // The tiny clock-distance tie-break avoids needless movement for periodic tones.
                return product / Math.sqrt(referenceEnergy * energy + 1e-30) -
                    Math.abs(start - expected) * 1e-9;
            }
            for (let start = low; start <= high; start += 2) {
                const value = score(start);
                if (value > bestScore) { bestScore = value; best = start; }
            }
            const coarse = best;
            for (let start = Math.max(low, coarse - 1); start <= Math.min(high, coarse + 1); start++) {
                const value = score(start);
                if (value > bestScore) { bestScore = value; best = start; }
            }
            return best;
        }

        add(0, 0);
        let previous = 0;
        const lastOutput = length - FRAME;
        for (let destination = HOP; destination < lastOutput; destination += HOP) {
            const expected = Math.round(destination * rate);
            const start = match(expected, previous, HOP);
            add(start, destination);
            previous = start;
        }
        // Anchor the tail rather than fill the requested duration by dropping its final samples.
        if (lastOutput > 0) add(input.length - FRAME, lastOutput);
        for (let i = 0; i < length; i++) output[i] /= weights[i];
        return output;
    }

    const api = Object.freeze({stretch, sampleRate: SAMPLE_RATE, maxSamples: MAX_SAMPLES,
        frameSamples: FRAME, hopSamples: HOP, searchSamples: SEARCH, rates: Object.freeze(RATES)});
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    else root.CaptionSpeedEvaluation = api;
})(typeof globalThis === "undefined" ? this : globalThis);
