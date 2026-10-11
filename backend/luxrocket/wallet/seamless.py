"""LUX Seamless Wallet v1 client: we call the operator's wallet (doc 09 §6, ADR-007).

Every call is LR1-signed with the platform key. Outcome classification is deliberately
pessimistic (doc 09 §6.5): only an HTTP 200 whose body validates against the contract and
echoes our transaction id counts as OK or REJECTED. Anything else (timeouts, 5xx, redirects,
unparseable or mismatched bodies) is UNKNOWN, which the callers resolve by retrying credits
and rolling back debits. A wrong OK would lose money; a wrong UNKNOWN only costs a retry.
"""

import json
import logging
import uuid
from functools import cache
from typing import Any
from urllib.parse import urlsplit

import httpx
from django.conf import settings

from luxrocket.core import contracts
from luxrocket.core.ids import deterministic_tx_id, tx_public_id
from luxrocket.core.lr1 import platform_sign_headers
from luxrocket.wallet.adapters import WalletResult

log = logging.getLogger(__name__)

SCHEMAS = {
    "debit": "wallet/v1/debit.request.schema.json",
    "credit": "wallet/v1/credit.request.schema.json",
    "rollback": "wallet/v1/rollback.request.schema.json",
    "balance": "wallet/v1/balance.request.schema.json",
}
RESPONSE_SCHEMA = "wallet/v1/response.schema.json"
BALANCE_RESPONSE_SCHEMA = "wallet/v1/balance.response.schema.json"


class WalletConfigError(ValueError):
    pass


def tx_ref(tx_id: uuid.UUID | str) -> str:
    return tx_public_id(tx_id)


def validate_base_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.netloc:
        raise WalletConfigError("wallet base URL must be an absolute URL")
    if parts.scheme != "https" and not settings.WALLET_ALLOW_HTTP:
        raise WalletConfigError("wallet base URL must use https")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise WalletConfigError("wallet base URL must not carry query, fragment or credentials")
    return url.rstrip("/")


@cache
def _http() -> httpx.Client:
    # One pooled client per process; redirects are never followed (a 3xx is UNKNOWN).
    return httpx.Client(
        follow_redirects=False,
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        headers={"User-Agent": "luxrocket-wallet/1"},
    )


class SeamlessClient:
    def __init__(self, base_url: str, http: httpx.Client | None = None) -> None:
        self.base_url = validate_base_url(base_url)
        self.http = http or _http()

    def _post(self, op: str, payload: dict[str, Any], timeout_ms: int) -> httpx.Response:
        errs = contracts.errors(SCHEMAS[op], payload)
        if errs:  # our bug, never the operator's: refuse to send a non-conforming request
            raise ValueError(f"outbound {op} violates contract: {errs}")
        url = f"{self.base_url}/{op}"
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        headers = {
            "Content-Type": "application/json",
            **platform_sign_headers("POST", urlsplit(url).path, body),
        }
        return self.http.post(url, content=body, headers=headers, timeout=timeout_ms / 1000)

    def call(self, op: str, payload: dict[str, Any], timeout_ms: int) -> WalletResult:
        """debit / credit / rollback. Never raises for transport or operator faults."""
        try:
            resp = self._post(op, payload, timeout_ms)
        except httpx.HTTPError as exc:
            return WalletResult("UNKNOWN", _transport_code(exc))
        return classify(
            resp.status_code, resp.content, payload["transaction_id"], payload["currency"]
        )

    def balance(self, payload: dict[str, Any], timeout_ms: int) -> int | None:
        try:
            resp = self._post("balance", payload, timeout_ms)
        except httpx.HTTPError:
            return None
        doc = _json(resp.content) if resp.status_code == 200 else None
        if doc is None or contracts.errors(BALANCE_RESPONSE_SCHEMA, doc):
            return None
        if doc["currency"] != payload["currency"]:
            return None
        return int(doc["balance"])


