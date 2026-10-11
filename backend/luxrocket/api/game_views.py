"""Game API /game/v1 — called by the embedded game with an in-memory bearer token (doc 05 §2.1)."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from luxrocket.api.http import BadJson, bearer, json_body
from luxrocket.api.operator_views import bet_view, round_view
from luxrocket.core.errors import problem
from luxrocket.gaming import sessions
from luxrocket.gaming.models import Bet, GameRound, GameSession
from luxrocket.wallet.models import SandboxWalletAccount


def authenticated(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    @csrf_exempt
    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        try:
            session = sessions.authenticate(bearer(request))
        except sessions.SessionError as exc:
            return problem(exc.code, exc.status)
        return view(request, session, *args, **kwargs)

    return wrapper


def _balance(session: GameSession) -> str | None:
    if session.mode != "SANDBOX":
        return None
    acct = SandboxWalletAccount.objects.filter(
        operator=session.operator, player=session.player, currency=session.currency
    ).first()
    return str(acct.balance_minor) if acct else None


@csrf_exempt
@require_http_methods(["POST"])
def exchange(request: HttpRequest) -> HttpResponse:
    try:
        token = str(json_body(request).get("launch_token", ""))
    except BadJson:
        return problem("INVALID_REQUEST", 400)
    if not token:
        return problem("INVALID_REQUEST", 400)
    try:
        session, game_token = sessions.exchange_launch_token(token)
    except sessions.SessionError as exc:
        return problem(exc.code, exc.status)
    return JsonResponse(
        {
            "game_session_token": game_token,
            "session": sessions.session_view(session),
            "balance": _balance(session),
        }
    )


@require_http_methods(["POST"])
@authenticated
def renew(request: HttpRequest, session: GameSession) -> HttpResponse:
    return JsonResponse({"game_session_token": sessions.renew(session)})


@require_http_methods(["POST"])
@authenticated
def ws_ticket(request: HttpRequest, session: GameSession) -> HttpResponse:
    return JsonResponse({"ticket": sessions.issue_ws_ticket(session)})


@require_http_methods(["GET"])
@authenticated
def config(request: HttpRequest, session: GameSession) -> HttpResponse:
    return JsonResponse({"session": sessions.session_view(session), "balance": _balance(session)})


@require_http_methods(["GET"])
@authenticated
def my_bets(request: HttpRequest, session: GameSession) -> HttpResponse:
    bets = (
        Bet.objects.filter(operator=session.operator, player=session.player)
        .exclude(status=Bet.Status.PENDING_DEBIT)
        .order_by("-created_at")[:50]
    )
    return JsonResponse({"bets": [bet_view(b) for b in bets]})


@require_http_methods(["GET"])
@authenticated
def recent_rounds(request: HttpRequest, session: GameSession) -> HttpResponse:
    rounds = GameRound.objects.filter(stream_slug=session.stream_slug, state="CRASHED").order_by(
        "-number"
    )[:30]
    return JsonResponse(
        {
            "rounds": [
                {"round_id": str(r.id), "number": r.number, "crash_x10000": r.crash_x10000}
                for r in rounds
            ]
        }
    )


@require_http_methods(["GET"])
@authenticated
def verification(request: HttpRequest, session: GameSession, round_id: str) -> HttpResponse:
    rnd = GameRound.objects.filter(stream_slug=session.stream_slug, pk=round_id).first()
    if rnd is None or rnd.state not in ("CRASHED", "VOIDED"):
        return problem("NOT_FOUND", 404)
    return JsonResponse(round_view(rnd))
