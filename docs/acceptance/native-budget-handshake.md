# Native noaudio budget handshake, source slice after d4b1193

Status: source implementation and offline tests only. No native executable was
compiled or run in this lane. No microphone entitlement, opener, output or native
admission was added. K2/C5/H0 operational capture acceptance remains OPEN.

## Complete implemented path

1. qualify_budget.qualify starts only fixed NoAudioController --noaudio-budget
   with a private stdin pipe, bounded stdout reader, empty environment and all
   unrelated descriptors closed. This explicit callable is a qualification harness,
   not an automatic startup path or operational launcher. It has no CLI/import side
   effects. Caller must first review/qualify its exact controller image.
2. Before any role, lifeline or synthetic input is created, controller validates
   inherited FD0 is a read-only pipe, sets nonblocking/CLOEXEC and samples
   mach_continuous_time. It publishes a fresh 256-bit native challenge.
3. Parent consumes the existing one-use custody-bound receipt and fsyncs the
   cumulative Journal debit before writing the fixed 56-byte reply. It closes the
   sole writer immediately. A short write is terminal failure, no new-controller
   retry. Invalid challenge schemas cannot debit. Oversized allowances fail with
   an already-debited HOLD, not an accidental refund.
4. Native accepts only exact magic, matching challenge, positive sequence, duration
   in 1..2000000000 ns, exact framing and EOF. Truncation, trailing data, wrong or
   old challenge, nonpipe stdin, missing EOF and expiration fail before role spawn.
   Tick conversion floors, checks overflow and anchors to the time BEFORE challenge
   publication. It never adds the allowance to receive time. Storage delay, IPC,
   controller suspension and sleep consume rather than extend this deadline.
5. The SAME absolute continuous deadline is passed through the existing private
   role capabilities to both guardians and synthetic helper. Existing suspended
   spawn, fixed disk/live image pins, immediate owned PID recording, role/PID READY
   ACK, >=500ms startup margin, sole-writer custody and checked cleanup are reused.
   Very short allowances may necessarily fail that startup margin and remain HOLD.
6. Driver reuses existing strict startup/schema6 terminal parsing, requires matching
   role PIDs, natural expected per-role wait statuses, no cleanup kills and direct
   controller return code 0. It bounds partial stdout, total output, EOF and waiting.
   It reaps only its direct controller and closes owned streams/session on failure.
   No reported/recycled role PID is signalled by the Python driver.

## What this does NOT prove

Native challenge correlation is not OS peer identity or a trust root. Parent
socket custody still identifies its local allowance transport, not the native
stdin reader's code. The controller's reported child reap statuses are qualification
consistency observations, NOT independent physical input closure proof. The driver
NEVER calls Journal.finish, even on success. Every completed/failed attempt retains
its full debit and active HOLD. Restart cannot instantiate fresh custody over it.
A later qualified terminal verifier remains necessary; do not clear the hold from
JSON, a helper exit, a hash or a test fixture.

Native continuous-time arithmetic is implemented here but not runtime-qualified.
A SIGSTOPed role cannot physically dispose a resource until scheduled again. The
existing parent-death evidence still proves aggregate parent-or-deadline closure,
not unique parent-monitor attribution. None of these limits is waived.

## Verification performed

- 17 new stdlib tests: exact wire/debit ordering, schema rejection, storage failure,
  HOLD retention, fixed launcher pipes, mocked startup/write/wait failures, bounded
  fragmented/coalesced reader, EOF/stall/output cap, source deadline propagation,
  fixed framing and strict terminal consistency.
- Existing helper budget and native source tests rerun separately.
- git diff --check and Python source compilation checks.

All subprocess/native actions are mocked in the new driver tests. Native-source
string invariants are not native behavior evidence. No device, provider call,
credentials, installs, network inference or GitHub action occurred.

## Next narrow runtime and engineering gates

Parent owns independent review and hosted macOS noaudio qualification. Build NEW
signed images with the existing builder; test valid handshake, fresh/wrong/replayed
challenge, partial/trailing wire, writer death/missing EOF, nonpipe descriptor,
late response and native suspension across budget expiry. Keep exact image/source
identity and existing old noaudio regression matrix. Do not reuse prior receipts
for this changed controller. Source tests here cannot establish those runtime facts.

Then implement the fixed operational capture role and independent native budget/
closure custody, preserving mute-before-route, one-input stop/drain/dispose and
permanent unknown-terminal HOLD. An authenticated production launcher and genuine
independent resource closure evidence are still missing. They are separate from
this now implemented noaudio debit-to-native-deadline path. Actual capture remains
unconditionally disabled until those gates, review and human/device safety pass.
