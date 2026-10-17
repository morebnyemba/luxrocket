"""CORS for the Game API: exactly the play origin, no credentials (doc 11 §1)."""

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse


class GameApiCorsMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        is_game_api = request.path.startswith("/game/")
        origin = request.headers.get("Origin")
        allowed = is_game_api and origin == settings.GAME_ORIGIN
        if is_game_api and request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        if allowed:
            response["Access-Control-Allow-Origin"] = origin  # type: ignore[assignment]
            response["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response["Access-Control-Max-Age"] = "600"
            response["Vary"] = "Origin"
        return response
