# 16 — Testing and Quality Assurance

## 1. Principles
- **Correctness tests gate money paths.** No merge to `main` touching `wallet`, `ledger`, `betting`, `settlement`, coordinator or outcome code without property/concurrency coverage for the change.
- **Contracts are tested from both sides** against `/contracts` (JSON Schema/OpenAPI).
- **Chaos is a test, not an incident.** Kill-coordinator, drop-messages, flush-Redis, slow-wallet scenarios run in CI nightly against the compose stack.
- Target numbers are set before measuring; results recorded in `docs/perf/` with environment details.

## 2. Test pyramid by layer

### 2.1 Django backend
| Type | Tools | Must cover |
|------|-------|-----------|
| Unit | pytest, pytest-django | Money arithmetic, limit checks, posting rules, state transitions |
| Property | Hypothesis | Idempotency: applying any journal fact sequence with duplicates/reorders yields the same final state; ledger journals always balance; payout recomputation equals Phoenix's for random (stake, k, max_win) |
| Authn/authz | pytest + generated matrices | Every endpoint × role allowed/denied (doc 12 §4, doc 13 §3.5) |
| Tenant isolation | pytest, route inventory | Every portal/operator endpoint × foreign tenant ⇒ 404; RLS-only test (repository filter disabled) still blocks |
| DB constraints | pytest against real Postgres (Testcontainers / compose) | Unique bet per panel, unique tx per type, ledger UPDATE/DELETE denied, RLS FORCE |
| Transactions & rollback | pytest | Exceptions in phase 2 leave no partial postings; no HTTP inside open transactions (instrumented check) |
| Wallet adapter | pytest + aiohttp test server | Timeout ⇒ UNKNOWN; 5xx ⇒ UNKNOWN; malformed 2xx ⇒ UNKNOWN; business reject ⇒ REJECTED; duplicate ⇒ success; circuit breaker; per-operator bulkhead |
| Webhook signing | pytest | Signature vectors; retries; dedupe headers |
| API contract | schemathesis against OpenAPI | Fuzzed requests never 500; responses validate |

### 2.2 Phoenix real-time
| Type | Tools | Must cover |
|------|-------|-----------|
| Unit | ExUnit | Curve table lookup, payout, k_eff, timers |
| State machine | ExUnit + StreamData | Random command/event sequences never violate: one outcome per round; no cash-out after crash; no admission after launch; journal seq gapless |
| WS auth | Phoenix.ChannelTest | Bad/expired/reused tickets rejected; revoked session closed with 4403 |
| Event ordering | ExUnit | `seq` monotonic per stream across nodes; snapshot + events reconstruct state |
| Reconnect/resync | ChannelTest + simulated gaps | Client model converges after random drops |
| Coordinator failure | Multi-node test cluster (`:peer`) | Kill holder at each state ⇒ exactly one VOID, no second outcome, fencing rejects stale writes |
| Split-brain | `:peer` + network partition simulation (block distribution, keep DB) | Two coordinators: only token holder writes; the other halts within TTL |
| Duplicate commands | ChannelTest | Same command_id ×N ⇒ one effect |
| Concurrent cash-out | Load harness | 10 k cash-outs within ±20 ms of crash: zero accepted with stamp ≥ crash_at; all stamped < crash_at accepted (given grace) |
| Info-leak | ExUnit + log capture | No pre-crash message/log/journal contains crash fields; auto cash-out facts timestamped ≥ crossing time |

### 2.3 Game mathematics
- Known-answer vectors for `LR-CRASH-1` shared by Python, Elixir and TS implementations (CI cross-check 10⁶ seeds).
- Distribution tests (χ², KS) on ≥ 10⁸ outcomes (nightly, not per PR); tail frequencies at listed thresholds within 99.9 % CIs.
- RTP simulations for fixed targets, max-win caps and scripted manual strategies; CI asserts within tolerance for 10⁷-round smoke runs.
- Boundary tests: r = 0, r = 2⁵²−1, raw just below/above 101, M clamp, tie at auto target = crash.
- **Independent mathematical review** (external) — tracked as a release gate, not a CI job.

### 2.4 Frontend
| Type | Tools | Must cover |
|------|-------|-----------|
| Unit / model | Vitest; model-based tests over `game-core` machines | Two-panel independence under random interleavings; recovery from any state via snapshot |
| Component | Testing Library | Panel states render correct buttons/labels; disabled during in-flight commands |
| Iframe launch | Playwright with a test parent page on a second origin | Handshake success; wrong-origin parent ⇒ no exchange; token reuse ⇒ relaunch flow; fragment mode clears hash |
| Token expiry | Playwright + fake clock | Renewal before expiry; expired ⇒ relaunch message |
| Responsive | Playwright screenshots at 320×480, 360×740, 740×360, 768×1024, 1440×900 | No overlap of HUD and critical controls |
| Accessibility | axe-core + manual screen-reader pass (TalkBack, VoiceOver) | WCAG 2.2 AA for dashboards; game controls operable |
| Network | Playwright with throttling & offline toggles | Reconnect banner, recovery, no duplicate commands |
| Rendering perf | Playwright + CDP tracing on real devices (device lab / BrowserStack-like) | fps per tier, memory, TTI budgets (NFR-008) |

