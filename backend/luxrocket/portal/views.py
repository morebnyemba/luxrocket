"""Operator portal API /api/portal/v1 (doc 13). Every query is scoped to ctx.operator."""

import secrets
from datetime import timedelta
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from luxrocket.api.http import BadJson, json_body
from luxrocket.api.operator_views import bet_view
from luxrocket.core.errors import problem
from luxrocket.core.lr1 import b64url_decode, platform_public_keys
from luxrocket.gaming.models import Bet, GameRound
from luxrocket.operators.models import (
    OperatorCredential,
    WalletKind,
    WebhookDelivery,
    WebhookEndpoint,
)
from luxrocket.portal import audit, totp
from luxrocket.portal.auth import (
    LOCK_AFTER,
    LOCK_FOR,
    PERMISSIONS,
    REALM,
    STEP_UP,
    Ctx,
    clear_cookie,
    client_ip,
    portal_view,
    set_cookie,
    start_session,
)
from luxrocket.portal.models import AuditEvent, Role, StaffSession, StaffUser
from luxrocket.wallet.models import (
    Discrepancy,
    LedgerEntry,
    Settlement,
    WalletTransaction,
    WalletTxAttempt,
)

PAGE = 50
MIN_PASSWORD = 12


def _body(request: HttpRequest) -> dict[str, Any]:
    try:
        data = json_body(request)
    except BadJson:
        return {}
    return data if isinstance(data, dict) else {}


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


# ---- Authentication ------------------------------------------------------------------------


@csrf_exempt
@require_http_methods(["POST"])
def login(request: HttpRequest) -> HttpResponse:
    if request.headers.get("X-LR-Portal") != "1":
        return problem("CSRF_REJECTED", 403)
    data = _body(request)
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    now = timezone.now()
    user = StaffUser.objects.select_related("operator").filter(email=email).first()
    if user is not None and user.locked_until and user.locked_until > now:
        return problem("ACCOUNT_LOCKED", 429)
    if (
        user is None
        or user.status != StaffUser.Status.ACTIVE
        or not check_password(password, user.password_hash)
    ):
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= LOCK_AFTER:
                user.locked_until = now + LOCK_FOR
                user.failed_logins = 0
            user.save(update_fields=["failed_logins", "locked_until"])
            audit.record(
                realm=REALM,
                actor=email,
                action="auth.login_failed",
                operator_id=user.operator_id,
                ip=client_ip(request),
            )
        else:
            check_password(password, make_password("timing-equaliser"))  # constant-ish time
        return problem("INVALID_CREDENTIALS", 401)
    user.failed_logins = 0
    user.locked_until = None
    user.save(update_fields=["failed_logins", "locked_until"])
    token = start_session(request, user, mfa_pending=user.mfa_enabled)
    audit.record(
        realm=REALM,
        actor=email,
        action="auth.login",
        operator_id=user.operator_id,
        data={"mfa_pending": user.mfa_enabled},
        ip=client_ip(request),
    )
    response = JsonResponse(
        {"mfa_required": user.mfa_enabled, "must_change_password": user.must_change_password}
    )
    set_cookie(response, token)
    return response


def _check_code(ctx: Ctx, code: str) -> bool:
    user = ctx.user
    if not user.totp_secret_enc:
        return False
    step = totp.verify(totp.decrypt(user.totp_secret_enc), code, user.last_totp_step)
    if step is None:
        user.failed_logins += 1
        if user.failed_logins >= LOCK_AFTER:
            user.locked_until = timezone.now() + LOCK_FOR
            user.failed_logins = 0
            StaffSession.objects.filter(user=user, revoked_at__isnull=True).update(
                revoked_at=timezone.now()
            )
        user.save(update_fields=["failed_logins", "locked_until"])
        ctx.audit("auth.mfa_failed")
        return False
    user.last_totp_step = step
    user.failed_logins = 0
    user.save(update_fields=["last_totp_step", "failed_logins"])
    return True


