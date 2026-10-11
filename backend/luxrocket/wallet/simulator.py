"""Reference operator wallet for LUX Seamless Wallet v1 (doc 09 §2, §6).

A standalone, Django-free server that implements the operator side of the contract exactly as
we require it of real operators, with fault injection for integration testing:

    python -m luxrocket.wallet.simulator --port 8090 \\
        --keys-url http://localhost:8000/.well-known/luxrocket-keys.json \\
        --lose-rate 0.05 --fail-rate 0.05 --latency-ms 50

Operators can read it as executable documentation of §6.5: idempotency by transaction id
(replays answer the original result with duplicate=true), rollback of an unknown debit
tombstones the id, credits and rollbacks never fail for a known player. Only needs
`cryptography` besides the standard library.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import random
import sqlite3
import threading
import time
import urllib.request
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

log = logging.getLogger("wallet-sim")

MAX_SKEW_SECONDS = 300
NONCE_WINDOW_SECONDS = 600


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def fetch_platform_keys(url: str) -> dict[str, Ed25519PublicKey]:
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 (operator-supplied URL)
        doc = json.load(resp)
    return {
        k["kid"]: Ed25519PublicKey.from_public_bytes(_b64url_decode(k["public_key"]))
        for k in doc["keys"]
        if k.get("alg") == "Ed25519"
    }


class Faults:
    def __init__(
        self,
        *,
        latency_ms: int = 0,
        fail_rate: float = 0.0,
        lose_rate: float = 0.0,
        seed: int | None = None,
    ) -> None:
        self.latency_ms = latency_ms
        self.fail_rate = fail_rate  # 500 before applying anything
        self.lose_rate = lose_rate  # apply, then answer 500 (the "lost response" case)
        self.rng = random.Random(seed)  # noqa: S311 (test fault injection, not security)
        self.lock = threading.Lock()

    def roll(self, rate: float) -> bool:
        with self.lock:
            return rate > 0 and self.rng.random() < rate


class Ledger:
    """The operator's wallet: balances and an idempotency record per transaction id."""

    def __init__(self, path: str = ":memory:", opening_balance: int = 100_000) -> None:
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.lock = threading.Lock()
        self.opening_balance = opening_balance
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS account (
              player_id TEXT, currency TEXT, balance INTEGER NOT NULL CHECK (balance >= 0),
              PRIMARY KEY (player_id, currency));
            CREATE TABLE IF NOT EXISTS webhook_event (
              event_id TEXT PRIMARY KEY, type TEXT, body TEXT, received INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS tx (
              transaction_id TEXT PRIMARY KEY, kind TEXT, player_id TEXT, currency TEXT,
              amount INTEGER, response TEXT, tombstone INTEGER DEFAULT 0);
            """
        )

    def _balance(self, player: str, ccy: str) -> int:
        row = self.db.execute(
            "SELECT balance FROM account WHERE player_id=? AND currency=?", (player, ccy)
        ).fetchone()
        if row is None:
            self.db.execute(
                "INSERT INTO account VALUES (?,?,?)", (player, ccy, self.opening_balance)
            )
            return self.opening_balance
        return int(row[0])

    def _move(self, player: str, ccy: str, delta: int) -> int:
        self.db.execute(
            "UPDATE account SET balance = balance + ? WHERE player_id=? AND currency=?",
            (delta, player, ccy),
        )
        return self._balance(player, ccy)

    def record_event(self, event: dict[str, Any]) -> bool:
        """Webhook consumer: dedupe by event_id (delivery is at-least-once). True if new."""
        with self.lock:
            self.db.execute(
                "INSERT INTO webhook_event (event_id, type, body) VALUES (?,?,?) "
                "ON CONFLICT(event_id) DO UPDATE SET received = received + 1",
                (event["event_id"], event["type"], json.dumps(event)),
            )
            row = self.db.execute(
                "SELECT received FROM webhook_event WHERE event_id=?", (event["event_id"],)
            ).fetchone()
            return bool(row and row[0] == 1)

    def lookup(self, tx_ids: list[str]) -> list[dict[str, Any]]:
        """Our record of each id (reconciliation endpoint)."""
        out = []
        with self.lock:
            for tx_id in tx_ids:
                row = self.db.execute(
                    "SELECT amount, currency, response, tombstone FROM tx WHERE transaction_id=?",
                    (tx_id,),
                ).fetchone()
                if row is None:
                    out.append({"transaction_id": tx_id, "status": "NOT_FOUND"})
                elif row[3]:
                    out.append({"transaction_id": tx_id, "status": "VOIDED"})
                else:
                    status = json.loads(row[2]).get("status", "REJECTED")
                    out.append(
                        {
                            "transaction_id": tx_id,
                            "status": status,
                            "amount": str(row[0]),
                            "currency": row[1],
                        }
                    )
        return out

    def events(self, type_: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT body FROM webhook_event WHERE ?1 IS NULL OR type = ?1 ORDER BY rowid",
                (type_,),
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def balance(self, player: str, ccy: str) -> int:
        with self.lock:
            return self._balance(player, ccy)

    def apply(self, op: str, req: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                out = self._apply(op, req)
                self.db.execute("COMMIT")
                return out
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def _apply(self, op: str, req: dict[str, Any]) -> dict[str, Any]:
        tx_id, player, ccy = req["transaction_id"], req["player_id"], req["currency"]
        amount = int(req["amount"])
        prior = self.db.execute(
            "SELECT response, tombstone FROM tx WHERE transaction_id=?", (tx_id,)
        ).fetchone()
        if prior is not None:
            if prior[1]:  # a rollback arrived first: this debit must never apply
                return self._reply(tx_id, ccy, "REJECTED", "DUPLICATE_TRANSACTION", player)
            original: dict[str, Any] = json.loads(prior[0])
            return original | {"duplicate": True}

        balance = self._balance(player, ccy)
        if op == "debit":
            if balance < amount:
                out = self._reply(tx_id, ccy, "REJECTED", "INSUFFICIENT_FUNDS", player)
            else:
                self._move(player, ccy, -amount)
                out = self._reply(tx_id, ccy, "OK", None, player)
        elif op == "credit":
            self._move(player, ccy, amount)
            out = self._reply(tx_id, ccy, "OK", None, player)
        else:  # rollback
            debit_id = req["rolled_back_transaction_id"]
            debit = self.db.execute(
                "SELECT amount, response FROM tx WHERE transaction_id=? AND kind='debit'",
                (debit_id,),
            ).fetchone()
            if debit is None:
                self.db.execute(
                    "INSERT INTO tx VALUES (?,?,?,?,?,?,1)",
                    (debit_id, "debit", player, ccy, 0, "{}"),
                )
            elif json.loads(debit[1]).get("status") == "OK":
                self._move(player, ccy, int(debit[0]))
            out = self._reply(tx_id, ccy, "OK", None, player)
        self.db.execute(
            "INSERT INTO tx VALUES (?,?,?,?,?,?,0)",
            (tx_id, op, player, ccy, amount, json.dumps(out)),
        )
        return out

    def _reply(
        self, tx_id: str, ccy: str, status: str, code: str | None, player: str
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "status": status,
            "transaction_id": tx_id,
            "operator_transaction_id": "op-" + hashlib.sha256(tx_id.encode()).hexdigest()[:16],
            "balance": str(self._balance(player, ccy)),
            "currency": ccy,
        }
        if code:
            out["code"] = code
        return out


class Verifier:
    def __init__(self, keys: dict[str, Ed25519PublicKey]) -> None:
        self.keys = keys
        self.seen: OrderedDict[tuple[str, str], float] = OrderedDict()
        self.lock = threading.Lock()

    def verify(self, method: str, path: str, headers: Any, body: bytes) -> bool:
        kid = headers.get("LR-Key-Id", "")
        ts = headers.get("LR-Timestamp", "")
        nonce = headers.get("LR-Nonce", "")
        scheme, _, sig = headers.get("LR-Signature", "").partition("=")
        key = self.keys.get(kid)
        if key is None or scheme != "ed25519" or not (ts.isdigit() and nonce and sig):
            return False
        now = time.time()
        if abs(now - int(ts)) > MAX_SKEW_SECONDS:
            return False
        digest = hashlib.sha256(body).hexdigest()
        msg = f"LR1\n{method}\n{path}\n{ts}\n{nonce}\n{digest}".encode()
        try:
            key.verify(_b64url_decode(sig), msg)
        except (InvalidSignature, ValueError):
            return False
        with self.lock:
            while self.seen and next(iter(self.seen.values())) < now - NONCE_WINDOW_SECONDS:
                self.seen.popitem(last=False)
            if (kid, nonce) in self.seen:
                return False
            self.seen[(kid, nonce)] = now
        return True


OPS = {"debit", "credit", "rollback", "balance", "webhooks", "transactions/lookup"}


def make_handler(ledger: Ledger, verifier: Verifier, faults: Faults, prefix: str) -> type:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        disable_nagle_algorithm = True  # headers and body go out in separate writes

        def log_message(self, fmt: str, *args: Any) -> None:
            log.debug(fmt, *args)

        def _send(self, status: int, doc: dict[str, Any]) -> None:
            body = json.dumps(doc).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            op = self.path.removeprefix(prefix).strip("/")
            if not self.path.startswith(prefix) or op not in OPS:
                self._send(404, {"error": "not found"})
                return
            if not verifier.verify("POST", self.path, self.headers, body):
                self._send(401, {"error": "bad signature"})
                return
            if faults.latency_ms:
                time.sleep(faults.latency_ms / 1000)
            if faults.roll(faults.fail_rate):
                self._send(500, {"error": "injected failure"})
                return
            try:
                req = json.loads(body)
            except ValueError:
                self._send(400, {"error": "bad json"})
                return
            if op == "transactions/lookup":
                self._send(200, {"transactions": ledger.lookup(req["transaction_ids"])})
                return
            if op == "webhooks":
                new = ledger.record_event(req)
                log.info(
                    "webhook %s %s%s",
                    req.get("type"),
                    req.get("event_id"),
                    "" if new else " (duplicate)",
                )
                self._send(200, {"received": True})
                return
            if op == "balance":
                bal = ledger.balance(req["player_id"], req["currency"])
                self._send(200, {"status": "OK", "balance": str(bal), "currency": req["currency"]})
                return
            out = ledger.apply(op, req)
            if faults.roll(faults.lose_rate):
                self._send(500, {"error": "injected lost response"})
                return
            self._send(200, out)

    return Handler


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    keys: dict[str, Ed25519PublicKey],
    prefix: str = "",
    ledger: Ledger | None = None,
    faults: Faults | None = None,
) -> ThreadingHTTPServer:
    """Build the server (call serve_forever, or run it in a thread in tests)."""
    handler = make_handler(ledger or Ledger(), Verifier(keys), faults or Faults(), prefix)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--prefix", default="", help="path prefix, e.g. /wallet")
    ap.add_argument("--keys-url", help="platform /.well-known/luxrocket-keys.json")
    ap.add_argument("--platform-key", help="kid=base64url public key (repeatable)", action="append")
    ap.add_argument("--db", default=":memory:")
    ap.add_argument("--opening-balance", type=int, default=100_000)
    ap.add_argument("--latency-ms", type=int, default=0)
    ap.add_argument("--fail-rate", type=float, default=0.0)
    ap.add_argument("--lose-rate", type=float, default=0.0)
    ap.add_argument("--seed", type=int)
    args = ap.parse_args()

    keys: dict[str, Ed25519PublicKey] = {}
    if args.keys_url:
        for attempt in range(30):  # the platform may still be starting
            try:
                keys |= fetch_platform_keys(args.keys_url)
                break
            except OSError:
                time.sleep(min(2**attempt, 5))
    for item in args.platform_key or []:
        kid, _, b64 = item.partition("=")
        keys[kid] = Ed25519PublicKey.from_public_bytes(_b64url_decode(b64))
    if not keys:
        raise SystemExit("no platform keys: pass --keys-url or --platform-key")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = serve(
        host=args.host,
        port=args.port,
        keys=keys,
        prefix=args.prefix.rstrip("/"),
        ledger=Ledger(args.db, args.opening_balance),
        faults=Faults(
            latency_ms=args.latency_ms,
            fail_rate=args.fail_rate,
            lose_rate=args.lose_rate,
            seed=args.seed,
        ),
    )
    log.info("wallet simulator on %s:%s (kids: %s)", args.host, args.port, ", ".join(keys))
    server.serve_forever()


if __name__ == "__main__":
    main()
