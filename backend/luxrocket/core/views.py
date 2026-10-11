from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods


def healthz(request: HttpRequest) -> JsonResponse:
    """Liveness + database reachability. Contains no sensitive detail."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    return JsonResponse(
        {"status": "ok" if db_ok else "degraded", "db": db_ok}, status=200 if db_ok else 503
    )


@require_http_methods(["GET"])
def platform_keys(request: HttpRequest) -> HttpResponse:
    """Public keys operators use to verify our wallet calls and webhooks (doc 09 §3)."""
    from luxrocket.core.lr1 import platform_public_keys

    resp = JsonResponse({"keys": platform_public_keys()})
    resp["Cache-Control"] = "public, max-age=300"
    return resp
