# 01 — Requirements Specification

## 1. User roles

| Role | Where | Description |
|------|-------|-------------|
| **Player** | Embedded game | Authenticated by the operator. Known to LUX ROCKET only by a pseudonymous `player_ref` scoped to the operator. |
| **Operator system** | Operator API | The operator's backend: creates sessions, receives wallet callbacks and webhooks. |
| **Operator staff** | Operator portal | `OP_OWNER`, `OP_ADMIN`, `OP_DEVELOPER`, `OP_FINANCE`, `OP_SUPPORT`, `OP_VIEWER` (doc 13 §4). |
| **Platform staff** | Platform admin | `PLAT_OWNER` (exactly one account: the founder), `PLAT_SUPERADMIN`, `PLAT_OPS`, `PLAT_FINANCE`, `PLAT_RISK`, `PLAT_SUPPORT`, `PLAT_GAME_RELEASE`, `PLAT_AUDITOR` (doc 12 §4). |
| **Verifier** | Public verify page / offline script | Anyone (player, regulator, auditor) checking a completed round. |
| **Service principals** | Internal | `django-api`, `django-worker`, `wallet-worker`, `phoenix-rt`; each with distinct credentials and DB roles. |

## 2. Operator responsibilities (contractual, not enforceable by code)

The integration agreement MUST oblige the operator to:

1. Authenticate players and only request sessions for eligible, non-excluded players in permitted jurisdictions.
2. Implement the wallet contract (doc 09): idempotent `debit`, `credit`, `rollback`, keyed by our `transaction_id`.
3. **Accept credits and rollbacks unconditionally** for previously debited bets, even if the player's session has ended, the player has since self-excluded, or the account is locked. (A win cannot be refused.)
4. Treat a `rollback` for an unknown `transaction_id` as a successful no-op, and reject any later `debit` with that id.
5. Notify us (API call) of session revocation, self-exclusion and account closure.
6. Serve the embed only on registered origins.
7. Hold the licence(s) required to offer the game to its players.

## 3. Functional requirements

### 3.1 Identity and sessions
| ID | Requirement |
|----|-------------|
| FR-001 | Players MUST NOT create accounts or authenticate with LUX ROCKET. Identity is the operator's `player_ref` + operator. |
| FR-002 | Operator backends MUST create launch sessions via a signed server-to-server API. |
| FR-003 | Launch tokens MUST be single-use, ≤ 60 s TTL, audience-bound, and exchanged server-side for scoped game-session credentials. |
| FR-004 | No permanent credential, wallet credential or PII may appear in an iframe URL. |
| FR-005 | Operators MUST be able to revoke a single session or all sessions of a player; revocation takes effect on the WebSocket within 5 s (target). |
| FR-007 | The platform is open to all markets. A player country may be served only if the platform `market` is enabled for that mode (sandbox/real) **and** the operator is permitted in it. Only `PLAT_OWNER` can enable, disable or change a market's mode. |
| FR-006 | Core authentication MUST NOT depend on third-party cookies. |

### 3.2 Game and rounds
| ID | Requirement |
|----|-------------|
| FR-010 | Rounds are shared by every player on a round stream; all observe the same launch time and crash point. |
| FR-011 | Each round's crash point MUST be determined and committed before betting opens and MUST NOT change. |
| FR-012 | The client MUST NOT be able to determine the crash point before the crash. |
| FR-013 | Exactly one coordinator controls a round at any time; coordinator failure MUST NOT produce a second outcome or reset a flight. |
| FR-014 | Every completed round MUST be independently verifiable from published data. |
| FR-015 | Planetary milestones are presentation only; reaching one confers no reward. |
| FR-016 | Round history (last N crash points) and per-round verification data are available to players. |

### 3.3 Betting
| ID | Requirement |
|----|-------------|
| FR-020 | Each player has ≥ 2 independent betting panels per round; the component model supports N. |
| FR-021 | Per panel: stake, bet id, acceptance status, optional auto cash-out target, cash-out state, potential return, settlement status, error/recovery state. |
| FR-022 | A bet is accepted only when the round is in `BETTING_OPEN` at coordinator receipt time AND the operator debit succeeded AND the coordinator admitted it before launch. |
| FR-023 | A cash-out is accepted only if received by the coordinator strictly before the crash instant; the multiplier is the server multiplier at receipt time. |
| FR-024 | Auto cash-out is evaluated by the server, not the client. A target equal to the crash point succeeds. |
| FR-025 | Duplicate submissions (double clicks, retries, reconnects) MUST NOT create duplicate bets or cash-outs. |
| FR-026 | Stake min/max, max win per bet and per-round exposure limits are enforced server-side per operator and currency. |
| FR-027 | The frontend displays potential return but never computes the authoritative payout. |
| FR-028 | Bets may be queued client-side for the next round; nothing is sent until `ROUND_OPEN`. |

