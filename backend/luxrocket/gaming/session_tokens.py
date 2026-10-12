"""Game-session tokens: short-lived Ed25519-signed JWS held only in browser memory (ADR-022)."""

import base64
import time
from functools import lru_cache
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.conf import settings

AUDIENCE = "luxrocket-game"
ISSUER = "luxrocket-platform"


@lru_cache(maxsize=1)
def _private_key() -> Ed25519PrivateKey:
    raw = base64.b64decode(settings.GAME_TOKEN_PRIVATE_KEY_B64)
    if len(raw) != 32:
        raise RuntimeError("GAME_TOKEN_PRIVATE_KEY_B64 must decode to 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(raw)


def issue(
    *, session_id: str, operator_id: str, session_version: int, ttl: int | None = None
) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sid": session_id,
        "op": operator_id,
        "sv": session_version,
        "iat": now,
        "exp": now + (ttl or settings.GAME_TOKEN_TTL_SECONDS),
    }
    return jwt.encode(claims, _private_key(), algorithm="EdDSA")


class InvalidToken(Exception):
    pass


def verify(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            _private_key().public_key(),
            algorithms=["EdDSA"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "sid", "sv", "op"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc
