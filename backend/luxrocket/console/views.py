"""Platform admin API /api/admin/v1 (doc 12). No route writes rt.* or any round outcome."""

import os
import secrets
import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import connection, transaction
from django.db.models import Count, Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from luxrocket.api.http import BadJson, json_body
from luxrocket.api.operator_views import bet_view
from luxrocket.console import passkeys
from luxrocket.console.auth import (
    LOCK_AFTER,
    LOCK_FOR,
    PERMISSIONS,
    REALM,
    STEP_UP,
    SUPERADMIN_CAP,
    Ctx,
    clear_cookie,
    console_view,
    same_admin_origin,
    set_cookie,
    start_session,
    step_up_fresh,
)
from luxrocket.console.models import (
    ApprovalRequest,
    Passkey,
    PlatformSession,
    PlatformStaff,
    Role,
)
from luxrocket.core.errors import problem
from luxrocket.core.ids import parse_public_id, tx_public_id
from luxrocket.gaming import fairness, rulesets
from luxrocket.gaming.models import Bet, GameRound, GameRuleset, GameSession, StreamConfig
from luxrocket.operators.models import (
    Market,
    Operator,
    OperatorCredential,
    OperatorCurrencyLimit,
    OperatorJurisdiction,
    WalletKind,
)
from luxrocket.portal import audit
from luxrocket.portal.auth import client_ip
from luxrocket.portal.models import AuditEvent, StaffUser
from luxrocket.portal.models import Role as OperatorRole
from luxrocket.wallet.models import (
    Discrepancy,
    LedgerEntry,
    Settlement,
    WalletTransaction,
    WalletTxAttempt,
)
from luxrocket.wallet.outbox import emit

S = PlatformSession.Stage
PAGE = 50
MIN_PASSWORD = 14


def _body(request: HttpRequest) -> dict[str, Any]:
    try:
        data = json_body(request)
    except BadJson:
        return {}
    return data if isinstance(data, dict) else {}


def _iso(v: Any) -> str | None:
    return v.isoformat() if v else None


NIL = uuid.UUID(int=0)


def _uuid(v: str) -> uuid.UUID:
    """Malformed ids become the nil UUID, which never matches a row (-> 404)."""
    try:
        return uuid.UUID(v)
    except ValueError:
        return NIL


# ---- Authentication ------------------------------------------------------------------------


@csrf_exempt
@require_http_methods(["POST"])
def login(request: HttpRequest) -> HttpResponse:
    if not same_admin_origin(request):
        return problem("CSRF_REJECTED", 403)
    data = _body(request)
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    now = timezone.now()
    staff = PlatformStaff.objects.filter(email=email).first()
    if staff is not None and staff.locked_until and staff.locked_until > now:
        return problem("ACCOUNT_LOCKED", 429)
    if (
        staff is None
        or staff.status != PlatformStaff.Status.ACTIVE
        or not check_password(password, staff.password_hash)
    ):
        if staff is not None:
            staff.failed_logins += 1
            if staff.failed_logins >= LOCK_AFTER:
                staff.locked_until = now + LOCK_FOR
                staff.failed_logins = 0
            staff.save(update_fields=["failed_logins", "locked_until"])
            audit.record(
                realm=REALM, actor=email, action="auth.login_failed", ip=client_ip(request)
            )
        else:
            check_password(password, make_password("timing-equaliser"))
        return problem("INVALID_CREDENTIALS", 401)
    staff.failed_logins = 0
    staff.locked_until = None
    staff.save(update_fields=["failed_logins", "locked_until"])
    has_passkey = Passkey.objects.filter(staff=staff).exists()
    stage = S.PASSKEY if has_passkey else S.ENROLL
    token = start_session(request, staff, stage)
    audit.record(
        realm=REALM,
        actor=email,
        action="auth.password_ok",
        data={"next": stage},
        ip=client_ip(request),
    )
    response = JsonResponse({"next": "passkey" if has_passkey else "enroll"})
    set_cookie(response, token)
    return response


