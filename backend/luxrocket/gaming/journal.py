"""Applies Phoenix round facts to financial records, in stream order (doc 08 §7).

Facts arrive at-least-once in batches ordered by stream_seq. Each fact is applied exactly once
(ProcessedEvent + cursor) inside one transaction with all of its effects: bet transitions,
ledger postings and wallet jobs. Django also re-verifies every revealed outcome independently.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from luxrocket.core import outcome
from luxrocket.core.ids import deterministic_tx_id
from luxrocket.core.multiplier import payout_minor
from luxrocket.gaming.models import Bet, GameRound, ProcessedEvent, StreamCursor
from luxrocket.operators import webhooks
from luxrocket.wallet import ledger
from luxrocket.wallet.models import Settlement, WalletTransaction

log = logging.getLogger(__name__)


@dataclass
class ApplyResult:
    applied: int = 0
    skipped: int = 0
    expected_seq: int | None = None  # set when a gap stops application


def apply_batch(events: list[dict[str, Any]]) -> ApplyResult:
    result = ApplyResult()
    for event in sorted(events, key=lambda e: int(e["stream_seq"])):
        stream = str(event["stream_id"])
        seq = int(event["stream_seq"])
        with transaction.atomic():
            cursor, _ = StreamCursor.objects.select_for_update().get_or_create(stream_slug=stream)
            if seq <= cursor.last_seq:
                result.skipped += 1
                continue
            if seq != cursor.last_seq + 1:
                result.expected_seq = cursor.last_seq + 1
                return result
            if not ProcessedEvent.objects.filter(pk=event["event_id"]).exists():
                _apply(event)
                ProcessedEvent.objects.create(event_id=event["event_id"])
            cursor.last_seq = seq
            cursor.save(update_fields=["last_seq"])
            result.applied += 1
    return result


def _apply(event: dict[str, Any]) -> None:
    handler = HANDLERS.get(event["type"])
    if handler is None:
        log.info("ignoring unknown fact type %s", event["type"])
        return
    handler(uuid.UUID(event["round_id"]), event["stream_id"], event.get("payload") or {})


# ---- round projection ----------------------------------------------------------------------


def _round(round_id: uuid.UUID, stream: str, number: int | None = None) -> GameRound:
    rnd = GameRound.objects.select_for_update().filter(pk=round_id).first()
    if rnd is None:
        rnd = GameRound.objects.create(
            id=round_id, stream_slug=stream, number=number or 0, state="PENDING"
        )
    return rnd


def on_round_created(round_id: uuid.UUID, stream: str, p: dict[str, Any]) -> None:
    rnd = _round(round_id, stream, int(p["number"]))
    rnd.number = int(p["number"])
    rnd.commitment = p.get("commitment", "")
    rnd.house_edge_bp = p.get("house_edge_bp")
    rnd.max_multiplier_x10000 = p.get("max_multiplier_x10000")
    rnd.ruleset_code = str(p.get("ruleset_code") or "LR-STD-97")[:40]
    rnd.ruleset_version = p.get("ruleset_version")
    rnd.ruleset_ok = _ruleset_approved(rnd)
    if not rnd.ruleset_ok:
        # The engine ran parameters nobody approved: the outcome can never count as verified.
        log.critical(
            "round %s uses unapproved ruleset %s (edge=%s max=%s)",
            round_id,
            rnd.ruleset_code,
            rnd.house_edge_bp,
            rnd.max_multiplier_x10000,
        )
    rnd.save()


def _ruleset_approved(rnd: GameRound) -> bool:
    from luxrocket.gaming.models import GameRuleset

    rs = GameRuleset.objects.filter(code=rnd.ruleset_code).first()
    return bool(
        rs is not None
        and rs.status in (GameRuleset.Status.APPROVED, GameRuleset.Status.RETIRED)
        and rs.house_edge_bp == rnd.house_edge_bp
        and rs.max_multiplier_x10000 == rnd.max_multiplier_x10000
    )


def _set_state(state: str) -> Any:
    def handler(round_id: uuid.UUID, stream: str, p: dict[str, Any]) -> None:
        rnd = _round(round_id, stream)
        rnd.state = state
        if "launch_at" in p:
            rnd.launch_at_ms = int(p["launch_at"])
        rnd.save()

    return handler


# ---- bets ----------------------------------------------------------------------------------


def _bet_by_ref(round_id: uuid.UUID, p: dict[str, Any]) -> Bet | None:
    qs = Bet.objects.select_for_update().filter(round_id=round_id)
    if p.get("bet_id"):
        return qs.filter(public_id=p["bet_id"]).first()
    command_id = p.get("command_id")
    if not command_id:
        return None
    return qs.filter(
        session__public_id=p.get("session_id", ""), client_command_id=str(command_id)
    ).first()


def on_bet_admitted(round_id: uuid.UUID, stream: str, p: dict[str, Any]) -> None:
    bet = _bet_by_ref(round_id, p)
    if bet is None or bet.status != Bet.Status.DEBITED:
        log.error("BET_ADMITTED for bet in unexpected state: %s", p)
        return
    bet.status = Bet.Status.ACTIVE
    bet.save(update_fields=["status", "updated_at"])


def exclude_bet(bet: Bet, reason: str) -> None:
    """A debited bet that is not part of the round is refunded (ADR-024)."""
    if bet.status == Bet.Status.DEBITED:
        ledger.refund_decided(bet)
        Settlement.objects.get_or_create(bet=bet, defaults={"outcome": Settlement.Outcome.REFUND})
        _enqueue(bet, WalletTransaction.Type.ROLLBACK, bet.stake_minor)
    bet.status = Bet.Status.EXCLUDED
    bet.reject_code = bet.reject_code or reason[:32]
    bet.save(update_fields=["status", "reject_code", "updated_at"])


def on_bet_excluded(round_id: uuid.UUID, stream: str, p: dict[str, Any]) -> None:
    bet = _bet_by_ref(round_id, p)
    if bet is None:
        return  # Django never received the request; nothing was debited.
    if bet.status in (Bet.Status.DEBITED, Bet.Status.PENDING_DEBIT):
        exclude_bet(bet, p.get("reason", "EXCLUDED"))


def on_cashout_accepted(round_id: uuid.UUID, stream: str, p: dict[str, Any]) -> None:
    bet = _bet_by_ref(round_id, p)
    if bet is None or bet.status != Bet.Status.ACTIVE:
        log.critical("CASHOUT_ACCEPTED for bet not ACTIVE: %s", p)
        return
    multiplier = int(p["cashout_x10000"])
    expected = payout_minor(bet.stake_minor, multiplier, bet.max_win_minor)
    if expected != int(p["payout_minor"]):
        # Never silently substitute either value (doc 02 §5).
        log.critical("payout mismatch for %s: phoenix=%s django=%s", bet.public_id, p, expected)
        Settlement.objects.update_or_create(
            bet=bet,
            defaults={
                "outcome": Settlement.Outcome.WIN,
                "payout_minor": expected,
                "multiplier_x10000": multiplier,
                "status": Settlement.Status.NEEDS_ATTENTION,
            },
        )
        return
    bet.status = Bet.Status.CASHED_OUT
    bet.cashout_x10000 = multiplier
    bet.payout_minor = expected
    bet.save(update_fields=["status", "cashout_x10000", "payout_minor", "updated_at"])
    ledger.cashout_accepted(bet, expected)
    Settlement.objects.create(
        bet=bet, outcome=Settlement.Outcome.WIN, payout_minor=expected, multiplier_x10000=multiplier
    )
    _enqueue(bet, WalletTransaction.Type.CREDIT, expected)


def _verify_outcome(rnd: GameRound, p: dict[str, Any]) -> bool:
    try:
        seed = bytes.fromhex(p["seed"])
        salt = bytes.fromhex(p["salt"])
        crash = outcome.crash_from_seed(
            seed, salt, int(rnd.house_edge_bp or 0), int(rnd.max_multiplier_x10000 or 0)
        )
        committed = hashlib.sha256(seed).hexdigest() == rnd.commitment
        return committed and crash == int(p["crash_x10000"]) and rnd.ruleset_ok is not False
    except (KeyError, ValueError) as exc:
        log.critical("outcome verification failed to run: %s", exc)
        return False


def on_round_crashed(round_id: uuid.UUID, stream: str, p: dict[str, Any]) -> None:
    rnd = _round(round_id, stream)
    rnd.state = "CRASHED"
    rnd.crash_x10000 = int(p["crash_x10000"])
    rnd.end_reason = p.get("end_reason", "CRASH")
    rnd.seed_hex = p.get("seed", "")
    rnd.salt_hex = p.get("salt", "")
    rnd.outcome_verified = _verify_outcome(rnd, p)
    rnd.settlement_status = GameRound.Settlement.SETTLING
    if not rnd.outcome_verified:
        log.critical("OUTCOME VERIFICATION FAILED for round %s", round_id)
        rnd.settlement_status = GameRound.Settlement.NEEDS_ATTENTION
    rnd.save()

    for bet in Bet.objects.select_for_update().filter(round_id=round_id):
        if bet.status == Bet.Status.ACTIVE:
            bet.status = Bet.Status.LOST
            bet.save(update_fields=["status", "updated_at"])
            ledger.lost(bet)
            # Phoenix notifies the player of the loss directly; no wallet call is needed.
            loss = Settlement.objects.create(
                bet=bet,
                outcome=Settlement.Outcome.LOSS,
                status=Settlement.Status.CONFIRMED,
                confirmed_at=timezone.now(),
            )
            webhooks.bet_settled(bet, loss)
        elif bet.status in (Bet.Status.DEBITED, Bet.Status.PENDING_DEBIT):
            exclude_bet(bet, "NOT_ADMITTED")
        elif bet.status == Bet.Status.CASHED_OUT and bet.cashout_x10000 is not None:
            if bet.cashout_x10000 > rnd.crash_x10000:
                log.critical("cash-out above crash point on bet %s", bet.public_id)
                rnd.settlement_status = GameRound.Settlement.NEEDS_ATTENTION
                rnd.save(update_fields=["settlement_status"])
    refresh_round_settlement(round_id)


def on_round_voided(round_id: uuid.UUID, stream: str, p: dict[str, Any]) -> None:
    rnd = _round(round_id, stream)
    rnd.state = "VOIDED"
    rnd.end_reason = p.get("reason", "VOIDED")[:16]
    rnd.seed_hex = p.get("seed", "")
    rnd.settlement_status = GameRound.Settlement.SETTLING
    rnd.save()
    for bet in Bet.objects.select_for_update().filter(round_id=round_id):
        if bet.status == Bet.Status.ACTIVE:
            ledger.refund_decided(bet)
            Settlement.objects.create(bet=bet, outcome=Settlement.Outcome.REFUND)
            _enqueue(bet, WalletTransaction.Type.ROLLBACK, bet.stake_minor)
            bet.status = Bet.Status.VOIDED
            bet.save(update_fields=["status", "updated_at"])
        elif bet.status in (Bet.Status.DEBITED, Bet.Status.PENDING_DEBIT):
            exclude_bet(bet, "ROUND_VOIDED")
    refresh_round_settlement(round_id)


def _enqueue(bet: Bet, tx_type: str, amount: int) -> None:
    WalletTransaction.objects.get_or_create(
        bet=bet,
        type=tx_type,
        defaults={
            "id": deterministic_tx_id(bet.id, tx_type),
            "operator_id": bet.operator_id,
            "amount_minor": amount,
            "currency": bet.currency,
        },
    )


def refresh_round_settlement(round_id: uuid.UUID) -> None:
    rnd = GameRound.objects.filter(pk=round_id).first()
    if rnd is None or rnd.state not in ("CRASHED", "VOIDED"):
        return
    if rnd.settlement_status == GameRound.Settlement.NEEDS_ATTENTION:
        return
    open_bets = Bet.objects.filter(
        round_id=round_id,
        status__in=[Bet.Status.ACTIVE, Bet.Status.DEBITED, Bet.Status.PENDING_DEBIT],
    ).exists()
    pending = WalletTransaction.objects.filter(
        bet__round_id=round_id,
        status__in=[WalletTransaction.Status.PENDING, WalletTransaction.Status.UNKNOWN],
    ).exists()
    if not open_bets and not pending:
        with transaction.atomic():
            # Conditional update: only the transition to SETTLED emits round.settled.
            changed = (
                GameRound.objects.filter(pk=round_id)
                .exclude(settlement_status=GameRound.Settlement.SETTLED)
                .update(settlement_status=GameRound.Settlement.SETTLED)
            )
            if changed:
                webhooks.round_settled(rnd)


HANDLERS = {
    "ROUND_CREATED": on_round_created,
    "ROUND_OPENED": _set_state("BETTING_OPEN"),
    "BETTING_CLOSED": _set_state("BETTING_CLOSED"),
    "ROUND_LAUNCHED": _set_state("FLYING"),
    "BET_ADMITTED": on_bet_admitted,
    "BET_EXCLUDED": on_bet_excluded,
    "CASHOUT_ACCEPTED": on_cashout_accepted,
    "ROUND_CRASHED": on_round_crashed,
    "ROUND_VOIDED": on_round_voided,
}

_ = settings  # settings imported for future per-stream ruleset lookups
