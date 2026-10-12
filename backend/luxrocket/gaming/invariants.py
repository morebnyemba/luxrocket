"""Money-correctness invariants (doc 16 §2.5). Run after every E2E/chaos run and on a schedule."""

from dataclasses import dataclass

from django.db import connection


@dataclass(frozen=True)
class Check:
    name: str
    sql: str
    expect_zero: bool = True


CHECKS = [
    Check(
        "ledger journals sum to zero",
        "SELECT count(*) FROM (SELECT journal_id FROM platform.wallet_ledgerentry "
        "GROUP BY journal_id HAVING sum(amount_minor) <> 0) x",
    ),
    Check(
        "at most one succeeded transaction per bet and type",
        "SELECT count(*) FROM (SELECT bet_id, type FROM platform.wallet_wallettransaction "
        "WHERE status = 'SUCCEEDED' GROUP BY bet_id, type HAVING count(*) > 1) x",
    ),
    Check(
        "no bet both cashed out and refunded",
        "SELECT count(*) FROM platform.gaming_bet b WHERE b.status = 'CASHED_OUT' AND EXISTS "
        "(SELECT 1 FROM platform.wallet_wallettransaction t WHERE t.bet_id = b.id "
        "AND t.type = 'ROLLBACK' AND t.status = 'SUCCEEDED')",
    ),
    Check(
        "every crashed round's outcome verified",
        "SELECT count(*) FROM platform.gaming_gameround WHERE state = 'CRASHED' "
        "AND outcome_verified IS NOT TRUE",
    ),
    Check(
        "no cash-out above its round's crash point",
        "SELECT count(*) FROM platform.gaming_bet b JOIN platform.gaming_gameround r "
        "ON r.id = b.round_id WHERE b.status = 'CASHED_OUT' AND r.crash_x10000 IS NOT NULL "
        "AND b.cashout_x10000 > r.crash_x10000",
    ),
    Check(
        "no live bets in finished rounds",
        "SELECT count(*) FROM platform.gaming_bet b JOIN platform.gaming_gameround r "
        "ON r.id = b.round_id WHERE r.state IN ('CRASHED','VOIDED') "
        "AND b.status IN ('ACTIVE','DEBITED')",
    ),
    Check(
        "sandbox wallet movements equal ledger player_wallet",
        "SELECT abs((SELECT coalesce(sum(amount_minor),0) FROM platform.wallet_ledgerentry "
        "WHERE account='player_wallet') - (SELECT coalesce(sum(CASE WHEN kind='DEBIT' AND "
        "result='OK' THEN -amount_minor WHEN kind IN ('CREDIT','ROLLBACK') AND result='OK' "
        "THEN amount_minor ELSE 0 END),0) FROM platform.wallet_sandboxwalletentry e "
        "WHERE e.transaction_id IN (SELECT id FROM platform.wallet_wallettransaction WHERE "
        "bet_id IN (SELECT bet_id FROM platform.wallet_wallettransaction WHERE type='DEBIT' "
        "AND status='SUCCEEDED'))))",
    ),
]


def run() -> list[tuple[str, int]]:
    """Returns (name, violations) for every check."""
    results = []
    with connection.cursor() as cursor:
        for check in CHECKS:
            cursor.execute(check.sql)
            row = cursor.fetchone()
            results.append((check.name, int(row[0]) if row else 0))
    return results
