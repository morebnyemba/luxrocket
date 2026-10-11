"""Executes pending credits and rollbacks until acknowledged (doc 08 §6)."""

import logging
import time
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from luxrocket.core.ids import deterministic_tx_id
from luxrocket.gaming.journal import refresh_round_settlement
from luxrocket.gaming.models import Bet
from luxrocket.wallet import ledger
from luxrocket.wallet.adapters import WalletResult, adapter_for
from luxrocket.wallet.models import Settlement, WalletTransaction, WalletTxAttempt
from luxrocket.wallet.outbox import emit

log = logging.getLogger(__name__)

# Retry schedule in seconds; after the last step, retry hourly until 72 h, then NEEDS_ATTENTION.
BACKOFF = [1, 2, 5, 15, 30, 60, 300, 900]
GIVE_UP_AFTER = timedelta(hours=72)


def _next_delay(attempt: int) -> int:
    return BACKOFF[attempt - 1] if attempt - 1 < len(BACKOFF) else 3600


def process_pending(limit: int = 100) -> int:
    now = timezone.now()
    with transaction.atomic():
        ids = list(
            WalletTransaction.objects.select_for_update(skip_locked=True)
            .filter(
                type__in=[WalletTransaction.Type.CREDIT, WalletTransaction.Type.ROLLBACK],
                status__in=[WalletTransaction.Status.PENDING, WalletTransaction.Status.UNKNOWN],
            )
            .exclude(next_attempt_at__gt=now)
            .order_by("created_at")
            .values_list("id", flat=True)[:limit]
        )
    done = 0
    for tx_id in ids:
        if _process(tx_id):
            done += 1
    return done


def _process(tx_id: object) -> bool:
    tx = WalletTransaction.objects.select_related(
        "bet", "bet__player", "bet__session", "bet__session__operator"
    ).get(pk=tx_id)
    if tx.status not in (WalletTransaction.Status.PENDING, WalletTransaction.Status.UNKNOWN):
        return False
    bet = tx.bet
    adapter = adapter_for(bet.session)
    started = time.monotonic()
    try:
        if tx.type == WalletTransaction.Type.CREDIT:
            result = adapter.credit(tx)
        else:
            result = adapter.rollback(tx, deterministic_tx_id(bet.id, "DEBIT"))
    except Exception:
        log.exception("wallet %s raised; will retry", tx.type)
        result = WalletResult("UNKNOWN", "ADAPTER_ERROR")
    latency = int((time.monotonic() - started) * 1000)

    with transaction.atomic():
        tx = WalletTransaction.objects.select_for_update().get(pk=tx_id)
        bet = Bet.objects.select_for_update().select_related("session").get(pk=tx.bet_id)
        tx.attempt_count += 1
        WalletTxAttempt.objects.create(
            transaction=tx,
            attempt_no=tx.attempt_count,
            outcome=result.outcome,
            operator_code=result.code,
            latency_ms=latency,
        )
        if result.outcome == "OK":
            tx.status = WalletTransaction.Status.SUCCEEDED
            tx.save()
            _on_success(tx, bet, result)
            transaction.on_commit(lambda: refresh_round_settlement(bet.round_id))
            return True
        if result.outcome == "REJECTED" or timezone.now() - tx.created_at > GIVE_UP_AFTER:
            # A credit or rollback must never be refused (doc 01 §2): human attention required.
            tx.status = WalletTransaction.Status.NEEDS_ATTENTION
            log.critical("wallet %s %s needs attention: %s", tx.type, tx.id, result.code)
        else:
            tx.status = WalletTransaction.Status.UNKNOWN
            tx.next_attempt_at = timezone.now() + timedelta(seconds=_next_delay(tx.attempt_count))
        tx.operator_code = result.code
        tx.save()
        return False


def _on_success(tx: WalletTransaction, bet: Bet, result: WalletResult) -> None:
    now = timezone.now()
    payload = {
        "session_id": bet.session.public_id,
        "bet_id": bet.public_id,
        "panel": bet.panel,
        "amount": str(tx.amount_minor),
    }
    if result.balance_minor is not None:
        payload["balance"] = str(result.balance_minor)
    if tx.type == WalletTransaction.Type.CREDIT:
        ledger.credit_ok(bet, tx.amount_minor)
        Settlement.objects.filter(bet=bet).update(
            status=Settlement.Status.CONFIRMED, confirmed_at=now
        )
        emit("settlement.confirmed", {**payload, "kind": "CREDIT"})
        return
    # Rollback: only post ledger entries if the debit was recorded on our side.
    debit_recorded = WalletTransaction.objects.filter(
        bet=bet, type=WalletTransaction.Type.DEBIT, status=WalletTransaction.Status.SUCCEEDED
    ).exists()
    if debit_recorded:
        ledger.rollback_ok(bet)
        Settlement.objects.filter(bet=bet).update(
            status=Settlement.Status.CONFIRMED, confirmed_at=now
        )
    emit("settlement.confirmed", {**payload, "kind": "REFUND"})
