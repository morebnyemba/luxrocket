"""Provably-fair outcome generation, formula LR-CRASH-1 (doc 07 §2, §6).

Pure integer arithmetic. This module is the reference implementation: the Elixir and
TypeScript implementations are tested against vectors generated from it
(contracts/math/lr-crash-1/vectors.json).
"""

import hashlib
import hmac
from typing import Final

from luxrocket.core.multiplier import GRID

FORMULA_VERSION: Final = "LR-CRASH-1"
BITS: Final = 52
D: Final = 1 << BITS


def first_52_bits(digest: bytes) -> int:
    """Integer value of the first 52 bits of a digest (big-endian)."""
    if len(digest) < 7:
        raise ValueError("digest too short")
    return int.from_bytes(digest[:7], "big") >> 4


def crash_from_r(r: int, house_edge_bp: int, max_multiplier_x10000: int) -> int:
    """Crash point in ten-thousandths for a 52-bit uniform integer r.

    raw = floor(100 * (10000 - e_bp) * D / (10000 * (D - r)))   # hundredths
    crash = 100 * clamp(raw, 100, M / 100)                      # on the 0.01x grid
    P(crash >= 100*k) = 100 * (1 - e) / k for 101 <= k <= M/100.
    """
    if not 0 <= r < D:
        raise ValueError("r out of range")
    if not 0 <= house_edge_bp < 10_000:
        raise ValueError("house_edge_bp out of range")
    if max_multiplier_x10000 % GRID != 0 or max_multiplier_x10000 < 101 * GRID:
        raise ValueError("max multiplier must be on the 0.01x grid and >= 1.01x")
    raw = (100 * (10_000 - house_edge_bp) * D) // (10_000 * (D - r))
    raw = max(100, min(raw, max_multiplier_x10000 // GRID))
    return raw * GRID


def round_hash(seed: bytes, salt: bytes) -> bytes:
    return hmac.new(seed, salt, hashlib.sha256).digest()


def crash_from_seed(
    seed: bytes, salt: bytes, house_edge_bp: int, max_multiplier_x10000: int
) -> int:
    return crash_from_r(first_52_bits(round_hash(seed, salt)), house_edge_bp, max_multiplier_x10000)


def chain_next(seed: bytes) -> bytes:
    """s_{i+1} = SHA256(s_i). Rounds consume the chain in reverse order."""
    return hashlib.sha256(seed).digest()


def verify_commitment(revealed_seed: bytes, commitment: bytes) -> bool:
    """A round's commitment is the previous round's revealed seed (or the chain terminal)."""
    return hmac.compare_digest(chain_next(revealed_seed), commitment)
