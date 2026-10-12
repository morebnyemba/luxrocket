"""Operator webhooks: transactional outbox + signed at-least-once delivery (doc 09 §7).

`emit` writes one delivery row per enabled endpoint inside the caller's transaction, so an
event exists if and only if the state change that caused it committed. `deliver_due` POSTs
them LR1-signed with the platform key; any 2xx is delivered, anything else is retried on the
documented schedule and finally marked FAILED (visible in the back-office). Consumers dedupe
by `event_id`.
"""

import json
import logging
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from luxrocket.core import contracts
from luxrocket.core.ids import public_id, tx_public_id
from luxrocket.core.lr1 import platform_sign_headers
from luxrocket.operators.models import Operator, WebhookDelivery, WebhookEndpoint

log = logging.getLogger(__name__)

SCHEMA = "operator/v1/webhook.schema.json"
# Retry delays after each failed attempt (doc 09 §7); one more failure after the last is final.
RETRY = [60, 300, 900, 3600, 21600, 86400]
CLAIM_SECONDS = 60  # a claimed delivery is invisible to other workers for this long


def event_id_for(type_: str, subject: str, operator_pk: Any) -> str:
    """Deterministic: the same fact can never become two events, however often it is emitted."""
    return public_id(
        "evt", uuid.uuid5(uuid.NAMESPACE_URL, f"luxrocket:evt:{type_}:{subject}:{operator_pk}")
    )


def emit(operator: Any, type_: str, subject: str, data: dict[str, Any]) -> str | None:
    """Queue an event for every enabled endpoint of the operator. Returns the event id."""
    endpoints = list(WebhookEndpoint.objects.filter(operator_id=operator.pk, enabled=True))
    if not endpoints:
        return None
    event_id = event_id_for(type_, subject, operator.pk)
    payload = {
        "event_id": event_id,
        "type": type_,
        "occurred_at": timezone.now().isoformat(),
        "operator_id": operator.public_id,
        "api_version": "v1",
        "data": data,
    }
    errs = contracts.errors(SCHEMA, payload)
    if errs:  # a bug on our side: never send operators a non-conforming event
        raise ValueError(f"webhook {type_} violates contract: {errs}")
    now = timezone.now()
    WebhookDelivery.objects.bulk_create(
        (
            WebhookDelivery(
                event_id=event_id,
                endpoint=ep,
                operator_id=operator.pk,
                type=type_,
                payload=payload,
                next_attempt_at=now,
            )
            for ep in endpoints
        ),
        ignore_conflicts=True,  # re-emission of the same fact
    )
    return event_id


# ---- Event builders --------------------------------------------------------------------------


def _transaction(t: Any) -> dict[str, str]:
    return {
        "transaction_id": tx_public_id(t.id),
        "type": t.type,
        "amount": str(t.amount_minor),
        "status": t.status,
    }


def bet_settled(bet: Any, settlement: Any) -> None:
    payout = settlement.payout_minor
    if settlement.outcome == "REFUND":
        payout = bet.stake_minor
    emit(
        bet.operator,
        "bet.settled",
        bet.public_id,
        {
            "bet_id": bet.public_id,
            "round_id": str(bet.round_id),
            "player_id": bet.player.external_player_id,
            "panel": bet.panel,
            "currency": bet.currency,
            "stake": str(bet.stake_minor),
            "outcome": settlement.outcome,
            "multiplier_x10000": settlement.multiplier_x10000,
            "payout": str(payout),
            "transactions": [_transaction(t) for t in bet.transactions.order_by("created_at")],
        },
    )


def transaction_needs_attention(tx: Any) -> None:
    bet = tx.bet
    emit(
        bet.operator,
        "transaction.needs_attention",
        str(tx.id),
        {
            "transaction": _transaction(tx),
            "bet_id": bet.public_id,
            "player_id": bet.player.external_player_id,
            "currency": tx.currency,
            "operator_code": tx.operator_code,
        },
    )


