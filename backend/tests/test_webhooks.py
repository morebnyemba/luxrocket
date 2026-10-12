"""Operator webhooks: outbox rows created with the state change, signed delivery, retries."""

from datetime import timedelta

import pytest
from django.utils import timezone

from luxrocket.core import contracts
from luxrocket.core.ids import tx_public_id
from luxrocket.core.multiplier import payout_minor
from luxrocket.operators.models import WebhookDelivery, WebhookEndpoint
from luxrocket.operators.webhooks import RETRY, deliver_due
from luxrocket.wallet.models import WalletTransaction
from tests.test_money_path import bet, send
from tests.test_seamless_wallet import Sim, world  # noqa: F401 (fixture)

pytestmark = pytest.mark.django_db


@pytest.fixture
def sim():
    s = Sim()
    yield s
    s.stop()


@pytest.fixture
def hooked(world, sim):  # noqa: F811
    WebhookEndpoint.objects.create(operator=world["demo"].operator, url=f"{sim.url}/webhooks")
    return world


def _play_round(client, w):
    rsim = w["sim"]
    a = bet(client, w, panel=0, stake="500")
    b = bet(client, w, panel=1, stake="300")
    send(client, rsim.admitted(a["bet_id"]), rsim.admitted(b["bet_id"]), rsim.launched())
    send(client, rsim.cashout(a["bet_id"], 20_000, payout_minor(500, 20_000)))
    send(client, rsim.crashed())
    return a, b


def test_settlement_events_are_delivered_signed_and_conformant(client, hooked, sim):
    a, b = _play_round(client, hooked)
    assert deliver_due() == 3
    events = sim.ledger.events()
    assert all(not contracts.errors("operator/v1/webhook.schema.json", e) for e in events)
    settled = {e["data"]["bet_id"]: e["data"] for e in sim.ledger.events("bet.settled")}
    assert settled[a["bet_id"]]["outcome"] == "WIN" and settled[a["bet_id"]]["payout"] == "1000"
    assert settled[b["bet_id"]]["outcome"] == "LOSS" and settled[b["bet_id"]]["payout"] == "0"
    debit = WalletTransaction.objects.get(bet__public_id=a["bet_id"], type="DEBIT")
    assert tx_public_id(debit.id) in {
        t["transaction_id"] for t in settled[a["bet_id"]]["transactions"]
    }
    (rnd,) = sim.ledger.events("round.settled")
    assert rnd["data"]["bets"] == 2
    assert rnd["data"]["totals"] == [{"currency": "USD", "stake": "800", "payout": "1000"}]
    assert WebhookDelivery.objects.filter(status="DELIVERED").count() == 3


def test_round_settled_is_emitted_once_even_if_the_crash_repeats(client, hooked, sim):
    _play_round(client, hooked)
    send(client, hooked["sim"].crashed(), expect=200)  # replayed crash fact
    from luxrocket.gaming.journal import refresh_round_settlement

    refresh_round_settlement(hooked["sim"].round_id)
    assert WebhookDelivery.objects.filter(type="round.settled").count() == 1


def test_failed_deliveries_retry_then_give_up(client, hooked, sim):
    _play_round(client, hooked)
    sim.faults.fail_rate = 1.0  # the operator's webhook receiver is down
    assert deliver_due() == 0
    d = WebhookDelivery.objects.filter(type="bet.settled").first()
    assert d.status == "PENDING" and d.attempts == 1 and d.last_status_code == 500
    assert d.next_attempt_at > timezone.now() + timedelta(seconds=RETRY[0] - 5)
    for _ in RETRY:
        WebhookDelivery.objects.update(next_attempt_at=timezone.now())
        deliver_due()
    d.refresh_from_db()
    assert d.status == "FAILED" and d.attempts == len(RETRY) + 1


def test_redelivery_is_deduped_by_the_consumer(client, hooked, sim):
    _play_round(client, hooked)
    deliver_due()
    WebhookDelivery.objects.update(status="PENDING", next_attempt_at=timezone.now())
    deliver_due()
    assert len(sim.ledger.events()) == 3  # same event ids: recorded once


def test_needs_attention_is_notified(client, hooked, sim):
    from luxrocket.wallet import worker
    from luxrocket.wallet.adapters import WalletResult

    a, _ = _play_round(client, hooked)
    tx = WalletTransaction.objects.get(bet__public_id=a["bet_id"], type="CREDIT")
    WalletTransaction.objects.filter(pk=tx.pk).update(status="PENDING")

    class Refusing:
        def credit(self, tx):
            return WalletResult("REJECTED", "PLAYER_BLOCKED")

    import luxrocket.wallet.worker as w

    orig = w.adapter_for
    w.adapter_for = lambda session: Refusing()
    try:
        worker.process_pending()
    finally:
        w.adapter_for = orig
    deliver_due()
    (evt,) = sim.ledger.events("transaction.needs_attention")
    assert evt["data"]["operator_code"] == "PLAYER_BLOCKED"
    assert evt["data"]["transaction"]["type"] == "CREDIT"


def test_no_endpoint_no_rows(client, world):  # noqa: F811
    _play_round(client, world)
    assert not WebhookDelivery.objects.exists()


def test_webhook_url_is_validated(settings):
    from django.core.exceptions import ValidationError

    settings.WALLET_ALLOW_HTTP = False
    with pytest.raises(ValidationError):
        WebhookEndpoint(url="http://op.example/hooks").clean()
    WebhookEndpoint(url="https://op.example/hooks").clean()
