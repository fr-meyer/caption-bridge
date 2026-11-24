# Bounded offline reliability checks

Use the existing project-compatible Python environment; no install or service starts here:

```sh
python -B evaluations/reliability_v050/run_offline.py --receipt-dir /tmp/caption-reliability-receipts
```

The runner denies native sounddevice APIs, outbound connections and unapproved child processes, disables saved dotenv loading, and permits only Git, Node and an optional PowerShell AST parser. It runs finite generated callback/SDK/PCM state checks, focused existing reliability/reconnect/Windows contracts, one existing full-pipeline case and the existing 250-segment injected-provider soak. Normal application budgets, defaults, routes and session lifetime are unchanged. On POSIX, the runner has a 15-second CPU-time limit; each Node/SDK loop also has a short explicit test timeout.

Reports identify actual skips and expected failures, with reasons in the `-ra` summary.
Receipts now bind HEAD, clean/dirty state, actual software-input bytes (including
untracked candidate source), and unchanged-source verification across the run.
A byte change fails the result even when pytest succeeds. Source symlinks are
hashed as links without reading their targets. The added lifecycle regressions
exercise fake process/state ownership and idempotence, not native process control.
See [the current-candidate packet](../../docs/windows-current-candidate-acceptance.md)
for native software execution, sanitized receipt retention and recovery.

The Windows lock-byte initialization test requires Windows; the PowerShell AST test requires an installed `pwsh`. The Mac/POSIX lifecycle's missing Windows Python path is an explicit expected-failure. No browser run, physical input/output, provider request, GCP operation or GitHub/hosted CI run is performed.

The source files and synthetic fixture counts are bounded. Do not interpret 64 callback cycles, 24 fake SDK connections or 512 fake PCM clips as elapsed two-hour endurance. The source module paths, versions, generated PCM hash and content-free cleanup counters are recorded separately from the physical Windows plan in `docs/windows-0.5.0-offline-and-physical-plan.md`.

The ordinary Ubuntu CI already runs these contracts. The separate
`.github/workflows/windows-v0.5.0-software.yml` runs the native Windows fixture
on pull requests and main/dev pushes, with exact-SHA manual dispatch retained.
PR evidence records GitHub's synthetic merge SHA, not the PR head.
It reuses these tests rather than adding another set of simulated platform
checks. Hosted Python/dependency setup and any dispatch require separately
authorized execution; the workflow's existence is not a Windows pass.
Physical device/listening and endurance checks are post-release, nonblocking
follow-ups. Neither the local runner nor this prepared job changes normal
Medium use, starts native audio or calls a provider.


## Windows asyncio IPC in the software harness

`scripts/software_network_guard.py` keeps public TCP connect/connect_ex,
UDP sendto (and sendmsg where available), bind and DNS resolution denied.
On Windows, where CPython3.11 has no native socketpair, its replacement
constructs a private IPv4 pair using a fresh owned loopback listener. The
connection destination is derived exclusively from that listener; both peer
endpoints are checked and the temporary listener is closed. It never relaxes
the global connection guard, including during pair construction.

The fixture server receives a prebound guard-owned loopback socket. Only that
registered socket, with matching descriptor and bound address, may listen;
other sockets cannot bind/listen/connect even to that port. The fixture uses
stdlib asyncio for consistent software coverage. Explicit repository-path
bootstrap supports direct execution by the PowerShell harness. Real audio and
provider clients remain disabled, and the application runtime is unchanged.

The guard regressions force the Windows-style fallback on the local test host
and exercise bidirectional IPC, event-loop/server startup, closed listeners,
and denied external/unowned loopback, datagram and DNS operations. This is
source/fixture evidence. Native Windows execution is now recorded by
[run40164259241](https://github.com/fr-meyer/caption-bridge/actions/runs/40164259241)
at `a912ea2f73630dba9c0205e6a33988f3add8c164`: four headless/report tests,
47 offline tests, one known expected failure, and owned fake-app/browser
teardown passed. That historical aggregate changed only documentation;
this statement does not bind later 0.6.0 harness/test changes to that native pass. See the [source binding and coverage limits](../../docs/release-delta-after-v0.5.0-2026-10-25.md).
`owned_fallback_ipc_pairs` is a content-free count, not hardware acceptance.
The three fresh-process headless import regressions use the same guard so
missing-device/backend behavior can also be tested on Windows.

Receipt generation reads the host family from `sys.platform`; it does not
probe the Windows OS version or authorize another child process. A separate
fresh-process receipt regression keeps the real IO guards installed and
rejects any OS-version probe while stubbing suite execution. That regression
does not count its stub as a test-suite pass.
