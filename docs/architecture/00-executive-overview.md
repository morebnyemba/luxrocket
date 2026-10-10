# 00 — Executive Overview

## 1. Product summary

LUX ROCKET is an original, mobile-first, multiplayer **rocket-crash game** delivered as a **B2B game-supplier platform**. Licensed betting operators embed the game in their websites via an iframe. A single authoritative flight is shared by every player connected to the same *round stream*. The multiplier rises from 1.00× as the rocket travels from Earth through the Moon, Mars, Jupiter and Saturn into deep space, and ends at a crash point fixed — and cryptographically committed — before the round's betting window closes. Each player has two independent betting panels and may cash out each one manually or automatically before the crash.

LUX ROCKET never owns player identity or player funds. The operator authenticates the player, owns the wallet and enforces eligibility; LUX ROCKET runs the game, orchestrates game-side wallet transactions against the operator's wallet API, and keeps an auditable record of every bet, cash-out and settlement.

## 2. Repository findings (discovery, 2026-10-10)

| Check | Finding |
|-------|---------|
| Directory structure | Empty. Only `.git/`. |
| Commits | None. Branch `claude/vibrant-lovelace-hjv9fh` has no history; the remote has no branches. |
| Existing apps / manifests / migrations | None. |
| Auth, API, deployment, test conventions | None to preserve. |
| Secrets / config risks | None present. |
| Monorepo vs multi-repo | Undetermined → proposed monorepo (ADR-001). |
| Existing architecture docs | None. This package is the first. |

**Implications.** There is no code to preserve and no migration path to design. The flip side: there are **no existing conventions**, so this package must establish them (repo layout, lint/format, CI, branch protection, commit conventions), and nothing has been validated in production. All capacity numbers in this package are test targets, not claims.

Because the remote has no default branch, the first push establishes one. A pull request needs an existing base branch; see the review document for how this was handled.

## 3. Goals

1. A distinctive, fast, legible crash game that a first-time player understands in ~5 seconds on a mid-range Android phone over a 3G/4G connection.
2. Correctness over availability for money: no duplicate bets, no duplicate payouts, no unrecorded wins, no silently lost transactions.
3. A single authoritative outcome per round, fixed before betting closes and independently verifiable after the round.
4. Multi-operator from day one: one codebase, isolated tenant configuration, credentials, reporting and data.
5. Easy operator integration: one server-to-server session call, a seamless-wallet callback contract, an embed SDK, a sandbox.
6. Operable by a small team: few moving parts, Docker on Linux, no Kubernetes at launch.
7. Extensible to additional games without redesigning the platform (game is a pluggable module behind `Game`/`GameVersion`/`Ruleset`).

## 4. Non-goals (for the initial product)

- Player accounts, registration, KYC, payments, deposits/withdrawals — operator-owned.
- Transfer-wallet custody of player funds (rejected for v1, ADR-007).
- Chat, social features, tournaments, jackpots, bonuses/free bets (future; schema leaves room for free bets).
- Native mobile apps (the iframe works inside operator WebViews).
- Multi-region active-active deployment.
- Crypto currencies.
- Legal or regulatory sign-off. **This package is not legal advice or certification.**

## 5. Major constraints

| Constraint | Consequence |
|-----------|-------------|
| Operator owns identity & wallet | Every financial action is a remote call that can time out with an unknown result → idempotency + reconciliation everywhere (doc 08). |
| Shared global rounds | One process must own time for a round; all cut-off and cash-out decisions serialise through it (doc 06). |
| Mandated stack: Next.js / Django / Phoenix / Postgres / Redis / RabbitMQ | Two backend runtimes → the responsibility boundary is the #1 architectural risk; it is pinned by ADR-002/003. |
| Low-end Android, variable networks | Deterministic client-side curve rendering, small initial bundle, adaptive 3D quality (doc 14). |
| Southern-African target markets | Host in a Johannesburg cloud region for latency; data-protection and cross-border transfer law must be checked (OQ-03, OQ-04). |
| Real money gated | Sandbox (virtual credits) first; real money disabled per operator until commercial, regulatory, security and certification gates pass. |

## 6. Key decisions (summary — full ADRs in doc 03)