### 2.5 End-to-end
Compose stack: Postgres, Redis, RabbitMQ, 3 Phoenix nodes, Django processes, operator simulator (with fault injection), game app.
1. **Multi-player same round**: 50 headless browsers (Playwright) across 3 rt nodes, each with 2 panels (different auto targets + manual cash-outs) ⇒ all receive identical `crash_x10000`/seed; each panel settles independently; ledger totals equal sum of wallet-simulator effects.
2. **Latency & loss**: toxiproxy 200 ms ± 100 ms, 3 % loss on clients; on wallet 0–2 s latency.
3. **Browser suspension**: background tabs during flight ⇒ correct state on resume.
4. **Service restarts**: kill rt nodes, Django internal, wallet-worker, RabbitMQ node, Redis; verify invariants after convergence.
5. **Duplicate requests**: client retry storms, relay duplicates, wallet duplicate responses.

**Global invariants checked after every E2E/chaos run** (SQL assertions):
- Each round has exactly one terminal fact; crash_x10000 equals formula(seed).
- Each admitted bet has exactly one terminal settlement; no bet both CASHED_OUT and REFUNDED.
- Per bet ≤ 1 DEBIT, ≤ 1 CREDIT, ≤ 1 ROLLBACK succeeded; simulator wallet balance changes equal ledger `player_wallet` sum.
- No CASHOUT_ACCEPTED with `received_at ≥ crash_at`.
- Ledger journals sum to zero.

## 3. Contract tests
- `/contracts` JSON Schemas validated against: Django serializers (generated examples), Elixir encoders, TS generated types (compile-time) and runtime validators.
- Operator wallet conformance suite (published to operators; also used for custom adapters).
- Backward compatibility check: schema diff in CI blocks breaking changes within a major version.

## 4. Security tests
- SAST: Semgrep (Python/TS/Elixir rules), Sobelow (Phoenix), Bandit; secrets scanning (gitleaks) pre-commit and CI.
- Dependency: pip-audit, pnpm audit, mix_audit; container scan (Trivy).
- DAST: OWASP ZAP baseline on staging for admin/portal/game API.
- Targeted: authz matrices, tenant isolation, replay tests, CSP/frame tests, SSRF on wallet URLs, WS fuzzing.
- External pen-test before real money; repeat annually and after major changes.

## 5. Concurrency test catalogue
| Scenario | Expectation |
|----------|-------------|
| 100 parallel launch-token exchanges | exactly 1 success |
| 50 parallel PLACE_BET same panel (two tabs) | exactly 1 bet |
| Cash-out spam same bet (20 parallel) | exactly 1 CASHOUT_ACCEPTED |
| Debit response arriving 1 ms after launch | bet excluded + rolled back |
| Relay delivering facts out of order | consumer buffers; final state identical |
| Exposure limit with 1 000 concurrent bets | never exceeded |

## 6. Environments for testing
`local` (compose), `ci` (ephemeral compose), `staging` (production-like topology, synthetic operators), `sandbox` (operator-facing, stable), `production`.

## 7. Load-testing plan

Tooling: k6 (HTTP), a custom Elixir/Go WS load client (thousands of sockets per generator, implementing the protocol incl. bets/cash-outs), operator wallet simulator with latency distributions.

| Stage | Sockets | Bets/round | Auto cash-out cluster | Wallet p99 | Pass criteria |
|-------|--------:|-----------:|----------------------|-----------:|---------------|
| S0 smoke | 500 | 300 | 200 @ 2.00× | 200 ms | Invariants hold |
| S1 target | 10 000 | 3 000 | 2 000 @ 2.00× | 800 ms | NFR-002/003/004 met; 0 invariant violations |
| S2 growth | 50 000 | 15 000 | 10 000 @ 1.50× | 800 ms | Identify bottleneck; document scaling step |
| S3 stress | until failure | — | — | 2 s + 5 % timeouts | Graceful degradation: bets rejected fast, no money errors |

Special scenarios: reconnect storm (S1 sockets reconnect within 5 s), slow-operator isolation (one operator at 5 s latency, others unaffected), relay backlog drain (RabbitMQ down 10 min), Postgres failover during flight (expected void).

Bottleneck criteria recorded per run: coordinator mailbox length & command latency, journal flush latency, Django internal p99 and DB pool saturation, PubSub fan-out time, node CPU/memory/scheduler utilisation, Postgres CPU/IO/locks, RabbitMQ queue depth.

## 8. Quality gates (CI)
Lint/format/typecheck all languages; unit + property tests; contract checks; tenant-isolation route inventory; security scans; frontend bundle-size budget check (fail if game initial JS > 250 KB gz); migration safety check (no destructive migrations without explicit marker).
