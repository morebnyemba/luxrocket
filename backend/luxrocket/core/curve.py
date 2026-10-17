"""Tabulated multiplier curve (doc 07 §3).

curve[t] = floor(10000 * exp(lambda * t)) for t in ms, computed with high-precision decimal
arithmetic so every implementation can use the identical table (hashed into the ruleset).
"""

import hashlib
import sys
from array import array
from bisect import bisect_left
from decimal import ROUND_FLOOR, Decimal, localcontext
from typing import Final

from luxrocket.core.multiplier import UNIT

DEFAULT_LAMBDA_PER_MS: Final = "0.00006"
PRECISION: Final = 60


def generate_table(lambda_per_ms: str, max_multiplier_x10000: int) -> array[int]:
    """Values from t = 0 up to and including the first t with curve[t] >= M."""
    lam = Decimal(lambda_per_ms)
    table: array[int] = array("i")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        t = 0
        while True:
            value = int((Decimal(UNIT) * (lam * t).exp()).to_integral_value(rounding=ROUND_FLOOR))
            table.append(value)
            if value >= max_multiplier_x10000:
                return table
            t += 1


def table_bytes(table: array[int]) -> bytes:
    """Canonical serialisation: little-endian int32."""
    out = array("i", table)
    if out.itemsize != 4:
        raise RuntimeError("platform int is not 32-bit")
    if sys.byteorder != "little":
        out.byteswap()
    return out.tobytes()


def table_hash(table: array[int]) -> str:
    return hashlib.sha256(table_bytes(table)).hexdigest()


def crash_time_ms(table: array[int], crash_x10000: int) -> int:
    """Smallest t with curve[t] >= crash point."""
    t = bisect_left(table, crash_x10000)
    if t >= len(table):
        raise ValueError("crash point beyond table")
    return t


def target_time_ms(table: array[int], target_x10000: int) -> int:
    """Time at which an auto cash-out target is crossed (same rule as the crash)."""
    return crash_time_ms(table, target_x10000)


def manual_cashout_multiplier(table: array[int], elapsed_ms: int, crash_x10000: int) -> int | None:
    """Multiplier paid for a manual cash-out at elapsed_ms after launch; None if too late."""
    if elapsed_ms < 0:
        raise ValueError("elapsed_ms must be >= 0")
    if elapsed_ms >= crash_time_ms(table, crash_x10000):
        return None
    return table[elapsed_ms]
