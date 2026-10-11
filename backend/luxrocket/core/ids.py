"""Identifiers: UUIDv7 (time-ordered) and prefixed public ids (README conventions)."""

import os
import time
import uuid

_B32 = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford base32, lowercase


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7: 48-bit unix ms timestamp + random bits."""
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version
    value |= ((rand >> 62) & 0xFFF) << 64  # rand_a (12 bits)
    value |= 0b10 << 62  # variant
    value |= rand & ((1 << 62) - 1)
    return uuid.UUID(int=value)


def b32(u: uuid.UUID) -> str:
    """26-char Crockford base32 encoding of a UUID (sortable for UUIDv7)."""
    n = u.int
    out = []
    for _ in range(26):
        out.append(_B32[n & 31])
        n >>= 5
    return "".join(reversed(out))


def public_id(prefix: str, u: uuid.UUID) -> str:
    return f"{prefix}_{b32(u)}"


def deterministic_tx_id(bet_id: uuid.UUID, tx_type: str) -> uuid.UUID:
    """Transaction ids are a pure function of (bet, type): re-deriving can never mint a new id."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"luxrocket:tx:{bet_id}:{tx_type}")


def tx_public_id(tx_id: uuid.UUID | str) -> str:
    """The one wire form of a wallet transaction id (wallet calls, operator API, webhooks)."""
    return public_id("tx", tx_id if isinstance(tx_id, uuid.UUID) else uuid.UUID(str(tx_id)))
