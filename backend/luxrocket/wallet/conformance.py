"""Conformance suite for an operator's Seamless Wallet v1 endpoints (doc 09 §2, §6.5).

Runs real, signed calls with fresh transaction ids against a test player and checks the
semantics our money path depends on. An operator must pass every REQUIRED check before any
real-money session can be routed to their wallet.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from luxrocket.core import contracts
from luxrocket.core.ids import uuid7
from luxrocket.core.lr1 import platform_sign_headers
from luxrocket.wallet.seamless import RESPONSE_SCHEMA, SeamlessClient, tx_ref


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    required: bool = True


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.required)

    def as_text(self) -> str:
        lines = []
        for c in self.checks:
            mark = "PASS" if c.passed else ("FAIL" if c.required else "WARN")
            lines.append(f"[{mark}] {c.name}" + (f" — {c.detail}" if c.detail else ""))
        lines.append("RESULT: " + ("CONFORMANT" if self.passed else "NOT CONFORMANT"))
        return "\n".join(lines)


class _Probe:
    def __init__(self, client: SeamlessClient, player_id: str, currency: str, timeout_ms: int):
        self.client = client
        self.player_id = player_id
        self.currency = currency
        self.timeout_ms = timeout_ms
        self.round_ref = str(uuid7())

    def call(self, op: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
        resp = self.client._post(op, payload, self.timeout_ms)
        try:
            doc = json.loads(resp.content)
        except ValueError:
            doc = None
        if not isinstance(doc, dict) or contracts.errors(RESPONSE_SCHEMA, doc):
            doc = None
        return resp.status_code, doc

    def base(self, amount: int) -> dict[str, Any]:
        return {
            "transaction_id": tx_ref(uuid7()),
            "bet_id": f"bet_conformance_{uuid.uuid4().hex[:12]}",
            "round_id": self.round_ref,
            "player_id": self.player_id,
            "currency": self.currency,
            "amount": str(amount),
        }

    def debit(self, amount: int, tx_id: str | None = None) -> dict[str, Any]:
        p = self.base(amount) | {
            "game": "lux-rocket",
            "panel": 0,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if tx_id:
            p["transaction_id"] = tx_id
        return p

    def credit(self, debit: dict[str, Any], amount: int) -> dict[str, Any]:
        return self.base(amount) | {
            "bet_id": debit["bet_id"],
            "debit_transaction_id": debit["transaction_id"],
            "type": "WIN",
            "multiplier_x10000": 20_000,
            "created_at": datetime.now(UTC).isoformat(),
        }

    def rollback(self, debit: dict[str, Any], reason: str = "DEBIT_UNCERTAIN") -> dict[str, Any]:
        return self.base(int(debit["amount"])) | {
            "bet_id": debit["bet_id"],
            "rolled_back_transaction_id": debit["transaction_id"],
            "reason": reason,
        }


def _ok(res: tuple[int, dict[str, Any] | None], tx_id: str) -> bool:
    status, doc = res
    return (
        status == 200
        and doc is not None
        and doc["status"] == "OK"
        and doc["transaction_id"] == tx_id
    )


def _bal(res: tuple[int, dict[str, Any] | None]) -> int | None:
    doc = res[1]
    return int(doc["balance"]) if doc and "balance" in doc else None


def run(
    base_url: str,
    *,
    player_id: str,
    currency: str,
    stake: int = 100,
    timeout_ms: int = 5000,
) -> Report:
    client = SeamlessClient(base_url)
    probe = _Probe(client, player_id, currency, timeout_ms)
    report = Report()

    def check(name: str, required: bool = True) -> Callable[[Callable[[], str | None]], None]:
        def wrap(fn: Callable[[], str | None]) -> None:
            try:
                problem = fn()
            except Exception as exc:  # transport errors are failures of this check
                problem = f"{type(exc).__name__}: {exc}"
            report.checks.append(Check(name, problem is None, problem or "", required))

        return wrap

    @check("debit succeeds and reports a balance")
    def _debit() -> str | None:
        d = probe.debit(stake)
        res = probe.call("debit", d)
        if not _ok(res, d["transaction_id"]):
            return f"expected 200 OK echoing transaction_id, got {res}"
        return None if _bal(res) is not None else "no balance in response"

    @check("debit replay is idempotent (same result, no second charge)")
    def _debit_replay() -> str | None:
        d = probe.debit(stake)
        first = probe.call("debit", d)
        again = probe.call("debit", d)
        if not (_ok(first, d["transaction_id"]) and _ok(again, d["transaction_id"])):
            return f"replay not OK: {again}"
        if (b1 := _bal(first)) is not None and (b2 := _bal(again)) is not None and b1 != b2:
            return f"balance moved on replay ({b1} -> {b2})"
        return None

    @check("replays are flagged duplicate=true", required=False)
    def _dup_flag() -> str | None:
        d = probe.debit(stake)
        probe.call("debit", d)
        again = probe.call("debit", d)
        return None if again[1] and again[1].get("duplicate") is True else "duplicate flag missing"

    @check("credit succeeds and is idempotent")
    def _credit() -> str | None:
        d = probe.debit(stake)
        probe.call("debit", d)
        c = probe.credit(d, stake * 2)
        first = probe.call("credit", c)
        again = probe.call("credit", c)
        if not (_ok(first, c["transaction_id"]) and _ok(again, c["transaction_id"])):
            return f"credit not OK: {first} / {again}"
        if (b1 := _bal(first)) is not None and (b2 := _bal(again)) is not None and b1 != b2:
            return f"balance moved on credit replay ({b1} -> {b2})"
        return None

    @check("rollback refunds a debit exactly once")
    def _rollback() -> str | None:
        d = probe.debit(stake)
        before = probe.call("debit", d)
        rb = probe.rollback(d)
        first = probe.call("rollback", rb)
        again = probe.call("rollback", rb)
        if not (_ok(first, rb["transaction_id"]) and _ok(again, rb["transaction_id"])):
            return f"rollback not OK: {first} / {again}"
        b0, b1, b2 = _bal(before), _bal(first), _bal(again)
        if None not in (b0, b1) and b1 != b0 + stake:  # type: ignore[operator]
            return f"refund wrong: {b0} -> {b1}, expected +{stake}"
        if None not in (b1, b2) and b1 != b2:
            return f"refunded twice ({b1} -> {b2})"
        return None

    @check("rollback of an unknown debit succeeds and blocks that debit forever")
    def _tombstone() -> str | None:
        d = probe.debit(stake)
        rb = probe.rollback(d)
        res = probe.call("rollback", rb)
        if not _ok(res, rb["transaction_id"]):
            return f"rollback of unknown debit not OK: {res}"
        late = probe.call("debit", d)
        status, doc = late
        if status == 200 and doc is not None and doc["status"] == "REJECTED":
            return None
        return f"late debit after rollback was not rejected: {late}"

    @check("insufficient funds is a 200 REJECTED with INSUFFICIENT_FUNDS")
    def _nsf() -> str | None:
        d = probe.debit(10**17)
        status, doc = probe.call("debit", d)
        if status == 200 and doc and doc["status"] == "REJECTED":
            return None if doc.get("code") == "INSUFFICIENT_FUNDS" else f"code {doc.get('code')}"
        return f"expected REJECTED, got {status} {doc}"

    @check("unsigned or badly signed requests are refused")
    def _bad_sig() -> str | None:
        d = probe.debit(stake)
        body = json.dumps(d).encode()
        url = f"{client.base_url}/debit"
        headers = platform_sign_headers("POST", "/tampered", body)
        resp = client.http.post(url, content=body, headers=headers, timeout=timeout_ms / 1000)
        if resp.status_code == 200:
            return "accepted a request with an invalid signature"
        return None

    @check("balance endpoint answers (optional)", required=False)
    def _balance() -> str | None:
        value = client.balance({"player_id": player_id, "currency": currency}, timeout_ms)
        return None if value is not None else "no valid balance response"

    @check("transaction lookup reports applied, rejected and voided ids (optional)", required=False)
    def _lookup() -> str | None:
        ok = probe.debit(stake)
        probe.call("debit", ok)
        nsf = probe.debit(10**17)
        probe.call("debit", nsf)
        voided = probe.debit(stake)
        probe.call("rollback", probe.rollback(voided))
        ids = [ok["transaction_id"], nsf["transaction_id"], voided["transaction_id"]]
        found = client.lookup(ids, timeout_ms)
        if found is None:
            return "no valid lookup response (operator reconciliation will be unavailable)"
        got = [found.get(i, {}).get("status") for i in ids]
        want = ["OK", "REJECTED", "VOIDED"]
        return None if got == want else f"expected {want}, got {got}"

    return report
