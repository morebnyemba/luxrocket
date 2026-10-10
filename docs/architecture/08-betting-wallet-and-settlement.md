# 08 — Betting, Wallet and Settlement

## 1. Two-panel model

- Each session has `panels = ruleset.panels` (default 2) independent panels, indexed 0..N−1.
- **At most one bet per panel per player per round** (DB unique constraint across sessions/tabs).
- Per-panel state: stake, `bet_id`, acceptance status, `auto_cashout_x10000`, cash-out request state, confirmed cash-out (`cashout_x10000`, `payout_minor`), potential return (display only), settlement status, error/recovery state.
- Panels share the round and crash point; nothing else. One panel's cash-out, rejection or error never changes the other's state.
- Auto cash-out target is fixed at placement (v1). Changing it mid-flight is excluded to avoid a race with the coordinator's auto timer (OQ-22).
- No autoplay/auto-bet in v1 (responsible-gambling concern; several regulators restrict autoplay; OQ-23).
- **Bet for next round**: if the player presses BET while a round is flying, the panel enters `QUEUED` client-side and sends `PLACE_BET` when `ROUND_OPEN` arrives. Nothing is reserved server-side.

### 1.1 Client panel state machine

```mermaid
stateDiagram-v2
  [*] --> IDLE
  IDLE --> QUEUED: press BET while round not open
  QUEUED --> IDLE: press CANCEL
  QUEUED --> PLACING: ROUND_OPEN → send PLACE_BET
  IDLE --> PLACING: press BET during BETTING_OPEN
  PLACING --> PLACED: BET_ACCEPTED
  PLACING --> REJECTED: BET_REJECTED
  PLACED --> ACTIVE: ROCKET_LAUNCHED
  ACTIVE --> CASHING_OUT: press CASH OUT
  ACTIVE --> CASHED_OUT: CASHOUT_ACCEPTED (auto)
  CASHING_OUT --> CASHED_OUT: CASHOUT_ACCEPTED
  CASHING_OUT --> LOST: CASHOUT_REJECTED(ROUND_ENDED) / ROUND_CRASHED
  CASHING_OUT --> ACTIVE: CASHOUT_REJECTED(retryable)
  ACTIVE --> LOST: ROUND_CRASHED
  CASHED_OUT --> SETTLED: SETTLEMENT_CONFIRMED
  PLACED --> REFUNDING: ROUND_VOIDED / BET_EXCLUDED
  ACTIVE --> REFUNDING: ROUND_VOIDED
  REFUNDING --> REFUNDED: SETTLEMENT_CONFIRMED(refund)
  REJECTED --> IDLE: next ROUND_OPEN or dismiss
  LOST --> IDLE: next ROUND_OPEN
  SETTLED --> IDLE: next ROUND_OPEN
  REFUNDED --> IDLE: next ROUND_OPEN
  note right of PLACING: Any state → RECOVERING on disconnect;<br/>RECOVERING → state from ROUND_SNAPSHOT.player_bets
```

Rules: buttons are disabled while a command is in flight; each user intent gets one `client_command_id` (UUIDv7) reused across retries; the UI never shows "Won" before `CASHOUT_ACCEPTED`, and shows "Crediting…" until `SETTLEMENT_CONFIRMED`.

## 2. Wallet model

Seamless wallet (ADR-007). Operations against the operator (contract in doc 09 §6):

| Operation | When | Amount | Retry? |
|-----------|------|--------|--------|
| `debit` | Bet placement | stake | **No** (deadline-bound; timeout ⇒ UNKNOWN ⇒ rollback) |
| `credit` | Cash-out accepted (manual/auto/max) | payout | Yes, until acknowledged |
| `rollback` | Debit unknown, bet excluded, round voided | original stake, references debit `transaction_id` | Yes, until acknowledged |
| `settle` (optional per operator) | Bet lost | 0 | Yes |

