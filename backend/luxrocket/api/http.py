"""Small JSON helpers shared by the API views."""

import json
from typing import Any

from django.http import HttpRequest


class BadJson(Exception):
    pass


def json_body(request: HttpRequest) -> Any:
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise BadJson from exc


def bearer(request: HttpRequest) -> str:
    header = request.headers.get("Authorization", "")
    return header[7:] if header.startswith("Bearer ") else ""
