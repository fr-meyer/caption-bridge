# Windows 0.5.0 preparation and remaining physical checks

This preparation uses main `39ecd3e7e6eafd367877eff3b0a0ef878a17b127`, package 0.5.0. It adds a separate Windows software harness and finite reliability checks. The historical 0.2 harness and its evidence remain unchanged. Existing Mac 0.5 physical acceptance is reused; no microphone, permission, device, provider, production activation, GCP or hosted CI operation belongs to this preparation.

## What the offline evidence covers

| Check | Actual code exercised | Boundary and limit |
| --- | --- | --- |
| 64 callback cycles | `AudioCapture` callback scheduling, finish-input tail, explicit Stop discard, EOF cleanup | Generated PCM and an asyncio queue; no `start()` or native stream |
| 24 ASR cycles | Production `transcribe`, installed SDK event parser/encoder, Created/Updated ACK, final-only, Delta/Done, EOF failure, cancellation | Fake socket/client, four 320-byte chunks per admitted stream, byte equality/hash; no model request |
| 512 PCM cycles | Production `CaptionPcmPlayer` and frontend epoch gate | Node VM, fake nodes/promises/clock; validates replay identities, late callbacks, cancellation and bounded retired/timer state; no browser/audio |
| Existing scenario and resilience checks | Real translation/TTS dispatchers, reconnect, owner conflict, snapshot, journals/export, bounded browser queue; 250 synthetic translations | Existing injected providers and temporary artifacts; no provider or hardware |
| Windows software contract | New 0.5 identity, existing-environment inputs, copied raw-CDP DOM gate/redaction/owned teardown, actual app lifespan | In-process fake SDK/sounddevice/readiness on Mac; PowerShell and Windows kernel execution remain pending |

The finite cycles are state accumulation checks, not a two-hour wall-clock soak. ASR fixture text and PCM data are synthetic and unrelated to recognition or audibility. Source content, provider bodies and raw PCM are excluded from the receipts. Python 3.11 and the exact installed SDK/Node versions are recorded; Python 3.12/3.13 have no new execution claim.

## Prepared Windows software gate

`scripts/windows_v050_software_acceptance.ps1` reuses the historical owned-process, loopback-port, raw-CDP and stage-only failure logic. It requires an existing test Python environment and Chromium/Chrome/Edge executable. It performs no dependency or browser installation. It rejects present provider credentials, wrong version/head, dirty source, reused listener ports or a fixture attempting native/provider IO. It launches only `scripts/windows_v050_fixture_app.py`, whose device metadata, readiness and SDK are faked before app import; native streams and requests are denied. The frontend is idle blocked and no Start is clicked.

After a Windows test host and its software run are explicitly scheduled, with dependencies already available and no provider keys in that environment:

```powershell
$env:RUNNER_TEMP = 'C:\CaptionBridge Offline\temporary'
pwsh -NoProfile -File scripts/windows_v050_software_acceptance.ps1 `
  -RepoRoot 'C:\CaptionBridge Offline\source' -ExpectedSha '<exact frozen commit>' `
  -PythonPath 'C:\CaptionBridge Offline\source\.venv\Scripts\python.exe' `
  -ChromiumPath '<existing approved browser executable>'
```

The run must preserve exact source identity, report software-fixture success with zero native/provider calls, leave no application/CDP listeners or profile, and retain only content-free reports. This command was not run on Windows during this Mac-only preparation. No new hosted CI run is authorized by the preparation itself.

## Separate Windows lifecycle limitation

`app.lifecycle` is the Mac/POSIX lifecycle controller: its Python path uses `.venv/bin/python`, process identity uses `ps` plus POSIX parsing, and Stop uses the POSIX signal path. The fake `msvcrt` contention tests do not prove native Windows process ownership. One real Windows lock-byte test is skipped on Mac; a new strict expected-failure records the missing `Scripts/python.exe` contract. The new software gate owns its fixture process directly and does not imply that this controller supports Windows.

A separate scoped lifecycle change would need platform-specific Python resolution, immutable Windows process creation identity and argv parsing, owned-only termination, stale-PID protection and Windows command-lock/process tests. Do not repair ownership by ignoring the start token or using a broad process kill. No lifecycle rewrite is included here.

## Physical Windows plan, after the software gate

1. Freeze the consolidated device/speed candidate and record Windows edition/build, architecture, Python/SDK/browser versions and exact source identity. Resolve the native lifecycle path above or document one reviewed, owned manual startup/Stop path. Use a separate temporary context and artifacts; preserve existing accepted Mac evidence.
2. With an attendee present and device/provider work explicitly scheduled, inspect the Windows privacy state and input/output choices. Device enumeration and input-format validation must be real in this phase. Let the attendee control any permission changes. Confirm the intended microphone and headphone output; never infer either from labels alone. Review the PR81 device controls on this exact consolidated commit.
3. Start once only after the attendee confirms readiness. Require capture active plus mandatory verified Updated ACK before the source is delivered; record content-free RMS/peak, append counts, protocol flags and stage timestamps. The attendee can speak one prepared public sentence if no reviewed Windows playback route exists. Do not adapt the Mac speaker script or change a global audio route automatically.
4. Verify actual captions and the attendee's hearing verdict, then one planned replay/mute operation and same-document Stop/export/NewSession restart. The second Start must reach the fixture gate without clicking a hidden enable button. A replacement document must require fresh trusted activation. Stop input immediately after each planned source; allow admitted work to finish, preserve export, and verify final reset and process/listener cleanup.
5. If live network interruption is authorized separately, disconnect/reconnect once under a reviewed controlled method. Check one owner, no duplicate source/caption, old epoch/clip retirement, preserved captions/export and fresh activation when the document changes. Without that action, record live interruption as untested.
6. Schedule a two-hour attended wall-clock session separately if requested. Define observations and a manual Stop procedure, not a new normal-session guard or retry loop. Record periodic content-free queue/task/resource and latency aggregates, planned source counts, export integrity and hearing judgments. A short generated/fake loop does not close this requirement.

Physical Windows microphone/privacy, WASAPI/other real host API, speaker/headphone routes, audibility, native process teardown, live provider/network recovery and two-hour endurance all remain open until their actual receipts exist.
