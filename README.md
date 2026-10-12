# CaptionBridge

Mac-local live transcription, translation, captions, and optional spoken readback for seminars.

## Architecture and operating model

- The application runtime is Mac-local because microphone capture and macOS permission prompts must remain on the Mac.
- GCP OpenClaw is the canonical development and orchestration environment.
- The browser connects only to `http://127.0.0.1:8765` on the Mac.
- The service is started on demand. No LaunchAgent, login item, or automatic startup is installed.


## Prerequisites

- Python 3.11+
- PortAudio
- `uv` 0.12.x for locked development and CI

## Setup

1. Clone the repository:
   ```bash
   git clone git@github.com:fr-meyer/caption-bridge.git
   cd caption-bridge
   ```

2. Copy the environment template and fill in your API key:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set `MISTRAL_API_KEY` to your Mistral API key.

3. Install dependencies. The locked `uv` workflow is preferred:

```bash
# macOS
brew install portaudio

# Debian / Ubuntu development host
sudo apt-get install libportaudio2

uv sync --frozen
```

The pip and conda paths below remain compatibility options.

### Option A — pip (requires PortAudio)

PortAudio is needed by the `sounddevice` package. Install it first:

```bash
# macOS
brew install portaudio

# Debian / Ubuntu
sudo apt-get install libportaudio2
```

Then install Python dependencies:

```bash
pip install -r requirements.txt
```

### Option B — conda (PortAudio managed automatically)

Conda installs PortAudio as a transitive dependency of `python-sounddevice`,
so no manual system-level setup is required.

```bash
conda env create -f environment.yml
conda activate caption-bridge
```

## Run
Run the live service on the Mac that owns the microphone:

```bash
make ctl-start
make ctl-status
```

