-include .env

HOST ?= 127.0.0.1
PORT ?= 8765
UV ?= uv
PYTHON ?= python3

.PHONY: run dev ctl-start ctl-status ctl-stop identity preflight support-bundle smoke setup test quality-benchmark segmentation-benchmark resilience-soak retention-preview lint check setup-conda

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

identity:
	$(UV) run python -m app.identity --json

preflight:
	$(UV) run python -m scripts.runtime_preflight --software --json

support-bundle:
	$(UV) run python -m scripts.support_bundle --json

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

.PHONY: dependency-audit

dependency-audit:
	$(UV) audit --frozen --python-version 3.11 --python-platform linux
	$(UV) audit --frozen --python-version 3.12 --python-platform linux
	$(UV) audit --frozen --python-version 3.13 --python-platform linux
	$(UV) audit --frozen --python-version 3.11 --python-platform macos
	$(UV) audit --frozen --python-version 3.12 --python-platform macos
	$(UV) audit --frozen --python-version 3.13 --python-platform macos
	$(UV) audit --frozen --python-version 3.11 --python-platform windows
	$(UV) audit --frozen --python-version 3.12 --python-platform windows
	$(UV) audit --frozen --python-version 3.13 --python-platform windows

.PHONY: reliability-report

reliability-report:
	$(UV) run python -m scripts.reliability_report

retention-preview:
	$(UV) run python -m scripts.prune_transcripts

lint:
	$(UV) run ruff check .

check: lint quality-benchmark segmentation-benchmark resilience-soak full-pipeline-scenario test
	node --check app/static/app.js
	node --check app/static/audio-devices.js
	node --test tests/audio-devices.test.cjs

setup-conda:
	conda env create -f environment.yml
