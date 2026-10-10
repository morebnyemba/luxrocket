# 03 — Architecture Decision Register

Status values: **Proposed** (awaiting approval), **Accepted**, **Superseded**, **Rejected**.
All ADRs below are **Proposed** until doc 22 is approved. Later implementation work MUST NOT contradict an Accepted ADR without a superseding ADR.

## Register

| ADR | Title | Status | Approval sensitivity |
|-----|-------|--------|----------------------|
| ADR-001 | Monorepo with separately deployable apps | Proposed | Low |
| ADR-002 | Phoenix owns time & round facts; Django owns money & business records | Proposed | **High** |
| ADR-003 | Phoenix round journal as append-only fact log and outbox | Proposed | High |
| ADR-004 | Coordinator ownership via Postgres lease + fencing token | Proposed | High |
| ADR-005 | Void-on-malfunction for interrupted rounds | Proposed | **High (regulatory/commercial)** |
| ADR-006 | Hash-chain provably-fair outcome with post-commitment public salt | Proposed | **High (certification)** |
| ADR-007 | Seamless wallet with rollback-on-doubt | Proposed | **High (commercial)** |
| ADR-008 | Integer money and integer multipliers | Proposed | Medium |
| ADR-009 | postMessage launch handshake + fragment fallback | Proposed | High |
| ADR-010 | Ed25519 request signing for operator API | Proposed | Medium |
| ADR-011 | Bet & cash-out commands over WebSocket; everything else HTTPS | Proposed | Medium |
| ADR-012 | Deterministic client-side curve; low-rate server ticks | Proposed | Medium |
| ADR-013 | Phoenix.PubSub on distributed Erlang (not Redis) | Proposed | Low |
| ADR-014 | Redis is never authoritative | Proposed | Medium |
| ADR-015 | Transactional outbox + RabbitMQ with idempotent consumers | Proposed | Medium |
| ADR-016 | Django ASGI internal API + asyncio wallet-worker (aiohttp); Celery for scheduled jobs | Proposed | Medium |
| ADR-017 | Three separate frontends; game as static export on its own origin | Proposed | Medium |
| ADR-018 | Defer PixiJS; DOM HUD + Three.js effects | Proposed | Low |
| ADR-019 | Tenant isolation: scoped repositories + Postgres RLS | Proposed | High |
| ADR-020 | One global round sequence per environment | **Accepted** (product owner, 2026-10-10) | High |
| ADR-025 | Player-sharded cash-out arbitration under one global lease | Proposed | High |
| ADR-021 | Docker on Linux VMs, no Kubernetes at launch; Johannesburg region | Proposed | Medium |
| ADR-022 | Short-lived signed game-session tokens + single-use WS tickets | Proposed | High |
| ADR-023 | No FX in platform; per-currency limits | Proposed | Low |
| ADR-024 | Bet admission journaled; debit is not inclusion | Proposed | High |

---

## ADR-001 — Monorepo with separately deployable apps
**Context.** Empty repo; three frontends, one Django codebase, one Phoenix app, shared protocol contracts.
**Decision.** Single repository:
```
/apps/game        Next.js (static export)
/apps/admin       Next.js
/apps/portal      Next.js
/packages/ui      shared shadcn/ui components + design tokens
/packages/protocol  versioned WS + HTTP contract types (generated from JSON Schema)
/packages/sdk     operator embed SDK (tiny, framework-free)
/backend          Django project (apps per doc 05)
/realtime         Elixir umbrella-free Phoenix app
/contracts        JSON Schemas + OpenAPI (source of truth for generated types)
/infra            Docker, compose files, proxy config, dashboards
/docs             this package
```
**Alternatives.** Multi-repo (rejected: contract drift between Django, Phoenix and frontend is the top integration risk; one PR must be able to change a contract and all its consumers). One Next.js app for all three UIs (rejected, see ADR-017).
**Consequences.** CI must use path filters. Contracts in `/contracts` are the single source; TS types, Python (pydantic/DRF serializers tests) and Elixir validators are generated or contract-tested against them.

