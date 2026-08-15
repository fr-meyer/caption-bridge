# CaptionBridge operations

## Responsibility split

- GCP OpenClaw is the canonical checkout, development environment, test runner, and orchestration point.
- The Mac is the runtime node for microphone capture, browser display, TTS playback, and final live validation.
- Do not run the live audio service on the GCP VM.
- Do not copy repository credentials or the Mac `.env` into GCP. Use a short-lived GitHub App or deploy credential scoped to this repository.

## GCP development bootstrap

```bash
sudo apt-get install -y make python3.11-venv libportaudio2
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

Use [`mac-acceptance.md`](mac-acceptance.md) for the complete content-free
candidate-release checklist.

## Safe on-demand lifecycle

The repository-owned controller is the supported OpenClaw control surface. It
does not install persistent services, a LaunchAgent, login item, cron entry, or
automatic cleanup.

Start:

```bash
cd /path/to/caption-bridge
make ctl-start
```

Status:

```bash
make ctl-status
```

Stop and verify:

```bash
make ctl-stop
make ctl-status
```

Add `--json` to the underlying command for automation:

```bash
python3 -m scripts.caption_bridge_ctl status --json
```

Exit code 0 means the requested state is satisfied, including repeated start or
stop. Code 2 identifies environment, configuration, microphone, or loopback
preflight failure; 3 identifies stale or mismatched runtime identity; 4 means
the port is occupied; 5 is startup or health failure; and 6 is graceful-stop
failure.

The controller checks the Mac-local `.env` only for the required key's
presence. It never prints values. Runtime state is mode 0600 under
`~/Library/Caches/CaptionBridge/runtime.json`; the mode-0600 log is under
`~/Library/Logs/CaptionBridge/caption-bridge.log`. A stop signal is sent only
after PID, process start token, exact argument vector, repository, virtual
environment, host, and port all match the saved state.

See [`mac-lifecycle.md`](mac-lifecycle.md) for recovery guidance.

## Failure response

| Symptom | Expected behavior | Operator action |
|---|---|---|
| Transcription close `1012` or transport interruption | Bounded reconnect with jitter and an in-browser notice | Wait for recovery; if exhausted, export and start a new session |
| Reconnect ceiling exhausted | Capture stops and the session remains exportable | Export, verify readiness, then create a new session |
| TTS `429` or `5xx` before playback | Bounded retry | No action unless retries exhaust |
| TTS failure after audio has started | No retry, preventing duplicate speech | Replay the caption manually if needed |
| TTS guardrail rejection | Caption remains visible; audio is skipped | Continue the session |
| Browser becomes slow | Partial/noncritical events may be coalesced or dropped; final state is prioritized | Refresh the browser if lag persists |

## Semantic fragment boundaries

- Run `make segmentation-benchmark` on GCP before every PR. Its ten synthetic
  cases require immediate partial callbacks, zero premature standalone fragments,
  zero delayed clear boundaries, exact merge/forced-release behavior, and a
  default maximum policy boundary of 4500 ms. Output is aggregate and content-free.
- Browser `source_partial` events are emitted on every transcription delta and
  remain independent from translation-ready finalization.
- Punctuation finalizes immediately. At a punctuation-free pause, clear Korean
  formal/polite sentence endings finalize normally; other Hangul endings wait
  for more speech or the bounded longer-silence ceiling.
- Short non-Korean fragments also wait for more speech. Long non-Korean clauses
  preserve the ordinary pause-timeout behavior.
- `FRAGMENT_MERGE_ENABLED` defaults to `true`.
- `FRAGMENT_MAX_HOLD_MS` defaults to 3000 and is bounded to 0–15000. This is
  an additional budget after the first `PAUSE_TIMEOUT_MS` expiry; reaching it
  always finalizes, preventing an indefinite caption stall.
- `FRAGMENT_MIN_CHARS` defaults to 15 (bounded 1–500) and
  `FRAGMENT_MIN_TOKENS` defaults to 3 (bounded 1–50).
- Deferral logs contain only a reason label and character count, never caption
  text. Reconnect and normal-stop draining still flush held text explicitly.
- Treat these expressions as conservative streaming heuristics, not full Korean
  morphological analysis. Add synthetic Korean regressions before changing the
  recognized sentence-ending set.

## Translation quality monitoring

- Run `make quality-benchmark` on GCP before every PR. The fixture is synthetic
  and the report contains only counts, rates, reason labels, and mismatched case IDs.
- Each segment records its initial and final quality flags, repair-call count,
  repair outcome, and repair latency. Repair is hard-limited to zero or one attempt
  through `TRANSLATION_REPAIR_MAX_ATTEMPTS`.
- Session snapshots and JSON exports include aggregate checked, initially flagged,
  repaired, repair-success, still-flagged, per-reason, and latency metrics.
- Run `uv run python -m scripts.analyze_exports` from the repository root to
  compare exported runs without printing source or translated caption text.
- Treat an increasing still-flagged rate, repair latency, or a new dominant reason
  as a release investigation signal. Do not weaken a detector without adding a
  representative synthetic regression case.

## Resilience fault injection

- Run `make resilience-soak` on GCP before every PR. It uses the injected
  translation-provider seam and never calls a real provider.
- The default 1,000-segment schedule includes successes, per-segment timeouts,
  429s that recover within budget, and 429s that exhaust the exact budget.
- The gate requires every segment to reach a terminal state, strict once-only
  delivery order, source-only degraded captions for failures, exact bounded
  provider-call counts, capacity warning counts, and zero remaining tasks.
- `TRANSLATION_DRAIN_TIMEOUT_MS` defaults to 30000 and bounds graceful
  settlement independently from the per-attempt `TRANSLATION_TIMEOUT_MS`.
- `TRANSLATION_MAX_CONCURRENCY` defaults to 8 and hard-bounds simultaneous
  translation and repair calls. The soak records the observed provider peak
  and fails if it exceeds the configured ceiling.
- `TRANSLATION_PROVIDER=mistral` is the only production value. Other providers,
  including the Gemini Live Translate spike in issue #13, require explicit
  implementation, opt-in configuration, privacy review, and Mac smoke coverage.

## Logs, journals, and retention

- Default logs must not include source captions, translations, credentials, provider bodies, or request payloads.
- Logs may include session identifiers, segment sequence numbers, text lengths, status codes, timing, queue depth, and failure class.
- `runs/.journal` and exported JSON contain transcript content.
- Keep transcript-bearing artifacts only as long as needed for the seminar or an explicitly consented, redacted quality corpus.
- Before sharing diagnostics, use aggregate metrics and remove transcript-bearing files.
- `TRANSCRIPT_RETENTION_DAYS` defaults to 30 days and controls only the manual
  retention tool; it does not install or enable automatic cleanup.
- Preview eligible timestamped exports and archived journals with
  `make retention-preview`. The scanner reads file names, sizes, and modification
  times only. Its output contains counts and byte totals, not transcript text or paths.
- After reviewing the preview, apply the same policy explicitly with
  `uv run python -m scripts.prune_transcripts --apply`.
- The tool never removes live journals. It refuses broad roots and symlinks, and
  preserves partial export directories or directories containing unexpected files.
  It deletes exact known files individually and removes a timestamp directory only
  after that directory is empty.
- Do not schedule retention with cron or a LaunchAgent until the Mac lifecycle and
  operator policy are separately reviewed and approved.

## Release procedure

1. Develop and validate on a GCP `agent/*` or feature branch.
2. Run `uv sync --frozen` and `make check`.
3. Open a draft PR into `dev` and require CI.
4. After acceptance, merge into `dev`.
5. Open a release PR from `dev` to `main`.
6. Reconcile issues whose fixes were previously merged only into `dev`.
7. Tag the first stable mainline release only after a successful long-session Mac soak test.
