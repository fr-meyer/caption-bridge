# CaptionBridge operations

## Responsibility split

- GCP OpenClaw is the canonical checkout, development environment, test runner, and orchestration point.
- The Mac is the runtime node for microphone capture, browser display, TTS playback, and final live validation.
- Do not run the live audio service on the GCP VM.
- Do not copy repository credentials or the Mac `.env` into GCP. Use a short-lived GitHub App or deploy credential scoped to this repository.

## GCP development bootstrap

```bash
sudo apt-get install -y python3.11-venv libportaudio2
git clone git@github.com:fr-meyer/caption-bridge.git
cd caption-bridge
uv sync --frozen
make check
```

The GCP host can run unit, lint, syntax, and server-startup checks. It cannot perform the microphone smoke test.

## Mac runtime preflight

1. Confirm the Mac node is connected to OpenClaw.
2. Confirm macOS microphone permission for the terminal or runtime process.
3. Confirm `MISTRAL_API_KEY` is present in the Mac-local `.env`.
4. Confirm TCP port 8765 is free.
5. Run `uv sync --frozen` after every lockfile change.
6. Run `make smoke` before an important live session.

## Manual lifecycle

Until GitHub issue #14 is implemented, lifecycle control remains explicit and on demand.

Start:

```bash
cd /path/to/caption-bridge
make run
```

Status:

```bash
curl --fail http://127.0.0.1:8765/
```

Stop with `Ctrl-C` in the owning terminal. Wait for the clean shutdown message before closing the terminal.

Do not create a LaunchAgent yet. The future OpenClaw `start`, `status`, and `stop` helpers must be idempotent, PID-aware, port-aware, and preserve graceful export/journal behavior.

## Failure response

| Symptom | Expected behavior | Operator action |
|---|---|---|
| Transcription close `1012` or transport interruption | Bounded reconnect with jitter and an in-browser notice | Wait for recovery; if exhausted, export and start a new session |
| Reconnect ceiling exhausted | Capture stops and the session remains exportable | Export, verify readiness, then create a new session |
| TTS `429` or `5xx` before playback | Bounded retry | No action unless retries exhaust |
| TTS failure after audio has started | No retry, preventing duplicate speech | Replay the caption manually if needed |
| TTS guardrail rejection | Caption remains visible; audio is skipped | Continue the session |
| Browser becomes slow | Partial/noncritical events may be coalesced or dropped; final state is prioritized | Refresh the browser if lag persists |

## Logs, journals, and retention

- Default logs must not include source captions, translations, credentials, provider bodies, or request payloads.
- Logs may include session identifiers, segment sequence numbers, text lengths, status codes, timing, queue depth, and failure class.
- `runs/.journal` and exported JSON contain transcript content.
- Keep transcript-bearing artifacts only as long as needed for the seminar or an explicitly consented, redacted quality corpus.
- Before sharing diagnostics, use aggregate metrics and remove transcript-bearing files.

## Release procedure

1. Develop and validate on a GCP `agent/*` or feature branch.
2. Run `uv sync --frozen` and `make check`.
3. Open a draft PR into `dev` and require CI.
4. After acceptance, merge into `dev`.
5. Open a release PR from `dev` to `main`.
6. Reconcile issues whose fixes were previously merged only into `dev`.
7. Tag the first stable mainline release only after a successful long-session Mac soak test.
