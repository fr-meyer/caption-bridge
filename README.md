# CaptionBridge

Live English captions for Korean-language seminars.

## Prerequisites

- Python 3.11+
- pip

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

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
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
