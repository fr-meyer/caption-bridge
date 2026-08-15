-include .env

HOST ?= 127.0.0.1
PORT ?= 8765
UV ?= uv

.PHONY: run dev smoke setup test quality-benchmark lint check setup-conda

run:
	$(UV) run uvicorn app.main:app --host $(HOST) --port $(PORT)

dev:
	$(UV) run uvicorn app.main:app --host $(HOST) --port $(PORT) --reload

smoke:
	$(UV) run python -m scripts.smoke_test

setup:
	$(UV) sync --frozen

test:
	$(UV) run python -m pytest -q

quality-benchmark:
	$(UV) run python -m scripts.benchmark_translation_quality \
		--max-false-positive-rate 0.05 --min-recall 1.0 --require-exact-reasons

lint:
	$(UV) run ruff check .

check: lint quality-benchmark test
	node --check app/static/app.js

setup-conda:
	conda env create -f environment.yml
