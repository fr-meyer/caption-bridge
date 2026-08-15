# Mac lifecycle control

This runbook defines the only supported remote lifecycle flow for Caption Bridge.
Development and automated testing stay on GCP. These commands run on the Mac
runtime node only when an operator intentionally requests a live session.

## Preconditions

- The Mac checkout is at the exact approved commit.
- `uv sync --frozen` has created the repository-local `.venv`.
- The Mac-local `.env` contains a non-empty `MISTRAL_API_KEY`.
- macOS has granted microphone access to the runtime process.
- `HOST` is unset or exactly `127.0.0.1`.
- The configured `PORT`, default 8765, is available.

The controller checks readiness without printing credential values, audio,
captions, translations, environment contents, or provider bodies.

## Commands

From the repository root:

```bash
make ctl-start
make ctl-status
make ctl-stop
make ctl-status
```

For automation, use the machine-readable form:

```bash
python3 -m scripts.caption_bridge_ctl start --json
python3 -m scripts.caption_bridge_ctl status --json
python3 -m scripts.caption_bridge_ctl stop --json
```

Start and stop are idempotent. Repeating start does not create another server.
Repeating stop does not signal anything. Status reports only state, health, PID,
loopback endpoint, and the local runtime/log paths.

## Safety model

The controller starts exactly:

```text
<repo>/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port <port>
```

Before sending SIGTERM, it rechecks the saved PID against the process start
token and exact argument vector, plus the repository root, virtual-environment
path, loopback host, and port. A stale file or reused PID is reported and never
signalled. Stop is graceful and bounded; it never escalates to SIGKILL.

State and logs live outside tracked source:

- `~/Library/Caches/CaptionBridge/runtime.json`
- `~/Library/Logs/CaptionBridge/caption-bridge.log`

Both files are owner-only (0600), and their parent directories are owner-only
(0700). No startup daemon, LaunchAgent, login item, public listener, or automatic
retention job is created.

## Recovery

| Status | Meaning | Safe action |
|---|---|---|
| `venv_missing` | `.venv/bin/python` is absent | Run `uv sync --frozen` |
| `venv_incomplete` | A locked dependency cannot import | Re-run `uv sync --frozen`; do not bypass the lock |
| `configuration_missing` | Required key name/value is absent | Repair the Mac-local `.env` without pasting it into logs |
| `microphone_unavailable` | No input device is visible | Connect/select an input device, then retry |
| `microphone_permission` | macOS denied opening the input | Grant Microphone permission, then retry |
| `non_loopback_refused` | HOST is not `127.0.0.1` | Correct HOST; never override this guard |
| `port_in_use` | Another process owns the port | Identify it independently; never kill it through this controller |
| `startup_failed` / `startup_timeout` | The owned process did not become healthy | Inspect the local log; then run status and stop |
| `stale_state` | State is corrupt or process identity differs | Do not signal the PID; start can replace stale state only after its own safety checks |
| `running_unhealthy` | Owned process lives but `/healthz` failed | Stop gracefully, inspect the log, then retry |
| `stop_timeout` | SIGTERM did not finish in the bounded window | Leave state intact and investigate before any manual action |

Never delete broad directories, kill a PID copied from the state file, or expose
the port beyond loopback as a recovery shortcut.
