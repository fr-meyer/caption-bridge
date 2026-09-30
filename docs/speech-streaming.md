# Earlier spoken readback prototype (#65)

This candidate is stacked on frozen PR70 (bf587c51), with no change to its branch.
Buffered whole-clip playback remains the default. Set
`MISTRAL_TTS_STREAMING_PLAYBACK=true` only in an isolated evaluation configuration
to select progressive PCM playback. The snapshot freezes that choice for each
new clip. No provider request format/model, translated caption, microphone path,
translation dispatch or terminology provenance changes.

## Player and cancellation

The progressive mode collects 150 ms of mono float32 PCM at 24 kHz, then schedules
adjacent Web Audio buffers against the audio clock with a 20 ms initial margin.
A short clip starts at EOS. Later buffers remain contiguous when data arrives in
time; late arrival increments numeric underrun/gap counters. A subsequent clip
waits until the preceding clip has both received EOS and finished every scheduled
source. There is no promise of audible onset at the scheduling timestamp.

Both modes share the same bounded player and protocol. Each accepted live/replay
job receives a monotonic clip ID. Speaking/audio/error/skipped messages and browser
ACKs carry `clip_id` plus `seq` and `tts_epoch`. Sequence identifies the caption;
clip identity distinguishes repeated replays. Duplicate completion is harmless,
and one failed replay cannot delete earlier audio for that caption. Legacy ACKs
are accepted only when one pending clip matches that caption and epoch.

Catch up, mute, snapshot/session transition and reconnect cancel every scheduled
source and invalidate a pending `AudioContext.resume()` callback. Retired clip IDs
are held in a bounded 256-entry rejection set so late chunks cannot restart a
completed/cancelled clip. An authoritative snapshot resets this rejection set,
allowing clip numbering to restart with a new server process; callbacks from a
replaced/closed WebSocket are ignored. Native binary frames use ArrayBuffer
and decode synchronously, preserving large PCM/snapshot frame order ahead of small
subsequent events; independent Blob.text promises can complete out of order. Captions and replay controls remain available.

A disconnected/replaced browser loses its document-local audio. The dispatcher
advances its epoch, cancels active synthesis, retires dispatched clips, and
rebases unsynthesized server-queued jobs into the new epoch. It does not retain a
phantom backlog or resynthesize sent audio automatically. The replacement must
unlock audio again. This fixes the independently reproduced PR70 refresh defect.

## Fixed limits and recovery

At most 64 pending clips exist on either side. The player retains at most 32 MiB
of PCM payload across clips, 60 seconds per clip and 512 payload chunks per clip.
Small chunks are coalesced before scheduling. Each clip has a 30-second missing
chunk/EOS timeout (started when speaking begins and renewed by each valid chunk).
Decoded float32 bytes may cross network chunk boundaries; the final tail must
align to four bytes. Duplicate indexes are ignored; a missing/out-of-order index,
invalid PCM, exhausted buffer, timeout or playback failure cancels that clip and
shows a replayable interruption. Browser failure retires the exact pending server
clip and cancels its active synthesis. There is no retry after partial audio.

PCM payload limits bound retained audio, not total JS heap: base64, typed-array and
AudioBuffer copies add transient overhead. These are prototype limits that can
reject unusually long clips. They must be checked with representative public
samples before enabling the mode in normal use.

## Content-free diagnostics

Reliability schema4 adds `speech_playback`; schema1/2/3 histories remain readable.
All sample arrays are capped at2048. The record contains only fixed modes/reasons,
numeric counts and distributions (median/p90/p95/p99/max/outliers):

- Request enqueue → inbound first browser chunk ACK, using only Python monotonic time.
- First received chunk → first source scheduling/start, including browser queue wait.
- First received chunk → initial buffer ready, on the browser performance clock.
- Completed clips, late-buffer underruns and gap milliseconds by mode.
- Buffer-limit, missing-chunk, invalid-PCM, timeout and playback-failure totals.

Browser clocks are never subtracted from server clocks. No PCM/base64, caption,
provider body, term, prompt or per-clip identity is persisted in diagnostics.
First-chunk and completed stats ACKs are idempotent and require a pending clip in
the current epoch. Old sequence-only latency diagnostics remain for compatibility;
the new per-clip browser measurements should be used for repeated-replay comparisons.

## Verification and remaining gate

Provider-free tests use silent PCM and fake audio clocks/sources. They prove
progressive scheduling before EOS, buffered fallback, order, contiguous offsets,
measured late gaps, odd byte-boundary decoding, duplicate/missing chunks, bounded
memory/timeouts, cancellation during resume and playback, exact replay identity,
reconnect queue rebasing and history/privacy contracts. Existing full browser,
Python and synthetic pipeline checks must pass on the frozen candidate.

These checks cannot establish speaker onset, voice quality, intelligibility,
Safari device behavior or provider chunk cadence. An attended Safari/Chromium
comparison with an approved public/synthetic speech sample remains required before
turning streaming on by default. Compare the same input in buffered and streaming
modes, startup/buffering distributions, underruns and interruption/replay behavior.
The acceptance owner coordinates the frozen64/70/71 combined review and enforceable
provider budget harness; #65 remains a separate follow-up until combined validation.
Issue67's silent evaluation rules out naive resampling as a pitch-preserving faster
setting; its human listening/design decision is independent of this opt-in mode.
