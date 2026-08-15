# Mac acceptance checklist

Use this checklist before merging a reliability change from `dev` to `main`.
Run it on the Mac that owns the microphone and speakers; keep development and
automated validation on GCP.

Do not paste captions, provider responses, API keys, or exported transcript
content into the acceptance record.

## Record

- Commit:
- Date:
- macOS version:
- Browser:
- Input device:
- Output device:
- Result: pass / fail
- Content-free notes:

## 1. Install and readiness

1. Check out the exact candidate commit.
2. Run `uv sync --frozen`.
3. Confirm the Mac-local `.env` contains the required key names without
   printing their values.
4. Confirm macOS grants microphone permission to the owning terminal or app.
5. Confirm port 8765 is free.
6. Run `make check`; all checks must pass.

## 2. Loopback and startup

1. Run `make run`.
2. Confirm the service reports `http://127.0.0.1:8765`.
3. Confirm it does not bind to a public interface.
4. Open the loopback URL in the browser.
5. Confirm readiness reaches the startable state without displaying provider
   response bodies or credential values.

## 3. Live captions and speech

1. Start a short session and speak several complete and fragmentary sentences.
2. Confirm partial source text remains responsive.
3. Confirm finalized captions remain ordered and are not duplicated.
4. Confirm translated captions appear and TTS plays in the selected language.
5. Mute and unmute TTS; captions must continue while muted.
6. Replay one completed caption; live captions must remain responsive.
7. Confirm the browser console and server log contain no caption excerpts,
   translations, credentials, or provider response bodies.

## 4. Browser replacement

1. While listening, refresh the browser once.
2. Confirm the old WebSocket is replaced and the session snapshot restores the
   current state.
3. Confirm captions continue without creating a second capture pipeline.
4. Confirm TTS remains locked until the replacement browser enables audio.

## 5. Controlled network interruption

Perform only when interrupting the Mac network is safe.

1. While listening, interrupt network access briefly.
2. Confirm the browser shows a transcription-unavailable/reconnecting notice.
3. Restore the network within the configured reconnect budget.
4. Confirm the browser reports recovery and finalized sequence identifiers
   remain ordered without duplicates.
5. Repeat with an interruption longer than the configured budget.
6. Confirm retries stop, the session becomes exportable, and shutdown does not
   hang.

## 6. Stop and export

1. Stop the session.
2. Confirm microphone capture and TTS end promptly.
3. Export the session locally.
4. Confirm the export succeeds and its quality summary is present.
5. Start a new session and repeat a short start/stop cycle.
6. Stop the owning process with `Ctrl-C` and confirm clean shutdown.
7. Confirm no Caption Bridge server remains listening on port 8765.

## Pass criteria

All mandatory steps pass at the candidate commit. The controlled network
interruption may be deferred only if the reason is recorded; reconnect unit
coverage and GCP CI do not replace the remaining Mac hardware checks.