## ADR-002 — Responsibility boundary
**Context.** Brief assigns "betting command orchestration" to Django and "active-round coordination" to Phoenix. Without a precise split, both would decide whether a bet or cash-out "counts".
**Decision.** Phoenix decides everything that depends on *round time*: cut-off, admission, launch, cash-out acceptance, crash, void. Django decides everything that depends on *money or business policy*: session validity, limits, exposure, debit, credit, ledger, settlement. The decisions are sequential, never concurrent, on the same fact (table in doc 02 §5).
**Alternatives.**
- *Django owns rounds, Phoenix is a dumb fan-out*: every cash-out becomes an HTTP call plus a DB lock on the round in Django; cash-out vs crash serialisation moves to Postgres row locks under burst load (auto cash-out clusters). Rejected: worse latency and contention for the hottest path.
- *Phoenix owns everything including wallet calls*: technically attractive (BEAM handles concurrent outbound HTTP well) but duplicates business logic and violates the mandated stack boundary. Kept as a fallback if bet-path latency fails NFR-003 (revisit after load test).
**Consequences.** One synchronous dependency Phoenix → Django on the bet path (must be fast and isolated: dedicated `django-internal` pool). Cash-out path has **no** synchronous dependency on Django.

## ADR-003 — Round journal
**Decision.** Phoenix appends every round fact to `rt.round_journal` (stream_id, round_id, journal_seq, event_type, payload, fencing_token, created_at). Writes are batched per 10–20 ms and committed before player acknowledgement. A relay publishes journal entries to RabbitMQ with publisher confirms and records `relayed_at`. Django consumes idempotently.
**Alternatives.** Phoenix calls Django per cash-out (rejected: couples cash-out latency/availability to Django); Phoenix writes `platform.bet` directly (rejected: two writers of financial records).
**Consequences.** Django's view of a round is eventually consistent (target lag p99 < 1 s). Reconciliation compares journal vs ledger.

## ADR-004 — Lease + fencing
**Decision.** Table `rt.stream_lease(stream_id PK, holder, fencing_token BIGINT, expires_at)`. Acquisition: `UPDATE … SET holder=$me, fencing_token=fencing_token+1, expires_at=now()+ttl WHERE stream_id=$s AND (expires_at < now() OR holder=$me) RETURNING fencing_token`. TTL 6 s, renewed every 2 s. Every journal insert is conditional on the current token (single SQL statement joins the lease row). Every call to Django carries the token; Django rejects tokens lower than the highest seen for that stream.
**Alternatives.** `:global` / Horde / Swarm registration (rejected as sole mechanism: during a network partition two nodes can each believe they own a name). Redis Redlock (rejected: not safe without fencing, and Redis is not authoritative per ADR-014). Raft (`ra`) (rejected for now: operational complexity; Postgres is already the source of truth).
**Consequences.** A coordinator that loses its lease cannot write a single journal entry, so it cannot produce a conflicting outcome. Failover time ≈ lease TTL (≤ 6 s) plus recovery.

## ADR-005 — Void on malfunction
**Decision.** If a coordinator loses its lease while a round is in `BETTING_OPEN`, `BETTING_CLOSED` or `FLYING`, the new coordinator journals `ROUND_VOIDED(reason=COORDINATOR_FAILOVER)`. Cash-outs already journaled are paid; all other admitted bets are refunded. The seed is still revealed. Planned deploys hand over at round boundaries and never void.
**Alternatives.** *Resume the deterministic timeline* (possible because flight = f(launch_at)): auto cash-outs could be honoured retroactively, but manual cash-outs during the gap were impossible, which disadvantages manual players. *Pause the flight*: breaks the time→multiplier contract and is exploitable.
**Consequences.** Simple, auditable rule that mirrors the common "malfunction voids all pays and plays" clause — but here only for *uncashed* bets. Needs commercial & regulatory approval (OQ-10). Voids must be rare: monitored and alerted.

