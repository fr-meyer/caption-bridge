# Optional exact-candidate two-hour Mac soak

The P1.4 product-path gate in
[issue #35](https://github.com/fr-meyer/caption-bridge/issues/35) is complete.
The current [roadmap](https://github.com/fr-meyer/caption-bridge/issues/23) and
[CLI support scope](mac-cli.md) make this run optional, non-blocking endurance
evidence. It is not a prerequisite for each maintenance release.

When an optional soak is chosen, follow the continuous-window and evidence
rules below. Development, review, and automated validation remain on GCP.
Only the bounded microphone, speaker, browser, TCC, and lifecycle run happens
on the Mac. Obtain a recording allowance and provider spend ceiling that
cover the chosen run before starting it.

The qualifying run is one continuous 120-minute listening session at one exact
reviewed candidate commit. Time from separate sessions cannot be combined. A
candidate change invalidates the result and requires a complete rerun.

Do not post or copy captions, translations, prompts, provider bodies, exception
messages, credentials, environment values, exported transcript content, or
machine-local paths. The evidence packet contains only commit identifiers,
versions, timestamps, durations, aggregate counters, bounded state labels, and
pass/fail results.

## 1. GCP candidate gate

Complete these steps in the canonical GCP checkout before reserving the Mac
window:

1. Select the reviewed `dev` commit and record its full SHA in the current
   acceptance issue or PR.
2. Confirm the GCP worktree is clean and the candidate is the expected branch
   head.
3. Run `uv sync --frozen` and `make check`.
4. Run `make browser-setup` if Chromium is not already installed, followed by
   `make browser-e2e`.
5. Review `make reliability-report`. Treat rates and deltas as observations,
   not invented release thresholds.
6. Confirm all required CI jobs pass for the exact candidate.
7. Confirm no unresolved review thread or requested change applies to the
   candidate.

Do not start the physical gate if the candidate, dependency lock, test result,
or review state changes after this check.

## 2. Mac preflight

Use the existing Mac checkout only during the explicitly approved window. Do
not edit source or configuration as part of acceptance.

1. Confirm the checkout is clean before changing its revision. Stop if it is
   dirty; do not discard another person's work.
2. Check out the exact candidate SHA recorded in the current acceptance issue
   or PR and verify it again with `git rev-parse HEAD`.
3. Run `uv sync --frozen`. Confirm GCP `make check` and required CI passed
   for the same exact candidate; do not move automated validation to the Mac.
4. Confirm required `.env` key names are present without printing values.
5. Confirm microphone permission belongs to the terminal or application that
   will own the runtime.
6. Confirm the intended input and output devices are available without
   changing the system defaults automatically.
7. Confirm port 8765 is free and `HOST` is unset or exactly `127.0.0.1`.
8. Confirm unrelated Mac work will not be disrupted. Do not run a whole-machine
   network interruption unless it has its own safe maintenance approval.
9. Record macOS, browser, input-device, and output-device names. Do not record
   serial numbers or private local paths.

## 3. Start and establish the baseline

1. Run `make ctl-start`, then `make ctl-status` twice.
2. Confirm both status results identify one healthy loopback endpoint at
   `http://127.0.0.1:8765` and one owned process.
3. Open the endpoint in the chosen browser and wait for the startable state.
4. Start listening and begin the monotonic 120-minute timer only after live
   capture is active.
5. Record the start timestamp and session identifier if the UI exposes one.
   Never record a caption or export path.

A startup attempt that fails before listening begins may be diagnosed and
retried within the same reserved window. Once the timer starts, any application
restart, capture-pipeline replacement, Mac sleep, candidate change, or operator
pause invalidates the qualifying run.

## 4. Continuous 120-minute schedule

Keep ordinary, non-sensitive live audio available throughout the session. The
content itself is not evidence. At every checkpoint, record only the fields in
the table below.

| Elapsed | Required action |
|---:|---|
| 00 min | Confirm listening, translation availability, TTS readiness, one browser, and a healthy loopback service. |
| 15 min | Confirm source partials remain responsive, finalized captions remain ordered, and queue/reconnect notices are not stuck. |
| 30 min | Mute TTS for at least two minutes, confirm captions continue, then unmute and confirm later speech can play. |
| 45 min | Replay one completed caption and confirm live captions remain responsive without duplicate live speech. |
| 60 min | Refresh the browser once. Confirm snapshot restoration, a single capture pipeline, and audio locked until the replacement document explicitly enables it. |
| 75 min | Enable audio in the replacement document and confirm current TTS resumes without replaying the old queue automatically. |
| 90 min | Close the caption tab, open a new tab at the loopback endpoint, and confirm browser reconnection/replacement, state restoration, and document-scoped audio relock. |
| 105 min | Confirm the service is still listening, no persistent degraded/reconnect banner is stale, and visible sequence order remains monotonic. |
| 120 min | Stop listening normally. Record the terminal state and choose export or explicit discard; never leave the choice implicit. |

A transcription/provider reconnect is not forced by disrupting the whole Mac.
If one occurs naturally, record only cycle count, aggregate downtime, retry
count, and terminal outcome from the reliability record. If none occurs, record
zero. Browser refresh and replacement still exercise the local WebSocket and
document restoration path. Bounded fault-injection coverage remains in the GCP
full-pipeline and browser gates.

### Checkpoint fields

For each row above, record:

- elapsed minute and wall-clock timestamp;
- controller state: `running` or another bounded state label;
- UI state: `listening`, `degraded`, `reconnecting`, or `stopped`;
- action result: pass / fail / not yet applicable;
- content-free observation, limited to aggregate counts, timing bands, or a
  failure-class label.

Do not paste the server log or browser console into the record. If diagnosis is
needed, inspect them locally and summarize only the failure class after checking
that no content or provider body is present.

## 5. Stop, terminal choice, and leak checks

After the 120-minute checkpoint:

1. Stop listening through the UI.
2. Select either local export or explicit discard. If exporting, keep the
   transcript-bearing artifact local and report only `succeeded` or `failed`.
3. Wait for TTS and translation draining to settle within their configured
   bounds.
4. Run `make ctl-status`; the service may still be healthy while the session is
   stopped.
5. Run `make ctl-stop`, then `make ctl-status` twice.
6. Confirm both status calls report stopped, port 8765 is released, and no owned
   capture, translation, TTS, browser-queue, or reconnect task remains.
7. Run one short `make ctl-start` / `make ctl-status` / `make ctl-stop` /
   `make ctl-status` cycle to verify idempotent recovery after the long session.
8. Run `make ctl-stop` and `make ctl-status` once more; both must remain safe and
   idempotent.

Generate the content-free summary locally:

```bash
uv run python -m scripts.reliability_report --json
```

The report may be summarized in the current acceptance issue or PR. Do not
attach the entire reliability directory, transcript exports, journals, controller state, `.env`, or logs.

## 6. Pass criteria

The soak passes only when all of the following are true:

- the full 120 minutes completed continuously at the recorded exact candidate;
- GCP, CI, browser E2E, and Mac preflight gates were green for that candidate;
- the listener remained loopback-only and the owned runtime did not restart;
- partials remained responsive and finalized sequence order showed no observed
  gaps or duplicates;
- mute/unmute, manual replay, browser refresh, browser replacement, state
  restoration, and document audio relock passed;
- any natural provider degradation or reconnect remained bounded and reached a
  terminal recovered or exportable state;
- aggregate queue peaks were finite and no queue showed continuing growth at
  the final checkpoints;
- export or discard was explicit and the reliability record reported the same
  terminal outcome;
- graceful stop, repeated status, port release, and the post-soak idempotency
  cycle passed with zero owned tasks or listeners left behind;
- the evidence packet contains no transcript, provider, credential,
  environment-value, exception-message, or local-path content.

Normal provider failures do not automatically fail the soak when the product
degrades as designed, stays usable, remains bounded, and shuts down cleanly.
An unbounded retry, stuck queue, silent sequence loss, duplicate final delivery,
capture restart, or shutdown leak always fails it.

## 7. Abort and rerun rules

Abort immediately if any of these occurs:

- the checkout is dirty, the candidate SHA differs, or source changes during
  the run;
- the service binds outside loopback or another process owns the configured
  port;
- microphone permission or the intended input disappears and capture cannot
  continue without restarting;
- the Mac sleeps, reboots, or the runtime/capture pipeline restarts;
- credentials, provider bodies, captions, or translations appear in default
  diagnostics;
- a retry loop, queue, browser replacement, export/discard, or shutdown cannot
  settle within its configured bound;
- continuing would disrupt unrelated Mac work or require an unapproved
  whole-machine network change.

After an abort, stop the owned runtime gracefully and preserve unrelated work.
Diagnose on GCP using synthetic fixtures whenever possible. A corrected commit
is a new candidate and requires a fresh, uninterrupted 120-minute run; do not
splice evidence from the failed run.

## 8. Content-free evidence form

Post one final comment to the current acceptance issue or PR using this structure:

```text
Candidate SHA:
GCP make check: pass / fail; test count:
GitHub Actions Python 3.11 / 3.13: pass / fail
GCP browser E2E: pass / fail; test count:
Mac date and timezone:
macOS / browser:
Input / output device class:
Continuous listening: 120 minutes pass / fail
Checkpoint results: 00, 15, 30, 45, 60, 75, 90, 105, 120
Translation totals: completed / source-only / timed-out / capacity-exhausted
Repair totals: checked / attempted / succeeded / still-flagged
Reconnect: cycles / attempts / aggregate downtime band / outcome
Queue peaks: audio / WebSocket / TTS; drops or coalescing by count
TTS: completed / retries / guardrail skips / failures
Terminal choice: export-succeeded / export-failed / discarded
Post-stop lifecycle: stopped twice / port released / idempotency cycle
Owned task or listener leaks: zero / nonzero
Whole-machine network interruption: separately passed / deferred with reason
Sensitive-content review: pass / fail
Overall result: pass / fail
Content-free deviations:
```

Use integer counts or coarse timing bands. Do not infer transcript quality from
private live content in the public record. File a synthetic regression case for
any product defect that can be reproduced without retaining meeting audio or
text.

## 9. Cleanup and roadmap closeout

1. Keep or discard transcript exports only through the existing explicit local
   retention controls; do not add automatic cleanup for the soak.
2. Remove any disposable copied configuration or temporary evidence file made
   for the bounded window. Do not remove ordinary user data or broad folders.
3. Leave content-free reliability history local unless the operator explicitly
   chooses to retain it.
4. Restore the Mac checkout only if requested and only after confirming it is
   still clean. Never discard user changes.
5. Record the optional endurance result only after the evidence form proves
   a passing exact-candidate run. Preserve the existing P1.4 completion record;
   do not reopen that completed gate because an optional soak was skipped.
6. If the whole-machine network test remains deferred, track it separately; it
   does not authorize GCP networking changes, public binding, or unrelated Mac
   disruption.
