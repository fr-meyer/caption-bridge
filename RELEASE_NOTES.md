# Release notes

## Unreleased

- Add optional, bounded terminology preferences before Start, tied to a session
  and target language. Browser storage requires explicit opt-in.
- Preserve used terms in private export/recovery metadata; keep diagnostics
  content-free. Existing provider, call/retry limits and retention are unchanged.
- Add the [terminology guide](docs/terminology.md). Live provider quality
  acceptance remains separate from synthetic prompt/browser checks.

## v0.3.0 - 2026-09-27

- Add a persistent **Captions only** preference before a session and in Settings.
  It survives New Session, browser refresh and reconnect.
- Stop current playback and suppress queued/new speech and Replay while the
  preference is on. Source and translated captions continue.
- Allow the speaker control to turn spoken readback back on, with truthful
  accessible names and the browser's normal audio-enable gesture.
- Store only a Boolean browser preference; no caption content or credentials
  are stored by this setting.
- Add an [operator guide](docs/captions-only.md). Transcription and translation
  still use the existing provider and can incur charges.

The supported owner Mac repository/CLI path remains on demand and loopback only.
Mistral remains the sole production provider. This release makes no physical
Windows, complete VoiceOver or second-operator support claim. Publication is
identified by the immutable tag and GitHub Release.

## v0.2.1 - 2026-09-27

Maintenance changes for the supported owner Mac repository/CLI path. Release
publication is identified by the immutable tag and GitHub Release, rather than
by a merge to `dev`.

- Add a hosted, synthetic exact-v0.2.0 Windows acceptance workflow and harness.
  Physical Windows runtime acceptance remains pending.
- Improve keyboard and screen-reader semantics, contrast, reduced-motion
  behavior, and failure notices in the browser UI. GCP Chromium and WebKit
  synthetic checks passed. Physical Safari checks covered corrected speech-control
  names, keyboard access, muted captions, live replay, browser refresh/audio
  relock, brief-outage recovery, retry exhaustion, export, and shutdown. Physical
  VoiceOver and second-operator onboarding remain follow-up audits; no complete
  screen-reader certification is claimed.
- Add locked-dependency audit commands and a monthly/pre-release review
  cadence. The concrete deployment-target audit passed for the current
  locked package set. The release keeps that dependency lock unchanged.
- Correct speech-control accessible names when playback is muted or unmuted.
- Reconcile acceptance runbooks with the optional two-hour endurance run and
  existing owner CLI support scope.
- Prevent a delayed export failure from leaving both discard and
  export-failure dialogs open.
- Record research-only Gemini Live Translate evaluation and a current-cycle
  no-go for integration. Mistral remains the only production translation
  provider; no Gemini runtime path or default change was added.

## v0.2.0 - 2026-08-29

Caption Bridge v0.2.0 completes the first post-release reliability and
supportability cycle while preserving the local-first, on-demand product
policy.

### Reliability and observability

- Add deterministic full-pipeline scenarios for transcription recovery,
  translation and TTS failure semantics, browser replacement, export, and
  shutdown.
- Add real-browser end-to-end contracts for degraded captions, reconnect,
  audio relock, export controls, keyboard navigation, and lifecycle states.
- Add content-free reliability history and end-to-end latency accounting with
  bounded aggregate diagnostics only.
- Ignore stale TTS queue waits and cancelled playback acknowledgements without
  weakening sequence or backpressure safeguards.

### Supported distribution

- Document the supported repository/CLI install, upgrade, rollback, uninstall,
  accessibility, and browser path for macOS.
- Add visible package/commit identity, bounded software preflight, idempotent
  on-demand lifecycle controls, and an aggregate-only support bundle.
- Keep `v0.1.0` intact as the previous published rollback.

### Portability

- Make lifecycle and retention locking importable and testable on Windows while
  preserving blocking command-lock semantics and one-byte lock initialization.
- Keep the application runtime Mac-local for microphone/TCC ownership; this is
  not a Windows runtime-support claim.

### Provider and privacy policy

- Mistral remains the default translation provider.
- Gemini Live Translate evaluation in issue #13 remains research-only,
  opt-in, and absent from the default runtime.
- No LaunchAgent, automatic startup, public listener, automatic transcript
  retention, or new paid-provider path is introduced by this release.

## v0.1.0

The initial stable reliability stack remains available as the immutable
`v0.1.0` tag and GitHub Release.
