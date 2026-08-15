-include .env

HOST ?= 127.0.0.1
PORT ?= 8765
UV ?= uv

.PHONY: run dev smoke setup test lint check setup-conda

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

lint:
	$(UV) run ruff check .

check: lint test
	node --check app/static/app.js

setup-conda:
	conda env create -f environment.yml
