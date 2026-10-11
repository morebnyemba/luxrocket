"""RFC 6238 TOTP (SHA-1, 6 digits, 30 s) with the secret encrypted at rest (AES-GCM)."""

import base64
import hashlib
import hmac
import os
import struct
import time
from urllib.parse import quote

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

STEP = 30
DIGITS = 6
WINDOW = 1  # accept the previous and next step for clock drift


def new_secret() -> bytes:
    return os.urandom(20)


def b32(secret: bytes) -> str:
    return base64.b32encode(secret).decode().rstrip("=")


def provisioning_uri(secret: bytes, account: str, issuer: str = "LUX ROCKET") -> str:
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={b32(secret)}&issuer={quote(issuer)}&digits={DIGITS}"


def code_at(secret: bytes, step: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def verify(secret: bytes, code: str, last_step: int, now: float | None = None) -> int | None:
    """Returns the matched step (store it: a code is never accepted twice), or None."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    current = int((now or time.time()) // STEP)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if step > last_step and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def _key() -> bytes:
    return base64.b64decode(settings.PORTAL_SECRETS_KEY_B64)


def encrypt(secret: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_key()).encrypt(nonce, secret, b"lr-totp")


def decrypt(blob: bytes | memoryview) -> bytes:
    blob = bytes(blob)
    return AESGCM(_key()).decrypt(blob[:12], blob[12:], b"lr-totp")