### 3.4 Wallet and settlement
| ID | Requirement |
|----|-------------|
| FR-030 | Every financial command has a unique, stable `transaction_id` and is idempotent. |
| FR-031 | Unknown outcomes (timeouts) are resolved by reconciliation, never by assuming failure. |
| FR-032 | Cash-out wins are credited immediately after acceptance, not at round end. |
| FR-033 | Voided rounds refund all uncashed accepted stakes. |
| FR-034 | Financial history is append-only; corrections are new entries. |
| FR-035 | Daily automated reconciliation against operator reports (when provided) and internal invariants. |

### 3.5 Operator integration
| ID | Requirement |
|----|-------------|
| FR-040 | Versioned operator API (`/operator/v1`), explicit schemas, stable identifiers, documented error codes. |
| FR-041 | Request signing, replay window, idempotency keys, rate limits. |
| FR-042 | Signed webhooks with retries and a delivery log. |
| FR-043 | Sandbox environment with simulated wallet and virtual credits, available to every onboarded operator. |
| FR-044 | Real-money mode disabled per operator until an explicit, audited enablement after all gates. |

### 3.6 Dashboards
| ID | Requirement |
|----|-------------|
| FR-050 | Platform admin: overview, operators, game management, financial ops, analytics, security & audit (doc 12). |
| FR-051 | Operator portal: overview, integration, permitted config, reports, users & access (doc 13). |
| FR-052 | No UI path or API may modify an active round's outcome. |
| FR-053 | Every administrative mutation produces an audit event. |
| FR-054 | Operator data isolation enforced on every backend request and at the database. |

## 4. Non-functional requirements

Targets are **initial proposals to be validated by load tests** (doc 16 §7); none is claimed as achieved.

| ID | Category | Requirement / target |
|----|----------|----------------------|
| NFR-001 | Correctness | Zero duplicate debits/credits per `transaction_id`; zero accepted cash-outs at or after crash time. Verified by property and concurrency tests. |
| NFR-002 | Latency | Cash-out decision (coordinator receipt → `CASHOUT_ACCEPTED` sent) p99 ≤ 50 ms, excluding client network. |
| NFR-003 | Latency | Bet placement (coordinator receipt → `BET_ACCEPTED`) p99 ≤ 1.2 s including operator debit with operator p99 ≤ 800 ms. |
| NFR-004 | Fan-out | Server event → client delivery p95 ≤ 250 ms within the hosting region under target load. |
| NFR-005 | Capacity (stage 1 target) | 10 k concurrent sockets, 2 k bets/s burst, 5 k cash-outs/s burst at a single multiplier (auto cash-out cluster), on the reference deployment. Stages 2–3 in doc 16. |
| NFR-006 | Availability | 99.9 % monthly for gameplay (proposal; measured, not promised, until SLO tooling exists). |
| NFR-007 | Recovery | RPO 0 for committed financial records (synchronous replica), ≤ 5 min for analytics; RTO ≤ 30 min for full region service loss (doc 17). |
| NFR-008 | Client performance | Interactive ≤ 3 s on reference low-end Android (Moto E-class, 2–3 GB RAM) over "Fast 3G"; initial JS ≤ 250 KB gz; sustained ≥ 30 fps at "low" quality. |
| NFR-009 | Security | OWASP ASVS L2 for all web surfaces; L3 controls for authentication and financial paths. |
| NFR-010 | Privacy | No player PII stored beyond `player_ref`, optional display alias, country, currency. |
| NFR-011 | Auditability | Tamper-evident audit log (hash-chained) for admin and financial actions. |
| NFR-012 | Accessibility | WCAG 2.2 AA for dashboards; game controls keyboard/screen-reader operable; reduced-motion mode. |
| NFR-013 | Operability | Deployable and recoverable by a team of 2–4 engineers using documented runbooks. |
| NFR-014 | Isolation | One operator's traffic spike or wallet outage MUST NOT degrade other operators' bet processing (per-operator concurrency pools). |

## 5. Acceptance criteria (phase-level)

Detailed per-requirement criteria are in doc 21. Phase-level exit criteria:

- **AC-B (prototype)**: two-panel UI drives a locally simulated round; 30 fps on reference device at low quality; usability test: 4/5 first-time users place and cash out a bet within 30 s without instructions.
- **AC-C (engine)**: 1 M simulated rounds match the theoretical distribution (doc 07 §8); coordinator kill tests produce no duplicate outcomes; reconnect resync works under packet loss.
- **AC-D/E (platform + wallet)**: contract tests against the reference operator simulator including timeouts, duplicates and 5xx; zero ledger invariant violations in chaos tests.
- **AC-F (dashboards)**: automated cross-tenant access tests (every endpoint × foreign tenant) return 404.
- **AC-G (hardening)**: load-test stage 1 met; external penetration test with no open high/critical findings.
- **AC-H (commercial)**: certification and licensing checklist complete for at least one jurisdiction.
