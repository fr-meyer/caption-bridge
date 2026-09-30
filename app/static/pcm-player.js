/* Bounded mono float32 PCM player. No audio/text survives completion or cancellation. */
(function (root) {
    "use strict";
    class CaptionPcmPlayer {
        constructor(options) {
            this.o = options;
            this.clips = new Map();
            this.queue = [];
            this.retired = new Set();
            this.active = null;
            this.bytes = 0;
            this.generation = 0;
            this.starting = false;
            this.rate = 24000;
            this.clock = options.clock || (() => performance.now());
            this.threshold = options.initialSamples || 3600; // 150 ms at 24 kHz
            this.maxBytes = options.maxBytes || 32 * 1024 * 1024;
            this.maxClipBytes = options.maxClipBytes || 60 * this.rate * 4;
            this.timeoutMs = options.timeoutMs || 30000;
        }
        key(msg) { return msg.tts_epoch + ":" + (msg.clip_id == null ? "legacy-" + msg.seq : msg.clip_id); }
        begin(msg) {
            const key = this.key(msg);
            if (this.retired.has(key)) return null;
            if (this.clips.has(key)) return this.clips.get(key);
            if (this.clips.size >= 64) { this.retire(msg); this.o.onError(msg, "buffer_limit"); return null; }
            const clip = {key, msg: {seq: msg.seq, clip_id: msg.clip_id, tts_epoch: msg.tts_epoch}, mode: this.o.streaming() ? "streaming" : "buffered",
                expected: 0, bytes: 0, samples: 0, frames: [], tail: new Uint8Array(0),
                nodes: new Set(), eos: false, cancelled: false, started: false,
                firstAt: null, readyAt: null, startedAt: null, endTime: null,
                underruns: 0, gapMs: 0, chunks: 0, timer: null};
            this.clips.set(key, clip);
            this.queue.push(clip);
            this.arm(clip);
            return clip;
        }
        arm(clip) {
            clearTimeout(clip.timer);
            clip.timer = setTimeout(() => this.fail(clip, "stream_timeout"), this.timeoutMs);
        }
        receive(msg) {
            const clip = this.begin(msg);
            if (!clip || clip.cancelled || clip.eos) return;
            const index = msg.chunk_index == null ? clip.expected : msg.chunk_index;
            if (!Number.isInteger(index) || index < 0 || index > clip.expected) {
                this.fail(clip, "missing_chunk"); return;
            }
            if (index < clip.expected) return; // Idempotent retransmission.
            try {
                if (msg.data) {
                    if (typeof msg.data !== "string" || msg.data.length > 8 * 1024 * 1024) {
                        this.fail(clip, "buffer_limit"); return;
                    }
                    const raw = atob(msg.data);
                    const size = raw.length;
                    if (this.bytes + size > this.maxBytes || clip.bytes + size > this.maxClipBytes ||
                        clip.chunks >= 512) { this.fail(clip, "buffer_limit"); return; }
                    if (clip.firstAt === null) {
                        clip.firstAt = this.clock();
                        this.o.onFirstChunk(clip.msg);
                    }
                    clip.chunks++;
                    clip.bytes += size;
                    this.bytes += size;
                    const bytes = new Uint8Array(clip.tail.length + size);
                    bytes.set(clip.tail);
                    for (let i = 0; i < size; i++) bytes[clip.tail.length + i] = raw.charCodeAt(i);
                    const count = Math.floor(bytes.length / 4);
                    const view = new DataView(bytes.buffer);
                    const samples = new Float32Array(count);
                    for (let i = 0; i < count; i++) {
                        const value = view.getFloat32(i * 4, true);
                        if (!Number.isFinite(value)) { this.fail(clip, "invalid_pcm"); return; }
                        samples[i] = Math.max(-1, Math.min(1, value));
                    }
                    clip.tail = bytes.slice(count * 4);
                    if (count) clip.frames.push(samples);
                    clip.samples += count;
                }
                clip.expected++;
                if (msg.is_last === true) {
                    clip.eos = true;
                    clearTimeout(clip.timer);
                    if (clip.tail.length) { this.fail(clip, "invalid_pcm"); return; }
                } else this.arm(clip);
                if (clip.readyAt === null && (clip.eos ||
                    (clip.mode === "streaming" && clip.samples >= this.threshold))) {
                    clip.readyAt = this.clock();
                }
                if (this.active === clip) this.schedule(clip);
                this.pump();
            } catch (_) { this.fail(clip, "invalid_pcm"); }
        }
        pump() {
            if (this.active || this.starting || !this.queue.length || !this.o.canPlay()) return;
            const clip = this.queue[0];
            if (clip.readyAt === null) return;
            const context = this.o.context();
            const generation = this.generation;
            this.starting = true;
            context.resume().then(() => {
                if (generation !== this.generation || clip.cancelled) return;
                this.starting = false;
                if (!this.o.canPlay()) return;
                this.queue.shift();
                this.active = clip;
                this.schedule(clip);
            }).catch(() => {
                if (generation !== this.generation) return;
                this.starting = false;
                this.o.onLocked();
            });
        }
        schedule(clip) {
            if (clip.cancelled || this.active !== clip) return;
            const context = this.o.context();
            if (clip.samples && (clip.eos || clip.samples >= this.threshold)) {
                const joined = new Float32Array(clip.samples);
                let offset = 0;
                clip.frames.forEach(frame => { joined.set(frame, offset); offset += frame.length; });
                const buffer = context.createBuffer(1, joined.length, this.rate);
                buffer.getChannelData(0).set(joined);
                clip.frames = [];
                clip.samples = 0;
                const node = context.createBufferSource();
                node.buffer = buffer;
                node.connect(context.destination);
                // Schedule contiguous buffers against the audio clock; late chunks are measurable gaps.
                const now = context.currentTime || 0;
                let start = clip.endTime === null ? now + 0.02 : clip.endTime;
                if (start < now) {
                    clip.underruns++;
                    clip.gapMs += (now + 0.02 - start) * 1000;
                    start = now + 0.02;
                }
                clip.endTime = start + joined.length / this.rate;
                clip.nodes.add(node);
                node.onended = () => {
                    clip.nodes.delete(node);
                    if (node.disconnect) node.disconnect();
                    if (!clip.cancelled && clip.eos && !clip.nodes.size && !clip.samples) this.finish(clip);
                };
                try { node.start(start); }
                catch (_) { this.fail(clip, "playback_failure"); return; }
                if (!clip.started) {
                    clip.started = true;
                    clip.startedAt = this.clock();
                    this.o.onStart(clip.msg);
                }
            }
            if (clip.eos && !clip.nodes.size && !clip.samples) this.finish(clip);
        }
        finish(clip) {
            if (clip.cancelled || !this.clips.has(clip.key)) return;
            this.release(clip);
            this.o.onComplete(clip.msg, {
                mode: clip.mode,
                first_chunk_to_playback_ms: Math.round(Math.max(0, (clip.startedAt ?? this.clock()) -
                    (clip.firstAt ?? this.clock()))),
                initial_buffer_ms: Math.round(Math.max(0, (clip.readyAt ?? this.clock()) -
                    (clip.firstAt ?? this.clock()))),
                underruns: clip.underruns, gap_ms: Math.round(clip.gapMs),
            });
            this.pump();
        }
        retire(msg) {
            if (msg.clip_id == null) return; // Legacy fixtures/callers cannot identify a replay.
            this.retired.add(this.key(msg));
            if (this.retired.size > 256) this.retired.delete(this.retired.values().next().value);
        }
        release(clip) {
            this.retire(clip.msg);
            clearTimeout(clip.timer);
            this.bytes -= clip.bytes;
            this.clips.delete(clip.key);
            this.queue = this.queue.filter(item => item !== clip);
            if (this.active === clip) this.active = null;
            clip.frames = [];
            clip.tail = new Uint8Array(0);
        }
        fail(clip, reason) {
            if (clip.cancelled || !this.clips.has(clip.key)) return;
            const msg = clip.msg;
            this.cancelClip(clip);
            this.o.onError(msg, reason);
            this.pump();
        }
        cancelClip(clip) {
            clip.cancelled = true;
            this.generation++;
            this.starting = false;
            clip.nodes.forEach(node => {
                node.onended = null;
                try { node.stop(0); } catch (_) { /* Already ended. */ }
                if (node.disconnect) node.disconnect();
            });
            clip.nodes.clear();
            this.release(clip);
        }
        cancel(msg) {
            const clip = this.clips.get(this.key(msg));
            if (clip) this.cancelClip(clip);
            this.pump();
        }
        cancelAll() {
            Array.from(this.clips.values()).forEach(clip => this.cancelClip(clip));
            this.generation++;
            this.starting = false;
        }
    }
    root.CaptionPcmPlayer = CaptionPcmPlayer;
})(window);
