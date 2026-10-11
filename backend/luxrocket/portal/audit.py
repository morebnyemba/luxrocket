"""Hash-chained audit log (doc 15 §4): any edit, deletion or reordering breaks the chain."""

import hashlib
import json
from typing import Any

from django.db import connection, transaction
from django.utils import timezone

from luxrocket.portal.models import AuditEvent

GENESIS = "0" * 64
_LOCK_KEY = 7_412_031  # advisory lock serialising appends (one chain)


def _canonical(fields: dict[str, Any]) -> bytes:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str).encode()


def _digest(prev_hash: str, fields: dict[str, Any]) -> str:
    return hashlib.sha256(prev_hash.encode() + _canonical(fields)).hexdigest()


def _fields(e: AuditEvent) -> dict[str, Any]:
    return {
        "at": e.at.isoformat(),
        "realm": e.realm,
        "operator_id": str(e.operator_id) if e.operator_id else None,
        "actor": e.actor,
        "action": e.action,
        "target": e.target,
        "data": e.data,
        "ip": e.ip,
    }


def record(
    *,
    realm: str,
    actor: str,
    action: str,
    operator_id: Any = None,
    target: str = "",
    data: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditEvent:
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", [_LOCK_KEY])
        last = AuditEvent.objects.order_by("-seq").only("hash").first()
        prev = last.hash if last else GENESIS
        event = AuditEvent(
            at=timezone.now(),
            realm=realm,
            operator_id=operator_id,
            actor=actor,
            action=action,
            target=target,
            data=data or {},
            ip=ip,
            prev_hash=prev,
        )
        event.hash = _digest(prev, _fields(event))
        event.save()
        return event


def verify_chain() -> tuple[bool, int | None]:
    """(ok, first broken seq). Run on a schedule and before the daily WORM anchor."""
    prev = GENESIS
    for e in AuditEvent.objects.order_by("seq").iterator():
        if e.prev_hash != prev or _digest(prev, _fields(e)) != e.hash:
            return False, e.seq
        prev = e.hash
    return True, None
