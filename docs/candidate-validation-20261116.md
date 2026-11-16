# Next-candidate validation, 2026-11-16

Status: tools/protocol prepared, acceptance PENDING. No new version, release,
provider, installation, microphone session or activation is claimed here.
Baseline is published v0.5.0, main merge
39ecd3e7e6eafd367877eff3b0a0ef878a17b127 (PR #84).

## Automated matrix (#23)

- Existing Linux Python 3.11/3.13 jobs: lint, tests, quality/segmentation,
  1,000-segment translation simulation, six-segment pipeline, JS syntax.
- Existing Linux Chromium job: browser contracts.
- New current-head Windows/macOS Python 3.13 jobs: software lifecycle,
  content-free health, reconnect contracts and fake-provider application
  scenario. This is NOT native audio routing or production Windows support.
  The immutable windows-v0.2.0 workflow remains unchanged historical evidence.
- Manual Candidate endurance workflow: select the reviewed candidate branch
  and record the resolved commit. Run once on the exact final candidate.
  No automatic cancellation; job timeout 140 minutes, aggregate artifact 7 days.
  Only checkout read permission, no secrets or provider credentials required.

Parent/integrator must record successful run URLs and immutable SHAs before
promotion. Workflow definitions alone are not successful checks. A changed
candidate invalidates affected evidence. Standard runner availability/setup
failures are unresolved until repaired or explicitly excluded by the owner.

### Endurance command and limits

On the already-prepared CI environment:

Run:

    uv run --python 3.13 python -m scripts.candidate_endurance --minutes 120 --output acceptance/endurance.json

The tool measures monotonic real elapsed time, not simulated segment count.
It repeatedly exercises the existing application pipeline with injected
translation timeout/capacity failure, ASR reconnect failure/recovery, bounded
browser queue pressure, owner conflict/replacement, audio relock, drain/export
and teardown. It fails on a failed scenario, a 45-second cycle timeout or live
async tasks left after teardown. The same event loop survives all cycles;
application sessions reset. This is continuous repeated lifecycle/fault load,
NOT one 120-minute user session, a physical Mac soak, audible playback or real
provider transport validation. It does not establish a resident-memory ceiling.
Existing reconnect unit cases separately cover retry exhaustion and cancellation
before the endurance run. The current ASR lane must keep these contracts passing
and add its own new recovery cases to normal CI. Unhandled failures produce a
content-free exception type, never messages/captions. An interrupted run fails;
do not add durations from separate runs or call short smoke mode two hours.

Fast deterministic tests (standard library, no install):

    python3 -m unittest discover -s tests/unit -p test_candidate_endurance.py -v
    python3 -m unittest discover -s tests/unit -p test_playback_timing_compare.py -v

## Same-input playback observations (#65)

Use one public fixture and fixed clip ordering, duration, ready times, browser,
rate (normal), profile, hardware and network condition. Compare buffered versus
opt-in progressive on separate reset runs; counterbalance order. Retain source
fixture checksum and baseline/candidate SHAs privately with the report. Capture
only actual scheduler event timestamps in milliseconds relative to run start,
not inferred or fabricated audio starts. Adapter/instrumentation and measured
observations remain pending; this lane provides the comparator, not measurements.

    uv run python -m scripts.playback_timing_compare observations.json

Input schema: fixture_id plus baseline/candidate ordered row arrays. Each row
has exactly clip_id, ready_ms, start_ms, end_ms. Identical unique ordered clip
IDs are required. No caption/audio/device fields. Outputs: count, median/p95
ready-to-scheduled-start wait, summed gaps and overlaps. These are SOFTWARE
SCHEDULING metrics only. Same IDs alone do not prove same audio: operator must
verify fixture identity. Pre-register baseline-relative numeric limits after
baseline capture and before candidate assessment. No invented latency target,
no audible-onset, intelligibility or human-quality conclusion. Human listening
and actual browser output observation remain open.

## Terminology usability (#69), attended only

No provider call is needed for the UI-only portion. Use public synthetic caption
fixtures, no personal glossary. Record candidate SHA/browser and anonymous role
(owner/second operator), task completion, misclicks, elapsed time and confusion
counts, not participant names or caption text. Counterbalance caption action
versus terminology editor order using the same 4 tasks:

1. Find the action for a deliberately misspelled public term, propose a correction.
2. Confirm it, explain whether earlier original ASR/captions should change.
3. Undo, then find/edit the same preference in the editor without a pointer hint.
4. Switch language, identify session/language scope, and export/reset safely.

Observe keyboard-only focus, accessible labels, confirmation, Undo visibility
and error recovery. Do not coach until the first attempt is recorded. Ask which
route is clearer and why; keep judgments separate from automated pass counts.
Pass requires all tasks without unsafe scope misunderstanding, retained original
ASR and usable Undo; record assistance/failure honestly. One owner trial does not
prove second-operator onboarding or VoiceOver. Current result: NOT PERFORMED.

## Meeting readiness, November 17 (KST)

1. By 13:00 gather exact-head CI/review/endurance evidence. Preserve the accepted
   v0.5.0 tree, lock/configuration and local environment, no overwrite upgrade.
2. With separately authorized operator, verify candidate identity, loopback-only
   launch, stopped capture, browser connectivity and graceful Stop. Confirm no
   automatic startup or provider/model change. A no-capture check is not live
   readiness. Never print credentials or device identifiers into artifacts.
3. Obtain explicit attended microphone/output/public-fixture provider authority.
   On the actual meeting Mac/browser, check the intended microphone and output,
   Medium default, actual translation/caption correctness, audible normal-speed
   readback, mute/unlock, Catch up/Replay, Stop/export/reset and cleanup. Record
   only identity/time and content-free pass/fail. Test candidate-specific routing
   or speed only within this authority; pending listening is not acceptance.
4. At 15:00 choose the passing candidate or freshly checked v0.5.0 fallback. If
   neither is currently verified, report BLOCKED, not meeting ready. Keep new
   candidate off the meeting path when mandatory evidence is absent.
5. By 16:00 freeze the accepted setup. No experiments, updates, provider/model
   switches until the 17:00 meeting ends. No autonomous capture/join/upload.
   Use only bounded recovery to the accepted baseline if needed.

Rollback rehearsal (no capture): stop/status, select preserved v0.5.0 clean tree,
restore prior local overrides without displaying secrets, frozen dependency sync
only in the approved setup window, verify identity and loopback health, stop and
confirm no owned process remains. Actual rollback is not claimed until recorded.

## Remaining explicit decisions

Physical Windows, native Safari listening, VoiceOver, second operator, 120-minute
single-session physical Mac soak, same-input listening and provider comparisons
remain open. GLM/Large promotion, new speakers/languages/voices, offline engines,
signed/notarized packaging and automatic startup are later decisions, not stable
support promises. Supported distribution stays Mac repository/CLI plus Chromium,
Python 3.11-3.13. Research: [provider verdicts](provider-research-20261116.md).

Release-complete and all-backlog-acceptance-complete are different states.
Keep #23/#65/#69 open for their unmet acceptance. Do not describe a documented
agent-policy gate as GitHub-enforced without live enforcement evidence.
