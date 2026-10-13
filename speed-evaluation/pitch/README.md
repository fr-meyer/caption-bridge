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

## Evaluation memory and reset contract

The source-only follow-up adds `CaptionSpeedTransformClient.MemoryBudget` (also
`CaptionSpeedMemoryBudget` in a browser). Clients share one 32 MiB budget by
default. A caller can instead pass the same explicit budget as the third
constructor argument to every client and reserve other retained or scheduled
PCM with `budget.reserve(bytes)`. Reservations expose idempotent `release()`
and checked `resize(bytes)`; `budget.snapshot()` contains byte counts only.
These are **tracked PCM reservations**, with a fixed 1 MiB allowance per worker.
They are not a bound on total process/browser memory, GC timing, JavaScript
objects, engine overhead or physical memory after browser termination.
`--max-old-space-size=128` limits Node's managed heap, not total memory.

`estimateMemory(pcm, rate)` counts the whole caller backing buffer (including a
larger backing buffer behind a small view), the copied/transferred input,
output, overlap weights, 960-sample window and worker allowance. `run()` reserves
this conservative peak before creating a worker or allocating its transfer
copy. The maximum 60-second 1.15x job reserves 22,589,800 bytes: 21,541,224 bytes
of known PCM plus the allowance. Concurrent jobs, even in different clients,
cannot exceed their shared reservation budget. Admission rejection creates
neither a worker nor a transfer copy. Worker results must have the exact
expected backing-buffer size as well as the expected sample count.

The caller retains ownership of the original input. Every returned operation
promise has `releaseInput()`; an accepted result also exposes that same release
and an independent `release()` for its output. The input charge persists after
success, failure or cancellation until the caller drops its original PCM and
calls `releaseInput()` after dropping all retained aliases. Output remains charged until its owner drops it or
reserves its next owner/copy, then calls `release()`. Both releases are
idempotent. A scheduled `AudioBuffer` copy, queued clips, frame/concatenation
duplicates and other PCM must each be reserved **before their allocation** by
a future player integration. Keeping an external input reservation alongside
the client's input charge double-counts it conservatively; it never exempts
external PCM from accounting. An input rejected at admission remains the
caller's separately accounted responsibility.

Cancellation rejects the operation with `AbortError` promptly. It returns a
cleanup promise. If `terminate()` returns a promise, the full peak remains
charged until that promise fulfills, including after transfer detaches the
sender's buffer. `reset()` cancels the current job and awaits all already
terminating jobs; `drain()` awaits termination without cancelling an active job.
Late replies from an old captured handler cannot finish or release a newer job.
A failed or throwing termination keeps its peak quarantined and makes
`reset()`/`drain()` reject with fixed `transform_termination_failed`. There is no
unsafe force-release escape hatch. A browser's void `terminate()` is treated
as its ownership fence; actual reclamation and engine overhead remain separate
browser measurements. Caller input and successful output releases are still
required after cleanup.

```js
const budget = new CaptionSpeedTransformClient.MemoryBudget();
const client = new CaptionSpeedTransformClient(workerFactory, 10000, budget);
let input = takeCompletedClipPcm(); // Its earlier queue/storage allocation needs its own accounting.
const operation = client.run(input, 1.15, {epoch: 3, clipId: 10});
let result;
try {
    result = await operation;
    // Reserve any scheduled copy before allocating it; keep its lease until that copy is dropped.
} finally {
    input = null;
    operation.releaseInput();
    if (result) {
        result.pcm = null;
        result.release();
    }
    await client.drain();
}
```

`test_transform_memory.cjs` adds focused synthetic reservation and lifecycle
checks, including structured-clone transfer detachment and a real Node worker's
asynchronous termination. It does not execute WSOLA or a browser. These checks
do not integrate the product player's 32 MiB bound, certify speech quality or
add a production speed control. The reviewed 34 Node checks and three Chrome
Worker checks remain historical evidence for the earlier client/worker; the
unchanged algorithm and worker source were not rerun in this follow-up.

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
4. Integrate the evaluation reservation contract with source PCM, transfer copy,
   output, overlap weights, scheduled AudioBuffer and Worker overhead in the
   existing 32 MiB player limit. The
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

To run only the new source-only memory follow-up checks:

```sh
node --max-old-space-size=128 --test --test-concurrency=1 \
  speed-evaluation/pitch/test_transform_memory.cjs
```

The application, WSOLA algorithm, direct worker entry and CI workflow are
unchanged by the memory follow-up. Human intelligibility at 1.15x/1.3x and actual
production-player integration remain separate work.
