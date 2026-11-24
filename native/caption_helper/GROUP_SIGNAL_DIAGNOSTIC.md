# Hosted Darwin owned-group signal diagnostic

This is diagnostic source, not a CaptureController repair or native admission.
The production group kill, fail-closed HOLD, budget, validators, noaudio protocol,
and success schema 1 are unchanged. No devices, capture API, provider or network
calls occur in the probe. Do not run it on the owner's Mac.

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
This is source-backed, not yet execution proof for the hosted kernel. The
published source commit is not attested to be the source of build 25G332.
EPERM still cannot generally be accepted as closed: a live unauthorized or
MAC-denied descendant can also leave nfound==0. Never just whitelist EPERM,
reap the anchor before group closure, skip group kill, or loosen the validator.

## Exact next hosted invocation

After building the candidate and BEFORE the failing capture noinput qualifier,
run this as a separate bounded diagnostic step (CI wiring belongs to the parent):


```sh
oh_out="$RUNNER_TEMP/native-group-signal-observation"
sh native/caption_helper/probe_group_signal.sh "$oh_out" \
  "$CAPTURE_BUILD/CaptionHelper.app/Contents/MacOS"


```

Set CAPTURE_BUILD to the existing build_capture.sh output. The second argument
is optional only when candidate signing evidence is being retained separately.
Use a fresh output directory. A hosted step timeout of one minute is ample;
normal observation is immediate and each of three cases has a 3-second active
budget plus a common 2-second cleanup budget. No production deadline is changed.
Upload that entire directory with the CI lane's existing failure-safe artifact
step, including build/sign stderr and runtime.txt even when this invocation fails.
Do not make successful observation into a native qualification/merge acceptance.

The wrapper compiles with -std=c11 -Wall -Wextra -Werror -Os, signs the probe
with hardened runtime and no entitlements, verifies it, and retains actual kernel,
OS, uid/gid, compiler, code signature, entitlements and source/binary SHA-256.
When given the candidate directory it only reads/verifies existing candidate
images, records their signatures/entitlements/hashes and never executes them.

## Probe safety and interpretation

probe_group_signal.c uses real fork/setpgid/waitid(WNOWAIT)/kill/sysctl/waitpid.
Three fresh, direct owned children are observed in each of these cases:

1. All alive, group SIGKILL positive control.
2. Leader a retained normal-exit-72 zombie, two live peers. This separates dead
   anchor from no live recipient, and keeps real live-peer group closure in view.
3. All three retained normal-exit-72 zombies, the exact relevant state pattern.

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

If the hosted kernel reproduces EPERM only for the all-zombie group with working
live/mixed controls, this confirms that mechanism on that kernel, not automatic
production closure. Next repair must retain the actual group signal and anchor,
prove bounded complete absence of live unknown descendants with stable identity,
and keep all ambiguous/denied census outcomes fail-closed. A production census
cannot assume the probe's closed-world/private-session topology. It must handle
real descendant races and ownership explicitly, with hosted noinput readback.
If the positive controls fail or all-zombie behavior differs, inspect actual
signature/entitlements and same-run sandbox/kernel logs before any policy change.
