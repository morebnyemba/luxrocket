import pytest

from luxrocket.core import multiplier as m


def test_payout_vectors(vectors):
    for v in vectors["payouts"]:
        assert (
            m.payout_minor(v["stake_minor"], v["multiplier_x10000"], v["max_win_minor"])
            == v["payout_minor"]
        )


def test_payout_rounds_toward_house():
    assert m.payout_minor(3, 15_555) == 4  # 4.6665 -> 4


def test_payout_rejects_invalid():
    with pytest.raises(ValueError):
        m.payout_minor(0, 20_000)
    with pytest.raises(ValueError):
        m.payout_minor(100, 9_999)


def test_effective_target_caps_by_max_win():
    # stake 10.00, max win 100.00 => forced cash-out at 10.00x
    assert m.effective_target(None, 1_000, 10_000, 100_000_000) == 100_000
    assert m.effective_target(50_000, 1_000, 10_000, 100_000_000) == 50_000
    assert m.effective_target(None, 1, 10**12, 100_000_000) == 100_000_000


def test_display_is_floored():
    assert m.format_display(23_456) == "2.34x"
    assert m.format_display(10_000) == "1.00x"
    assert m.format_display(100_000_000) == "10000.00x"
