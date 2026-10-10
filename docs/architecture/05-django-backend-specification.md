# 05 — Django Backend Specification

## 1. Project layout (proposed)

```
backend/
  config/                 settings (12-factor, env-driven), asgi.py, wsgi.py, celery.py
  luxrocket/
    core/                 TenantContext, ids, money types, errors, idempotency helpers, outbox
    accounts/             StaffUser, MFA, roles, staff sessions
    operators/            Operator, credentials, domains, config versions, limits, wallet endpoint
    games/                Game, GameVersion, Ruleset, RoundStream, GameRound projection
    sessions/             PlayerRef, GameSession, LaunchToken, WsTicket
    betting/              Bet, exposure, place-bet service
    wallet/               WalletTransaction, attempts, adapters (seamless v1, sandbox), wallet-worker
    ledger/               LedgerEntry, posting rules, invariants
    settlement/           Settlement, journal-consumer, round finalisation
    reconciliation/       runs, items, resolution workflows
    webhooks/             endpoints, deliveries, signer
    reporting/            daily stats, exports
    audit/                hash-chained audit writer
    api_operator/         /operator/v1 (DRF)
    api_game/             /game/v1 (DRF) — called by the embedded game
    api_admin/            /api/admin/v1 (DRF) — platform admin
    api_portal/           /api/portal/v1 (DRF) — operator portal
    api_internal/         /internal/v1 — Phoenix only (ASGI async views)
    sandbox/              simulated operator wallet (sandbox environment only)
```

Domain logic lives in `services.py` modules (plain functions taking a `TenantContext`), not in views or model `save()`. Views are thin: authenticate → build context → validate schema → call service → serialize.

## 2. API surfaces

| Surface | Base path | Host | Caller | Auth | Notes |
|---------|-----------|------|--------|------|-------|
| Operator API | `/operator/v1` | `api.luxrocket.example` | Operator backend | Ed25519/HMAC request signature (doc 09) | Versioned, public contract |
| Game API | `/game/v1` | `api.luxrocket.example` | Embedded game | Launch token → game session token (Bearer, in memory) | CORS: only `https://play.luxrocket.example` |
| Admin API | `/api/admin/v1` | `admin.luxrocket.example` (same origin as the admin app, path-routed by the reverse proxy; IP allowlist/VPN optional) | Platform admin app | Staff session cookie (`__Host-`, Secure, HttpOnly, SameSite=Strict) + CSRF + MFA | Never exposed to operator realm |
| Portal API | `/api/portal/v1` | `portal.luxrocket.example` (same origin as the portal app, path-routed) | Operator portal | Staff session cookie (realm=OPERATOR) + CSRF; MFA per operator policy | RLS role |
| Internal API | `/internal/v1` | private network only | Phoenix | mTLS + service token + fencing token where relevant | Not routed by public proxy |

Public schemas are generated as OpenAPI 3.1 (drf-spectacular) and contract-tested against `/contracts`. Internal Django models are never serialised directly; every endpoint has explicit request/response serializers.

### 2.1 Game API (illustrative)

| Method & path | Purpose |
|---------------|---------|
| `POST /game/v1/sessions/exchange` | Launch token → game session token, config, stream info |
| `POST /game/v1/sessions/renew` | Renew game session token before expiry |
| `POST /game/v1/ws-tickets` | Issue single-use WS ticket |
| `GET /game/v1/config` | Effective panel/stake/limit config for the session |
| `GET /game/v1/me/bets?cursor=` | The player's bet history (own bets only) |
| `GET /game/v1/rounds/recent` | Last N crash points for the session's stream |
| `GET /game/v1/rounds/{round_id}/verification` | Seed, salt, chain proof, formula version |
| `GET /game/v1/rules` | Rendered rules & RTP disclosure for the active ruleset |

### 2.2 Internal API (Phoenix → Django)

