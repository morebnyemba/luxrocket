# 21 — Requirements Traceability Matrix

Milestones per doc 19 §3. Test strategy references doc 16 sections.

| Req | Description | Responsible component | Spec | Security / reliability implication | Acceptance criteria | Test strategy | Milestone |
|-----|-------------|-----------------------|------|-----------------------------------|---------------------|---------------|-----------|
| FR-001 | Operator-owned player identity; no LR accounts | Django `sessions`, `operators` | 04 §4.3, 09 §4 | No PII stored; pseudonymous refs | No player login endpoint exists; session create requires signed operator call | Route inventory; schema tests reject PII fields | M4 |
| FR-002 | Signed S2S session creation | Django `api_operator` | 05 §3.1, 09 §3 | Forged requests (T-01) | Invalid signature/skew/nonce ⇒ 401; valid ⇒ session | Signature vectors, replay tests (16 §2.1) | M4 |
| FR-003 | Single-use, short-lived launch tokens exchanged server-side | Django `sessions`, game `ParentBridge` | 11 §3–4 | Replay (T-02) | 100 parallel exchanges ⇒ 1 success; TTL ≤ 60 s | Concurrency test (16 §5); Playwright launch tests | M4 |
| FR-004 | No secrets/PII in iframe URLs | Launch route, SDK | 11 §2 | Leakage via logs/Referer | Query-token requests rejected; fragment cleared | Playwright + proxy log inspection | M4 |
| FR-005 | Session revocation ≤ 5 s on WS | Django + Phoenix | 06 §8, 11 §4 | Hijack containment (T-03) | Revoke ⇒ 4403 close within 5 s p95 | E2E timing test | M4 |
| FR-006 | No third-party cookies for core auth | Game app | 11 §4 | Browser compatibility | Game works with 3P cookies blocked (Safari/Firefox strict) | Playwright with cookie blocking | M4 |
| FR-010 | Global rounds: one sequence shared by all operators & jurisdictions | Phoenix coordinator (+ BetShards, ADR-025), PubSub | 06 §4–6, §5.7; ADR-020/025 | Consistency across nodes | 50 browsers on 3 nodes see identical crash & seed | E2E multi-player (16 §2.5) | M3 |
| FR-011 | Crash point fixed & committed before betting | Phoenix outcome + seed chain | 07 §2, §6 | Manipulation | Commitment at ROUND_OPEN verifies against revealed seed | Verifier cross-check; property tests | M3 |
| FR-012 | Client cannot learn crash early | Phoenix protocol, journal | 10 §7, 06 §5.4 | Disclosure (T-09) | No pre-crash event/log contains crash fields; auto cash-outs not before crossing | Schema & log-capture tests; timing tests | M3 |
| FR-013 | Single coordinator; no second outcome on failure | Lease/fencing, recovery | 06 §3, §7; ADR-004/005 | Split brain | Kill/partition tests ⇒ exactly one terminal fact per round | `:peer` cluster tests (16 §2.2) | M3 |
| FR-014 | Independent verification | Verify API, verifier (py/js) | 07 §6 | Trust | Third-party script reproduces crash from public data | Cross-language KAT | M3 |
| FR-015 | Planets are presentation only | Game scene | 14 §4.1 | RG (no near-miss) | No reward/flag tied to milestones; neutral copy | Content review; code review checklist | M2 |
| FR-020/021 | Two independent betting panels (N-capable) | game-core PanelMachine, Phoenix, Django bet uniqueness | 08 §1, 14 §2 | Duplicate bets (T-06) | Random interleavings keep panels independent; 1 bet/panel/round | Model-based tests; concurrency tests | M2 (UI), M3 (server) |
| FR-022 | Bet accepted only if open + debited + admitted | Phoenix + Django | 08 §3–4, ADR-024 | Late bets; uncertain debits | Late/unknown debits never ACTIVE; always refunded | Failure matrix tests (08 §10) | M4 |
| FR-023 | Cash-out only before crash at server time | Coordinator | 06 §5.1–5.3 | Race (T-10) | Zero accepted with stamp ≥ crash_at under 10 k burst | Concurrent cash-out load test | M3 |
| FR-024 | Server-side auto cash-out; tie to player | Coordinator | 06 §5.4, 07 §3 | Info leak | Auto pays exactly target iff target ≤ crash | Property tests | M3 |
| FR-025 | Duplicate submissions harmless | All layers | 08 §10 | Duplicate money | Same command id ×N ⇒ one effect | Concurrency & chaos tests | M4 |
| FR-026 | Limits & exposure server-side | Django place-bet | 05 §4, 08 §9 | Exposure | Exposure never exceeds limit with 1 000 concurrent bets | Concurrency test | M4 |
| FR-030 | Unique transaction ids, idempotent | Django wallet | 08 §2, 09 §6 | Duplicate payouts (T-07) | ≤ 1 succeeded tx per (bet, type) | Property + chaos tests | M4 |
| FR-031 | Unknown ≠ failed; reconciliation | wallet-worker, reconciliation | 08 §6, §8 | Lost money | Every UNKNOWN reaches terminal state; no silent drops | Fault-injection simulator | M4 |
| FR-032/033 | Immediate credit; void refunds | journal-consumer, wallet-worker | 08 §5, §7 | Settlement delay | Credit enqueued < 1 s after acceptance p99 (excluding operator) | E2E timing | M4 |
| FR-034 | Append-only financial history | Ledger | 04 §4.5, 08 §7.1 | Tampering (T-13) | UPDATE/DELETE on ledger denied; journals balance | DB role tests | M4 |
| FR-040–043 | Versioned operator API, signing, webhooks, sandbox | Django `api_operator`, `webhooks`, sandbox | 09 | API abuse | OpenAPI published; conformance suite passes | schemathesis; contract tests | M4 |
| FR-044 | Real money gated | Admin approvals | 12 §3.2, 19 §5 | Premature real-money | Cannot enable without four-eyes + evidence | Authz/approval tests | M5 |
| FR-050/053 | Platform admin modules & audit | apps/admin, Django `api_admin`, audit | 12 | Admin compromise (T-14) | AC-ADM-1..6 | Authz matrices, audit tests | M5 |
| FR-051/054 | Operator portal & tenant isolation | apps/portal, `api_portal`, RLS | 13, 04 §6, ADR-019 | Cross-tenant (T-04) | AC-OP-1..6 | Cross-tenant suite (CI-enforced) | M5 |
| FR-052 | No outcome editing | Admin API surface | 12 §1 | Integrity | No route writes `rt` or outcomes | Route inventory test | M5 |
| NFR-001 | Money correctness invariants | All | 16 §2.5 | Core | Zero invariant violations in chaos suites | Invariant SQL after every run | M6 |
| NFR-002–005 | Latency & capacity targets | Phoenix, Django | 16 §7 | Degradation | S1 targets met | Load tests S0–S3 | M6 |
| NFR-006/007 | Availability & recovery | Infra | 17 §6 | Outage, data loss | Restore test passes; failover within RTO | DR game-day | M6 |
| NFR-008 | Mobile performance | Game app, scene | 14 §4.4–4.5, §8 | Churn | Budgets met on reference devices | Device-lab perf tests | M2 (prototype), M6 (final) |
| NFR-009/011 | Security & tamper-evident audit | All, audit | 15 | Breach | Pen-test clear; audit chain verifies | Pen-test; chain verification job | M6 |
| NFR-010 | Privacy minimisation | Django schemas | 15 §5 | Data-protection exposure | No PII fields in schemas; contract forbids | Schema review; DPA | M4 |
| NFR-012 | Accessibility | Frontends | 14 §6, 12/13 ACs | Exclusion | WCAG 2.2 AA dashboards; game controls operable | axe + manual | M5/M6 |
| NFR-014 | Operator isolation under load | wallet adapters, workers | 05 §5, 08 §6 | Noisy neighbour | Slow operator doesn't affect others' bet p99 | Slow-operator load scenario | M6 |
| REG-01 | Regulatory dependencies identified & resolved per jurisdiction | Product/legal + platform hooks | 15 §7, 20 | Illegal operation | Checklist complete for pilot jurisdiction | Compliance review | M7 |
| REG-02 | Math independently reviewed & certified | Math + lab | 07 §8 | Certification | Review report + certificate references stored on ruleset | External | M7 |
| OPS-01 | Operational recovery (coordinator, DB, queues) | Phoenix, infra | 06 §7, 17 §6–9 | Availability | Runbooks exist and exercised | Chaos & DR game-day | M6 |

**Coverage check**: every brief-mandated area — operator-owned identity (FR-001..006), secure iframe launch (FR-003/004/006), two panels (FR-020/021), shared rounds (FR-010), authoritative outcomes (FR-011..013), cash-out integrity (FR-023/024), financial idempotency (FR-025/030/031), tenant isolation (FR-054), operator dashboard (FR-051), platform admin (FR-050), planetary rendering (FR-015), mobile performance (NFR-008), fairness verification (FR-014), regulatory dependencies (REG-01/02), operational recovery (OPS-01) — has an owner, a spec, an acceptance criterion and a test strategy.
