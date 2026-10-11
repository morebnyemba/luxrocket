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
| **LUX Seamless Wallet v1 client**: LR1-signed calls to the operator's `/debit` `/credit` `/rollback` `/balance`, contract-validated both ways, pessimistic classification (only a valid 200 echoing our tx id is OK/REJECTED; everything else UNKNOWN), debit bounded by the betting cut-off, per-session wallet snapshot | ✅ | `wallet/seamless.py`, `core/lr1.py` |
| Platform signing keys published at `/.well-known/luxrocket-keys.json` | ✅ | `core/views.py` |
| Reference operator wallet (standalone, fault injection: latency, 5xx, lost responses) | ✅ `python -m luxrocket.wallet.simulator` / `make stack-seamless` | `wallet/simulator.py` |
| Signed operator webhooks (`bet.settled`, `round.settled`, `transaction.needs_attention`): transactional outbox, deterministic event ids, retry schedule, delivery log in back-office | ✅ | `operators/webhooks.py` |
| Reconciliation: internal sweep with safe auto-repair + discrepancy queue (mandatory resolution notes); operator reconciliation via batched lookup of our tx ids; `reconciliation.discrepancy` webhook | ✅ `make reconcile` | `wallet/reconciliation.py` (doc 08 §8) |
| Wallet conformance runner (operators must pass before go-live) | ✅ `manage.py wallet_conformance` / `make wallet-conformance` | `wallet/conformance.py` |
| Double-entry ledger; DB triggers make it append-only and reject unbalanced journals | ✅ | `wallet/ledger.py`, `wallet/migrations/0002_ledger_integrity.py` |
| Player game: two panels, live multiplier, cash-out, history, rules/RTP, in-browser round verification, reconnect/resync, Three.js journey | ✅ | `apps/game` |
| **Operator portal** (doc 13): staff accounts per operator with six roles, `__Host-` HttpOnly SameSite=Strict session cookie (8 h / 30 min idle), lockout, forced first-login password change, TOTP 2FA (secret AES-GCM at rest, single-use codes), step-up for credentials / wallet / users, custom-header + Origin CSRF check; overview KPIs (GGR from the ledger), bets & bet detail with wallet attempts, rounds, reconciliation, credentials (public-key upload or in-browser Ed25519 generation, private key downloaded once), wallet endpoint + conformance run, webhooks + delivery log + replay, users, sessions, audit | ✅ `http://localhost:3002` | `backend/luxrocket/portal`, `apps/portal` |
| Hash-chained, DB-enforced append-only audit log with chain verification | ✅ | `portal/audit.py` |
| Cross-tenant isolation suite + route inventory (AC-OP-1) | ✅ | `backend/tests/test_portal.py` |
| **Platform console** (doc 12): password + mandatory WebAuthn passkey (UV required) for every staff sign-in, passkey step-up for privileged writes, §4 role matrix, owner-only markets, operator onboarding/suspend, four-eyes real-money enablement and reactivation (DB-enforced requester ≠ approver), finance queue + retry, bet timeline, audited player search, discrepancy resolution, read-only rounds + journal, staff, audit + chain verification | ✅ `http://localhost:3003` | `backend/luxrocket/console`, `apps/admin` |
| Shared console UI/API kit | ✅ | `packages/console-kit` |
| Django admin (break-glass / data inspection only) | ✅ `/django-admin/` | `*/admin.py` |
| Money invariants checker | ✅ `make invariants` | `gaming/invariants.py` |
| Tests | ✅ 152 Django, 28 Phoenix, 16 game-core, 8 E2E (4 gameplay multi-browser, 2 portal, 2 console with virtual security keys) | CI job `e2e` runs the full stack |
| One-command sandbox stack | ✅ `make stack` | `infra/compose/docker-compose.yml` |

## Deliberate interim deviations (tracked)

| Architecture says | Built now | Why / next step |
|-------------------|-----------|-----------------|
| RabbitMQ for journal relay and platform events (ADR-015) | Authenticated internal HTTP from the same journal/outbox tables | Same delivery guarantees (durable source, at-least-once, dedupe, ordered with gap detection) with fewer moving parts. Swapping the transport touches only `Relay` and `outbox.relay_once`. |
| Redis caches (ADR-014) | Not used yet | Nothing correctness-critical needs it; add for rate limits/caching at scale. |
| Salt from a public randomness beacon (drand) | Random salt fixed at chain creation (`salt_source: local-random`) | Fine for sandbox; production ceremony must use drand (doc 07 §6.1). |
| Seed KEK in KMS/HSM | KEK from `SEED_KEK_B64` env (dev/test derive a throwaway key) | Move to KMS before real money (OQ-06). |
| mTLS on internal calls | Shared bearer service token | Add mTLS on the private network. |
| Postgres roles per service + RLS for the portal (ADR-019) | Single DB role; tenant isolation by session-derived operator + explicit filters, proven by the cross-tenant route suite | Add `portal_rw` role + `FORCE ROW LEVEL SECURITY` with `SET LOCAL app.operator_id` as defence in depth. |
| Per-operator CSP `frame-ancestors` on a dynamic launch document | Static launch page; dev nginx allows any parent | Serve the launch document from the platform with per-operator CSP. |
| Console: game versions / rulesets / streams / seed-chain activation, maintenance & drain, adjustments, analytics series, incidents, exports, IP allowlist (doc 12) | Not yet | Next console increments; approvals, step-up and audit primitives are in place. |
| Portal extras (doc 13): domains with DNS verification, game settings & config versions, CSV/XLSX exports, operator-enforced MFA, HMAC credentials | Not yet | Next increments; the auth/audit/tenant core they need is in place. |
| Daily WORM anchor of the audit-chain head | Not yet | `audit/verify` exposes the head hash; add the scheduled export to object storage. |
| Seamless wallet adapter on aiohttp workers | Synchronous `httpx` pooled client inside the existing workers | Same contract and semantics; switch to async when wallet-call concurrency (not correctness) becomes the bottleneck. REAL sessions additionally require `real_money_enabled`, LIVE status and a seamless wallet — still gated by Gate RM (doc 19 §5). |
| Webhook types `session.revoked`, `game.*`, `credential.expiring` (doc 09 §7) | Not yet | Same outbox; add with the reconciliation job and the portal. |
| Phoenix clustering, BetShard scaling | Single node | Load tests (doc 16 §7) decide. |

## Run it

```bash
make stack          # full sandbox: game :3000, portal :3002, console :3003, API :8000, realtime :4000
                    # portal login: demo-owner@luxrocket.local / PORTAL_DEMO_PASSWORD in .demo/stack.env
                    # console :3003: owner@luxrocket.local / ADMIN_DEMO_PASSWORD, then register a passkey
make stack-seamless # same, but the demo operator's money moves through the reference
                    # Seamless Wallet v1 server (:8090) over signed HTTP, and webhooks
                    # are delivered to it (see `docker compose logs wallet-sim`)
make wallet-conformance             # conformance suite vs the reference wallet
make wallet-conformance URL=https://operator.example/lux PLAYER=test-1   # vs a real wallet
make demo-launch    # prints a launch link (acts as the operator)
open http://localhost:8000/demo/operator   # embedded via the SDK (postMessage handshake)
make e2e            # multi-browser end-to-end tests
make invariants     # money-correctness checks
make reconcile      # reconciliation now (also runs in the workers every 5 min / hourly)
```
