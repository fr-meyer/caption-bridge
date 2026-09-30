# Spoken-readback backlog and Catch up (draft)

Related: [issue #66](https://github.com/fr-meyer/caption-bridge/issues/66).

When spoken readback trails the transcript, the session shows the number of unfinished
speech clips. That count includes a playing clip, synthesis in progress, queued synthesis,
and synthesized clips waiting in the browser. It does not estimate seconds of delay.

**Catch up** stops the current clip and skips every pending spoken clip. It keeps every
caption and translation. Replay still works; new captions continue to receive spoken
readback if speech is enabled. The button explains the action, supports keyboard use,
and announces that captions were kept.

Muting, browser audio permission, and captions-only mode retain their existing meaning.
A refreshed document still requires Enable audio. A new session clears the backlog
and the previous catch-up announcement.

## Queue contract

- The dispatcher counts enqueued speech until playback completion, a synthesis failure,
  an existing queue-pressure skip, mute, drain, or Catch up.
- The tts_queue event reports only tts_epoch, pending_count, and playing_seq. Session
  snapshots include that state and the current epoch.
- The tts_catch_up command carries the browser's tts_epoch. The server advances the epoch,
  clears pending work, cancels synthesis, and sends tts_caught_up. A stale/duplicate
  action returns current state and cannot skip new speech.
- The browser immediately stops its source and clears buffered/queued audio while
  waiting for the acknowledgment. It discards old-epoch events and invalidates pending
  AudioContext resume callbacks. Playback acknowledgments carry the epoch.
- Count/state and acknowledgment events retain WebSocket ordering. Catch up does not
  alter captions, the glossary, translation settings, or provider selection.

Reliability schema v3 records aggregate catch_up_actions and catch_up_skipped
under queues.tts; skipped clips retain the fixed reason user_catch_up. Legacy
v1/v2 history remains readable. These records contain no transcript text or audio.
Cancelled/skipped speech clears its latency stamps, so replay cannot use an old
cancelled request as a new timing sample.

## Provider-free validation and release boundary

Deterministic tests use a fake speech provider and fake Web Audio. They cover synthesized,
queued and active speech; stale requests and callbacks; replay; mute; session replacement;
refresh and audio relock; keyboard activation; counter privacy; and legacy history.

GCP validation uses the existing offline container and cached dependencies with bounded
CPU, memory, process count, and time. No provider call, microphone capture, personal
audio, permission change, host dependency installation, or Mac rollout is required.

Human Safari/Chromium judgment and a reviewed release decision still precede deployment.
Automated WebKit checks establish browser contracts, not physical Safari audio quality.
Keep issue #66 open until those acceptance steps are complete.

## Related audio work

Earlier streaming playback (#65) should retain this clip/epoch contract: playback starts
once per clip, completion is acknowledged once per clip, and Catch up stops every
scheduled source for that epoch. A progressive player should live behind one queue
interface; changing the translation pipeline is unnecessary. First-chunk arrival,
initial buffer duration, under-runs, and request-to-playback delay require separate
content-free measurements and a bounded public-clip comparison.

Playback speed (#67) depends on the chosen playback mechanism. Changing a Web Audio
buffer's playbackRate also changes pitch; provider-free scheduling tests cannot establish
intelligibility. Keep normal speed and do not ship a faster-rate setting until human
Safari/Chromium listening supports a go/no-go decision.

The startup-model decision (#68) stays with draft PR #64; live terminology corrections
(#69) are an independent candidate. This catch-up draft is based on released v0.4.0/dev
and can be integrated through additive TTS hunks after review.
