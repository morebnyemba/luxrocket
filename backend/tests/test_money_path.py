"""Bet -> admission -> cash-out / loss / void -> wallet -> ledger, end to end through the APIs."""

import uuid

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.models import Sum

from luxrocket.core.multiplier import payout_minor
from luxrocket.gaming.models import Bet, GameRound
from luxrocket.wallet.models import LedgerEntry, SandboxWalletAccount, Settlement, WalletTransaction
from tests.factories import INTERNAL, create_session, make_operator
from tests.rt import RoundSim

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(client):
    demo = make_operator()
    data = create_session(client, demo, player="alice")
    r = client.post(
        "/game/v1/sessions/exchange",
        {"launch_token": data["launch_token"]},
        content_type="application/json",
    )
    sim = RoundSim.with_min_crash(20_000)
    send(client, sim.created(), sim.opened())
    return {
        "demo": demo,
        "session_id": data["session_id"],
        "sim": sim,
        "token": r.json()["game_session_token"],
    }


def send(client, *events, expect=200):
    r = client.post(
        "/internal/v1/rt-events",
        {"events": list(events)},
        content_type="application/json",
        **INTERNAL,
    )
    assert r.status_code == expect, r.content
    return r.json()


def bet(client, world, panel=0, stake="500", auto=None, command=None, fencing=1):
    payload = {
        "session_id": world["session_id"],
        "round_id": str(world["sim"].round_id),
        "command_id": command or str(uuid.uuid4()),
        "panel": panel,
        "stake": stake,
        "debit_deadline_ms": world["sim"].deadline_ms(),
        "fencing_token": fencing,
        "stream_id": "global",
    }
    if auto is not None:
        payload["auto_cashout_x10000"] = auto
    return client.post(
        "/internal/v1/bets", payload, content_type="application/json", **INTERNAL
    ).json()


def balance():
    return SandboxWalletAccount.objects.get().balance_minor


def ledger_by_account():
    return {
        row["account"]: row["s"]
        for row in LedgerEntry.objects.values("account").annotate(s=Sum("amount_minor"))
    }


def test_two_panels_win_and_lose_independently(client, world):
    sim = world["sim"]
    a = bet(client, world, panel=0, stake="500", auto=15_000)
    b = bet(client, world, panel=1, stake="300")
    assert a["status"] == b["status"] == "ACCEPTED"
    assert balance() == 100_000 - 800
    send(client, sim.admitted(a["bet_id"]), sim.admitted(b["bet_id"]), sim.launched())
    payout = payout_minor(500, 15_000)
    send(client, sim.cashout(a["bet_id"], 15_000, payout, "AUTO"))
    send(client, sim.crashed())

    bet_a = Bet.objects.get(public_id=a["bet_id"])
    bet_b = Bet.objects.get(public_id=b["bet_id"])
    assert bet_a.status == Bet.Status.CASHED_OUT and bet_a.payout_minor == 750
    assert bet_b.status == Bet.Status.LOST
    assert balance() == 100_000 - 800 + 750
    assert Settlement.objects.get(bet=bet_a).status == Settlement.Status.CONFIRMED
    ledger = ledger_by_account()
    assert ledger["player_wallet"] == -800 + 750
    assert ledger["game_result"] == 800 - 750
    assert ledger.get("bets_in_play", 0) == 0 and ledger.get("payouts_payable", 0) == 0
    rnd = GameRound.objects.get(pk=sim.round_id)
    assert rnd.outcome_verified is True
    assert rnd.settlement_status == GameRound.Settlement.SETTLED


def test_duplicate_command_and_panel_are_idempotent(client, world):
    cmd = str(uuid.uuid4())
    first = bet(client, world, command=cmd)
    again = bet(client, world, command=cmd)
    assert again["bet_id"] == first["bet_id"]
    other = bet(client, world, panel=0)
    assert other == {"status": "REJECTED", "code": "PANEL_BUSY"}
    assert balance() == 100_000 - 500


def test_duplicate_facts_apply_once(client, world):
    sim = world["sim"]
    a = bet(client, world)
    admit = sim.admitted(a["bet_id"])
    send(client, admit, sim.launched())
    cash = sim.cashout(a["bet_id"], 20_000, 1000)
    send(client, cash)
    send(client, cash, admit)  # replayed batch
    assert WalletTransaction.objects.filter(type="CREDIT").count() == 1
    assert balance() == 100_000 - 500 + 1000