Transaction ids are deterministic per bet and type: `tx_` + UUIDv5(namespace, `bet_id ‖ type`) — a re-derived id for the same bet and type is always identical, so even a bug that re-enqueues a credit cannot mint a new id. DB unique `(bet_id, type)` backs this.

## 3. Server-side bet lifecycle

```mermaid
stateDiagram-v2
  [*] --> PENDING_DEBIT: tx_phase1
  PENDING_DEBIT --> REJECTED: validation or operator rejects
  PENDING_DEBIT --> DEBIT_UNKNOWN: timeout / 5xx / malformed
  PENDING_DEBIT --> DEBITED: operator OK
  DEBITED --> ACTIVE: fact BET_ADMITTED
  DEBITED --> EXCLUDED: fact BET_EXCLUDED or round terminal without admission
  DEBIT_UNKNOWN --> EXCLUDED: always (never admitted)
  ACTIVE --> CASHED_OUT: fact CASHOUT_ACCEPTED
  ACTIVE --> LOST: fact ROUND_CRASHED
  ACTIVE --> VOIDED: fact ROUND_VOIDED
  CASHED_OUT --> [*]: settlement WIN (credit confirmed)
  LOST --> [*]: settlement LOSS (settle confirmed or not required)
  EXCLUDED --> [*]: settlement REFUND (rollback confirmed)
  VOIDED --> [*]: settlement REFUND (rollback confirmed)
  REJECTED --> [*]
```

`bet.status` changes only via service functions that also write the matching ledger postings and outbox events in the same transaction.

## 4. Bet acceptance sequence

```mermaid
sequenceDiagram
  autonumber
  participant P as Player (iframe)
  participant G as Phoenix gateway
  participant C as RoundCoordinator
  participant D as django-internal
  participant DB as Postgres (platform)
  participant W as Operator wallet
  participant J as JournalWriter (rt)

  P->>G: PLACE_BET {cmd_id, round_id, panel, stake, auto}
  G->>G: stamp received_at
  G->>C: place_bet(stamped)
  C-->>P: reply {status: RECEIVED}
  alt state ≠ BETTING_OPEN or received_at ≥ close_at
    C-->>P: BET_REJECTED {BETTING_CLOSED}
  else
    C->>D: POST /internal/v1/bets {fencing, round, deadline}
    D->>DB: tx1: bet PENDING_DEBIT, exposure++, wallet_tx DEBIT PENDING
    D->>W: debit(tx_id, stake) [aiohttp, ≤ timeout]
    alt OK
      W-->>D: 200 OK
      D->>DB: tx2: bet DEBITED, ledger, outbox
      D-->>C: ACCEPTED {bet_id}
      alt now < launch_at
        C->>J: BET_ADMITTED (batched, fenced)
        J-->>C: flushed
        C-->>P: BET_ACCEPTED {bet_id, panel}
      else late
        Note over C: excluded at launch (BET_EXCLUDED journaled)
        C-->>P: BET_REJECTED {LATE, refund: PENDING}
      end
    else business rejection
      W-->>D: 200 {INSUFFICIENT_FUNDS}
      D->>DB: tx2: bet REJECTED, exposure--
      D-->>C: REJECTED {code}
      C-->>P: BET_REJECTED {code}
    else timeout / 5xx
      D->>DB: tx2: wallet_tx UNKNOWN, bet DEBIT_UNKNOWN, enqueue rollback
      D-->>C: UNKNOWN
      C-->>P: BET_REJECTED {UNCERTAIN, refund: PENDING}
    end
  end
```

## 5. Cash-out sequence

