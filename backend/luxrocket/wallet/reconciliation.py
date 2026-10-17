"""Reconciliation (doc 08 §8): find money states that should not exist, repair the safe ones.

Internal (every few minutes): bets, wallet transactions, settlements and the ledger must agree.
Repairs are limited to re-driving work that was decided but not done (a missing credit or
rollback job, an unconfirmed settlement, a debit whose worker died mid-flight); each repair
re-checks its condition under a row lock so it cannot race the live handlers. Everything else
becomes an OPEN discrepancy for a human, who resolves it with a note — money is never edited.

Operator (hourly, incremental): our terminal wallet transactions are looked up at the operator
by OUR transaction ids (every id originates here, so this covers both directions without
day-boundary ambiguity) and compared by status and amount.
"""

import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from luxrocket.core.ids import tx_public_id
from luxrocket.gaming.models import Bet, GameRound
from luxrocket.operators import webhooks
from luxrocket.operators.models import Operator, WalletKind
from luxrocket.wallet.models import (
    Discrepancy,
    OperatorReconCursor,
    ReconciliationRun,
    Settlement,
    WalletTransaction,
)

log = logging.getLogger(__name__)

TX = WalletTransaction
GRACE = timedelta(minutes=2)  # let in-flight work finish before judging it
OPERATOR_LAG = timedelta(minutes=10)
LOOKUP_BATCH = 200


class _Recorder:
    def __init__(self, run: ReconciliationRun) -> None:
        self.run = run

    def auto(self, kind: str, subject: str, operator_id: Any, detail: dict[str, Any]) -> None:
        Discrepancy.objects.create(
            run=self.run,
            operator_id=operator_id,
            kind=kind,
            severity=Discrepancy.Severity.WARNING,
            subject=subject,
            detail=detail,
            status=Discrepancy.Status.AUTO_RESOLVED,
            resolution_note="auto-repaired by reconciliation",
            resolved_by="reconciliation",
            resolved_at=timezone.now(),
        )
        self.run.auto_resolved += 1
        log.warning("reconciliation auto-resolved %s %s", kind, subject)

    def open(
        self,
        kind: str,
        subject: str,
        operator_id: Any,
        detail: dict[str, Any],
        severity: str = Discrepancy.Severity.CRITICAL,
    ) -> None:
        with transaction.atomic():
            item, created = Discrepancy.objects.get_or_create(
                kind=kind,
                subject=subject,
                status=Discrepancy.Status.OPEN,
                defaults={
                    "run": self.run,
                    "operator_id": operator_id,
                    "severity": severity,
                    "detail": detail,
                },
            )
            if not created:
                return
            self.run.opened += 1
            log.error("reconciliation opened %s %s: %s", kind, subject, detail)
            if operator_id is not None:
                operator = Operator.objects.get(pk=operator_id)
                webhooks.emit(
                    operator,
                    "reconciliation.discrepancy",
                    str(item.id),
                    {
                        "discrepancy_id": str(item.id),
                        "kind": kind,
                        "severity": severity,
                        "subject": subject,
                        "detail": detail,
                    },
                )


def _start(kind: str, operator: Operator | None = None) -> ReconciliationRun:
    return ReconciliationRun.objects.create(kind=kind, operator=operator)


def _finish(run: ReconciliationRun, status: str, note: str = "") -> ReconciliationRun:
    run.status = status
    run.note = note[:200]
    run.finished_at = timezone.now()
    run.save()
    return run


def _has_tx(tx_type: str, status: str | None = None) -> Exists:
    q = TX.objects.filter(bet=OuterRef("pk"), type=tx_type)
    if status:
        q = q.filter(status=status)
    return Exists(q)


# ---- Internal reconciliation -------------------------------------------------------------


def run_internal(now: Any = None) -> ReconciliationRun:
    now = now or timezone.now()
    cutoff = now - GRACE
    run = _start(ReconciliationRun.Kind.INTERNAL)
    rec = _Recorder(run)
    try:
        for check in (
            _stuck_pending_debits,
            _uncertain_debits_without_rollback,
            _cashouts_without_credit,
            _refunds_without_rollback,
            _unconfirmed_settlements,
            _live_bets_in_finished_rounds,
            _needs_attention,
            _unverified_outcomes,
            _ledger_clearing_accounts,
        ):
            run.checked += check(rec, cutoff)
    except Exception as exc:
        log.exception("internal reconciliation failed")
        return _finish(run, ReconciliationRun.Status.FAILED, f"{type(exc).__name__}: {exc}")
    return _finish(run, ReconciliationRun.Status.COMPLETED)


