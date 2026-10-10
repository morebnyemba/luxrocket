# 20 — Open Questions and Assumptions

Legend — **Approval**: *Required* = blocks the gate shown; *Default OK* = we proceed with the proposed default unless told otherwise.

## 1. Approval-critical (needed at Gate A or before the stated phase)

| ID | Question | Why it matters | Proposed default | Approval / gate |
|----|----------|----------------|------------------|-----------------|
| OQ-01 | Which markets? | — | **Resolved 2026-10-10: open to all markets; each market enabled only by the owner (`PLAT_OWNER`) via the market registry (ADR-026)** | Closed |
| OQ-02 | Team composition & access | — | **Resolved 2026-10-10: role-based access with levels L0–L4 (doc 15 §3.1)**; headcount still determines dates — roadmap stays in relative sizes until known | Closed (access) / headcount informational |
| OQ-10 | Void-on-malfunction policy for interrupted rounds | Player fairness, regulator acceptance, financial cost | Void uncashed bets & refund; pay journaled cash-outs (ADR-005) | Required — Gate A |
| OQ-12 | RNG certification path (hash-chain vs. certified RNG) per jurisdiction | May force a different outcome source | Hash-chain + drand salt; formula separable | Required — before Phase H, inform Phase C |
| OQ-13 | House edge / target RTP | Core economics & certification | **Resolved 2026-10-10: 3 % edge, 97 % RTP** | Closed |
| OQ-14 | Max multiplier M and max win per bet W (per currency) | Exposure, rules text | M = 10 000×; W = USD 10 000 equiv., set per currency | Required — Gate B→C |
| OQ-17 | Auto cash-out tie rule (target = crash) | Rules text; RTP exactness | Tie goes to player | Required — Gate B→C |
| OQ-18 | Manual cash-out pricing precision (0.01× vs 0.0001×) | Manual RTP drag up to ~1 % | **Resolved 2026-10-10: all multipliers stored as `*_x10000`; manual cash-outs priced at 0.0001×; display 2 dp** | Closed |
| OQ-07 | Is "LUX ROCKET" trademark-cleared in target markets? | Branding rework risk | Assume clear; check before public launch | Required — before Phase G |

## 2. Commercial & operator

| ID | Question | Proposed default | Approval |
|----|----------|------------------|----------|
| OQ-15 | Must we send a zero-value `settle` for losses? | Per-operator flag, default off | Default OK |
| OQ-27 | Negative GGR treatment in revenue share | Carry-forward within contract period | Required before billing reports |
| OQ-33 | Source of operator-side reconciliation data (API pull, file upload, none) | Optional API pull; file upload fallback | Default OK |
| OQ-34 | Do we need invoicing/billing in the platform, or reports only? | Reports only (export), invoicing outside | Default OK |
| OQ-28 | Group operators (one staff, many brands)? | One account per operator; revisit | Default OK |
| OQ-21 | After session revocation, should auto cash-outs of already-accepted bets still execute? | Yes (bet is already debited; payout is owed) | Default OK — confirm with operators |

## 3. Game & UX

| ID | Question | Proposed default | Approval |
|----|----------|------------------|----------|
| OQ-20 | Allow cancelling an accepted bet during the betting window? | Not in v1 (adds a rollback path under time pressure) | Default OK |
| OQ-22 | Allow changing auto target mid-flight? | No in v1 | Default OK |
| OQ-23 | Autoplay / auto-bet? | No (RG) | Default OK |
| OQ-24 | Show other players' cash-outs with amounts? | Multipliers + masked aliases only | Default OK |
| OQ-32 | Round timing defaults (7 s betting, 1 s grace, 2 s cooldown, λ) | As in doc 07 §1 | Default OK |
| OQ-35 | Launch locales | en first; then pt (Mozambique), sn/nd (Zimbabwe) subject to demand | Default OK |
| OQ-09 | One global stream vs per-jurisdiction streams at launch | One stream per environment; split only when required | Default OK |

## 4. Security, infra & compliance

| ID | Question | Proposed default | Approval |
|----|----------|------------------|----------|
| OQ-03 | Data-protection registration obligations (e.g. POTRAZ under Zimbabwe CDPA) | Counsel to confirm; budget for registration | Required before real money |
| OQ-04 | Is hosting outside Zimbabwe (Johannesburg) permitted for game & financial data? | Johannesburg hosting, subject to confirmation | Required before Phase G |
| OQ-05 | Managed Postgres with sync standby available in the chosen region/provider? | Prefer managed; fallback Patroni | Default OK — decide at scaffold |
| OQ-06 | KMS/HSM for KEKs and platform signing keys? | Cloud KMS where available; HSM for seed KEK if regulator requires | Required before real money |
| OQ-08 | Record retention periods per jurisdiction | 7 years financial/audit; 13 months sessions | Required before real money |
| OQ-11 | Accept drand as the public salt source (one call per chain)? | Yes; alternative: a published future block hash or a notarised public draw | Default OK |
| OQ-16 | Currency list and exponents (USD, ZWG, ZAR, ZMW, BWP, MZN, MWK…) | Verify each at onboarding against ISO 4217 and local practice | Default OK |
| OQ-19 | Breached-password checks via external k-anonymity API | Enabled (sends only hash prefixes) | Default OK |
| OQ-25 | DPoP-style sender-constrained game tokens before real money? | Yes, in Phase G | Default OK |
| OQ-26 | Admin console behind VPN/IP allowlist? | Yes | Default OK |
| OQ-29 | Make MFA mandatory for all operator portal users? | Mandatory for privileged actions; tenant-enforceable for all | Default OK |
| OQ-30 | Deploy tooling (Kamal vs Ansible+Compose) | Decide at scaffold; both meet ADR-021 | Default OK |
| OQ-31 | Production canary/smoke method permitted under real-money rules? | Staging + canary node; no synthetic real-money bets until regulator confirms | Required before real money |

## 5. Assumptions (explicit)

| ID | Assumption | If false |
|----|-----------|----------|
| AS-01 | Operators can implement idempotent debit/credit/rollback with rollback-of-unknown semantics | Custom adapters + status-query path; more reconciliation burden |
| AS-02 | Operators accept credits/rollbacks after session end | Contractual blocker for that operator |
| AS-03 | Players are pseudonymous to us; operators send no PII | DPA scope grows; data-protection obligations increase |
| AS-04 | One hosting region is acceptable for launch | Multi-region design needed (later ADR) |
| AS-05 | Team can operate Elixir in production | Consider ADR-002 alternative (reduce Phoenix role) — but the coordinator must live somewhere single-threaded and leased |
| AS-06 | Players in target markets mostly use Android Chrome/WebView on 3G/4G | Adjust tiers & budgets |
| AS-07 | Operators can host the SDK or use fragment mode | Provide additional server-side redirect launch variant (still no query tokens) |
| AS-08 | 2 betting panels are sufficient for launch | Component supports N; ruleset `panels` change |
| AS-09 | Sandbox may use virtual credits with no wallet at all | — |
| AS-10 | Clock sync ≤ 5 ms across nodes achievable with chrony in the chosen cloud | Use coordinator-receipt time instead of gateway stamp (slightly less player-favourable under load) |
