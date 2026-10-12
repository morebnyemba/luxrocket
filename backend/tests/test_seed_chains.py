"""Seed-chain ceremony on the platform side (doc 07 §6.1): beacon, four-eyes activation, gate."""

from datetime import timedelta
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from luxrocket.console.models import ApprovalRequest, Role
from luxrocket.core.lr1 import b64url_decode, platform_public_keys
from luxrocket.gaming import fairness
from luxrocket.wallet.models import OutboxEvent
from tests.rt_chains import active_drand_chain, beacon, insert_chain, past_round
from tests.test_console import call, signed_in

pytestmark = pytest.mark.django_db


class Relays:
    """Stands in for the drand HTTP relays."""

    def __init__(self) -> None:
        self.answers: list[Any] = []
        self.urls: list[str] = []

    def __call__(self, url: str, timeout: float) -> httpx.Response:
        self.urls.append(url)
        answer = self.answers.pop(0) if self.answers else httpx.ConnectError("down")
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(200, json=answer)


@pytest.fixture
def relays(monkeypatch, settings):
    settings.DRAND_URLS = ["https://relay-1.test", "https://relay-2.test"]
    r = Relays()
    monkeypatch.setattr(fairness.httpx, "get", r)
    return r


def request_activation(client, chain_id, payload=None):
    return call(
        client,
        "post",
        "approvals",
        {
            "action": "ACTIVATE_SEED_CHAIN",
            "subject": chain_id,
            "reason": "ceremony 2026-10",
            "payload": payload or {},
        },
    )


def test_activation_is_four_eyes_and_uses_the_beacon_the_platform_fetched(client, relays):
    r = past_round()
    chain_id = insert_chain(drand_round=r)
    real = beacon(r)
    relays.answers = [httpx.ConnectError("relay 1 down"), real]
    gr = signed_in(Role.GAME_RELEASE, "gr@lux.test")

    # Whatever the requester claims, the beacon is fetched by the platform itself.
    forged = {"randomness": "00" * 32, "signature": "00", "drand_round": "1"}
    resp = request_activation(gr, chain_id, forged)
    assert resp.status_code == 201, resp.json()
    payload = resp.json()["payload"]
    assert payload["randomness"] == real["randomness"]
    assert payload["drand_round"] == str(r) and payload["stream"] == "global"
    assert relays.urls[1] == f"https://relay-2.test/{fairness.settings.DRAND_CHAIN_HASH}/public/{r}"

    approval = resp.json()["id"]
    assert (
        call(gr, "post", f"approvals/{approval}/approve", {"note": "x"}).json()["code"]
        == "SELF_APPROVAL"
    )
    ops = signed_in(Role.OPS, "ops@lux.test")
    assert (
        call(ops, "post", f"approvals/{approval}/approve", {"note": "x"}).json()["code"]
        == "FORBIDDEN"
    )
    assert not OutboxEvent.objects.filter(type="seed_chain.activate").exists()

    risk = signed_in(Role.RISK, "risk@lux.test")
    ok = call(risk, "post", f"approvals/{approval}/approve", {"note": "beacon checked"})
    assert ok.status_code == 200, ok.json()
    event = OutboxEvent.objects.get(type="seed_chain.activate")
    assert event.payload == {
        "chain_id": chain_id,
        "stream": "global",
        "drand_round": r,
        "randomness": real["randomness"],
        "signature": real["signature"],
    }


def test_beacon_must_be_published_and_consistent(client, relays):
    gr = signed_in(Role.GAME_RELEASE, "gr@lux.test")
    future = past_round(timedelta(hours=-2))
    early = insert_chain(drand_round=future)
    resp = request_activation(gr, early)
    assert resp.status_code == 409 and resp.json()["code"] == "BEACON_UNAVAILABLE"
    assert relays.urls == []  # not even asked before the round time

    r = past_round()
    chain_id = insert_chain(drand_round=r)
    bad = beacon(r) | {"randomness": "11" * 32}
    relays.answers = [bad, beacon(r + 1)]  # inconsistent, then the wrong round
    resp = request_activation(gr, chain_id)
    assert resp.json()["code"] == "BEACON_UNAVAILABLE"
    assert ApprovalRequest.objects.count() == 0


def test_commitments_must_predate_their_salt(client, relays):
    gr = signed_in(Role.GAME_RELEASE, "gr@lux.test")
    r = past_round()
    rushed = insert_chain(drand_round=r, committed_at=fairness.round_time(r) - timedelta(hours=1))
    relays.answers = [beacon(r)]
    resp = request_activation(gr, rushed)
    assert "too close to the commitment" in resp.json()["detail"]

    foreign = insert_chain(drand_round=r, chain_hash="ab" * 32)
    relays.answers = [beacon(r)]
    assert "untrusted drand network" in request_activation(gr, foreign).json()["detail"]

    active = active_drand_chain("other")
    assert "only a COMMITTED" in request_activation(gr, active).json()["detail"]


def test_the_chain_list_carries_signed_commitments(client):
    chain_id = insert_chain()
    resp = client.get("/.well-known/luxrocket-chains.json")
    assert resp.status_code == 200
    [chain] = [c for c in resp.json()["chains"] if c["chain_id"] == chain_id]
    assert chain["status"] == "COMMITTED" and chain["salt"] is None
    assert "root_seed_ct" not in chain and "drand_signature" in chain

    [key] = platform_public_keys()
    assert chain["commitment"]["kid"] == key["kid"]
    public = Ed25519PublicKey.from_public_bytes(b64url_decode(key["public_key"]))
    statement = chain["commitment"]["statement"]
    public.verify(b64url_decode(chain["commitment"]["signature"]), statement.encode())
    assert statement.split("\n")[:2] == ["LRCHAIN1", chain_id]
    assert str(chain["drand_round"]) in statement

    console = signed_in(Role.AUDITOR, "aud@lux.test")
    [row] = [c for c in call(console, "get", "games/seed-chains").json()["seed_chains"]]
    assert row["beacon_due"] is True and row["usage_bp"] == 0


def test_real_money_needs_a_ceremony_chain_on_the_operators_stream(client):
    from tests.factories import make_operator
    from tests.test_console import EVIDENCE, _ready_for_real_money

    op = make_operator("Gate Op").operator
    _ready_for_real_money(op, chain=False)
    su = signed_in(Role.SUPERADMIN, "su@lux.test")
    req = {"action": "ENABLE_REAL_MONEY", "reason": "go live", "payload": EVIDENCE}
    path = f"operators/{op.public_id}/approvals"
    assert "ceremony seed chain" in call(su, "post", path, req).json()["detail"]

    # A dev chain (local-random salt) does not count.
    insert_chain(op.stream_slug, status="ACTIVE", salt="aa" * 32, salt_source="local-random")
    assert "ceremony seed chain" in call(su, "post", path, req).json()["detail"]

    active_drand_chain("other-stream")
    assert call(su, "post", path, req).status_code == 422  # another stream's chain is irrelevant
