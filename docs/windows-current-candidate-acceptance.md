# Windows current-candidate acceptance packet

## Evidence classes, never interchangeable

- **Offline software**: guarded Python/Node contracts, injected media/providers,
  lifecycle state/ownership regressions. An off-Windows run is not native evidence.
- **Native Windows software**: the same suite plus an owned fake-app process,
  idle browser DOM and process/listener/profile cleanup on Windows. Start is never
  clicked. No native capture, playback, provider request or permission change.
- **Real Windows**: actual host API/input/output, permission, audibility and owned
  native-session closure. These remain open until an authorized attended run.
  The software fixture cannot close them, even when its CI job is green.

Current package: 0.6.0. The v050 filenames are retained compatibility names.
The previous [Windows result and limits](windows-0.5.0-offline-and-physical-plan.md)
remain bound to their original commit. Re-run software checks for the final
integrated candidate; an ancestor or sibling branch is not exact-head proof.

## Autonomous software procedure

1. Freeze the reviewed commit. Verify origin, HEAD, clean status and identical
   lock/manifest. Keep the accepted installation and controller state untouched.
2. Check actual Windows executor access first. Record OS/build/architecture,
   PowerShell 7, Python 3.11, Node, Git and existing Chromium availability without
   querying audio, displaying credentials or reading browser/account state.
   A connected but execution-denied node is an access gate, not missing hardware.
3. Use only a fresh temporary checkout and an existing compatible test environment.
   Never edit an accepted clone, install globally or reuse the seminar runtime.
   On CI, use the existing locked environment setup, without provider secrets.
4. Run the guarded suite. Its stdout includes real skip/xfail reasons. The receipt
   records HEAD, dirty state, a digest of actual software inputs, unchanged-source
   verification and zero native/provider calls. Software-input paths are app,
   scripts, tests, reliability checks, pyproject.toml and uv.lock. Digests bind
   working-tree bytes, not just the commit label; symlinks are not followed.
5. On Windows, run the existing fixture with free dedicated ports and a unique
   receipt destination outside source. Example, with paths supplied by the caller:

~~~powershell
$env:RUNNER_TEMP = $TemporaryRoot
pwsh -NoProfile -File scripts/windows_v050_software_acceptance.ps1 `
  -RepoRoot $IsolatedSource -ExpectedSha $ReviewedSha `
  -PythonPath $ExistingTestPython -ChromiumPath $ExistingChromium `
  -ReceiptPath (Join-Path $EvidenceRoot 'windows-software.json')
~~~

6. Accept only exit zero **and** final receipt status passed, matching exact SHA,
   source_dirty false, source_unchanged true, zero denied/native/provider calls,
   owned server/browser stopped, zero listeners and no temporary state/profile.
   Retain the content-free receipt and CI URL/source identity. Never upload raw
   server/browser logs, captions, provider bodies, device names or account paths.
   The optional receipt is written with CreateNew, not by replacing an old result.
7. Run the existing fresh-process headless import and receipt-metadata regressions
   separately; they intentionally launch isolated Python children and are not
   smuggled through the guarded runner's child-process allowlist:

~~~sh
python -B -m pytest -p no:cacheprovider -q -ra tests/unit/test_headless_audio_import.py tests/unit/test_offline_receipt_metadata.py
~~~

A skipped PowerShell parser or Windows lock test stays skipped, not passed. The
strict expected failure for the POSIX controller's Windows Python path remains
an acknowledged limitation, not an ordinary Windows lifecycle success. Do not
remove it, broaden process termination or ignore ownership tokens to make green.

## Recovery, including failed attempts

The fixture keeps only its own Process objects and unique runtime directory. It
stops owned browser/server process trees, verifies the two dedicated ports, then
removes its temporary state. It emits success only after that sequence. A failed
stage still produces the optional sanitized receipt after attempted cleanup.
Early argument/access failures may occur before a receipt can be created.

If cleanup fails, do not retry or kill processes by name/PID alone. Preserve the
private stage receipt, inspect the exact owned Process identity and dedicated
ports, and reconcile only that run. Never kill unrelated Chrome/Python or delete
accepted state. If residual runtime files cannot be removed safely, keep them
private and report their presence, not their content. Restore no global audio,
privacy, browser, environment or power settings: this procedure changes none.

## One consolidated owner packet: Windows leaves only

Prepare the following before requesting attended time. Include these leaves in
the programme's single owner handoff, not as unsolicited participant messages.

- **Executor access**: if genuinely denied, name the exact bounded software
  command and missing execution permission. Prefer existing current-head hosted
  Windows CI when eligible. No admin, credential change or new account required
  merely to report a software result. Do not call ordinary engineering owner-blocked.
- **Supported native ownership path**: the ordinary controller is POSIX-only.
  A reviewed Windows start/stop adapter must establish executable/argv and process
  creation identity, single owner, stale-PID refusal and verified owned closure.
  Until implemented and independently reviewed, do not offer native Windows use.
  This is engineering work, not a permission dialog the attendee can waive.
- **Attended device choice**: only after software/native-ownership prerequisites,
  request whether Windows is actually required, a quiet private window, the
  intended input/output, operator presence and permission-prompt control. A human
  must confirm the real route and hearing; labels/metadata are insufficient.
- **Capture authority and accounting**: reconcile all prior physical use against
  the original cumulative 600-second programme cap across devices, instruments,
  calibration, failures and retries. Unknown consumption is not free capacity.
  Request only the measured remaining programme need; no implicit renewed cap.
- **Safety**: before any provider-free physical observation, require network
  denial, single capture custody, a deadline/watchdog, emergency Stop and verified
  stream closure before/after. No Start while unattended. A participant ready
  signal is not authority for new providers, spend, route/default or OS changes.
- **Separate paid leaves**: any real ASR/TTS/network recovery needs the exact
  separately approved numeric budget and privacy/account route. Historical debt
  is retained. Physical provider-free checks do not authorize inference.

Record software, actual device facts and human verdicts separately. Keep Windows
physical and unsupported-controller criteria open if deferred; do not close an
issue or represent Mac delivery, mock tests or CI as Windows device acceptance.
Two-hour endurance is optional separately scoped work, not a new software gate.
