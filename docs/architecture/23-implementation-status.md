# 23 — Implementation Status

As of 2026-10-11. Sandbox mode, end to end. **Real money is not enabled and must not be**
until the Gate RM requirements in doc 19 §5 are met.

## What works today

| Area | Status | Where |
|------|--------|-------|
| Operator API: Ed25519 signing (LR1), nonce replay protection, idempotency keys, contract-schema validation | ✅ | `backend/luxrocket/operators/signing.py`, `api/operator_views.py` |
| Owner-controlled market registry + operator jurisdictions at session creation | ✅ | `operators/models.py`, `gaming/sessions.py` |
| Launch: single-use launch tokens (race-safe), postMessage handshake + fragment fallback, operator SDK | ✅ | `gaming/sessions.py`, `apps/game/src/lib/launch.ts`, `packages/sdk` |
| Game-session tokens (EdDSA JWS, 15 min, renewal, revocation) and single-use WS tickets | ✅ | `gaming/session_tokens.py` |
| Authoritative round coordinator: lease + fencing, betting window, admission, exclusion at launch, manual + auto cash-out, max multiplier, crash, void-on-recovery | ✅ | `realtime/lib/lux_rt/rounds/coordinator.ex` |
| Provably-fair hash chain (encrypted seeds, checkpoints), LR-CRASH-1 in Python/Elixir/TS with shared vectors, bit-identical curve table | ✅ | `realtime/lib/lux_rt/fairness`, `*/math`, `contracts/math` |
| Append-only round journal + ordered at-least-once relay to Django; Django re-verifies every outcome | ✅ | `rounds/journal.ex`, `rounds/relay.ex`, `gaming/journal.py` |
| Bet placement (two transactions around the debit), exposure limits, one bet per panel, rollback-on-doubt | ✅ | `gaming/betting.py` |
| Sandbox seamless wallet with contract semantics, retrying wallet worker, outbox to Phoenix | ✅ | `wallet/adapters.py`, `wallet/worker.py`, `wallet/outbox.py` |
| Double-entry ledger; DB triggers make it append-only and reject unbalanced journals | ✅ | `wallet/ledger.py`, `wallet/migrations/0002_ledger_integrity.py` |
| Player game: two panels, live multiplier, cash-out, history, rules/RTP, in-browser round verification, reconnect/resync, Three.js journey | ✅ | `apps/game` |
| Interim back-office (read-only financial views) | ✅ Django admin at `/django-admin/` | `*/admin.py` |
| Money invariants checker | ✅ `make invariants` | `gaming/invariants.py` |
| Tests | ✅ 62 Django, 28 Phoenix, 16 game-core, 4 multi-browser E2E | CI job `e2e` runs the full stack |
| One-command sandbox stack | ✅ `make stack` | `infra/compose/docker-compose.yml` |

## Deliberate interim deviations (tracked)

| Architecture says | Built now | Why / next step |
|-------------------|-----------|-----------------|
| RabbitMQ for journal relay and platform events (ADR-015) | Authenticated internal HTTP from the same journal/outbox tables | Same delivery guarantees (durable source, at-least-once, dedupe, ordered with gap detection) with fewer moving parts. Swapping the transport touches only `Relay` and `outbox.relay_once`. |
| Redis caches (ADR-014) | Not used yet | Nothing correctness-critical needs it; add for rate limits/caching at scale. |
| Salt from a public randomness beacon (drand) | Random salt fixed at chain creation (`salt_source: local-random`) | Fine for sandbox; production ceremony must use drand (doc 07 §6.1). |
| Seed KEK in KMS/HSM | KEK from `SEED_KEK_B64` env (dev/test derive a throwaway key) | Move to KMS before real money (OQ-06). |
| mTLS on internal calls | Shared bearer service token | Add mTLS on the private network. |
| Postgres roles per service + RLS for the portal (ADR-019) | Single DB role | Add roles/RLS with the operator portal (Phase F). |
| Per-operator CSP `frame-ancestors` on a dynamic launch document | Static launch page; dev nginx allows any parent | Serve the launch document from the platform with per-operator CSP. |
| Platform admin & operator portal (Next.js) | Django admin (read-only financials) | Phase F. |
| Staff MFA, four-eyes approvals, hash-chained audit log | Not yet | Phase F/G. |
| REAL-money seamless wallet adapter (aiohttp) | Not implemented; REAL sessions are refused | Implement with the conformance suite before any operator goes live. |
| Phoenix clustering, BetShard scaling | Single node | Load tests (doc 16 §7) decide. |

## Run it

```bash
make stack          # full sandbox: game :3000, API :8000, realtime :4000
make demo-launch    # prints a launch link (acts as the operator)
open http://localhost:8000/demo/operator   # embedded via the SDK (postMessage handshake)
make e2e            # multi-browser end-to-end tests
make invariants     # money-correctness checks
```
