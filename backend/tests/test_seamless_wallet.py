"""Seamless Wallet v1: real signed HTTP against the reference operator wallet (doc 09 §6)."""

import threading
import uuid
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.db.models import Sum
from django.utils import timezone

from luxrocket.core.lr1 import b64url_decode, platform_public_keys
from luxrocket.core.multiplier import payout_minor
from luxrocket.gaming.models import Bet, GameSession
from luxrocket.wallet import conformance, worker
from luxrocket.wallet.models import LedgerEntry, Settlement, WalletTransaction
from luxrocket.wallet.seamless import classify
from luxrocket.wallet.simulator import Faults, Ledger, serve
from tests.factories import create_session, make_operator, session_payload
from tests.rt import RoundSim
from tests.test_money_path import bet, send

pytestmark = pytest.mark.django_db
PLAYER = "p-seamless"


def _keys() -> dict[str, Ed25519PublicKey]:
    return {
        k["kid"]: Ed25519PublicKey.from_public_bytes(b64url_decode(k["public_key"]))
        for k in platform_public_keys()
    }


class Sim:
    def __init__(self, ledger: Ledger | None = None) -> None:
        self.ledger = ledger or Ledger()
        self.faults = Faults(seed=7)
        self.server = serve(keys=_keys(), prefix="/wallet", ledger=self.ledger, faults=self.faults)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/wallet"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def balance(self, player: str = PLAYER) -> int:
        return self.ledger.balance(player, "USD")

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def sim():
    s = Sim()
    yield s
    s.stop()


@pytest.fixture
def world(client, sim):
    demo = make_operator("Seamless Op")
    demo.operator.wallet_kind = "SEAMLESS_V1"
    demo.operator.wallet_base_url = sim.url
    demo.operator.save()
    data = create_session(client, demo, player=PLAYER)
    r = client.post(
        "/game/v1/sessions/exchange",
        {"launch_token": data["launch_token"]},
        content_type="application/json",
    )
    assert r.status_code == 200
    rsim = RoundSim.with_min_crash(20_000)
    send(client, rsim.created(), rsim.opened())
    return {
        "demo": demo,
        "session_id": data["session_id"],
        "sim": rsim,
        "exchange": r.json(),
    }


def test_platform_keys_are_published(client):
    r = client.get("/.well-known/luxrocket-keys.json")
    assert r.status_code == 200
    (key,) = r.json()["keys"]
    assert key["alg"] == "Ed25519" and key["kid"] == "plat_dev"


def test_reference_wallet_is_conformant(sim):
    report = conformance.run(sim.url, player_id="conformance-1", currency="USD")
    assert report.passed, report.as_text()
    assert all(c.passed for c in report.checks), report.as_text()


class ForgetfulLedger(Ledger):
    """A non-conformant wallet: forgets transaction ids, so replays charge again."""

    def apply(self, op, req):
        with self.lock:
            self.db.execute("DELETE FROM tx WHERE transaction_id=?", (req["transaction_id"],))
        return super().apply(op, req)


def test_conformance_catches_a_non_idempotent_wallet():
    bad = Sim(ForgetfulLedger())
    try:
        report = conformance.run(bad.url, player_id="conformance-2", currency="USD")
    finally:
        bad.stop()
    failed = {c.name for c in report.checks if not c.passed}
    assert not report.passed
    assert "debit replay is idempotent (same result, no second charge)" in failed
    assert "rollback of an unknown debit succeeds and blocks that debit forever" in failed


def test_unsigned_calls_are_refused_by_the_reference_wallet(sim):
    import httpx

    r = httpx.post(f"{sim.url}/debit", json={"transaction_id": "tx_x"})
    assert r.status_code == 401


TX = "tx_" + "0" * 26


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, b'{"status":"OK","transaction_id":"%s","balance":"5"}' % TX.encode(), "OK"),
        (
            200,
            b'{"status":"REJECTED","transaction_id":"%s","code":"INSUFFICIENT_FUNDS"}'
            % TX.encode(),
            "REJECTED",
        ),
        (500, b'{"status":"OK","transaction_id":"%s"}' % TX.encode(), "UNKNOWN"),
        (302, b"", "UNKNOWN"),
        (200, b"<html>gateway</html>", "UNKNOWN"),
        (200, b'{"status":"OK"}', "UNKNOWN"),  # schema violation
        (200, b'{"status":"OK","transaction_id":"tx_other"}', "UNKNOWN"),  # not our tx
        (200, b'{"status":"REJECTED","transaction_id":"%s"}' % TX.encode(), "UNKNOWN"),  # no code
        (
            200,
            b'{"status":"OK","transaction_id":"%s","currency":"EUR"}' % TX.encode(),
            "UNKNOWN",
        ),
    ],
)
def test_response_classification_is_pessimistic(status, body, expected):
    assert classify(status, body, TX, "USD").outcome == expected