| ADR | Decision |
|-----|----------|
| ADR-002 | **Phoenix owns time and round facts** (betting cut-off, launch, crash, cash-out acceptance, bet admission). **Django owns money and business records** (sessions, operators, limits, wallet calls, ledger, settlement, reporting). |
| ADR-003 | Phoenix records every round decision in an append-only **round journal** (`rt` schema). Django never writes it; Phoenix never writes financial tables. The journal doubles as Phoenix's transactional outbox to Django. |
| ADR-004 | One coordinator per round stream, enforced by a **Postgres lease with a fencing token**; every journal write and Django call carries the token. |
| ADR-005 | **Void on malfunction**: a round interrupted by coordinator loss is voided; uncashed stakes are refunded, already-accepted cash-outs are paid. (Needs approval — OQ-10.) |
| ADR-006 | **Provably-fair hash chain** with a post-commitment public salt; crash point computed with exact integer arithmetic; target RTP = 1 − edge for every strategy. |
| ADR-007 | **Seamless wallet** (debit / credit / rollback) with a *rollback-on-doubt* rule for unknown debit outcomes. |
| ADR-009 | Iframe launch via **postMessage handshake** (primary) or **URL-fragment** one-time token (fallback). Never query-string tokens; never third-party cookies. |
| ADR-010 | Operator → platform requests signed with **Ed25519** (we store only public keys); platform → operator calls signed with a per-environment platform key. |
| ADR-012 | Clients render the multiplier curve **locally from the server's launch timestamp**; the server sends low-rate ticks for correction only. Crash point is never sent before the crash. |
| ADR-017 | Three **separately deployed** frontends (game, platform admin, operator portal) in one pnpm monorepo; the game is a static export on a CDN on its own origin. |
| ADR-018 | **PixiJS deferred**: HUD in accessible DOM, effects in Three.js. Two WebGL contexts on low-end Android is not justified yet. |
| ADR-019 | Tenant isolation by **scoped query layer + Postgres Row-Level Security** for operator-facing roles. |
| ADR-020 | Shared rounds are scoped to **round streams**; operators are assigned to streams (jurisdiction/certification boundaries). |

## 7. Where I pushed back on the brief

1. **"Django owns betting command orchestration"** conflicts with "Phoenix owns active-round coordination" unless split precisely. Resolution: Phoenix *admits* a bet into a round (time decision); Django *debits* it (money decision). Neither can do the other's job. See doc 02 §5 and the bet sequence in doc 08.
2. **`PLANET_REACHED` as a server event** is unnecessary fan-out: planet milestones are a pure function of the multiplier and a versioned journey map, so clients compute them. Removed from the wire protocol.
3. **PixiJS + Three.js** = two WebGL contexts and two render loops on devices we explicitly target. Deferred (ADR-018).
4. **Phoenix Presence for "players online"** broadcasts CRDT diffs per join/leave; at thousands of players that dominates traffic. Replaced by periodic aggregated counts.
5. **Single-use launch tokens in Redis** can be replayed after a Redis failover. Single-use enforcement lives in Postgres.
6. **"Globally shared rounds" across all operators** collides with per-jurisdiction certification. Rounds are shared *within a round stream*; the default is one stream per environment, but the model allows jurisdiction-specific streams.
7. **Operational load.** Postgres + Redis + RabbitMQ + Phoenix cluster + Django + workers + three frontends is a lot for a small team. Every component has a justified, narrow job (doc 02 §7); RabbitMQ is retained because it was mandated, but nothing correctness-critical depends on it being lossless (journal/outbox + reconciliation cover it).
8. **Markets: open to all, owner-gated (decided 2026-10-10).** No market is hard-coded in or out. Every country exists in a platform `market` registry; enabling one for sandbox or real money is an action only the platform owner (`PLAT_OWNER`, one account) can take. The platform does not decide legality — the owner does, per market, with evidence recorded (doc 15 §7, ADR-026). Legal risk in restricted markets (e.g. South Africa) is unchanged; it becomes the owner's explicit, audited decision rather than an architectural assumption.

## 8. What approval unlocks

Approval of doc 22 authorises **Phase B** (visual prototype on simulated flights and virtual credits) and the repo scaffolding in doc 19. It does **not** authorise real-money operation, which has its own gates (doc 19 §5).
