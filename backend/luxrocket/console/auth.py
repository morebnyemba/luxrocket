"""Platform console authentication: password + mandatory passkey, step-up, RBAC (doc 12 §1, §4)."""

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from functools import wraps
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from luxrocket.console.models import PlatformSession, PlatformStaff, Role
from luxrocket.core.errors import problem
from luxrocket.portal import audit
from luxrocket.portal.auth import client_ip, same_origin

R = Role


def roles(*members: Role) -> set[str]:
    return {m.value for m in members}


ALL = roles(*Role)
# The doc 12 §4 matrix, verbatim. Tests generate the allow/deny matrix from this table.
PERMISSIONS: dict[str, set[str]] = {
    "overview.read": ALL,
    "markets.read": ALL,
    "markets.write": roles(R.OWNER),  # ADR-026: owner only
    "operators.read": ALL,
    "operators.manage": roles(R.OWNER, R.SUPERADMIN, R.OPS),
    "realmoney.request": roles(R.OWNER, R.SUPERADMIN),
    "realmoney.approve": roles(R.OWNER, R.SUPERADMIN, R.RISK),
    "reactivate.approve": roles(R.OWNER, R.SUPERADMIN),
    "credentials.manage": roles(R.OWNER, R.SUPERADMIN, R.OPS),
    "finance.read": roles(R.OWNER, R.SUPERADMIN, R.OPS, R.FINANCE, R.RISK, R.SUPPORT, R.AUDITOR),
    "players.search": roles(R.OWNER, R.SUPERADMIN, R.FINANCE, R.RISK, R.SUPPORT, R.AUDITOR),
    "finance.retry": roles(R.OWNER, R.SUPERADMIN, R.OPS, R.FINANCE),
    "reconciliation.resolve": roles(R.OWNER, R.SUPERADMIN, R.FINANCE, R.RISK),
    "staff.manage": roles(R.OWNER, R.SUPERADMIN),
    "audit.read": roles(R.OWNER, R.SUPERADMIN, R.RISK, R.AUDITOR),
    "games.read": ALL,
    "games.manage": roles(R.OWNER, R.SUPERADMIN, R.GAME_RELEASE),
    "games.approve": roles(R.OWNER, R.SUPERADMIN, R.RISK),
}
# Every mutation guarded by one of these needs a passkey assertion within the step-up window.
STEP_UP = {
    "markets.write",
    "operators.manage",
    "realmoney.request",
    "realmoney.approve",
    "reactivate.approve",
    "credentials.manage",
    "finance.retry",
    "staff.manage",
    "games.manage",
    "games.approve",
}
SUPERADMIN_CAP = 3
LOCK_AFTER = 5
LOCK_FOR = timedelta(minutes=15)
REALM = "PLATFORM"


@dataclass
class Ctx:
    session: PlatformSession
    staff: PlatformStaff
    ip: str | None

    def can(self, perm: str) -> bool:
        return self.staff.role in PERMISSIONS[perm]

    def audit(self, action: str, target: str = "", operator_id: Any = None, **data: Any) -> None:
        audit.record(
            realm=REALM,
            actor=self.staff.email,
            action=action,
            operator_id=operator_id,
            target=target,
            data=data,
            ip=self.ip,
        )


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(request: HttpRequest, staff: PlatformStaff, stage: str) -> str:
    token = secrets.token_urlsafe(32)
    PlatformSession.objects.create(
        token_hash=token_hash(token),
        staff=staff,
        stage=stage,
        expires_at=timezone.now() + timedelta(hours=settings.ADMIN_SESSION_HOURS),
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent", "")[:200],
    )
    return token


def set_cookie(response: HttpResponse, token: str) -> None:
    response.set_cookie(
        settings.ADMIN_COOKIE_NAME,
        token,
        max_age=settings.ADMIN_SESSION_HOURS * 3600,
        secure=True,
        httponly=True,
        samesite="Strict",
        path="/",
    )


def clear_cookie(response: HttpResponse) -> None:
    response.delete_cookie(settings.ADMIN_COOKIE_NAME, path="/", samesite="Strict")


def load_session(request: HttpRequest) -> PlatformSession | None:
    token = request.COOKIES.get(settings.ADMIN_COOKIE_NAME, "")
    if not token:
        return None
    now = timezone.now()
    s = (
        PlatformSession.objects.select_related("staff")
        .filter(token_hash=token_hash(token), revoked_at__isnull=True, expires_at__gt=now)
        .first()
    )
    if s is None:
        return None
    if now - s.last_seen_at > timedelta(minutes=settings.ADMIN_IDLE_MINUTES):
        PlatformSession.objects.filter(pk=s.pk).update(revoked_at=now)
        return None
    if s.staff.status != PlatformStaff.Status.ACTIVE:
        return None
    if now - s.last_seen_at > timedelta(seconds=60):
        PlatformSession.objects.filter(pk=s.pk).update(last_seen_at=now)
    return s


def same_admin_origin(request: HttpRequest) -> bool:
    return same_origin(request, settings.ADMIN_ALLOWED_ORIGINS)


def step_up_fresh(session: PlatformSession) -> bool:
    fresh = timezone.now() - timedelta(minutes=settings.ADMIN_STEP_UP_MINUTES)
    return session.mfa_at is not None and session.mfa_at >= fresh


def console_view(
    perm: str | None = None,
    *,
    methods: tuple[str, ...] = ("GET",),
    stages: tuple[str, ...] = (PlatformSession.Stage.FULL,),
    allow_password_change: bool = False,
) -> Callable[[Callable[..., HttpResponse]], Callable[..., HttpResponse]]:
    def decorate(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @csrf_exempt  # replaced by same_admin_origin + SameSite=Strict
        @wraps(view)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            if request.method not in methods:
                return problem("METHOD_NOT_ALLOWED", 405)
            if request.method != "GET" and not same_admin_origin(request):
                return problem("CSRF_REJECTED", 403)
            s = load_session(request)
            if s is None:
                return problem("UNAUTHENTICATED", 401)
            if s.stage not in stages:
                code = "PASSKEY_ENROLLMENT_REQUIRED" if s.stage == "ENROLL" else "PASSKEY_REQUIRED"
                return problem(code, 401)
            if s.staff.must_change_password and not allow_password_change and s.stage == "FULL":
                return problem("PASSWORD_CHANGE_REQUIRED", 403)
            ctx = Ctx(s, s.staff, client_ip(request))
            if perm is not None:
                if not ctx.can(perm):
                    return problem("FORBIDDEN", 403)
                if perm in STEP_UP and request.method != "GET" and not step_up_fresh(s):
                    return problem("STEP_UP_REQUIRED", 403)
            response = view(request, ctx, *args, **kwargs)
            response["Cache-Control"] = "no-store"
            return response

        return wrapper

    return decorate