def test_win_moves_money_in_the_operator_wallet(client, world, sim):
    assert world["exchange"]["balance"] == "100000"  # read from the operator's /balance
    rsim = world["sim"]
    a = bet(client, world, panel=0, stake="500")
    assert a["status"] == "ACCEPTED" and a["balance"] == "99500"
    assert sim.balance() == 99_500
    send(client, rsim.admitted(a["bet_id"]), rsim.launched())
    send(client, rsim.cashout(a["bet_id"], 20_000, payout_minor(500, 20_000)))
    send(client, rsim.crashed())
    assert sim.balance() == 100_500
    b = Bet.objects.get(public_id=a["bet_id"])
    assert Settlement.objects.get(bet=b).status == Settlement.Status.CONFIRMED
    assert WalletTransaction.objects.get(bet=b, type="CREDIT").status == "SUCCEEDED"
    assert LedgerEntry.objects.aggregate(s=Sum("amount_minor"))["s"] == 0


def test_lost_debit_response_is_rolled_back_with_reason(client, world, sim):
    sim.faults.lose_rate = 1.0  # the operator charges, then the response is lost
    result = bet(client, world, stake="700")
    assert result["status"] == "UNKNOWN"
    assert sim.balance() == 100_000 - 700
    sim.faults.lose_rate = 0.0
    worker.process_pending()
    assert sim.balance() == 100_000
    rb = WalletTransaction.objects.get(type="ROLLBACK")
    assert rb.status == "SUCCEEDED"
    reasons = sim.ledger.db.execute("SELECT kind FROM tx WHERE kind='rollback'").fetchall()
    assert len(reasons) == 1


def test_credit_retries_until_the_wallet_answers(client, world, sim):
    rsim = world["sim"]
    a = bet(client, world, stake="500")
    send(client, rsim.admitted(a["bet_id"]), rsim.launched())
    sim.faults.fail_rate = 1.0  # wallet down when the cash-out happens
    send(client, rsim.cashout(a["bet_id"], 20_000, 1000))
    credit = WalletTransaction.objects.get(type="CREDIT")
    assert credit.status == "UNKNOWN" and credit.operator_code == "HTTP_500"
    sim.faults.fail_rate = 0.0
    WalletTransaction.objects.filter(pk=credit.pk).update(
        next_attempt_at=timezone.now() - timedelta(seconds=1)
    )
    worker.process_pending()
    credit.refresh_from_db()
    assert credit.status == "SUCCEEDED" and credit.attempt_count == 2
    assert sim.balance() == 100_000 - 500 + 1000


def test_slow_debit_times_out_as_unknown(client, world, sim):
    op = world["demo"].operator
    op.wallet_debit_timeout_ms = 100
    op.save()
    sim.faults.latency_ms = 400
    result = bet(client, world)
    assert result["status"] == "UNKNOWN"
    assert WalletTransaction.objects.get(type="DEBIT").operator_code == "TIMEOUT"


def test_credits_follow_the_session_wallet_after_reconfiguration(client, world, sim):
    rsim = world["sim"]
    a = bet(client, world, stake="500")
    op = world["demo"].operator
    op.wallet_kind = "SIMULATED"  # reconfigured mid-session
    op.wallet_base_url = ""
    op.save()
    send(client, rsim.admitted(a["bet_id"]), rsim.launched())
    send(client, rsim.cashout(a["bet_id"], 20_000, 1000))
    assert sim.balance() == 100_000 - 500 + 1000  # still paid where the stake was taken
    assert GameSession.objects.get(public_id=world["session_id"]).wallet_kind == "SEAMLESS_V1"


def _create(client, demo, **overrides):
    import json

    body = json.dumps(session_payload("p-x") | overrides).encode()
    path = "/operator/v1/sessions"
    return client.post(
        path, body, content_type="application/json", **demo.headers("POST", path, body)
    )


def test_real_money_requires_a_seamless_wallet(client):
    demo = make_operator("Live But Simulated")
    op = demo.operator
    op.status = "LIVE"
    op.real_money_enabled = True
    op.save()
    from luxrocket.operators.models import Market

    Market.objects.filter(country_code="ZW").update(status="REAL")
    r = _create(client, demo, mode="REAL")
    assert r.status_code == 403 and r.json()["code"] == "REAL_MONEY_DISABLED"


def test_seamless_operator_without_url_is_refused(client):
    demo = make_operator("Half Configured")
    demo.operator.wallet_kind = "SEAMLESS_V1"
    demo.operator.save()
    r = _create(client, demo)
    assert r.status_code == 403 and r.json()["code"] == "WALLET_NOT_CONFIGURED"


def test_operator_session_token_is_forwarded(client, sim):
    demo = make_operator("Token Op")
    demo.operator.wallet_kind = "SEAMLESS_V1"
    demo.operator.wallet_base_url = sim.url
    demo.operator.save()
    r = _create(client, demo, operator_session_token="opaque-123")
    assert r.status_code == 201
    s = GameSession.objects.get(public_id=r.json()["session_id"])
    assert s.operator_session_token == "opaque-123"
    assert uuid.UUID(str(s.id))


def test_operator_wallet_config_is_validated(settings):
    from django.core.exceptions import ValidationError

    from luxrocket.operators.models import Operator

    op = Operator(legal_name="X", wallet_kind="SEAMLESS_V1", wallet_base_url="ftp://wallet")
    with pytest.raises(ValidationError):
        op.clean()
    settings.WALLET_ALLOW_HTTP = False
    op.wallet_base_url = "http://wallet.example/api"
    with pytest.raises(ValidationError):
        op.clean()
    op.wallet_base_url = "https://wallet.example/api"
    op.clean()
    with pytest.raises(ValidationError):
        Operator(legal_name="Y", real_money_enabled=True).clean()