def _transport_code(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "TIMEOUT"
    if isinstance(exc, httpx.ConnectError):
        return "CONNECT_ERROR"
    return "TRANSPORT_ERROR"


def _json(content: bytes) -> Any:
    try:
        return json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return None


def classify(status: int, content: bytes, tx_id: str, currency: str) -> WalletResult:
    if status != 200:
        return WalletResult("UNKNOWN", f"HTTP_{status}")
    doc = _json(content)
    if not isinstance(doc, dict) or contracts.errors(RESPONSE_SCHEMA, doc):
        return WalletResult("UNKNOWN", "BAD_RESPONSE")
    if doc["transaction_id"] != tx_id:
        log.error("wallet answered for %s while we asked about %s", doc["transaction_id"], tx_id)
        return WalletResult("UNKNOWN", "TX_MISMATCH")
    if doc.get("currency", currency) != currency:
        return WalletResult("UNKNOWN", "CURRENCY_MISMATCH")
    balance = int(doc["balance"]) if "balance" in doc else None
    if doc["status"] == "OK":
        return WalletResult("OK", balance_minor=balance)
    return WalletResult("REJECTED", doc["code"], balance)


class SeamlessWalletAdapter:
    """WalletAdapter over the operator's Seamless Wallet v1 endpoints."""

    def __init__(self, client: SeamlessClient, debit_timeout_ms: int) -> None:
        self.client = client
        self.debit_timeout_ms = min(debit_timeout_ms, settings.WALLET_DEBIT_TIMEOUT_MAX_MS)

    @staticmethod
    def _envelope(tx: Any) -> dict[str, Any]:
        bet = tx.bet
        session = bet.session
        out: dict[str, Any] = {
            "transaction_id": tx_ref(tx.id),
            "bet_id": bet.public_id,
            "round_id": str(bet.round_id),  # same form as the operator API
            "player_id": bet.player.external_player_id,
            "currency": tx.currency,
            "amount": str(tx.amount_minor),
        }
        return out | _session_fields(session)

    def debit(self, tx: Any, timeout_ms: int | None = None) -> WalletResult:
        payload = self._envelope(tx) | {
            "game": "lux-rocket",
            "panel": tx.bet.panel,
            "created_at": tx.created_at.isoformat(),
        }
        budget = self.debit_timeout_ms
        if timeout_ms is not None:
            budget = min(budget, timeout_ms)
        return self.client.call("debit", payload, budget)

    def credit(self, tx: Any) -> WalletResult:
        bet = tx.bet
        payload = self._envelope(tx) | {
            "debit_transaction_id": tx_ref(deterministic_tx_id(bet.id, "DEBIT")),
            "type": "WIN",
            "multiplier_x10000": bet.cashout_x10000,
            "created_at": tx.created_at.isoformat(),
        }
        return self.client.call("credit", payload, settings.WALLET_TIMEOUT_MS)

    def rollback(self, tx: Any, debit_tx_id: uuid.UUID) -> WalletResult:
        payload = self._envelope(tx)
        for key in ("session_id", "operator_session_token"):
            payload.pop(key, None)  # not part of the rollback contract
        payload |= {
            "rolled_back_transaction_id": tx_ref(debit_tx_id),
            "reason": rollback_reason(tx.bet),
        }
        return self.client.call("rollback", payload, settings.WALLET_TIMEOUT_MS)

    def balance(self, session: Any) -> int | None:
        payload = {
            "player_id": session.player.external_player_id,
            "currency": session.currency,
        } | _session_fields(session)
        return self.client.balance(payload, settings.WALLET_BALANCE_TIMEOUT_MS)


def _session_fields(session: Any) -> dict[str, str]:
    out = {"session_id": session.public_id}
    if session.operator_session_token:
        out["operator_session_token"] = session.operator_session_token
    return out


def rollback_reason(bet: Any) -> str:
    if bet.status == "DEBIT_UNKNOWN":
        return "DEBIT_UNCERTAIN"
    if bet.status == "VOIDED" or bet.reject_code == "ROUND_VOIDED":
        return "ROUND_VOIDED"
    return "BET_EXCLUDED"
