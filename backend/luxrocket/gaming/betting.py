"""Bet placement called synchronously by the Phoenix coordinator (doc 05 §4, doc 08 §4).

Two short transactions around the wallet debit; never an external call inside a transaction.
A debit is not inclusion: Phoenix's journaled BET_ADMITTED makes a bet part of the round.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F

from luxrocket.core.ids import deterministic_tx_id
from luxrocket.core.multiplier import GRID, MIN_AUTO_CASHOUT, UNIT
from luxrocket.gaming.models import Bet, GameRound, GameSession, RoundOperatorExposure, StreamCursor
from luxrocket.gaming.sessions import is_active
from luxrocket.operators.models import Operator, OperatorCurrencyLimit
from luxrocket.wallet import ledger
from luxrocket.wallet.adapters import WalletResult, adapter_for
from luxrocket.wallet.models import WalletTransaction, WalletTxAttempt

log = logging.getLogger(__name__)

TERMINAL_ROUND_STATES = {"FLYING", "CRASHED", "VOIDED"}
DEBIT_HEADROOM_MS = 100


@dataclass(frozen=True)
class BetResult:
    status: str  # ACCEPTED | REJECTED | UNKNOWN
    code: str = ""
    bet_id: str = ""
    balance_minor: int | None = None
    max_win_minor: int | None = None
    stake_minor: int | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.code:
            out["code"] = self.code
        if self.bet_id:
            out["bet_id"] = self.bet_id
        if self.balance_minor is not None:
            out["balance"] = str(self.balance_minor)
        if self.max_win_minor is not None:
            out["max_win"] = str(self.max_win_minor)
        if self.stake_minor is not None:
            out["stake"] = str(self.stake_minor)
        return out


def _existing_result(bet: Bet) -> BetResult:
    mapping = {
        Bet.Status.REJECTED: "REJECTED",
        Bet.Status.DEBIT_UNKNOWN: "UNKNOWN",
        Bet.Status.PENDING_DEBIT: "UNKNOWN",
    }
    status = mapping.get(bet.status, "ACCEPTED")  # type: ignore[call-overload]
    if status == "ACCEPTED":
        return BetResult(status, "", bet.public_id, None, bet.max_win_minor, bet.stake_minor)
    return BetResult(status, bet.reject_code, bet.public_id)


def check_fencing(stream_slug: str, token: int) -> bool:
    """Reject calls from a coordinator older than the newest one we have seen (ADR-004)."""
    with transaction.atomic():
        cursor, _ = StreamCursor.objects.select_for_update().get_or_create(stream_slug=stream_slug)
        if token < cursor.max_fencing_token:
            return False
        if token > cursor.max_fencing_token:
            cursor.max_fencing_token = token
            cursor.save(update_fields=["max_fencing_token"])
    return True


def place_bet(req: dict[str, Any]) -> BetResult:
    try:
        round_id = uuid.UUID(req["round_id"])
        command_id = uuid.UUID(req["command_id"])
        panel = int(req["panel"])
        stake = int(req["stake"])
        auto = req.get("auto_cashout_x10000")
        auto = int(auto) if auto is not None else None
        deadline_ms = int(req["debit_deadline_ms"])
        fencing = int(req["fencing_token"])
        stream = str(req["stream_id"])
    except (KeyError, TypeError, ValueError):
        return BetResult("REJECTED", "INVALID_REQUEST")

    if not check_fencing(stream, fencing):
        return BetResult("REJECTED", "STALE_COORDINATOR")

    # ---- Phase 1: validate and record intent ---------------------------------------------
    with transaction.atomic():
        session = (
            GameSession.objects.select_for_update()
            .select_related("operator", "player")
            .filter(public_id=req.get("session_id", ""))
            .first()
        )
        if session is None or not is_active(session):
            return BetResult("REJECTED", "SESSION_INACTIVE")
        existing = Bet.objects.filter(
            round_id=round_id, session=session, client_command_id=command_id
        ).first()
        if existing is not None:
            return _existing_result(existing)
        if session.stream_slug != stream:
            return BetResult("REJECTED", "ROUND_MISMATCH")
        if time.time() * 1000 > deadline_ms:
            return BetResult("REJECTED", "BETTING_CLOSED")
        projected = GameRound.objects.filter(pk=round_id).only("state").first()
        if projected is not None and projected.state in TERMINAL_ROUND_STATES:
            return BetResult("REJECTED", "BETTING_CLOSED")
        operator = session.operator
        if operator.status in (Operator.Status.SUSPENDED, Operator.Status.TERMINATED):
            return BetResult("REJECTED", "OPERATOR_UNAVAILABLE")
        if session.player.restricted:
            return BetResult("REJECTED", "PLAYER_RESTRICTED")
        if not 0 <= panel < settings.RULESET["panels"]:
            return BetResult("REJECTED", "INVALID_REQUEST")
        limit = OperatorCurrencyLimit.objects.get(operator=operator, currency=session.currency)
        if not limit.min_stake_minor <= stake <= limit.max_stake_minor:
            return BetResult("REJECTED", "STAKE_OUT_OF_RANGE")
        max_mult = settings.RULESET["max_multiplier_x10000"]
        if auto is not None and (auto % GRID or auto < MIN_AUTO_CASHOUT or auto > max_mult):
            return BetResult("REJECTED", "AUTO_CASHOUT_INVALID")

        liability = min(stake * max_mult // UNIT, limit.max_win_minor)
        exposure, _ = RoundOperatorExposure.objects.get_or_create(
            round_id=round_id,
            operator=operator,
            currency=session.currency,
            defaults={"limit_minor": limit.round_exposure_limit_minor},
        )
        bumped = RoundOperatorExposure.objects.filter(
            pk=exposure.pk, exposure_minor__lte=F("limit_minor") - liability
        ).update(exposure_minor=F("exposure_minor") + liability)
        if bumped != 1:
            return BetResult("REJECTED", "EXPOSURE_LIMIT")
        try:
            with transaction.atomic():
                bet = Bet.objects.create(
                    operator=operator,
                    session=session,
                    player=session.player,
                    round_id=round_id,
                    panel=panel,
                    client_command_id=command_id,
                    currency=session.currency,
                    stake_minor=stake,
                    auto_cashout_x10000=auto,
                    max_win_minor=limit.max_win_minor,
                    status=Bet.Status.PENDING_DEBIT,
                )
        except IntegrityError:
            transaction.set_rollback(True)
            return BetResult("REJECTED", "PANEL_BUSY")
        tx = WalletTransaction.objects.create(
            id=deterministic_tx_id(bet.id, "DEBIT"),
            operator=operator,
            bet=bet,
            type=WalletTransaction.Type.DEBIT,
            amount_minor=stake,
            currency=session.currency,
        )

    # ---- External call: wallet debit (no transaction open) -------------------------------
    # A debit answered after the cut-off cannot be admitted anyway: never wait past it, and
    # keep headroom so we answer Phoenix (whose own timeout ends at the cut-off) in time.
    remaining_ms = max(int(deadline_ms - time.time() * 1000) - DEBIT_HEADROOM_MS, 50)
    started = time.monotonic()
    try:
        result = adapter_for(session).debit(tx, timeout_ms=remaining_ms)
    except Exception:  # an adapter crash is an unknown outcome, never a failure
        log.exception("wallet debit raised; treating as UNKNOWN")
        result = WalletResult("UNKNOWN", "ADAPTER_ERROR")
    latency = int((time.monotonic() - started) * 1000)

    # ---- Phase 2: record the outcome -------------------------------------------------------
    with transaction.atomic():
        bet = Bet.objects.select_for_update().get(pk=bet.pk)
        WalletTxAttempt.objects.create(
            transaction=tx,
            attempt_no=1,
            outcome=result.outcome,
            operator_code=result.code,
            latency_ms=latency,
        )
        tx.attempt_count = 1
        tx.operator_code = result.code
        if result.outcome == "OK":
            # The coordinator may already have excluded this bet (BET_EXCLUDED applied while the
            # debit was in flight), or the round may be over: record the debit, then refund.
            excluded_meanwhile = bet.status == Bet.Status.EXCLUDED
            tx.status = WalletTransaction.Status.SUCCEEDED
            tx.save()
            bet.status = Bet.Status.DEBITED
            bet.save(update_fields=["status", "updated_at"])
            ledger.debit_ok(bet)
            projected = GameRound.objects.filter(pk=round_id).only("state").first()
            if excluded_meanwhile or (
                projected is not None and projected.state in {"CRASHED", "VOIDED"}
            ):
                from luxrocket.gaming.journal import exclude_bet

                exclude_bet(bet, reason="LATE")
            return BetResult(
                "ACCEPTED",
                bet_id=bet.public_id,
                balance_minor=result.balance_minor,
                max_win_minor=bet.max_win_minor,
                stake_minor=bet.stake_minor,
            )
        if result.outcome == "REJECTED":
            tx.status = WalletTransaction.Status.FAILED
            tx.save()
            bet.status = Bet.Status.REJECTED
            bet.reject_code = result.code or "WALLET_REJECTED"
            bet.save(update_fields=["status", "reject_code", "updated_at"])
            _release_exposure(bet)
            return BetResult("REJECTED", bet.reject_code, bet.public_id, result.balance_minor)
        tx.status = WalletTransaction.Status.UNKNOWN
        tx.save()
        bet.status = Bet.Status.DEBIT_UNKNOWN
        bet.reject_code = "UNCERTAIN"
        bet.save(update_fields=["status", "reject_code", "updated_at"])
        _release_exposure(bet)
        _enqueue_rollback(bet)
        return BetResult("UNKNOWN", "UNCERTAIN", bet.public_id)


def _release_exposure(bet: Bet) -> None:
    liability = min(
        bet.stake_minor * settings.RULESET["max_multiplier_x10000"] // UNIT, bet.max_win_minor
    )
    RoundOperatorExposure.objects.filter(
        round_id=bet.round_id, operator_id=bet.operator_id, currency=bet.currency
    ).update(exposure_minor=F("exposure_minor") - liability)


def _enqueue_rollback(bet: Bet) -> WalletTransaction:
    tx, _ = WalletTransaction.objects.get_or_create(
        bet=bet,
        type=WalletTransaction.Type.ROLLBACK,
        defaults={
            "id": deterministic_tx_id(bet.id, "ROLLBACK"),
            "operator_id": bet.operator_id,
            "amount_minor": bet.stake_minor,
            "currency": bet.currency,
        },
    )
    return tx
