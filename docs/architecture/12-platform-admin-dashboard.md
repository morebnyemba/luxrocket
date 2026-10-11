# 12 — Platform Admin Dashboard

App: `apps/admin` → `https://admin.luxrocket.example` (IP allowlist/VPN recommended, OQ-26). API: `/api/admin/v1`, same origin, path-routed to Django by the reverse proxy (no CORS; host-only `__Host-` cookies). Realm `PLATFORM` only. `frame-ancestors 'none'`.

## 1. Principles
- Least privilege; MFA mandatory; step-up for privileged actions.
- No UI or API path can read a future crash point, read seeds before reveal, or edit an active round. The admin API has **no** endpoint that writes `rt.*`; operational controls (pause/drain stream) are requests that Phoenix applies at round boundaries.
- Financial history is read-only; corrections are approved adjustments.
- Every mutation ⇒ audit event; four-eyes (`approval_request`) for the actions marked ★.
- Every read of tenant-identifying data (player-level views, exports) ⇒ audit event.

## 2. Navigation

```
Overview
Operators            ▸ list ▸ operator detail (tabs: Profile, Integration, Config, Limits, Domains, Credentials, Streams, Commercial, Activity)
Games                ▸ Games & versions ▸ Rulesets ▸ Streams ▸ Seed chains ▸ Releases & rollout ▸ Maintenance
Rounds               ▸ search ▸ round detail (journal, bets summary, verification)
Finance              ▸ Bets ▸ Transactions ▸ Settlements ▸ Pending/failed ▸ Reconciliation ▸ Adjustments
Analytics            ▸ Platform ▸ By operator ▸ Reliability
Security & Audit     ▸ Staff users ▸ Roles ▸ Audit log ▸ Credential events ▸ Sessions ▸ Incidents ▸ Approvals
System               ▸ Health ▸ Queues ▸ Feature flags
```

## 3. Modules

### 3.1 Overview
Cards & charts (all from Prometheus/metrics API or reporting tables, refreshed ≤ 30 s): active operators (LIVE/SANDBOX), stream status and current round state, concurrent sockets, bet/cash-out rates, API error rates (operator API, game API, internal), wallet success/latency per operator, settlement backlog (`payouts_payable` age), relay lag, void count (24 h), open reconciliation items by severity, open incidents, integration alerts (circuit breakers open, webhook failures).

### 3.2 Operator management
| Capability | Notes |
|-----------|-------|
| Onboard operator (wizard) | Legal entity, contacts, jurisdictions, currencies, stream, integration model, commercial metadata (rev-share %, contract ref, start date) |
| Status lifecycle | ONBOARDING → SANDBOX → LIVE ↔ SUSPENDED → TERMINATED; LIVE requires checklist (★) |
| Markets (owner only) | Registry of all countries; set DISABLED / SANDBOX / REAL with evidence reference; visible to all platform roles, editable only by `PLAT_OWNER` (ADR-026). Disabling REAL revokes live sessions in that country. |
| Real-money enablement ★ | Requires: signed contract flag, licence evidence reference, conformance tests passed, certification reference for the stream's ruleset, security review sign-off |
| Allowed domains | Add/remove exact origins; verification by DNS TXT or file (recommended) |
| Credentials | View metadata (kid, alg, created, last used, expiry); revoke; platform cannot view private keys or HMAC secrets after creation |
| Currencies & limits | Per currency min/max stake, max win, round exposure; within platform-defined ceilings |
| Wallet endpoint | URL, timeouts, concurrency, settle flag; "Run conformance test" |
| Suspend / reactivate ★ (reactivate) | Reason mandatory; suspension stops new sessions immediately and revokes active sessions (configurable: let active bets finish — always true for already accepted bets) |

### 3.3 Game management
| Capability | Notes |
|-----------|-------|
| Game versions | Create DRAFT, attach build hashes/asset manifest, move to CERTIFYING/APPROVED ★/ACTIVE/RETIRED |
| Rulesets | Create from template; parameters schema-validated; RTP calculator preview; APPROVED ★ requires certificate reference; immutable after approval |
| Streams | Bind version + ruleset (applies at next round boundary ★), assign operators, set mode |
| Seed chains | Ceremony status, terminal hash, salt source/round, usage %, activation ★. Seeds never displayed. |
| Controlled rollout | Per operator pin / percentage of operators / sandbox first |
| Maintenance | Schedule window (notifies operators by webhook ≥ 24 h ahead when possible); drain stream at round boundary; emergency stop (★ after the fact review) — voids nothing already completed; current round finishes or is voided per ADR-005 if a fault |
| Rollback | Re-point stream to a previous APPROVED version/ruleset ★ |

### 3.4 Financial operations
- Search bets/transactions by id, operator, round, player ref (audited), status, date.
- Bet detail: lifecycle timeline (journal facts + wallet attempts + ledger postings).
- Pending/failed queue: UNKNOWN debits awaiting rollback, credits in retry, NEEDS_ATTENTION — actions: retry now, mark operator-confirmed (with evidence), request adjustment ★.
- Reconciliation: runs, items, resolution workflow with notes; export.
- Adjustments ★: manual `ADJUSTMENT_CREDIT` with reason, evidence, approver ≠ requester.
- Refunds/cancellation: round void is not manual; manual refund of a specific bet only through adjustment workflow.

