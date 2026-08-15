-include .env

HOST ?= 127.0.0.1
PORT ?= 8765
UV ?= uv
PYTHON ?= python3

.PHONY: run dev ctl-start ctl-status ctl-stop smoke setup test quality-benchmark segmentation-benchmark resilience-soak retention-preview lint check setup-conda

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

segmentation-benchmark:
	$(UV) run python -m scripts.benchmark_segmentation \
		--max-unexpected-standalone 0 --max-delayed-clear 0 \
		--max-policy-delay-ms 4500

resilience-soak:
	$(UV) run python -m scripts.resilience_soak --segments 1000

.PHONY: full-pipeline-scenario

full-pipeline-scenario:
	$(UV) run python -m scripts.full_pipeline_scenario --json

.PHONY: browser-setup browser-e2e

browser-setup:
	$(UV) run python -m playwright install chromium

browser-e2e:
	$(UV) run python -m pytest -q browser_tests --browser chromium

retention-preview:
	$(UV) run python -m scripts.prune_transcripts

lint:
	$(UV) run ruff check .

check: lint quality-benchmark segmentation-benchmark resilience-soak full-pipeline-scenario test
	node --check app/static/app.js

setup-conda:
	conda env create -f environment.yml
