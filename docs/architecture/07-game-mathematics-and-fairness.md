# 07 — Game Mathematics and Fairness

> **Status: PROPOSAL — not production-ready.** This model must be independently reviewed by a qualified game mathematician and certified by an accredited test laboratory for each target jurisdiction before real-money use. "Provably fair" here means *players can verify that a round's outcome was fixed in advance and computed by the published formula*. It does not prove the absence of insider knowledge (§7.4), and it is not a regulatory certification.

## 1. Parameters (per `Ruleset`, versioned and hashed)

| Symbol | Ruleset field | Proposed default | Approval |
|--------|---------------|------------------|----------|
| e | `house_edge_bp` | **300 bp (3 %, RTP 97 %)** | Decided 2026-10-10 (OQ-13) |
| λ | `curve_lambda_per_ms` | 6 × 10⁻⁵ ms⁻¹ (2× at 11.55 s) | Product |
| M | `max_multiplier_x10000` | 100 000 000 (10 000×) | **OQ-14** |
| W | `max_win_minor` (per operator × currency) | e.g. USD 10 000.00 | **OQ-14** |
| — | `min_auto_cashout_x10000` | 10 100 (1.01×) | — |
| — | `multiplier_unit` | 1/10 000 (all multipliers are `*_x10000` integers) | Decided 2026-10-10 (OQ-18) |
| — | `betting_window_ms` / `close_grace_ms` / `crash_grace_ms` / `cooldown_ms` | 7 000 / 1 000 / 50 / 2 000 | Product |
| — | `formula_version` | `LR-CRASH-1` | — |
| — | `curve_table_hash` | SHA-256 of the generated curve table (§3) | — |

## 2. Outcome generation (formula `LR-CRASH-1`)

Inputs: round seed `s` (32 bytes, from the hash chain, §6), chain salt `salt` (public bytes), `e_bp`, `M`.

```
h      = HMAC-SHA256(key = s, message = salt)            # 32 bytes
r      = integer value of the first 52 bits of h (big-endian)   # 0 ≤ r < 2^52
D      = 2^52
raw    = floor( 100 · (10000 − e_bp) · D  /  (10000 · (D − r)) )   # exact integer division
crash_x10000 = 100 · clamp(raw, 100, M/100)   # crash points stay on the 0.01× grid
```

All arithmetic is arbitrary-precision integer (Python `int`, Elixir integer, JS `BigInt`). No floating point is involved in the outcome.

### 2.1 Distribution

Let U = r/D (uniform on a 2⁻⁵² grid in [0, 1)). Then `raw/100 ≈ (1−e)/(1−U)` and, for every integer k (in hundredths) with 101 ≤ k ≤ M/100:

```
P(raw ≥ k) = P(crash_x10000 ≥ 100·k) = 100·(1 − e) / k        (exact up to ±2⁻⁵²)
```

Proof sketch: `raw ≥ k ⇔ 100(1−e)D/(D−r) ≥ k` (floor of a real is ≥ integer k iff the real is ≥ k) `⇔ r ≥ D − 100(1−e)D/k`; the number of admissible r out of D gives the probability.

Consequences (e = 3 %):

| Event | Probability |
|-------|-------------|
| Instant crash at 1.00× (`crash_x10000 = 10000`) | 1 − 0.97/1.01 ≈ **3.96 %** |
| Reaches 2× | 48.5 % |
| Reaches 5× | 19.4 % |
| Reaches 10× | 9.7 % |
| Reaches 100× | 0.97 % |
| Reaches 1 000× | 0.097 % |
| Reaches cap 10 000× | 0.0097 % |
| Median crash point | ≈ 1.94× |

### 2.2 Why this shape
P(X ≥ x) ∝ 1/x is the unique family for which **every fixed cash-out target has the same expected return** — the game has no "best" target, so RTP is a single honest number rather than strategy-dependent. Any alternative distribution must be justified against this property.

## 3. Multiplier progression (presentation & cash-out pricing)

Continuous curve: `m(t) = exp(λ·t)`, t = ms since `launch_at`.

To make server, verifier and auditors bit-identical across languages, the curve is **tabulated once per ruleset**:

```
curve[t] = floor( 10000 · exp(λ · t) )   for t = 0, 1, 2, … , T_max   (ms)
```
computed offline with ≥ 50-digit decimal precision, stored as an artefact, hashed into the ruleset (`curve_table_hash`). T_max = smallest t with `curve[t] ≥ M` (≈ 153 500 ms for 10 000×; values ≤ 10⁸ fit int32; table ≈ 600 KB, loaded once per node).

