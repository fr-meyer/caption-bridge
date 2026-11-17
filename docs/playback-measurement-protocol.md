# Frozen paired playback protocol v1, 2026-11-17

Preparation only. No native/device/human acceptance has been collected by this
package. Buffered and 1x defaults are unchanged. Existing scheduler comparator
scripts/playback_timing_compare.py remains authoritative for scheduling gaps
and overlaps; do not replace its interval-frontier algorithm.

## Freeze before collection

Use the identical hashed public/local speech PCM, mono 24 kHz, packet sizes and
packet arrival offsets for both modes. Store source/license or local synthesis
engine/version, fixture hash, duration, language and packet schedule in the
run manifest, never private speech. Select two short English/Korean fixtures
with pauses and consonant onsets. Public real speech still needs selection and
local provisioning; the deterministic marker is NOT a substitute for speech.
Commit the manifest before collecting evidence. Use 30 valid paired observations
per fixture per native browser (Chromium and native Safari separately), AB then
BA alternation, retaining every failed attempt and its original pair identity.
No optional stopping after a favorable p95. Report nearest-rank p95 and median,
valid/attempted denominators and paired deltas; n=30 tail is imprecise. If
variance prevents a decision, predeclare an expanded run before collecting it.
Linux WebKit or synthetic arrays must never be labeled native Safari.

Freeze the existing comparison intent as: candidate median request-to-output
must improve, candidate p95 must not exceed buffered p95 beyond measured clock
uncertainty; no additional invalid attempts, gaps, overlaps or underruns;
no human clarity/quality regression. Scheduling alone cannot satisfy this rule.
This operational rule is not an evidence-derived absolute numeric target.
Derive and record that future target only after the paired evidence is reviewed.
Do not relax a failed comparison. Report inconclusive if clock error dominates.

## Clock, signal and metric semantics

Record request dispatch, first PCM, ready, scheduled start/end on a common
monotonic clock. Map capture sample zero onto that clock with calibration and
reported uncertainty; AudioContext.currentTime is NOT performance.now().
A calibration marker precedes the speech with a fixed known offset. Measure
marker onset separately from speech onset; do not call marker timing speech
intelligibility. Correlate a known leading speech segment separately where its
energy and uniqueness permit it. Silence/ambiguous/repeated signals invalidate
the attempt, not a zero latency. Calibrate route delay without subtracting away
the actual device latency being measured. Preserve raw and corrected numeric
latencies and calibration method in the adapter receipt.

scripts/playback_measurement.py provides pure correlate(), onset(), summarize().
Capture arrays remain in memory and are discarded immediately after analysis.
The bounded correlation window is <=24000 samples and reference 32..512 samples;
the adapter extracts a clock-stamped onset window, not an entire meeting.
Gain/DC/polarity are normalized. Threshold 0.9 is frozen for v1. Acoustic room
filtering may fail it; report failure, do not silently tune after collection.

Three distinct scopes: scheduling is software intent; digital_loopback measures
delivered digital samples; acoustic requires a calibrated physical reference
route and attended capture. Digital loopback is NOT headphone acoustic latency.
Capture adapter must verify declared route; the pure analyzer cannot attest it.
Use existing comparator for scheduled intervals. Actual output discontinuities
require captured sample continuity/sequence evidence, not scheduled gaps alone.
Summaries accept independently measured gap_ms, overlap_ms and underruns; unknown
continuity is not zero. Do not submit a row until these metrics are available;
otherwise retain a capture_failed attempt plus an explicit unknown-data note.

## Lane C adapter contract and gates

C owns device runner/attended guard. Import pure functions only. Before any
physical stream: meeting-ended confirmation, participant-ready, provider-denied
network, route safety, single capture owner, programme ledger, hard watchdog and
cleanup verification. Never use ordinary provider Start. Supply actual sample
rate, capture-start/request clock mapping, uncertainty and verified scope to
onset(). Persist only numeric result and fixed reason; translate to summarize()
rows, with browser/version and fixture identity in the bound run manifest.
Unknown or missing metrics invalidate the attempt. Every calibration, failure
and retry consumes the shared 600-second physical budget. Dry-run duration plan:
2 fixtures * 30 pairs * 2 modes * 2 browsers * window_seconds, plus calibration,
routing tests and failures. Even 2 seconds/window consumes 480 seconds before
other lanes; this is an estimate, NOT authority or a feasible-budget claim.
If measured dry-run exceeds remaining budget, leave acoustic acceptance open
and request a concrete amendment, never reduce evidence or mislabel digital.
Cancellation/replay/refresh/Stop must have separate lifecycle observations and
no stale output/acknowledgment. No device adapter or capture was run in this lane.

## Speed evaluation and conditional integration

Reuse speed-evaluation/pitch WSOLA and cancellable worker, not playbackRate.
benchmark_pcm.cjs accepts public/local mono float PCM at 24 kHz and outputs
numeric 1/1.15/1.3 processing/duration results. Input identity is SHA-256; no PCM
is output. Node timings are NOT browser worker startup, acoustic or human proof.
Run the existing worker browser harness later in both native target browsers;
record startup+processing p50/p95, reserved PCM peak and cancellation cleanup.
Compare the same hashed speech at each rate, counterbalance rate order, obtain
pitch/clarity/preference verdicts. Missing human evidence is not a no-go.

