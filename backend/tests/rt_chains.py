"""Phoenix-owned seed-chain rows for platform tests (the Django test database has no rt schema)."""

import hashlib
import os
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

from luxrocket.gaming import fairness

DDL = """
CREATE SCHEMA IF NOT EXISTS rt;
CREATE TABLE IF NOT EXISTS rt.seed_chain (
    chain_id uuid PRIMARY KEY, stream_id text NOT NULL, length bigint NOT NULL,
    terminal_hash text NOT NULL, salt text NOT NULL, salt_source text NOT NULL,
    root_seed_ct bytea NOT NULL, checkpoint_every integer NOT NULL, status text NOT NULL,
    inserted_at timestamptz NOT NULL, drand_chain_hash text, drand_round bigint,
    drand_signature text, committed_at timestamptz, activated_at timestamptz,
    retired_at timestamptz);
CREATE TABLE IF NOT EXISTS rt.round (chain_id uuid, chain_index bigint);
"""


def ensure_rt() -> None:
    with connection.cursor() as cur:
        cur.execute(DDL)


def past_round(ago: timedelta = timedelta(hours=1)) -> int:
    """A drand round already published `ago`."""
    t = (timezone.now() - ago).timestamp()
    return int((t - settings.DRAND_GENESIS_TIME) // settings.DRAND_PERIOD_S) + 1


def beacon(round_: int) -> dict[str, object]:
    sig = os.urandom(96)
    return {"round": round_, "randomness": hashlib.sha256(sig).hexdigest(), "signature": sig.hex()}


def insert_chain(
    stream: str = "global",
    status: str = "COMMITTED",
    drand_round: int | None = None,
    committed_at: datetime | None = None,
    salt: str = "",
    salt_source: str = "drand-pending",
    chain_hash: str | None = None,
) -> str:
    ensure_rt()
    chain_id = str(uuid.uuid4())
    drand_round = drand_round if drand_round is not None else past_round()
    if committed_at is None:
        committed_at = fairness.round_time(drand_round) - timedelta(days=2)
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rt.seed_chain (chain_id, stream_id, length, terminal_hash, salt,
              salt_source, root_seed_ct, checkpoint_every, status, inserted_at, drand_chain_hash,
              drand_round, committed_at)
            VALUES (%s, %s, 1000, %s, %s, %s, '\\x00', 100, %s, now(), %s, %s, %s)
            """,
            [
                chain_id,
                stream,
                os.urandom(32).hex(),
                salt,
                salt_source,
                status,
                chain_hash or settings.DRAND_CHAIN_HASH,
                drand_round,
                committed_at,
            ],
        )
    return chain_id


def active_drand_chain(stream: str = "global") -> str:
    r = past_round(timedelta(days=3))
    return insert_chain(
        stream,
        status="ACTIVE",
        drand_round=r,
        salt=os.urandom(32).hex(),
        salt_source=f"drand:{settings.DRAND_CHAIN_HASH}:{r}",
    )
