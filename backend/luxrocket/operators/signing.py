"""Operator request signing, scheme LR1 (doc 09 §3, ADR-010).

Verifies operator -> platform calls (string to sign in `luxrocket.core.lr1`).
Signature header: "ed25519=<base64url>". Only the operator's public key is stored.
"""

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.db import IntegrityError, transaction
from django.utils import timezone

from luxrocket.core.lr1 import b64url_decode, string_to_sign
from luxrocket.operators.models import Operator, OperatorCredential, RequestNonce

MAX_SKEW_SECONDS = 300
NONCE_TTL = timedelta(minutes=10)


class SignatureError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class VerifiedOperator:
    operator: Operator
    kid: str


def verify_request(
    *, method: str, path: str, headers: Mapping[str, str], body: bytes, now: float | None = None
) -> VerifiedOperator:
    kid = headers.get("LR-Key-Id", "")
    timestamp = headers.get("LR-Timestamp", "")
    nonce = headers.get("LR-Nonce", "")
    signature = headers.get("LR-Signature", "")
    if not (kid and timestamp and nonce and signature):
        raise SignatureError("INVALID_SIGNATURE")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise SignatureError("INVALID_SIGNATURE") from exc
    if abs((now or time.time()) - ts) > MAX_SKEW_SECONDS:
        raise SignatureError("TIMESTAMP_OUT_OF_WINDOW")
    if len(nonce) < 16 or len(nonce) > 128:
        raise SignatureError("INVALID_SIGNATURE")

    cred = (
        OperatorCredential.objects.select_related("operator")
        .filter(kid=kid, status=OperatorCredential.Status.ACTIVE)
        .first()
    )
    if cred is None:
        raise SignatureError("UNKNOWN_KEY")
    scheme, _, sig_b64 = signature.partition("=")
    if scheme != "ed25519" or not sig_b64:
        raise SignatureError("INVALID_SIGNATURE")
    try:
        Ed25519PublicKey.from_public_bytes(bytes(cred.public_key)).verify(
            b64url_decode(sig_b64), string_to_sign(method, path, timestamp, nonce, body)
        )
    except (InvalidSignature, ValueError) as exc:
        raise SignatureError("INVALID_SIGNATURE") from exc

    # Nonce is recorded only after the signature verifies, so attackers cannot burn nonces.
    try:
        with transaction.atomic():
            RequestNonce.objects.create(kid=kid, nonce=nonce)
    except IntegrityError as exc:
        raise SignatureError("NONCE_REUSED") from exc
    OperatorCredential.objects.filter(pk=cred.pk).update(last_used_at=timezone.now())
    return VerifiedOperator(operator=cred.operator, kid=kid)


def prune_nonces() -> int:
    deleted, _ = RequestNonce.objects.filter(created_at__lt=timezone.now() - NONCE_TTL).delete()
    return deleted
