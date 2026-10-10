# 15 — Security and Compliance

> This document is an engineering threat model and control plan. It is **not legal advice, a licence, or a certification**. Regulatory positions must be confirmed by qualified counsel in each jurisdiction.

## 1. Assets & trust boundaries

| Asset | Classification | Primary threat |
|-------|----------------|----------------|
| Seed chains (root & checkpoints) | **Restricted-critical** | Outcome prediction by insiders/attackers |
| Operator wallet path & credentials | Restricted | Fraudulent debits/credits |
| Ledger & bets | Confidential | Tampering, duplicate payouts |
| Session/launch tokens, WS tickets | Restricted | Hijacking/replay |
| Staff accounts (esp. platform) | Restricted | Admin compromise |
| Player references | Confidential | Cross-tenant leakage, re-identification |
| Audit log | Confidential, integrity-critical | Tampering to hide abuse |

Trust boundaries: Internet ↔ edge; operator parent page ↔ game iframe; browser ↔ Game API/WS; Phoenix ↔ Django (internal); platform ↔ operator wallet; app ↔ data tier; staff ↔ dashboards.

## 2. Threat model (STRIDE-oriented)

| ID | Threat | Mitigations | Detection | Tests |
|----|--------|-------------|-----------|-------|
| T-01 | Forged operator API requests | Ed25519/HMAC signatures, ±300 s window, nonce store, per-kid revocation, optional mTLS/IP allowlist | Signature-failure rate alerts per kid/IP | Signature vectors, replay, skew, wrong-kid tests |
| T-02 | Launch-token replay / theft | Single-use (Postgres conditional update), ≤ 60 s, never in query string, fragment cleared, postMessage origin checks | Second-use attempts ⇒ security event | Replay & race tests (100 parallel exchanges ⇒ exactly 1 success) |
| T-03 | Session hijacking (stolen game-session token) | 15 min TTL, memory-only, session_version revocation, optional DPoP binding (OQ-25), WS tickets single-use | Concurrent sockets per session > 1 alert; geo/IP change heuristics (signal only) | Token-expiry, revoked-token, ticket-reuse tests |
| T-04 | Cross-tenant data leakage | TenantContext, RLS (FORCE), 404 on foreign ids, tenant-keyed caches | RLS violation errors logged; anomaly on cross-tenant 404 bursts | Cross-tenant matrix on every endpoint (CI-enforced) |
| T-05 | Forged WebSocket commands | Ticket auth, channel bound to session claims, command schema validation, ownership checks (bet ∈ session) | Protocol-error rate per session | Fuzzing of WS payloads; NOT_OWNER tests |
| T-06 | Duplicate bets | Unique (round, player, panel) and (round, session, command_id); idempotent replay | Constraint-violation counter | Concurrency tests: N parallel PLACE_BET |
| T-07 | Duplicate payouts | Unique (bet, CREDIT); deterministic tx ids; inbox dedupe; operator idempotency | Ledger invariant monitor | Chaos: duplicate/reordered relay messages |
| T-08 | Client-side manipulation | Client never decides acceptance, multiplier or payout; server stamps time | — | Modified-client test harness |
| T-09 | Outcome prediction/disclosure | Seeds encrypted (KEK outside DB), decrypted in coordinator memory only; crash never persisted/logged pre-crash; `rt_reader` excludes seed tables; information-leak rule for auto cash-outs | Access audit on seed tables & KMS; log scanners for crash fields pre-crash | Schema tests on pre-crash events; log-redaction tests; timing test (auto cash-out not before crossing) |
| T-10 | Cash-out race at crash | Single serialised coordinator; gateway stamp vs `crash_at`; crash grace; clock-skew guard | `late_after_finalise_total`, skew metrics | Property test: no accepted cash-out with stamp ≥ crash_at, under load |
| T-11 | Redis compromise | Redis non-authoritative; AUTH + TLS + private network; no secrets in Redis | Unexpected command patterns | Flush-Redis chaos test: money/outcomes unaffected |
| T-12 | RabbitMQ message replay/injection | Per-service vhost users with least privilege; TLS; consumers dedupe by `event_id`; Django validates fencing token & journal existence for critical facts (catch-up read) | Unknown-event-id alarms | Replay test; injected fake CASHOUT_ACCEPTED is rejected because it's absent from `rt.round_journal` |
| T-13 | Database privilege abuse | Separate roles per service; no superuser in apps; ledger UPDATE/DELETE revoked; audit hash chain + WORM anchors; break-glass access logged | pgaudit on privileged roles | Role-permission tests in CI (attempt forbidden writes) |
| T-14 | Admin compromise | MFA (WebAuthn for platform), step-up, four-eyes, IP allowlist/VPN, short sessions, no seed visibility, no outcome-edit paths | Login anomaly alerts, approval anomalies | Authz matrix tests; phishing-resistant MFA enforcement test |
| T-15 | Webhook forgery (to operators) / callback spoofing (to us) | Outbound signed with platform key; operators verify; inbound wallet *responses* only over TLS connections we initiated | Operator-reported verification failures | Signature tests |
| T-16 | Denial of service | CDN for static; edge rate limits; per-IP & per-session WS limits; connection caps per node; per-operator bulkheads; cheap rejection before Django calls | Saturation dashboards | Load & abuse tests (doc 16) |
| T-17 | Third-party iframe attacks (malicious parent, clickjacking) | `frame-ancestors` allowlist; postMessage strict origin+source; no sensitive data to parent; `sandbox` attributes recommended | CSP reports | Embedding tests from unlisted origins |
| T-18 | Supply-chain compromise | Lockfiles, pinned versions, `pnpm audit`/`pip-audit`/`mix_audit`, Dependabot/Renovate with review, SBOM (CycloneDX), image signing (cosign), minimal base images, SRI for SDK | Vulnerability scan alerts | CI gates on critical CVEs |
| T-19 | Insider collusion with player (seed leak) | Seed access restricted to coordinator runtime; ceremony four-eyes; staff key-holder rotation; anomaly detection on win rates per player/operator | Statistical monitoring: players with improbable success on high targets | Monitoring rule tests |
| T-20 | Wallet endpoint SSRF (operator-configured URLs) | URL allowlist rules (https only, public IPs only, no redirects to private ranges), egress proxy | Egress denials | SSRF tests |

