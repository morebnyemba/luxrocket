"""Operator API /operator/v1 — Ed25519-signed server-to-server calls (doc 09)."""

import hashlib
import json
from collections.abc import Callable
from functools import wraps
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from luxrocket.api.http import BadJson, json_body
from luxrocket.core import contracts
from luxrocket.core.errors import problem
from luxrocket.gaming import sessions
from luxrocket.gaming.models import Bet, GameRound, GameSession
from luxrocket.operators.models import IdempotencyRecord, Operator
from luxrocket.operators.signing import SignatureError, verify_request


def signed(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    @csrf_exempt
    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        try:
            verified = verify_request(
                method=request.method or "GET",
                path=request.get_full_path(),
                headers=request.headers,  # case-insensitive
                body=request.body,
            )
        except SignatureError as exc:
            return problem(exc.code, 401)
        return view(request, verified.operator, *args, **kwargs)

    return wrapper


def _idempotent(
    request: HttpRequest, operator: Operator, handler: Callable[[], tuple[int, dict[str, Any]]]
) -> HttpResponse:
    key = request.headers.get("Idempotency-Key", "")
    if not 8 <= len(key) <= 128:
        return problem("INVALID_REQUEST", 400, "Idempotency-Key header is required")
    request_hash = hashlib.sha256(request.body).hexdigest()
    previous = IdempotencyRecord.objects.filter(operator=operator, key=key).first()
    if previous is not None:
        if previous.request_hash != request_hash:
            return problem("IDEMPOTENCY_KEY_REUSED", 409)
        return JsonResponse(previous.response_body, status=previous.response_status)
    status, body = handler()
    if status < 500:
        try:
            with transaction.atomic():
                IdempotencyRecord.objects.create(
                    operator=operator,
                    key=key,
                    request_hash=request_hash,
                    response_status=status,
                    response_body=body,
                )
        except IntegrityError:
            previous = IdempotencyRecord.objects.get(operator=operator, key=key)
            return JsonResponse(previous.response_body, status=previous.response_status)
    return JsonResponse(body, status=status)


@require_http_methods(["POST"])
@signed
def create_session(request: HttpRequest, operator: Operator) -> HttpResponse:
    try:
        payload = json_body(request)
    except BadJson:
        return problem("INVALID_REQUEST", 400, "Body must be JSON")
    errs = contracts.errors("operator/v1/session-create.request.schema.json", payload)
    if errs:
        return problem("INVALID_REQUEST", 400, errors=errs)

    def handle() -> tuple[int, dict[str, Any]]:
        try:
            created = sessions.create_session(operator, payload)
        except sessions.SessionError as exc:
            return exc.status, {"code": exc.code, "status": exc.status}
        query = urlencode({"op": operator.public_id, "lang": created.session.locale})
        base = f"{settings.PLAY_BASE_URL}/launch?{query}"
        return 201, {
            "session_id": created.session.public_id,
            "launch_token": created.launch_token,
            "launch_token_expires_at": created.expires_at.isoformat().replace("+00:00", "Z"),
            "iframe_url": base,
            "fragment_launch_url": f"{base}#lt={created.launch_token}",
        }

    return _idempotent(request, operator, handle)


@require_http_methods(["POST"])
@signed
def revoke_session(request: HttpRequest, operator: Operator, session_id: str) -> HttpResponse:
    session = GameSession.objects.filter(operator=operator, public_id=session_id).first()
    if session is None:
        return problem("NOT_FOUND", 404)
    sessions.revoke(session, "OPERATOR_REVOKED")
    return JsonResponse({"session_id": session.public_id, "status": "REVOKED"})


@require_http_methods(["GET"])
@signed
def get_bet(request: HttpRequest, operator: Operator, bet_id: str) -> HttpResponse:
    bet = Bet.objects.filter(operator=operator, public_id=bet_id).select_related("player").first()
    if bet is None:
        return problem("NOT_FOUND", 404)
    return JsonResponse(bet_view(bet, include_player=True))


@require_http_methods(["GET"])
@signed
def get_round(request: HttpRequest, operator: Operator, round_id: str) -> HttpResponse:
    rnd = GameRound.objects.filter(pk=round_id).first() if _is_uuid(round_id) else None
    if rnd is None or rnd.state not in ("CRASHED", "VOIDED"):
        return problem("NOT_FOUND", 404)
    return JsonResponse(round_view(rnd))


def _is_uuid(value: str) -> bool:
    import uuid

    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def bet_view(bet: Bet, include_player: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "bet_id": bet.public_id,
        "round_id": str(bet.round_id),
        "panel": bet.panel,
        "currency": bet.currency,
        "stake": str(bet.stake_minor),
        "auto_cashout_x10000": bet.auto_cashout_x10000,
        "status": bet.status,
        "cashout_x10000": bet.cashout_x10000,
        "payout": str(bet.payout_minor) if bet.payout_minor is not None else None,
        "created_at": bet.created_at.isoformat(),
        "transactions": [
            {
                "transaction_id": f"tx_{t.id.hex}",
                "type": t.type,
                "amount": str(t.amount_minor),
                "status": t.status,
            }
            for t in bet.transactions.order_by("created_at")
        ],
    }
    if include_player:
        out["player_id"] = bet.player.external_player_id
    return out


def round_view(rnd: GameRound) -> dict[str, Any]:
    return {
        "round_id": str(rnd.id),
        "number": rnd.number,
        "state": rnd.state,
        "crash_x10000": rnd.crash_x10000,
        "end_reason": rnd.end_reason,
        "commitment": rnd.commitment,
        "seed": rnd.seed_hex,
        "salt": rnd.salt_hex,
        "house_edge_bp": rnd.house_edge_bp,
        "max_multiplier_x10000": rnd.max_multiplier_x10000,
        "formula_version": "LR-CRASH-1",
        "outcome_verified": rnd.outcome_verified,
    }


_ = json  # json kept for future streaming responses
