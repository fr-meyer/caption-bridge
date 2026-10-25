# Windows 0.5.0 preparation and remaining physical checks

The original preparation used released main
`39ecd3e7e6eafd367877eff3b0a0ef878a17b127`, package 0.5.0. The October 25
software preparation uses recorded dev
`e25623d0168400f8b1867f6f4ab34ef85fa157fe`, also package 0.5.0; its Windows
fixture and bounded reliability tests remain the existing ones. Two separately
approved native Windows attempts followed that preparation; the second passed
as recorded below. The historical 0.2 harness and its evidence remain unchanged.
Existing Mac evidence keeps its original scope. The aggregate source preparation
starts no microphone, device, provider, production activation or hosted run.

Physical device/listening checks are **post-release and nonblocking**, following
the owner's current release direction. The remaining Windows software/lifecycle
limits below must be described accurately; they do not create a new physical
acceptance prerequisite for the supported Mac product.

## Recorded native software result

[Run40164259241](https://github.com/fr-meyer/caption-bridge/actions/runs/40164259241)
passed on Windows Server 2025 at exact source
`a912ea2f73630dba9c0205e6a33988f3add8c164`: four headless/report tests,
47 offline tests and one known expected failure, followed by the owned server,
idle browser DOM and cleanup gates. Python was 3.11.15, Node 22.23.4 and
PowerShell 7.6.7. Native streams and provider calls stayed disabled.
Teardown recorded zero listeners and no temporary browser profile.

Its application tree `64dcfa6b3aaccb8b0a0ba97301fbcb15bd3e7d37` equals
published PR89 `fbb213f4db2247e0d0192ca3802463524e73991c`. The aggregate
adds documentation-only updates to that tested harness source; it changes no
application, dependency, workflow, harness executable or test bytes.
This is not aggregate-head Ubuntu CI, native audio acceptance or ordinary
Windows controller support. Both approved Windows attempts are consumed;
there is no authorization for another attempt or an automatic retry loop.

## What the offline evidence covers

| Check | Actual code exercised | Boundary and limit |
| --- | --- | --- |
| 64 callback cycles | `AudioCapture` callback scheduling, finish-input tail, explicit Stop discard, EOF cleanup | Generated PCM and an asyncio queue; no `start()` or native stream |
| 24 ASR cycles | Production `transcribe`, installed SDK event parser/encoder, Created/Updated ACK, final-only, Delta/Done, EOF failure, cancellation | Fake socket/client, four 320-byte chunks per admitted stream, byte equality/hash; no model request |
| 512 PCM cycles | Production `CaptionPcmPlayer` and frontend epoch gate | Node VM, fake nodes/promises/clock; validates replay identities, late callbacks, cancellation and bounded retired/timer state; no browser/audio |
| Existing scenario and resilience checks | Real translation/TTS dispatchers, reconnect, owner conflict, snapshot, journals/export, bounded browser queue; 250 synthetic translations | Existing injected providers and temporary artifacts; no provider or hardware |
| Windows software contract | New 0.5 identity, existing-environment inputs, raw-CDP DOM gate/redaction/owned teardown, actual app lifespan | Native Server 2025 execution passed at `a912ea2`; SDK/sounddevice/readiness remain fake, so real device/controller behavior is unqualified |

The finite cycles are state accumulation checks, not a two-hour wall-clock soak. ASR fixture text and PCM data are synthetic and unrelated to recognition or audibility. Source content, provider bodies and raw PCM are excluded from the receipts. The native Windows result records Python 3.11.15 and the exact installed SDK/Node versions; no native Windows Python 3.12/3.13 run is claimed. Separate Ubuntu Python 3.11/3.13 evidence is bound in the [release delta](release-delta-after-v0.5.0-2026-10-25.md).

## Prepared Windows software gate

`scripts/windows_v050_software_acceptance.ps1` reuses the historical loopback-port, raw-CDP and stage-only failure logic. It requires PowerShell 7 with its modern .NET process API, an existing test Python environment and Chromium/Chrome/Edge executable. It performs no dependency or browser installation. It rejects present provider credentials, wrong version/head, dirty source, reused listener ports or a fixture attempting native/provider IO. It creates a unique temporary directory and retains the started Process objects for teardown instead of invoking a PID-only task kill. It launches only `scripts/windows_v050_fixture_app.py`, whose device metadata, readiness and SDK are faked before app import; native streams and requests are denied. The frontend is idle blocked and no Start is clicked. Owned fixture teardown passed in the recorded native run; ordinary controller teardown is a separate unsupported path.

After a Windows test host and its software run are explicitly scheduled, with dependencies already available and no provider keys in that environment:

```powershell
$env:RUNNER_TEMP = 'C:\CaptionBridge Offline\temporary'
pwsh -NoProfile -File scripts/windows_v050_software_acceptance.ps1 `
  -RepoRoot 'C:\CaptionBridge Offline\source' -ExpectedSha '<exact frozen commit>' `
  -PythonPath 'C:\CaptionBridge Offline\source\.venv\Scripts\python.exe' `
  -ChromiumPath '<existing approved browser executable>'
```

Any future run must preserve exact source identity, report software-fixture success with zero native/provider calls, leave no application/CDP listeners or profile, and retain only content-free reports. The recorded native execution met those gates; this example does not authorize another hosted run.

## Prepared manual automation for the current version

The new `.github/workflows/windows-v0.5.0-software.yml` has only a manual
`workflow_dispatch` trigger. Unlike the retained v0.2.0 workflow, it checks out
an explicit reviewed 40-character candidate SHA and invokes the existing v0.5.0
PowerShell fixture. A future approved job prepares Python 3.11 and the frozen
dependencies on a native Windows runner, uses its existing Chrome/Edge and Node,
and runs with read-only repository access. It installs no browser, passes no
provider secrets, does not click Start and does not use the ordinary lifecycle
controller as a substitute for owned fixture-process teardown.
Pytest's `-ra` summary retains actual skip/expected-failure reasons in the job
log before the fixture removes its temporary state.

The recorded success used a separately approved one-shot branch launcher,
not dispatch of this retained manual workflow. The one-shot launchers are not
included in the aggregate. Publishing or making the manual workflow available
does not authorize a run. If a new execution is separately requested, check availability on the
repository's default branch and name the immutable candidate SHA. Retain the
job URL, source identity, actual test/skips/expected-failure output and the
fixture's final stage-only software/cleanup results. The passing run covers
the native Windows software fixture; it does not prove native capture,
hearing, live provider recovery or the unsupported ordinary Windows controller.

## Separate Windows lifecycle limitation

`app.lifecycle` is the Mac/POSIX lifecycle controller: its Python path uses `.venv/bin/python`, process identity uses `ps` plus POSIX parsing, and Stop uses the POSIX signal path. The fake `msvcrt` contention tests do not prove native Windows process ownership. One real Windows lock-byte test is skipped on Mac; a new strict expected-failure records the missing `Scripts/python.exe` contract. The new software gate owns its fixture process directly and does not imply that this controller supports Windows.

A separate scoped lifecycle change would need platform-specific Python resolution, immutable Windows process creation identity and argv parsing, owned-only termination, stale-PID protection and Windows command-lock/process tests. Do not repair ownership by ignoring the start token or using a broad process kill. No lifecycle rewrite is included here.

## Post-release physical Windows follow-up

1. Freeze the consolidated device/speed candidate and record Windows edition/build, architecture, Python/SDK/browser versions and exact source identity. Resolve the native lifecycle path above or document one reviewed, owned manual startup/Stop path. Use a separate temporary context and artifacts; preserve existing accepted Mac evidence.
2. With an attendee present and device/provider work explicitly scheduled, inspect the Windows privacy state and input/output choices. Device enumeration and input-format validation must be real in this phase. Let the attendee control any permission changes. Confirm the intended microphone and headphone output; never infer either from labels alone. Review the PR81 device controls on this exact consolidated commit.
3. Start once only after the attendee confirms readiness. Require capture active plus mandatory verified Updated ACK before the source is delivered; record content-free RMS/peak, append counts, protocol flags and stage timestamps. The attendee can speak one prepared public sentence if no reviewed Windows playback route exists. Do not adapt the Mac speaker script or change a global audio route automatically.
4. Verify actual captions and the attendee's hearing verdict, then one planned replay/mute operation and same-document Stop/export/NewSession restart. The second Start must reach the verified transcription-ready gate without clicking a hidden enable button. A replacement document must require fresh trusted activation. Stop input immediately after each planned source; allow admitted work to finish, preserve export, and verify final reset and process/listener cleanup.
5. If live network interruption is authorized separately, disconnect/reconnect once under a reviewed controlled method. Check one owner, no duplicate source/caption, old epoch/clip retirement, preserved captions/export and fresh activation when the document changes. Without that action, record live interruption as untested.
6. Schedule a two-hour attended wall-clock session separately if requested. Define observations and a manual Stop procedure, not a new normal-session guard or retry loop. Record periodic content-free queue/task/resource and latency aggregates, planned source counts, export integrity and hearing judgments. A short generated/fake loop does not close this requirement.

Physical Windows microphone/privacy, WASAPI/other real host API, speaker/headphone routes, audibility, ordinary controller process teardown, live provider/network recovery and two-hour endurance remain open as post-release follow-ups until their actual receipts exist.
