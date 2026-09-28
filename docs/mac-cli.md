# Supported Mac CLI distribution

Caption Bridge is a **repository/CLI** product. Do not install a signed app,
LaunchAgent, login item, cron job, or public listener.

This is the P2 supportability path after P1.4. The accepted product-path bar is
the five-minute exact-candidate run closed in issue #35. A two-hour soak is
optional endurance only.

## Install

1. Clone the private repository and check out the approved commit.
2. Copy `.env.example` to a Mac-local `.env` and set `MISTRAL_API_KEY`. Never
   paste that value into issues, logs, support bundles, or chat.
3. Install PortAudio (`brew install portaudio`) and `uv` 0.12.x.
4. Run `uv sync --frozen` so the repository-local `.venv` exists.
5. Confirm identity: `make identity`.
6. Run software preflight: `make preflight`.
7. Start on demand with `make ctl-start`, then open `http://127.0.0.1:8765`.

Microphone and TCC ownership stay on the Mac process that opens the input.
Grant Microphone permission to that process on first run. Do not copy `.env`
off the Mac.

## Upgrade

1. `make ctl-stop` and confirm `make ctl-status` reports stopped.
2. Fast-forward the checkout to the next reviewed commit. Do not mix local
   source edits into a live runtime tree.
3. Run `uv sync --frozen`.
4. Confirm `make identity` shows the expected package version and git SHA.
5. Start only when needed.

## Rollback

For v0.4.0, the immediate published rollback is immutable `v0.3.0`
at `1542b462534590b7183765d9071efff4ae9e65ab` on `main`.
Earlier `v0.2.1`, `v0.2.0` and `v0.1.0` tags remain available.

1. Stop the controller.
2. Check out that tag or SHA in a clean tree.
3. Run `uv sync --frozen`.
4. Confirm identity, then start only if a live session is required.

## Uninstall

1. `make ctl-stop` and confirm the controller is stopped.
2. Remove the repository checkout if it is no longer needed.
3. Optionally delete owner-only runtime state and logs:
   `~/Library/Caches/CaptionBridge` and `~/Library/Logs/CaptionBridge`.
4. Do not delete unrelated browsers, TCC grants for other apps, or other
   repositories.

## Support bundle

When something fails, collect only aggregate diagnostics:

```bash
make support-bundle
```

The bundle contains package/git identity, software preflight, controller
state without filesystem paths, and content-free reliability aggregates.
It must not contain captions, translations, provider bodies, credentials,
environment values, or local paths.

## Accessibility and browser notes

Current supported operator browser is Chromium/Chrome against the loopback
UI. Safari should load the same loopback page but is not the acceptance
browser.

Keyboard-only use: Start, Stop, Export, New Session, and settings controls
are native buttons/selects. Icon-only controls now have accessible names.
Status and provider notices use `role="status"`.

Visual: respect `prefers-reduced-motion`. Focusable controls use a visible
`:focus-visible` outline. Do not rely on color alone for Ready vs blocked.

Screen-reader semantics remain a follow-up audit if a second operator who
depends on VoiceOver is onboarded. Do not treat this document as a complete
WCAG certification.

## Non-goals

- LaunchAgent or automatic startup
- signed/notarized `.app`
- issue #13 provider work
- public bind
- treating merged-to-`dev` as released
