# Wait events, suspended-child custody and bounded cleanup

Frozen public source base: 6c45804889e1ba2d03c7e59151e679845eee8102.
The actual next hosted run remained HOLD: controller 70 / CLI 1, PIN_TERMINAL
role 1, recorded errno_class OTHER, at 4,066,458 ns of 1,999,124,625 ns. Old code
establishes waitid returned 0 and si_pid was nonzero, NOT the code/status/signo.
The zero system_errno output was misclassified as OTHER by a missing zero case.
Existing receipts are not rewritten to NONE or assigned a guessed event code.

The signed-self probe separately returned 70 with ONE partial row: pids
2193/0/0, no complete census, unknown all-zombie/adverse evaluations, no successful
signal attempts, reaps -1/-1/-1, force 0/0/0, and remaining-held 1/0/0. Its private
pin stderr was not retained. Neither its failure branch nor SSTOP/event readback
can be inferred from the production reason. This is NOT five-case/normal-cleanup
proof, and no runner-cleanup assumption repairs it.

## Primary source resolves the apparent option contradiction

Qualified primary source: Apple XNU 12377.1.9, commit
f6217f891ac0bb64f3d375211650a4c1ff8ca1ea:

1. bsd/sys/cdefs.h:805-808 defaults __DARWIN_UNIX03 to 0 for KERNEL.
2. bsd/sys/wait.h:166-173 defines WEXITED=4, WNOWAIT=32, and defines the waitid
   WSTOPPED=8 only for UNIX03. At 239-243 the non-UNIX03 definition is the old
   wait-status sentinel _WSTOPPED=0177 (127).
3. kern_exit.c:3275 tests options & WSTOPPED. With those kernel defaults, the
   caller's WEXITED|WNOHANG|WNOWAIT value 37 overlaps 0177 even WITHOUT bit 8.
   Reading only the branch text while assuming the user-space UNIX03 WSTOPPED
   value therefore gives the wrong conclusion about the kernel's stop path.
4. kern_fork.c:935 allocates a fresh zeroed proc; p_xstat is its stop/exit field.
   kern_exec.c:2220-2233 sets SSTOP for START_SUSPENDED without delivering a stop
   signal or setting p_xstat. kern_exit.c:3290-3300 emits CLD_STOPPED and raw
   p_xstat. Thus a genuine fresh suspended stop can carry status 0, not SIGSTOP.
5. kern_exit.c:371-415 explicitly copies signo/code/pid/status into zeroed LP64
   siginfo, while its no-event WNOHANG path at 3364-3385 leaves user storage
   untouched. The existing caller already zeroes that storage.

The primary kernel macro expansion provides a causal source-level mechanism
consistent with the observed nonzero PID, rather than an invented Libc ABI
conversion. It does NOT reveal the unrecorded old event or attest the exact
hosted kernel: actual runtime is macOS 26.7.2, build 25G332, Darwin 25.8.0 arm64.
No kernel build override or shipped binary implementation was directly inspected.

The Apple-published XNU 7195.121.3 syscall generator/map identifies waitid as a
cancelable generated syscall with a nocancel alias. Inspected Libc 1752.100.10
wait/waitpid wrappers use wait4; libpthread-539 cancellation source and the legacy
stub evidence do not establish a current-runtime waitid conversion. No actual
modern wrapper ABI corruption is proved. Exact versions/URLs/bytes are retained
in the isolated evidence primary/ directory. Standard public APIs are retained;
no raw syscall, connector replacement or unsupported symbol bypass is introduced.

## Minimal semantic correction, unknowns remain fail-closed

A shared classifier does not equate nonzero si_pid with exit. A NONE event must
have zero PID/signo/code/status. Other events require the exact requested PID and
SIGCHLD. Only CLD_EXITED/KILLED/DUMPED are terminal; signal deaths require a valid
signal number. CLD_STOPPED with raw status in the source-supported zero/signal
range is nonterminal. Unknown/foreign/malformed/traced/continued events fail
closed. Darwin extended exit bits remain terminal evidence, but production
helpers' ordinary exit-status projection explicitly rejects values outside 0..255
instead of aliasing extended values to normal 72.