def _stuck_pending_debits(rec: _Recorder, cutoff: Any) -> int:
    """Phase 2 never ran (process died around the debit call): treat the debit as uncertain."""
    from luxrocket.gaming.betting import _enqueue_rollback, _release_exposure

    ids = list(
        Bet.objects.filter(status=Bet.Status.PENDING_DEBIT, created_at__lt=cutoff).values_list(
            "pk", flat=True
        )
    )
    for pk in ids:
        with transaction.atomic():
            bet = Bet.objects.select_for_update().get(pk=pk)
            if bet.status != Bet.Status.PENDING_DEBIT:
                continue
            TX.objects.filter(bet=bet, type=TX.Type.DEBIT, status=TX.Status.PENDING).update(
                status=TX.Status.UNKNOWN, operator_code="RECONCILED_STUCK"
            )
            bet.status = Bet.Status.DEBIT_UNKNOWN
            bet.reject_code = "UNCERTAIN"
            bet.save(update_fields=["status", "reject_code", "updated_at"])
            _release_exposure(bet)
            _enqueue_rollback(bet)
            rec.auto("STUCK_PENDING_DEBIT", bet.public_id, bet.operator_id, {})
    return len(ids)


def _uncertain_debits_without_rollback(rec: _Recorder, cutoff: Any) -> int:
    from luxrocket.gaming.betting import _enqueue_rollback

    qs = Bet.objects.filter(status=Bet.Status.DEBIT_UNKNOWN, updated_at__lt=cutoff).exclude(
        _has_tx(TX.Type.ROLLBACK)
    )
    ids = list(qs.values_list("pk", flat=True))
    for pk in ids:
        with transaction.atomic():
            bet = Bet.objects.select_for_update().get(pk=pk)
            if TX.objects.filter(bet=bet, type=TX.Type.ROLLBACK).exists():
                continue
            _enqueue_rollback(bet)
            rec.auto("UNCERTAIN_DEBIT_WITHOUT_ROLLBACK", bet.public_id, bet.operator_id, {})
    return len(ids)


def _cashouts_without_credit(rec: _Recorder, cutoff: Any) -> int:
    from luxrocket.gaming.journal import _enqueue

    qs = Bet.objects.filter(status=Bet.Status.CASHED_OUT, updated_at__lt=cutoff).exclude(
        _has_tx(TX.Type.CREDIT)
    )
    ids = list(qs.values_list("pk", flat=True))
    for pk in ids:
        with transaction.atomic():
            bet = Bet.objects.select_for_update().get(pk=pk)
            settlement = Settlement.objects.filter(bet=bet).first()
            if TX.objects.filter(bet=bet, type=TX.Type.CREDIT).exists():
                continue
            if (
                bet.payout_minor is None
                or settlement is None
                or settlement.status == Settlement.Status.NEEDS_ATTENTION
                or settlement.payout_minor != bet.payout_minor
            ):
                rec.open(
                    "CASHOUT_WITHOUT_CREDIT",
                    bet.public_id,
                    bet.operator_id,
                    {"payout": str(bet.payout_minor), "settlement": bool(settlement)},
                )
                continue
            _enqueue(bet, TX.Type.CREDIT, bet.payout_minor)
            rec.auto("CASHOUT_WITHOUT_CREDIT", bet.public_id, bet.operator_id, {})
    return len(ids)


def _refunds_without_rollback(rec: _Recorder, cutoff: Any) -> int:
    from luxrocket.gaming.journal import _enqueue

    qs = (
        Bet.objects.filter(
            status__in=[Bet.Status.EXCLUDED, Bet.Status.VOIDED], updated_at__lt=cutoff
        )
        .filter(_has_tx(TX.Type.DEBIT, TX.Status.SUCCEEDED))
        .exclude(_has_tx(TX.Type.ROLLBACK))
    )
    ids = list(qs.values_list("pk", flat=True))
    for pk in ids:
        with transaction.atomic():
            bet = Bet.objects.select_for_update().get(pk=pk)
            if TX.objects.filter(bet=bet, type=TX.Type.ROLLBACK).exists():
                continue
            if _account_balance(bet.pk, "refunds_payable") != bet.stake_minor:
                # The refund decision itself is missing from the ledger: a human must look.
                rec.open("REFUND_NOT_DECIDED", bet.public_id, bet.operator_id, {})
                continue
            _enqueue(bet, TX.Type.ROLLBACK, bet.stake_minor)
            rec.auto("REFUND_WITHOUT_ROLLBACK", bet.public_id, bet.operator_id, {})
    return len(ids)


