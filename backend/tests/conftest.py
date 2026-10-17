import json
from array import array
from pathlib import Path

import pytest

from luxrocket.core import curve

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"


@pytest.fixture(scope="session")
def vectors() -> dict:
    return json.loads((CONTRACTS / "math" / "lr-crash-1" / "vectors.json").read_text())


@pytest.fixture(scope="session")
def default_table(vectors: dict) -> array:
    p = vectors["params"]
    return curve.generate_table(p["curve_lambda_per_ms"], p["max_multiplier_x10000"])
