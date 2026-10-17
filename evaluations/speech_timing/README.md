# Offline per-chunk speech timing

This evaluation is not imported by the application. Import and construction do
not create a device, AudioContext, player, SDK, socket or process. There is no
launcher or readiness receipt here. The installed Medium configuration and
buffered/default speech behavior are unchanged.

`FixtureDelivery` accepts already-prepared public mono float32 PCM at 24 kHz.
It preserves the isolated cadence-v3 formula: each deadline includes consumer
work and wake delay within its audio interval. It adds a numeric record for
each emitted chunk and for the consumer's return. The final tail keeps its
actual sample duration. Completion, cancellation or context closure releases
the supplied PCM; a stream cannot restart. Input is limited to 128 chunks of
2,400 samples (12.8 seconds), sufficient for the retained 12.36-second fixture.
No audio, text, content hash, absolute time or exception message enters its
report.

`ChunkTimingProbe` is an explicit observer of an already-created production
PCM player for a selected public fixture clip. It does not start, receive,
resume or play anything itself. It delegates existing calls, recording up to
128 chunk rows and 128 scheduling rows. It observes only local monotonic
offsets, receive-processing duration, scheduling lead/gap/duration and the
delay from readiness to the first schedule. It excludes payloads, caption
sequence/text and private event fields. Detach restores the owned methods;
observer faults are counted and never interrupt the player. Completed traces
with rejected rows are not certified.
Each probe instance attaches once. Detach is idempotent and cannot release a
newer observer's ownership; a non-writable native node method leaves playback
untouched and marks timing evidence rejected.

| Evidence | Clock domain | What it can establish |
| --- | --- | --- |
| Nominal deadline, yield offset, lateness, consumer work | Source monotonic | Whether fixture/controller delivery missed its own deadline |
| Receive offset and receive-processing duration | Browser/player monotonic | Work inside `receive`; this includes decoding and synchronous scheduling, not pure decode time |
| Ready to first schedule | Browser/player monotonic | A readiness/resume hold after enough PCM was available |
| Scheduled lead, gap and duration | AudioContext | Scheduling continuity; not audible onset |
| Receive-interval excess over yield interval | Two independently computed durations | Transit/dispatch variation, limited by both clocks' rate and precision |

`classify` validates an allowlisted finite schema, consecutive chunk indexes,
sample-derived deadlines and strictly advancing schedule coverage/submission.
Each scheduled buffer's duration must equal the newly covered source samples,
and a completed trace must cover the final chunk. It never
subtracts the source and browser clock origins. It returns evidence flags,
not an assigned cause. Unknown fields, nonfinite values, malformed identity or
unmatched data fail with fixed messages. Partial or rejected traces cannot
claim complete evidence. A browser processing delay can also cause a receive
interval excess; these flags are not exclusive causal categories.

The original attended quartet only retained aggregate gaps (160/163 ms) and
human clarity/no-overlap. It cannot be retroactively given this per-chunk
evidence. Prior relative-cadence and cadence-v3 reviews remain valid for their
separate helper versions. The collector and pinned-fixture integration entered
`dev` through PR86/PR85; the browser attachment at `51c56bb` remains local.
Neither changes the immutable qualified helper.

## Synthetic contracts

Use the existing Python/Node environments, with no installs:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  python -B -m pytest -q -p no:cacheprovider tests/unit/test_speech_timing.py
```

The regression file lives under `tests/unit` and is collected by the existing
CI test command; no new CI run is claimed here. The tests supply generated silence and fake monotonic/audio clocks and nodes.
The probe is composed with the unchanged production player. Cases isolate
anchored delivery, a 350 ms controller stall, a 250 ms resume hold, 120 ms
receive work, a short tail flushed at EOS, an observer fault and a non-writable
node method. Stale detach and incomplete schedule coverage have separate
regressions. Each player case
compares scheduling/start/completion behavior with the observer absent. Node
has a 128 MiB heap and five-second timeout. No actual browser, hardware audio,
network, SDK or provider request is involved. Optional
`SPEECH_TIMING_RECEIPT_DIR` saves only numeric synthetic receipts outside the
source tree.

## Pinned fixture integration

`fixture_adapter.py` provides an explicit `load_qualified_fixture(pack_path)`
reader for the retained timing-v2 pack. It verifies the receipt's exact source
head/app tree and all seven helper/manifest/PCM pins. It executes only the
hash-verified inert fixture module, then rechecks the pack; the launcher,
runtime and browser actor are never imported. It neither prepares nor downloads
audio. Receipt verification refers to the old pack's scope and does not qualify
this new adapter or extend an attended approval.

`TimedFixture(fixture)` preserves the fixture interface used by the qualified
fake SDK: `fixture.stream(cadence_seconds=0.1)` returns an async context manager
and iterator yielding `audio_data`. It replaces relative sleeps with the reviewed
anchored collector, using the identical public PCM and 60 ms final tail. Four
serial context-managed streams are allowed. Their ordinal maps to clip IDs 1–4
at epoch zero only under the qualified B/P/P/B protocol before refresh. Overlap,
extra streams, another cadence or mismatched report identities are rejected.
Refresh/replay is outside this adapter's scope; no mapping is inferred for it.

The new `fixture_contract.cjs` composes those streams with the unchanged
production PCM player and observer, using one shared fake context/player and
four sequential buffered/progressive/progressive/buffered clips. It validates
start/completion counts, exact scheduled sample bytes, finite numeric trace
coverage, mode selection and empty buffers/timers after each clip. Input public
PCM is passed through child stdin and is excluded from result files; clocks,
nodes and playback are simulated. It does not launch Chrome or a server.

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  python -B -m pytest -q -p no:cacheprovider \
  tests/unit/test_speech_fixture_integration.py
```