Then open [http://localhost:8765](http://localhost:8765) in your browser.

Stop it gracefully and confirm the final state:

```bash
make ctl-stop
make ctl-status
```

The controller uses only the repository-local `.venv`, refuses non-loopback
binding, verifies process identity before signalling, and emits content-free
human or JSON diagnostics. See [the Mac lifecycle runbook](docs/mac-lifecycle.md).

Install, upgrade, rollback, uninstall, and the content-free support bundle
are documented in [the Mac CLI runbook](docs/mac-cli.md). P1.4 is the
five-minute exact-candidate product path closed in
[issue #35](https://github.com/fr-meyer/caption-bridge/issues/35). A two-hour
run remains optional endurance evidence in [the Mac soak runbook](docs/mac-soak.md).

The GCP-only [Gemini Live Translate spike](docs/gemini-live-spike.md) records the
research decision and remaining evaluation; it does not change the default provider.

## Captions-only preference

Select **Captions only** before starting or in Settings during a session to keep
spoken readback off. The choice is saved in this browser and applies to future
sessions and page reloads. Turning it off allows spoken readback again; the browser
still requires **Enable audio** before speech can play. The speaker button provides
a temporary mute when captions-only mode is off.

Choose native microphone input before Start and browser spoken output in the idle
panel or Settings. Browser output selection depends on API/permission support;
[the audio-device guide](docs/audio-devices.md) explains defaults and fallback.

## Development

For auto-reload during development:

```bash
make dev
```

Run all repeatable development checks from the GCP checkout:

```bash
uv sync --frozen
uv run ruff check .
uv run python -m pytest -q
make quality-benchmark
make segmentation-benchmark
make resilience-soak
make full-pipeline-scenario
node --check app/static/app.js
```

Run the real-browser contracts separately after installing the repository-scoped
Chromium build:

```bash
make browser-setup
make browser-e2e
```

The quality benchmark uses only synthetic captions. It fails when detector recall
drops below 100%, the false-positive rate exceeds 5%, or expected reason labels
change. Runtime repair is separately hard-limited to at most one added provider
call per segment with `TRANSLATION_REPAIR_MAX_ATTEMPTS` (set it to `0` to disable).

The resilience soak injects deterministic timeouts and capacity failures into
1,000 synthetic segments. It fails on pending work, ordering gaps, duplicates,
unbounded provider calls, missing capacity notices, or missing source-only
degraded captions. It makes no network calls and prints aggregate counts only.

The full-pipeline scenario composes the production boundary, translation,
reconnection, TTS, WebSocket queue/replacement, journal, and export seams around
six synthetic segments. It makes no network or device calls, deletes its temporary
artifacts, and fails on ordering, retry-budget, snapshot, export, or task-leak
regressions. Its report contains only aggregate counts and booleans.

The browser suite serves the production HTML, CSS, and JavaScript from a
loopback-only synthetic WebSocket backend and drives it with headless Chromium.
It covers degraded captions/notices, reconnect snapshot restoration, audio
relocking, export/new-session controls, and keyboard lifecycle behavior without
microphones, provider calls, public listeners, or retained browser artifacts.

Each completed, failed-export, or explicitly discarded session also produces a
separate content-free reliability record under `runs/reliability/`. These records
contain only versioned aggregate counters, timestamps, durations, outcomes, and
queue peaks; transcript text, provider bodies, exception messages, prompts,
credentials, environment values, and export paths are excluded by an exact schema.
Review recent sessions, aggregate rates, and equal-window trends with:

```bash
make reliability-report
```

Deterministic history is opt-in so CI and normal checks retain no artifacts:

```bash
uv run python -m scripts.resilience_soak --segments 1000 \
  --record-history runs/reliability
uv run python -m scripts.full_pipeline_scenario \
  --record-history runs/reliability
```

The microphone smoke test must run on the Mac because the GCP server has no audio device:

```bash
uv run python -m scripts.smoke_test
```

## Captions-only mode

Choose **Captions only** before Start or in Settings to keep captions without
spoken readback. The choice persists across sessions and browser refresh. Use the
speaker control to turn speech back on. Transcription and translation can still
incur provider charges. See the [operator guide](docs/captions-only.md).

Optional [terminology preferences](docs/terminology.md) can guide technical terms.
Browser storage is opt-in; session exports include the terms used.
See the [public quality evaluation](docs/glossary-quality-evaluation.md) for
its offline checks and separately authorized live gate.

## Semantic fragment merging

Browser source partials remain immediate. Translation, export, and TTS finalization
use a stronger boundary: punctuation, a clear Korean formal/polite sentence ending,
or a bounded longer silence. Other Korean endings and short non-Korean fragments
are held and merged with later deltas when possible.

The deterministic `make segmentation-benchmark` gate uses ten synthetic cases.
Under defaults it requires immediate partial callbacks for all cases, zero
premature standalone fragments, zero delayed clear boundaries, exact merge and
forced-release outcomes, and a maximum policy boundary of 4500 ms: the 1500 ms
base pause plus at most 3000 ms additional hold.

The default additional hold budget is 3000 ms after the first
`PAUSE_TIMEOUT_MS` expiry. It cannot exceed 15000 ms. Tune
`FRAGMENT_MAX_HOLD_MS`, `FRAGMENT_MIN_CHARS`, and
`FRAGMENT_MIN_TOKENS` only with regression fixtures. Set
`FRAGMENT_MERGE_ENABLED=false` for the explicit legacy pause behavior.

## Outage behavior

- Realtime transcription retries provider restarts and transient transport failures with bounded exponential backoff and jitter.
- Retry exhaustion ends capture safely without discarding the session. Export it, start a new session, and retry.
- A translation timeout or exhausted capacity budget still delivers the source caption in sequence with a clear "translation unavailable" state; later captions continue.
- TTS retries transient provider failures only before any audio chunk has played, avoiding duplicated speech.
- Microphone, TTS, and browser outbound queues are hard-bounded. Disposable partial events may be coalesced or dropped before final captions and lifecycle events.

## Privacy and diagnostics

Default logs and reliability records contain sequence numbers or session IDs,
aggregate counts, lengths, timings, status codes, outcomes, and failure classes—not
caption text or provider response bodies. Session journals and transcript exports
still contain content and should follow the retention policy in `docs/operations.md`.

Preview aged transcript exports and archived journals without reading or deleting them:

```bash
make retention-preview
```

Deletion is never automatic. After reviewing the content-free counts, an operator
may run `uv run python -m scripts.prune_transcripts --apply`. The tool preserves
active journals, recent artifacts, symlinks, partial exports, and unexpected files.
