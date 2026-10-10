# 18 — UI/UX and Asset Plan

> No images or artwork are generated in Phase A. This document specifies what will be designed and in which order once approved.

## 1. Design system

Two themes over one token set (`packages/ui`), exposed as CSS variables and a Tailwind preset.

### 1.1 Core tokens (proposal)
| Token | Game ("Cosmos") | Console (admin/portal) |
|-------|-----------------|------------------------|
| `--bg` | #05060A (near-black, blue cast) | #0B0D12 dark / #F7F8FA light |
| `--surface` | rgba(14,17,28,0.72) + blur | #12151C / #FFFFFF |
| `--text` | #F2F4F8 | #E6E8EE / #111318 |
| `--text-muted` | #9AA3B5 | #8A93A6 / #5B6475 |
| `--accent` (brand "Lux gold") | #F5C04A | #D9A93A |
| `--accent-2` (ion blue) | #4CC9F0 | #3BA6D0 |
| `--success` (cash-out) | #3DDC97 | #23A26D |
| `--danger` (crash) | #FF4D5E | #D93848 |
| `--warning` | #FFB347 | #C98A1E |
| Radius | 14 px panels, 999 px buttons | 8 px |
| Spacing | 4-px scale | 4-px scale, denser defaults |
| Motion | 120/200/320 ms, `cubic-bezier(.2,.8,.2,1)`; reduced-motion = 0 ms or fades | 120/200 ms |
All text/background pairs validated ≥ 4.5:1 (≥ 3:1 for ≥ 24 px multiplier digits).

### 1.2 Typography
- Multiplier: a distinctive geometric display face with **tabular figures** (license-cleared; candidates evaluated in Phase B), weight 700–800, sizes fluid `clamp(48px, 14cqi, 128px)`.
- UI: a neutral grotesk with tabular numerals (e.g. Inter or equivalent open licence) for panels and dashboards.
- Self-hosted, subset (Latin + required locales), `font-display: swap`.

### 1.3 Components
Game: MultiplierDisplay, CountdownRing, BetPanel (+ StakeInput, QuickStakes, AutoCashoutField, PrimaryActionButton), HistoryStrip (crash chips coloured by bucket — neutral colours, not "hot/cold" framing), RoundStatusPill, ConnectionBanner, Toast, Dialog, VerifyCard, RulesSheet, SessionReminder.
Console: shadcn/ui primitives + DataTable, FilterBar, KpiTile, TimeSeriesChart, StatusBadge, AuditDiff, ApprovalBanner, CredentialRevealOnce, CodeBlock, EmptyState.

## 2. Screen inventories

### 2.1 Player game
| # | Screen / state |
|---|----------------|
| G1 | Loading (shell, progress, brand mark) |
| G2 | Betting open (countdown, panels active, previous crash shown) |
| G3 | Betting closed / pre-launch (countdown to ignition) |
| G4 | In flight (multiplier, rocket, CASH OUT buttons, milestone toasts) |
| G5 | Cashed out (per panel confirmation, crediting → confirmed) |
| G6 | Crash (explosion, crash multiplier, lost/cashed summary per panel) |
| G7 | Voided round notice (refund messaging) |
| G8 | Rules & RTP sheet |
| G9 | Round verification (seed, salt, formula, step-by-step check) |
| G10 | My bets history |
| G11 | Session reminder (RG) |
| G12 | Reconnecting / offline |
| G13 | Session expired / relaunch required |
| G14 | Maintenance / unavailable |
| G15 | Unsupported browser / too-small viewport |
| G16 | No-WebGL 2D mode |

### 2.2 Platform admin
Overview; Operators list/detail (9 tabs); Onboarding wizard; Games/versions; Ruleset editor + RTP preview; Streams; Seed chains; Releases/rollout; Maintenance; Rounds search/detail; Bets/Transactions/Settlements; Pending & failed queue; Reconciliation runs/items; Adjustments; Analytics (platform/operator/reliability); Staff users; Roles; Audit log; Credential events; Sessions; Incidents; Approvals; System health/queues; Login/MFA/step-up.