Three integration cases run in ordinary existing CI using generated silence;
the retained-public-pack case explicitly skips when the asset is absent. To run
that additional local case, set `SPEECH_TIMING_QUALIFIED_PACK` to the immutable
timing-v2 folder. No PCM, local receipt, machine path, credentials or attended
evidence is added to Git. `SPEECH_TIMING_RECEIPT_DIR` optionally saves numeric
results to an existing directory. The local exact-pack case checks all 296,640
samples, 124 chunks, the SDK stream interface and the same shared-player quartet.

This is an offline integration candidate. It does not modify the qualified
helper/browser actor or install an automatic observer into the app. A future
attended helper needs its own explicit observer attachment/lifecycle integration,
source review and affected silent-browser qualification. Old attended aggregate
gap measurements remain unchanged; these fake-clock results cannot establish
physical latency or a user's mode preference.

## Remaining gates

`browser_attachment.cjs` now supplies an explicit before-app factory hook for
the public-fixture helper. It attaches the reviewed observer to the app's actual
lazy player, including the first payload when a speaking notice is missing.
It composes with the existing helper's later prototype observer and follows
the four serial epoch-zero clip IDs. It never constructs or resumes audio.
Out-of-order clips or a second player reject timing evidence while application
playback continues. Disposal restores only the factory/methods still owned by
the observer; it preserves newer owners.

`ActorTimingBridge(actor, timed_fixture, receipt_dir=existing_directory).attach()`
wraps an existing **offline** actor's observer installation and observation.
Pass the same `TimedFixture` instance to the existing fake SDK runtime. The
original actor still owns all operations and its observations are returned
unchanged. Completed reports are validated against source streams before the
bridge saves numeric source/browser rows and classifications. Call
`bridge.require_quartet()` after the actor finishes and `await bridge.close()` in
`finally`. Both actor and browser attachments are explicit and single-use.
Closing retires the browser observer and registers an inert disable script so
the observer stays retired across refresh regardless of init-script order.
A second bridge cannot reuse the same actor or page after closure. The
qualified helper files and public fixture are unchanged; no new launcher
or automatic application import is added.

The focused `tests/unit/test_speech_actor_attachment.py` uses fake pages and a
VM running the production player with fake nodes/clocks. It covers the deferred
factory, existing prototype observer, first payload, shared B/P/P/B quartet,
sample identity, owner replacement, malformed snapshots and partial evidence.
The retained-public-pack case runs locally when explicitly selected and skips
in hosted CI when that unpublished asset is absent. These are eight new source
contracts, not an actual Chrome/Safari or attended helper qualification. The
bridge deliberately supports offline actors only until that later scope is
qualified; it cannot be used to start an attended session.

Source preparation at `51c56bb` has eight passing contracts, independent source
review, and one affected muted-Chrome check using the qualified actor, native
WebSocket, fake input/SDK/AudioContext and three 100 ms silence chunks per clip.
That check completed four reports and verified observer retirement and owned
cleanup in 14.46 seconds. It does not qualify the full public fixture in Chrome,
an actual AudioContext, physical devices or attended use. Retained receipts stay
outside Git. Reuse these results while their source and harness hashes match.

The [installation and physical-check plan](acceptance-plan.md) separates ordinary
Medium use from optional timing research. An attended adapter still needs its own
implementation, review, exact helper/source/fixture freeze and affected silent
qualification before a readiness request. Do not bypass the offline-only check
or relabel a real-device actor as offline. None of those steps starts a session
automatically.

A future explicitly approved public-fixture session can collect these rows
and a per-mode human gap/overlap/quality/preference report. Actual audible
onset requires a defined acoustic measurement; ACK/scheduling proxies must
remain labeled. Native Safari listening, comparative terminology usability,
and physical Windows coverage are separate. None blocks ordinary installed
Medium use.
