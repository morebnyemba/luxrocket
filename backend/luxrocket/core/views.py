from django.db import connection
from django.http import HttpRequest, JsonResponse


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