def round_settled(rnd: Any) -> None:
    """One event per operator that had settled bets in the round, with that operator's totals."""
    from luxrocket.wallet.models import Settlement

    rows = (
        Settlement.objects.filter(bet__round_id=rnd.id)
        .values("bet__operator_id", "bet__currency", "outcome")
        .annotate(stake=Sum("bet__stake_minor"), payout=Sum("payout_minor"))
    )
    per_op: dict[Any, dict[str, Any]] = {}
    for r in rows:
        op = per_op.setdefault(r["bet__operator_id"], {"bets": 0, "totals": {}})
        tot = op["totals"].setdefault(r["bet__currency"], {"stake": 0, "payout": 0})
        tot["stake"] += r["stake"] or 0
        # Refunds return the stake: count them as paid back so stake - payout is the result.
        tot["payout"] += (r["stake"] or 0) if r["outcome"] == "REFUND" else (r["payout"] or 0)
    counts = (
        Settlement.objects.filter(bet__round_id=rnd.id)
        .values("bet__operator_id")
        .annotate(n=Count("bet"))
    )
    for c in counts:
        per_op[c["bet__operator_id"]]["bets"] = c["n"]
    for operator in Operator.objects.filter(pk__in=per_op):
        agg = per_op[operator.pk]
        emit(
            operator,
            "round.settled",
            str(rnd.id),
            {
                "round_id": str(rnd.id),
                "end_state": rnd.state,
                "crash_x10000": rnd.crash_x10000,
                "bets": agg["bets"],
                "totals": [
                    {"currency": ccy, "stake": str(t["stake"]), "payout": str(t["payout"])}
                    for ccy, t in sorted(agg["totals"].items())
                ],
            },
        )


# ---- Delivery --------------------------------------------------------------------------------

_client: httpx.Client | None = None


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            follow_redirects=False, headers={"User-Agent": "luxrocket-webhooks/1"}
        )
    return _client


def deliver_due(limit: int = 50) -> int:
    """Claim due deliveries (skip-locked, short lease) and send them outside any transaction."""
    now = timezone.now()
    with transaction.atomic():
        ids = list(
            WebhookDelivery.objects.select_for_update(skip_locked=True)
            .filter(status=WebhookDelivery.Status.PENDING, next_attempt_at__lte=now)
            .order_by("next_attempt_at")
            .values_list("id", flat=True)[:limit]
        )
        WebhookDelivery.objects.filter(id__in=ids).update(
            next_attempt_at=now + timedelta(seconds=CLAIM_SECONDS)
        )
    delivered = 0
    for d in WebhookDelivery.objects.select_related("endpoint").filter(id__in=ids):
        delivered += _send(d)
    return delivered


def _send(d: WebhookDelivery) -> int:
    body = json.dumps(d.payload, separators=(",", ":"), sort_keys=True).encode()
    url = d.endpoint.url
    code: int | None = None
    error = ""
    try:
        headers = {
            "Content-Type": "application/json",
            "LR-Event-Id": d.event_id,
            "LR-Event-Type": d.type,
            **platform_sign_headers("POST", urlsplit(url).path or "/", body),
        }
        resp = _http().post(
            url, content=body, headers=headers, timeout=settings.WEBHOOK_TIMEOUT_MS / 1000
        )
        code = resp.status_code
        ok = 200 <= code < 300
        if not ok:
            error = f"HTTP {code}"
    except httpx.HTTPError as exc:
        ok = False
        error = type(exc).__name__

    d.attempts += 1
    d.last_status_code = code
    d.last_error = error[:200]
    if ok:
        d.status = WebhookDelivery.Status.DELIVERED
        d.delivered_at = timezone.now()
    elif d.attempts > len(RETRY):
        d.status = WebhookDelivery.Status.FAILED
        log.error("webhook %s to %s failed permanently: %s", d.event_id, url, error)
    else:
        d.next_attempt_at = timezone.now() + timedelta(seconds=RETRY[d.attempts - 1])
    d.save(
        update_fields=[
            "attempts",
            "last_status_code",
            "last_error",
            "status",
            "delivered_at",
            "next_attempt_at",
        ]
    )
    return 1 if ok else 0