```mermaid
sequenceDiagram
  autonumber
  participant P as Player
  participant G as Phoenix gateway
  participant C as RoundCoordinator
  participant J as JournalWriter
  participant MQ as RabbitMQ
  participant K as journal-consumer (Django)
  participant WW as wallet-worker
  participant W as Operator wallet

  P->>G: CASH_OUT {cmd_id, bet_id}
  G->>G: stamp received_at
  G->>C: cash_out(stamped)
  C->>C: serialised with crash: FLYING ∧ received_at < crash_at ∧ bet ACTIVE ∧ not cashed
  alt accepted
    C->>C: cashout_x10000 = curve[received_at − launch_at], payout = min(floor(stake·k/10000), max_win)
    C->>J: CASHOUT_ACCEPTED (fenced, ≤10 ms batch)
    J-->>C: flushed
    C-->>P: CASHOUT_ACCEPTED {bet_id, cashout_x10000, payout}
    J-)MQ: relay (publisher confirms)
    MQ-)K: rt.events CASHOUT_ACCEPTED
    K->>K: dedupe event_id, recompute payout (must match), bet CASHED_OUT, ledger, wallet_tx CREDIT PENDING, outbox
    K-)MQ: wallet.credit job
    MQ-)WW: credit job
    WW->>W: credit(tx_id, payout)
    W-->>WW: OK
    WW->>WW: wallet_tx SUCCEEDED, settlement CONFIRMED, ledger, outbox settlement.confirmed
    WW-)G: platform.events → session topic
    G-->>P: SETTLEMENT_CONFIRMED {bet_id, payout}
  else rejected
    C-->>P: CASHOUT_REJECTED {ROUND_ENDED | NOT_ACTIVE | ALREADY_CASHED_OUT}
  end
```

## 6. Retry, timeout and unknown-outcome policy

| Case | Policy |
|------|--------|
| Debit timeout / network error / 5xx / unparseable | Mark `UNKNOWN`; bet not accepted; enqueue `rollback(ref=debit tx)`. If operator supports status query, query first; `NOT_FOUND` ⇒ rollback still sent (fences a late-arriving debit). |
| Debit business rejection | Final. No retry. |
| Credit / rollback / settle failure (timeout, 5xx, network) | Retry same `transaction_id`: 1 s, 2 s, 5 s, 15 s, 30 s, 1 min, 5 min, 15 min, then hourly up to 72 h. Then `NEEDS_ATTENTION` + page on-call. Never auto-abandoned; `ABANDONED` requires approval + audit. |
| Credit definitive rejection (operator says "no") | Contract violation; `NEEDS_ATTENTION`, operator notified by webhook + portal alert. |
| Operator returns `DUPLICATE` with original result | Treat as success (idempotent replay). |
| Rollback returns `TRANSACTION_NOT_FOUND` | Success (debit never landed; operator must now refuse that debit id forever). |
| Circuit breaker open | Debits rejected fast; credits/rollbacks stay queued (delayed retry), never dropped. |
| Operator down for hours | Bets for that operator fail fast; other operators unaffected (per-operator semaphores/queues); credits accumulate and drain on recovery in FIFO order per player. |

Per-operator fairness: wallet jobs are routed to `wallet.{priority}` queues with per-operator concurrency caps inside the worker, so one slow operator cannot hold all worker slots.

## 7. Settlement

`journal-consumer` applies facts in stream order:

