"""Reconciliation: safe auto-repair, open items for everything else, operator lookups."""

from datetime import timedelta

import pytest
from django.utils import timezone

from luxrocket.core.ids import tx_public_id, uuid7
from luxrocket.core.multiplier import payout_minor
from luxrocket.gaming.models import Bet, GameRound
from luxrocket.operators.models import WebhookDelivery, WebhookEndpoint
from luxrocket.wallet import reconciliation, worker
from luxrocket.wallet.models import (
    Discrepancy,
    LedgerEntry,
    OperatorReconCursor,
    SandboxWalletAccount,
    Settlement,
    WalletTransaction,
)
from tests.test_money_path import bet, send
from tests.test_money_path import world as sandbox_world  # noqa: F401 (fixture)
from tests.test_seamless_wallet import Sim, world  # noqa: F401 (fixture)

pytestmark = pytest.mark.django_db
LATER = timedelta(minutes=30)  # judge state as if the grace periods had passed


def later():
    return timezone.now() + LATER


def open_kinds():
    return sorted(Discrepancy.objects.filter(status="OPEN").values_list("kind", flat=True))


def sbx_balance():
    return SandboxWalletAccount.objects.get().balance_minor


# ---- Internal --------------------------------------------------------------------------------


def test_clean_books_reconcile_clean(client, sandbox_world):  # noqa: F811
    w = sandbox_world
    a = bet(client, w, stake="500")
    send(client, w["sim"].admitted(a["bet_id"]), w["sim"].launched())
    send(client, w["sim"].cashout(a["bet_id"], 20_000, payout_minor(500, 20_000)))
    send(client, w["sim"].crashed())
    run = reconciliation.run_internal(later())
    assert run.status == "COMPLETED" and run.opened == 0 and run.auto_resolved == 0
    assert not Discrepancy.objects.exists()


def test_debit_whose_worker_died_is_rolled_back(client, sandbox_world, monkeypatch):  # noqa: F811
    import luxrocket.gaming.betting as betting

    def die(*args, **kwargs):
        raise SystemExit("process killed after the wallet answered")

    # The wallet takes the money, then the process dies before phase 2 records anything.
    monkeypatch.setattr(betting.WalletTxAttempt.objects, "create", die)
    with pytest.raises(SystemExit):
        betting.place_bet(
            {
                "session_id": sandbox_world["session_id"],
                "round_id": str(sandbox_world["sim"].round_id),
                "command_id": str(uuid7()),
                "panel": 0,
                "stake": "700",
                "debit_deadline_ms": sandbox_world["sim"].deadline_ms(),
                "fencing_token": 1,
                "stream_id": "global",
            }
        )
    monkeypatch.undo()
    assert sbx_balance() == 100_000 - 700
    b = Bet.objects.get()
    assert b.status == "PENDING_DEBIT"
    run = reconciliation.run_internal(later())
    assert run.auto_resolved == 1
    b.refresh_from_db()
    assert b.status == "DEBIT_UNKNOWN"
    worker.process_pending()
    assert sbx_balance() == 100_000
    final = reconciliation.run_internal(later())
    assert final.opened == 0 and final.auto_resolved == 0 and not open_kinds()


def test_cashout_whose_credit_job_was_lost_is_paid_once(client, sandbox_world, monkeypatch):  # noqa: F811
    w = sandbox_world
    a = bet(client, w, stake="500")
    send(client, w["sim"].admitted(a["bet_id"]), w["sim"].launched())
    import luxrocket.gaming.journal as journal

    real = journal._enqueue
    monkeypatch.setattr(journal, "_enqueue", lambda *args, **kw: None)
    send(client, w["sim"].cashout(a["bet_id"], 20_000, 1000))
    monkeypatch.setattr(journal, "_enqueue", real)
    assert sbx_balance() == 100_000 - 500  # not paid
    run = reconciliation.run_internal(later())
    assert run.auto_resolved == 1
    worker.process_pending()
    assert sbx_balance() == 100_000 - 500 + 1000
    assert Settlement.objects.get(bet__public_id=a["bet_id"]).status == "CONFIRMED"
    final = reconciliation.run_internal(later())  # idempotent: nothing more to do
    assert final.auto_resolved == 0 and not open_kinds()
    assert WalletTransaction.objects.filter(type="CREDIT").count() == 1
    assert sbx_balance() == 100_000 - 500 + 1000


def test_unverified_outcome_opens_one_item_across_runs(client, sandbox_world):  # noqa: F811
    w = sandbox_world
    send(client, w["sim"].launched(), w["sim"].crashed(crash=w["sim"].crash + 100))
    reconciliation.run_internal(later())
    reconciliation.run_internal(later())
    assert open_kinds() == ["OUTCOME_UNVERIFIED"]


