# CaptionBridge

Live English captions for Korean-language seminars.

## Prerequisites

- Python 3.11+

## Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/your-org/caption-bridge.git
   cd caption-bridge
   ```

2. Copy the environment template and fill in your API key:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set `MISTRAL_API_KEY` to your Mistral API key.

3. Install dependencies using **one** of the two options below:

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

```bash
make run
```

Then open [http://localhost:8765](http://localhost:8765) in your browser.

## Development

For auto-reload during development:

```bash
make dev
```