- **Crash time:** `t_crash = min{ t : curve[t] ≥ crash_x10000 }`; `crash_at = launch_at + t_crash`.
- **Manual cash-out** stamped at `t = received_at − launch_at` with `t < t_crash` → `cashout_x10000 = curve[t]`. Because `curve` is non-decreasing and `t < t_crash`, `curve[t] < crash_x10000`. A manual cash-out can never equal or exceed the crash point. Manual cash-outs are priced at **0.0001×** resolution (OQ-18, decided).
- **Auto cash-out** at target k fires at `t_k = min{ t : curve[t] ≥ k }` and pays **exactly k**, iff `k ≤ crash_x10000` (**tie goes to the player**, OQ-17).
- **Client display** may use float `exp()`; it is presentation only.

## 4. Round end and caps

1. `crash_x10000 = 10000` → instant crash at launch; all bets lose. Disclosed in rules ("The rocket can explode on the launchpad").
2. `crash_x10000 < M` → `ROUND_CRASHED{end_reason: CRASH}`; un-cashed bets lose.
3. `crash_x10000 = M` → `ROUND_CRASHED{end_reason: MAX_MULTIPLIER}`; **every still-active bet is cashed at M** ("journey complete"). This keeps RTP = 1 − e for players who hold to the end.
4. **Max win per bet** W: each admitted bet gets an *effective target* `k_eff = min(auto_target or ∞, floor(10000·W / stake), M)` (x10000 units). The coordinator auto-cashes at `k_eff`. This caps exposure **without** changing the crash point or reducing the RTP of the bet (it is exactly a fixed-target bet at k_eff).

## 5. Return to player

For a bet with effective target k in hundredths (101 ≤ k ≤ M/100), ignoring payout rounding:
```
E[return] = (k/100) · P(crash_x10000 ≥ 100·k) = (k/100) · 100(1−e)/k = 1 − e
```
- **Strategy invariance.** For manual play, survival from any reached multiplier a to b is a/b (memoryless in log-space), so any stopping rule based on the observed flight also has expected return ≤ 1 − e, with equality in the limit of continuous pricing.
- **Manual pricing precision (decided: 0.0001×).** Manual cash-outs are priced at `curve[t]` in x10000 units. Residual drag ≤ 0.0001/m from the floor plus ≤ λ·m per ms of stamp granularity (≈ 0.006 % relative) — i.e. manual RTP ≈ 96.99 % vs. ≈ 96.0–97.0 % with 0.01× pricing. Display shows 2 decimals; the confirmation shows the exact paid amount (and the 4-decimal multiplier in bet details). Rules text: "Manual cash-outs are paid at the multiplier to four decimal places at the moment the server receives your request."
- **Payout rounding.** `floor(stake_minor × multiplier_x10000 / 10000)` loses < 1 minor unit per winning bet.

### 5.1 Timing expectations (e = 3 %, λ = 6×10⁻⁵/ms)
- E[ln X] ≈ 1 − e ⇒ E[flight] ≈ 0.97/λ ≈ **16.2 s**; median ≈ 11.0 s.
- Intermission = cooldown 2 s + betting 7 s + grace 1 s = 10 s ⇒ ≈ 26 s/round ⇒ ≈ **138 rounds/hour/stream**.

### 5.2 Planet milestones (presentation only, doc 14)
| Milestone | Multiplier | P(reached) at e = 3 % |
|-----------|-----------:|---------------------:|
| Leave atmosphere | 1.20× | 80.8 % |
| Moon flyby | 2× | 48.5 % |
| Mars | 5× | 19.4 % |
| Jupiter | 20× | 4.85 % |
| Saturn | 50× | 1.94 % |
| Deep space | 100× | 0.97 % |
| Heliopause | 1 000× | 0.097 % |

Milestones are spaced in log-multiplier, so they arrive at roughly regular *time* intervals. The visual design must not dramatise crashes "just before" a planet (no near-miss messaging, doc 15 §6).

## 6. Provably-fair protocol (per round stream)

### 6.1 Chain ceremony (offline, four-eyes, audited)
1. Generate `s_0` = 32 bytes from an OS CSPRNG on an isolated host.
2. Compute `s_{i+1} = SHA256(s_i)` for i = 0 … N−1 (N default 10 000 000 ≈ 8 years at 138 rounds/h). Store encrypted checkpoints every 10 000 indexes.
3. Publish `chain_id`, N, `terminal = s_N`, `formula_version`, `ruleset_hash`, and **a future drand round number R** (≥ 24 h ahead) — signed with the platform fairness key.
4. When drand round R is published, `salt = drand.randomness(R)`; chain → `SALTED`. Activation requires an `approval_request`.

