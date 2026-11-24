# Native all-zombie group closure: narrow Darwin correction

## Authority and delta ownership

This isolated native source lane starts at e9aa766145976dff8f0c1a079baddf68b2c486f0.
The parent owns review, public-safety review, integration, publication, hosted
qualification and any later eligible Dev merge. No workflow, dependency lock,
browser, Windows, provider, device, node, credential or production configuration
is changed here. There is no deployment/physical capture approval in this change.
The production correction and diagnostic extensions are separate sections below.

## Actual causal evidence, not new-head acceptance

CI [45456295172](https://github.com/fr-meyer/caption-bridge/actions/runs/45456295172),
actual checkout fb2f3b069368ecf614cd26e6f53ffe718c241785, tree
6e35cbcc086934be4247f9450f12f9e4aba177c4 (identical to e9aa766), retained a genuine
three-case compiled/signed Darwin 25.6.0 / build 25G332 probe:

- Live group: states 2/2/2, both signal calls rc 0 / errno 0, actual reap 9/9/9.
- Zombie leader plus live peers: states 5/2/2, WNOWAIT exits 72/0/0,
  both signals rc 0 / errno 0, reap 18432/9/9.
- All zombies: states 5/5/5, all WNOWAIT normal exit 72, signal 0 and SIGKILL
  both rc -1 / EPERM, reap 18432/18432/18432.

Every case had complete owned census, retained custody, zero forced cleanup and
zero remaining owned children. Public native-probe receipt SHA256:
395a156e5938b152b24f99df17c3ea34558be82e4b729011584ca7e70fb53022.
Capture provenance receipt SHA256:
f1973943895498aa6556bcbf2f81538eea48b4badda5148d43bb0af40d3d07d6.
The actual capture still returned 70 / GROUP_SIGNAL role 1 EPERM and HOLD, with
three normal-72 owned children. That failure is not called successful. Four exact
image SHA256/CDHashes, generated pins and the then-33-source inventory are retained
for that run, not backfilled from an earlier run. Historical e4be is still unknown.

## Production correction

The actual group SIGKILL remains before reaping the group-leader anchor. A normal
successful syscall follows the existing path. Only EPERM can enter the new proof;
all other kill errors (including ESRCH despite a retained anchor) now fail closed.
The original signal errno/stage is preserved when proof fails, even if metadata
queries overwrite errno. This is not an unconditional EPERM whitelist.

owned_group_closure.h provides the shared predicate. Each of three direct children
is enrolled while live/suspended, AFTER the existing exact code-image verification,
with its PID, parent, group, real/effective UID and kernel birth time. Enrollment
requires WNOWAIT direct-child custody. A partial spawn/missing enrollment fails.
Before an EPERM result can be considered closed, the predicate requires:

1. All three unique expected identities are still direct unreaped children with
   WNOWAIT terminal observations. The retained leader must be the PGID anchor.
2. Independent exact-size KERN_PROC_PID readback says SZOMB for every child, with
   the enrolled birth, parent, PGID and credentials unchanged. A zombie cannot
   exec, move group or fork. No new identity is inferred from a recycled PID.
3. proc_listpids(PROC_PGRP_ONLY) returns EXACTLY those three PIDs in a fixed
   FOUR-PID buffer. Any fourth/unknown/live/foreign member, full/truncated output,
   duplicate/missing PID, denied/failed/empty query or malformed byte count fails.

The spare slot is mandatory: accepting a full three-slot buffer would mistake a
truncated group for a complete group. The four-slot call accepts only 12 bytes,
never 16. No sizing-query/reallocation race or unbounded userspace allocation is
introduced. All metadata calls are fixed-size, non-reaping, and have no retry loop.

A group sysctl callback census alone is NOT the completeness proof. Apple XNU
[proc_listpids](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/proc_info.c#L359-L469)
selects the raw cached PGID across both allproc and zombproc while holding
proc_list_lock, without the sysctl SIDL skip or later proc_find callback loss.
The same lock protects
[pgrp_add_member](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_proc.c#L2596-L2615)
and
[pgrp_replace](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_proc.c#L4353-L4363).
Thus the underfull list is a membership snapshot, not a sampled callback walk.
The already-pinned zombies cannot generate a later fork during this snapshot.
It establishes closure at that boundary, not authority to signal a later recycled
PGID, ignore escaped descendants, or assume the production session is private.

The system libproc link is native macOS API use, not a new third-party dependency.
Terminal status/forced-cleanup validators remain unchanged: proving dead membership
does not turn signaled or unexpected child exits into normal admission. Native
budgets and success schema 1 are unchanged. After independent owned reaping,
ECHILD readback replaces numeric kill(pid,0): no recycled PID is queried/signaled
as though it were the old identity. This checks lost OWN custody, not global PID
absence. The noaudio-only controller branch is unchanged.

## Diagnostic extension, deliberately not production admission

The hosted fork-only probe now compiles the SAME production predicate and records
its real answer for the existing live/mixed/all-zombie cases. It must reject live
and mixed, and close the exact three-zombie group. Within the all-zombie case a
real fourth owned child joins the private group, but is omitted from the expected
three identities. The predicate must reject it both live and WNOWAIT-zombie; it
must accept the original group again only after that fourth child is independently
reaped. The shared readback reports actual PID-snapshot byte counts: 12 for the
three-zombie proof and 16 for BOTH extra-member rejections. A transient census
error cannot be mistaken for exercising the extra-member rejection branch. No group signal is made while the extra member is present. All children
use lifeline EOF and the same common cleanup budget; forced cleanup remains failure.

Only diagnostic rows move to schema 2, adding all_owned_zombies plus a fixed
adverse object containing nullable booleans and bounded snapshot-byte/status/cleanup
integers. No raw extra PID or birth-time field is added to the public projection.
Missing observations remain null, not fabricated negative or positive outcomes.
The public observer still publishes only its bounded one-file projection, now
with exact schema-2 keys and four source/binary hash records (C, shell, shared
header, binary). Capture provenance includes the new header in its exact inventory
(now 34 files). Raw runtime/signature/absolute-path data remain private. Existing
workflow invocation and single-file upload routes need no changes.

## Required next-head checks

Static Python/shell/source inspection and exact old-receipt replay are not Darwin
acceptance of this patch. The new header, libproc call, new adverse process path
and changed controller have NOT been compiled/executed in the Linux authoring
session. No mocks/stubs, synthetic fixtures or Linux substitute process proof was
used. The old schema-1 receipt is preserved as old evidence, not upgraded to 2.

After independent parent review/publication, hosted exact-head qualification must
retain the updated source/header/image/generated-pin bindings, genuine three-case
schema-2 predicate/adverse observations, successful noinput controller closure
with normal exits and no forced cleanup, and existing independent qualifier
readback. Live/mixed predicate rejection and extra live/zombie rejection must be
real OS results. Census-denial/corruption paths are statically fail-closed but are
not claimed dynamically exercised. All physical/admission flags of the diagnostic
remain false. No local result makes the PR eligible to merge before that readback.
