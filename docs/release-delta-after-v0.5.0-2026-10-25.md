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

The development baseline includes merged PR85, PR86 and PR87. Its exact-head
Ubuntu [CI39046064304](https://github.com/fr-meyer/caption-bridge/actions/runs/39046064304)
passed Python 3.11, Python 3.13 and Chromium on October 17. This is retained
evidence for that commit, not CI for a later diagnostics or workflow change.
Package version remains 0.5.0; `pyproject.toml` and `uv.lock` are unchanged from
the released baseline. No new tag or release version is selected here.

The recorded installed application already matches this development application.
This inventory creates no reason to update or retest ordinary installed Medium.
An equal application tree is source identity, not a fresh runtime/settings,
dependency-advisory or physical-acceptance result.

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
playback remains opt-in. Issue #88 ASR diagnostics work is a separate candidate
and is **not** part of this frozen baseline or this software-workflow change.
Review its final combined diff and exact-revision checks separately if included
in a later release candidate; no cause or duration of a historical outage is
inferred here.

## Automated platform coverage and the actual gap

| Platform / path | Existing evidence | Remaining automated scope |
| --- | --- | --- |
| Ubuntu | Ordinary CI: full Python 3.11/3.13, Chromium, Node routing and bounded offline contracts at the recorded head | Reuse it; a future candidate needs its appropriate exact-head checks |
| macOS | Retained local fake/stdlib/Node checks and the affected muted Chrome/qualified-actor regression | These retain exact source/harness limits; no new Mac workload is needed for this workflow/document change |
| Windows current version | PowerShell fixture, copied raw-CDP/redaction/owned-process contracts and Mac-faked app lifespan; native Windows run not recorded | The prepared manual v0.5 job fills the execution route, not the evidence gap until actually run |
| Historical Windows v0.2.0 | Separate immutable-release workflow | Preserve it; it does not qualify current v0.5 software |

The current automated gap is native execution of the existing v0.5 Windows
software fixture. A new manual-only workflow prepares that route without
duplicating the same fake contracts or expanding automatic Ubuntu CI. It uses
an explicit candidate SHA, the locked catalog and an existing browser. No hosted
run, installation or provider call is performed in this preparation.

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