### 2.3 Operator portal
Overview; Integration (IDs, credentials, domains, webhooks, wallet endpoint, conformance test, logs, docs, sandbox); Game settings (availability, currencies & stakes, display, RG); Reports (bets, cash-outs, settlements, refunds, transactions, rounds, reconciliation, downloads); Team (users, roles, sessions, audit); Login/MFA.

## 3. Responsive specification (game)
| Container | Layout |
|-----------|--------|
| < 360 w or < 480 h | "Enlarge" notice |
| Portrait 360–600 w | Scene 55 % top; multiplier centred over scene; panels stacked (two compact cards) or tabbed below 640 h |
| Landscape phone (h < 500) | Scene left 62 %; panels right column, compact |
| ≥ 768 w | Scene full; panels bottom row side-by-side; history strip top |
| ≥ 1280 w | Same as tablet with max content width; optional side rail for rules/verification |
CASH OUT button: minimum 56 px tall on touch; primary colour per state (gold BET, green CASH OUT, neutral WAITING).

## 4. Interaction flows
1. **First launch**: load → G2 with one-line coach mark ("Bet, watch the rocket, cash out before it explodes") dismissible; never blocks.
2. **Place two bets**: edit stake (quick chips) → set auto on panel 2 → BET ×2 → each shows "Placed" → launch.
3. **Cash out**: tap CASH OUT → button → "Cashing out…" (≤ 1 RTT) → "Cashed out 2.41× · +$24.10" → "Credited".
4. **Crash with active bet**: panel shows "Lost at 1.87×" (neutral tone, no "so close").
5. **Bet during flight**: BET → "Queued for next round" with CANCEL.
6. **Disconnect mid-flight**: banner, panels "Pending result", on recovery accurate results.
7. **Verify a round**: history chip → round detail → "Verify" walks the hash and formula in-browser.

Loading/empty/error/recovery states are enumerated per screen in the Phase B design file.

## 5. Asset inventory (to be produced after approval)

| ID | Asset | Format & budget | Notes |
|----|-------|-----------------|-------|
| A1 | Rocket model (original design), 2 LODs | glTF + meshopt; ≤ 15 k / 5 k tris; ≤ 250 KB | PBR 1k atlas (KTX2); emissive engine parts |
| A2 | Earth materials | KTX2 albedo 1k/2k/4k, night lights, clouds alpha, normal optional | Public-domain NASA-derived sources (verify licence) or procedural |
| A3 | Moon, Mars, Jupiter, Saturn (+ring) | KTX2 512–2k each | Same licence check |
| A4 | Space backgrounds | Equirect/cubemap KTX2 512/2k; procedural nebula shader alternative | Prefer procedural to save bytes |
| A5 | Launchpad environment | Low-poly glTF ≤ 150 KB | Stylised |
| A6 | Exhaust & particle textures | 64–256 px sprite sheets, KTX2 | Additive |
| A7 | Explosion/crash effect | Sprite sheet + shader | Reduced-motion variant |
| A8 | Heliopause/Proxima effects | Shader-driven | — |
| A9 | Loading/brand artwork | SVG logo + lightweight animated SVG | No heavy raster |
| A10 | Icon set | SVG, 24 px grid | Shared with console |
| A11 | Sound set (optional) | Opus/AAC ≤ 300 KB total | Off by default |
| A12 | Dashboard empty states | SVG, monochrome | Optional |

Procedural first: starfields, atmosphere glow, ring shading, nebulae, exhaust are code/shader-generated where quality permits.

## 6. Asset-generation sequence (post-approval)
1. Brand mark & colour/typography validation (static references only).
2. Rocket concept references → A1 modelling brief → model.
3. Earth + launchpad (A2, A5) — first playable zone.
4. Particles & exhaust (A6) and crash (A7).
5. Moon/Mars (A3 part), then Jupiter/Saturn.
6. Space backgrounds (A4) and deep-space effects (A8).
7. Loading art (A9), icons (A10), sounds (A11), empty states (A12).
Each asset recorded in `apps/game/assets/manifest.json` with dimensions, format, budget, licence/source, intended use, LOD tier. Generated reference images are **references**, never shipped as UI screenshots; the UI is built as real accessible components.
