# Parent launch-budget seam, source milestone

Lane C, 2026-11-17. This is not operational capture qualification.

## Implemented

Custody.prepare_launch consumes the existing inherited-channel-bound, authenticated,
one-use allowance, durably debits Journal, then returns an in-memory immutable
LaunchReservation. Its deadline begins before reserve/fsync, so slow storage cannot
extend the requested allowance. launch_remaining_ns rechecks parent process,
channel identity, original envelope object, active sequence, journal availability,
poison state and bounded remaining time. Copies/JSON are not capabilities.
Expired or regressed clocks retire the local envelope. Revoke closes owned parent
transport and forgets envelopes without closing/refunding the reservation.
A restart sees the outstanding debit and cannot instantiate fresh Custody.
Journal still serializes all devices against the cumulative 600000 ms ceiling.

This supplies the missing debit-to-deadline seam, not a production native launcher.
No caller is wired to actual native execution. Both existing admission entry points
still unconditionally refuse, and PR95 signed roles, suspended spawn, identity pins,
READY acknowledgments and resource ownership code are unchanged. The envelope's
native_admission field is false and must never be used as an authorization check.

## Tests and evidence

Stdlib-only Linux source tests, no credentials, provider calls, devices or native
execution:

- python3 -m unittest discover -s tests -p 'test_caption_helper_launch_budget.py' -v
- python3 -m unittest discover -s tests -p 'test_caption_native*.py' -v
- git diff --check

10 new deterministic tests cover durable debit, false admission, cloned-envelope
rejection, expiry, slow fsync deadline consumption, competing session exclusion,
revoke/restart hold, wrong process, clock regression and closed journal/replay.
11 existing native-source checks pass. An exploratory broader test_caption_*.py
run passed 25 tests but failed importing unrelated unit.test_caption_terminology
because pytest is absent. No dependencies were installed; this is not full CI.

## Exact remaining critical path

1. Independently review and qualify the current signed no-audio assembly on hosted
   macOS. Its controller-death test proves aggregate parent-or-deadline closure,
   not uniquely the parent-monitor mechanism. Do not upgrade that attribution.
2. Implement a fixed signed operational capture role and production launcher with
   native continuous-time budget custody, one input only, network deny and explicit
   owned stop/drain/dispose verification. Convert only the remaining budget interval
   to the earlier native continuous deadline; Python monotonic is not suspend-safe
   device closure proof. This seam has no independent suspend enforcement.
3. Bind the actual qualified native identity/session/custody and terminal verifier
   to debit and closure. Journal.finish is not a public native-proof verifier.
   Helper exit, source state, receipts or booleans must never release unknown state.
4. Exercise resource closure, failure/restart and mute-before-route against the real
   candidate under independent hosted/native evidence. No actual microphone stream
   may open until trustworthy native/custody evidence and all attendance/network/
   cumulative-budget/emergency-stop gates pass. Meeting end remains unconfirmed.

K2/C5/H0 operational criteria remain open. The accepted device and release are
unchanged. Incremental provider spend and physical capture duration: zero.
