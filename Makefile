# Developer entry points. Requires: uv, pnpm, Elixir/OTP (see README), Docker for `make up`.
SHELL := /bin/bash
.PHONY: help up down install generate vectors test test-backend test-realtime test-frontend lint images stack stack-down demo-launch invariants e2e

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
	docker build -f backend/Dockerfile -t luxrocket/backend:dev .
	docker build -t luxrocket/realtime:dev realtime
	docker build -f apps/game/Dockerfile -t luxrocket/game:dev .

COMPOSE := docker compose -f infra/compose/docker-compose.yml

stack: ## Build and run the full sandbox stack (game on :3000, API :8000, realtime :4000)
	@mkdir -p .demo
	@test -f .demo/seed.kek || head -c 32 /dev/urandom | base64 > .demo/seed.kek
	SEED_KEK_B64=$$(cat .demo/seed.kek) $(COMPOSE) --profile app up -d --build --wait api realtime game workers
	@for url in http://localhost:8000/healthz http://localhost:4000/healthz http://localhost:3000/launch; do \
	  for i in $$(seq 1 60); do curl -fs $$url >/dev/null && break; sleep 2; done; \
	  curl -fs $$url >/dev/null || { echo "$$url not healthy"; exit 1; }; done
	@echo "Stack ready. Get a launch link: make demo-launch  ·  embed demo: http://localhost:8000/demo/operator"

stack-down: ## Stop the full stack
	SEED_KEK_B64=x $(COMPOSE) --profile app down

demo-launch: ## Print a sandbox launch URL (acts as the operator; PLAYER=name)
	@cd backend && uv run python scripts/demo_operator.py --key $(or $(KEY),../.demo/operator.key) --player $(or $(PLAYER),demo-$$RANDOM)

invariants: ## Check money-correctness invariants against the database
	cd backend && DJANGO_DEBUG=1 uv run python manage.py check_invariants

e2e: ## Multi-browser end-to-end tests against a running stack
	cd e2e && npx playwright test
