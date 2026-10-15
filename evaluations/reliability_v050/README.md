# Bounded offline reliability checks

Use the existing project-compatible Python environment; no install or service starts here:

```sh
python -B evaluations/reliability_v050/run_offline.py --receipt-dir /tmp/caption-reliability-receipts
```

The runner denies native sounddevice APIs, outbound connections and unapproved child processes, disables saved dotenv loading, and permits only Git, Node and an optional PowerShell AST parser. It runs finite generated callback/SDK/PCM state checks, focused existing reliability/reconnect/Windows contracts, one existing full-pipeline case and the existing 250-segment injected-provider soak. Normal application budgets, defaults, routes and session lifetime are unchanged. On POSIX, the runner has a 15-second CPU-time limit; each Node/SDK loop also has a short explicit test timeout.

Reports identify actual skips and expected failures. The Windows lock-byte initialization test requires Windows; the PowerShell AST test requires an installed `pwsh`. The Mac/POSIX lifecycle's missing Windows Python path is an explicit expected-failure. No browser run, physical input/output, provider request, GCP operation or GitHub/hosted CI run is performed.

The source files and synthetic fixture counts are bounded. Do not interpret 64 callback cycles, 24 fake SDK connections or 512 fake PCM clips as elapsed two-hour endurance. The source module paths, versions, generated PCM hash and content-free cleanup counters are recorded separately from the physical Windows plan in `docs/windows-0.5.0-offline-and-physical-plan.md`.
