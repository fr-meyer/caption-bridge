-include .env

HOST ?= 127.0.0.1
PORT ?= 8765
UV ?= uv
PYTHON ?= python3

.PHONY: run dev ctl-start ctl-status ctl-stop smoke setup test quality-benchmark retention-preview lint check setup-conda

run:
	$(UV) run uvicorn app.main:app --host $(HOST) --port $(PORT)

dev:
	$(UV) run uvicorn app.main:app --host $(HOST) --port $(PORT) --reload

ctl-start:
	$(PYTHON) -m scripts.caption_bridge_ctl start

ctl-status:
	$(PYTHON) -m scripts.caption_bridge_ctl status

ctl-stop:
	$(PYTHON) -m scripts.caption_bridge_ctl stop

smoke:
	$(UV) run python -m scripts.smoke_test

setup:
	$(UV) sync --frozen

test:
	$(UV) run python -m pytest -q

quality-benchmark:
	$(UV) run python -m scripts.benchmark_translation_quality \
		--max-false-positive-rate 0.05 --min-recall 1.0 --require-exact-reasons

retention-preview:
	$(UV) run python -m scripts.prune_transcripts

lint:
	$(UV) run ruff check .

check: lint quality-benchmark test
	node --check app/static/app.js

setup-conda:
	conda env create -f environment.yml
