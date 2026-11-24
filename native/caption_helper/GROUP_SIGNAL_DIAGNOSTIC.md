# Hosted Darwin owned-group signal diagnostic

The probe is diagnostic, never native admission. The narrow production repair
now shares its closure predicate; see
[Native zombie-group closure](../../docs/native-zombie-group-closure.md).
Native budgets, status validators, noaudio protocol and success schema 1 remain
unchanged. No devices, capture API, provider or network calls occur in the probe.
Do not run it on the owner's Mac.

Current follow-through: [Suspended-spawn custody enrollment](../../docs/native-group-custody-enrollment.md).
The actual 20d run passed the five fork/live predicate evaluations but production
failed an ambiguous first-child enrollment guard. The revised probe replaces
fork-only members with its exact signed self-image via production-style suspended
posix_spawn, live/disk verification and pinning before SIGCONT. This is source work
pending new hosted execution; old fork observations are not relabeled as exec proof.

The actual e9aa766 hosted run 45456295172 on Darwin 25.6.0/build 25G332
subsequently demonstrated both successful live/mixed signals and all-zombie EPERM
with normal reaping and zero forced cleanup. That is actual historical mechanism
evidence, not proof of the new production predicate or adverse fourth-child path.
The older first-failure evidence below is retained as history, not backfilled.

## Actual retained failure

The macOS job 138619271909 of CI run 45443071656 checked out
7f5dc32965d6465393cb77f3dd4ee6d4032f6943, tree-identical to frozen
f949547542ae5e30e5aeed0506d82a75439eed9c. The runner reports macOS 26.7.2,
build 25G332, macos-26-arm64 image 20261117.0516.1. The retained diagnostic has
GROUP_SIGNAL, role 1, EPERM, elapsed 1904870166 ns, window 1999193541 ns,
wait statuses [18432,18432,18432] (normal exit 72), cleanup_killed [0,0,0],
cleanup_errors 4, terminal HOLD. ALL_OBSERVED precedes CLEANUP. These facts
identify the failing syscall branch, not its underlying authorization cause.
Historical e4be has insufficient corresponding native evidence here.

The build recipe signs CaptureController and CaptureGuardianA/B with hardened
runtime and no explicit entitlements. CaptureHelper has app-sandbox and audio
input entitlements. Outer app signing does not alone prove the controller's
runtime sandbox status. Retained build logs/pins are not runtime credentials,
effective entitlements or a kernel sandbox-denial trace. Do not infer permission
denial, its absence, or a working historical Darwin outcome from them.

## Primary-source causal mechanism

Apple XNU source pinned to f6217f891ac0bb64f3d375211650a4c1ff8ca1ea:

