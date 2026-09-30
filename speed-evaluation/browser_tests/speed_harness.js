/* Issue #67 evaluation only. Offline tone rendering and muted silent media.
 * No production imports, microphone, provider, raw-audio export, or audible route.
 */
"use strict";

window.speedEvaluation = (() => {
    const SAMPLE_RATE = 24000;
    const TONE_HZ = 440;
    const INPUT_SECONDS = 1;

    async function resampling(rate) {
        const context = new OfflineAudioContext(1, SAMPLE_RATE * 1.1, SAMPLE_RATE);
        const buffer = context.createBuffer(1, SAMPLE_RATE * INPUT_SECONDS, SAMPLE_RATE);
        const input = buffer.getChannelData(0);
        for (let index = 0; index < input.length; index++) {
            input[index] = 0.25 * Math.sin(2 * Math.PI * TONE_HZ * index / SAMPLE_RATE);
        }
        const source = context.createBufferSource();
        source.buffer = buffer;
        source.playbackRate.value = rate;
        // Offline destination is an in-memory AudioBuffer, never a sound device.
        source.connect(context.destination);
        source.start();
        const rendered = await context.startRendering();
        const output = rendered.getChannelData(0);
        let lastActive = -1;
        for (let index = 0; index < output.length; index++) {
            if (Math.abs(output[index]) > 1e-4) lastActive = index;
        }
        const durationSeconds = (lastActive + 1) / SAMPLE_RATE;
        const crossings = [];
        // Discard the edges and estimate pitch from interpolated positive crossings.
        const start = Math.ceil(0.1 * SAMPLE_RATE);
        const end = Math.floor((INPUT_SECONDS / rate - 0.1) * SAMPLE_RATE);
        for (let index = start + 1; index < end; index++) {
            const previous = output[index - 1];
            const current = output[index];
            if (previous <= 0 && current > 0) {
                crossings.push(index - 1 + (-previous) / (current - previous));
            }
        }
        if (crossings.length < 20) throw new Error("Insufficient offline crossing samples");
        const measuredHz = (crossings.length - 1) * SAMPLE_RATE /
            (crossings[crossings.length - 1] - crossings[0]);
        return {
            mechanism: "AudioBufferSourceNode.playbackRate",
            rate,
            sample_rate: SAMPLE_RATE,
            input_duration_seconds: INPUT_SECONDS,
            input_frequency_hz: TONE_HZ,
            measured_duration_seconds: durationSeconds,
            expected_duration_seconds: INPUT_SECONDS / rate,
            measured_frequency_hz: measuredHz,
            measured_pitch_shift_semitones: 12 * Math.log2(measuredHz / TONE_HZ),
            has_preserves_pitch_property: "preservesPitch" in source,
            audible_output: false,
            rendering: "OfflineAudioContext only",
        };
    }

    function silentWav(seconds) {
        const sampleCount = Math.round(SAMPLE_RATE * seconds);
        const data = new ArrayBuffer(44 + sampleCount * 2);
        const view = new DataView(data);
        const text = (offset, value) => {
            for (let index = 0; index < value.length; index++) {
                view.setUint8(offset + index, value.charCodeAt(index));
            }
        };
        text(0, "RIFF");
        view.setUint32(4, 36 + sampleCount * 2, true);
        text(8, "WAVE");
        text(12, "fmt ");
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true); // PCM
        view.setUint16(22, 1, true); // mono
        view.setUint32(24, SAMPLE_RATE, true);
        view.setUint32(28, SAMPLE_RATE * 2, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true);
        text(36, "data");
        view.setUint32(40, sampleCount * 2, true);
        // The initialized data section is entirely zero-valued silence.
        return new Blob([data], {type: "audio/wav"});
    }

    function mediaSupport() {
        const element = document.createElement("audio");
        const support = {
            standard: "preservesPitch" in element,
            webkit: "webkitPreservesPitch" in element,
            moz: "mozPreservesPitch" in element,
        };
        const property = support.standard ? "preservesPitch" :
            (support.webkit ? "webkitPreservesPitch" :
                (support.moz ? "mozPreservesPitch" : null));
        const defaultValue = property ? element[property] : null;
        if (property) element[property] = false;
        const disabled = property ? element[property] : null;
        if (property) element[property] = true;
        const enabled = property ? element[property] : null;
        const mse = window.MediaSource;
        return {
            mechanism: "HTMLMediaElement.pitchControlSupport",
            rate: 1,
            pitch_property: property,
            pitch_property_support: support,
            default_preserves_pitch: defaultValue,
            property_after_disabled: disabled,
            property_after_enabled: enabled,
            wav_can_play_type: element.canPlayType("audio/wav"),
            media_source_supported: !!mse,
            media_source_pcm_wav: !!mse && mse.isTypeSupported("audio/wav"),
            media_source_webm_opus: !!mse && mse.isTypeSupported('audio/webm;codecs="opus"'),
            media_source_mp4_aac: !!mse && mse.isTypeSupported('audio/mp4;codecs="mp4a.40.2"'),
            audible_output: false,
            pitch_frequency_measured: false,
        };
    }

    async function media(rate, preservesPitch = true) {
        const element = document.createElement("audio");
        element.muted = true;
        element.volume = 0;
        element.preload = "auto";
        const support = {
            standard: "preservesPitch" in element,
            webkit: "webkitPreservesPitch" in element,
            moz: "mozPreservesPitch" in element,
        };
        const pitchProperty = support.standard ? "preservesPitch" :
            (support.webkit ? "webkitPreservesPitch" :
                (support.moz ? "mozPreservesPitch" : null));
        const defaultPreservesPitch = pitchProperty ? element[pitchProperty] : null;
        if (pitchProperty) element[pitchProperty] = preservesPitch;
        const url = URL.createObjectURL(silentWav(INPUT_SECONDS));
        let timer;
        try {
            element.src = url;
            await new Promise((resolve, reject) => {
                timer = setTimeout(() => reject(new Error("Muted media metadata timeout")), 4000);
                element.onloadedmetadata = resolve;
                element.onerror = () => reject(new Error("Silent WAV unsupported"));
                element.load();
            });
            clearTimeout(timer);
            element.playbackRate = rate;
            const positions = [];
            let startedAt = null;
            let playingEvents = 0;
            const ended = new Promise((resolve, reject) => {
                timer = setTimeout(() => reject(new Error("Muted media playback timeout")), 4000);
                element.onplaying = () => {
                    playingEvents++;
                    if (startedAt === null) startedAt = performance.now();
                };
                element.ontimeupdate = () => positions.push(element.currentTime);
                element.onended = resolve;
                element.onerror = () => reject(new Error("Muted media playback failed"));
            });
            await element.play();
            await ended;
            const elapsed = (performance.now() - startedAt) / 1000;
            return {
                mechanism: "HTMLMediaElement.playbackRate",
                media_playback_supported: true,
                rate,
                actual_playback_rate: element.playbackRate,
                input_duration_seconds: element.duration,
                expected_duration_seconds: element.duration / rate,
                measured_playing_to_ended_seconds: elapsed,
                final_media_time_seconds: element.currentTime,
                playing_events: playingEvents,
                monotonic_media_time: positions.every((value, index) => index === 0 || value >= positions[index - 1]),
                pitch_property: pitchProperty,
                pitch_property_support: support,
                default_preserves_pitch: defaultPreservesPitch,
                requested_preserves_pitch: preservesPitch,
                observed_preserves_pitch: pitchProperty ? element[pitchProperty] : null,
                pitch_frequency_measured: false,
                pitch_measurement_limitation: "Silent media has no pitch; API support and timeline behavior only",
                muted: element.muted,
                volume: element.volume,
                audible_output: false,
                input_signal: "Locally generated one-second zero-valued PCM WAV",
            };
        } catch (error) {
            if (element.error && element.error.code === 4) {
                return {
                    mechanism: "HTMLMediaElement.playbackRate",
                    rate,
                    media_playback_supported: false,
                    media_error_code: element.error.code,
                    limitation: "This browser/runtime cannot decode the local silent PCM WAV",
                    pitch_property: pitchProperty,
                    pitch_property_support: support,
                    default_preserves_pitch: defaultPreservesPitch,
                    observed_preserves_pitch: pitchProperty ? element[pitchProperty] : null,
                    requested_preserves_pitch: preservesPitch,
                    pitch_frequency_measured: false,
                    muted: element.muted,
                    volume: element.volume,
                    audible_output: false,
                };
            }
            throw error;
        } finally {
            clearTimeout(timer);
            element.pause();
            element.removeAttribute("src");
            element.load();
            URL.revokeObjectURL(url);
            element.remove();
        }
    }

    return {resampling, media, mediaSupport};
})();
