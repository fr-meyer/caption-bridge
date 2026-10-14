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
separate helper versions; this portable module does not change that qualified
helper or add it to PR85.

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

## Remaining gates

This is source preparation, not attended qualification. Before using this
observer in an attended helper, independently review its new integration,
freeze exact helper/source/fixture hashes, run only the affected silent
regression and obtain an explicit readiness request. None of those steps
starts a live session automatically.

A future explicitly approved public-fixture session can collect these rows
and a per-mode human gap/overlap/quality/preference report. Actual audible
onset requires a defined acoustic measurement; ACK/scheduling proxies must
remain labeled. Native Safari listening, comparative terminology usability,
and physical Windows coverage are separate. None blocks ordinary installed
Medium use.
