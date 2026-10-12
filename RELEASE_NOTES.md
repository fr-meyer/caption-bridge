# Release notes

## v0.5.0 candidate — unreleased

This proposed minor release prepares the source integrated by PR #82 into
`dev` at `a5e81b6bcc8a3eecec88d38283c3099a38c79257`. Published `main` remains
v0.4.0. See the [release-readiness record](docs/release-readiness-0.5.0.md).

- Select translation models and caption timing profiles before Start or in
  Settings. Medium is the startup default; explicit environment overrides win.
  Model/thinking changes affect future captions and preserve in-flight requests.
  GLM 5.3 and Large 4 remain optional previews without a live-reliability claim.
- Preserve requested/reported model, thinking, token cap, usage, profile and
  terminology revisions in private exports/recovery. Reject token-limited
  partial answers and truncated repairs rather than speaking incomplete text.
- Show unfinished speech and provide Catch up and Replay. Per-clip identities
  and epochs isolate replay failures and stale acknowledgements. Progressive
  playback remains opt-in; buffered playback and normal speed remain defaults.
- Confirm or undo session terminology changes while preserving original ASR
  text and earlier captions. Export analysis avoids counting identical snapshots
  twice and retains the session's configuration scope.
- Show connection loss, protect an attached browser's ownership, verify ASR
  readiness/settings, accept final-only text safely and drain admitted capture
  tails before input completion. Diagnostics remain content-free.
- Update the development/test dependency `urllib3` to 2.8.0 for the reported
  proxy-TLS, Deflate-loop and chunk-size buffering fixes. The production
  dependency closure and application behavior remain unchanged.

Exact merged-dev CI passed Python 3.11/3.13 and Chromium. The attended October 12
public Korean ASR → Medium → English buffered-speech case passed with a clear
human hearing verdict. The earlier public prerecorded Catch up/Replay result
retains its playback-only scope. These results do not complete the broader Mac
release checklist or establish GLM/Large 4, physical Windows, VoiceOver or
long-session reliability. No repeated audio session was used for this preparation.

The proposed immediate rollback is immutable v0.4.0. Publication, any Mac-local
model override change and activation remain separate from this local candidate.

## v0.4.0 - 2026-09-28

- Add optional, bounded terminology preferences before Start, tied to a session
  and target language. Browser storage requires explicit opt-in.
- Send only preferred terms whose source occurs in the current caption segment.
  Terms appearing only in earlier context or elsewhere in the glossary are
  withheld from translation and repair prompts.
- Preserve the session glossary in private export/recovery metadata; keep
  diagnostics content-free. Existing provider, call/retry limits and retention
  are unchanged.
- Add the [terminology guide](docs/terminology.md) and offline-by-default
  [public quality evaluation](docs/glossary-quality-evaluation.md) with an
  eight-request cap, durable cost reservations and no automatic retry.

On the final glossary code, eight public-text live quality cases passed. GCP
release gates passed 246 Python tests (1 skipped), 28 Chromium/WebKit browser
contracts, lint, quality/segmentation benchmarks, a 1,000-segment resilience
soak and the full-pipeline scenario. Exact-head GitHub Python 3.11, Python 3.13
and browser checks passed before main promotion. An earlier adversarial case
failed and prompted the matching-term fix; the bounded follow-up passed.
Neither run used a microphone or speech playback. This evidence does
not establish general translation accuracy, human playback quality, complete
VoiceOver support or physical Windows support.

The immutable v0.3.0 release is the immediate rollback. The app remains
on-demand and loopback only; Mistral remains its sole production provider.


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
