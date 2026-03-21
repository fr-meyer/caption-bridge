-include .env

HOST ?= 127.0.0.1
PORT ?= 8765

.PHONY: run dev

run:
	uvicorn app.main:app --host $(HOST) --port $(PORT)

dev:
	uvicorn app.main:app --host $(HOST) --port $(PORT) --reload
