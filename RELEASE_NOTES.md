# Release notes

## v0.2.0 - Planned

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
