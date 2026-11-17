# Attended acceptance preparation, 2026-11-17

Status: OFFLINE PREPARATION ONLY. No hardware, browser, microphone, native Safari,
Windows device, VoiceOver or participant test performed. Meeting setup stays frozen.
This packet does not supersede historical receipts or close #23/#69/#80.

## Admission and ownership

Coordinator owns one append-only programme ledger across ALL devices, calibration,
failures and retries. Total physical input allowance is 600,000 ms, not per run.
Before each attempt reserve its whole maximum duration durably; never refund unused
reservation in this conservative protocol. Unclosed attempts block further capture.
Record actual elapsed duration even on error; overrun is a failed watchdog gate.
A lost ledger or unknown stream closure is a stop, not a fresh allowance.
No concurrent operators or device leases. No ordinary provider-enabled Start.

Run the pure checker with:

    python3 -m scripts.attended_acceptance packet.json
    python3 -m unittest discover -s tests/unit -p test_attended_acceptance.py -v

It checks schema, readiness flags, proof references and reservation arithmetic ONLY.
It does not verify referenced proof bytes, ledger completeness, truth of flags,
atomic persistence, clock deadlines or physical shutdown. Even a valid plan returns
capture_authorized=false and hardware_verified=false. Coordinator must independently
verify proof hashes and exact candidate, ledger continuity and current readiness.
Do not wire this checker to capture admission until those runtime controls exist.

Packet fields (no others): schema=caption-attended-v1, candidate_sha (40 lowercase
hex), meeting_ended/participant_ready/private_quiet (true), requested_ms (positive
integer), ledger (ordered rows), proofs. Each ledger row has sequence (1-based),
reserved_ms, elapsed_ms (nonnegative integer), closed (true only after verified
closure). Proofs must contain network_deny, hard_watchdog, emergency_stop,
single_capture, output_fail_closed, owned_cleanup, each with candidate_sha and
sha256 of a retained reviewed receipt. Hash syntax is NOT authenticity proof.
No names, transcripts, device labels, raw audio or arbitrary comments in packets.

## Runtime safety gates still OPEN (C5)

Before any physical attempt, independent reviewer must witness:

1. Provider-free runner denies SDK calls AND outbound network before importing app;
   no dotenv or credential reuse. Existing scripts/software_network_guard.py and
   windows_v050_fixture_app.py are software reuse seams, NOT an OS/browser firewall.
   Browser WebSocket/fetch and alternate native transports require separate deny
   verification. Do not use its fake sounddevice module as physical proof.
2. A separate hard watchdog owns the actual native capture lifetime, armed before
   stream opening. A hung UI/event loop, opening failure, exception, operator Stop
   and controller death must close the stream by the reserved deadline. An asyncio
   timeout, timer in the captured process or this arithmetic checker is insufficient.
3. Exactly one application/native input; browser getUserMedia never opens a second
   capture. Acoustic instrumentation also counts toward the global allowance.
4. Emergency Stop works independently of UI; owned process handles and native stream
   closure are verified, not inferred from a quiet meter. No broad process kill.
5. Route switching stays muted until explicit verified output success and participant
   readiness. Unsupported/denied/default-changed output cannot silently play speakers.
6. Cleanup receipts cover native streams, owned browser/profile/controller, listeners,
   provider request count=0, raw recording retention=0 and durable ledger closure.

These are implementation/integration and review gates, not a claim of a delivered
physical runner. Do not schedule an attended slot on this packet alone.

## #80 route cases (C1)

Use local public fixture/tones, no owner speech. Record candidate, OS/browser version,
case ID, outcome pass/fail/unsupported/not_run, elapsed capture ms and proof hash.
Use aliases input-A/headphones-A only, no identifying hardware labels.

| Case | Action after safety admission | Required observation |
| --- | --- | --- |
| R1 | Select intended physical input, then one bounded stream | Actual intended source and one stream; selection alone is not proof |
| R2 | While muted select explicit supported headphones | Verified sink success, then attended unmute; human hears intended output |
| R3 | Deny input permission using participant-controlled prompt | Truthful denial, no active stream or provider work |
| R4 | Deny explicit sink permission | Remain muted, truthful error, no default speaker fallback |
| R5 | Unsupported sink API | Truthful unsupported state; default output requires separate readiness |
| R6 | Mute, remove selected output | Remain muted, invalidate selection; no silent default reroute |
| R7 | Mute, remove selected input | Truthful capture failure, closure, no duplicate/restarted stream |
| R8 | Stop/error/refresh | Old stream closed; fresh readiness before any restart; cleanup receipt |