## ADR-006 — Outcome generation
**Decision.** For the global round sequence, an offline ceremony generates a SHA-256 hash chain of length N; the terminal hash is published and signed. After publication, a public salt is fixed from a future drand round (number announced at commitment). Round *k* uses chain seed `s_{N-k}`; crash point from `HMAC-SHA256(s, salt)` via the integer formula in doc 07. Verification: `SHA256(s_round) = s_previous_round` and the formula.
**Alternatives.** Per-round server seed + player client seeds (rejected: shared multiplayer round cannot incorporate each player's seed fairly); CSPRNG per round with commit-reveal only (acceptable, but the chain additionally proves the house cannot regenerate outcomes mid-chain); certified hardware/RNG service (may be *required* by a regulator — OQ-12; the formula can accept any certified 52-bit uniform source instead of the HMAC).
**Consequences.** Outcomes for the whole chain are known to whoever holds the chain seed → seed secrecy is a top security control (doc 15). Must be independently reviewed before production.

## ADR-007 — Seamless wallet, rollback-on-doubt
**Decision.** Operator keeps the balance; we call `debit` at bet time, `credit` on win, `rollback` on cancel/void/unknown debit, optional `settle` (zero credit) on loss. If a debit's outcome is unknown, the bet is **not accepted** and a `rollback` is queued and retried until acknowledged.
**Alternatives.** Transfer wallet (we hold a game balance: custody, licensing and reconciliation burden — rejected for v1). Debit-then-status-query (needs a status endpoint every operator implements correctly; offered as optional optimisation).
**Consequences.** Operators must implement idempotent rollback-of-unknown semantics (doc 01 §2). Players occasionally see a refunded "failed" bet after a timeout — correct and safe.

## ADR-008 — Integer money
**Decision.** `amount_minor BIGINT` + `currency CHAR(3)`; per-currency exponent from `CurrencyConfiguration`. Multipliers `multiplier_x100 INT`. Payout = `floor(stake_minor × multiplier_x100 / 100)`, then `min(·, max_win_minor)`.
**Consequences.** Python `int`, Elixir integers and JS `BigInt`/safe integers; JSON carries amounts as **strings** to avoid JS double precision issues above 2^53.

## ADR-009 — Launch handshake
**Decision.** Default: iframe URL contains only `operator` public id, `lang`, `v` (version). The parent page's SDK delivers the one-time launch token via `postMessage` to the iframe's exact origin after the iframe announces readiness; the iframe validates `event.origin` against the operator's allowlist. Fallback for WebViews/no-JS integrations: token in the URL **fragment** (`#lt=…`), single-use, ≤ 60 s, removed from history with `history.replaceState` immediately.
**Rejected.** Query-string tokens (logged by proxies/CDNs/analytics, leaked via Referer); third-party cookies (blocked by Safari/Firefox, phasing in Chrome).
**Consequences.** Operators integrate a ~3 KB SDK or follow the fragment contract. Reload inside the iframe requires a relaunch from the parent (credentials live only in memory).

## ADR-010 — Request signing
**Decision.** Operators sign requests with an Ed25519 private key; we store only the public key. Signature over `method\npath\ntimestamp\nnonce\nsha256(body)`; ±300 s window; nonce uniqueness for 10 min. Outbound calls to operators are signed with the platform's Ed25519 key (public keys published with `kid`). HMAC-SHA256 is offered as a fallback scheme for operators who cannot do Ed25519; HMAC secrets are envelope-encrypted at rest.
**Consequences.** A database leak does not leak operator credentials (Ed25519 path).

## ADR-011 — Command transport
**Decision.** `PLACE_BET` and `CASH_OUT` go over the WebSocket to Phoenix, because Phoenix owns the deadlines. Launch exchange, session renewal, history, verification and config go over HTTPS to Django. A WS reply only means *received*; the authoritative result is a separate event (`BET_ACCEPTED`, `CASHOUT_ACCEPTED`, …) emitted after durable recording.
**Rejected.** Bets over HTTPS to Django (Django would then need to ask Phoenix for admission → an extra synchronous hop and a split decision).

## ADR-012 — Client-side curve
**Decision.** On launch, server sends `ROCKET_LAUNCHED{launch_at, curve_params}`. Clients compute `m(t)` locally with a server-clock offset estimate. Server sends `MULTIPLIER_UPDATE` at 4 Hz (configurable) for correction and liveness. Crash is signalled by `ROUND_CRASHED`.
**Consequences.** Fan-out cost ~1/15 of a 60 Hz stream; smooth on bad networks. Clients may briefly display a multiplier above the crash point (up to one RTT) before `ROUND_CRASHED` arrives; UI rules in doc 14 §6 (the rocket keeps flying until told otherwise; cash-out button result is always server-decided).

## ADR-013 — PubSub
**Decision.** `Phoenix.PubSub` with the PG adapter over a libcluster-formed Erlang cluster (DNS/static topology). Redis adapter only if the network forbids distribution ports.

## ADR-014 — Redis non-authoritative
**Decision.** Redis loss/flush must never change money, outcomes or token single-use. Single-use launch tokens, WS tickets and idempotency records live in Postgres.

## ADR-015 — Outbox + RabbitMQ
**Decision.** Django writes `platform.outbox_event` in the same transaction as the business change; a relay publishes with publisher confirms and marks `published_at`. Phoenix's journal plays the same role (ADR-003). Consumers keep `processed_event(event_id)` with a unique constraint inside the same transaction as their effect. Quorum queues; DLX per queue; poison messages to DLQ after 10 attempts with exponential backoff.

## ADR-016 — Django async strategy
**Decision.** `django-internal` runs under ASGI (uvicorn workers). The place-bet view is `async`, performs its DB work in a `sync_to_async` transactional block (Django transactions are not async-native), and performs the wallet debit with a per-process shared `aiohttp.ClientSession` (per-operator connector limits, explicit timeouts). Credits, rollbacks and settle calls are executed by `wallet-worker`: a Django-codebase asyncio process consuming RabbitMQ (aio-pika) and calling operators via aiohttp. Celery handles scheduled/batch jobs (reconciliation, reports, webhook retries, pruning).
**Alternatives.** Celery for wallet calls (thread/process-per-request concurrency, poor for thousands of concurrent slow HTTP calls); standalone aiohttp server (rejected per brief).
**Consequences.** Two worker models (asyncio + Celery). Acceptable: clear split — "outbound wallet I/O" vs "everything else".

## ADR-017 — Frontend separation
**Decision.** Game, admin and portal are separate Next.js apps on separate origins with separate CSPs, sharing `packages/ui` and `packages/protocol`. Game is `output: 'export'` (static) served by CDN.
**Rejected.** One Next.js app with route groups: one XSS in the game (which is framed by third parties) would sit on the same origin as the admin console; `frame-ancestors` must be permissive for the game and `'none'` for admin.

## ADR-018 — Defer PixiJS
**Decision.** No PixiJS in the MVP. HUD (multiplier, panels) is DOM for accessibility and crisp text; particles/effects in Three.js (instanced points/sprites). Revisit if a measured need appears (e.g. complex 2D telemetry animation that DOM can't hold at 60 fps).

## ADR-019 — Tenant isolation
**Decision.** (1) Every tenant-owned table has `operator_id NOT NULL`. (2) Django access via repository/service functions requiring an explicit `TenantContext`; unscoped managers forbidden by lint rule in operator-facing code. (3) Operator-portal API uses DB role `portal_rw` with Postgres RLS policies `operator_id = current_setting('app.operator_id')::uuid`, set per request with `SET LOCAL`. (4) Cross-tenant tests for every endpoint. Platform admin uses a separate role without RLS but with full audit.

## ADR-020 — One global round sequence
**Status.** Accepted by the product owner (2026-10-10). Supersedes the earlier "round streams per jurisdiction" proposal.
**Decision.** Each environment runs exactly one round sequence (`stream_id = global`; sandbox is a separate environment with its own). Every operator's players, in every jurisdiction and currency, play the same rounds. The `stream_id` column remains in the schema as the sequence identifier, but production configuration permits exactly one active stream and the admin UI has no "create stream" action.
**What varies per operator (allowed):** currency, stake limits, max win per bet (implemented as a per-bet effective auto cash-out target — doc 07 §4, so the round is unaffected), round exposure limit, auto cash-out availability, locale, RG settings, displayed features.
**What can never vary (one value for the whole world):** ruleset (house edge, curve, max multiplier, betting window), RNG/seed chain, crash point, round timing.
**Consequences.**
1. *Certification is global*: the single ruleset and RNG must be acceptable to every jurisdiction we serve; changing them is a coordinated, all-markets release. A market whose regulator demands different RTP, a local RNG, or in-country game servers **cannot be served** by this design — it is excluded, not given its own rounds (OQ-36).
2. *One hosting region serves everyone*: players far from Johannesburg get higher latency; this affects only display smoothness and cash-out reaction time, never correctness (server stamps). Latency per market is an onboarding check.
3. *Throughput ceiling*: all bets and cash-outs worldwide meet one coordinator — mitigated by ADR-025.
4. *Blast radius*: a coordinator failover voids the round for every operator at once; void rate becomes a platform-wide SLO.
5. *Liquidity & social proof* are maximised — the reason for the decision.
**Alternatives rejected.** Per-jurisdiction streams (product owner rejected: fragments the shared experience). Per-operator streams (same).

## ADR-021 — Hosting
**Decision.** Docker containers on Linux VMs (Compose per host + a simple deploy tool, e.g. Kamal or Ansible), reverse proxy, managed Postgres if available. Region: Johannesburg (≈ 20–40 ms RTT from Harare/Lusaka/Gaborone typical, to be measured). No Kubernetes, no service mesh.
**Revisit when:** > ~8 hosts, or autoscaling becomes economically necessary.

## ADR-022 — Session credentials
**Decision.** Game session token: Ed25519-signed compact token (JWS), 15 min TTL, claims `sid, op, pref(hashed), stream, cur, sv (session version), aud=game`. Renewed via HTTPS before expiry. WebSocket connect uses a separate single-use `ws_ticket` (30 s TTL, Postgres-backed) to keep long-lived tokens out of WS URLs (Phoenix sends connect params in the query string).
**Consequences.** Phoenix validates tickets via Django internal endpoint (one call per connect, cheap) and caches session status.

## ADR-023 — Currency
**Decision.** Each bet is in the session currency; no conversion. Limits and max-win are configured per operator × currency. Reporting can show an FX-normalised view using a daily rate table, clearly labelled as indicative.

## ADR-024 — Debit is not inclusion
**Decision.** A successful debit makes a bet *eligible*; the coordinator's journaled `BET_ADMITTED` makes it *part of the round*. A debited bet that is excluded (late, round voided, coordinator lost) is refunded via rollback.
**Consequences.** Bet lifecycle has a `DEBITED` (pending admission) state. Reconciler refunds any debited bet without an admission fact once its round is terminal.

## ADR-025 — Player-sharded cash-out arbitration under one global lease
**Context.** With global rounds, an auto cash-out cluster at a popular target (e.g. 2.00×) or a burst of manual cash-outs from all markets lands on one `:gen_statem`. Correctness only needs serialisation *per bet* plus a single crash instant; it does not need one process for all players.
**Decision.** Stage 1: single coordinator (simplest, sufficient for load-test stage S1). Stage 2, triggered by measured mailbox/latency thresholds (doc 16 §7): the coordinator remains the only authority for round state and timing, and spawns `BetShard` processes (one per rt node, players hashed to shards). At `ROCKET_LAUNCHED` each shard receives `crash_at`/`crash_x100` in memory; each shard independently decides manual and auto cash-outs for its players with the same rule (`received_at < crash_at`) and journals through its own fenced writer using the **global** lease's fencing token and a per-shard sequence. The coordinator journals `ROUND_CRASHED` only after every shard has flushed and acknowledged finalisation.
**Trade-off.** The crash point exists in N processes instead of one during flight — still only inside the trusted rt cluster, never persisted or logged; the insider surface grows slightly. A shard losing contact with the coordinator halts (same as coordinator loss → void).
**Alternatives.** Bigger single process (vertical only); moving cash-out decisions to Postgres row locks (contention on the hottest path).

## Unresolved decisions (tracked in doc 20)
OQ-10 (void policy), OQ-12 (RNG certification path), OQ-13 (house edge), OQ-14 (max multiplier & max win), OQ-15 (wallet `settle` call), OQ-05 (managed Postgres availability), OQ-20 (cancel bet in betting window).
