# Complete-clip pitch-preserving PCM evaluation (#67)

This follow-up provides a dependency-free waveform-similarity overlap-add
(WSOLA) prototype for generated mono 24 kHz Float32 PCM at 1.15x and 1.3x.
It processes a completed clip into a shorter PCM buffer, which can then be
played at normal `AudioBufferSourceNode.playbackRate = 1` through the existing
shared `AudioContext`. No WAV/media decoder, second output route, provider speed
parameter, microphone, or sample-file export is required. The application and
its normal speed/opt-in progressive default are unchanged. CI adds this bounded
Node contract to the existing Python 3.11 job, with a one-minute step timeout;
no job, dispatch, action or dependency is added.

The mechanism follows the time-domain frame-alignment concept described in the
[original WSOLA paper](https://www.isca-archive.org/eurospeech_1993/roelands93_eurospeech.html).
This implementation is original evaluation code, with 40 ms raised-sine-squared
frames, a 20 ms synthesis hop, +/- 10 ms waveform matching around a fixed content
clock, normalized overlap-add, and exact first/final sample anchors. Frames are
selected and overlapped without resampling. This is a candidate mechanism, not a
claim of perceptual quality for arbitrary speech or music.

## Synthetic findings

`evidence/pitch-measurements-20261013.json` contains aggregate duration, frequency,
RMS and processing measurements for generated 110–880 Hz tones, a three-harmonic
160 Hz voiced fixture, and a maximum-length 60-second clip. No samples are saved.
`test_wsola.cjs` also checks a rising-frequency fixture, shortened-content pulse
envelopes, deterministic output, immutable input, tail anchors, silence and
invalid/overlong inputs.

The expected duration savings are 13.04% at 1.15x and 23.08% at 1.3x, within one
sample of the requested duration. Tone-frequency error must stay below 0.3%
and pitch shift below 0.06 semitones in the synthetic tests. This contrasts with
PR #72's measured +2.42/+4.54-semitone shift from naive resampling. The 60-second
transform has a conservative 5-second test ceiling; actual processing time is
recorded separately and is not a browser/Windows performance guarantee.

PCM must be finite, within [-1, 1], and no longer than 60 seconds. A speed-up
requiring fewer than 1,440 output samples (60 ms) is rejected; a future caller
must explicitly play that short clip at normal speed. The input is never rewritten.

`transform-client.js` plus `wsola-worker.js` form a separate cancellable prototype:
one pending job, content-free epoch/clip identity, copy-before-transfer, timeout,
worker termination on completion/cancellation/failure, and rejection of stale or
malformed results. It exposes no audio API and emits no playback acknowledgment.
The fake-worker/actual-worker-entry-point Node tests verify its boundary. A
separate existing-Chrome 155 check passes three real Worker wiring cases: both
faster rates and immediate cancellation. The two-second tone stayed near 440 Hz;
Worker startup plus processing took 52.4/30.3 ms at 1.15x/1.3x. That check binds
only a temporary local source server and replaces audio/capture entry points
with throwing counters (zero calls). After direct-entry hardening, the same
three checks passed again; startup plus processing was 117.2/62.6 ms, illustrating
that the earlier timing is an observation rather than a guarantee. It is distinct from application-player or
native Safari integration. Its receipt is
`evidence/pitch-worker-browser-20261013.json`.
The [HTML Worker specification](https://html.spec.whatwg.org/multipage/workers.html#dom-worker-terminate)
defines termination; real browser scheduling and memory overhead remain separate
measurements.

The Worker entry independently requires safe integer job/epoch/clip IDs, a
supported rate, exactly the supported message fields, and bounded Float32 PCM.
Malformed identities (including null) are ignored before the one-job state
changes, so a subsequent valid request can still succeed. A valid numeric
identity with an invalid payload consumes that one job and returns only the
numeric identity plus fixed `transform_rejected`; no arbitrary field is echoed.

## Concrete integration proposal

1. Apply a selected rate at clip start and keep Normal as the default. Preserve
   each clip's `seq`, `clip_id`, `tts_epoch`, mode and one-start/one-terminal ACK.
2. For **buffered** playback after EOS, concatenate the received PCM and run one
   transform in a Worker. Use the existing player's shared context and its chosen
   sink to schedule the returned PCM at rate 1. Keep the original PCM available
   only until a normal-speed fallback is selected or the transform succeeds.
3. Before scheduling a completed result, check the existing active clip and
   generation/epoch again. Catch up, mute, connection replacement, New Session
   and cancellation must terminate pending transforms as well as stop scheduled
   sources. A cancelled transform produces no start or completion ACK.
4. Account for source PCM, transfer copy, output, overlap weights, scheduled
   AudioBuffer and Worker overhead in the existing 32 MiB player limit. The
   maximum 60-second/1.15x transform alone holds about 15.8 MB of PCM including
its input and weights; preserving the caller's input adds another 5.76 MB.
   Concurrent queued clips must be included. Reject or choose normal speed
   before allocation when the aggregate would exceed the bound.
5. A worker failure/unsupported Worker/short clip must select normal playback
   visibly; the UI and diagnostics must record the effective rate, not pretend
   the requested faster rate succeeded. Only numeric rate/outcome counters are
   appropriate for retained diagnostics.
6. Progressive mode remains normal-speed. This batch transform waits for EOS
   and cannot preserve #65's progressive first-chunk onset. A stateful transform
    with bounded lookahead, partial-output cancellation and final-tail flush would
   need separate source review and protocol tests before faster progressive
   playback is offered. Do not run independent transforms on each PCM chunk.

Before any faster runtime control ships, perform a separately approved attended
normal/1.15x/1.3x comparison containing pauses, punctuation, numbers, acronyms and
technical terms in supported target languages. Test Safari and Chromium, the
selected output route, interruption/Catch up/Replay, and short-clip fallback.
Human intelligibility, voice timbre, transient smearing, unvoiced/noisy speech,
native Safari and physical Windows coverage are **unmeasured** here. Synthetic
pitch and envelope checks do not substitute for listening. There is no new model
call allowance or microphone approval for that comparison.

## Reproduce locally

Use an already-installed Node runtime. No dependencies or browsers are installed:

```sh
node --max-old-space-size=128 --test --test-concurrency=1 \
  speed-evaluation/pitch/test_wsola.cjs \
  speed-evaluation/pitch/test_transform_client.cjs
node --max-old-space-size=128 speed-evaluation/pitch/measure.cjs
```

The first command runs 34 bounded synthetic checks; the second prints aggregate
measurements only. This follow-up used one local Node process at a time, no GCP,
external application endpoint, provider request, audio context or physical device.
The optional `check_browser_worker.py` uses an existing Python Playwright runtime
and installed Chrome, without browser downloads; it runs three generated-buffer
Worker checks with a temporary loopback source server. It does not construct an
audio context, play media or request capture. Timing does not claim exclusive
host resources or a browser/Windows performance guarantee.
The narrow Worker repair reran its nine affected Node checks and three real
Worker checks; the 25 unchanged algorithm checks carry from the identical WSOLA
source. No unrelated browser or algorithm measurement was repeated.
PR #72's earlier 11 browser passes/3 Linux WebKit decoder skips are carried as
historical evidence, not rerun or presented as current v0.5.0 Worker coverage.
