# Developer entry points. Requires: uv, pnpm, Elixir/OTP (see README), Docker for `make up`.
SHELL := /bin/bash
.PHONY: help up down install generate vectors test test-backend test-realtime test-frontend lint images

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-16s %s\n", $$1, $$2}'

up: ## Start Postgres, Redis, RabbitMQ
	docker compose -f infra/compose/docker-compose.yml up -d --wait

down: ## Stop local dependencies
	docker compose -f infra/compose/docker-compose.yml down

install: ## Install all dependencies
	cd backend && uv sync
	cd realtime && mix deps.get
	pnpm install

generate: ## Regenerate protocol types from contracts/
	pnpm --filter @luxrocket/protocol generate

vectors: ## Regenerate LR-CRASH-1 known-answer vectors from the Python reference
	cd backend && uv run python scripts/gen_vectors.py

test-backend: ## Django lint, types, tests, vector check
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy \
	  && uv run python scripts/gen_vectors.py --check && uv run pytest

test-realtime: ## Phoenix format, compile, tests
	cd realtime && mix format --check-formatted && mix compile --warnings-as-errors && mix test

test-frontend: ## Typecheck, lint, test, build all JS packages
	pnpm --filter @luxrocket/protocol check-generated && pnpm turbo run typecheck lint test build

test: test-backend test-realtime test-frontend ## Everything CI runs (except image builds)

images: ## Build service images
	docker build -t luxrocket/backend:dev backend
	docker build -t luxrocket/realtime:dev realtime