Only after an actual recorded go: buffered complete clips use existing worker
and shared AudioContext with playbackRate=1. Snapshot rate when a clip enters
the queue; setting changes affect only subsequently enqueued clips, never the
playing or already queued clips. Replay preserves the original clip rate and
provenance. Save explicit preference with default 1x and accessible labeled
control; progressive visibly supports only 1x and must not silently transform.
Reserve queued/source/transformed/scheduled copies before allocation using the
existing shared memory budget. Failure falls back only with explicit 1x
provenance, never a false faster-rate acknowledgment. Stop/mute/Catch up/relock/
refresh invalidate epochs and await worker cleanup. Cover every lifecycle at
all rates plus progressive incompatibility before production integration.
No production control or default change is included in this first batch.

## Offline capture adapter, second batch

scripts/playback_capture_adapter.py now joins calibrated sample clocks, bounded
onset correlation and capture-block continuity. calibrate() takes 3..32 ordered
(sample_index, monotonic_ms, uncertainty_ms) anchors. Feasible offset intervals
must intersect at the nominal sample rate; drift outside uncertainty fails.
Anchors must bracket the analyzed window, no extrapolation. analyze_window()
accepts an owned mutable PCM list and zeros it in finally, including errors.
This does not erase aliases/backend buffers or attest actual stream shutdown.
The C runner retains sole responsibility for capture and its guard/cleanup.

continuity() requires actual block start/sample count/underrun integer metadata;
nulls and missing fields fail, never become zeros. This is CAPTURE TRANSPORT
continuity, not proof of an absence of speech dropouts on the output route.
Any transport gap/overlap/underrun invalidates onset. Delivered speech continuity
still requires reference-versus-output alignment and native qualification.
Do not map transport zero to an audible no-gap verdict.

Concrete programme allocation at 2s per onset window: 240 observations = 480s;
20s calibration, 60s reserved to other lanes, 40s retries = 600s. The pure
capture_budget() checks against the *current* shared remaining ledger and never
authorizes capture. This arithmetic fits only at a full 600s balance and only
if actual preflight proves each full open-to-close window <=2s. No native dry-run
has proved that bound. At 2.1s the plan is 624s and fails. Longer speech-quality
listening uses no physical capture; full-clip acoustic continuity remains open
if it cannot fit. Do not trim promised evidence to manufacture feasibility.

Public fixture asset preparation is in speed-evaluation/fixtures. Short greetings
are real speech, but insufficient by themselves for the full multi-sentence
pause/consonant/quality rubric. No local decoder/synthesizer is installed in this
lane. Decode later in the isolated offline browser/approved toolchain, hash the
exact mono 24kHz PCM and freeze packet schedule BEFORE paired collection.

Review corrections: invalid attempts may carry explicit null continuity; retain
them with per-metric unknown counts. Complete totals are null if any contributing
metric is unknown; separately labeled known sums are partial, never a pass.
Valid rows still require every finite metric. Correlation rejects competing
above-threshold peaks beyond one neighboring sample and equal-score competing
peaks even adjacent; short-period phase ambiguity cannot select a false onset.

## 2026-11-17 v1.1 source-only readiness delta

English original provisioning is now complete: `speed-evaluation/fixtures/en-hello.ogg`,
9036 bytes, SHA256 `ade8485f1cfd454e27ec1bb93cc0234d3187b2507230f72e96f46ac686e82972`.
Commons author Dvortygirl explicitly dedicates it to the public domain with an
unconditional-use fallback. Source/license and unmodified-byte identity are in
the fixture manifest. Korean attribution and local synthesis recipe are unchanged.
Earlier missing-asset notes above describe the earlier batch; no failed receipt
was rewritten. Neither original was decoded or played in this source-only batch.
These greetings do NOT complete the multi-sentence public real-speech corpus.

The offline Node benchmark now interleaves rates using all six permutations,
five cycles at default 30 repetitions, instead of processing one rate block at
a time. Its numeric `trial_order` makes order reproducible, and `order_balanced`
is false for reduced runs not divisible by six. This avoids conflating systematic
rate order with warm-up drift, but does not eliminate resource contention or
make Node timing into native browser startup/performance evidence.

Prepared offline verification (standard library Python and existing Node only):

```sh
python3 -m unittest discover -s tests/unit -p 'test_playback*.py'
python3 -m unittest discover -s tests/unit -p 'test_local_speech_fixture.py'
node --test --test-concurrency=1 speed-evaluation/pitch/test_*.cjs
# Once separately provisioned/hashed mono 24kHz float32 speech is available:
node speed-evaluation/pitch/benchmark_pcm.cjs /private/local/speech.f32le
```

Native-window handoff: freeze decoded PCM hashes, packet arrival schedule,
browser versions, mode/rate ordering and actual remaining capture ledger first.
Use `playback_capture_adapter.calibrate`, `analyze_window`, `capture_budget` and
`playback_measurement.summarize` through the guarded device owner, not ordinary
provider Start. The APIs are prepared analysis entrypoints, NOT an operational
capture admission or cleanup implementation. Native Chromium/Safari measurements,
measured budget preflight, output continuity, human listening and actual speed-go
remain required. No production speed control is shipped and no no-go inferred.
