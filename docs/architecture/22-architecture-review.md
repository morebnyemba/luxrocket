# 22 — Architecture Review (Approval Gate A)

**Decision requested:** approve the architecture (ADRs 001–024 as Proposed) and answer or accept defaults for the approval-critical questions in §12, so Phase B and the scaffold can start. Real-money operation is **not** part of this approval.

## 1. Proposed architecture (summary)
One monorepo producing: a static embeddable game (Next.js export on CDN, Three.js), two Next.js consoles (platform admin, operator portal), a Django platform (operator API, game API, internal API, async wallet worker, journal consumer, Celery jobs), and a Phoenix cluster that terminates WebSockets and runs one leased, fenced **RoundCoordinator per round stream**. PostgreSQL is the only source of truth (schemas `platform`, `rt`, `audit`); Redis is cache-only; RabbitMQ carries at-least-once events backed by outbox/journal tables. Single Johannesburg region on Docker/Linux VMs, no Kubernetes.

## 2. Repository findings
Empty repository: no commits, no remote branches, no code, no conventions to preserve. This package establishes the first conventions. No secrets or configuration risks present.

## 3. Major decisions
- **ADR-002** Phoenix owns time & round facts; Django owns money & business records.
- **ADR-003/024** Phoenix's append-only round journal is the record of admission, cash-out, crash and void; debit ≠ inclusion.
- **ADR-004** Postgres lease + fencing token per stream; stale coordinators cannot write.
- **ADR-005** Void-on-malfunction (refund uncashed; pay journaled cash-outs).
- **ADR-006** Hash-chain provably-fair outcomes with a public post-commitment salt; exact integer crash formula; tabulated curve.
- **ADR-007** Seamless wallet with rollback-on-doubt.
- **ADR-009/022** postMessage launch handshake (fragment fallback), 15-min in-memory session tokens, single-use WS tickets.
- **ADR-012** Clients render the curve from `launch_at`; 4 Hz corrective ticks.
- **ADR-017/018** Separate frontends/origins; PixiJS deferred.
- **ADR-026 (Accepted)** Open to all markets; only the owner can enable a market, with evidence recorded.
- **ADR-019** Tenant isolation with scoped repositories **and** Postgres RLS.

## 4. Alternatives rejected
| Alternative | Why rejected |
|-------------|--------------|
| Django owns live rounds; Phoenix as fan-out only | Cash-out/crash serialisation via DB row locks under auto-cash-out bursts; worse latency; cash-out path depends on Django |
| Phoenix calls operator wallets | Duplicates business logic, violates mandated boundary (kept as fallback if bet latency fails) |
| `:global`/Horde/Redlock for coordinator ownership | Unsafe under partitions without fencing |
| Resume interrupted flights | Disadvantages manual players during the gap; harder to certify |
| Transfer wallet | Custody & licensing burden |
| Query-string launch tokens; third-party cookies | Token leakage; blocked by browsers |
| One Next.js app for game + consoles | Shared origin between a third-party-framed app and the admin console |
| 60 Hz multiplier streaming; Presence for online counts; `PLANET_REACHED` server events | Fan-out cost with no correctness benefit |
| Redis-backed single-use tokens | Replayable after failover |

## 5. Database & transaction ownership
`platform.*` written only by Django (`platform_rw`), `rt.*` only by Phoenix (`rt_rw`), `audit.*` INSERT-only. Money: BIGINT minor units; multipliers integer. Unique keys make duplicate bets (`round, player, panel`) and duplicate payouts (`bet, CREDIT`) impossible at the database. Ledger is double-entry and append-only. No HTTP call inside a DB transaction. Crash point and seed are never persisted before the crash.

## 6. Django–Phoenix boundary
| Phoenix decides | Django decides |
|-----------------|----------------|
| Cut-off, admission, launch, cash-out (manual/auto), crash, void, outcome derivation | Session validity, limits, exposure, debit, credit, rollback, ledger, settlement, reconciliation, reporting |

Channels: one synchronous fenced HTTPS call (place-bet) Phoenix→Django; journal facts Phoenix→Django via RabbitMQ (+ catch-up reads); platform events Django→Phoenix via RabbitMQ. The cash-out path has no synchronous dependency on Django.

