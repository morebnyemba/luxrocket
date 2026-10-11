"""Builds Phoenix round facts (the rt.events contract) for tests."""

import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field

from luxrocket.core import outcome

EDGE = 300
MAX = 100_000_000


@dataclass
class RoundSim:
    stream: str = "global"
    seq: int = 0
    round_id: uuid.UUID = field(default_factory=uuid.uuid4)
    number: int = 1
    seed: bytes = field(default_factory=lambda: os.urandom(32))
    salt: bytes = field(default_factory=lambda: os.urandom(32))

    @property
    def crash(self) -> int:
        return outcome.crash_from_seed(self.seed, self.salt, EDGE, MAX)

    def _ev(self, type_: str, payload: dict) -> dict:
        self.seq += 1
        return {
            "event_id": str(uuid.uuid4()),
            "stream_id": self.stream,
            "stream_seq": self.seq,
            "round_id": str(self.round_id),
            "type": type_,
            "payload": payload,
        }

    def created(self, **ruleset: object) -> dict:
        """ROUND_CREATED; pass ruleset_code/ruleset_version (or other overrides) to vary it."""
        return self._ev(
            "ROUND_CREATED",
            {
                "number": self.number,
                "commitment": hashlib.sha256(self.seed).hexdigest(),
                "house_edge_bp": EDGE,
                "max_multiplier_x10000": MAX,
                **ruleset,
            },
        )

    def opened(self) -> dict:
        now = int(time.time() * 1000)
        return self._ev(
            "ROUND_OPENED", {"opens_at": now, "close_at": now + 7000, "launch_at": now + 8000}
        )

    def launched(self) -> dict:
        return self._ev("ROUND_LAUNCHED", {"launch_at": int(time.time() * 1000)})

    def admitted(self, bet_id: str) -> dict:
        return self._ev("BET_ADMITTED", {"bet_id": bet_id})

    def excluded(self, session_id: str, command_id: str, reason: str = "LATE") -> dict:
        return self._ev(
            "BET_EXCLUDED", {"session_id": session_id, "command_id": command_id, "reason": reason}
        )

    def cashout(self, bet_id: str, mult: int, payout: int, trigger: str = "MANUAL") -> dict:
        return self._ev(
            "CASHOUT_ACCEPTED",
            {"bet_id": bet_id, "cashout_x10000": mult, "payout_minor": payout, "trigger": trigger},
        )

    def crashed(self, crash: int | None = None) -> dict:
        return self._ev(
            "ROUND_CRASHED",
            {
                "crash_x10000": self.crash if crash is None else crash,
                "end_reason": "CRASH",
                "seed": self.seed.hex(),
                "salt": self.salt.hex(),
            },
        )

    def voided(self) -> dict:
        return self._ev("ROUND_VOIDED", {"reason": "COORDINATOR_FAILOVER", "seed": self.seed.hex()})

    @classmethod
    def with_min_crash(cls, min_crash: int) -> "RoundSim":
        """A round whose crash point is at least min_crash (so cash-outs below it are valid)."""
        while True:
            sim = cls()
            if sim.crash >= min_crash:
                return sim

    def deadline_ms(self) -> int:
        return int(time.time() * 1000) + 5000
