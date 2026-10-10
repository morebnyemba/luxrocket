import itertools

from hypothesis import given
from hypothesis import strategies as st

from luxrocket.core import curve


def test_table_matches_committed_hash(default_table, vectors):
    p = vectors["params"]
    assert len(default_table) == p["curve_length"]
    assert curve.table_hash(default_table) == p["curve_table_sha256"]


def test_samples_and_crash_times(default_table, vectors):
    for s in vectors["curve_samples"]:
        assert default_table[s["t_ms"]] == s["multiplier_x10000"]
    for c in vectors["crash_times"]:
        assert curve.crash_time_ms(default_table, c["crash_x10000"]) == c["t_crash_ms"]


def test_table_is_non_decreasing(default_table):
    assert default_table[0] == 10_000
    assert all(a <= b for a, b in itertools.pairwise(default_table))


@given(
    crash_hundredths=st.integers(min_value=100, max_value=1_000_000),
    elapsed=st.integers(0, 160_000),
)
def test_manual_cashout_never_reaches_crash(default_table, crash_hundredths, elapsed):
    crash = crash_hundredths * 100
    paid = curve.manual_cashout_multiplier(default_table, elapsed, crash)
    if paid is not None:
        assert paid < crash
        assert elapsed < curve.crash_time_ms(default_table, crash)


def test_instant_crash_allows_no_cashout(default_table):
    assert curve.crash_time_ms(default_table, 10_000) == 0
    assert curve.manual_cashout_multiplier(default_table, 0, 10_000) is None
