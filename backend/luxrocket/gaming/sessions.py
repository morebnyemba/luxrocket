"""Session lifecycle: create (operator), exchange launch token, renew, WS tickets (doc 11 §3-4)."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from luxrocket.core.tokens import new_token, token_hash
from luxrocket.gaming import session_tokens
from luxrocket.gaming.models import GameSession, LaunchToken, PlayerRef, WsTicket
from luxrocket.operators.models import (
    Market,
    Operator,
    OperatorCurrencyLimit,
    OperatorJurisdiction,
    WalletKind,
)
from luxrocket.wallet.models import SandboxWalletAccount


class SessionError(Exception):
    def __init__(self, code: str, status: int = 403) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class CreatedSession:
    session: GameSession
    launch_token: str
    expires_at: Any


def create_session(operator: Operator, payload: dict[str, Any]) -> CreatedSession:
    """Validate policy and create a session + single-use launch token (doc 09 §4.1)."""
    mode = payload["mode"]
    player_in = payload["player"]
    country = player_in["country"]
    currency = payload["currency"]

    if operator.status in (Operator.Status.SUSPENDED, Operator.Status.TERMINATED):
        raise SessionError("OPERATOR_SUSPENDED")
    wallet_kind = operator.wallet_kind
    if mode == "REAL" and not (
        operator.real_money_enabled
        and operator.status == Operator.Status.LIVE
        and wallet_kind == WalletKind.SEAMLESS_V1
    ):
        raise SessionError("REAL_MONEY_DISABLED")
    if wallet_kind == WalletKind.SEAMLESS_V1 and not operator.wallet_base_url:
        raise SessionError("WALLET_NOT_CONFIGURED")
    market = Market.objects.filter(country_code=country).first()
    if market is None or not market.allows(mode):
        raise SessionError("JURISDICTION_NOT_PERMITTED")
    if not OperatorJurisdiction.objects.filter(operator=operator, country_code=country).exists():
        raise SessionError("JURISDICTION_NOT_PERMITTED")
    if not OperatorCurrencyLimit.objects.filter(operator=operator, currency=currency).exists():
        raise SessionError("CURRENCY_NOT_ENABLED")

    now = timezone.now()
    token = new_token("lt")
    with transaction.atomic():
        player, _ = PlayerRef.objects.get_or_create(
            operator=operator,
            external_player_id=player_in["id"],
            defaults={"country_code": country, "display_alias": player_in.get("alias", "")},
        )
        if player.restricted:
            raise SessionError("PLAYER_RESTRICTED", status=422)
        session = GameSession.objects.create(
            operator=operator,
            player=player,
            currency=currency,
            locale=payload.get("locale", "en"),
            mode=mode,
            stream_slug=operator.stream_slug,
            wallet_kind=wallet_kind,
            wallet_base_url=operator.wallet_base_url,
            operator_session_token=payload.get("operator_session_token", ""),
            expires_at=now + timedelta(hours=settings.SESSION_MAX_HOURS),
        )
        expires = now + timedelta(seconds=settings.LAUNCH_TOKEN_TTL_SECONDS)
        LaunchToken.objects.create(
            token_hash=token_hash(token), session=session, expires_at=expires
        )
        if wallet_kind == WalletKind.SIMULATED:
            SandboxWalletAccount.objects.get_or_create(
                operator=operator,
                player=player,
                currency=currency,
                defaults={"balance_minor": settings.SANDBOX_OPENING_BALANCE_MINOR},
            )
    return CreatedSession(session=session, launch_token=token, expires_at=expires)


def _issue_token(session: GameSession) -> str:
    return session_tokens.issue(
        session_id=session.public_id,
        operator_id=session.operator.public_id,
        session_version=session.session_version,
    )


def exchange_launch_token(token: str) -> tuple[GameSession, str]:
    """Consume a launch token exactly once (conditional UPDATE — race-safe) (FR-003)."""
    now = timezone.now()
    with transaction.atomic():
        updated = LaunchToken.objects.filter(
            token_hash=token_hash(token), used_at__isnull=True, expires_at__gt=now
        ).update(used_at=now)
        if updated != 1:
            raise SessionError("LAUNCH_TOKEN_INVALID", status=401)
        lt = LaunchToken.objects.select_related("session__operator").get(
            token_hash=token_hash(token)
        )
        session = lt.session
        if session.status not in (GameSession.Status.PENDING, GameSession.Status.ACTIVE):
            raise SessionError("SESSION_INACTIVE", status=401)
        if session.status == GameSession.Status.PENDING:
            session.status = GameSession.Status.ACTIVE
            session.save(update_fields=["status"])
    return session, _issue_token(session)


def authenticate(bearer: str) -> GameSession:
    """Validate a game-session token and the session's live status/version."""
    try:
        claims = session_tokens.verify(bearer)
    except session_tokens.InvalidToken as exc:
        raise SessionError("TOKEN_INVALID", status=401) from exc
    session = (
        GameSession.objects.select_related("operator", "player")
        .filter(public_id=claims["sid"])
        .first()
    )
    if session is None or not is_active(session) or session.session_version != claims["sv"]:
        raise SessionError("SESSION_INACTIVE", status=401)
    return session


def is_active(session: GameSession) -> bool:
    return session.status == GameSession.Status.ACTIVE and session.expires_at > timezone.now()


def renew(session: GameSession) -> str:
    return _issue_token(session)


def issue_ws_ticket(session: GameSession) -> str:
    ticket = new_token("wst")
    WsTicket.objects.create(
        token_hash=token_hash(ticket),
        session=session,
        expires_at=timezone.now() + timedelta(seconds=settings.WS_TICKET_TTL_SECONDS),
    )
    return ticket


def consume_ws_ticket(ticket: str) -> GameSession:
    now = timezone.now()
    with transaction.atomic():
        updated = WsTicket.objects.filter(
            token_hash=token_hash(ticket), used_at__isnull=True, expires_at__gt=now
        ).update(used_at=now)
        if updated != 1:
            raise SessionError("TICKET_INVALID", status=401)
        session = (
            WsTicket.objects.select_related("session__operator", "session__player")
            .get(token_hash=token_hash(ticket))
            .session
        )
    if not is_active(session):
        raise SessionError("SESSION_INACTIVE", status=401)
    return session


def revoke(session: GameSession, reason: str) -> None:
    from luxrocket.wallet.outbox import emit

    with transaction.atomic():
        GameSession.objects.filter(pk=session.pk).update(
            status=GameSession.Status.REVOKED,
            revoked_reason=reason[:64],
            session_version=session.session_version + 1,
        )
        emit("session.revoked", {"session_id": session.public_id, "reason": reason[:64]})


def session_view(session: GameSession) -> dict[str, Any]:
    """Session configuration shared with the game client and Phoenix."""
    limit = OperatorCurrencyLimit.objects.get(operator=session.operator, currency=session.currency)
    return {
        "session_id": session.public_id,
        "operator_id": session.operator.public_id,
        "player_alias": session.player.display_alias,
        "currency": session.currency,
        "exponent": limit.exponent,
        "locale": session.locale,
        "mode": session.mode,
        "stream_id": session.stream_slug,
        "session_version": session.session_version,
        "panels": settings.RULESET["panels"],
        "limits": {
            "min_stake": str(limit.min_stake_minor),
            "max_stake": str(limit.max_stake_minor),
            "max_win": str(limit.max_win_minor),
        },
    }
