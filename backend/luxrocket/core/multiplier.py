"""Multiplier units and payout arithmetic (ADR-008, doc 07).

All multipliers are integers in ten-thousandths: 10_000 == 1.00x.
Crash points and auto cash-out targets lie on the 0.01x grid (multiples of GRID).
Manual cash-outs are priced at full 0.0001x precision.
"""

from typing import Final

UNIT: Final = 10_000
"""Multiplier value representing 1.00x."""

GRID: Final = 100
"""0.01x expressed in multiplier units; crash points and auto targets are multiples of this."""

MIN_AUTO_CASHOUT: Final = 10_100
"""1.01x — the lowest permitted auto cash-out target."""


def is_on_grid(multiplier_x10000: int) -> bool:
    return multiplier_x10000 % GRID == 0


def payout_minor(stake_minor: int, multiplier_x10000: int, max_win_minor: int | None = None) -> int:
    """Payout in minor units: floor(stake * multiplier / UNIT), capped by max win.

    Rounding is always toward the house by less than one minor unit (disclosed in rules).
    """
    if stake_minor <= 0:
        raise ValueError("stake_minor must be positive")
    if multiplier_x10000 < UNIT:
        raise ValueError("multiplier must be >= 1.00x")
    payout = (stake_minor * multiplier_x10000) // UNIT
    if max_win_minor is not None:
        payout = min(payout, max_win_minor)
    return payout


def effective_target(
    auto_cashout_x10000: int | None,
    stake_minor: int,
    max_win_minor: int,
    max_multiplier_x10000: int,
) -> int:
    """Effective auto cash-out target k_eff (doc 07 §4).

    min(auto target, multiplier at which the max win is reached, max multiplier). Forcing a
    cash-out at the max-win multiplier caps exposure without touching the round or the RTP.
    """
    cap_by_win = (max_win_minor * UNIT) // stake_minor
    candidates = [cap_by_win, max_multiplier_x10000]
    if auto_cashout_x10000 is not None:
        candidates.append(auto_cashout_x10000)
    return max(UNIT, min(candidates))


def format_display(multiplier_x10000: int) -> str:
    """Two-decimal display string, floored (never shows more than the true value)."""
    hundredths = multiplier_x10000 // GRID
    return f"{hundredths // 100}.{hundredths % 100:02d}x"
