"""RFC 9457 problem responses with a closed set of codes (doc 05 §8)."""

from django.http import JsonResponse


def problem(code: str, status: int, detail: str = "", **extra: object) -> JsonResponse:
    body: dict[str, object] = {
        "type": f"https://docs.luxrocket.example/errors/{code}",
        "title": code.replace("_", " ").capitalize(),
        "status": status,
        "code": code,
    }
    if detail:
        body["detail"] = detail
    body.update(extra)
    return JsonResponse(body, status=status, content_type="application/problem+json")