## 3. Security controls baseline

- TLS 1.2+ (1.3 preferred) everywhere incl. internal (mTLS between Phoenix and Django; TLS to Postgres/Redis/RabbitMQ).
- Secrets: never in git/images; mounted files or secret manager; rotation runbooks (doc 17).
- Encryption at rest: disk encryption on all hosts/volumes; field-level for restricted columns; backups encrypted.
- Logging: no tokens, secrets, seeds, crash points pre-crash, operator session tokens, or raw wallet bodies; structured redaction allowlist (fields are logged only if explicitly allowed).
- OWASP ASVS L2 baseline; L3 for auth and money paths.
- Annual external penetration test + before real-money launch.

## 4. Audit requirements
- Hash-chained `audit.audit_event`; daily anchor (latest hash) written to WORM object storage and optionally emailed to an external auditor mailbox.
- Audited: staff auth events, all admin/portal mutations, credential lifecycle, approvals, real-money toggles, ruleset/stream changes, seed ceremonies/activations, data exports, platform-staff views of player-level data, maintenance actions.
- Retention ≥ 7 years for financial/audit (OQ-08 per jurisdiction).

## 5. Data protection
- Data minimisation: `player_ref` (operator's pseudonymous id), optional alias, country, currency. No names, emails, phone numbers, dates of birth, IDs or payment data — contractually prohibited in session requests.
- Controller/processor roles: operator is controller of player data; LUX ROCKET acts as processor → DPA required with each operator.
- Zimbabwe **Cyber and Data Protection Act [Chapter 12:07]** (2021) and its regulations: potential registration/licensing with POTRAZ as data controller/processor and rules on cross-border transfer — hosting in South Africa must be assessed (OQ-03, OQ-04). Equivalent laws: South Africa POPIA, Zambia Data Protection Act 2021, Botswana DPA 2018, Malawi Data Protection Act 2024 (verify), etc.
- Data subject requests routed via operator.

## 6. Responsible-gambling safeguards (platform features)

| Safeguard | Implementation |
|-----------|----------------|
| Operator-enforced eligibility | Operator only creates sessions for eligible players; `PUT /players/{id}/restrictions` lets operators push exclusions; Django rejects bets for restricted players |
| Jurisdiction restrictions | `operator_jurisdiction` allowlist checked at session creation (country from operator) |
| Stake & exposure limits | Per-operator × currency limits; max win; round exposure (doc 08 §9) |
| Session reminders | `SESSION_REMINDER` at operator/jurisdiction interval with elapsed time and net result for the session; requires acknowledgement |
| Time limits | Session hard limit ⇒ session ends gracefully after current round (active bets still settle) |
| Cooling-off / self-exclusion | Operator-owned; enforced through restrictions API and session revocation |
| Clear rules | In-game rules, RTP disclosure (incl. manual cash-out rounding note if applicable), max win, max multiplier, malfunction/void rule, instant-crash probability |
| Reporting | Per-player-ref session/bet summaries available to the operator for their RG programmes |
| Design ethics | No near-miss dramatisation; no "you almost won" messaging; no loss-chasing prompts; no autoplay in v1; no countdown pressure beyond the factual betting timer; cash-out feed shows multipliers, not amounts, by default |

## 7. Regulatory questions to resolve before real money (per jurisdiction)

1. Is an online crash game a permitted product category, and under which licence (casino/gaming vs. betting)? Who must hold it — operator only, or also the game supplier (supplier/manufacturer licence)?
2. Is technical certification by an accredited lab mandatory? Which standard (e.g. GLI-11/GLI-19-style requirements) and which labs are recognised?
3. RNG requirements: is a hash-chain/HMAC derivation acceptable, or is a certified RNG module required? Seeding and re-seeding requirements?
4. Required RTP minimums/disclosure and change-control procedures for game math.
5. Game malfunction rules (does void-on-malfunction comply?).
6. Server location and data localisation requirements; regulator access to systems/reports.
7. Record retention periods; reporting formats and frequency to the regulator.
8. Responsible-gambling mandatory features (reminders, limits, autoplay bans, minimum round duration).
9. Currency rules (e.g. ZWG vs. USD use in Zimbabwe; exchange-control implications for revenue share).
10. Tax treatment of supplier revenue share; withholding obligations.
11. AML obligations for a B2B supplier.

### 7.1 Market notes (to validate with counsel — indicative only)
| Market | Regulator (indicative) | Initial engineering stance |
|--------|------------------------|----------------------------|
| Zimbabwe | Lotteries and Gaming Board (Lotteries and Gaming Act) | Primary target; confirm licensing route for online games & suppliers |
| South Africa | National Gambling Board + provincial boards | **High risk**: online casino-style games are broadly prohibited under the National Gambling Act outside licensed categories; do not assume addressable (OQ-01) |
| Zambia | Betting Control and Licensing Board / relevant ministry | Confirm whether online casino-type games are licensable |
| Botswana | Gambling Authority | Confirm remote gaming licensing status |
| Mozambique, Malawi, Namibia | Respective gaming authorities | Confirm |

## 8. Compliance-driven engineering hooks
- Ruleset immutability and certificate reference (doc 12).
- Stream per jurisdiction if certification differs (ADR-020).
- Per-operator real-money gate with evidence references.
- Regulator report exports (format TBD per jurisdiction).
- Clock sync evidence (NTP/chrony logs retained).
