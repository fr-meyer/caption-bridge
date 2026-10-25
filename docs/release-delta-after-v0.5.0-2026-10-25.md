# Reviewable delta after v0.5.0 — October 25, 2026

This is a source and automated-software inventory, not a release, installation,
hosted-run request or new listening session. Physical device/listening testing is
a post-release, nonblocking follow-up under the owner's current direction.

## Exact comparison

| Identity | Recorded commit / application tree |
| --- | --- |
| Released v0.5.0 | `39ecd3e7e6eafd367877eff3b0a0ef878a17b127` / `8853dd29621f3da02a399034bf4fe82844987722` |
| Reviewed development baseline | `e25623d0168400f8b1867f6f4ab34ef85fa157fe` / `bc00dc015d58374ec579b9ce6063df8635567197` |
| Recorded Mac installation | `a746f9aff65ee40ff3943d1137127378e744fae2` / `bc00dc015d58374ec579b9ce6063df8635567197` |
| Published PR89 with passing Ubuntu CI | `fbb213f4db2247e0d0192ca3802463524e73991c` / `64dcfa6b3aaccb8b0a0ba97301fbcb15bd3e7d37` |
| Windows-tested harness source | `a912ea2f73630dba9c0205e6a33988f3add8c164` / `64dcfa6b3aaccb8b0a0ba97301fbcb15bd3e7d37` |

