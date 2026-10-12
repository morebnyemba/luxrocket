"""Wallet adapters behind one interface (doc 08 §2, doc 09 §6).

`SandboxWalletAdapter` simulates an operator's seamless wallet with the exact semantics the
contract requires of real operators: idempotent by transaction id, rollback of an unknown
debit succeeds and tombstones that id, credits always succeed.
"""

import random
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from django.conf import settings
from django.db import transaction
from django.db.models import F

from luxrocket.wallet.models import SandboxWalletAccount, SandboxWalletEntry, WalletTransaction

Outcome = Literal["OK", "REJECTED", "UNKNOWN"]


@dataclass(frozen=True)
class WalletResult:
    outcome: Outcome
    code: str = ""
    balance_minor: int | None = None


class WalletAdapter(Protocol):
    def debit(self, tx: WalletTransaction, timeout_ms: int | None = None) -> WalletResult: ...
    def credit(self, tx: WalletTransaction) -> WalletResult: ...
    def rollback(self, tx: WalletTransaction, debit_tx_id: uuid.UUID) -> WalletResult: ...
    def balance(self, session: Any) -> int | None: ...


class SandboxWalletAdapter:
    """In-platform simulated wallet for SANDBOX sessions."""

    def _account(self, tx: WalletTransaction) -> SandboxWalletAccount:
        bet = tx.bet
        return SandboxWalletAccount.objects.select_for_update().get(
            operator_id=bet.operator_id, player_id=bet.player_id, currency=bet.currency
        )

    def debit(self, tx: WalletTransaction, timeout_ms: int | None = None) -> WalletResult:
        with transaction.atomic():
            account = self._account(tx)
            existing = SandboxWalletEntry.objects.filter(transaction_id=tx.id).first()
            if existing is not None:
                if existing.tombstone:
                    return WalletResult("REJECTED", "DUPLICATE_TRANSACTION", account.balance_minor)
                return self._replay(existing, account)
            if account.balance_minor < tx.amount_minor:
                SandboxWalletEntry.objects.create(
                    transaction_id=tx.id,
                    account=account,
                    kind="DEBIT",
                    amount_minor=tx.amount_minor,
                    result="INSUFFICIENT_FUNDS",
                )
                return WalletResult("REJECTED", "INSUFFICIENT_FUNDS", account.balance_minor)
            SandboxWalletAccount.objects.filter(pk=account.pk).update(
                balance_minor=F("balance_minor") - tx.amount_minor
            )
            SandboxWalletEntry.objects.create(
                transaction_id=tx.id,
                account=account,
                kind="DEBIT",
                amount_minor=tx.amount_minor,
                result="OK",
            )
            balance = account.balance_minor - tx.amount_minor
        # Fault injection: the debit landed but the response is "lost" (rollback-on-doubt test).
        if random.random() < settings.SANDBOX_DEBIT_UNKNOWN_RATE:  # noqa: S311
            return WalletResult("UNKNOWN", "SIMULATED_TIMEOUT")
        return WalletResult("OK", balance_minor=balance)

    def credit(self, tx: WalletTransaction) -> WalletResult:
        with transaction.atomic():
            account = self._account(tx)
            existing = SandboxWalletEntry.objects.filter(transaction_id=tx.id).first()
            if existing is not None:
                return self._replay(existing, account)
            SandboxWalletAccount.objects.filter(pk=account.pk).update(
                balance_minor=F("balance_minor") + tx.amount_minor
            )
            SandboxWalletEntry.objects.create(
                transaction_id=tx.id,
                account=account,
                kind="CREDIT",
                amount_minor=tx.amount_minor,
                result="OK",
            )
            return WalletResult("OK", balance_minor=account.balance_minor + tx.amount_minor)

    def rollback(self, tx: WalletTransaction, debit_tx_id: uuid.UUID) -> WalletResult:
        with transaction.atomic():
            account = self._account(tx)
            existing = SandboxWalletEntry.objects.filter(transaction_id=tx.id).first()
            if existing is not None:
                return self._replay(existing, account)
            debit = SandboxWalletEntry.objects.filter(transaction_id=debit_tx_id).first()
            refunded = 0
            if debit is None:
                # Unknown debit: tombstone it so a late-arriving debit with this id is refused.
                SandboxWalletEntry.objects.create(
                    transaction_id=debit_tx_id,
                    account=account,
                    kind="DEBIT",
                    amount_minor=0,
                    result="TOMBSTONE",
                    tombstone=True,
                )
            elif debit.result == "OK":
                refunded = debit.amount_minor
                SandboxWalletAccount.objects.filter(pk=account.pk).update(
                    balance_minor=F("balance_minor") + refunded
                )
            SandboxWalletEntry.objects.create(
                transaction_id=tx.id,
                account=account,
                kind="ROLLBACK",
                amount_minor=refunded,
                result="OK",
            )
            return WalletResult("OK", balance_minor=account.balance_minor + refunded)

    def balance(self, session: Any) -> int | None:
        acct = SandboxWalletAccount.objects.filter(
            operator_id=session.operator_id, player_id=session.player_id, currency=session.currency
        ).first()
        return acct.balance_minor if acct else None

    @staticmethod
    def _replay(entry: SandboxWalletEntry, account: SandboxWalletAccount) -> WalletResult:
        if entry.result == "OK":
            return WalletResult("OK", balance_minor=account.balance_minor)
        return WalletResult("REJECTED", entry.result, account.balance_minor)


def adapter_for(session: Any) -> WalletAdapter:
    """Route by the wallet snapshotted on the session, never the operator's current setting."""
    if session.wallet_kind == "SIMULATED":
        if session.mode != "SANDBOX":
            raise RuntimeError("simulated wallet can never carry REAL money")
        return SandboxWalletAdapter()
    if session.wallet_kind == "SEAMLESS_V1":
        from luxrocket.wallet.seamless import SeamlessClient, SeamlessWalletAdapter

        operator = session.operator
        # Prefer the operator's current URL (endpoint rotation), but never lose the wallet that
        # took the stake if the operator has since been moved off seamless routing.
        url = operator.wallet_base_url if operator.wallet_kind == "SEAMLESS_V1" else ""
        return SeamlessWalletAdapter(
            SeamlessClient(url or session.wallet_base_url), operator.wallet_debit_timeout_ms
        )
    raise RuntimeError(f"unknown wallet kind {session.wallet_kind!r}")