def test_sequence_gap_is_refused(client, world):
    sim = world["sim"]
    sim.launched()  # consumed seq, never sent
    r = send(client, sim.crashed(), expect=409)
    assert r["expected_seq"] == 3


def test_excluded_bet_is_refunded(client, world):
    sim = world["sim"]
    cmd = str(uuid.uuid4())
    a = bet(client, world, command=cmd)
    send(client, sim.excluded(world["session_id"], cmd), sim.launched(), sim.crashed())
    bet_a = Bet.objects.get(public_id=a["bet_id"])
    assert bet_a.status == Bet.Status.EXCLUDED
    assert balance() == 100_000
    assert ledger_by_account().get("player_wallet", 0) == 0


def test_debited_but_never_admitted_is_refunded_at_crash(client, world):
    sim = world["sim"]
    bet(client, world)
    send(client, sim.launched(), sim.crashed())
    assert balance() == 100_000


def test_void_refunds_uncashed_and_pays_cashed(client, world):
    sim = world["sim"]
    a = bet(client, world, panel=0)
    b = bet(client, world, panel=1)
    send(client, sim.admitted(a["bet_id"]), sim.admitted(b["bet_id"]), sim.launched())
    send(client, sim.cashout(a["bet_id"], 12_345, payout_minor(500, 12_345)))
    send(client, sim.voided())
    assert Bet.objects.get(public_id=b["bet_id"]).status == Bet.Status.VOIDED
    assert balance() == 100_000 - 1000 + payout_minor(500, 12_345) + 500


def test_payout_mismatch_is_not_credited(client, world):
    sim = world["sim"]
    a = bet(client, world)
    send(
        client, sim.admitted(a["bet_id"]), sim.launched(), sim.cashout(a["bet_id"], 20_000, 999_999)
    )
    assert not WalletTransaction.objects.filter(type="CREDIT").exists()
    assert (
        Settlement.objects.get(bet__public_id=a["bet_id"]).status
        == Settlement.Status.NEEDS_ATTENTION
    )


def test_forged_outcome_fails_verification(client, world):
    sim = world["sim"]
    send(client, sim.launched(), sim.crashed(crash=sim.crash + 100))
    rnd = GameRound.objects.get(pk=sim.round_id)
    assert rnd.outcome_verified is False
    assert rnd.settlement_status == GameRound.Settlement.NEEDS_ATTENTION


def test_unknown_debit_is_rolled_back(client, world, settings):
    settings.SANDBOX_DEBIT_UNKNOWN_RATE = 1.0  # debit lands, response "lost"
    result = bet(client, world)
    assert result["status"] == "UNKNOWN"
    settings.SANDBOX_DEBIT_UNKNOWN_RATE = 0.0
    from luxrocket.wallet import worker

    worker.process_pending()
    assert balance() == 100_000
    assert WalletTransaction.objects.get(type="ROLLBACK").status == "SUCCEEDED"


def test_limits_and_validation(client, world):
    assert bet(client, world, stake="5")["code"] == "STAKE_OUT_OF_RANGE"
    assert bet(client, world, auto=15_050)["code"] == "AUTO_CASHOUT_INVALID"
    assert bet(client, world, stake="200000")["code"] == "STAKE_OUT_OF_RANGE"


def test_insufficient_funds(client, world):
    SandboxWalletAccount.objects.update(balance_minor=100)
    assert bet(client, world, stake="500")["code"] == "INSUFFICIENT_FUNDS"


def test_stale_coordinator_is_rejected(client, world):
    assert bet(client, world, fencing=5)["status"] == "ACCEPTED"
    assert bet(client, world, panel=1, fencing=4)["code"] == "STALE_COORDINATOR"


def test_betting_closed_after_launch(client, world):
    send(client, world["sim"].launched())
    assert bet(client, world)["code"] == "BETTING_CLOSED"


def test_ledger_is_append_only_and_balanced(client, world):
    a = bet(client, world)
    entry = LedgerEntry.objects.filter(bet__public_id=a["bet_id"]).first()
    with pytest.raises(DatabaseError), transaction.atomic():
        LedgerEntry.objects.filter(pk=entry.pk).update(amount_minor=1)
    with pytest.raises(DatabaseError), transaction.atomic():
        LedgerEntry.objects.create(
            journal_id=uuid.uuid4(),
            operator_id=entry.operator_id,
            account="game_result",
            amount_minor=5,
            currency="USD",
            bet_id=entry.bet_id,
            memo="bogus",
        )
        with connection.cursor() as c:
            c.execute("SET CONSTRAINTS ALL IMMEDIATE")
