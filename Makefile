-include .env

HOST ?= 127.0.0.1
PORT ?= 8765

.PHONY: run dev smoke

run:
	uvicorn app.main:app --host $(HOST) --port $(PORT)

dev:
	uvicorn app.main:app --host $(HOST) --port $(PORT) --reload

smoke:
	python -m scripts.smoke_test