If app does not fail closed, stop and send a minimal reproduction to lane B, sole
shared-app owner. This lane does not patch app/static or duplicate its player.
Do not exercise surprise unplug/default switching while audio is unmuted.

## #69 human terminology comparison (C2)

Reuse docs/candidate-validation-20261116.md's four-task protocol and existing
browser_tests/test_caption_terminology.py plus test_glossary.py fixtures. Do not
build a competing editor or call production providers. The fixture runner must
be proven provider/native-denied before interactive use; no browser run here.

Public fixture pairs, identical in both routes:
통계적 유의성 => statistical significance; 신뢰 구간 => confidence interval.
Use synthetic original caption containing both terms. Reset fixture and glossary
between routes, preserve original caption and source/effective provenance.
Odd anonymous participant index: caption action then pre-session editor; even:
reverse order. Same task wording and fixture in both routes; explain only the goal:

1. Add preferred rendering for statistical significance and confirm it.
2. Change it to significance, inspect the saved list, then undo that change.
3. Remove confidence interval, then restore it using available controls.
4. Check future-only scope, original caption preservation, language change and refresh.

Record route/order/task ID, completed yes/no, elapsed ms, error count, assistance
count, confusion category (discovery/confirmation/scope/undo/none), and participant
preference caption/editor/tie/undecided. Missing preference remains missing, not an
AI inference. Facilitator intervention is assistance, never silently a clean pass.
Human result pending; automated fixture assertions are not a usability verdict.

## #23 VoiceOver and onboarding (C4)

VoiceOver on actual macOS/native Safari: keyboard-only reach input/output selectors,
Start/Stop, caption correction, settings, edit/save/cancel/undo and export. Check
accessible names/state announcements, logical focus order, dialog focus containment,
Escape/close focus return, error announcement and no unexpected focus theft during
captions. Use synthetic fixtures with capture denied unless separately admitted.
Record each task pass/fail/not_run, assistance and sanitized defect ID. Linux WebKit
is not native Safari, and DOM accessibility tests are not a VoiceOver judgment.

Second owner-approved operator receives only repository user docs and a clean
project-local candidate. Ask to identify readiness, choose input/output, start/stop
using the approved OFFLINE fixture path, locate recovery/export and explain whether
anything is still recording. No coaching until the attempt ends; log assistance.
Do not instruct ordinary live Start. Synthetic fixture onboarding covers software
only; actual input/output onboarding remains separate under admission gates.
No names or recruitment, no screen/audio recordings; retain aggregate task outcomes.

## Windows and browser preflight (C3)

No available node/device or browser version has been established in this lane.
Coordinator records actual existing authorized host, OS/build, browser/version,
Python/SDK and exact clean candidate SHA later. Use a disposable directory within
the owned project area and already available runtimes. No administrator/system
packages, drivers, global routes, installs outside project or machine acquisition.

Reuse scripts/windows_v050_software_acceptance.ps1 with exact ExpectedSha and
existing PythonPath/ChromiumPath (see docs/windows-0.5.0-offline-and-physical-plan.md).
It is a software-only fixture: native calls denied, no Start and owned teardown.
Its pass does not establish Windows microphone/output or ordinary controller support.
The existing POSIX controller remains a documented Windows limitation. Before a
physical slot, review an owned manual lifecycle or separately repair that limitation;
never bypass process identity or use a broad kill. Native Chromium/Safari results
must identify actual native browser; no simulated/fake-media result substitutes.

## Remaining disposition

- C1 route cases prepared; actual route/denial/removal and runtime fail-closed proof open.
- C2 existing tasks reused with fixed fixture/order/receipt fields; human comparison open.
- C3 reuse path and isolated Windows preflight specified; device availability/native run open.
- C4 task sheets prepared; actual VoiceOver and uncoached participant verdict open.
- C5 offline arithmetic validator tested; hard watchdog/physical runner, complete network
  denial, output fail-closed integration and independent cleanup review open.
- #23 remains open. This local milestone is not READY_FOR_ATTENDED_CHECK.
