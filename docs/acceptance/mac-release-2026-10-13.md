# Owner Mac acceptance — 2026-10-13

The planned owner Mac listening and lifecycle checks completed across two
separately approved windows on exact runtime source
`080ee7aa31ad5bb4ade26e1a695c4d9286983bb1`, application tree
`8853dd29621f3da02a399034bf4fe82844987722`, proposed version `0.5.0`.
The intended path was built-in Mac microphone → Mistral realtime ASR →
Small/Medium translation → normal buffered English speech in Chrome →
Sony WF-1000XM5 output. The operator confirmed clear speech and visible saved
results. Raw audio was not retained; caption-bearing evidence stays private.

## Observed cases

- Supported ordinary CLI startup, readiness, loopback ownership, repeated
  start/status/stop and shutdown passed.
- Medium/default completed the public connective-pause, polite-ending and
  negation/number cases. Medium/high completed the terminology case through
  the actual Settings and terminology controls; private provenance was checked.
- Mid-clip mute cancelled the intended primary, unmute and its sole Replay
  completed, and browser replacement required fresh audio enable while the
  capture pipeline remained singular.
- The follow-up selected Small before Start, completed one caption and speech
  job, changed the actual Settings selector to Medium/Provider default, then
  completed the next caption and speech job with the new model revision.
- Finish input, drain, Stop, export and New Session reset passed. The new idle
  session restored Medium/Provider default and empty terminology. Capture and
  owned servers stopped; exported results remain in a read-only window until
  the operator chooses Close.

Across both windows, three ASR connections opened and closed, five Medium
translations (one High) and one Small translation completed, and seven speech
jobs completed at the provider. Six clips completed browser playback; the
other primary was deliberately cancelled by mute and followed by Replay.
These are observed counts, not product limits or a spending cap.

The first window's restarted session ended on a test-helper timeout before
its Small fixture. Its accepted four-caption result remains valid. The helper
was corrected offline; the separately approved narrow follow-up supplied the
missing Small → Medium speech and reset evidence. The original uninterrupted
two-session live orchestration is not reported as passing. Corrected complete
orchestration passed with silent mocked devices/providers and the production
frontend, preserving the distinction between synthetic and physical evidence.

## Configuration and release scope

The test process used the candidate's Medium default. This does not change
either installed checkout: both still have a saved Small override, which takes
precedence over the code default. Installed Medium activation requires a
deliberate local setting choice and preservation of its prior value for rollback.

Controlled Mac-wide network interruption was deferred to avoid disrupting the
operator's network and adding provider retries outside the approved fixtures.
The default reconnect/connection-ownership tests remain automated evidence.
Two-hour endurance, physical Windows, VoiceOver/second-operator judgments and
experimental-model comparisons retain their separate follow-up scope. This
record does not certify opt-in progressive playback or faster speech physically.

For a documentation-only successor, compare the application tree to the exact
accepted runtime above and retain the source/evidence distinction. No new audio
run is needed for unchanged application bytes. Require exact successor CI and
review under the release procedure. Main promotion, immutable tag/release and
installed activation are separate actions; preserve v0.4.0 as rollback.