## 7. Iframe authentication
Operator backend creates a session (Ed25519-signed) → receives a ≤ 60 s single-use launch token → SDK hands it to the iframe by origin-checked `postMessage` (or URL fragment fallback) → iframe exchanges it for a 15-min in-memory game-session token → single-use 30-s WS ticket → Phoenix. Per-operator `frame-ancestors` on a dynamic launch document; no `X-Frame-Options` on the game; no third-party cookies; reload ⇒ relaunch via parent callback.

## 8. Two-panel betting lifecycle
Independent client state machines per panel (IDLE → PLACING → PLACED → ACTIVE → CASHING_OUT → CASHED_OUT → SETTLED, with LOST/REJECTED/REFUNDING/RECOVERING branches). Server: PENDING_DEBIT → DEBITED → ACTIVE → CASHED_OUT/LOST/VOIDED; unknown debits and late debits are refunded. One bet per panel per player per round, enforced in the DB. Auto cash-outs run in the coordinator at curve crossing time; `CASHOUT_ACCEPTED` is sent only after the fact is journaled; `SETTLEMENT_CONFIRMED` after the operator acknowledges the credit.

## 9. Game mathematics risks
- Decided: 3 % edge / 97 % RTP (OQ-13) and 0.0001× manual pricing (OQ-18). Still open: cap, max-win and tie rule (OQ-14/17).
- Provable fairness does not exclude insider knowledge of the seed chain → key management is a primary control.
- RNG acceptability by regulators is unknown (OQ-12).
- Requires independent mathematical review and lab certification before production.

## 10. Security & regulatory dependencies
Threat model T-01..T-20 with controls and tests (doc 15). Regulatory: product legality and supplier licensing per market (South Africa flagged high-risk), certification standard & lab, RNG acceptance, malfunction rules, data protection registration and cross-border hosting (Zimbabwe CDPA), retention, RG mandates, currency/exchange-control and tax treatment. None of this package constitutes legal approval.

## 11. Performance & reliability risks
- Bet path latency is bounded by operator wallets (p99 ≤ 800 ms assumed); slow operators are isolated by bulkheads.
- Auto cash-out bursts at popular targets (e.g. 2.00×) concentrate load on one coordinator process — batch journaling mitigates; must be load-tested (S1: 2 000 at one tick).
- Reconnect storms after node loss — snapshots served from node-local ETS.
- Postgres is a hard dependency for gameplay by design (correctness over availability).
- Low-end Android rendering — HUD-first loading, quality governor, 2D fallback.
- All capacity figures are targets; nothing has been measured.

## 12. Assumptions & questions requiring approval
| ID | Decision | Default proposed |
|----|----------|------------------|
| OQ-02 | Team size & timeline | 3–5 engineers incl. 1 Elixir-capable |
| OQ-10 | Void-on-malfunction | Accept ADR-005 |
| OQ-12 | RNG path | Hash-chain + drand; swappable |
| OQ-14 | Max multiplier / max win | 10 000× / USD 10 000 equiv. |
| OQ-17 | Tie rule | Tie to player |
| OQ-07 | Trademark clearance | Check before public launch |
Plus assumptions AS-01..AS-10 (doc 20 §5), notably that operators accept the rollback-of-unknown and credit-after-session-end obligations.

## 13. Documentation created
`docs/architecture/`: README, 00 executive overview, 01 requirements, 02 system architecture, 03 ADR register, 04 domain model & database, 05 Django, 06 Phoenix, 07 game math & fairness, 08 betting/wallet/settlement, 09 operator API, 10 WebSocket protocol, 11 iframe & embedding, 12 platform admin, 13 operator portal, 14 frontend & rendering, 15 security & compliance, 16 testing, 17 deployment & observability, 18 UI/UX & assets, 19 roadmap, 20 open questions, 21 traceability, 22 this review. 13 required diagrams (index in README) and representative schemas for launch sessions, game sessions, bet/cash-out commands, round snapshots, WS events, wallet debit/credit/rollback, settlement responses and webhooks.

## 14. Proposed implementation sequence
Gate A → Scaffold (monorepo, CI, contracts, compose) → Phase B prototype (simulated rounds, two panels, first 3D zones) in parallel with Phase C engine and Phase D platform core → M3 shared authoritative rounds in the real UI → Phase E wallet & settlement → M4 operator sandbox E2E → Phase F dashboards → Phase G hardening (full assets, load/DR/pen-test) → Phase H certification and a single-operator real-money pilot.

---
**Stop point.** No application code, dependencies, assets or deployments have been created. Work resumes only after explicit approval.
