"""Double-entry ledger postings (doc 08 §7.1). Each call writes one balanced journal."""

from luxrocket.core.ids import uuid7
from luxrocket.gaming.models import Bet
from luxrocket.wallet.models import LedgerEntry

A = LedgerEntry.Account


class UnbalancedJournal(Exception):
    pass


def post(bet: Bet, memo: str, legs: list[tuple[str, int]]) -> None:
    if sum(amount for _, amount in legs) != 0:
        raise UnbalancedJournal(f"{memo}: {legs}")
    journal_id = uuid7()
    LedgerEntry.objects.bulk_create(
        LedgerEntry(
            journal_id=journal_id,
            operator_id=bet.operator_id,
            account=account,
            amount_minor=amount,
            currency=bet.currency,
            bet=bet,
            memo=memo,
        )
        for account, amount in legs
        if amount != 0
    )


def debit_ok(bet: Bet) -> None:
    post(bet, "debit", [(A.PLAYER_WALLET, -bet.stake_minor), (A.BETS_IN_PLAY, bet.stake_minor)])


def cashout_accepted(bet: Bet, payout: int) -> None:
    s = bet.stake_minor
    post(
        bet,
        "cashout",
        [(A.BETS_IN_PLAY, -s), (A.PAYOUTS_PAYABLE, payout), (A.GAME_RESULT, s - payout)],
    )


def credit_ok(bet: Bet, payout: int) -> None:
    post(bet, "credit", [(A.PAYOUTS_PAYABLE, -payout), (A.PLAYER_WALLET, payout)])


def lost(bet: Bet) -> None:
    post(bet, "lost", [(A.BETS_IN_PLAY, -bet.stake_minor), (A.GAME_RESULT, bet.stake_minor)])


def refund_decided(bet: Bet) -> None:
    post(
        bet,
        "refund_decided",
        [(A.BETS_IN_PLAY, -bet.stake_minor), (A.REFUNDS_PAYABLE, bet.stake_minor)],
    )


def rollback_ok(bet: Bet) -> None:
    post(
        bet, "rollback", [(A.REFUNDS_PAYABLE, -bet.stake_minor), (A.PLAYER_WALLET, bet.stake_minor)]
    )