def _unconfirmed_settlements(rec: _Recorder, cutoff: Any) -> int:
    from luxrocket.wallet.worker import _confirm

    pending = Settlement.objects.filter(status=Settlement.Status.PENDING).filter(
        Q(outcome=Settlement.Outcome.WIN, bet__transactions__type=TX.Type.CREDIT)
        | Q(outcome=Settlement.Outcome.REFUND, bet__transactions__type=TX.Type.ROLLBACK),
        bet__transactions__status=TX.Status.SUCCEEDED,
        bet__transactions__updated_at__lt=cutoff,
    )
    ids = list(pending.values_list("bet_id", flat=True).distinct())
    for bet_id in ids:
        with transaction.atomic():
            bet = Bet.objects.select_for_update().select_related("player").get(pk=bet_id)
            _confirm(bet, timezone.now())
            rec.auto("SETTLEMENT_NOT_CONFIRMED", bet.public_id, bet.operator_id, {})
    return len(ids)


def _live_bets_in_finished_rounds(rec: _Recorder, cutoff: Any) -> int:
    finished = GameRound.objects.filter(state__in=["CRASHED", "VOIDED"]).values("pk")
    bets = Bet.objects.filter(
        round_id__in=finished,
        status__in=[Bet.Status.ACTIVE, Bet.Status.DEBITED],
        updated_at__lt=cutoff,
    )
    n = 0
    for bet in bets:
        n += 1
        rec.open(
            "LIVE_BET_IN_FINISHED_ROUND",
            bet.public_id,
            bet.operator_id,
            {"status": bet.status, "round_id": str(bet.round_id)},
        )
    return n


def _needs_attention(rec: _Recorder, cutoff: Any) -> int:
    n = 0
    for tx in TX.objects.filter(status=TX.Status.NEEDS_ATTENTION).select_related("bet"):
        n += 1
        rec.open(
            "WALLET_TX_NEEDS_ATTENTION",
            tx_public_id(tx.id),
            tx.operator_id,
            {"type": tx.type, "bet_id": tx.bet.public_id, "operator_code": tx.operator_code},
        )
    for s in Settlement.objects.filter(status=Settlement.Status.NEEDS_ATTENTION).select_related(
        "bet"
    ):
        n += 1
        rec.open(
            "SETTLEMENT_NEEDS_ATTENTION",
            s.bet.public_id,
            s.bet.operator_id,
            {"outcome": s.outcome, "payout": str(s.payout_minor)},
        )
    return n


def _unverified_outcomes(rec: _Recorder, cutoff: Any) -> int:
    n = 0
    for rnd in GameRound.objects.filter(state="CRASHED").exclude(outcome_verified=True):
        n += 1
        rec.open("OUTCOME_UNVERIFIED", str(rnd.pk), None, {"number": rnd.number})
    return n


# Clearing accounts must net to zero for every bet whose money movements are all final.
_LEDGER_SQL = """
SELECT b.id, b.public_id, b.operator_id, e.account, sum(e.amount_minor)
FROM platform.gaming_bet b
JOIN platform.wallet_ledgerentry e ON e.bet_id = b.id
WHERE b.updated_at < %s
  AND e.account IN ('bets_in_play', 'payouts_payable', 'refunds_payable')
  AND b.status IN ('LOST', 'CASHED_OUT', 'EXCLUDED', 'VOIDED', 'REJECTED', 'DEBIT_UNKNOWN')
  AND NOT EXISTS (SELECT 1 FROM platform.wallet_wallettransaction t
                  WHERE t.bet_id = b.id AND t.status IN ('PENDING', 'UNKNOWN', 'NEEDS_ATTENTION')
                    AND t.type <> 'DEBIT')
  AND NOT EXISTS (SELECT 1 FROM platform.wallet_settlement s
                  WHERE s.bet_id = b.id AND s.status = 'NEEDS_ATTENTION')
GROUP BY b.id, b.public_id, b.operator_id, e.account
HAVING sum(e.amount_minor) <> 0
"""


def _ledger_clearing_accounts(rec: _Recorder, cutoff: Any) -> int:
    with connection.cursor() as cur:
        cur.execute(_LEDGER_SQL, [cutoff])
        rows = cur.fetchall()
    for _bet_id, public, operator_id, account, amount in rows:
        rec.open(
            "LEDGER_NOT_CLEARED",
            f"{public}:{account}",
            operator_id,
            {"account": account, "balance": str(amount)},
        )
    return len(rows)


