# Mac acceptance checklist

Use this checklist when a post-release Mac device/listening follow-up is chosen.
Following the owner's October 19, 2026 direction, these checks are nonblocking
and are not a prerequisite for `dev` to `main` promotion. This replaces the
checklist's former pre-promotion timing; historical results keep their original
scope. Required software checks, CI, source review and separately authorized
promotion remain governed by the [release procedure](operations.md#release-procedure).
Run it on the Mac that owns the microphone and speakers; keep development and
automated validation on GCP.

Meeting activation still requires separately authorized current actual-device
evidence. Use hosted CI for software checks and the
[current protocol](candidate-validation-20261116.md) for the November 17 meeting.

Do not paste captions, provider responses, API keys, or exported transcript
content into the acceptance record.

The P1.4 product-path gate was completed by the exact-candidate five-minute
run recorded in [issue #35](https://github.com/fr-meyer/caption-bridge/issues/35).
The current [roadmap](https://github.com/fr-meyer/caption-bridge/issues/23) and
[CLI support scope](mac-cli.md) make the two-hour run optional, non-blocking
endurance evidence. Use [`mac-soak.md`](mac-soak.md) only when that separate
run is chosen; its continuous-window rules do not add a release prerequisite.

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
6. Confirm `make check` and required CI passed for this candidate on GCP.
   Keep automated validation on GCP; run hardware/readiness preflight on the Mac.

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

A short acceptance run does not constitute a two-hour endurance result. If
an optional soak is selected, a failed or interrupted run cannot be completed
by adding time from a later session.

Physical VoiceOver and second-operator onboarding are follow-up audits under
the [CLI support scope](mac-cli.md). Record them as unperformed when they have
not occurred; do not claim screen-reader certification or new-operator evidence.


## Historical draft integration #64 and startup choice #68

Historical context: #64 is superseded and Medium shipped in v0.5.0. The
following old candidate instructions do not describe an unshipped feature.
The October 13 acceptance record is the baseline; changes need their own
affected evidence. Preserve recorded deferrals and use the current protocol.

This is the remaining physical gate for the combined profile/model/thinking
candidate. Passing GCP CI or the earlier native Safari synthetic fixture does
not complete it. Use the exact candidate commit and the identity reported by
the isolated app; the published v0.4.0 result cannot be reused for changed code.

Current decision: the draft starts on Medium unless an explicit
`MISTRAL_TRANSLATE_MODEL` override selects another model. GLM remains
experimental. Issue #68 is implemented in the draft but remains open for the
device judgment and reviewed release. No Windows run is required to establish
Mac CLI support; any Windows acceptance requires its own device authorization.

### Operator and device prerequisites

An attended operator must provide the physical Mac, its already-authorized
microphone, intended browser and output device, and a quiet public-fixture
source. Stop unrelated playback so background speech cannot invalidate the
run again. Make an isolated exact-candidate checkout on a separate loopback
port with separate journal/export/reliability directories. Preserve the
canonical checkout, production configuration and service state.

A live run sends its captured audio and translations to configured providers.
Obtain the owner's authorization for the concrete live-public-audio/provider
scope before starting; this checklist adds no spend, permission-change or
deployment authorization. Any agreed one-off request limit applies to that test,
not ordinary product sessions. Never use private seminar
audio or a private export as a test fixture. Keep the raw local export private;
record only counts, model IDs, timing bands and pass/fail outcomes.

### Candidate-specific checks

1. Record exact commit, app identity, effective model override by model ID,
   browser, input/output device and public fixture case IDs.
2. Verify first Start selects Medium when no override exists. Verify a
   deliberate override or pre-Start GLM choice is honored. GLM shows the
   experimental/missed-or-delayed-caption note.
3. In a short controlled Korean session, check complete endings, the public
   connective-pause case in section 3, negation, numbers and representative
   terminology. Judge source responsiveness, target readability and latency
   separately. Record any missing/failed/timed-out captions; an unexplained
   failure blocks claiming GLM reliable.
4. Change model and thinking live; verify the status names the selected model
   and only future finalized segments change. Keep the chosen caption timing
   profile. Inspect private export metadata locally for per-caption requested
   and reported model, thinking level, cap, profile and usage.
5. Refresh while listening. Confirm the selected model restores from the
   session, capture does not duplicate, and spoken readback waits for the
   replacement browser's Enable audio gesture.
6. Listen to translated speech on the intended output device. Judge
   intelligibility/order and check mute, unmute and replay while captions
   continue. A translation failure is a missing translation, not evidence of
   a speech backlog.
7. Stop and export, then New Session. Confirm it restores the effective
   configured startup model and Provider default thinking. Check shutdown
   and loopback ownership using the existing lifecycle steps.
8. Record GLM quality, failures, latency and usage against the existing public
   evidence. Easy GCP compatibility cases are insufficient. Keep GLM
   experimental until this representative result and owner judgment support
   changing the startup decision.

The operator must mark unperformed checks explicitly. Physical VoiceOver,
visual contrast and second-operator onboarding remain follow-up judgments
under the CLI support scope; automated WebKit/axe results do not stand in for
them. A version/release decision, environment-override review and rollout/
rollback approval remain separate after acceptance. Do not promote, merge or
deploy as part of this record.

The [October 12 Medium record](acceptance/medium-mac-2026-10-12.md) closes the
single public Korean ASR → Medium → buffered-speech case on its exact runtime
tree. It lists the broader checks that were not performed; do not treat it as
completion of the whole checklist or as an installed-app upgrade.
