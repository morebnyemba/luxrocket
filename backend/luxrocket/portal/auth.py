"""Portal authentication: cookie sessions, TOTP second factor, step-up, RBAC (doc 13 §3.5, §4).

The operator comes only from the session (doc 13 §1): no request parameter can select another
tenant, and every query below is filtered by `ctx.operator`.
"""

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

from luxrocket.core.errors import problem
from luxrocket.operators.models import Operator
from luxrocket.portal import audit
from luxrocket.portal.models import Role, StaffSession, StaffUser

R = Role


def roles(*members: Role) -> set[str]:
    return {m.value for m in members}


ALL = roles(*Role)
PERMISSIONS: dict[str, set[str]] = {
    "overview.read": ALL,
    "reports.read": roles(R.OWNER, R.ADMIN, R.FINANCE, R.SUPPORT, R.VIEWER),
    "players.read": roles(R.OWNER, R.ADMIN, R.FINANCE, R.SUPPORT),  # player-level detail
    "reconciliation.read": roles(R.OWNER, R.ADMIN, R.FINANCE),
    "integration.read": roles(R.OWNER, R.ADMIN, R.DEVELOPER),
    "webhooks.manage": roles(R.OWNER, R.ADMIN, R.DEVELOPER),
    "credentials.manage": roles(R.OWNER, R.DEVELOPER),
    "wallet.manage": roles(R.OWNER, R.DEVELOPER),
    "users.manage": roles(R.OWNER, R.ADMIN),
    "audit.read": roles(R.OWNER, R.ADMIN),
}
# Actions that require a second factor within the last few minutes (doc 13 §3.5).
STEP_UP = {"credentials.manage", "wallet.manage", "users.manage"}

LOCK_AFTER = 5
LOCK_FOR = timedelta(minutes=15)
REALM = "OPERATOR"


@dataclass
class Ctx:
    session: StaffSession
    user: StaffUser
    operator: Operator
    ip: str | None

    def can(self, perm: str) -> bool:
        return self.user.role in PERMISSIONS[perm]

    def audit(self, action: str, target: str = "", **data: Any) -> None:
        audit.record(
            realm=REALM,
            actor=self.user.email,
            action=action,
            operator_id=self.operator.pk,
            target=target,
            data=data,
            ip=self.ip,
        )


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip(request: HttpRequest) -> str | None:
    return request.META.get("REMOTE_ADDR")


def start_session(request: HttpRequest, user: StaffUser, *, mfa_pending: bool) -> str:
    token = secrets.token_urlsafe(32)
    StaffSession.objects.create(
        token_hash=_hash(token),
        user=user,
        mfa_pending=mfa_pending,
        expires_at=timezone.now() + timedelta(hours=settings.PORTAL_SESSION_HOURS),
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent", "")[:200],
    )
    return token


def set_cookie(response: HttpResponse, token: str) -> None:
    response.set_cookie(
        settings.PORTAL_COOKIE_NAME,
        token,
        max_age=settings.PORTAL_SESSION_HOURS * 3600,
        secure=True,
        httponly=True,
        samesite="Strict",
        path="/",
    )


def clear_cookie(response: HttpResponse) -> None:
    response.delete_cookie(settings.PORTAL_COOKIE_NAME, path="/", samesite="Strict")


def load_session(request: HttpRequest) -> StaffSession | None:
    token = request.COOKIES.get(settings.PORTAL_COOKIE_NAME, "")
    if not token:
        return None
    now = timezone.now()
    s = (
        StaffSession.objects.select_related("user", "user__operator")
        .filter(token_hash=_hash(token), revoked_at__isnull=True, expires_at__gt=now)
        .first()
    )
    if s is None:
        return None
    if now - s.last_seen_at > timedelta(minutes=settings.PORTAL_IDLE_MINUTES):
        s.revoked_at = now
        s.save(update_fields=["revoked_at"])
        return None
    if s.user.status != StaffUser.Status.ACTIVE or s.user.operator.status in (
        Operator.Status.SUSPENDED,
        Operator.Status.TERMINATED,
    ):
        return None
    if now - s.last_seen_at > timedelta(seconds=60):
        StaffSession.objects.filter(pk=s.pk).update(last_seen_at=now)
    return s


def same_origin(request: HttpRequest, allowed: list[str] | None = None) -> bool:
    """Mutations need our custom header (not sendable cross-site without CORS) and, when the
    browser sends one, a same-origin Origin. SameSite=Strict on the cookie is the third layer."""
    if request.headers.get("X-LR-Portal") != "1":
        return False
    origin = request.headers.get("Origin")
    extra = settings.PORTAL_ALLOWED_ORIGINS if allowed is None else allowed
    if origin is None or origin in extra:
        return True
    return origin == f"{request.scheme}://{request.get_host()}"


def portal_view(
    perm: str | None = None,
    *,
    methods: tuple[str, ...] = ("GET",),
    allow_pending_mfa: bool = False,
    allow_password_change: bool = False,
) -> Callable[[Callable[..., HttpResponse]], Callable[..., HttpResponse]]:
    def decorate(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @csrf_exempt  # replaced by same_origin + SameSite=Strict
        @wraps(view)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            if request.method not in methods:
                return problem("METHOD_NOT_ALLOWED", 405)
            if request.method != "GET" and not same_origin(request):
                return problem("CSRF_REJECTED", 403)
            s = load_session(request)
            if s is None:
                return problem("UNAUTHENTICATED", 401)
            if s.mfa_pending and not allow_pending_mfa:
                return problem("MFA_REQUIRED", 401)
            if s.user.must_change_password and not (allow_password_change or allow_pending_mfa):
                return problem("PASSWORD_CHANGE_REQUIRED", 403)
            ctx = Ctx(s, s.user, s.user.operator, client_ip(request))
            if perm is not None:
                if not ctx.can(perm):
                    return problem("FORBIDDEN", 403)
                if perm in STEP_UP and request.method != "GET":
                    if not s.user.mfa_enabled:
                        return problem("MFA_ENROLLMENT_REQUIRED", 403)
                    fresh = timezone.now() - timedelta(minutes=settings.PORTAL_STEP_UP_MINUTES)
                    if s.mfa_at is None or s.mfa_at < fresh:
                        return problem("STEP_UP_REQUIRED", 403)
            response = view(request, ctx, *args, **kwargs)
            response["Cache-Control"] = "no-store"
            return response

        return wrapper

    return decorate