**As built.** The ceremony is `LuxRt.Fairness.SeedChain.commit/2` (release task `seed_ceremony`, mix task
`lux.seed_ceremony`); the network is drand *quicknet* (period 3 s, `randomness = SHA-256(signature)`).
`COMMITTED → ACTIVE` happens only through a four-eyes `ACTIVATE_SEED_CHAIN` approval (doc 12 §5a); there is no
separate `SALTED` state because salting and activation are one approved step. Statuses:
`COMMITTED | ACTIVE | RETIRED | EXHAUSTED`, at most one `ACTIVE` per stream. The platform publishes each
commitment as an Ed25519-signed statement (`LRCHAIN1`, chain id, stream, N, terminal, formula, drand network,
round, commit time) at `/.well-known/luxrocket-chains.json`, with the salt and the drand BLS signature once
active. Limitations: the platform and engine check the beacon's internal consistency, not the BLS signature
(auditors verify it against the drand public key); step 1 runs on an engine node with the KEK, so the
"isolated host" is an operational control, not a technical one, until the KEK moves to an HSM (OQ-06).

### 6.2 Per round
- Round k (k = 1 … N) uses `seed_k = s_{N−k}`.
- **Commitment** shown at `ROUND_OPEN`: `commitment_k = s_{N−k+1}` (the previous round's revealed seed, or `terminal` for k = 1).
- **Reveal** at `ROUND_CRASHED`/`ROUND_VOIDED`: `seed_k`.
- **Verification**: `SHA256(seed_k) == commitment_k` **and** `crash_x10000 == LR-CRASH-1(seed_k, salt, e_bp, M)`. Auditors can additionally verify that all revealed seeds link back to the signed terminal hash.

### 6.3 What this proves and does not prove
| Property | Proved? |
|----------|---------|
| Outcome fixed before betting opened | Yes (commitment published at ROUND_OPEN; preimage resistance of SHA-256) |
| Outcome not changed in response to bets | Yes (commitment chain) |
| House did not pick a favourable chain | Yes, given salt from a public beacon published after commitment |
| Each round computed with the published formula and edge | Yes |
| No insider knows future outcomes | **No** — whoever can decrypt `s_0` or a checkpoint knows every future outcome in that chain. Mitigated by key management (§7.4), not by math. |
| RNG meets a jurisdiction's certified-RNG standard | **No** — a lab must assess it (OQ-12). The formula accepts any certified uniform 52-bit source in place of the HMAC if required. |

Voided rounds consume their seed and reveal it; the next round uses the next chain index. Chain exhaustion triggers a new ceremony well in advance (alert at 90 % used).

## 7. Risks

| ID | Risk | Mitigation |
|----|------|-----------|
| R-M1 | Insider with seed access predicts outcomes | Seeds encrypted with KEK outside DB, decrypted only in coordinator memory; no API/admin path exposes seeds before reveal; access audited; optional HSM (OQ-06); rotate chains on staff departure from key-holder roles. |
| R-M2 | Timing side channel leaks crash point (early credits/logs) | Information-leak rule (doc 06 §5.4); tests assert no pre-crash journal/log contains crash data. |
| R-M3 | Exposure from a long flight with large stakes | Max win per bet (§4.4), per-round exposure limit per operator × currency enforced at bet acceptance (doc 08). |
| R-M4 | Regulator rejects hash-chain RNG | Formula separable from RNG source; plan B certified RNG per round + commit-reveal. |
| R-M5 | Floating-point divergence between server and verifier | Integer outcome; tabulated curve with hash. |
| R-M6 | Late cash-outs accepted due to clock skew | Gateway clock-skew guard (doc 06 §5.1); property test: no accepted cash-out with stamp ≥ crash_at. |
| R-M7 | "Tie to player" or max-multiplier rule misunderstood by players | Rules page + certification of the exact text. |

## 8. Mathematical testing & certification plan

1. **Unit/property tests** (all three languages): known-answer vectors for `LR-CRASH-1` (published with the spec); `raw` monotone in r; clamp boundaries; curve table monotone; `t_crash` minimality.
2. **Distribution tests** on ≥ 10⁸ simulated outcomes: χ² goodness-of-fit over log-spaced buckets; KS test on `ln X`; exact tail checks at 2×, 10×, 100×, 1 000×, M; instant-crash frequency.
3. **RTP simulation**: fixed targets {1.01, 1.5, 2, 5, 10, 100, 1 000, M}, max-win caps, and scripted manual strategies; report RTP with 99 % confidence intervals.
4. **Reproducibility**: verifier implementations (Python reference, browser JS, Elixir) agree on 10⁶ random seeds.
5. **Independent review**: written report from an external game mathematician.
6. **Lab certification**: game rules, RNG, RTP, and the round recovery/void behaviour (GLI-19-style interactive-gaming requirements are a likely baseline; the specific standard is jurisdiction-defined, OQ-12).
