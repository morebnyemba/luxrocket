"""Validation against the shared JSON Schemas in /contracts (source of truth, ADR-001)."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.conf import settings
from jsonschema import Draft202012Validator, FormatChecker


@lru_cache(maxsize=32)
def validator(relative: str) -> Draft202012Validator:
    path = Path(settings.CONTRACTS_DIR) / relative
    return Draft202012Validator(json.loads(path.read_text()), format_checker=FormatChecker())


def errors(relative: str, document: Any) -> list[str]:
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '$'}: {e.message}"
        for e in validator(relative).iter_errors(document)
    ]
