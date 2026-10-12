# Attended Medium check — October 12, 2026

This record covers one short public Korean source on the isolated runtime
`a9cdc2b6093b98033286c6bcbb87ca9aa9e917dd`. Its application tree is
`9bb804d1655d26df1bd6f11903ee7df94f5dc4fa`; a documentation-only integration
commit may carry this result when that application tree is identical.
The installed checkout and published v0.4.0 were not replaced.

## Setup and scope

- Existing Mac with already-authorized builtin microphone, mono 16 kHz int16.
- Existing Chrome, buffered English speech, Sony earbuds connected and worn.
- macOS 26.7.1 and Chrome bundle 154.0.8037.98 read after the run.
- Public FLEURS Korean test-offset-100 fixture, 12.36 seconds. The local test
  player applied constant gain to peak 0.5 without clipping or a system volume
  change. This player is test equipment; it is not a runtime audio processor.
- The operator explicitly selected `mistral-medium-latest`, Provider default
  thinking, English, empty terminology and enabled speech.
- Isolated server at `127.0.0.1:8899`, with separate export/journal directories.
  Supported product control remains at its configured port, default 8765.

## Observed results

| Stage | Result |
| --- | --- |
| Native capture | Pass: 154 callbacks, 15.4 seconds including setup/tail, no callback or observer failure, no clipped samples or input overflow. |
| App and SDK transport | Pass: 492,800 PCM bytes accepted and locally sent; input flush/end completed. |
| ASR | Pass: one connection, matching model/16 kHz PCM/1000 ms settings ACK, typed Done, one 53-character caption exactly matching the earlier public-fixture reference. |
| Medium | Pass: one completed request, 166 prompt and 20 completion tokens, `stop` finish reason, no repair. Independent text comparison preserved the source meaning. |
| Buffered speech | Pass: one completed TTS request, one browser playback start/completion; operator explicitly confirmed clear English through the earbuds. |
| Finish and cleanup | Pass: capture stopped, completed speech observed before full Stop, export saved, owned server/controller exited, managed microphone RAM cleared. |

No retry or additional live test followed this success. Raw microphone audio and
its digest were not saved. Derived exports stayed private; this record contains
no caption, translation, credential, voice ID or provider response body.
The reported model remained the latest alias; an immutable backend version and
actual invoice cost were not attested. Reported ASR usage is not a measurement
of locally admitted audio duration.

## Acceptance boundaries

The test harness observed PCM and transport, bound the builtin input explicitly,
used read-only idle permission checks and agreed one-off request limits, and kept
saved results available separately from media cleanup. None of those harness
adapters or the public player belongs in the product release. The product uses
its existing native default input and browser output until the separately
reviewed device-selector PR #81 is integrated. The observed system default input
also was the builtin microphone during this successful run.

This single case does not establish the full [Mac checklist](../mac-acceptance.md).
Controlled connective pauses, negation/numbers/terminology cases, live model and
thinking changes, refresh/relock, mute/replay during captions, repeated supported
CLI lifecycle and network interruption were not performed in this run. Earlier
playback-only Catch up/Replay evidence retains its own narrower scope.
GLM, Large 4, progressive playback, Windows and long-session endurance were not
tested here. Windows and the optional two-hour endurance run are separate from
Mac CLI support. Release promotion, installed configuration changes and activation
still require their separately authorized scope.
