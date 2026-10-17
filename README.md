# LUX ROCKET

Embeddable, multiplayer rocket-crash game and B2B game-supplier platform.

> **Status:** sandbox mode works end to end — operator launch, shared real-time rounds,
> two-panel betting, cash-outs, wallet settlement and in-browser verification. See
> [implementation status](docs/architecture/23-implementation-status.md). Nothing here is
> certified, and real-money operation is disabled by design until its gates pass.

Start with [`docs/architecture/`](docs/architecture/README.md) — every design decision lives
there, and code must not contradict an accepted ADR.

## Layout

| Path | What | Stack |
|------|------|-------|
| `apps/game` | Embedded player game (static export, CDN) | Next.js, React, TS |
| `apps/admin` | Platform admin console | Next.js |
| `apps/portal` | Operator portal | Next.js |
| `packages/game-core` | Shared game math & state (client side, display only) | TS |
| `packages/protocol` | Types generated from `contracts/` | TS |
| `backend` | Business platform: operators, sessions, wallet, ledger, APIs | Django, DRF, Postgres |
| `realtime` | WebSockets and authoritative round coordination | Elixir, Phoenix |
| `contracts` | JSON Schemas + math known-answer vectors (source of truth) | — |
| `infra` | Local Compose stack | Docker |

The crash formula (`LR-CRASH-1`) is implemented three times — Python (reference), Elixir
(authoritative at runtime) and TypeScript (player-side verification) — and all three are
tested against `contracts/math/lr-crash-1/vectors.json`.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node 22 and pnpm 10
- Erlang/OTP 27 and Elixir 1.18
- Docker (for Postgres, Redis, RabbitMQ)

## Run the full sandbox (Docker)

```bash
make stack          # builds and starts Postgres, Django API + workers, Phoenix, the game
make demo-launch    # acts as an operator: prints a signed-session launch link — open it
```

Or open `http://localhost:8000/demo/operator` to see the game embedded through the operator
SDK (postMessage handshake). `make e2e` runs the multi-browser tests, `make invariants` checks
the ledger. Back-office (read-only): `http://localhost:8000/django-admin/` after
`docker compose -f infra/compose/docker-compose.yml exec api python manage.py createsuperuser`.

## Develop locally

```bash
cp .env.example .env
make up        # Postgres, Redis, RabbitMQ
make install   # uv sync, mix deps.get, pnpm install
make test      # everything CI runs
```

The operator portal runs its queries under Postgres row-level security as the NOLOGIN role
`lr_portal` (ADR-019). A superuser database user creates it automatically on `migrate`; with a
non-superuser local user, run `sudo -u postgres make db-roles` once.

Run services locally:

```bash
cd backend && DJANGO_DEBUG=1 uv run python manage.py runserver   # http://localhost:8000/healthz
cd realtime && mix phx.server                                     # http://localhost:4000/healthz
pnpm --filter @luxrocket/game dev                                 # http://localhost:3000
```

`make help` lists all targets.

## Conventions

- Money: integer minor units (strings in JSON). Multipliers: integers in ten-thousandths.
- Contracts first: change `contracts/`, then `make generate` / `make vectors`.
- No secrets in the repo; `.env` is git-ignored. CI runs a secret scan.
- Changes to money and outcome code need owner review (`.github/CODEOWNERS`).
