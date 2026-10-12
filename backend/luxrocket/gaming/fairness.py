"""Seed-chain ceremony facts and the drand beacon (doc 07 §6.1).

Phoenix owns `rt.seed_chain` (and the encrypted seeds); the platform only reads its public
columns. A chain is COMMITTED by the ceremony with a drand round fixed at least
`SEED_CHAIN_MIN_DELAY_S` ahead; once that round is published, a four-eyes approval sends its
beacon to Phoenix, which salts and activates the chain.
"""

import hashlib
import uuid
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from django.conf import settings
from django.db import connection

from luxrocket.core.lr1 import b64url, platform_key

_COLUMNS = """
    c.chain_id::text, c.stream_id, c.length, c.terminal_hash, c.status, c.salt, c.salt_source,
    c.drand_chain_hash, c.drand_round, c.drand_signature, c.committed_at, c.activated_at,
    c.retired_at, c.inserted_at,
    (SELECT max(r.chain_index) FROM rt.round r WHERE r.chain_id = c.chain_id)
"""


@dataclass(frozen=True)
class Chain:
    chain_id: str
    stream: str
    length: int
    terminal_hash: str
    status: str
    salt: str
    salt_source: str
    drand_chain_hash: str | None
    drand_round: int | None
    drand_signature: str | None
    committed_at: datetime | None
    activated_at: datetime | None
    retired_at: datetime | None
    created_at: datetime
    rounds_used: int

    @property
    def drand_salted(self) -> bool:
        return self.salt_source.startswith("drand:")


def _rt_ready() -> bool:
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('rt.seed_chain') IS NOT NULL")
        row = cur.fetchone()
    return bool(row and row[0])


_FILTERS = {
    "chain_id": "c.chain_id = %s::uuid",
    "stream": "c.stream_id = %s",
    "status": "c.status = %s",
}


def chains(**filters: str) -> list[Chain]:
    """Chains matching the given filters (keys from `_FILTERS`), newest first."""
    if not _rt_ready():
        return []
    where = " AND ".join(_FILTERS[k] for k in filters) or "TRUE"
    # Only constant fragments are interpolated; every value is a bound parameter.
    sql = f"SELECT {_COLUMNS} FROM rt.seed_chain c WHERE {where} ORDER BY c.inserted_at DESC"  # noqa: S608
    with connection.cursor() as cur:
        cur.execute(sql, list(filters.values()))
        rows = cur.fetchall()
    names = [f.name for f in fields(Chain)]
    return [Chain(**dict(zip(names, (*row[:-1], row[-1] or 0), strict=True))) for row in rows]


def chain(chain_id: str) -> Chain | None:
    try:
        uuid.UUID(chain_id)
    except ValueError:
        return None
    found = chains(chain_id=chain_id)
    return found[0] if found else None


def active_chain(stream: str) -> Chain | None:
    found = chains(stream=stream, status="ACTIVE")
    return found[0] if found else None


# ---- drand -----------------------------------------------------------------------------------


def round_time(round_: int) -> datetime:
    return datetime.fromtimestamp(
        settings.DRAND_GENESIS_TIME + (round_ - 1) * settings.DRAND_PERIOD_S, tz=UTC
    )


def min_delay() -> timedelta:
    return timedelta(seconds=settings.SEED_CHAIN_MIN_DELAY_S)


@dataclass(frozen=True)
class Beacon:
    round: int
    randomness: str
    signature: str


class BeaconError(Exception):
    pass


def beacon_consistent(randomness: str, signature: str) -> bool:
    """drand defines randomness = SHA-256(signature). The BLS signature itself is published so
    auditors can check it against the drand network's public key."""
    try:
        return len(randomness) == 64 and hashlib.sha256(bytes.fromhex(signature)).hexdigest() == (
            randomness.lower()
        )
    except ValueError:
        return False


def fetch_beacon(round_: int, chain_hash: str) -> Beacon:
    """Fetch a published beacon from the first relay that answers consistently."""
    if datetime.now(tz=UTC) < round_time(round_):
        raise BeaconError(f"drand round {round_} is published at {round_time(round_).isoformat()}")
    last = "no drand relay configured"
    for base in settings.DRAND_URLS:
        url = f"{base.rstrip('/')}/{chain_hash}/public/{round_}"
        try:
            resp = httpx.get(url, timeout=settings.DRAND_TIMEOUT_S)
            body = resp.json() if resp.status_code == 200 else None
        except (httpx.HTTPError, ValueError) as exc:
            last = f"{base}: {exc.__class__.__name__}"
            continue
        if not isinstance(body, dict):
            last = f"{base}: HTTP {resp.status_code}"
            continue
        randomness, signature = str(body.get("randomness", "")), str(body.get("signature", ""))
        if body.get("round") != round_ or not beacon_consistent(randomness, signature):
            last = f"{base}: inconsistent beacon"
            continue
        return Beacon(round_, randomness.lower(), signature.lower())
    raise BeaconError(last)


# ---- public commitments ----------------------------------------------------------------------


def statement(c: Chain) -> str:
    """What the platform attests for a chain: fixed before its salt could be known."""
    committed = c.committed_at.isoformat() if c.committed_at else ""
    return "\n".join(
        [
            "LRCHAIN1",
            c.chain_id,
            c.stream,
            str(c.length),
            c.terminal_hash,
            "LR-CRASH-1",
            c.drand_chain_hash or "",
            str(c.drand_round or ""),
            committed,
        ]
    )


def public_view(c: Chain) -> dict[str, Any]:
    """Non-secret chain facts, with the platform's Ed25519 signature over the commitment."""
    out: dict[str, Any] = {
        k: v
        for k, v in asdict(c).items()
        if k not in ("committed_at", "activated_at", "retired_at", "created_at", "salt")
    }
    out.update(
        {
            "salt": c.salt or None,
            "committed_at": _iso(c.committed_at),
            "activated_at": _iso(c.activated_at),
            "retired_at": _iso(c.retired_at),
            "created_at": _iso(c.created_at),
            "drand_round_time": _iso(round_time(c.drand_round)) if c.drand_round else None,
            "commitment": {
                "statement": statement(c),
                "kid": settings.PLATFORM_SIGNING_KID,
                "signature": b64url(platform_key().sign(statement(c).encode())),
            },
        }
    )
    return out


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None