def test_ledger_that_does_not_clear_is_flagged(client, sandbox_world):  # noqa: F811
    w = sandbox_world
    a = bet(client, w, stake="500")
    send(client, w["sim"].admitted(a["bet_id"]), w["sim"].launched(), w["sim"].crashed())
    b = Bet.objects.get(public_id=a["bet_id"])
    journal_id = uuid7()
    for account, amount in (("payouts_payable", 42), ("game_result", -42)):  # balanced, wrong
        LedgerEntry.objects.create(
            journal_id=journal_id,
            operator_id=b.operator_id,
            account=account,
            amount_minor=amount,
            currency="USD",
            bet=b,
            memo="bogus",
        )
    Bet.objects.filter(pk=b.pk).update(updated_at=timezone.now() - LATER)
    reconciliation.run_internal(later())
    assert open_kinds() == ["LEDGER_NOT_CLEARED"]


# ---- Operator (seamless wallet) ---------------------------------------------------------------


@pytest.fixture
def sim():
    s = Sim()
    yield s
    s.stop()


def _round_with_win(client, w):
    a = bet(client, w, stake="500")
    send(client, w["sim"].admitted(a["bet_id"]), w["sim"].launched())
    send(client, w["sim"].cashout(a["bet_id"], 20_000, 1000))
    send(client, w["sim"].crashed())
    return a


def _sim_exec(sim, sql, *args):
    with sim.ledger.lock:
        sim.ledger.db.execute(sql, args)


def test_operator_books_match(client, world, sim):  # noqa: F811
    _round_with_win(client, world)
    op = world["demo"].operator
    run = reconciliation.run_operator(op, later())
    assert run.status == "COMPLETED" and run.checked == 2 and not Discrepancy.objects.exists()
    assert OperatorReconCursor.objects.get(operator=op).last_updated_at is not None
    again = reconciliation.run_operator(op, later())
    assert again.checked == 0 and again.note == "nothing new"


def test_credit_the_operator_lost_is_opened_and_notified(client, world, sim):  # noqa: F811
    op = world["demo"].operator
    WebhookEndpoint.objects.create(operator=op, url=f"{sim.url}/webhooks")
    a = _round_with_win(client, world)
    credit = WalletTransaction.objects.get(bet__public_id=a["bet_id"], type="CREDIT")
    _sim_exec(sim, "DELETE FROM tx WHERE transaction_id=?", tx_public_id(credit.id))
    reconciliation.run_operator(op, later())
    item = Discrepancy.objects.get(status="OPEN")
    assert item.kind == "MISSING_AT_OPERATOR" and item.subject == tx_public_id(credit.id)
    assert WebhookDelivery.objects.filter(type="reconciliation.discrepancy").count() == 1


def test_amount_mismatch_is_opened(client, world, sim):  # noqa: F811
    a = _round_with_win(client, world)
    debit = WalletTransaction.objects.get(bet__public_id=a["bet_id"], type="DEBIT")
    _sim_exec(sim, "UPDATE tx SET amount=499 WHERE transaction_id=?", tx_public_id(debit.id))
    reconciliation.run_operator(world["demo"].operator, later())
    assert open_kinds() == ["AMOUNT_MISMATCH"]


def test_rejected_debit_the_operator_applied_anyway_is_refunded(client, world, sim):  # noqa: F811
    _sim_exec(sim, "UPDATE account SET balance=100")
    r = bet(client, world, stake="500")
    assert r["code"] == "INSUFFICIENT_FUNDS"
    debit = WalletTransaction.objects.get(type="DEBIT")
    # Operator bug: it charged the player but answered REJECTED.
    _sim_exec(
        sim,
        "UPDATE tx SET response=? WHERE transaction_id=?",
        '{"status": "OK"}',
        tx_public_id(debit.id),
    )
    _sim_exec(sim, "UPDATE account SET balance=balance+1000")  # top-up so the debit "fits"
    _sim_exec(sim, "UPDATE account SET balance=balance-500")
    run = reconciliation.run_operator(world["demo"].operator, later())
    assert run.auto_resolved == 1
    worker.process_pending()
    assert sim.balance("p-seamless") == 100 + 1000  # the wrongful charge was returned


def test_lookup_outage_retries_the_same_window(client, world, sim):  # noqa: F811
    _round_with_win(client, world)
    op = world["demo"].operator
    sim.faults.fail_rate = 1.0
    run = reconciliation.run_operator(op, later())
    assert run.status == "UNAVAILABLE"
    assert OperatorReconCursor.objects.get(operator=op).last_updated_at is None
    sim.faults.fail_rate = 0.0
    assert reconciliation.run_operator(op, later()).checked == 2


# ---- Human resolution ------------------------------------------------------------------------


def test_resolution_requires_a_note(client, sandbox_world):  # noqa: F811
    from luxrocket.wallet.admin import DiscrepancyForm

    w = sandbox_world
    send(client, w["sim"].launched(), w["sim"].crashed(crash=w["sim"].crash + 100))
    reconciliation.run_internal(later())
    item = Discrepancy.objects.get()
    assert not DiscrepancyForm(
        {"status": "RESOLVED", "resolution_note": ""}, instance=item
    ).is_valid()
    assert DiscrepancyForm(
        {"status": "RESOLVED", "resolution_note": "forged test outcome; no bets"}, instance=item
    ).is_valid()
    assert GameRound.objects.filter(outcome_verified=False).exists()
