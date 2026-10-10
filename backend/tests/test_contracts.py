import json

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from tests.conftest import CONTRACTS

SCHEMAS = sorted(CONTRACTS.rglob("*.schema.json"))


def load(rel: str) -> dict:
    return json.loads((CONTRACTS / rel).read_text())


@pytest.mark.parametrize("path", SCHEMAS, ids=lambda p: str(p.relative_to(CONTRACTS)))
def test_schema_is_valid(path):
    Draft202012Validator.check_schema(json.loads(path.read_text()))


def test_place_bet_accepts_valid_and_rejects_off_grid_target():
    v = Draft202012Validator(load("ws/v1/place-bet.schema.json"))
    good = {
        "type": "PLACE_BET",
        "v": 1,
        "command_id": "0192f5c2-0000-7000-8000-000000000000",
        "round_id": "rnd_1",
        "data": {"panel": 0, "stake": "500", "auto_cashout_x10000": 20_000},
    }
    v.validate(good)
    bad = json.loads(json.dumps(good))
    bad["data"]["auto_cashout_x10000"] = 20_050
    with pytest.raises(ValidationError):
        v.validate(bad)


def test_snapshot_forbids_crash_point_before_crash():
    v = Draft202012Validator(load("ws/v1/round-snapshot.schema.json"))
    flying = {
        "stream_id": "s",
        "seq": 1,
        "server_ts": 1,
        "round": {"round_id": "r", "number": 1, "state": "FLYING", "crash_x10000": 20_000},
    }
    with pytest.raises(ValidationError):
        v.validate(flying)
    crashed = json.loads(json.dumps(flying))
    crashed["round"]["state"] = "CRASHED"
    v.validate(crashed)


def test_wallet_rejection_requires_code():
    v = Draft202012Validator(load("wallet/v1/response.schema.json"))
    with pytest.raises(ValidationError):
        v.validate({"status": "REJECTED", "transaction_id": "tx_1"})
    v.validate({"status": "REJECTED", "transaction_id": "tx_1", "code": "INSUFFICIENT_FUNDS"})