### 3.5 Analytics — metric definitions
| Metric | Definition |
|--------|-----------|
| Turnover (stakes) | Σ stakes of bets with status ∈ {ACTIVE→terminal: CASHED_OUT, LOST} (excludes REJECTED, EXCLUDED, VOIDED) |
| Wins (payouts) | Σ `payout_minor` of CASHED_OUT bets |
| GGR | Turnover − Wins (per operator × currency; may be negative) |
| Refunds | Σ stakes of EXCLUDED/VOIDED bets (reported separately, not in GGR) |
| Actual RTP | Wins / Turnover (reported with sample size; meaningful only at volume) |
| NGR | Operator-defined (GGR − bonuses − taxes − …); **not computed by LUX ROCKET**; shown only if operator supplies figures |
| Supplier revenue | Contracted rev-share % × GGR for the billing period, with the contract's negative-GGR rule (carry-forward vs. reset, OQ-27) |
| Unique players | Distinct `player_ref` per operator (pseudonymous; never cross-operator de-duplication) |
| Rounds | Rounds reaching CRASHED (voided counted separately) |
| Availability | Successful round cycles / scheduled round cycles; API success rates |
Time-series by hour/day/month; FX-normalised view labelled "indicative".

### 3.6 Security & audit
Staff users & roles; MFA status; sessions (revoke); audit log search with hash-chain verification indicator; credential events (created/rotated/revoked/first used); security incidents register; approvals queue.

## 4. Roles (platform realm)

| Permission ↓ / Role → | OWNER | SUPERADMIN | OPS | FINANCE | RISK | SUPPORT | GAME_RELEASE | AUDITOR |
|-----------------------|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **Enable/disable markets** | **✓ (only)** | | | | | | | |
| View overview/health | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Manage operators (non-financial) | ✓ | ✓ | ✓ | | | | | |
| Enable real money ★ | ✓ | ✓ (+approver) | | | ✓ approver | | | |
| Manage credentials metadata/revoke | ✓ | ✓ | ✓ | | | | | |
| Game versions/rulesets/streams ★ | ✓ | ✓ | | | approver | | ✓ | |
| Seed-chain activation ★ | ✓ | ✓ | | | approver | | ✓ | |
| Maintenance / drain | ✓ | ✓ | ✓ | | | | ✓ | |
| View bets/transactions | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (masked) | | ✓ |
| Player-level search (audited) | ✓ | ✓ | | ✓ | ✓ | ✓ | | ✓ |
| Adjustments ★ | ✓ | request/approve | | request | approve | | | |
| Reconciliation resolve | ✓ | ✓ | | ✓ | ✓ | | | |
| Staff & roles | ✓ | ✓ | | | | | | |
| Audit log read | ✓ | ✓ | | | ✓ | | | ✓ |
No role can approve its own request (exception: `PLAT_OWNER` market changes, ADR-026). Exactly one OWNER; SUPERADMIN count ≤ 3; all with hardware-key MFA.

## 5. Key workflows
1. **Operator go-live**: onboarding → sandbox credentials → conformance tests pass → domains verified → commercial/licence evidence → real-money request ★ → approved → status LIVE, `real_money_enabled = true` → webhook `game.availability_changed`.
2. **Ruleset release**: draft → math review attached → certification reference → approve ★ → schedule stream binding → applied at next round boundary → audit.
3. **Credential compromise**: revoke key (immediate) → revoke operator sessions (optional) → incident record → operator notified.
4. **Stuck credit**: alert → finance views timeline → contacts operator → operator confirms credit landed (evidence) → mark resolved (no money moved) or adjustment ★.

## 5a. As built (v1)
- API `backend/luxrocket/console` at `/api/admin/v1`; UI `apps/admin` (static export behind nginx proxying only
  `/api/admin/`). Shared UI/API code with the operator portal lives in `packages/console-kit`.
- Sign-in: password, then a **WebAuthn passkey with user verification** every time; first sign-in can only
  register a key. Challenges are session-bound, single-use, 5 min; origin + RP id checked; sign-counter
  regressions refused. Sessions 4 h / 15 min idle (`__Host-lr_admin`). Step-up = a passkey assertion within
  5 min for every privileged write.
- Permissions are the §4 matrix verbatim (`console/auth.py`); `tests/test_console.py` generates the role ×
  endpoint allow/deny matrix from it (AC-ADM-1), proves no route can write round data (AC-ADM-2), and that
  self-approval is refused by the view **and** a database CHECK constraint (AC-ADM-3).
- Built: overview, markets (owner only; closing REAL revokes live real-money sessions), operator onboarding
  (with first portal owner), immediate suspend, credential revocation, four-eyes **real-money enablement**
  (conformance passed on the current wallet URL + contract/licence/certification/security evidence + a REAL
  market) and **reactivation**, finance queue with retry, bet timeline (wallet attempts + ledger),
  audited player search (masked for support), discrepancy resolution, read-only rounds with journal,
  staff (one owner, ≤ 3 superadmins appointed by the owner, passkey reset), audit search + chain verification.
- Not yet: game versions / rulesets / streams / seed-chain activation, maintenance & drain requests to Phoenix,
  adjustments (`ADJUSTMENT_CREDIT`), analytics time series, incidents register, exports, IP allowlist.

## 6. Acceptance criteria
- AC-ADM-1: Every endpoint has an authorization test per role (allowed/denied matrix generated from §4).
- AC-ADM-2: Attempting any write to `rt` data or round outcome via admin API is impossible (no route) — verified by route inventory test.
- AC-ADM-3: Four-eyes actions cannot be completed by a single user (test with same user approving ⇒ rejected).
- AC-ADM-4: Every mutation produces exactly one audit event with before/after.
- AC-ADM-5: Overview loads ≤ 2 s p95 with 100 operators of data.
- AC-ADM-6: WCAG 2.2 AA (axe automated + manual keyboard pass).