| Fact | Effect (one DB transaction) |
|------|-----------------------------|
| `ROUND_CREATED` / `ROUND_OPENED` | Upsert `game_round` projection |
| `BET_ADMITTED` | bet DEBITED → ACTIVE (if bet unknown yet — debit tx2 not committed — park and retry; Django's own tx2 commits within ms) |
| `BET_EXCLUDED` | bet → EXCLUDED; if DEBITED, enqueue rollback; release exposure |
| `CASHOUT_ACCEPTED` | Verify payout recomputation; bet → CASHED_OUT; ledger (obligation); enqueue credit |
| `ROUND_CRASHED` | All ACTIVE → LOST; ledger; enqueue settle (if operator requires); store crash/seed; settlement_status → SETTLING |
| `ROUND_VOIDED` | All ACTIVE → VOIDED; enqueue rollbacks; seed |
| (all bets terminal & confirmed) | `game_round.settlement_status = SETTLED`; outbox `round.settled` (webhook) |

### 7.1 Ledger postings (per operator × currency, signed, each journal sums to 0)

| Event | Postings |
|-------|----------|
| Debit OK | `player_wallet −S`, `bets_in_play +S` |
| Cash-out accepted | `bets_in_play −S`, `payouts_payable +P`, `game_result +(S−P)` |
| Credit OK | `payouts_payable −P`, `player_wallet +P` |
| Lost | `bets_in_play −S`, `game_result +S` |
| Excluded/voided decision | `bets_in_play −S`, `refunds_payable +S` |
| Rollback OK (of a recorded debit) | `refunds_payable −S`, `player_wallet +S` |

`game_result` balance = GGR (stakes − wins) — negative when players win. Invariants checked continuously: `bets_in_play` = 0 for settled rounds; `payouts_payable`, `refunds_payable` entries older than 15 min alert.

## 8. Reconciliation

```mermaid
sequenceDiagram
  autonumber
  participant B as celery-beat
  participant R as reconciliation job
  participant RT as rt.round_journal (read-only)
  participant PL as platform (bets, wallet_tx, ledger)
  participant OP as Operator (report API, optional)
  participant Q as wallet queues
  participant A as Admin / Operator portal

  B->>R: every 5 min: internal reconciliation
  R->>RT: facts for rounds terminal > 2 min
  R->>PL: matching bets / wallet transactions
  R->>R: diff: admitted-but-not-ACTIVE, cashed-without-credit, debited-without-admission, ACTIVE-in-terminal-round, ledger imbalance, payout mismatch
  alt auto-resolvable (missed fact, missing job)
    R->>PL: re-apply fact idempotently / re-enqueue job
    R->>Q: wallet job (same tx id)
    R->>PL: item AUTO_RESOLVED
  else
    R->>PL: item OPEN (severity)
    R->>A: alert + discrepancy queue
  end
  B->>R: daily 02:00 UTC: operator reconciliation
  R->>OP: GET transactions for day (or ingest uploaded file)
  R->>PL: compare by transaction_id: missing / amount / status
  R->>PL: items + report
  R->>A: daily reconciliation report per operator
```

Resolution of open items is a portal/admin workflow with mandatory notes; any monetary correction is a new `ADJUSTMENT_CREDIT` (four-eyes approved), never an edit.

## 9. Exposure control

At tx_phase1, `round_operator_exposure.exposure_minor += max_win_minor_for_bet` (worst-case liability = `min(stake × M/100, W)`) with a conditional update against `round_exposure_limit_minor`. Rejected bets/exclusions decrement it. This bounds an operator's worst-case round loss **without** touching the outcome or forcing cash-outs based on player behaviour.

## 10. Failure matrix (money correctness)

| Scenario | Outcome | Why it's safe |
|----------|---------|---------------|
| Double-click BET | One bet | Unique (round, player, panel) + command id |
| Two tabs bet same panel | One bet; second gets current state | Same constraint |
| Debit succeeds after our timeout | Bet not accepted; rollback refunds | Rollback-on-doubt; operator contract |
| Django commits DEBITED, crashes before replying | Phoenix sees timeout ⇒ UNKNOWN ⇒ excluded at launch ⇒ journal-consumer sees DEBITED + BET_EXCLUDED ⇒ rollback | Exclusion fact |
| Cash-out click races crash | Exactly one wins in the coordinator mailbox order, judged by gateway stamp vs `crash_at` | Single serialised process |
| Coordinator dies after journaling cash-out, before ack | Cash-out is paid (journal is truth); client learns on resync | Durable-before-ack |
| Coordinator dies before journaling cash-out | Not paid; round voided ⇒ stake refunded | Only journaled facts count |
| Credit message duplicated | One credit | `(bet_id, CREDIT)` unique + operator idempotency |
| Journal relay publishes twice | Applied once | `processed_event` |
| RabbitMQ loses a message | Reconciler finds fact without effect, re-applies | Journal + 5-min reconciliation |
