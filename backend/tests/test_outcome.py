import itertools
from fractions import Fraction

from hypothesis import given
from hypothesis import strategies as st

from luxrocket.core import outcome
from luxrocket.core.multiplier import GRID

EDGE = 300
M = 100_000_000
D = outcome.D


def test_known_answer_r_vectors(vectors):
    for v in vectors["r_vectors"]:
        assert outcome.crash_from_r(int(v["r"]), EDGE, M) == v["crash_x10000"]


def test_known_answer_seed_vectors(vectors):
    salt = bytes.fromhex(vectors["salt"])
    for v in vectors["seed_vectors"]:
        seed = bytes.fromhex(v["seed"])
        assert outcome.round_hash(seed, salt).hex() == v["round_hash"]
        assert outcome.first_52_bits(bytes.fromhex(v["round_hash"])) == int(v["r"])
        assert outcome.crash_from_seed(seed, salt, EDGE, M) == v["crash_x10000"]


def test_chain_commitments(vectors):
    chain = [bytes.fromhex(s) for s in vectors["chain"]]
    # Rounds consume the chain in reverse: the seed revealed for a round hashes to its commitment.
    for earlier, later in itertools.pairwise(chain):
        assert outcome.verify_commitment(earlier, later)
    assert not outcome.verify_commitment(chain[0], chain[2])


@given(st.integers(min_value=0, max_value=D - 2))
def test_monotone_in_r(r):
    assert outcome.crash_from_r(r, EDGE, M) <= outcome.crash_from_r(r + 1, EDGE, M)


@given(st.integers(min_value=0, max_value=D - 1))
def test_on_grid_and_bounded(r):
    c = outcome.crash_from_r(r, EDGE, M)
    assert c % GRID == 0
    assert 10_000 <= c <= M


def _exact_tail_probability(k_hundredths: int) -> Fraction:
    """P(raw >= k) by counting admissible r exactly."""
    num = 100 * (10_000 - EDGE) * D
    threshold = D - num // (10_000 * k_hundredths)
    return Fraction(D - threshold, D)


def test_tail_probabilities_match_theory():
    for k in [101, 120, 200, 500, 1_000, 10_000, 100_000, 1_000_000]:
        exact = _exact_tail_probability(k)
        theory = Fraction(100 * (10_000 - EDGE), 10_000 * k)
        assert abs(exact - theory) <= Fraction(1, D)


def test_rtp_is_strategy_invariant_for_fixed_targets():
    """E[return] for any auto target k equals 1 - e (up to 2^-52)."""
    for k in [101, 150, 200, 1_000, 100_000, M // 100]:
        rtp = Fraction(k, 100) * _exact_tail_probability(k)
        assert abs(rtp - Fraction(97, 100)) < Fraction(k, 100) * Fraction(1, D)


def test_instant_crash_probability():
    p_instant = 1 - _exact_tail_probability(101)
    assert abs(float(p_instant) - (1 - 0.97 / 1.01)) < 1e-12
