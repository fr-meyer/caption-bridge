# CaptionBridge

Mac-local live transcription, translation, captions, and optional spoken readback for seminars.

## Architecture and operating model

- The application runtime is Mac-local because microphone capture and macOS permission prompts must remain on the Mac.
- GCP OpenClaw is the canonical development and orchestration environment.
- The browser connects only to `http://127.0.0.1:8765` on the Mac.
- The service is started on demand. Persistent LaunchAgent startup is intentionally deferred until the OpenClaw lifecycle controls are complete.


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
make run
```

Then open [http://localhost:8765](http://localhost:8765) in your browser.

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
node --check app/static/app.js
```

The quality benchmark uses only synthetic captions. It fails when detector recall
drops below 100%, the false-positive rate exceeds 5%, or expected reason labels
change. Runtime repair is separately hard-limited to at most one added provider
call per segment with `TRANSLATION_REPAIR_MAX_ATTEMPTS` (set it to `0` to disable).

The microphone smoke test must run on the Mac because the GCP server has no audio device:

```bash
uv run python -m scripts.smoke_test
```

## Outage behavior

- Realtime transcription retries provider restarts and transient transport failures with bounded exponential backoff and jitter.
- Retry exhaustion ends capture safely without discarding the session. Export it, start a new session, and retry.
- TTS retries transient provider failures only before any audio chunk has played, avoiding duplicated speech.
- Microphone, TTS, and browser outbound queues are hard-bounded. Disposable partial events may be coalesced or dropped before final captions and lifecycle events.

## Privacy and diagnostics

Default logs contain sequence numbers, lengths, timings, status codes, and failure classes—not caption text or provider response bodies. Session journals and exports still contain transcript content and should follow the retention policy in `docs/operations.md`.

Preview aged transcript exports and archived journals without reading or deleting them:

```bash
make retention-preview
```

Deletion is never automatic. After reviewing the content-free counts, an operator
may run `uv run python -m scripts.prune_transcripts --apply`. The tool preserves
active journals, recent artifacts, symlinks, partial exports, and unexpected files.
