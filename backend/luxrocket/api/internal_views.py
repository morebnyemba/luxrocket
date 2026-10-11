"""Internal API /internal/v1 — Phoenix only, private network, service token (doc 05 §2.2)."""

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from luxrocket.api.http import BadJson, json_body
from luxrocket.core.errors import problem
from luxrocket.core.service_auth import require_service_token
from luxrocket.gaming import betting, journal, sessions
from luxrocket.gaming.models import GameSession
from luxrocket.wallet import worker


@csrf_exempt
@require_http_methods(["POST"])
@require_service_token
def consume_ws_ticket(request: HttpRequest) -> HttpResponse:
    try:
        ticket = str(json_body(request).get("ticket", ""))
    except BadJson:
        return problem("INVALID_REQUEST", 400)
    try:
        session = sessions.consume_ws_ticket(ticket)
    except sessions.SessionError as exc:
        return problem(exc.code, exc.status)
    return JsonResponse({"session": sessions.session_view(session)})


@require_http_methods(["GET"])
@require_service_token
def session_status(request: HttpRequest, session_id: str) -> HttpResponse:
    session = GameSession.objects.filter(public_id=session_id).first()
    if session is None:
        return problem("NOT_FOUND", 404)
    return JsonResponse(
        {
            "session_id": session.public_id,
            "active": sessions.is_active(session),
            "session_version": session.session_version,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
@require_service_token
def place_bet(request: HttpRequest) -> HttpResponse:
    try:
        payload = json_body(request)
    except BadJson:
        return problem("INVALID_REQUEST", 400)
    return JsonResponse(betting.place_bet(payload).as_dict())


@csrf_exempt
@require_http_methods(["POST"])
@require_service_token
def rt_events(request: HttpRequest) -> HttpResponse:
    try:
        events = json_body(request).get("events", [])
    except BadJson:
        return problem("INVALID_REQUEST", 400)
    result = journal.apply_batch(events)
    # Best-effort immediate settlement; the worker loop retries anything left over.
    worker.process_pending(limit=200)
    body = {"applied": result.applied, "skipped": result.skipped}
    if result.expected_seq is not None:
        return JsonResponse({**body, "expected_seq": result.expected_seq}, status=409)
    return JsonResponse(body)
