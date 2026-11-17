# Fixed macOS profile: source preflight, native launcher blocked

2026-11-17. scripts/attended_macos_profile.py implements exact role/hash and
entitlement allowlists, an executable single-input lifetime protocol model and
unconditional native-launch refusal. Seven new tests exercise those contracts.
It does NOT implement CoreAudio capture or OS process guardians. No Mac/device
inspection or native run occurred. Matching supplied hashes bind bytes only, not
signed executable authenticity, candidate provenance or conformance approval.

## First-party policy evidence, retrieved this batch

- Apple current microphone entitlement JSON:
  https://developer.apple.com/tutorials/data/documentation/bundleresources/entitlements/com.apple.security.device.microphone.json
  HTTP200, describes App Sandbox > Hardware > Audio Input and the microphone key.
- Apple archived entitlement guide:
  https://developer.apple.com/library/archive/documentation/Miscellaneous/Reference/EntitlementKeyReference/Chapters/EnablingAppSandbox.html
  HTTP200. Entitlements are incorporated into the target code signature; without
  app-sandbox enabled the other sandbox keys are meaningless. Keys default false;
  network.client/server grant network capabilities. This is not a guarantee that
  unsigned plist source affects a Python process.
- Apple DTS thread https://developer.apple.com/forums/thread/661939 surfaced in
  search as discouraging custom sandbox-exec profiles/undocumented profile language.
  Direct fetch returned human verification, so full text was NOT verified here.
  No guessed Seatbelt syntax or sandbox-exec invocation was implemented.

The fixed source entitlement allowlist is app-sandbox=true, device.microphone=true,
no network.client/server, inheritance, exceptions or ambient entitlements. These
are a proposed capture target's entitlements, NOT an accepted signed artifact.
Guardians must have separate least-privilege signing profiles; do not blindly grant
microphone access to every role. Runtime signature inspection and kernel egress
conformance are unresolved. No signing identity/credential has been used or requested.

## Reuse finding

Inspected retained handsfree-0938/attended_guard.py and run_attended.py from the
prior acceptance packet. That helper permits narrowly budgeted paid Mistral calls,
requires an exact BlackHole virtual input, rejects physical microphones, and uses
Python SDK/transport wrappers. It is not provider-denied physical capture, not an
OS firewall, and contains no independent native lifetime guarantee. Copying it into
this $0 physical runner would violate scope rather than accelerate qualification.
Reuse the conservative reservation principle and exact input identity checks, not
its provider constructors, key-bearing environment or virtual acceptance claims.

## Precise next code prerequisite

A supported kernel-restricted native launcher needs a built, signed App Sandbox
helper target with verified entitlements and a reviewed fixed CoreAudio backend
(B's ephemeral capture seam), plus a fixed process-lifetime implementation. No such
artifact, target/signing arrangement or verified launch contract exists in the
inspected lane. Creating a plist or marking a Python subprocess 'sandboxed' cannot
supply it. Current scope excludes new signing credentials/system changes and this
batch forbids Mac inspection/build/run, so an operational OS launcher cannot be
validated or safely enabled here. Native launch remains an unconditional exception,
not a user-controlled readiness boolean or accepted self-issued attestation.

Next source work can implement the fixed native helper once parent selects an
existing authorized supported build/signing target and B's actual backend contract.
Do not silently change this into a new packaging/signing project or install tools.
A custom sandbox-exec alternative requires explicitly reviewed authoritative target
policy evidence, not guessed private syntax. No assertion that ad-hoc signing is
impossible: its supported applicability/identity requirements remain unverified.

## Lifetime contract and real limitations

LifetimeModel emits open_single_input once; a second open fails terminally. Deadline,
backward/invalid clock, Stop, controller EOF, either guardian EOF and backend error
emit mute -> close_input -> verify_closed, never revive. Route change emits mute
before invalidation; there is deliberately no unmute operation (B owns output and
participant-ready route verification). This is a tested state machine, not actual
physical closure or independent scheduling.

For real dual guardians, both must be armed before input opens, observe controller
and each other's private inherited pipe EOF, have independent absolute deadlines,
and hold immutable owned-process identity. Neither may inherit the other's liveness
writer. Capture must observe both guardian lifetimes too. Avoid arbitrary PID/group
kill. Simultaneous guardian death plus hung capture is NOT solved merely by this
arrangement; native kernel/resource lifetime proof or an explicitly bounded verified
backend stop path is still required. Never advertise an impossible userspace hard
real-time guarantee under kernel stalls/power failure. Prior offline supervisor's
SIGKILL survival limitation remains unchanged, not waived by a protocol model.

## Native qualification still missing

Exact built/signed candidate and helper identities; effective sandbox entitlements;
TCP/UDP/DNS/child transport denial under actual kernel sandbox; one selected native
input; watchdog deadline including open/close overhead; Stop/controller/each guardian
and combined-failure cases; physical stream closure and no raw retained PCM; muted
route changes and owned cleanup. Must fit ALL attempts under the same coordinator
journal's remaining 600000-ms cap, no refund or new ledger. Meeting end/readiness
still required. Linux fake/source tests establish none of these physical outcomes.