def _account_balance(bet_pk: Any, account: str) -> int:
    from django.db.models import Sum

    from luxrocket.wallet.models import LedgerEntry

    total = LedgerEntry.objects.filter(bet_id=bet_pk, account=account).aggregate(
        s=Sum("amount_minor")
    )["s"]
    return int(total or 0)


# ---- Operator reconciliation -------------------------------------------------------------


def run_operator(operator: Operator, now: Any = None, limit: int = 5000) -> ReconciliationRun:
    from luxrocket.wallet.adapters import adapter_for

    now = now or timezone.now()
    run = _start(ReconciliationRun.Kind.OPERATOR, operator)
    rec = _Recorder(run)
    cursor, _ = OperatorReconCursor.objects.get_or_create(operator=operator)
    qs = (
        TX.objects.filter(
            operator=operator,
            bet__session__wallet_kind=WalletKind.SEAMLESS_V1,
            status__in=[TX.Status.SUCCEEDED, TX.Status.FAILED],
            updated_at__lte=now - OPERATOR_LAG,
        )
        .select_related("bet", "bet__session", "bet__session__operator", "bet__player")
        .order_by("updated_at", "id")
    )
    if cursor.last_updated_at is not None:
        qs = qs.filter(updated_at__gt=cursor.last_updated_at)
    txs = list(qs[:limit])
    if not txs:
        return _finish(run, ReconciliationRun.Status.COMPLETED, "nothing new")

    # Sessions can point at different wallet URLs (rotation): group by client.
    groups: dict[str, list[WalletTransaction]] = defaultdict(list)
    clients: dict[str, Any] = {}
    for tx in txs:
        client = adapter_for(tx.bet.session).client  # type: ignore[attr-defined]
        groups[client.base_url].append(tx)
        clients[client.base_url] = client

    for url, items in groups.items():
        for i in range(0, len(items), LOOKUP_BATCH):
            batch = items[i : i + LOOKUP_BATCH]
            theirs = clients[url].lookup(
                [tx_public_id(t.id) for t in batch], settings.WALLET_TIMEOUT_MS
            )
            if theirs is None:
                # Cursor not advanced: the same window is retried next run.
                return _finish(run, ReconciliationRun.Status.UNAVAILABLE, f"lookup failed: {url}")
            for tx in batch:
                run.checked += 1
                _compare(rec, tx, theirs.get(tx_public_id(tx.id)))

    cursor.last_updated_at = txs[-1].updated_at
    cursor.save(update_fields=["last_updated_at"])
    return _finish(run, ReconciliationRun.Status.COMPLETED)


def _compare(rec: _Recorder, tx: WalletTransaction, theirs: dict[str, Any] | None) -> None:
    subject = tx_public_id(tx.id)
    their_status = theirs["status"] if theirs else "NOT_FOUND"
    detail = {
        "type": tx.type,
        "bet_id": tx.bet.public_id,
        "ours": {"status": tx.status, "amount": str(tx.amount_minor), "currency": tx.currency},
        "theirs": theirs or {"status": "NOT_FOUND"},
    }
    if tx.status == TX.Status.SUCCEEDED:
        if their_status != "OK":
            rec.open("MISSING_AT_OPERATOR", subject, tx.operator_id, detail)
        elif theirs and (
            theirs.get("amount", str(tx.amount_minor)) != str(tx.amount_minor)
            or theirs.get("currency", tx.currency) != tx.currency
        ):
            rec.open("AMOUNT_MISMATCH", subject, tx.operator_id, detail)
        return
    # We recorded the debit as rejected; if the operator applied it, the player was charged
    # for a bet that never existed: refund through a rollback (same deterministic id rules).
    if tx.type == TX.Type.DEBIT and their_status == "OK":
        from luxrocket.gaming.betting import _enqueue_rollback

        with transaction.atomic():
            bet = Bet.objects.select_for_update().get(pk=tx.bet_id)
            if not TX.objects.filter(bet=bet, type=TX.Type.ROLLBACK).exists():
                _enqueue_rollback(bet)
        rec.auto("OPERATOR_APPLIED_REJECTED_DEBIT", subject, tx.operator_id, detail)


def run_all_operators(now: Any = None) -> list[ReconciliationRun]:
    ops = Operator.objects.filter(
        pk__in=TX.objects.filter(bet__session__wallet_kind=WalletKind.SEAMLESS_V1).values(
            "operator_id"
        )
    )
    return [run_operator(op, now) for op in ops]