The development baseline includes merged PR85, PR86 and PR87. Its exact-head
Ubuntu [CI39046064304](https://github.com/fr-meyer/caption-bridge/actions/runs/39046064304)
passed Python 3.11, Python 3.13 and Chromium on October 17. This is retained
evidence for that commit, not CI for a later diagnostics or workflow change.
Package version remains 0.5.0; `pyproject.toml` and `uv.lock` are unchanged from
the released baseline. No new tag or release version is selected here.

The recorded installed application matches the `e25623d` development baseline
above. Cross-platform workflow/documentation preparation alone needs no update
or repeat test of ordinary installed Medium. PR89 includes the combined ASR
follow-up and its headless-import fix; its application tree is
`64dcfa6b3aaccb8b0a0ba97301fbcb15bd3e7d37`, different from
the installed `bc00dc0` tree; it is prepared source and has not been installed.
Installed Medium remains unchanged and usable. An equal application tree is
source identity, not a fresh runtime/settings, dependency-advisory or physical
acceptance result. No installation or runtime test is performed by this inventory.

## Behavior and source changes since the release

| Area | Included change | Defaults and limits |
| --- | --- | --- |
| Device selection | Explicit microphone/speech-output controls, permission-assisted browser output discovery, input selection held through reconnect, unavailable-output cancellation | User controls device choices and permission; normal capture/Start behavior remains |
| Reconnect | Audio unlock restores only after the current admitted connection's snapshot; stale callbacks/epochs remain rejected | Captions and source/translation provenance are retained |
| Terminology UI | Keyboard focus survives row rebuild/close; resolved error descriptions are cleared | Earlier caption text is not rewritten |
| Reliability software | Bounded callback, fake SDK and PCM state cycles; a current-version Windows idle-app fixture | Finite software contracts, not elapsed endurance or physical Windows support |
| Timing research | Numeric per-chunk source/browser reports, pinned fixture adapter, offline actor attachment and retryable observer retirement | Not imported by the app; attended actors remain rejected |
| Speech-speed research | Bounded pitch/speed worker and memory evaluations | Evaluation only; production speech speed remains normal |

Medium, provider routing and token/deadline behavior are not changed by the
cross-platform preparation. Buffered speech remains the default; progressive
playback remains opt-in. The baseline comparison above ends at `e25623d`.

The prepared October 25 local combination also includes issue #88's
[ASR diagnostics and recovery-notice correction](asr-recovery-diagnostics.md),
backend candidate `2c4b1c37d61253e4a75dccef73b2d34d0ab2fb61`, with frontend
snapshot correction `85be9c2bdc732e4798a44baa18d55cfdc0b0468c`. It adds timestamped,
allowlisted failure/reconnect records with opaque run/attempt correlation,
duplicate suppression and a truthful automatic-recovery notice. A final
provider-free Mac run passed 88 focused Python/pipeline/WS cases; five headless
Mac Chrome cases passed with media APIs and external page requests denied.
These results do not identify the cause or duration of the October 20 incident,
qualify another platform by themselves, or update the installed Mac. The later
headless-import repair defers sounddevice loading until a real device query or
Start, preserving runtime failure when no backend/device exists. PR89 at
`fbb213f` subsequently passed the Ubuntu software checks below.

## Exact evidence binding for this aggregate

Ubuntu [run40159366785](https://github.com/fr-meyer/caption-bridge/actions/runs/40159366785)
passed at PR89 head `fbb213f4db2247e0d0192ca3802463524e73991c`.
Its checked-out merge commit `add16c8cb135162a986e4399a8ae3a0769da0d38`
has the same complete Git tree as that head:
`1030aae45251e33579720ca28b77aebd8315da72`.
Python 3.11 and 3.13 each passed 530 tests with three recorded skips;
Chromium passed 62 cases, Node routing 16 and Node pitch evaluation 34.

Native Windows [run40164259241](https://github.com/fr-meyer/caption-bridge/actions/runs/40164259241)
checked out `a912ea2f73630dba9c0205e6a33988f3add8c164` via a separately
approved one-shot launcher. Four headless/report cases and 47 offline cases
passed with one known strict expected failure. The owned fixture server,
idle public DOM gate and teardown passed; no listeners or temporary browser
profile remained. The run used Windows Server 2025, Python 3.11.15,
Node 22.23.4 and PowerShell 7.6.7, with fake media/providers throughout.

PR89 and that Windows source have identical `app/`, dependency and workflow
bytes. The eight-file difference is the tested Windows IPC/fixture/report
harness and its tests/documentation. This local aggregate takes that exact
`a912ea2` source with documentation-only updates; its executable source,
tests and dependencies are unchanged from the Windows-tested source.
The one-shot Windows launchers are excluded. Neither prior run is claimed as
exact-head CI for this aggregate: ordinary aggregate-head Ubuntu CI remains
pending publication and separate execution approval.

## Automated platform coverage and the actual gap

| Platform / path | Existing evidence | Remaining automated scope |
| --- | --- | --- |
| Ubuntu | Passing ordinary CI at `fbb213f`: full Python 3.11/3.13, Chromium, Node routing and bounded offline contracts | Refresh exact-head CI for the aggregate harness/documentation delta |
| macOS | Retained local fake/stdlib/Node checks and the affected muted Chrome/qualified-actor regression | These retain exact source/harness limits; no new Mac workload is needed for this workflow/document change |
| Windows current version | Passing native Server 2025 run at `a912ea2`: guarded software tests, actual fake-media/provider app lifespan, idle raw-CDP DOM and owned teardown | Software fixture only; native audio, live providers and ordinary Windows controller remain unqualified |
| Historical Windows v0.2.0 | Separate immutable-release workflow | Preserve it; it does not qualify current v0.5 software |

The remaining aggregate check is its normal three-job Ubuntu PR workflow.
No further Windows run is required for these documentation-only changes to
the tested source. The retained v0.5 manual workflow is still manual-only;
its presence does not authorize another run. The earlier Windows attempt
[40163129292](https://github.com/fr-meyer/caption-bridge/actions/runs/40163129292)
failed after its tests while reporting the OS version; that failure is retained,
and the success above includes its guarded receipt correction.

The strict expected failure for the ordinary controller's native Windows Python
path remains open. A successful Windows fixture job must not be advertised as
native lifecycle support. Optional PowerShell parsing, Windows-only lock tests,
the unpublished public fixture and other actual skips must retain their recorded
reasons; generic platform mocks do not close them.

## Later release review

For a concrete release candidate, reconcile its final source delta, review and
exact-revision software results; preserve the rollback and Mac-local settings.
The recorded installed candidate's immediate rollback is `78c25a49`, while the
published-release predecessor is v0.4.0. Verify the actual installed predecessor
if a later installation is requested. Do not treat a published tag as the
automatic immediate rollback for a development installation.

Publication, main/master promotion, tagging, installation and hosted execution
remain separately requested actions. None is performed by this document or the
new manual workflow's presence. Physical Windows/Safari, devices, listening,
VoiceOver and elapsed endurance remain post-release follow-ups and do not block
the supported Mac release or ordinary Medium use.
