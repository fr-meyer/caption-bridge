# Hosted capture noinput provenance retention

An observer-only retention path for the existing macOS build and noinput qualifier, not a new
native probe or admission gate. Native sources, builders, qualifier and diagnostic
parser are unchanged. The noaudio artifact remains separate.

## Fixed safe artifact

The existing build command and the exact uv no-sync Python 3.13 noinput-module
command remain directly in their original Bash steps, with actual failure status
preserved. Metadata phases never launch either native command or change its process
session/group ancestry. Separate bounded phases observe before and after qualification.
Only these filenames can be uploaded:

- capture-noinput-provenance.json, if safe disk readback succeeds.
- capture-noinput-qualifier.json, only for a genuine strictly validated stdout
  receipt, including its failure diagnostic. A failure is never rewritten as success.

Each file is at most 32 KiB, total at most 64 KiB. The upload lists both filenames
explicitly, without globs, and requires finalizer post-readback safe_artifact=true even after
native failure. No raw logs, binaries, generated-header text, absolute paths, argv,
environment, device identity, audio, captions or secrets are uploaded. Unknown keys,
arbitrary text, duplicate JSON keys, nonfinite numbers, symlink/irregular leaf files
and unexpected artifact files are rejected. Raw child output stays private outside
the public directory. Readback happens before and after the atomic directory rename.

## Actual image, pin and source binding

After successful build, hash the actual four signed files: CaptureController,
CaptureGuardianA, CaptureGuardianB and CaptureHelper. Verify each signature using
codesign and retain only the fixed expected Identifier and CDHash. Rehash after
verification. Read generated capture_pins.h as data, require the exact existing
generator format, and compare all three ordered role CDHashes with signed images.
Only the generated file's SHA256 is retained, not its header text.

Bind actual git HEAD and tree to github.sha and hash a fixed 33-file entrypoint/native
input allowlist. Tracked source must be clean; every selected working file must equal
its committed blob. The event-head SHA is declared GitHub context, not an independently
fetched head tree; shallow checkout is unchanged. The actual checkout tree remains
authoritative. The parent collector separately verifies merge/head tree identity.
The full Git tree covers tracked inputs beyond this explicit list; this does not
claim complete compiler/SDK reproducibility.

After qualification, recheck source, four image hashes and generated-pin hash.
These are before/after observations, not continuous immutability or independent
owned-group/descendant closure acceptance. Both admission flags stay false.

## Failure and gate behavior

Build failure retains its real return code and source binding if obtained, with
unknown (null) images, generated pins and qualifier fields. Partial files are never
called verified. Malformed/missing/oversized/contradictory qualifier output produces
only fixed classifications; it is not copied. Cancellation or timeout may prevent
any final artifact. Raw private files are never fallback upload candidates.

An actual nonzero build/qualifier return code wins over retention success or error.
Bash retains the original child shell status (including signals). A retention,
source, signature, receipt or disk-readback error makes an otherwise successful
child path fail. Nothing accepts native exit70 or loosens its qualification gate.

## Verification limits

Local source/static gates and replay of the genuine hosted f949 failure packet can
validate the decoder without mocks, stubs or fabricated image data. They do not run
macOS codesign, build new capture images or qualify a new hosted run. The next
parent-published CI run must independently read back this exact artifact and check
source/image/pin/receipt bindings. Historical missing image hashes remain missing.
This change does not repair GROUP_SIGNAL/EPERM.