@console_view(methods=("POST",), stages=(S.PASSKEY, S.FULL))
def passkey_options(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    return JsonResponse(passkeys.authentication_options(ctx.session))


@console_view(methods=("POST",), stages=(S.PASSKEY, S.FULL))
def passkey_verify(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    try:
        key = passkeys.authenticate(ctx.session, _body(request).get("credential") or {})
    except passkeys.PasskeyError as exc:
        ctx.audit("auth.passkey_failed")
        return problem(str(exc), 401)
    PlatformSession.objects.filter(pk=ctx.session.pk).update(stage=S.FULL, mfa_at=timezone.now())
    ctx.audit("auth.passkey_ok", key.name)
    return JsonResponse({"ok": True, "must_change_password": ctx.staff.must_change_password})


@console_view(methods=("POST",), stages=(S.ENROLL, S.FULL), allow_password_change=True)
def passkey_register_options(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    if ctx.session.stage == S.FULL and not step_up_fresh(ctx.session):
        return problem("STEP_UP_REQUIRED", 403)  # adding a key is itself privileged
    return JsonResponse(passkeys.registration_options(ctx.session))


@console_view(methods=("POST",), stages=(S.ENROLL, S.FULL), allow_password_change=True)
def passkey_register(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    data = _body(request)
    try:
        key = passkeys.register(
            ctx.session, data.get("credential") or {}, str(data.get("name", "Security key"))
        )
    except passkeys.PasskeyError as exc:
        return problem(str(exc), 422)
    PlatformSession.objects.filter(pk=ctx.session.pk).update(stage=S.FULL, mfa_at=timezone.now())
    ctx.audit("auth.passkey_registered", key.name)
    return JsonResponse({"ok": True, "must_change_password": ctx.staff.must_change_password})


@console_view(methods=("POST",), stages=(S.ENROLL, S.PASSKEY, S.FULL))
def logout(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    PlatformSession.objects.filter(pk=ctx.session.pk).update(revoked_at=timezone.now())
    ctx.audit("auth.logout")
    response = JsonResponse({"ok": True})
    clear_cookie(response)
    return response


@console_view(stages=(S.ENROLL, S.PASSKEY, S.FULL), allow_password_change=True)
def me(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    return JsonResponse(
        {
            "email": ctx.staff.email,
            "role": ctx.staff.role,
            "stage": ctx.session.stage,
            "must_change_password": ctx.staff.must_change_password,
            "step_up_valid": step_up_fresh(ctx.session),
            "permissions": sorted(p for p, r in PERMISSIONS.items() if ctx.staff.role in r),
            "step_up_permissions": sorted(STEP_UP),
            "passkeys": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "created_at": _iso(p.created_at),
                    "last_used_at": _iso(p.last_used_at),
                }
                for p in Passkey.objects.filter(staff=ctx.staff).order_by("created_at")
            ],
        }
    )


@console_view(methods=("POST",), allow_password_change=True)
def change_password(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    data = _body(request)
    if not check_password(str(data.get("current", "")), ctx.staff.password_hash):
        return problem("INVALID_CREDENTIALS", 401)
    new = str(data.get("new", ""))
    if len(new) < MIN_PASSWORD or new == data.get("current"):
        return problem("WEAK_PASSWORD", 422, f"at least {MIN_PASSWORD} characters, and new")
    ctx.staff.password_hash = make_password(new)
    ctx.staff.must_change_password = False
    ctx.staff.save(update_fields=["password_hash", "must_change_password"])
    PlatformSession.objects.filter(staff=ctx.staff, revoked_at__isnull=True).exclude(
        pk=ctx.session.pk
    ).update(revoked_at=timezone.now())
    ctx.audit("auth.password_changed")
    return JsonResponse({"ok": True})


# ---- Overview --------------------------------------------------------------------------------


@console_view("overview.read")
def overview(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    since = timezone.now() - timedelta(hours=24)
    by_status = dict(Operator.objects.values_list("status").annotate(n=Count("pk")))
    ggr = [
        {"currency": ccy, "ggr": str(int(total or 0))}
        for ccy, total in LedgerEntry.objects.filter(
            account=LedgerEntry.Account.GAME_RESULT, created_at__gte=since
        )
        .values_list("currency")
        .annotate(s=Sum("amount_minor"))
        .order_by("currency")
    ]
    rounds = GameRound.objects.filter(updated_at__gte=since)
    return JsonResponse(
        {
            "operators": by_status,
            "rounds_24h": {
                "crashed": rounds.filter(state="CRASHED").count(),
                "voided": rounds.filter(state="VOIDED").count(),
                "unverified": rounds.filter(state="CRASHED").exclude(outcome_verified=True).count(),
            },
            "ggr_24h": ggr,
            "wallet": {
                "pending": WalletTransaction.objects.filter(
                    status__in=[WalletTransaction.Status.PENDING, WalletTransaction.Status.UNKNOWN]
                ).count(),
                "needs_attention": WalletTransaction.objects.filter(
                    status=WalletTransaction.Status.NEEDS_ATTENTION
                ).count(),
            },
            "discrepancies": dict(
                Discrepancy.objects.filter(status=Discrepancy.Status.OPEN)
                .values_list("severity")
                .annotate(n=Count("pk"))
            ),
            "pending_approvals": ApprovalRequest.objects.filter(
                status=ApprovalRequest.Status.PENDING
            ).count(),
        }
    )


# ---- Markets (owner only, ADR-026) ------------------------------------------------------------


def _market(m: Market) -> dict[str, Any]:
    return {
        "country_code": m.country_code,
        "status": m.status,
        "evidence_ref": m.evidence_ref,
        "changed_at": _iso(m.changed_at),
        "operators": OperatorJurisdiction.objects.filter(country_code=m.country_code).count(),
    }


@console_view("markets.read")
def markets(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    return JsonResponse({"markets": [_market(m) for m in Market.objects.order_by("country_code")]})


@console_view("markets.write", methods=("PUT",))
def set_market(request: HttpRequest, ctx: Ctx, country: str) -> HttpResponse:
    country = country.upper()
    data = _body(request)
    status = str(data.get("status", ""))
    evidence = str(data.get("evidence_ref", "")).strip()
    if len(country) != 2 or not country.isalpha() or status not in Market.Status.values:
        return problem("INVALID_REQUEST", 422)
    if status == Market.Status.REAL and not evidence:
        return problem("EVIDENCE_REQUIRED", 422, "real-money markets need a licence/evidence ref")
    with transaction.atomic():
        market, created = Market.objects.select_for_update().get_or_create(
            country_code=country, defaults={"status": Market.Status.DISABLED}
        )
        before = {"status": None if created else market.status, "evidence": market.evidence_ref}
        market.status = status
        market.evidence_ref = evidence
        market.save()
        revoked = 0
        if before["status"] == Market.Status.REAL and status != Market.Status.REAL:
            revoked = _revoke_sessions(
                GameSession.objects.filter(mode="REAL", player__country_code=country),
                "MARKET_CLOSED",
            )
        if status == Market.Status.DISABLED:
            revoked += _revoke_sessions(
                GameSession.objects.filter(player__country_code=country), "MARKET_DISABLED"
            )
    ctx.audit(
        "market.changed",
        country,
        before=before,
        after={"status": status, "evidence": evidence},
        sessions_revoked=revoked,
    )
    return JsonResponse(_market(market))


def _revoke_sessions(qs: Any, reason: str) -> int:
    from django.db.models import F

    n: int = qs.filter(status__in=[GameSession.Status.PENDING, GameSession.Status.ACTIVE]).update(
        status=GameSession.Status.REVOKED,
        revoked_reason=reason,
        session_version=F("session_version") + 1,
    )
    return n


# ---- Operators --------------------------------------------------------------------------------


def _operator(op: Operator, detail: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": op.public_id,
        "legal_name": op.legal_name,
        "status": op.status,
        "real_money_enabled": op.real_money_enabled,
        "stream": op.stream_slug,
        "wallet_kind": op.wallet_kind,
        "created_at": _iso(op.created_at),
    }
    if detail:
        out |= {
            "wallet_base_url": op.wallet_base_url,
            "wallet_conformance_passed_at": _iso(op.wallet_conformance_passed_at),
            "jurisdictions": sorted(op.jurisdictions.values_list("country_code", flat=True)),
            "limits": [
                {
                    "currency": lim.currency,
                    "min_stake": str(lim.min_stake_minor),
                    "max_stake": str(lim.max_stake_minor),
                    "max_win": str(lim.max_win_minor),
                    "round_exposure": str(lim.round_exposure_limit_minor),
                }
                for lim in op.limits.order_by("currency")
            ],
            "credentials": [
                {
                    "kid": c.kid,
                    "status": c.status,
                    "created_at": _iso(c.created_at),
                    "last_used_at": _iso(c.last_used_at),
                }
                for c in op.credentials.order_by("-created_at")
            ],
            "portal_users": op.staff.count(),
            "active_sessions": GameSession.objects.filter(
                operator=op, status=GameSession.Status.ACTIVE
            ).count(),
            "approvals": [_approval(a) for a in op.approvals.order_by("-created_at")[:20]],
        }
    return out


def _get_operator(op_id: str) -> Operator | None:
    return Operator.objects.filter(public_id=op_id).first()


@console_view("operators.read", methods=("GET", "POST"))
def operators(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    if request.method == "POST":
        return _onboard(request)
    qs = Operator.objects.order_by("legal_name")
    if (status := request.GET.get("status")) and status in Operator.Status.values:
        qs = qs.filter(status=status)
    return JsonResponse({"operators": [_operator(o) for o in qs]})


@console_view("operators.manage", methods=("POST",))
def _onboard(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    """Wizard result: operator in SANDBOX, jurisdictions, limits and its first portal owner."""
    data = _body(request)
    name = str(data.get("legal_name", "")).strip()
    owner_email = str(data.get("owner_email", "")).strip().lower()
    countries = [str(c).upper() for c in data.get("jurisdictions", [])]
    limits = data.get("currencies", [])
    if not name or "@" not in owner_email or not countries or not limits:
        return problem("INVALID_REQUEST", 422, "legal_name, owner_email, jurisdictions, currencies")
    open_markets = set(
        Market.objects.filter(country_code__in=countries)
        .exclude(status=Market.Status.DISABLED)
        .values_list("country_code", flat=True)
    )
    if missing := sorted(set(countries) - open_markets):
        return problem("JURISDICTION_NOT_PERMITTED", 422, f"markets not open: {missing}")
    if StaffUser.objects.filter(email=owner_email).exists():
        return problem("ALREADY_EXISTS", 409, "owner email already has a portal account")
    temporary = secrets.token_urlsafe(12)
    try:
        with transaction.atomic():
            op = Operator.objects.create(legal_name=name, status=Operator.Status.SANDBOX)
            for cc in countries:
                OperatorJurisdiction.objects.create(operator=op, country_code=cc)
            for lim in limits:
                OperatorCurrencyLimit.objects.create(
                    operator=op,
                    currency=str(lim["currency"]).upper(),
                    min_stake_minor=int(lim["min_stake"]),
                    max_stake_minor=int(lim["max_stake"]),
                    max_win_minor=int(lim["max_win"]),
                    round_exposure_limit_minor=int(lim["round_exposure"]),
                )
            StaffUser.objects.create(
                operator=op,
                email=owner_email,
                role=OperatorRole.OWNER,
                password_hash=make_password(temporary),
                must_change_password=True,
            )
    except (KeyError, TypeError, ValueError):
        return problem("INVALID_REQUEST", 422, "currency limits malformed")
    except Exception as exc:  # constraint violations (limits_sane, duplicates)
        if "limits_sane" in str(exc) or "uniq" in str(exc):
            return problem("INVALID_REQUEST", 422, "currency limits out of bounds or duplicated")
        raise
    ctx.audit(
        "operator.onboarded",
        op.public_id,
        op.pk,
        jurisdictions=countries,
        currencies=[str(lim["currency"]).upper() for lim in limits],
        owner=owner_email,
    )
    return JsonResponse(
        _operator(op, detail=True) | {"owner_temporary_password": temporary}, status=201
    )


@console_view("operators.read")
def operator_detail(request: HttpRequest, ctx: Ctx, op_id: str) -> HttpResponse:
    op = _get_operator(op_id)
    if op is None:
        return problem("NOT_FOUND", 404)
    return JsonResponse(_operator(op, detail=True))


@console_view("operators.manage", methods=("POST",))
def suspend_operator(request: HttpRequest, ctx: Ctx, op_id: str) -> HttpResponse:
    """Immediate (no approval): stop new sessions and revoke active ones; accepted bets settle."""
    op = _get_operator(op_id)
    if op is None:
        return problem("NOT_FOUND", 404)
    reason = str(_body(request).get("reason", "")).strip()
    if not reason:
        return problem("REASON_REQUIRED", 422)
    if op.status in (Operator.Status.SUSPENDED, Operator.Status.TERMINATED):
        return problem("INVALID_STATE", 409)
    before = op.status
    with transaction.atomic():
        op.status = Operator.Status.SUSPENDED
        op.save(update_fields=["status"])
        revoked = _revoke_sessions(GameSession.objects.filter(operator=op), "OPERATOR_SUSPENDED")
    ctx.audit(
        "operator.suspended",
        op.public_id,
        op.pk,
        before=before,
        reason=reason,
        sessions_revoked=revoked,
    )
    return JsonResponse(_operator(op, detail=True) | {"previous_status": before})


@console_view("operators.manage", methods=("POST",))
def promote_operator(request: HttpRequest, ctx: Ctx, op_id: str) -> HttpResponse:
    """ONBOARDING -> SANDBOX only. LIVE is reached through the real-money approval."""
    op = _get_operator(op_id)
    if op is None:
        return problem("NOT_FOUND", 404)
    if op.status != Operator.Status.ONBOARDING:
        return problem("INVALID_STATE", 409)
    op.status = Operator.Status.SANDBOX
    op.save(update_fields=["status"])
    ctx.audit("operator.status_changed", op.public_id, op.pk, before="ONBOARDING", after="SANDBOX")
    return JsonResponse(_operator(op, detail=True))


@console_view("credentials.manage", methods=("POST",))
def revoke_operator_credential(
    request: HttpRequest, ctx: Ctx, op_id: str, kid: str
) -> HttpResponse:
    """Compromise response (doc 12 §5.3): immediate, even if it is the operator's last key."""
    op = _get_operator(op_id)
    if op is None:
        return problem("NOT_FOUND", 404)
    reason = str(_body(request).get("reason", "")).strip()
    if not reason:
        return problem("REASON_REQUIRED", 422)
    n = OperatorCredential.objects.filter(
        operator=op, kid=kid, status=OperatorCredential.Status.ACTIVE
    ).update(status=OperatorCredential.Status.REVOKED)
    if not n:
        return problem("NOT_FOUND", 404)
    ctx.audit("credential.revoked_by_platform", kid, op.pk, reason=reason)
    return JsonResponse({"ok": True})


# ---- Four-eyes approvals ----------------------------------------------------------------------

REQUEST_PERM: dict[str, str] = {
    ApprovalRequest.Action.ENABLE_REAL_MONEY: "realmoney.request",
    ApprovalRequest.Action.REACTIVATE_OPERATOR: "operators.manage",
    ApprovalRequest.Action.APPROVE_RULESET: "games.manage",
    ApprovalRequest.Action.BIND_RULESET: "games.manage",
    ApprovalRequest.Action.ACTIVATE_SEED_CHAIN: "games.manage",
}
APPROVE_PERM: dict[str, str] = {
    ApprovalRequest.Action.ENABLE_REAL_MONEY: "realmoney.approve",
    ApprovalRequest.Action.REACTIVATE_OPERATOR: "reactivate.approve",
    ApprovalRequest.Action.APPROVE_RULESET: "games.approve",
    ApprovalRequest.Action.BIND_RULESET: "games.approve",
    ApprovalRequest.Action.ACTIVATE_SEED_CHAIN: "games.approve",
}
OPERATOR_ACTIONS = {
    ApprovalRequest.Action.ENABLE_REAL_MONEY,
    ApprovalRequest.Action.REACTIVATE_OPERATOR,
}
REAL_MONEY_EVIDENCE = ("contract_ref", "licence_ref", "certification_ref", "security_signoff_ref")


def _approval(a: ApprovalRequest) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "action": a.action,
        "subject": a.subject,
        "operator": a.operator.public_id if a.operator else None,
        "operator_name": a.operator.legal_name if a.operator else None,
        "payload": a.payload,
        "reason": a.reason,
        "requested_by": a.requested_by.email,
        "status": a.status,
        "decided_by": a.decided_by.email if a.decided_by else None,
        "decision_note": a.decision_note,
        "created_at": _iso(a.created_at),
        "decided_at": _iso(a.decided_at),
    }


def _preconditions(a: ApprovalRequest) -> str | None:
    """Checked when the request is made AND again, inside the transaction, when approved."""
    action, payload = a.action, a.payload
    if action in OPERATOR_ACTIONS:
        op = Operator.objects.filter(pk=a.operator_id).first() if a.operator_id else None
        if op is None:
            return "operator not found"
        if action == ApprovalRequest.Action.ENABLE_REAL_MONEY:
            if op.real_money_enabled:
                return "real money is already enabled"
            if op.status not in (Operator.Status.SANDBOX, Operator.Status.LIVE):
                return f"operator is {op.status}"
            if op.wallet_kind != WalletKind.SEAMLESS_V1 or not op.wallet_conformance_passed_at:
                return "the operator's seamless wallet has not passed the conformance suite"
            missing = [k for k in REAL_MONEY_EVIDENCE if not str(payload.get(k, "")).strip()]
            if missing:
                return f"missing evidence: {', '.join(missing)}"
            if not Market.objects.filter(
                country_code__in=op.jurisdictions.values("country_code"),
                status=Market.Status.REAL,
            ).exists():
                return "none of the operator's jurisdictions is open for real money"
            active = fairness.active_chain(op.stream_slug)
            if active is None or not active.drand_salted:
                return (
                    f"stream {op.stream_slug} is not running a ceremony seed chain "
                    "(drand-salted and four-eyes activated, doc 07 §6.1)"
                )
        elif op.status != Operator.Status.SUSPENDED:
            return "operator is not suspended"
        return None
    if action == ApprovalRequest.Action.APPROVE_RULESET:
        rs = GameRuleset.objects.filter(code=a.subject).first()
        if rs is None or rs.status != GameRuleset.Status.DRAFT:
            return "only an existing DRAFT ruleset can be approved"
        if not str(payload.get("certification_ref", "")).strip():
            return "a certification reference (test lab certificate) is required"
        return None
    if action == ApprovalRequest.Action.BIND_RULESET:
        rs = GameRuleset.objects.filter(code=payload.get("ruleset", "")).first()
        if rs is None or rs.status != GameRuleset.Status.APPROVED:
            return "only an APPROVED ruleset can be bound"
        current = StreamConfig.objects.filter(stream_slug=a.subject).first()
        if current is not None and current.ruleset_id == rs.code:
            return "the stream already uses this ruleset"
        return None
    if action == ApprovalRequest.Action.ACTIVATE_SEED_CHAIN:
        return _chain_preconditions(a.subject, payload)
    return "unknown action"


def _chain_preconditions(chain_id: str, payload: dict[str, Any]) -> str | None:
    c = fairness.chain(chain_id)
    if c is None or c.status != "COMMITTED":
        return "only a COMMITTED seed chain can be activated"
    if c.drand_round is None or c.committed_at is None:
        return "the chain was not committed to a drand round"
    if c.drand_chain_hash != settings.DRAND_CHAIN_HASH:
        return "the chain is committed to an untrusted drand network"
    if fairness.round_time(c.drand_round) < c.committed_at + fairness.min_delay():
        return "the drand round was too close to the commitment"
    if str(payload.get("drand_round", "")) != str(c.drand_round):
        return "the beacon is not for the committed drand round"
    if not fairness.beacon_consistent(
        str(payload.get("randomness", "")), str(payload.get("signature", ""))
    ):
        return "the beacon is inconsistent"
    return None


def _server_payload(action: str, subject: str) -> dict[str, str] | None:
    """Payloads the platform derives itself instead of trusting the requester's input."""
    if action != ApprovalRequest.Action.ACTIVATE_SEED_CHAIN:
        return None
    c = fairness.chain(subject)
    if c is None or c.status != "COMMITTED" or c.drand_round is None or not c.drand_chain_hash:
        return {}  # the preconditions explain why
    b = fairness.fetch_beacon(c.drand_round, c.drand_chain_hash)
    return {
        "stream": c.stream,
        "drand_round": str(b.round),
        "randomness": b.randomness,
        "signature": b.signature,
        "terminal_hash": c.terminal_hash,
    }


def _new_request(
    ctx: Ctx, action: str, subject: str, operator: Operator | None, data: dict[str, Any]
) -> HttpResponse:
    if action not in REQUEST_PERM:
        return problem("INVALID_REQUEST", 422)
    if not ctx.can(REQUEST_PERM[action]):
        return problem("FORBIDDEN", 403)
    if not step_up_fresh(ctx.session):
        return problem("STEP_UP_REQUIRED", 403)
    reason = str(data.get("reason", "")).strip()
    payload = {k: str(v) for k, v in (data.get("payload") or {}).items()}
    if not reason:
        return problem("REASON_REQUIRED", 422)
    try:
        derived = _server_payload(action, subject)
    except fairness.BeaconError as exc:
        return problem("BEACON_UNAVAILABLE", 409, str(exc))
    if derived is not None:
        payload = derived
    draft = ApprovalRequest(
        action=action,
        operator=operator,
        subject=subject,
        payload=payload,
        reason=reason,
        requested_by=ctx.staff,
    )
    if why := _preconditions(draft):
        return problem("PRECONDITION_FAILED", 422, why)
    if ApprovalRequest.objects.filter(action=action, subject=subject, status="PENDING").exists():
        return problem("ALREADY_PENDING", 409)
    draft.save()
    ctx.audit(
        "approval.requested",
        str(draft.id),
        operator.pk if operator else None,
        approval_action=action,
        subject=subject,
        payload=payload,
    )
    return JsonResponse(_approval(draft), status=201)


@console_view(methods=("POST",))
def request_approval(request: HttpRequest, ctx: Ctx, op_id: str) -> HttpResponse:
    data = _body(request)
    if str(data.get("action", "")) not in OPERATOR_ACTIONS:
        return problem("INVALID_REQUEST", 422)
    if not ctx.can(REQUEST_PERM[str(data["action"])]):
        return problem("FORBIDDEN", 403)
    op = _get_operator(op_id)
    if op is None:
        return problem("NOT_FOUND", 404)
    return _new_request(ctx, str(data["action"]), op.public_id, op, data)


@console_view(methods=("GET", "POST"))
def approvals(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    if request.method == "POST":
        data = _body(request)
        action = str(data.get("action", ""))
        if action in OPERATOR_ACTIONS:
            return problem("INVALID_REQUEST", 422, "use the operator's approvals route")
        return _new_request(ctx, action, str(data.get("subject", "")).strip(), None, data)
    qs = ApprovalRequest.objects.select_related("operator", "requested_by", "decided_by").order_by(
        "-created_at"
    )
    if (status := request.GET.get("status")) and status in ApprovalRequest.Status.values:
        qs = qs.filter(status=status)
    return JsonResponse({"approvals": [_approval(a) for a in qs[:200]]})


@console_view(methods=("POST",))
def decide_approval(
    request: HttpRequest, ctx: Ctx, approval_id: str, decision: str
) -> HttpResponse:
    if decision not in ("approve", "reject", "cancel"):
        return problem("NOT_FOUND", 404)
    note = str(_body(request).get("note", "")).strip()
    with transaction.atomic():
        a = (
            ApprovalRequest.objects.select_for_update(of=("self",))
            .select_related("operator", "requested_by")
            .filter(pk=_uuid(approval_id))
            .first()
        )
        if a is None:
            return problem("NOT_FOUND", 404)
        if a.status != ApprovalRequest.Status.PENDING:
            return problem("INVALID_STATE", 409)
        if decision == "cancel":
            if a.requested_by_id != ctx.staff.pk:
                return problem("FORBIDDEN", 403)
            a.status = ApprovalRequest.Status.CANCELLED
        else:
            if a.requested_by_id == ctx.staff.pk:
                return problem(
                    "SELF_APPROVAL", 403, "the requester cannot decide their own request"
                )
            if not ctx.can(APPROVE_PERM[a.action]):
                return problem("FORBIDDEN", 403)
            if not step_up_fresh(ctx.session):
                return problem("STEP_UP_REQUIRED", 403)
            if not note:
                return problem("NOTE_REQUIRED", 422)
            if decision == "approve":
                if why := _preconditions(a):
                    return problem("PRECONDITION_FAILED", 422, why)
                _execute(a, ctx.staff)
                a.status = ApprovalRequest.Status.APPROVED
            else:
                a.status = ApprovalRequest.Status.REJECTED
            a.decided_by = ctx.staff
        a.decision_note = note
        a.decided_at = timezone.now()
        a.save()
    ctx.audit(
        f"approval.{a.status.lower()}",
        str(a.id),
        a.operator_id,
        approval_action=a.action,
        subject=a.subject,
        note=note,
    )
    return JsonResponse(_approval(a))


def _execute(a: ApprovalRequest, approver: PlatformStaff) -> None:
    if a.action in OPERATOR_ACTIONS:
        assert a.operator_id is not None  # operator actions always carry their operator
        op = Operator.objects.select_for_update().get(pk=a.operator_id)
        if a.action == ApprovalRequest.Action.ENABLE_REAL_MONEY:
            op.real_money_enabled = True
            op.status = Operator.Status.LIVE
        else:
            op.status = Operator.Status.LIVE if op.real_money_enabled else Operator.Status.SANDBOX
        op.save(update_fields=["real_money_enabled", "status"])
    elif a.action == ApprovalRequest.Action.APPROVE_RULESET:
        rs = GameRuleset.objects.select_for_update().get(code=a.subject)
        rs.status = GameRuleset.Status.APPROVED
        rs.certification_ref = a.payload["certification_ref"].strip()
        rs.approved_by = approver.email
        rs.approved_at = timezone.now()
        rs.save()
    elif a.action == ApprovalRequest.Action.BIND_RULESET:
        rulesets.bind(a.subject, GameRuleset.objects.get(code=a.payload["ruleset"]))
    elif a.action == ApprovalRequest.Action.ACTIVATE_SEED_CHAIN:
        # Phoenix applies it idempotently and adopts the chain at the stream's next round.
        emit(
            "seed_chain.activate",
            {
                "chain_id": a.subject,
                "stream": a.payload["stream"],
                "drand_round": int(a.payload["drand_round"]),
                "randomness": a.payload["randomness"],
                "signature": a.payload["signature"],
            },
        )


# ---- Finance ----------------------------------------------------------------------------------


def _tx(t: WalletTransaction) -> dict[str, Any]:
    return {
        "transaction_id": tx_public_id(t.id),
        "type": t.type,
        "status": t.status,
        "amount": str(t.amount_minor),
        "currency": t.currency,
        "operator": t.operator.public_id,
        "bet_id": t.bet.public_id,
        "attempts": t.attempt_count,
        "operator_code": t.operator_code,
        "next_attempt_at": _iso(t.next_attempt_at),
        "created_at": _iso(t.created_at),
    }


@console_view("finance.read")
def pending_transactions(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    qs = (
        WalletTransaction.objects.filter(
            status__in=[
                WalletTransaction.Status.PENDING,
                WalletTransaction.Status.UNKNOWN,
                WalletTransaction.Status.NEEDS_ATTENTION,
            ]
        )
        .select_related("operator", "bet")
        .order_by("created_at")
    )
    return JsonResponse({"transactions": [_tx(t) for t in qs[:500]]})


@console_view("finance.retry", methods=("POST",))
def retry_transaction(request: HttpRequest, ctx: Ctx, tx_id: str) -> HttpResponse:
    """Re-drive a credit or rollback now. Safe: same deterministic id, operators are idempotent."""
    pk = parse_public_id("tx", tx_id)
    tx = (
        WalletTransaction.objects.filter(
            pk=pk,
            type__in=[WalletTransaction.Type.CREDIT, WalletTransaction.Type.ROLLBACK],
            status__in=[
                WalletTransaction.Status.UNKNOWN,
                WalletTransaction.Status.NEEDS_ATTENTION,
                WalletTransaction.Status.PENDING,
            ],
        )
        .select_related("operator", "bet")
        .first()
        if pk
        else None
    )
    if tx is None:
        return problem("NOT_FOUND", 404)
    before = tx.status
    WalletTransaction.objects.filter(pk=tx.pk).update(
        status=WalletTransaction.Status.UNKNOWN, next_attempt_at=timezone.now()
    )
    ctx.audit("finance.retry", tx_id, tx.operator_id, before=before)
    tx.refresh_from_db()
    return JsonResponse(_tx(tx))


@console_view("finance.read")
def bets(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    qs = Bet.objects.select_related("operator", "player").order_by("-created_at", "-id")
    if bet_id := request.GET.get("bet_id"):
        qs = qs.filter(public_id=bet_id)
    if op := request.GET.get("operator"):
        qs = qs.filter(operator__public_id=op)
    if (status := request.GET.get("status")) and status in Bet.Status.values:
        qs = qs.filter(status=status)
    if player := request.GET.get("player_id"):
        if not ctx.can("players.search"):
            return problem("FORBIDDEN", 403)
        ctx.audit("player.searched", player)  # player-level reads are audited (doc 12 §1)
        qs = qs.filter(player__external_player_id=player)
    masked = ctx.staff.role == Role.SUPPORT
    rows = []
    for b in qs[:PAGE]:
        row = bet_view(b, include_player=not masked) | {"operator": b.operator.public_id}
        rows.append(row)
    return JsonResponse({"bets": rows})


@console_view("finance.read")
def bet_timeline(request: HttpRequest, ctx: Ctx, bet_id: str) -> HttpResponse:
    bet = Bet.objects.select_related("operator", "player").filter(public_id=bet_id).first()
    if bet is None:
        return problem("NOT_FOUND", 404)
    out = bet_view(bet, include_player=ctx.staff.role != Role.SUPPORT)
    s = Settlement.objects.filter(bet=bet).first()
    out["operator"] = bet.operator.public_id
    out["settlement"] = (
        {"outcome": s.outcome, "status": s.status, "payout": str(s.payout_minor)} if s else None
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
    out["ledger"] = [
        {
            "journal": str(e.journal_id),
            "memo": e.memo,
            "account": e.account,
            "amount": str(e.amount_minor),
            "at": _iso(e.created_at),
        }
        for e in LedgerEntry.objects.filter(bet=bet).order_by("created_at", "account")
    ]
    return JsonResponse(out)


@console_view("finance.read")
def discrepancies(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    qs = Discrepancy.objects.select_related("operator").order_by("-created_at")
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
                    "operator": d.operator.public_id if d.operator else None,
                    "detail": d.detail,
                    "status": d.status,
                    "created_at": _iso(d.created_at),
                    "resolution_note": d.resolution_note,
                    "resolved_by": d.resolved_by,
                }
                for d in qs[:300]
            ]
        }
    )


@console_view("reconciliation.resolve", methods=("POST",))
def resolve_discrepancy(request: HttpRequest, ctx: Ctx, item_id: str) -> HttpResponse:
    note = str(_body(request).get("note", "")).strip()
    if not note:
        return problem("NOTE_REQUIRED", 422, "a resolution note is mandatory (doc 08 §8)")
    n = Discrepancy.objects.filter(pk=_uuid(item_id), status=Discrepancy.Status.OPEN).update(
        status=Discrepancy.Status.RESOLVED,
        resolution_note=note,
        resolved_by=ctx.staff.email,
        resolved_at=timezone.now(),
    )
    if not n:
        return problem("NOT_FOUND", 404)
    ctx.audit("discrepancy.resolved", item_id, note=note)
    return JsonResponse({"ok": True})


# ---- Games: rulesets, streams, seed chains (doc 12 §3.3) ---------------------------------------


def _ruleset(rs: GameRuleset) -> dict[str, Any]:
    return {
        "code": rs.code,
        "formula": rs.formula,
        "house_edge_bp": rs.house_edge_bp,
        "rtp_bp": rs.rtp_bp,
        "max_multiplier_x10000": rs.max_multiplier_x10000,
        "status": rs.status,
        "certification_ref": rs.certification_ref,
        "notes": rs.notes,
        "created_by": rs.created_by,
        "approved_by": rs.approved_by,
        "created_at": _iso(rs.created_at),
        "approved_at": _iso(rs.approved_at),
        "streams": list(
            StreamConfig.objects.filter(ruleset=rs).values_list("stream_slug", flat=True)
        ),
    }


@console_view("games.read", methods=("GET", "POST"))
def game_rulesets(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    if request.method == "POST":
        return _create_ruleset(request)
    return JsonResponse(
        {"rulesets": [_ruleset(r) for r in GameRuleset.objects.order_by("-created_at")]}
    )


@console_view("games.manage", methods=("POST",))
def _create_ruleset(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    data = _body(request)
    code = str(data.get("code", "")).strip().upper()
    try:
        edge = int(data.get("house_edge_bp", 0))
        max_x = int(data.get("max_multiplier_x10000", 0))
    except (TypeError, ValueError):
        return problem("INVALID_REQUEST", 422)
    if not code or not all(ch.isalnum() or ch in "-_." for ch in code) or len(code) > 40:
        return problem("INVALID_REQUEST", 422, "code: letters, digits, - _ .")
    if not 100 <= edge <= 1000:
        return problem("CONFIG_NOT_PERMITTED", 422, "house edge must be 100..1000 bp (RTP 90-99%)")
    if not 1_000_000 <= max_x <= 100_000_000 or max_x % 100:
        return problem("CONFIG_NOT_PERMITTED", 422, "max multiplier 100x..10000x, 0.01x steps")
    if GameRuleset.objects.filter(code=code).exists():
        return problem("ALREADY_EXISTS", 409)
    rs = GameRuleset.objects.create(
        code=code,
        house_edge_bp=edge,
        max_multiplier_x10000=max_x,
        notes=str(data.get("notes", ""))[:2000],
        created_by=ctx.staff.email,
    )
    ctx.audit("ruleset.drafted", code, house_edge_bp=edge, max_multiplier_x10000=max_x)
    return JsonResponse(_ruleset(rs), status=201)


@console_view("games.read")
def game_streams(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    out = []
    for cfg in StreamConfig.objects.select_related("ruleset").order_by("stream_slug"):
        last = (
            GameRound.objects.filter(stream_slug=cfg.stream_slug)
            .exclude(ruleset_code="")
            .order_by("-number")
            .first()
        )
        out.append(
            {
                "stream": cfg.stream_slug,
                "desired": {"ruleset": cfg.ruleset_id, "version": cfg.version},
                # What the engine actually journaled for its latest round (adoption is at the
                # next round boundary, so the two differ briefly after a binding).
                "applied": {
                    "ruleset": last.ruleset_code,
                    "version": last.ruleset_version,
                    "round": last.number,
                    "approved": last.ruleset_ok,
                }
                if last
                else None,
                "operators": Operator.objects.filter(stream_slug=cfg.stream_slug).count(),
            }
        )
    return JsonResponse({"streams": out})


@console_view("games.read")
def seed_chains(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    """Public chain facts only. The encrypted root seed and checkpoints are never selected."""
    out = []
    for c in fairness.chains():
        view = fairness.public_view(c)
        view["usage_bp"] = c.rounds_used * 10000 // c.length if c.length else 0
        view["beacon_due"] = (
            c.status == "COMMITTED"
            and c.drand_round is not None
            and fairness.round_time(c.drand_round) <= timezone.now()
        )
        out.append(view)
    return JsonResponse({"seed_chains": out})


# ---- Rounds (read-only: there is deliberately no write path, AC-ADM-2) -------------------------


@console_view("overview.read")
def rounds(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    qs = GameRound.objects.filter(state__in=["CRASHED", "VOIDED"]).order_by("-updated_at")
    if stream := request.GET.get("stream"):
        qs = qs.filter(stream_slug=stream)
    agg: dict[Any, Any] = {
        r["round_id"]: r
        for r in Bet.objects.filter(round_id__in=[r.id for r in qs[:PAGE]])
        .values("round_id")
        .annotate(bets=Count("id"), stake=Sum("stake_minor"))
    }
    return JsonResponse(
        {
            "rounds": [
                {
                    "round_id": str(r.id),
                    "stream": r.stream_slug,
                    "number": r.number,
                    "state": r.state,
                    "crash_x10000": r.crash_x10000,
                    "outcome_verified": r.outcome_verified,
                    "settlement_status": r.settlement_status,
                    "bets": agg.get(r.id, {}).get("bets", 0),
                }
                for r in qs[:PAGE]
            ]
        }
    )


@console_view("overview.read")
def round_detail(request: HttpRequest, ctx: Ctx, round_id: str) -> HttpResponse:
    rid = _uuid(round_id)
    rnd = GameRound.objects.filter(pk=rid).first()
    # Only finished rounds: nothing about a live round's outcome can leave through this path.
    if rnd is None or rnd.state not in ("CRASHED", "VOIDED"):
        return problem("NOT_FOUND", 404)
    journal: list[dict[str, Any]] = []
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('rt.round_journal') IS NOT NULL")
        row = cur.fetchone()
        if row and row[0]:
            cur.execute(
                "SELECT stream_seq, type, payload, recorded_at FROM rt.round_journal "
                "WHERE round_id = %s ORDER BY stream_seq",
                [rid],
            )
            journal = [
                {"seq": seq, "type": typ, "payload": payload, "at": _iso(at)}
                for seq, typ, payload, at in cur.fetchall()
            ]
    return JsonResponse(
        {
            "round_id": str(rnd.id),
            "stream": rnd.stream_slug,
            "number": rnd.number,
            "state": rnd.state,
            "crash_x10000": rnd.crash_x10000,
            "commitment": rnd.commitment,
            "seed": rnd.seed_hex,
            "salt": rnd.salt_hex,
            "outcome_verified": rnd.outcome_verified,
            "settlement_status": rnd.settlement_status,
            "journal": journal,
            "bets_by_status": dict(
                Bet.objects.filter(round_id=rnd.id).values_list("status").annotate(n=Count("id"))
            ),
        }
    )


# ---- Staff ------------------------------------------------------------------------------------


def _staff(s: PlatformStaff) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "email": s.email,
        "role": s.role,
        "status": s.status,
        "passkeys": s.passkeys.count(),
        "created_at": _iso(s.created_at),
    }


@console_view("staff.manage", methods=("GET", "POST"))
def staff(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    if request.method == "GET":
        return JsonResponse({"staff": [_staff(s) for s in PlatformStaff.objects.order_by("email")]})
    data = _body(request)
    email = str(data.get("email", "")).strip().lower()
    role = str(data.get("role", ""))
    if "@" not in email or role not in Role.values:
        return problem("INVALID_REQUEST", 422)
    if role == Role.OWNER:
        return problem("FORBIDDEN", 403, "there is exactly one owner")
    if role == Role.SUPERADMIN and ctx.staff.role != Role.OWNER:
        return problem("FORBIDDEN", 403, "only the owner appoints superadmins")
    if (
        role == Role.SUPERADMIN
        and PlatformStaff.objects.filter(
            role=Role.SUPERADMIN, status=PlatformStaff.Status.ACTIVE
        ).count()
        >= SUPERADMIN_CAP
    ):
        return problem("SUPERADMIN_CAP", 409)
    if PlatformStaff.objects.filter(email=email).exists():
        return problem("ALREADY_EXISTS", 409)
    temporary = secrets.token_urlsafe(14)
    s = PlatformStaff.objects.create(
        email=email,
        role=role,
        password_hash=make_password(temporary),
        webauthn_user_id=os.urandom(32),
    )
    ctx.audit("staff.created", email, role=role)
    return JsonResponse(_staff(s) | {"temporary_password": temporary}, status=201)


@console_view("staff.manage", methods=("PATCH",))
def update_staff(request: HttpRequest, ctx: Ctx, staff_id: str) -> HttpResponse:
    s = PlatformStaff.objects.filter(pk=_uuid(staff_id)).first()
    if s is None:
        return problem("NOT_FOUND", 404)
    if s.pk == ctx.staff.pk or s.role == Role.OWNER:
        return problem("FORBIDDEN", 403)
    data = _body(request)
    role = str(data.get("role", s.role))
    status = str(data.get("status", s.status))
    if role not in Role.values or status not in PlatformStaff.Status.values or role == Role.OWNER:
        return problem("INVALID_REQUEST", 422)
    if Role.SUPERADMIN in (role, s.role) and ctx.staff.role != Role.OWNER and role != s.role:
        return problem("FORBIDDEN", 403, "only the owner changes superadmins")
    if (
        role == Role.SUPERADMIN
        and s.role != Role.SUPERADMIN
        and PlatformStaff.objects.filter(role=Role.SUPERADMIN, status="ACTIVE").count()
        >= SUPERADMIN_CAP
    ):
        return problem("SUPERADMIN_CAP", 409)
    before = {"role": s.role, "status": s.status}
    s.role, s.status = role, status
    s.save(update_fields=["role", "status"])
    if status != PlatformStaff.Status.ACTIVE:
        PlatformSession.objects.filter(staff=s, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
    ctx.audit("staff.updated", s.email, before=before, after={"role": role, "status": status})
    return JsonResponse(_staff(s))


@console_view("staff.manage", methods=("POST",))
def reset_staff_passkeys(request: HttpRequest, ctx: Ctx, staff_id: str) -> HttpResponse:
    """Lost key: wipe passkeys and sessions; the person enrols again after password login."""
    s = PlatformStaff.objects.filter(pk=_uuid(staff_id)).first()
    if s is None:
        return problem("NOT_FOUND", 404)
    if s.pk == ctx.staff.pk or s.role == Role.OWNER:
        return problem("FORBIDDEN", 403)
    n = Passkey.objects.filter(staff=s).delete()[0]
    PlatformSession.objects.filter(staff=s, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    ctx.audit("staff.passkeys_reset", s.email, removed=n)
    return JsonResponse(_staff(s))


# ---- Audit ------------------------------------------------------------------------------------


@console_view("audit.read")
def audit_log(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    qs = AuditEvent.objects.select_related("operator").order_by("-seq")
    if (before := request.GET.get("before", "")).isdigit():
        qs = qs.filter(seq__lt=int(before))
    if action := request.GET.get("action"):
        qs = qs.filter(action__startswith=action)
    if actor := request.GET.get("actor"):
        qs = qs.filter(actor=actor.lower())
    if op := request.GET.get("operator"):
        qs = qs.filter(operator__public_id=op)
    rows = list(qs[: PAGE + 1])
    return JsonResponse(
        {
            "events": [
                {
                    "seq": e.seq,
                    "at": _iso(e.at),
                    "realm": e.realm,
                    "operator": e.operator.public_id if e.operator else None,
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


@console_view("audit.read")
def audit_verify(request: HttpRequest, ctx: Ctx) -> HttpResponse:
    ok, broken = audit.verify_chain()
    last = AuditEvent.objects.order_by("-seq").only("seq", "hash").first()
    return JsonResponse(
        {
            "ok": ok,
            "first_broken_seq": broken,
            "events": last.seq if last else 0,
            "head_hash": last.hash if last else None,
        }
    )
