"""Service-to-service authentication for the internal API (doc 06 §8).

Interim: a shared bearer token per direction, compared in constant time. Production adds mTLS
on the private network (doc 15 §3).
"""

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.conf import settings
from django.http import HttpRequest, JsonResponse

from luxrocket.core.tokens import constant_time_equal


def require_service_token(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        header = request.headers.get("Authorization", "")
        expected = settings.INTERNAL_SERVICE_TOKEN
        if not header.startswith("Bearer ") or not constant_time_equal(header[7:], expected):
            return JsonResponse({"code": "UNAUTHORIZED"}, status=401)
        return view(request, *args, **kwargs)

    return wrapper
