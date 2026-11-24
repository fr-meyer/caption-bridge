# Windows Node shortcut timeout: diagnostic only

## Actual evidence and unresolved cause

At head `20d973a372766290ab7a367f2a803061a24f3f34`, Windows run45469384719,
job138712872955, the four fresh-process checks passed. The offline phase had
92 passes, one failure, two skips, one existing xfail and172 subtests. The
failure was `ShortcutContractTests.test_capture_forwards_and_modal_guard_mutation_is_detectable`:
`node.exe -e ...` exceeded the existing five-second `subprocess.run` bound.
No public-DOM fixture was reached; cleanup passed. This is not browser or
physical/user-outcome acceptance.

The retained CPython3.11 trace timed out in `stdout_thread.join`, not in the
parent's stdin writer. CPython's Windows `_communicate` starts output readers,
then calls `_stdin_write` before joining them. The generic writer closes stdin
and ignores BrokenPipeError/expected Windows EINVAL. An OS child was created,
but the trace does not establish JavaScript entry, delivered input, observed
EOF, JavaScript completion, OS exit, or the
identity of a remaining stdout handle. The exact current source serializes
2791 ASCII input bytes. Node22's fd0 UTF-8 `readFileSync` route delegates to the
native binding; no unsupported input API or proven transport bug was found.
Prior heads with the same relevant code passed, but that does not prove a
false alarm. **Root cause remains UNKNOWN; no causal repair is claimed.**

Implementation references (contract inspection, not exact CI-binary attestation):
- https://github.com/python/cpython/blob/3.11/Lib/subprocess.py
- https://github.com/nodejs/node/blob/v22.x/lib/fs.js
- https://docs.python.org/3.11/library/subprocess.html#subprocess.run

## Bounded observation for the next authorized hosted execution

The existing Node entrypoint, stdin/UTF-8 `communicate(input=...)` route and
five-second timeout are retained. No retry, timeout padding, new Node/model
case, extra subprocess, guard relaxation, native change or workflow change is
introduced. The existing shortcut model, deliberate modal-guard mutation and
all original assertions remain **MODEL_ONLY**, unchanged as acceptance claims.
The existing model stdout receipt and offline success receipt schema are unchanged.

Synchronous, fixed ASCII stderr markers identify actual progress:
0 entry (after requiring fs);1 before stdin read;2 after stdin read (with the
UTF-8 byte count);3 JSON parsed;4/5 original model begin/done;6/7 mutant
begin/done;8/9 forwarding begin/done;10 result-write begin;11 console.log
returned (not proof of flushing);12 Node exit-event callback (not OS-exit proof).
The fs bootstrap is inside the unobserved interval before marker0. A missing
marker never proves where the process stopped. Markers may be incomplete on
timeout; protocol validity is not completion or success.

The Python parent reports only an allowlisted diagnostic: actual outcome,
actual monotonic elapsed milliseconds, input byte count/SHA256, observed marker
IDs/byte count, fixed error class/code if visible, truncation/protocol flags and
`cause=UNKNOWN`. It scans at most4096 stderr units and publishes at most13
marker IDs. No raw stderr/stdout, script source, executable path, PID, environment,
credentials or arbitrary error text is published. Timeout/nonzero/spawn failures
still fail; exception messages use the bounded diagnostic rather than raw Node
command/stderr. Measured elapsed time may include process creation/cleanup;
Python's timeout is not a promise that those operations are interruptible.

The existing offline plugin independently checks the exact diagnostic shape,
size (<=2048 characters), enums, integer/hash types and stage names. Only the
exact existing test's packet is scanned within8192 captured characters and
re-emitted in the terminal summary, including on green, because pytest otherwise
hides successful-call output. This does not
change counts, selections, status decisions, guards, receipt schemas or budgets.
Malformed diagnostic rows are not republished; they are not gate waivers.

## Qualification boundary

Only source/static checks are authorized locally. Do not execute this model,
create fake Node timing/IO examples, invoke owner Windows/macOS runtimes, or
rerun/dispatch CI. Parent review/publication is followed by a new genuine hosted
Windows run. Retain its exact-head checkout and diagnostic before narrowing the
cause. A green run establishes only that run's software result, not a repair of
the historical timeout and never physical/provider/release acceptance.
