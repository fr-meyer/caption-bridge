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

Use [`mac-cli.md`](mac-cli.md) for supported install, upgrade, rollback,
uninstall, and the content-free support bundle. Use [`mac-soak.md`](mac-soak.md)
only for optional two-hour endurance evidence.

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
| Initial transcription connection does not establish | Microphone activity is shown separately; the startup deadline stops capture and ends an exportable session without retrying | Export, then create a new session and retry manually |
| Transcription close `1012` or transport interruption | Bounded reconnect with jitter and an in-browser notice | Wait for recovery; if exhausted, export and start a new session |
| Reconnect ceiling exhausted | Capture stops and the session remains exportable | Export, verify readiness, then create a new session |
| TTS `429` or `5xx` before playback | Bounded retry | No action unless retries exhaust |
| TTS failure after audio has started | No retry, preventing duplicate speech | Replay the caption manually if needed |
| TTS guardrail rejection | Caption remains visible; audio is skipped | Continue the session |
| Browser becomes slow | Partial/noncritical events may be coalesced or dropped; final state is prioritized | Refresh the browser if lag persists |

The header and ASR notice show connecting, ready, or failed independently from
the session lifecycle. Wait for **transcription ready** before speaking or
playing a test clip. `listening` in the lifecycle snapshot alone does not prove
the provider handshake succeeded. Ready requires a typed `session.updated`
acknowledgment with the requested model, PCM encoding, and sample rate. An
explicitly supplied streaming delay must match; an omitted or null optional
delay stays unknown. Stop remains available while connecting.
`ASR_INITIAL_TIMEOUT_MS` defaults to 10000, accepts 100–60000, and bounds initial
provider establishment only; an established session has no automatic duration
limit. Ordinary bounded reconnect still applies after a verified handshake.
On Stop during setup, capture ends immediately; the SDK setup task settles under
its explicit transport/handshake timeouts, and any late connection is closed
without sending audio or changing session readiness.

Session snapshots expose `pipeline_diagnostics`, with aggregate capture chunks,
bytes, samples, frames, invalid chunks, normalized PCM RMS/peak, capture activity,
ASR connection state/reason, successful audio-append frames/bytes, and fixed event,
text-character, and error counts. Schema 6 adds a strict `protocol` object with
requested and acknowledged numeric/boolean settings, verification flags,
terminal text length/handling, and optional provider audio-usage seconds.
`input_flushed` and `input_ended` mean local SDK send completion; audio-append
counters likewise do not prove provider receipt or transcription. Unknown
acknowledged delay, terminal text length, and audio usage remain null. Reliability
schema 6 persists the same object under `pipeline`; history loading continues
to accept schemas 1–5 with their original exact fields. Counters never
retain raw PCM, transcript text, provider bodies, secrets, request identifiers,
or device identifiers. RMS/peak are null before any PCM samples arrive, numeric
zero for observed silence; old records keep diagnostics absent. Transcript export
and recovery provenance stay unchanged. Nonempty terminal-only text is admitted
through a distinct final-text callback before the detector flush; it does not
invent a provider delta. Once a nonempty delta was delivered, terminal aggregate
text cannot duplicate or rewrite those captions. Terminal text without a final
callback is classified `not_admitted`. Clean EOF without typed Done fails with
`closed_before_done` rather than announcing successful completion.

For explicitly controlled input validation, the `finish_input` WebSocket command
requires a verified ready session. It stops microphone capture, shows ASR
`draining`, and allows final source text, already admitted translations, and speech
to finish. It never starts a retry. Once final source text is flushed,
`finish_input_complete` emits only ASR state/reason, final `source_count`, and
`translation_pending_count`. This admission count lets an operator wait for all
captions and browser speech to complete before the ordinary Stop and Export.
This command is manual and does not add an automatic session cutoff. Ordinary
Stop retains its existing speech cancellation behavior.

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
- Run `make full-pipeline-scenario` on GCP before every PR. It deterministically
  composes the production boundary, translation, reconnect, TTS, WebSocket,
  journal, and export seams without microphones, browsers, provider calls, or
  retained artifacts. The gate requires exact terminal outcomes and retry counts,
  strict once-only delivery, bounded browser pressure, attached-owner protection,
  reconnect snapshot/audio behavior, exact export/journal completion, and zero
  owned tasks after teardown.
- Run `make browser-setup` once per GCP environment, then `make browser-e2e`
  before every PR that changes the frontend or WebSocket contract. The fixture
  binds only to `127.0.0.1`, serves the production browser assets, and uses fixed
  synthetic WebSocket events. It exercises a real headless Chromium document but
  does not start the production pipeline, access devices/providers, or retain
  traces, screenshots, transcripts, or temporary serving artifacts.

## Content-free reliability history

- Session reliability records live separately under `runs/reliability/` by
  default. Set `RELIABILITY_DIR` only to another local, operator-controlled path.
- Each exact-schema record contains timestamps, duration, terminal/export state,
  translation and repair counts, reconnect counts/downtime/outcome, and aggregate
  audio, TTS, and browser queue peaks/drops/skips. It excludes text, provider
  bodies, prompts, exception messages, credentials, environment values, and paths.
