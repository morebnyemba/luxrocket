"""LR1 request signing shared by both directions (doc 09 §3, ADR-010).

String to sign: "LR1\\n{METHOD}\\n{path_with_query}\\n{timestamp}\\n{nonce}\\n{sha256_hex(body)}".
Operators sign calls to us with their key; we sign wallet calls and webhooks with the platform key.
"""

import base64
import hashlib
import secrets
import time
from functools import cache

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.conf import settings


def string_to_sign(method: str, path: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    digest = hashlib.sha256(body).hexdigest()
    return f"LR1\n{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{digest}".encode()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_headers(
    key: Ed25519PrivateKey, kid: str, method: str, path: str, body: bytes
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    signature = key.sign(string_to_sign(method, path, timestamp, nonce, body))
    return {
        "LR-Key-Id": kid,
        "LR-Timestamp": timestamp,
        "LR-Nonce": nonce,
        "LR-Signature": f"ed25519={b64url(signature)}",
    }


@cache
def platform_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(settings.PLATFORM_SIGNING_KEY_B64))


def platform_sign_headers(method: str, path: str, body: bytes) -> dict[str, str]:
    return sign_headers(platform_key(), settings.PLATFORM_SIGNING_KID, method, path, body)


def platform_public_keys() -> list[dict[str, str]]:
    """Published at /.well-known/luxrocket-keys.json so operators can verify our calls."""
    raw = platform_key().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return [{"kid": settings.PLATFORM_SIGNING_KID, "alg": "Ed25519", "public_key": b64url(raw)}]