| Method & path | Purpose | Timeout (caller) |
|---------------|---------|------------------|
| `POST /internal/v1/bets` | Validate + debit; returns `ACCEPTED`/`REJECTED`/`UNKNOWN` | 900 ms |
| `POST /internal/v1/ws-tickets/consume` | Validate & consume ticket; returns session claims | 300 ms |
| `GET /internal/v1/sessions/{sid}/status` | Session status for join/periodic check | 300 ms |
| `GET /internal/v1/streams/{id}/config` | Ruleset + stream config snapshot | 1 s |

## 3. Authentication and permissions

### 3.1 Operator API
1. Parse `LR-Key-Id`, `LR-Timestamp`, `LR-Nonce`, `LR-Signature` headers.
2. Load credential by `kid` (cached 60 s in Redis; cache never authoritative for revocation beyond 60 s — revocation also publishes a cache-bust event).
3. Reject if timestamp skew > 300 s; reject nonce reuse (Postgres `request_nonce` table, unique `(kid, nonce)`, 10-min TTL; Redis SETNX in front as a fast-path filter only).
4. Verify signature over canonical string; constant-time compare for HMAC.
5. Build `TenantContext(operator_id, actor=OPERATOR_API, kid)`.
6. Idempotency: mutating endpoints require `Idempotency-Key`; stored with request hash and response for 24 h; same key + different body → `409 IDEMPOTENCY_KEY_REUSED`.

### 3.2 Staff (admin & portal)
- Django sessions in Postgres-backed store with Redis cache; session cookie per host; 12 h absolute, 30 min idle (admin); portal configurable.
- Password: Argon2id, breached-password check (k-anonymity HIBP range API — optional, OQ-19), lockout with exponential backoff.
- MFA: WebAuthn preferred, TOTP allowed; **mandatory for all platform staff**; step-up re-authentication (≤ 5 min old) for privileged actions (credential creation, real-money enablement, ruleset release, adjustments, role grants).
- Permission model: role → permission set (code constants), checked in a DRF permission class *and* inside services for sensitive operations (defence in depth).

### 3.3 Game API
- Exchange endpoint authenticates the launch token only.
- Subsequent calls: `Authorization: Bearer <game_session_token>` (Ed25519 JWS, 15 min). Verified locally; `sv` claim compared with cached `session_version` (Redis, 5 s TTL, fallback DB) so revocation is near-immediate.

## 4. Place-bet service (internal API)

```
async def place_bet(req):                       # ASGI view
    ctx = fence_check(req.stream_id, req.fencing_token)   # reject stale coordinators
    phase1 = await sync_to_async(tx_phase1)(req)  # one DB transaction
    if phase1.is_replay: return phase1.previous_result     # idempotent replay
    if phase1.rejected: return REJECTED(phase1.code)
    result = await wallet.debit(phase1.wallet_tx, deadline=req.debit_deadline)  # aiohttp
    final = await sync_to_async(tx_phase2)(phase1, result)  # one DB transaction
    return final  # ACCEPTED | REJECTED | UNKNOWN
```

`tx_phase1` (single transaction, `SELECT … FOR UPDATE` only on the session row):
1. Session ACTIVE, `session_version` matches, mode matches stream mode.
2. Operator LIVE/SANDBOX consistent with mode; `real_money_enabled` for REAL.
3. Currency enabled; stake within `[min,max]`; `auto_cashout_x10000` a multiple of 100 within `[10100, max_multiplier_x10000]`.
4. Responsible-gaming flags from operator (e.g. `rg_blocked`) not set.
5. Insert `bet(PENDING_DEBIT)` — unique constraints catch duplicates → return existing bet's current result.
6. Atomic exposure increment (`max_win_minor` of this bet) — fails → `REJECTED(EXPOSURE_LIMIT)`.
7. Insert `wallet_transaction(DEBIT, PENDING)`.