- Run `make reliability-report` for recent sessions, whole-history aggregates,
  and equal-window recent-versus-previous trends. The command scans only
  `session-*.json` and `soak-*.json` inside the reliability directory; it never
  opens transcript exports or journals.
- Malformed files and unknown schema versions are skipped with a count-only
  warning. Reliability recording failure is diagnostic-only and cannot turn a
  successful transcript export into a failed export.
- Deterministic gate history is never retained by `make check` or CI. Record it
  explicitly when establishing a local baseline with
  `--record-history runs/reliability` on `scripts.resilience_soak` or
  `scripts.full_pipeline_scenario`.
- The report shows observed rates and deltas, not pass/fail thresholds. Establish
  a stable baseline before proposing any alert or release gate.

## Logs, journals, and retention

- Default logs must not include source captions, translations, credentials, provider bodies, or request payloads.
- Logs may include session identifiers, segment sequence numbers, text lengths, status codes, timing, queue depth, and failure class.
- `runs/.journal` and exported JSON contain transcript content.
- Keep transcript-bearing artifacts only as long as needed for the seminar or an explicitly consented, redacted quality corpus.
- Before sharing diagnostics, use aggregate metrics and remove transcript-bearing files.
- Content-free reliability history may be shared independently after confirming
  the exact schema. It is not covered by transcript retention and is never uploaded
  automatically; deletion remains a manual operator choice.
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

## Dependency review cadence

Once a month, and again before a release, run this from an isolated GCP checkout:

```bash
uv sync --frozen
make dependency-audit
```

The target checks the locked dependencies against OSV for Python 3.11, 3.12,
and 3.13 using uv's generic `linux`, `macos`, and `windows` platform selectors.
These nine checks are a broad screen, not an audit of every architecture, Linux
libc variant, or environment-marker combination. `requires-python >=3.11,<3.14`
bounds interpreter versions only. Before a release, identify the actual deployment
targets and run additional
`uv audit --frozen --python-version <version> --python-platform <target>`
checks for their concrete platform triples. CI separately tests application
execution on its configured Python versions. The audit requires network access
and leaves `uv.lock` unchanged, so it is separate from deterministic `make check`.
Record the date, audited lockfile commit, exact Python/platform selectors,
package count, advisory IDs, and resolution in the project workboard.
A zero-finding result is a point-in-time
check, not a guarantee against later disclosures.

Review direct dependencies and the pinned GitHub Actions revisions at the same
cadence. Make any lockfile or action update on an isolated `agent/*` branch,
then run `make check` and `make browser-e2e` on GCP. Require CI and an exact-head
review before merging to `dev`; release promotion remains a separate decision.
Do not put credentials, provider responses, captions, or transcript content in
audit evidence.

## Release procedure

Policy clarification, October 25, 2026: following the owner's October 19
direction, physical device and listening tests are post-release, nonblocking
follow-ups for the supported Mac product. This supersedes older wording that
made those tests a prerequisite for promotion, including the timing of the
[Mac acceptance checklist](mac-acceptance.md). Existing acceptance records keep
their original exact-source scope. Required software checks, CI and source
review still apply; main/master promotion, tagging and installation retain their
separate requested scope.

1. Develop and validate on a GCP `agent/*` or feature branch.
2. Run `uv sync --frozen` and `make check`.
3. Open a draft PR into `dev` and require CI.
4. After required source review and software checks pass, merge into `dev`.
5. Open a release PR from `dev` to `main`.
6. Reconcile issues whose fixes were previously merged only into `dev`.
7. Promote or tag only the reviewed candidate after its required exact-commit
   software checks pass and that promotion or tag is separately authorized.
8. P1.4 is already closed by the exact-candidate five-minute run in issue #35.
   A two-hour run under [`mac-soak.md`](mac-soak.md) is optional, non-blocking
   endurance evidence. Record its content-free result only when that run is chosen.

## Browser connection ownership

The first attached browser owns control of the local session, including while
idle. New connections cannot replace it: they receive a `connection_lifecycle`
event with `state=rejected`, `reason=owner_active`, and close code 4409. Rejection
does not reset the owner's audio readiness, detach its listener, change session
state, or run commands. A true owner disconnect releases control, so ordinary
transport recovery can reconnect. Cleanup from an older connection cannot alter
the next owner's readiness or subscription.

The admitted browser receives `state=admitted`, `reason=owner_admitted`, and a
generated process-local `connection_id` such as `conn-000001`. Its initial and
later snapshots include the same descriptor under `connection_lifecycle`.
IDs and fixed lifecycle reason labels appear only in transient connection events
and content-free lifecycle logs; they never derive from client/device identifiers
or enter session journals, transcript exports, or reliability history.

A page closed with owner conflict 4409 or legacy code 1000/reason `replaced`
stays disconnected with an ownership notice. It stops local playback and automatic
reconnect; reload manually after the owning page disconnects to try again.
Ordinary transport failure still uses reconnect backoff without automatic Start.
Session commands and audio readiness restoration wait for an admitted snapshot.
