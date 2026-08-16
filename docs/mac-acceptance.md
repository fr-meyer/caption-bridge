# Mac acceptance checklist

Use this checklist before merging a reliability change from `dev` to `main`.
Run it on the Mac that owns the microphone and speakers; keep development and
automated validation on GCP.

Do not paste captions, provider responses, API keys, or exported transcript
content into the acceptance record.

For the final post-v1 P1 gate, use this checklist together with
[`mac-soak.md`](mac-soak.md). The soak runbook adds the mandatory continuous
120-minute window, checkpoint schedule, abort and rerun rules, and evidence form.

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

1. Run `make ctl-start`, then `make ctl-status`.
2. Confirm the service reports `http://127.0.0.1:8765`.
3. Confirm it does not bind to a public interface.
4. Open the loopback URL in the browser.
5. Confirm readiness reaches the startable state without displaying provider
   response bodies or credential values.

## 3. Live captions and speech

1. Start a short session and speak several complete and fragmentary sentences.
2. For the semantic-boundary check, say the public fixture
   `이 결과는 통계적으로 유의미하지만`, pause briefly, then continue with
   `추가 검증이 필요합니다.` An equivalent non-sensitive Korean connective
   fixture is acceptable when recorded only by case/result, not transcript text.
3. During the brief pause, confirm the complete fragment remains visible as a
   responsive source partial and does not create standalone translation or TTS.
4. After the continuation, confirm exactly one merged finalized caption,
   translation, export segment, and live TTS item are produced.
5. Say a clear formal/polite ending such as `맞아요` or
   `이 결과는 유의미합니다`; confirm it finalizes at the ordinary pause
   without the additional hold.
6. Confirm other partial source text remains responsive.
7. Confirm finalized captions remain ordered and are not duplicated.
8. Confirm translated captions appear and TTS plays in the selected language.
9. Mute and unmute TTS; captions must continue while muted.
10. Replay one completed caption; live captions must remain responsive.
11. Confirm the browser console and server log contain no caption excerpts,
    translations, credentials, or provider response bodies.
12. Record only pass/fail and timing bands. With defaults, a clear boundary is
    expected after the 1500 ms pause. An incomplete fragment has a 4500 ms total
    policy target when no continuation arrives; allow modest event-loop and
    provider scheduling jitter, but treat materially longer stalls as a failure.

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
6. Run `make ctl-stop`, then `make ctl-status` twice.
7. Confirm both status calls say stopped and no server remains on port 8765.
8. Repeat start and stop once; confirm both commands are idempotent and emit no
   credentials, transcript content, or provider response bodies.

## Pass criteria

All mandatory steps pass at the candidate commit. The controlled network
interruption may be deferred only if the reason is recorded; reconnect unit
coverage and GCP CI do not replace the remaining Mac hardware checks.

A short acceptance run does not satisfy the two-hour gate. A failed or
interrupted soak cannot be completed by adding time from a later session.