`tx_phase2`:
- `SUCCEEDED` → bet `DEBITED`, ledger postings, outbox `bet.debited`.
- Operator business rejection (insufficient funds, player blocked) → bet `REJECTED`, wallet tx `FAILED`, exposure decrement.
- Timeout / network / 5xx / malformed → wallet tx `UNKNOWN`, bet `DEBIT_UNKNOWN`, enqueue `ROLLBACK` job (doc 08 §6). Return `UNKNOWN` to Phoenix (player sees "Bet not placed — any deducted amount will be returned").
- If `now() > debit_deadline` when the debit returns success: still record `DEBITED` truthfully and return `ACCEPTED`; the coordinator will exclude it and the exclusion fact triggers a rollback. Django never guesses the coordinator's decision.

## 5. Async integration strategy (aiohttp)

- One `aiohttp.ClientSession` per process, created at ASGI lifespan startup, closed at shutdown.
- `TCPConnector(limit=…, limit_per_host=operator.max_concurrency, ttl_dns_cache=60, enable_cleanup_closed=True)`; per-operator connectors when operators share hosts behind different credentials.
- Timeouts: `ClientTimeout(total=operator.timeout_ms, connect=300ms, sock_read=operator.timeout_ms)`.
- **Bulkheads**: `asyncio.Semaphore` per operator in each process; when saturated, the bet is rejected fast with `OPERATOR_BUSY` instead of queueing past the deadline (NFR-014).
- **Circuit breaker** per operator (rolling error rate > 50 % over 20 calls or 5 consecutive timeouts → open 10 s → half-open). Open breaker → `REJECTED(OPERATOR_UNAVAILABLE)` for debits; credits/rollbacks are queued, never dropped.
- Retries: **no automatic retry for debits within the bet path** (a retry would race the deadline and the outcome is ambiguous). Credits/rollbacks retried by `wallet-worker` with the same `transaction_id` (doc 08 §6).
- Response validation against the wallet response schema; unparseable 2xx = `UNKNOWN`, not success.
- Request/response bodies logged only as digests + redacted excerpts.

## 6. Background processes

| Process | Framework | Responsibilities |
|---------|-----------|------------------|
| `wallet-worker` | asyncio + aio-pika + aiohttp | Queues `wallet.credit`, `wallet.rollback`, `wallet.settle` — one queue per priority, per-operator semaphores, retries with backoff (doc 08 §6) |
| `journal-consumer` | asyncio + aio-pika (Django ORM via sync_to_async) | Applies `rt.events`; one consumer per stream for ordering (single-active-consumer queue) |
| `celery-worker` | Celery (RabbitMQ broker) | Outbox relay (fallback poller), webhooks, reconciliation, reports, pruning, partition management |
| `celery-beat` | Celery beat | Schedules |

## 7. Configuration and secrets

- Settings from environment; secrets from files mounted by the deploy tool (or a secrets manager) — never in images or git.
- Field-level encryption (AES-256-GCM) with envelope keys for: HMAC operator secrets, operator session tokens, TOTP secrets. Data-encryption keys wrapped by a key-encryption key held outside the DB (KMS or sealed file on hosts; OQ-06).
- `DEBUG=False`, `SECURE_*` headers, `ALLOWED_HOSTS` explicit, `CSRF_TRUSTED_ORIGINS` explicit.

## 8. Error model

All APIs return RFC 9457 `application/problem+json`:
```json
{ "type": "https://docs.luxrocket.example/errors/STAKE_OUT_OF_RANGE",
  "title": "Stake out of range", "status": 422,
  "code": "STAKE_OUT_OF_RANGE", "correlation_id": "c_01J…",
  "detail": "Stake must be between 0.10 and 100.00 USD" }
```
Error codes are a closed, versioned enum per surface (doc 09 §9, doc 10 §8).

## 9. Coding standards (to be enforced from the first commit)
- Python 3.12+, Django 5.x LTS line, DRF; `ruff`, `mypy --strict` on `luxrocket/core`, `wallet`, `ledger`, `betting`, `settlement`.
- Lint rule: forbid `.objects.` on tenant models outside repository modules; forbid `float` in money modules.
- Every service function that mutates money has a property-based test (Hypothesis) for idempotency.
