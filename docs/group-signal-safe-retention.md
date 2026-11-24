# Hosted owned-group signal observation: public-safe retention

This wires the already-reviewed real Darwin probe, not a production repair or an
admission test. No native source is changed. The only extra runtime step is a
one-minute probe after successful capture build and before the noinput qualifier.
Both use explicit !cancelled() and build.outcome == success conditions, so a failed
probe does not suppress the real qualifier. A failed probe still fails its job;
there is no continue-on-error. No existing timing/resource limit is expanded.

The observer runs inside the existing two-minute provenance-finalizer step. It
never launches the probe or capture binaries. The capture finalizer's failure is
preserved while still allowing probe-data projection. The existing two-file
capture artifact contract and noaudio artifact remain separate and unchanged.

## One bounded public JSON file

Only native-group-signal-observation-public/group-signal-observation.json is
uploaded, at most 32 KiB. The observer strictly validates actual disk readback
before and after atomic publication, then emits safe_probe_artifact=true. Upload
uses always() plus that marker, not the raw directory or broad RUNNER_TEMP globs.
The native diagnostic document's whole-directory suggestion is deliberately NOT
used: raw runtime/id/sysctl/codesign/entitlement/build/stderr/hash-path files and
outer stdout/stderr remain private runner-temp files.

Fixed public fields include:

- Actual checkout commit/tree and SHA256 of workflow, observer, probe C and shell
  source. The working source must match clean committed blobs.
- Genuine observations only, in the source's ordered 0/1/3 natural-exit cases.
  Fixed labels, booleans and bounded integers are checked recursively, with exact
  keys and bounded arrays. No anticipated syscall errno is substituted or accepted
  as a production closure rule. Numeric uid/euid/PID/session fields are the actual
  ephemeral runner observations, not usernames or owner identity strings.
- Kernel release and OS build only, constrained to bounded version syntax and
  crosschecked against the two native runtime-file build fields. No kernel version
  free text, host/machine/user identity or raw runtime lines are copied.
- Actual probe binary SHA256, signature-verification state, and comparison against
  the private three-line source/binary hash record. No signature text is retained.
- Four actual candidate image SHA256s, when available, and exact/prefix comparison
  against the private candidate hash record. Candidate images are never executed
  by the observer. A partial prefix count is not a complete binding.
- Actual probe result code when its fixed result file exists, and the genuine
  GitHub step outcome. Missing/partial/rejected sections remain explicitly unknown.

Only complete schema-valid JSONL rows are retained. If a final row is truncated or
invalid, preceding valid rows can remain with REJECTED status; missing cases are
never filled in. A failed/early probe can retain known source/runtime/binary data
and zero, one or two genuine observations. Missing return codes/hashes stay null.
Unknown keys, arbitrary strings, duplicate keys, nonfinite JSON, symlink/irregular
leaf files, extra public files and oversized data fail closed. Absolute paths in
private shasum records are compared internally, never copied into public JSON.

A claimed successful probe must have all three actual mechanism-complete rows,
result zero, known source/runtime, verified probe binary and complete source/binary
and candidate hash bindings. Otherwise retention itself fails. Safe partial data
from a failed probe can still upload without changing that failed probe's status.
All admission/physical-acceptance flags remain false, including for a successful
observation. This forked unsandboxed probe does not establish the actual capture
exec/sandbox topology or justify accepting EPERM for production closure.

## Verification boundary

Local checks use actual source/static gates and real existing filesystem evidence,
not mocked processes, fabricated observations or predicted receipts. This Linux
session does not compile or execute the Darwin probe and cannot validate genuine
three-case output. Parent exact-head review and the next authorized hosted run
must verify the actual public artifact, hashes, versions and real observations.
