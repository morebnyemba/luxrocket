# LUX ROCKET — Architecture Package

Status: **APPROVED — Gate A passed 2026-10-10** (proposed defaults accepted for remaining open questions; see doc 20). Real-money operation is not covered by this approval.
Date: 2026-10-10
Scope: Phase 1 (architecture-first discovery). No application code, dependencies or visual assets exist yet.

## How to read this package

| # | Document | Purpose |
|---|----------|---------|
| 00 | [Executive overview](00-executive-overview.md) | Product summary, goals, non-goals, repository findings, key decisions |
| 01 | [Requirements specification](01-requirements-specification.md) | Functional/non-functional requirements, roles, acceptance criteria |
| 02 | [System architecture](02-system-architecture.md) | Context, components, topology, data ownership |
| 03 | [Architecture decisions (ADR register)](03-architecture-decisions.md) | Every consequential decision, alternatives, consequences |
| 04 | [Domain model & database](04-domain-model-and-database.md) | Entities, ERD, constraints, tenant isolation, money representation |
| 05 | [Django backend](05-django-backend-specification.md) | Django apps, APIs, auth, async/wallet strategy |
| 06 | [Elixir/Phoenix real-time](06-elixir-phoenix-realtime-specification.md) | Supervision tree, round coordinator, leases, recovery |
| 07 | [Game mathematics & fairness](07-game-mathematics-and-fairness.md) | Crash distribution, curve, RTP, verification protocol |
| 08 | [Betting, wallet & settlement](08-betting-wallet-and-settlement.md) | Two-panel model, bet lifecycle, idempotency, reconciliation |
| 09 | [Operator integration API](09-operator-integration-api.md) | Operator-facing API, wallet callbacks, webhooks, errors |
| 10 | [WebSocket protocol](10-websocket-protocol.md) | Browser ⇄ Phoenix protocol, schemas, sequencing, resync |
| 11 | [Iframe & embedding](11-iframe-and-embedding.md) | Launch flow, token exchange, CSP, postMessage contract |
| 12 | [Platform admin dashboard](12-platform-admin-dashboard.md) | Supplier back-office specification |
| 13 | [Operator dashboard](13-operator-dashboard.md) | Tenant portal specification |
| 14 | [Frontend & game rendering](14-frontend-and-game-rendering.md) | Next.js structure, Three.js scene, performance strategy |
| 15 | [Security & compliance](15-security-and-compliance.md) | Threat model, controls, regulatory dependencies, RG |
| 16 | [Testing & QA](16-testing-and-quality-assurance.md) | Test strategy across all layers |
| 17 | [Deployment & observability](17-deployment-and-observability.md) | Docker topology, environments, monitoring, DR |
| 18 | [UI/UX & asset plan](18-uiux-and-asset-plan.md) | Design system, screen inventories, asset sequence |
| 19 | [Implementation roadmap](19-implementation-roadmap.md) | Phases, dependencies, milestones, gates |
| 20 | [Open questions & assumptions](20-open-questions-and-assumptions.md) | Everything that needs a decision |
| 21 | [Requirements traceability matrix](21-requirements-traceability.md) | Requirement → component → doc → test → milestone |
| 22 | [Architecture review (approval gate)](22-architecture-review.md) | The concise review to approve or reject |
| 23 | [Implementation status](23-implementation-status.md) | What is built, interim deviations, how to run it |

## Conventions used throughout

- **Identifiers**: requirements `FR-xxx` / `NFR-xxx`, decisions `ADR-0xx`, open questions `OQ-xx`, threats `T-xx`, risks `R-xx`.
- **Normative language**: MUST / MUST NOT / SHOULD / MAY as in RFC 2119.
- **Illustrative**: every endpoint, payload and hostname in this package is a **proposed contract**. Nothing is implemented. Hostnames use the reserved placeholder domain `luxrocket.example`.
- **Money**: always integer minor units (`amount_minor`, BIGINT) plus ISO-4217 `currency`. Multipliers are integer ten-thousandths everywhere (`*_x10000`, e.g. `23456` = 2.3456×). Crash points and auto cash-out targets are restricted to the 0.01× grid (multiples of 100); manual cash-outs are priced at full 0.0001× precision. No floating-point money anywhere.
- **Time**: UTC, RFC 3339 with millisecond precision in JSON; `int64` Unix milliseconds on the real-time wire where noted.
- **IDs**: UUIDv7 (time-ordered) for all internal entity IDs unless stated; public operator-facing IDs are prefixed (`op_`, `ses_`, `rnd_`, `bet_`, `tx_`).

## Diagram index

| Diagram | Location |
|---------|----------|
| System context | 02 §2 |
| Component diagram | 02 §3 |
| Deployment diagram | 02 §6, 17 §2 |
| Django–Phoenix communication | 02 §4, 06 §8 |
| Player launch-session sequence | 11 §3 |
| Bet acceptance sequence | 08 §4 |
| Cash-out sequence | 08 §5 |
| Round lifecycle state machine | 06 §4 |
| Settlement & reconciliation sequence | 08 §7–8 |
| Entity-relationship diagram | 04 §3 |
| Tenant-isolation diagram | 04 §6 |
| WebSocket event flow | 10 §6 |
| Failure-recovery diagram | 06 §7 |