Pinning explicitly requests WSTOPPED alongside WEXITED/WNOHANG/WNOWAIT. A STOPPED
classification additionally REQUIRES independently queried SSTOP metadata. Every
original identity predicate still applies: exact-size/PID metadata, non-zombie,
direct parent, private group, real/effective UID, positive birth seconds, valid
microseconds. No identity is enrolled until all checks pass. WNOWAIT retains PID
custody through image verification, pinning, SIGCONT and later group signaling.
No unknown code, syscall failure, zombie or foreign mismatch becomes eligible.

The production/probe observers use the same strict event classification. The
atomic exact-three/all-zombie snapshot predicate is byte-unchanged. Normal cleanup,
HOLD/noinput/admission, success schema 1 and all native deadlines remain intact.

## Causal cleanup defect removed independently of event decoding

Old probe cleanup skipped SIGKILL whenever observe returned 1 solely from matching
si_pid, even if a child was stopped. It then waited for a child that could not
consume lifeline EOF. The source permits exactly this deadlock; the old receipt
alone does not identify which event/earlier branch actually occurred.

After the last group action, cleanup now uses actual waitpid(WNOHANG), not siginfo.
Only a returned requested PID records a reap/status and clears custody. A fresh
return 0 is the direct-child, unreaped authority for per-PID SIGKILL; the probe has
one reaper and does not release that identity between readback and signal. A
terminal transition in that gap remains an unreaped zombie, not a recycled PID.
ECHILD/other failures deny signaling; only EINTR is retryable inside the original
common deadline. All four potentially owned children share the original one-second
grace/two-second total, with no per-child deadline extension. Unknown/unreaped
identities remain truthfully reported and fail the mechanism. No cleanup is claimed
successful without a real returned-PID reap. Fresh hosted evidence is still needed.

## Exact paired negative-diagnostic interoperability proposal

Append PIN_WAIT_EVENT and PIN_WAIT_STATE to the fixed C/Python stage registries;
existing values/history remain intact. Correct zero errno classification to NONE.
For the FIRST failed terminal/event/state pin, retain only the actual successful
waitid readback as a nullable failure.wait_event object:

    {"signo": int32, "code": int32, "status": int32, "pid_relation": 0|1|2}

pid_relation is factual: 0=zero PID, 1=requested PID, 2=other PID. It is NOT a
terminal/stop decoder and exposes no raw foreign PID. Other stages emit null.
No syscall-error output is decoded as a valid event. No historical object is
backfilled. The parser accepts exactly the original schema-2 keys OR those keys
plus this one nullable object, checks exact object keys/signed-int32 bounds and
relation enum, and defensively copies the nested primitive object. The two new
stages require a non-null readback. Legacy negative packets still validate unchanged.

This is a parent-review proposal before integration/publication. Existing native
qualifier/public provenance consumers delegate to the paired strict native parser;
no observer/provenance helper, workflow, Windows or browser edit is performed or
required by this source delta. Probe JSON keys/case count are unchanged. No positive
schema or acceptance predicate is expanded. Actual emission/retention of the new
object is pending the reviewed hosted run, not proven by old-record replay.

## Evidence boundary

Only actual source/static assertions, Python/shell syntax and unmodified genuine
retained records were checked here. No synthetic events/fixtures/mocks/stubs,
native/controller/audio/device/provider execution, owner node, configuration,
credentials, installation, network write or CI rerun/dispatch occurred. New native
C compilation and production/probe/cleanup runtime outcomes remain unqualified.
The exact old event remains UNKNOWN despite the source-proven compatible mechanism.
Parent independently reviews, publishes and owns the genuine hosted cycle; no
irreducible owner-input blocker or relaxed safety/timeout gate is asserted.
