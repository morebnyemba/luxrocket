# Developer entry points. Requires: uv, pnpm, Elixir/OTP (see README), Docker for `make up`.
SHELL := /bin/bash
# Random per-checkout secrets for the local stack (git-ignored). Delete it and run
# `docker compose ... down -v` to rotate them.
STACK_ENV := .demo/stack.env
COMPOSE := docker compose -f infra/compose/docker-compose.yml
PHONY_DB := db-roles db-roles-check stack-env
.PHONY: $(PHONY_DB) help up down install generate vectors test test-backend test-realtime test-frontend lint images stack stack-seamless stack-down wallet-conformance reconcile demo-launch invariants e2e

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-16s %s\n", $$1, $$2}'

up: stack-env ## Start Postgres (and Redis/RabbitMQ with --profile infra)
	$(COMPOSE) up -d --wait postgres

down: ## Stop local dependencies
	$(COMPOSE) down

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
	docker build -f apps/portal/Dockerfile -t luxrocket/portal:dev .
	docker build -f apps/admin/Dockerfile -t luxrocket/admin:dev .

$(STACK_ENV): ## Random per-checkout secrets for the local stack (git-ignored)
	@mkdir -p .demo
	@{ echo "POSTGRES_DB=luxrocket"; echo "POSTGRES_USER=luxrocket"; \
	   echo "POSTGRES_PASSWORD=$$(openssl rand -hex 16)"; \
	   echo "RABBITMQ_DEFAULT_USER=luxrocket"; echo "RABBITMQ_DEFAULT_VHOST=luxrocket"; \
	   echo "RABBITMQ_DEFAULT_PASS=$$(openssl rand -hex 16)"; \
	   echo "DJANGO_SECRET_KEY=$$(openssl rand -hex 32)"; \
	   echo "SECRET_KEY_BASE=$$(openssl rand -hex 48)"; \
	   echo "INTERNAL_SERVICE_TOKEN=$$(openssl rand -hex 24)"; \
	   echo "SEED_KEK_B64=$$(openssl rand -base64 32)"; \
	   echo "PORTAL_DEMO_PASSWORD=$$(openssl rand -hex 12)"; \
	   echo "ADMIN_DEMO_PASSWORD=$$(openssl rand -hex 12)"; \
	   echo "PLATFORM_DB_PASSWORD=$$(openssl rand -hex 16)"; \
	   echo "REALTIME_DB_PASSWORD=$$(openssl rand -hex 16)"; } > $@
	@echo "wrote $@"

stack-env: $(STACK_ENV) ## Add secrets introduced since stack.env was generated
	@grep -q '^PORTAL_DEMO_PASSWORD=' $(STACK_ENV) || echo "PORTAL_DEMO_PASSWORD=$$(openssl rand -hex 12)" >> $(STACK_ENV)
	@grep -q '^ADMIN_DEMO_PASSWORD=' $(STACK_ENV) || echo "ADMIN_DEMO_PASSWORD=$$(openssl rand -hex 12)" >> $(STACK_ENV)
	@grep -q '^PLATFORM_DB_PASSWORD=' $(STACK_ENV) || echo "PLATFORM_DB_PASSWORD=$$(openssl rand -hex 16)" >> $(STACK_ENV)
	@grep -q '^REALTIME_DB_PASSWORD=' $(STACK_ENV) || echo "REALTIME_DB_PASSWORD=$$(openssl rand -hex 16)" >> $(STACK_ENV)

stack: stack-env ## Full sandbox stack (game :3000, portal :3002, console :3003, API :8000, realtime :4000)
	$(COMPOSE) --profile app up -d --build --wait api realtime game workers portal admin
	@for url in http://localhost:8000/healthz http://localhost:4000/healthz http://localhost:3000/launch http://localhost:3002/login http://localhost:3003/login; do \
	  for i in $$(seq 1 60); do curl -fs $$url >/dev/null && break; sleep 2; done; \
	  curl -fs $$url >/dev/null || { echo "$$url not healthy"; exit 1; }; done
	@echo "Stack ready. Get a launch link: make demo-launch  ·  embed demo: http://localhost:8000/demo/operator"
	@echo "Operator portal: http://localhost:3002  (demo-owner@luxrocket.local / PORTAL_DEMO_PASSWORD in $(STACK_ENV))"
	@echo "Platform console: http://localhost:3003 (owner@luxrocket.local / ADMIN_DEMO_PASSWORD; register a passkey at first sign-in)"

stack-seamless: stack-env ## Full stack with the demo operator on the reference Seamless Wallet v1 (signed HTTP)
	DEMO_WALLET_URL=http://wallet-sim:8090/wallet DEMO_WEBHOOK_URL=http://wallet-sim:8090/wallet/webhooks $(MAKE) stack
	$(COMPOSE) --profile app up -d wallet-sim

wallet-conformance: ## Run the Seamless Wallet v1 conformance suite (URL=..., default: the reference wallet)
	$(COMPOSE) --profile app exec api python manage.py wallet_conformance \
	  --base-url $(or $(URL),http://wallet-sim:8090/wallet) --player-id $(or $(PLAYER),conformance-$$RANDOM)

stack-down: ## Stop the full stack
	$(COMPOSE) --profile app down

demo-launch: ## Print a sandbox launch URL (acts as the operator; PLAYER=name)
	@cd backend && uv run python scripts/demo_operator.py --key $(or $(KEY),../.demo/operator.key) --player $(or $(PLAYER),demo-$$RANDOM)

reconcile: ## Run reconciliation now (internal + every seamless operator); fails if items are open
	$(COMPOSE) --profile app exec api python manage.py reconcile --internal --operator all

invariants: ## Check money-correctness invariants against the database
	cd backend && set -a && { [ -f ../$(STACK_ENV) ] && . ../$(STACK_ENV) || true; } && set +a && DJANGO_DEBUG=1 uv run python manage.py check_invariants

db-roles: ## Local single-user dev DB: create the portal RLS role (needs sudo/superuser psql)
	psql -v ON_ERROR_STOP=1 -d $(or $(DB),luxrocket) -v db=$(or $(DB),luxrocket) \
	  -v platform_user=$(or $(USER_DB),luxrocket) -v realtime_user=$(or $(USER_DB),luxrocket) \
	  -v portal_role=lr_portal -f infra/postgres/roles.sql

db-roles-check: ## Probe the per-service role boundaries (DB=, PLATFORM_PW=, REALTIME_PW=)
	DB=$(DB) PLATFORM_PW=$(PLATFORM_PW) REALTIME_PW=$(REALTIME_PW) infra/postgres/check-roles.sh

e2e: ## Multi-browser end-to-end tests against a running stack
	cd e2e && npx playwright test