@portal_view(methods=("POST",), allow_pending_mfa=True)
def mfa(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    """Second factor after the password, and step-up for sensitive actions."""
    if not ctx.user.mfa_enabled:
        return problem("MFA_NOT_ENROLLED", 409)
    if not _check_code(ctx, str(_body(request).get("code", ""))):
        return problem("INVALID_CODE", 401)
    ctx.session.mfa_pending = False
    ctx.session.mfa_at = timezone.now()
    ctx.session.save(update_fields=["mfa_pending", "mfa_at"])
    ctx.audit("auth.mfa_ok")
    return JsonResponse({"ok": True})


@portal_view(methods=("POST",), allow_pending_mfa=True)
def logout(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    ctx.session.revoked_at = timezone.now()
    ctx.session.save(update_fields=["revoked_at"])
    ctx.audit("auth.logout")
    response = JsonResponse({"ok": True})
    clear_cookie(response)
    return response


def _me(ctx: Ctx) -> dict[str, Any]:
    fresh = timezone.now() - timedelta(minutes=settings.PORTAL_STEP_UP_MINUTES)
    return {
        "email": ctx.user.email,
        "role": ctx.user.role,
        "mfa_enabled": ctx.user.mfa_enabled,
        "must_change_password": ctx.user.must_change_password,
        "step_up_valid": bool(ctx.session.mfa_at and ctx.session.mfa_at >= fresh),
        "permissions": sorted(p for p, roles in PERMISSIONS.items() if ctx.user.role in roles),
        "step_up_permissions": sorted(STEP_UP),
        "operator": {
            "id": ctx.operator.public_id,
            "name": ctx.operator.legal_name,
            "status": ctx.operator.status,
            "real_money_enabled": ctx.operator.real_money_enabled,
        },
    }


@portal_view(allow_password_change=True)
def me(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    return JsonResponse(_me(ctx))


@portal_view(methods=("POST",), allow_password_change=True)
def change_password(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    data = _body(request)
    if not check_password(str(data.get("current", "")), ctx.user.password_hash):
        return problem("INVALID_CREDENTIALS", 401)
    new = str(data.get("new", ""))
    if len(new) < MIN_PASSWORD or new == data.get("current"):
        return problem("WEAK_PASSWORD", 422, f"at least {MIN_PASSWORD} characters, and new")
    ctx.user.password_hash = make_password(new)
    ctx.user.must_change_password = False
    ctx.user.save(update_fields=["password_hash", "must_change_password"])
    # Other sessions die with the old password.
    StaffSession.objects.filter(user=ctx.user, revoked_at__isnull=True).exclude(
        pk=ctx.session.pk
    ).update(revoked_at=timezone.now())
    ctx.audit("auth.password_changed")
    return JsonResponse({"ok": True})


@portal_view(methods=("POST",), allow_password_change=True)
def mfa_setup(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    if ctx.user.mfa_enabled:
        return problem("MFA_ALREADY_ENABLED", 409)
    secret = totp.new_secret()
    ctx.user.totp_secret_enc = totp.encrypt(secret)
    ctx.user.last_totp_step = 0
    ctx.user.save(update_fields=["totp_secret_enc", "last_totp_step"])
    ctx.audit("auth.mfa_setup_started")
    # Shown exactly once (AC-OP-2); never returned again.
    return JsonResponse(
        {"secret": totp.b32(secret), "uri": totp.provisioning_uri(secret, ctx.user.email)}
    )


@portal_view(methods=("POST",), allow_password_change=True)
def mfa_enable(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    if ctx.user.mfa_enabled:
        return problem("MFA_ALREADY_ENABLED", 409)
    if not _check_code(ctx, str(_body(request).get("code", ""))):
        return problem("INVALID_CODE", 401)
    ctx.user.mfa_enabled = True
    ctx.user.save(update_fields=["mfa_enabled"])
    ctx.session.mfa_at = timezone.now()
    ctx.session.save(update_fields=["mfa_at"])
    ctx.audit("auth.mfa_enabled")
    return JsonResponse({"ok": True})


@portal_view(allow_password_change=True)
def my_sessions(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    rows = StaffSession.objects.filter(
        user=ctx.user, revoked_at__isnull=True, expires_at__gt=timezone.now()
    ).order_by("-created_at")
    return JsonResponse(
        {
            "sessions": [
                {
                    "id": str(s.id),
                    "current": s.pk == ctx.session.pk,
                    "created_at": _iso(s.created_at),
                    "last_seen_at": _iso(s.last_seen_at),
                    "ip": s.ip,
                    "user_agent": s.user_agent,
                }
                for s in rows
            ]
        }
    )


@portal_view(methods=("POST",), allow_password_change=True)
def revoke_my_session(request: HttpRequest, ctx: Ctx, session_id: str) -> HttpResponse:
    n = StaffSession.objects.filter(
        user=ctx.user, pk=_uuid_or_none(session_id), revoked_at__isnull=True
    ).update(revoked_at=timezone.now())
    if not n:
        return problem("NOT_FOUND", 404)
    ctx.audit("auth.session_revoked", session_id)
    return JsonResponse({"ok": True})


def _uuid_or_none(value: str) -> Any:
    import uuid

    try:
        return uuid.UUID(value)
    except ValueError:
        return None


# ---- Overview --------------------------------------------------------------------------------


@portal_view("overview.read")
def overview(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    hours = min(max(int(request.GET.get("hours", "24") or 24), 1), 24 * 31)
    since = timezone.now() - timedelta(hours=hours)
    op = ctx.operator

    settled = (
        Settlement.objects.filter(
            bet__operator=op,
            bet__created_at__gte=since,
            outcome__in=[Settlement.Outcome.WIN, Settlement.Outcome.LOSS],
        )
        .values("bet__currency")
        .annotate(
            turnover=Sum("bet__stake_minor"),
            payouts=Sum("payout_minor"),
            bets=Count("bet"),
            players=Count("bet__player", distinct=True),
        )
    )
    # GGR comes from the ledger, so reported totals equal ledger totals (AC-OP-5).
    ggr = dict(
        LedgerEntry.objects.filter(
            operator=op, bet__created_at__gte=since, account=LedgerEntry.Account.GAME_RESULT
        )
        .values_list("currency")
        .annotate(s=Sum("amount_minor"))
    )
    currencies = []
    for row in settled:
        ccy = row["bet__currency"]
        turnover = int(row["turnover"] or 0)
        payouts = int(row["payouts"] or 0)
        currencies.append(
            {
                "currency": ccy,
                "bets": row["bets"],
                "players": row["players"],
                "turnover": str(turnover),
                "payouts": str(payouts),
                "ggr": str(int(ggr.get(ccy, 0))),
                "rtp_bp": (payouts * 10000 // turnover) if turnover else None,
            }
        )

    attempts = list(
        WalletTxAttempt.objects.filter(transaction__operator=op, created_at__gte=since).values_list(
            "outcome", "latency_ms"
        )
    )
    latencies = sorted(lat for _, lat in attempts)
    answered = sum(1 for outcome, _ in attempts if outcome != "UNKNOWN")
    deliveries = WebhookDelivery.objects.filter(operator=op, created_at__gte=since)
    return JsonResponse(
        {
            "window_hours": hours,
            "currencies": currencies,
            "wallet": {
                "calls": len(attempts),
                "answered_rate_bp": (answered * 10000 // len(attempts)) if attempts else None,
                "p95_latency_ms": latencies[int(len(latencies) * 0.95) - 1] if latencies else None,
                "pending": WalletTransaction.objects.filter(
                    operator=op,
                    status__in=[WalletTransaction.Status.PENDING, WalletTransaction.Status.UNKNOWN],
                ).count(),
                "needs_attention": WalletTransaction.objects.filter(
                    operator=op, status=WalletTransaction.Status.NEEDS_ATTENTION
                ).count(),
            },
            "webhooks": {
                "delivered": deliveries.filter(status="DELIVERED").count(),
                "pending": deliveries.filter(status="PENDING").count(),
                "failed": deliveries.filter(status="FAILED").count(),
            },
            "open_discrepancies": Discrepancy.objects.filter(
                operator=op, status=Discrepancy.Status.OPEN
            ).count(),
        }
    )


# ---- Reports ---------------------------------------------------------------------------------


def _bet_row(bet: Bet, players: bool) -> dict[str, Any]:
    row = {
        "bet_id": bet.public_id,
        "round_id": str(bet.round_id),
        "panel": bet.panel,
        "currency": bet.currency,
        "stake": str(bet.stake_minor),
        "status": bet.status,
        "cashout_x10000": bet.cashout_x10000,
        "payout": str(bet.payout_minor) if bet.payout_minor is not None else None,
        "created_at": _iso(bet.created_at),
    }
    if players:
        row["player_id"] = bet.player.external_player_id
    return row


@portal_view("reports.read")
def bets(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    players = ctx.can("players.read")
    qs = (
        Bet.objects.filter(operator=ctx.operator)
        .select_related("player")
        .order_by("-created_at", "-id")
    )
    if (status := request.GET.get("status")) and status in Bet.Status.values:
        qs = qs.filter(status=status)
    if (rid := request.GET.get("round_id")) and _uuid_or_none(rid):
        qs = qs.filter(round_id=rid)
    if (player := request.GET.get("player_id")) is not None and player != "":
        if not players:
            return problem("FORBIDDEN", 403, "player-level detail requires a reporting role")
        qs = qs.filter(player__external_player_id=player)
    if before := request.GET.get("before"):
        anchor = Bet.objects.filter(operator=ctx.operator, public_id=before).first()
        if anchor is not None:
            qs = qs.filter(
                Q(created_at__lt=anchor.created_at)
                | Q(created_at=anchor.created_at, id__lt=anchor.id)
            )
    rows = list(qs[: PAGE + 1])
    return JsonResponse(
        {
            "bets": [_bet_row(b, players) for b in rows[:PAGE]],
            "next": rows[PAGE - 1].public_id if len(rows) > PAGE else None,
        }
    )


@portal_view("reports.read")
def bet_detail(request: HttpRequest, ctx: Ctx, bet_id: str) -> HttpResponse:
    bet = (
        Bet.objects.filter(operator=ctx.operator, public_id=bet_id).select_related("player").first()
    )
    if bet is None:
        return problem("NOT_FOUND", 404)
    out = bet_view(bet, include_player=ctx.can("players.read"))
    settlement = Settlement.objects.filter(bet=bet).first()
    out["settlement"] = (
        {
            "outcome": settlement.outcome,
            "status": settlement.status,
            "payout": str(settlement.payout_minor),
            "confirmed_at": _iso(settlement.confirmed_at),
        }
        if settlement
        else None
    )
    out["attempts"] = [
        {
            "type": a.transaction.type,
            "attempt": a.attempt_no,
            "outcome": a.outcome,
            "operator_code": a.operator_code,
            "latency_ms": a.latency_ms,
            "at": _iso(a.created_at),
        }
        for a in WalletTxAttempt.objects.filter(transaction__bet=bet)
        .select_related("transaction")
        .order_by("created_at")
    ]
    return JsonResponse(out)


@portal_view("reports.read")
def rounds(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    qs = GameRound.objects.filter(
        stream_slug=ctx.operator.stream_slug, state__in=["CRASHED", "VOIDED"]
    ).order_by("-number")
    if before := request.GET.get("before"):
        if before.isdigit():
            qs = qs.filter(number__lt=int(before))
    page = list(qs[: PAGE + 1])
    ids = [r.id for r in page[:PAGE]]
    mine: dict[Any, Any] = {
        row["round_id"]: row
        for row in Bet.objects.filter(operator=ctx.operator, round_id__in=ids)
        .values("round_id")
        .annotate(bets=Count("id"), stake=Sum("stake_minor"), payout=Sum("payout_minor"))
    }
    return JsonResponse(
        {
            "rounds": [
                {
                    "round_id": str(r.id),
                    "number": r.number,
                    "state": r.state,
                    "crash_x10000": r.crash_x10000,
                    "outcome_verified": r.outcome_verified,
                    "commitment": r.commitment,
                    "seed": r.seed_hex,
                    "settlement_status": r.settlement_status,
                    "your_bets": mine.get(r.id, {}).get("bets", 0),
                }
                for r in page[:PAGE]
            ],
            "next": str(page[PAGE - 1].number) if len(page) > PAGE else None,
        }
    )


@portal_view("reconciliation.read")
def discrepancies(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    qs = Discrepancy.objects.filter(operator=ctx.operator).order_by("-created_at")
    if (status := request.GET.get("status")) and status in Discrepancy.Status.values:
        qs = qs.filter(status=status)
    return JsonResponse(
        {
            "discrepancies": [
                {
                    "id": str(d.id),
                    "kind": d.kind,
                    "severity": d.severity,
                    "subject": d.subject,
                    "detail": d.detail,
                    "status": d.status,
                    "created_at": _iso(d.created_at),
                    "resolved_at": _iso(d.resolved_at),
                    "resolution_note": d.resolution_note,
                }
                for d in qs[:200]
            ]
        }
    )


# ---- Integration -----------------------------------------------------------------------------


def _credential(c: OperatorCredential) -> dict[str, Any]:
    return {
        "kid": c.kid,
        "algorithm": c.algorithm,
        "status": c.status,
        "created_at": _iso(c.created_at),
        "last_used_at": _iso(c.last_used_at),
    }


@portal_view("integration.read", methods=("GET", "POST"))
def credentials(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    if request.method == "POST":
        return _create_credential(request)
    rows = OperatorCredential.objects.filter(operator=ctx.operator).order_by("-created_at")
    return JsonResponse({"credentials": [_credential(c) for c in rows]})


@portal_view("credentials.manage", methods=("POST",))
def _create_credential(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    """Operator uploads the PUBLIC key; the private key never reaches us (ADR-010)."""
    raw_b64 = str(_body(request).get("public_key", ""))
    try:
        raw = b64url_decode(raw_b64)
        Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError, TypeError):
        return problem(
            "INVALID_REQUEST", 422, "public_key must be base64url raw Ed25519 (32 bytes)"
        )
    with transaction.atomic():
        active = OperatorCredential.objects.select_for_update().filter(
            operator=ctx.operator, status=OperatorCredential.Status.ACTIVE
        )
        if active.count() >= 2:
            return problem("CREDENTIAL_LIMIT", 409, "revoke a key first (max two active)")
        cred = OperatorCredential.objects.create(
            operator=ctx.operator,
            kid=f"k_{ctx.operator.public_id[-8:]}_{secrets.token_hex(4)}",
            public_key=raw,
        )
    ctx.audit("credential.created", cred.kid)
    return JsonResponse(_credential(cred), status=201)


@portal_view("credentials.manage", methods=("POST",))
def revoke_credential(request: HttpRequest, ctx: Ctx, kid: str) -> HttpResponse:
    with transaction.atomic():
        cred = (
            OperatorCredential.objects.select_for_update()
            .filter(operator=ctx.operator, kid=kid, status=OperatorCredential.Status.ACTIVE)
            .first()
        )
        if cred is None:
            return problem("NOT_FOUND", 404)
        others = OperatorCredential.objects.filter(
            operator=ctx.operator, status=OperatorCredential.Status.ACTIVE
        ).exclude(pk=cred.pk)
        if not others.exists():
            return problem("LAST_ACTIVE_KEY", 409, "add the replacement key first")
        cred.status = OperatorCredential.Status.REVOKED
        cred.save(update_fields=["status"])
    ctx.audit("credential.revoked", kid)
    return JsonResponse(_credential(cred))


def _wallet(ctx: Ctx) -> dict[str, Any]:
    op = ctx.operator
    return {
        "wallet_kind": op.wallet_kind,
        "base_url": op.wallet_base_url,
        "debit_timeout_ms": op.wallet_debit_timeout_ms,
        "debit_timeout_max_ms": settings.WALLET_DEBIT_TIMEOUT_MAX_MS,
        "platform_keys": platform_public_keys(),
    }


@portal_view("integration.read", methods=("GET", "PUT"))
def wallet(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    if request.method == "PUT":
        return _update_wallet(request)
    return JsonResponse(_wallet(ctx))


@portal_view("wallet.manage", methods=("PUT",))
def _update_wallet(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    data = _body(request)
    op = ctx.operator
    before = {
        "kind": op.wallet_kind,
        "url": op.wallet_base_url,
        "timeout": op.wallet_debit_timeout_ms,
    }
    try:
        timeout = int(data.get("debit_timeout_ms", op.wallet_debit_timeout_ms))
    except (TypeError, ValueError):
        return problem("INVALID_REQUEST", 422)
    if not 100 <= timeout <= settings.WALLET_DEBIT_TIMEOUT_MAX_MS:
        return problem("CONFIG_NOT_PERMITTED", 422, "debit timeout out of platform bounds")
    url = str(data.get("base_url", "")).strip()
    if url:
        op.wallet_kind = WalletKind.SEAMLESS_V1
        op.wallet_base_url = url
    elif op.real_money_enabled:
        return problem("CONFIG_NOT_PERMITTED", 422, "real-money operators need a wallet URL")
    else:
        op.wallet_kind = WalletKind.SIMULATED
        op.wallet_base_url = ""
    op.wallet_debit_timeout_ms = timeout
    try:
        op.clean()
    except ValidationError as exc:
        return problem("CONFIG_NOT_PERMITTED", 422, "; ".join(exc.messages))
    op.save(update_fields=["wallet_kind", "wallet_base_url", "wallet_debit_timeout_ms"])
    ctx.audit(
        "wallet.updated",
        op.public_id,
        before=before,
        after={"kind": op.wallet_kind, "url": op.wallet_base_url, "timeout": timeout},
    )
    return JsonResponse(_wallet(ctx))


@portal_view("wallet.manage", methods=("POST",))
def wallet_conformance(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    from luxrocket.wallet import conformance

    if ctx.operator.wallet_kind != WalletKind.SEAMLESS_V1:
        return problem("WALLET_NOT_CONFIGURED", 409)
    player = str(_body(request).get("player_id", "")).strip()
    if not player:
        return problem("INVALID_REQUEST", 422, "a dedicated test player_id is required")
    report = conformance.run(
        ctx.operator.wallet_base_url, player_id=player, currency="USD", timeout_ms=3000
    )
    ctx.audit("wallet.conformance_run", player, passed=report.passed)
    return JsonResponse(
        {
            "passed": report.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "required": c.required, "detail": c.detail}
                for c in report.checks
            ],
        }
    )


def _endpoint(e: WebhookEndpoint) -> dict[str, Any]:
    return {"id": str(e.id), "url": e.url, "enabled": e.enabled, "created_at": _iso(e.created_at)}


@portal_view("integration.read", methods=("GET", "POST"))
def webhooks(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    if request.method == "POST":
        return _create_webhook(request)
    rows = WebhookEndpoint.objects.filter(operator=ctx.operator).order_by("-created_at")
    return JsonResponse({"webhooks": [_endpoint(e) for e in rows]})


@portal_view("webhooks.manage", methods=("POST",))
def _create_webhook(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    url = str(_body(request).get("url", "")).strip()
    endpoint = WebhookEndpoint(operator=ctx.operator, url=url)
    try:
        endpoint.clean()
    except ValidationError as exc:
        return problem("INVALID_REQUEST", 422, "; ".join(exc.messages))
    endpoint, _ = WebhookEndpoint.objects.update_or_create(
        operator=ctx.operator, url=url, defaults={"enabled": True}
    )
    ctx.audit("webhook.enabled", url)
    return JsonResponse(_endpoint(endpoint), status=201)


@portal_view("webhooks.manage", methods=("POST",))
def disable_webhook(request: HttpRequest, ctx: Ctx, endpoint_id: str) -> HttpResponse:
    endpoint = WebhookEndpoint.objects.filter(
        operator=ctx.operator, pk=_uuid_or_none(endpoint_id)
    ).first()
    if endpoint is None:
        return problem("NOT_FOUND", 404)
    endpoint.enabled = False
    endpoint.save(update_fields=["enabled"])
    ctx.audit("webhook.disabled", endpoint.url)
    return JsonResponse(_endpoint(endpoint))


@portal_view("integration.read")
def webhook_deliveries(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    qs = WebhookDelivery.objects.filter(operator=ctx.operator).order_by("-created_at")
    if (status := request.GET.get("status")) and status in WebhookDelivery.Status.values:
        qs = qs.filter(status=status)
    return JsonResponse(
        {
            "deliveries": [
                {
                    "id": str(d.id),
                    "event_id": d.event_id,
                    "type": d.type,
                    "status": d.status,
                    "attempts": d.attempts,
                    "last_status_code": d.last_status_code,
                    "last_error": d.last_error,
                    "created_at": _iso(d.created_at),
                    "delivered_at": _iso(d.delivered_at),
                }
                for d in qs[:200]
            ]
        }
    )


@portal_view("webhooks.manage", methods=("POST",))
def replay_delivery(request: HttpRequest, ctx: Ctx, delivery_id: str) -> HttpResponse:
    n = WebhookDelivery.objects.filter(operator=ctx.operator, pk=_uuid_or_none(delivery_id)).update(
        status=WebhookDelivery.Status.PENDING, next_attempt_at=timezone.now()
    )
    if not n:
        return problem("NOT_FOUND", 404)
    ctx.audit("webhook.replayed", delivery_id)
    return JsonResponse({"ok": True})


# ---- Team ------------------------------------------------------------------------------------


def _user(u: StaffUser) -> dict[str, Any]:
    return {
        "id": str(u.id),
        "email": u.email,
        "role": u.role,
        "status": u.status,
        "mfa_enabled": u.mfa_enabled,
        "created_at": _iso(u.created_at),
    }


def _may_manage(ctx: Ctx, role: str) -> bool:
    """Admins manage everyone except owners, and cannot mint owners."""
    return ctx.user.role == Role.OWNER or role != Role.OWNER


@portal_view("users.manage", methods=("GET", "POST"))
def users(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    if request.method == "GET":
        rows = StaffUser.objects.filter(operator=ctx.operator).order_by("email")
        return JsonResponse({"users": [_user(u) for u in rows]})
    data = _body(request)
    email = str(data.get("email", "")).strip().lower()
    role = str(data.get("role", ""))
    if role not in Role.values or "@" not in email:
        return problem("INVALID_REQUEST", 422)
    if not _may_manage(ctx, role):
        return problem("FORBIDDEN", 403)
    if StaffUser.objects.filter(email=email).exists():
        return problem("ALREADY_EXISTS", 409)
    temporary = secrets.token_urlsafe(12)
    user = StaffUser.objects.create(
        operator=ctx.operator,
        email=email,
        role=role,
        password_hash=make_password(temporary),
        must_change_password=True,
    )
    ctx.audit("user.created", email, role=role)
    # The temporary password is shown exactly once (AC-OP-2).
    return JsonResponse(_user(user) | {"temporary_password": temporary}, status=201)


@portal_view("users.manage", methods=("PATCH",))
def update_user(request: HttpRequest, ctx: Ctx, user_id: str) -> HttpResponse:
    user = StaffUser.objects.filter(operator=ctx.operator, pk=_uuid_or_none(user_id)).first()
    if user is None:
        return problem("NOT_FOUND", 404)
    if user.pk == ctx.user.pk:
        return problem("FORBIDDEN", 403, "you cannot change your own role or status")
    data = _body(request)
    role = data.get("role", user.role)
    status = data.get("status", user.status)
    if role not in Role.values or status not in StaffUser.Status.values:
        return problem("INVALID_REQUEST", 422)
    if not (_may_manage(ctx, user.role) and _may_manage(ctx, role)):
        return problem("FORBIDDEN", 403)
    if user.role == Role.OWNER and (role != Role.OWNER or status != StaffUser.Status.ACTIVE):
        remaining = StaffUser.objects.filter(
            operator=ctx.operator, role=Role.OWNER, status=StaffUser.Status.ACTIVE
        ).exclude(pk=user.pk)
        if not remaining.exists():
            return problem("LAST_OWNER", 409)
    before = {"role": user.role, "status": user.status}
    user.role = role
    user.status = status
    user.save(update_fields=["role", "status"])
    if status != StaffUser.Status.ACTIVE:
        StaffSession.objects.filter(user=user, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
    ctx.audit("user.updated", user.email, before=before, after={"role": role, "status": status})
    return JsonResponse(_user(user))


@portal_view("users.manage", methods=("POST",))
def reset_user_mfa(request: HttpRequest, ctx: Ctx, user_id: str) -> HttpResponse:
    user = StaffUser.objects.filter(operator=ctx.operator, pk=_uuid_or_none(user_id)).first()
    if user is None:
        return problem("NOT_FOUND", 404)
    if user.pk == ctx.user.pk or not _may_manage(ctx, user.role):
        return problem("FORBIDDEN", 403)
    user.mfa_enabled = False
    user.totp_secret_enc = None
    user.save(update_fields=["mfa_enabled", "totp_secret_enc"])
    StaffSession.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    ctx.audit("user.mfa_reset", user.email)
    return JsonResponse(_user(user))


@portal_view("audit.read")
def audit_log(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    qs = AuditEvent.objects.filter(operator=ctx.operator).order_by("-seq")
    if (before := request.GET.get("before", "")).isdigit():
        qs = qs.filter(seq__lt=int(before))
    rows = list(qs[: PAGE + 1])
    return JsonResponse(
        {
            "events": [
                {
                    "seq": e.seq,
                    "at": _iso(e.at),
                    "actor": e.actor,
                    "action": e.action,
                    "target": e.target,
                    "data": e.data,
                    "ip": e.ip,
                    "hash": e.hash,
                }
                for e in rows[:PAGE]
            ],
            "next": str(rows[PAGE - 1].seq) if len(rows) > PAGE else None,
        }
    )
