# Opt-in native capture candidate (not physically qualified)

The existing helper/noaudio build, launch protocol and hosted suite remain intact.
The separate build_capture.sh builds a real input implementation; it never runs
it. This milestone is source + software-policy tests only. There is no application
Start hook, provider path, output playback, route mutation, auto-admission or
runtime grant installed. Existing UI and model/ASR defaults are unchanged.

## Architecture

- CaptureController retains the existing suspended-spawn disk/live CDHash checks,
  fixed role identities, retained direct-child ownership and readiness protocol.
  Its generated capture pins bind GuardianA, GuardianB and CaptureHelper, not the
  original SyntheticHelper. The original NoAudioController still hard-pins CBNA0001.
- Before any role launch, a native continuous-time challenge is published. Parent
  Custody fsyncs the shared programme debit before supplying one exact inherited
  pipe reply. Capture (CBCA0001), no-input (CBNC0001) and original noaudio (CBNA0001)
  messages are distinct. The native anchor predates IPC/debit; latency consumes the
  <=2-second native ceiling. Existing programme cap/no-refund/HOLD rules remain.
- Only CaptureHelper links the HAL opener. It disables output, selects the exact
  explicit CoreAudio AudioDeviceID before initialization, opens at most once,
  checks controller/guardian/emergency pipe liveness, and discards/zeros native PCM.
  It queries the selected HAL input format rather than assuming ASR mono format,
  bounds rate/channels/frames/scratch storage and never changes hardware rates.
  A PortAudio index is NOT a HAL device ID. No default-device lookup or mutation,
  data retention, network/provider access or automatic alternative-device retry.
- CaptureHelper begins closure 100 ms before the shared continuous deadline. It
  checks callback quiescence, stop, uninitialization and disposal results. Controller
  independently monitors the parent, close-only emergency pipe, guardians and
  hard deadline; it can kill/reap only its retained direct capture child. Any
  unexpected/native-forced termination remains unknown/HOLD, not closure proof.
- There is deliberately no output path to unmute: output remains absent. Binding
  actual output-route changes to B-lane mute-before-invalidate is separate work.

## Fail-closed admission and trust boundary

attended_helper_budget.admit_helper() still refuses missing prerequisites and
old UI-style identity/kernel/readiness booleans. The opt-in adapter only consumes
an opaque one-use permit registered in CaptureAdmission by the independent parent.

The parent must authenticate and pin a review manifest and current explicit owner
runtime grant via an independent reviewed channel. Passing a hash read from the
same untrusted document is NOT authentication. No trust pin, qualifying proof or
runtime grant is supplied in source. Unit-test fixture bytes are not acceptance.
The fixed review names every binary SHA256 and exact proof bytes for signature /
entitlements, full kernel network denial, single stream, deadline/controller /
guardian / suspend closure, emergency stop, mute-before-route, and native cleanup.
Proof documents bind the exact candidate and image set; noinput/fixture receipts
cannot substitute. A current short-lived grant additionally binds programme,
ledger tail, exact HAL input, <=2-second allowance, ready/private/meeting-ended
conditions, and a parent/session-bound runtime kernel-egress-denial observation.
The grant and permit cannot be replayed within their authority instance.

Python hash checks detect drift but do not create an OS inode/exec lock. Native
roles additionally verify strict code identity on suspended disk/live images.
The parent/controller themselves and the browser/backend must be in the reviewed
kernel-denied runtime boundary; env={} and absence of socket code are NOT kernel
network-denial evidence. This source does not change machine firewall/TCC/defaults.
All results keep native_admission=false/physical_acceptance=false and ledger HOLD;
independent authenticated closure observation remains required to finish a debit.

## Later hosted no-input build/qualification (never physical)

From repository root, on an approved macOS CI host:

    sh native/caption_helper/build_capture.sh NEW_PRIVATE_OUTPUT
    python3 -m native.caption_helper.qualify_capture_noinput NEW_PRIVATE_OUTPUT/CaptionHelper.app/Contents/MacOS

This harness has no device, grant or attended-ledger argument. It creates its own
private disposable software ledger, uses only --capture-noinput-budget and emits
a content-free result. The role exercises custody/guardian/liveness/deadline and
terminal ownership paths but calls neither opener nor closer. Linked frameworks
are not proof of physical access. Independent hosted inspection must establish
that no device/TCC/audio side effect occurred. This phase has not run these steps.

## Integration/remaining gates

1. Independent source review and macOS compile/signature/no-input qualification of
   the exact integration candidate. Builder opt-in only; do not replace existing
   CI acceptance or infer a pass from Python/source-pattern tests.
2. Separately authorized physical qualification under reviewed complete kernel
   egress denial, exact signed images, explicit HAL device and fresh runtime grant.
   Confirm actual deadline/stop/closure, controller/guardian deaths, suspend/hang
   combinations, no other input, and no audio/output/provider leak. In particular,
   controller plus helper scheduling/OS-device cleanup must be demonstrated, not
   assumed from cooperative polling or owned SIGKILL/reap. No claim this source
   alone establishes every independent-custodian closure guarantee.
3. Parent retains one locked Journal across devices/retries, authenticates evidence
   and owner grant pins, owns an EmergencyStop outside UI/backend workers, and
   invokes launch_capture only after source/runtime qualification. Never auto-call
   from app startup/Start. Closure acceptance is external, never child JSON.
4. This deliberately discard-only input is not a transcription pipeline adapter.
   A production PCM transport and app/main capture-factory hook require a separately
   reviewed bounded framing/backpressure/generation/closure handoff; do not route
   sounddevice around the native gate or claim native runtime acceptance meanwhile.