- [kill wrapper](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/libsyscall/wrappers/kill.c#L39-L47)
  passes posix=1 for __DARWIN_UNIX03.
- [kill syscall](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_sig.c#L1380-L1422)
  dispatches negative PID to killpg1.
- [killpg1](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_sig.c#L1675-L1722)
  finds the pgrp, explicitly filters SZOMB out of pgrp_iterate, and returns
  EPERM when nfound==0 and posix is true. Missing pgrp instead returns ESRCH.
  The callback's earlier zombie-success comment applies to a callback path
  which this group filter excludes, not proof that group-zombie kill succeeds.
- [pgrp_iterate](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_proc.c#L4272-L4355)
  applies the filter to members, then proc_find obtains live proc references.
- [reap_child_locked](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_exit.c#L2819-L2834)
  removes group membership while reaping. WNOWAIT does not reap the anchor.
- [KERN_PROC_PGRP census](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_sysctl.c#L881-L943)
  includes PROC_ALLPROCLIST | PROC_ZOMBPROCLIST and returns ENOMEM rather than
  silently accepting a short output buffer.

Thus the retained outcome is specifically consistent with POSIX Darwin's
existing-group/no-eligible-live-recipient path, even with identical credentials.
The later e9aa766 real hosted probe demonstrates this mechanism for its owned
closed topology. The published source commit is still not attested to be the
source of build 25G332, nor does the old probe prove new production closure.
EPERM still cannot generally be accepted as closed: a live unauthorized or
MAC-denied descendant can also leave nfound==0. Never just whitelist EPERM,
reap the anchor before group closure, skip group kill, or loosen the validator.

## Exact next hosted invocation

After building the candidate and BEFORE the failing capture noinput qualifier,
run this as a separate bounded diagnostic step (CI wiring belongs to the parent):


```sh
umask 077
oh_out="$RUNNER_TEMP/native-group-signal-observation"
sh native/caption_helper/probe_group_signal.sh "$oh_out" \
  "$CAPTURE_BUILD/CaptionHelper.app/Contents/MacOS" \
  > "$RUNNER_TEMP/native-group-signal-probe-private.stdout" \
  2> "$RUNNER_TEMP/native-group-signal-probe-private.stderr"


```

Set CAPTURE_BUILD to the existing build_capture.sh output. The second argument
is optional only when candidate signing evidence is being retained separately.
Use a fresh output directory. A hosted step timeout of one minute is ample;
normal observation is immediate and each of three cases has a 3-second active
budget plus a common 2-second cleanup budget. No production deadline is changed.
Keep the entire raw output directory, stdout and stderr private, including
build/sign logs and runtime.txt. Never upload or print those raw files, even on
failure: they contain identity, kernel, signature and absolute-path metadata.
Publish only the bounded, validated content-free receipt produced and read back
by scripts/ci_group_signal_observer.py through the explicit single-file CI
artifact allowlist. Missing or invalid observations remain unknown, not success.
See docs/group-signal-safe-retention.md for the public receipt contract.
Do not make successful observation into a native qualification/merge acceptance.

The wrapper compiles with -std=c11 -Wall -Wextra -Werror -Os, signs the probe
with hardened runtime and no entitlements, verifies it, and retains actual kernel,
OS, uid/gid, compiler, code signature, entitlements and source/binary SHA-256.
When given the candidate directory it only reads/verifies existing candidate
images, records their signatures/entitlements/hashes and never executes them.

## Probe safety and interpretation

probe_group_signal.c now uses real suspended posix_spawn/self-exec, pre-SIGCONT
verified pinning, waitid(WNOWAIT)/kill/sysctl/waitpid
and the SAME owned_group_closure.h predicate as production, including libproc
complete PID enumeration and enrolled birth/ownership checks.
Three fresh, direct owned children are observed in each of these cases:

1. All alive, group SIGKILL positive control.
2. Leader a retained normal-exit-72 zombie, two live peers. This separates dead
   anchor from no live recipient, and keeps real live-peer group closure in view.
3. All three retained normal-exit-72 zombies, the exact relevant state pattern.
   The predicate must close exactly those three. Then a genuinely owned fourth
   child is added but omitted from the expected identity set: both its live and
   retained-zombie states must reject closure. Only after its independent reap
   may the original three-member proof succeed again. No group signal is made
   while that extra child is present; the original common budgets are unchanged.

Diagnostic schema 2 adds nullable all_owned_zombies and a fixed adverse object
with rejection booleans and bounded snapshot-byte/status/cleanup values. Actual
shared enumeration readback must be 12 bytes for three zombies and 16 bytes for
both extra-member rejections, so generic census error is not adverse-path proof. These are actual
software/OS observations, never predicted errno or a production admission packet.
Capture success schema 1 is unchanged. Missing new observations are not filled in
from the old three-case receipt.

A new private session excludes existing runner processes from joining a probe
group. Children never fork or exec and exit naturally when their lifeline closes.
A complete bounded KERN_PROC_PGRP census must contain exactly the three owned,
unreaped direct children with matching parent, group and credentials before BOTH
group syscalls. Overflow, unknown membership or custody loss forbids the signal.
Cleanup signals only still-owned direct children after fresh WNOWAIT observation,
then boundedly reaps them. Any forced cleanup makes mechanism_complete false and
exit nonzero. No signal targets a reaped/recycled PID or an unknown member.

observations.jsonl records actual return values and errno numerically; Darwin
EPERM is 1, ESRCH is 3. No expected zombie result is fabricated or used to change
production acceptance. An exit-zero diagnostic means the real observations and
owned cleanup completed, NOT that capture worked; native_admission is always
false. Both positive controls must deliver real SIGKILL and all statuses must be
independently reaped. The zombie case permits any syscall observation to be
recorded, so inspect it rather than interpreting diagnostic exit 0 as a fix.

Limitation: forked unsandboxed children share the probe's signature. This isolates
kernel group/zombie behavior, not CaptureHelper's exec/sandbox topology, the
actual controller's effective sandbox context, or the historical e4be failure.
The optional retained candidate metadata helps correlate, not erase that limit.
No Darwin execution/compilation has been performed in the Linux authoring session.
No synthetic tests, stubs, mocks, Linux stand-ins, devices or owner-node operations
supply acceptance for this change.

## Guarded follow-through

The real e9aa766 probe completed the initial three-case mechanism check. The
new strict proof and real extra-member adverse paths are source work pending
independent parent review/publication and exact-new-head hosted execution. Require
actual header/source/image/generated-pin bindings, real predicate rejection for
live/mixed/extra-member states, and successful unchanged noinput readback with
normal owned reaping and no forced cleanup. Keep all unknown/denied/truncated
census states fail-closed. The production proof does not assume this diagnostic
private session, and old evidence is not acceptance of this new implementation.
