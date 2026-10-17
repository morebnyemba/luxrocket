"""Test fixtures for the platform domain."""

import base64
import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from luxrocket.operators.models import (
    Market,
    Operator,
    OperatorCredential,
    OperatorCurrencyLimit,
    OperatorJurisdiction,
)


@dataclass
class DemoOperator:
    operator: Operator
    kid: str
    key: Ed25519PrivateKey

    def headers(self, method: str, path: str, body: bytes, *, idem: str | None = None) -> dict:
        ts = str(int(time.time()))
        nonce = secrets.token_hex(16)
        msg = f"LR1\n{method}\n{path}\n{ts}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode()
        sig = base64.urlsafe_b64encode(self.key.sign(msg)).decode().rstrip("=")
        h = {
            "HTTP_LR_KEY_ID": self.kid,
            "HTTP_LR_TIMESTAMP": ts,
            "HTTP_LR_NONCE": nonce,
            "HTTP_LR_SIGNATURE": f"ed25519={sig}",
        }
        if method == "POST":
            h["HTTP_IDEMPOTENCY_KEY"] = idem or str(uuid.uuid4())
        return h


def make_operator(name: str = "Test Op", **limits: int) -> DemoOperator:
    Market.objects.get_or_create(country_code="ZW", defaults={"status": Market.Status.SANDBOX})
    op = Operator.objects.create(legal_name=name, status=Operator.Status.SANDBOX)
    OperatorJurisdiction.objects.create(operator=op, country_code="ZW")
    OperatorCurrencyLimit.objects.create(
        operator=op,
        currency="USD",
        min_stake_minor=limits.get("min_stake", 10),
        max_stake_minor=limits.get("max_stake", 10_000),
        max_win_minor=limits.get("max_win", 1_000_000),
        round_exposure_limit_minor=limits.get("exposure", 50_000_000),
    )
    key = Ed25519PrivateKey.generate()
    kid = f"k_{secrets.token_hex(4)}"
    OperatorCredential.objects.create(
        operator=op,
        kid=kid,
        public_key=key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
    )
    return DemoOperator(op, kid, key)


def session_payload(player: str = "p-1", country: str = "ZW") -> dict:
    return {
        "player": {"id": player, "country": country, "alias": player},
        "currency": "USD",
        "game": "lux-rocket",
        "mode": "SANDBOX",
    }


def create_session(client, demo: DemoOperator, player: str = "p-1") -> dict:
    body = json.dumps(session_payload(player)).encode()
    path = "/operator/v1/sessions"
    r = client.post(path, body, content_type="application/json", **demo.headers("POST", path, body))
    assert r.status_code == 201, r.content
    return r.json()


INTERNAL = {"HTTP_AUTHORIZATION": "Bearer test-internal-token"}
