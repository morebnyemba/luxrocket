# 09 — Operator Integration API

> All endpoints, hostnames and payloads are **illustrative proposed contracts**. Nothing is implemented. The machine-readable source of truth will be `/contracts/operator/v1/openapi.yaml` and `/contracts/wallet/v1/*.schema.json`.

## 1. Integration models

| Model | v1 status | Notes |
|-------|-----------|-------|
| **LUX Seamless Wallet v1** (our standard contract, §6) | Supported | Operator implements 3–4 endpoints. Recommended. |
| **Custom adapter** (we map to the operator's existing wallet API) | Supported case-by-case | Implemented as a `WalletAdapter` subclass in `backend/luxrocket/wallet/adapters/`; must pass the same contract test suite; billed as integration work. |
| **Aggregator / RGS hub** | Future | Same adapter mechanism. |
| **Transfer wallet** | Not supported | Custody & licensing implications (ADR-007). |

## 2. Environments

| Env | API base | Game origin | Money |
|-----|----------|-------------|-------|
| Sandbox | `https://sandbox-api.luxrocket.example/operator/v1` | `https://sandbox-play.luxrocket.example` | Virtual credits; built-in simulated wallet optional |
| Production | `https://api.luxrocket.example/operator/v1` | `https://play.luxrocket.example` | Real money only when `real_money_enabled` |

Sandbox ships with an **operator simulator** (reference wallet implementation with fault injection: latency, timeouts, 5xx, duplicate responses, insufficient funds) that operators can run to test their own integration, and a conformance test runner that exercises *their* wallet endpoints.

## 3. Authentication & request signing (operator → platform)

Headers on every request:
```
LR-Key-Id:    k_01J9…              (credential kid)
LR-Timestamp: 1791633600           (Unix seconds; ±300 s accepted)
LR-Nonce:     9b1d0f…              (≥128-bit random, unique per kid for 10 min)
LR-Signature: ed25519=<base64url signature>   | hmac-sha256=<base64url mac>
Idempotency-Key: <uuid>            (required on POST/PATCH)
```
String to sign (UTF-8, `\n` separated):
```
LR1
<HTTP_METHOD>
<path_with_query_exactly_as_sent>
<LR-Timestamp>
<LR-Nonce>
<hex(sha256(raw_body))>
```
Credentials: created in the portal (Ed25519: operator uploads the **public** key, or generates in-browser and downloads the private key once). Max two active keys per environment for rotation; old key auto-expires ≤ 14 days after the new key's first use.

Platform → operator calls (wallet, webhooks) use the same scheme signed with the platform key (`LR-Key-Id: plat_2026a`); public keys published at `https://api.luxrocket.example/.well-known/luxrocket-keys.json` and in the portal. Operators MAY additionally allowlist our egress IPs and require mTLS.

## 4. Platform endpoints (operator calls us)

| Method & path | Purpose | Rate limit (default) |
|---------------|---------|----------------------|
| `POST /sessions` | Create a launch session for an authenticated player | 50 rps |
| `GET /sessions/{session_id}` | Session status | 20 rps |
| `POST /sessions/{session_id}/revoke` | Revoke one session | 20 rps |
| `POST /players/{player_id}/revoke-sessions` | Revoke all sessions of a player | 20 rps |
| `PUT /players/{player_id}/restrictions` | Push RG flags (self-excluded, cooling-off, blocked) | 20 rps |
| `GET /games` | Game availability, versions, maintenance windows | 5 rps |
| `GET /config` / `PATCH /config` | Read / change operator-permitted settings | 5 rps |
| `GET /rounds/{round_id}` | Round result + verification data (after crash) | 20 rps |
| `GET /bets?from=&to=&player_id=&cursor=` | Bet history (own tenant) | 10 rps |
| `GET /bets/{bet_id}` | One bet with its transactions | 20 rps |
| `GET /transactions?date=&cursor=` | Wallet transactions for a UTC day | 5 rps |
| `GET /transactions/{transaction_id}` | One transaction status | 20 rps |
| `GET /reconciliation/{date}` | Daily reconciliation summary | 2 rps |
| `GET /webhook-endpoints`, `POST`, `DELETE /{id}`, `POST /{id}/test` | Webhook management | 2 rps |
| `GET /health` | Unauthenticated liveness | — |

Exceeded limits: `429` + `Retry-After`. Limits are per operator, configurable by platform admin.

### 4.1 Create session — request (JSON Schema, abridged)
```json
{
  "$id": "https://contracts.luxrocket.example/operator/v1/session-create.request.json",
  "type": "object",
  "required": ["player", "currency", "game", "mode"],
  "additionalProperties": false,
  "properties": {
    "player": {
      "type": "object", "required": ["id", "country"], "additionalProperties": false,
      "properties": {
        "id": { "type": "string", "minLength": 1, "maxLength": 128, "description": "Operator's pseudonymous player id" },
        "alias": { "type": "string", "maxLength": 24, "description": "Optional display alias; masked before display" },
        "country": { "type": "string", "pattern": "^[A-Z]{2}$" }
      }
    },
    "currency": { "type": "string", "pattern": "^[A-Z]{3}$" },
    "game": { "type": "string", "const": "lux-rocket" },
    "mode": { "enum": ["REAL", "SANDBOX"] },
    "locale": { "type": "string", "default": "en" },
    "operator_session_token": { "type": "string", "maxLength": 512, "description": "Opaque; echoed back in wallet calls" },
    "return_url": { "type": "string", "format": "uri" },
    "rg": {
      "type": "object", "additionalProperties": false,
      "properties": {
        "session_reminder_minutes": { "type": "integer", "minimum": 5 },
        "session_time_limit_minutes": { "type": "integer", "minimum": 1 }
      }
    }
  }
}
```
### 4.2 Create session — response
```json
{
  "session_id": "ses_01J9Z…",
  "launch_token": "lt_6f1c…",           
  "launch_token_expires_at": "2026-10-10T12:01:00.000Z",
  "iframe_url": "https://play.luxrocket.example/v1/launch?op=op_01J8…&lang=en",
  "fragment_launch_url": "https://play.luxrocket.example/v1/launch?op=op_01J8…&lang=en#lt=lt_6f1c…",
  "sdk_url": "https://play.luxrocket.example/sdk/v1/luxrocket-embed.js",
  "sdk_integrity": "sha384-…"
}
```
`launch_token` is single-use, ≤ 60 s. The operator's backend passes it to its own page (never to third parties). See doc 11 for delivery to the iframe.

## 5. Error model

`application/problem+json` with `code` from a closed enum:

| HTTP | `code` | Meaning |
|------|--------|---------|
| 400 | `INVALID_REQUEST` | Schema violation (`errors[]` lists JSON pointers) |
| 401 | `INVALID_SIGNATURE`, `TIMESTAMP_OUT_OF_WINDOW`, `NONCE_REUSED`, `UNKNOWN_KEY` | Auth failure (no detail beyond code) |
| 403 | `OPERATOR_SUSPENDED`, `REAL_MONEY_DISABLED`, `WALLET_NOT_CONFIGURED`, `JURISDICTION_NOT_PERMITTED`, `CURRENCY_NOT_ENABLED` | Policy |
| 404 | `NOT_FOUND` | Unknown *or foreign-tenant* resource |
| 409 | `IDEMPOTENCY_KEY_REUSED`, `STATE_CONFLICT` | |
| 422 | `PLAYER_RESTRICTED`, `CONFIG_NOT_PERMITTED` | |
| 429 | `RATE_LIMITED` | |
| 503 | `GAME_UNAVAILABLE`, `MAINTENANCE` | `Retry-After` set |
| 500 | `INTERNAL_ERROR` | `correlation_id` for support |

## 6. Operator wallet contract (we call the operator) — LUX Seamless Wallet v1

Base URL configured per operator. All requests signed (§3). All amounts are **strings of integer minor units**. All operations MUST be idempotent on `transaction_id`.

| Endpoint | Required | Timeout we apply |
|----------|----------|------------------|
| `POST {base}/debit` | Yes | ≤ 900 ms (configurable lower) |
| `POST {base}/credit` | Yes | 5 s |
| `POST {base}/rollback` | Yes | 5 s |
| `POST {base}/settle` | Optional (`send_settle_on_loss`) | 5 s |
| `POST {base}/balance` | Optional (for in-game balance display) | 1 s |
| `POST {base}/transactions/lookup` | Optional, **required for operator reconciliation** (`wallet/v1/lookup.*`) | 5 s |

### 6.1 Debit request
```json
{
  "$id": "https://contracts.luxrocket.example/wallet/v1/debit.request.json",
  "type": "object",
  "required": ["transaction_id", "bet_id", "round_id", "player_id", "currency", "amount", "created_at"],
  "additionalProperties": false,
  "properties": {
    "transaction_id": { "type": "string", "pattern": "^tx_[0-9a-z]{26}$" },
    "bet_id": { "type": "string" },
    "round_id": { "type": "string" },
    "session_id": { "type": "string" },
    "operator_session_token": { "type": "string" },
    "player_id": { "type": "string" },
    "currency": { "type": "string", "pattern": "^[A-Z]{3}$" },
    "amount": { "type": "string", "pattern": "^[1-9][0-9]{0,17}$" },
    "game": { "const": "lux-rocket" },
    "panel": { "type": "integer", "minimum": 0 },
    "created_at": { "type": "string", "format": "date-time" }
  }
}
```
### 6.2 Credit request
Same envelope plus `"type": "WIN"`, `"multiplier_x10000": 23456`, `"amount"` = payout, `"debit_transaction_id"`. `amount` may be `"0"` only on `/settle`.

### 6.3 Rollback request
```json
{ "transaction_id": "tx_…", "rolled_back_transaction_id": "tx_…(debit)", "bet_id": "bet_…",
  "round_id": "rnd_…", "player_id": "p-778", "currency": "USD", "amount": "500",
  "reason": "DEBIT_UNCERTAIN | BET_EXCLUDED | ROUND_VOIDED" }
```
### 6.4 Wallet response (all operations)
```json
{
  "$id": "https://contracts.luxrocket.example/wallet/v1/response.json",
  "type": "object",
  "required": ["status", "transaction_id"],
  "properties": {
    "status": { "enum": ["OK", "REJECTED"] },
    "transaction_id": { "type": "string" },
    "operator_transaction_id": { "type": "string" },
    "balance": { "type": "string", "description": "Optional post-transaction balance, minor units" },
    "currency": { "type": "string" },
    "code": { "enum": ["INSUFFICIENT_FUNDS", "PLAYER_BLOCKED", "SESSION_EXPIRED", "LIMIT_EXCEEDED",
                       "CURRENCY_MISMATCH", "DUPLICATE_TRANSACTION", "TRANSACTION_NOT_FOUND",
                       "INVALID_REQUEST", "INTERNAL_ERROR"] },
    "duplicate": { "type": "boolean", "description": "true if this is a replay of an already-processed transaction_id" }
  }
}
```
### 6.4a Balance (optional)
`POST {base}/balance` with `{ "player_id", "currency", "session_id"?, "operator_session_token"? }` →
`{ "status": "OK", "balance": "<minor units>", "currency": "USD" }`
(`contracts/wallet/v1/balance.*.schema.json`). Used only for the in-game HUD; failures hide the figure
and never block play.

### 6.5 Required operator semantics
1. Same `transaction_id` ⇒ same effect once; replays return the original result with `duplicate: true`.
2. `credit` and `rollback` MUST succeed for any previously debited bet regardless of session state or player restrictions (`SESSION_EXPIRED`/`PLAYER_BLOCKED` are not valid reasons to reject them).
3. `rollback` of an unknown `transaction_id` ⇒ `OK` and the operator records a tombstone so a later `debit` with that id is rejected.
4. HTTP 2xx with unparseable body, any 5xx, or timeout are treated by us as *unknown* — never as rejection.
5. Business rejection is HTTP 200 with `status: REJECTED` and a `code`.
6. The response MUST echo our `transaction_id`; a response for a different id, a 3xx, or a body
   that fails the response schema is treated as *unknown*.

### 6.6 How the platform calls the wallet (as built)
- Requests are LR1-signed (§3) with the platform key; verify against `/.well-known/luxrocket-keys.json`.
- Debit timeout = min(operator setting, platform cap 750 ms, time left before the betting cut-off − 100 ms).
  A debit that cannot be confirmed before the cut-off becomes *unknown* and is rolled back.
- Credits and rollbacks retry with backoff (1 s … 15 min, then hourly) for 72 h, then `NEEDS_ATTENTION`.
- Each session snapshots its wallet routing at creation, so credits and rollbacks always reach the wallet
  that took the stake, even if the operator is reconfigured mid-session.
- Plain `http` wallet URLs are refused outside development (`WALLET_ALLOW_HTTP`).

### 6.7 Reference wallet and conformance
- `python -m luxrocket.wallet.simulator --keys-url …/.well-known/luxrocket-keys.json [--lose-rate …]` runs a
  standalone reference implementation of this contract (Python + `cryptography` only) with fault injection.
- `manage.py wallet_conformance --base-url https://… --player-id <test player>` runs signed calls that check
  idempotent debit/credit/rollback, tombstoning, `INSUFFICIENT_FUNDS`, and signature enforcement. Passing it
  is a precondition for `real_money_enabled`.

## 7. Webhooks (we notify the operator)

Delivered `POST` to registered URLs, signed (§3), at-least-once, retried 1 m, 5 m, 15 m, 1 h, 6 h, 24 h; delivery log visible in the portal. Consumers dedupe by `event_id`.

```json
{
  "$id": "https://contracts.luxrocket.example/operator/v1/webhook.json",
  "type": "object",
  "required": ["event_id", "type", "occurred_at", "operator_id", "data", "api_version"],
  "properties": {
    "event_id": { "type": "string" },
    "type": { "enum": ["bet.settled", "round.settled", "transaction.needs_attention",
                       "reconciliation.discrepancy", "session.revoked", "game.maintenance_scheduled",
                       "game.availability_changed", "credential.expiring"] },
    "occurred_at": { "type": "string", "format": "date-time" },
    "operator_id": { "type": "string" },
    "api_version": { "const": "v1" },
    "data": { "type": "object" }
  }
}
```
**As built (v1):** event types `bet.settled`, `round.settled`, `transaction.needs_attention`
(schema: `contracts/operator/v1/webhook.schema.json`; the type enum is open — ignore unknown types).
- Signed with LR1 (§3) using the platform key, plus `LR-Event-Id` / `LR-Event-Type` headers. Any 2xx acknowledges.
- Events are written in the same database transaction as the state change (outbox), then delivered
  at-least-once: immediately, then retried after 1 m, 5 m, 15 m, 1 h, 6 h, 24 h; after that `FAILED`
  (re-queue from the back-office).
- `event_id` is **deterministic** per (type, subject, operator): the same fact always carries the same id,
  so dedupe on it and re-emission can never produce a second event.
- `bet.settled` fires when the settlement is final (LOSS at crash; WIN/REFUND when the wallet confirms).
  `round.settled` carries per-currency `stake` and `payout` totals for your bets only; `payout` includes
  refunded stakes, so `stake − payout` is your round result. Transaction ids match the wallet calls.

Example `bet.settled.data`: `{ "bet_id", "round_id", "player_id", "currency", "stake": "500", "outcome": "WIN", "multiplier_x10000": 23456, "payout": "1172", "transactions": ["tx_…","tx_…"] }`.

## 8. Settlement response (operator queries a bet)
`GET /bets/{bet_id}` →
```json
{ "bet_id": "bet_…", "round_id": "rnd_…", "player_id": "p-778", "panel": 1,
  "currency": "USD", "stake": "500", "auto_cashout_x10000": 100000,
  "status": "CASHED_OUT", "cashout_x10000": 100000, "payout": "5000",
  "settlement": { "outcome": "WIN", "status": "CONFIRMED", "confirmed_at": "…" },
  "transactions": [
    { "transaction_id": "tx_…", "type": "DEBIT", "amount": "500", "status": "SUCCEEDED" },
    { "transaction_id": "tx_…", "type": "CREDIT", "amount": "5000", "status": "SUCCEEDED" } ] }
```

## 9. Versioning & compatibility
- Major version in path (`/v1`). Within a major: additive fields only; clients MUST ignore unknown fields; enums may gain values only where documented as open.
- Breaking changes ⇒ `/v2`, ≥ 6 months overlap, deprecation headers (`Deprecation`, `Sunset`).
- Wallet contract versioned independently (`wallet/v1`), negotiated per operator.

## 10. Auditability
Every operator API call is logged (kid, endpoint, status, latency, correlation id, idempotency key; no bodies containing tokens). Every wallet attempt is stored (`wallet_tx_attempt`). Operators see both in the portal's integration log.
