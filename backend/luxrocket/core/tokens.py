"""Opaque single-use tokens: only the SHA-256 hash is stored (ADR-014, doc 11 §4)."""

import hashlib
import hmac
import secrets


def new_token(prefix: str, nbytes: int = 32) -> str:
    return f"{prefix}_{secrets.token_urlsafe(nbytes)}"


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
