# Suspended-spawn custody enrollment: historical diagnostic follow-through

This records the 20d source delta later consumed by 6c45804. For the actual 6c
hosted failure, kernel UNIX03 macro collision, semantic wait-event/cleanup repair
and narrow paired negative-diagnostic proposal, see
[Wait events and custody](native-waitid-event-custody.md).

## Actual evidence and unknown cause

Frozen source head: 20d973a372766290ab7a367f2a803061a24f3f34. CI 45469384734
actually checked out 17b73e558d29196a2d0f9669989ec4eb655b5168, tree
48cd1cf661ec232ec12886fbb2b9510945170a77, identical to the candidate.
The native build/link/sign, source-34/header/image binding and all FIVE genuine
shared-predicate evaluations passed: live/mixed false, exact-three zombies true
with 12 bytes, extra-live/extra-zombie false with 16 bytes, normal owned cleanup.
That probe used fork/live enrollment, NOT production suspended-exec enrollment.

Production still returned controller 70 / CLI 1 / STARTUP HOLD. First failure:
GROUP_CUSTODY role 1, recorded errno_class NONE, elapsed 2,088,166 ns in a
1,999,409,416 ns window. Failure-time waits were -1/-1/-1; cleanup_errors=4.
Final retained PID tuple 2069/-1/-1 was reaped 9/-1/-1 with forced cleanup 1/0/0.
This is not normal production closure or successful admission.

Both getpgid and the combined pin helper emitted that SAME stage with
CAPTURE_FAILURE, which did not snapshot a syscall errno. Therefore NONE does NOT
prove that getpgid/waitid/sysctl succeeded, and the packet cannot identify the
failed subguard. No historical branch, field value or errno is backfilled.
The older e9 three-case mechanism/normal-72 GROUP_SIGNAL EPERM failure remains
separate; historical e4be is still unknown. Source review r15 is source-only.

## Primary-source investigation, not runtime attestation

Apple XNU f6217f891ac0bb64f3d375211650a4c1ff8ca1ea shows:

- kern_fork.c:1123-1132 initializes p_start for a new process and preserves it
  across exec. A blanket claim that suspended spawn necessarily has zero birth
  time is NOT supported by this source.
- kern_exec.c:2220-2233 applies POSIX_SPAWN_START_SUSPENDED via process suspension
  and p_stat=SSTOP. The production expectation differs from fork/live pinning.
- kern_exit.c:3163-3390 counts matching direct children, filters stopped status
  unless requested, and returns success without modifying siginfo on WNOHANG
  with no requested event. The helper already zeroes si_pid first. A stopped
  child is not inherently invalid WEXITED|WNOHANG|WNOWAIT custody.
- kern_sysctl.c:1199 onward exports p_start into LP64 extern_proc and exports
  cached parent/PGID plus real/effective credentials in eproc. kern_prot.c:217-239
  implements getpgid from the cached group ID or returns a real lookup error.

Those sources explain field lifetime and expected API behavior, not the exact
kernel source or unrecorded values on build 25G332. There is no demonstrated
field/provenance failure that justifies removing or broadening a guard. This
change is therefore pinpoint diagnostic instrumentation and faithful hosted
probe coverage, NOT a demonstrated production root-cause correction.

## Production diagnostic-only change

The existing image verification still precedes enrollment, and enrollment still
precedes SIGCONT. All existing checks remain: valid arguments, direct unreaped
WNOWAIT child with no terminal event, exact-size metadata/PID, non-zombie state,
matching parent/group/real UID/effective UID, positive birth seconds and valid
microseconds. The stored identity and enrollment flag are written only after ALL
checks succeed. No retry, zero-birth exception, errno allowance or deadline change
is introduced. Group-zombie closure predicates are unchanged.

The pin helper returns a fixed reason and captures a real syscall errno only at
the failing waitid/sysctl call. Production records its FIRST failure before
cleanup can overwrite context. The preliminary getpgid guard is separate.

### Exact enum interoperability proposal for parent review

Failure schema 2 retains exactly its existing keys, bounds and HOLD/70 semantics.
Append these fixed stage values in BOTH capture_diagnostic.h and
capture_diagnostics.py (existing numeric values/history remain intact):

GROUP_PGID, PIN_ARGUMENT, PIN_WAIT, PIN_TERMINAL, PIN_METADATA_QUERY,
PIN_METADATA_SIZE, PIN_METADATA_PID, PIN_ZOMBIE, PIN_PARENT, PIN_GROUP,
PIN_RUID, PIN_EUID, PIN_BIRTH_SEC, PIN_BIRTH_USEC.

The native parser registry is the only required consumer extension. Existing
provenance/qualifier consumers import it; their files and safe observer/projection
are untouched. There are no new public keys, raw field values, paths or signature
strings. Historical GROUP_CUSTODY and IDENTITY_VISIBLE remain valid old labels.
Parent must independently review this exact enum delta before integration; no
observer/provenance-helper or workflow patch is proposed or performed here.

## Diagnostic-only real suspended-exec coverage

The hosted probe now spawns its own exact signed executable instead of fork-only
members. It uses the production flags START_SUSPENDED, CLOEXEC_DEFAULT and
SETPGROUP, an empty environment, mapped lifeline/ready FDs, and held direct PIDs.
Before any continuation it checks getpgid, strict live/disk code validity, exact
path/identifier/CDHash, an actual SSTOP metadata observation, and the SAME pin
helper. Only then does it send SIGCONT and accept readiness. This is a genuine
POSIX-spawn-suspended path, never a mocked kernel or fabricated observation.

All three original cases and the two real extra-member evaluations remain. Root
JSON schema 2, exact keys, case count, census-byte readback, no-admission flags,
three-second case/two-second common cleanup budgets and source hash inventory
are unchanged. Security/CoreFoundation are native framework links, not third-party
dependencies. The existing shell still signs the exact image before it executes.
The actual capture-role images/sandbox and physical APIs are NOT executed by the
probe, so probe success alone still cannot qualify production.

## Source assertion correction

The obsolete current-macro demand for IDENTITY_VISIBLE is replaced with actual
IDENTITY_QUERY/ECHILD behavior. Added source assertions require independent saved
reap status, no retained identity, WNOWAIT ECHILD readback, fail-closed query failure,
and NO numeric kill/getpgid query after reaping. Registry parity/critical-stage
coverage remains and includes every new pin guard. Additional static assertions
require all original pin conditions and verified-pin-before-SIGCONT probe order.
No synthetic packet fixture, mock/stub or simulated OS result is added or run.

## Qualification boundary

Only source assertions, Python/shell syntax, bounded source inspection and genuine
retained-receipt replay are possible in this Linux authoring lane. Revised native
C has NOT been compiled/executed on Darwin. The actual production subguard and
required semantic repair remain unknown pending the next exact-head hosted packet.
Keep HOLD and all existing safety/admission/deadline gates. Parent owns independent
review/publication and the existing hosted cycle, not an owner/infrastructure
blocker. New Windows execution is outside this native writer's scope.
