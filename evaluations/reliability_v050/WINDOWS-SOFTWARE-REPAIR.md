# Windows software portability repair

The current-candidate Windows run at source `aa717105` reached four passing
fresh-process checks, then failed two reliability checks. Its fixture/browser
never started. Those results remain failures; this change does not replace them
with a native Windows pass.

## Exact link text, not a resolved target

Windows `os.readlink` can return an extended-path spelling different from
`str(target)`. The leaf-link test now records the actual link text before and
after changing external target bytes. It compares that exact text and the
existing source hash; it neither resolves nor normalizes the link.

The regression forbids target payload reads and path resolution. A separate
Linux test models Windows extended-link spelling and the no-dir-fd branch.
Ancestor/reparse refusal, root checks and race checks remain unchanged. Modeled
Windows metadata is software evidence, not real host/device qualification.

## Existing process names, Windows casing only

The explicit names remain `git`, `node`, `node.exe` and `pwsh`. Only on
Windows are their ASCII filename case variants equivalent, including a discovered
`node.EXE`. POSIX names stay case-sensitive. The guard does not infer additional
suffixes from PATHEXT: batch/command wrappers and new executable names stay
unapproved. It does not resolve new paths, rewrite caller argv, or introduce a
shell. Existing basename-based path policy remains; this is not executable-byte
attestation or a sandbox for hostile Python code.

Keyword and positional shell/executable overrides are rejected before process
construction, so they cannot bypass the name check. Valid argv and ordinary
non-shell options pass through unchanged. JavaScript punctuation inside Node's
literal argv is not shell syntax.

Dedicated policy tests cover both host semantics, Windows case variants,
PATHEXT and deceptive suffixes, wrong executable/path leaves, invalid argv,
POSIX case rejection, unchanged approved calls and constructor refusal. Modeled
calls use mocks and cannot create children. The real guarded suite still runs
its existing finite Node checks and denies network/native audio/provider IO.

## Remaining qualification

Run the guarded reliability selection and the dedicated source/process tests
using the existing compatible environment. Source-bound receipts must retain
unchanged-source checks and all existing privacy/cleanup guards. A reviewed
integrated candidate still needs fresh native Windows CI, including its fixture
and owned browser teardown. The POSIX controller's unsupported native Windows
ownership path remains explicit; no test is skipped or weakened to hide it.
