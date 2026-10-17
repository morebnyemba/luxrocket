"""Outbox: platform events written in the business transaction, relayed to Phoenix (ADR-015)."""

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from luxrocket.wallet.models import OutboxEvent

log = logging.getLogger(__name__)


def emit(event_type: str, payload: dict[str, Any]) -> OutboxEvent:
    return OutboxEvent.objects.create(type=event_type, payload=payload)


def relay_once(batch_size: int = 200) -> int:
    """Publish unpublished events in order. At-least-once; Phoenix de-duplicates by event_id."""
    with transaction.atomic():
        events = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(published_at__isnull=True)
            .order_by("created_at", "event_id")[:batch_size]
        )
        if not events:
            return 0
        body = json.dumps(
            {
                "events": [
                    {"event_id": str(e.event_id), "type": e.type, "payload": e.payload}
                    for e in events
                ]
            }
        ).encode()
        request = urllib.request.Request(  # noqa: S310 - internal, configured URL
            f"{settings.REALTIME_INTERNAL_URL}/internal/v1/platform-events",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.INTERNAL_SERVICE_TOKEN}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310
                ok = 200 <= response.status < 300
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log.warning("outbox relay failed: %s", exc)
            ok = False
        ids = [e.event_id for e in events]
        if ok:
            OutboxEvent.objects.filter(event_id__in=ids).update(published_at=timezone.now())
            return len(ids)
        for e in events:
            OutboxEvent.objects.filter(event_id=e.event_id).update(attempts=e.attempts + 1)
        return 0
