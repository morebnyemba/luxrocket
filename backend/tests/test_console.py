"""Platform console (doc 12): passkey MFA, role matrix, four-eyes, markets, operators, finance."""

import json
import os
from datetime import timedelta

import pytest
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import URLPattern
from django.utils import timezone

from luxrocket.console import urls as console_urls
from luxrocket.console.auth import PERMISSIONS
from luxrocket.console.models import (
    ApprovalRequest,
    Passkey,
    PlatformSession,
    PlatformStaff,
    Role,
)
from luxrocket.core.ids import tx_public_id
from luxrocket.gaming.models import GameSession
from luxrocket.operators.models import Market, Operator
from luxrocket.portal import audit
from luxrocket.portal.models import AuditEvent, StaffUser
from luxrocket.wallet.models import Discrepancy, ReconciliationRun, WalletTransaction
from tests.factories import create_session, make_operator
from tests.soft_authenticator import SoftAuthenticator
from tests.test_money_path import bet
from tests.test_money_path import world as sandbox_world  # noqa: F401 (fixture)

pytestmark = pytest.mark.django_db
API = "/api/admin/v1"
H = {"HTTP_X_LR_PORTAL": "1"}
PASSWORD = "a long staff passphrase"


def make_staff(email, role=Role.SUPERADMIN):
    return PlatformStaff.objects.create(
        email=email,
        role=role,
        password_hash=make_password(PASSWORD),
        must_change_password=False,
        webauthn_user_id=os.urandom(32),
    )


def call(client, method, path, data=None):
    if method == "get":
        return client.get(f"{API}/{path}")
    return getattr(client, method)(
        f"{API}/{path}", json.dumps(data or {}), content_type="application/json", **H
    )


def login(client, email, password=PASSWORD):
    return call(client, "post", "auth/login", {"email": email, "password": password})


def enroll(client, key):
    options = call(client, "post", "auth/passkey/register/options").json()
    return call(
        client,
        "post",
        "auth/passkey/register",
        {"credential": key.create(options), "name": "YubiKey"},
    )


def assert_passkey(client, key, **kw):
    options = call(client, "post", "auth/passkey/options").json()
    return call(client, "post", "auth/passkey/verify", {"credential": key.get(options, **kw)})


def signed_in(role=Role.SUPERADMIN, email=None):
    """A fully authenticated client with a fresh passkey assertion."""
    staff = make_staff(email or f"{role.lower()}@lux.test", role)
    c, key = Client(), SoftAuthenticator()
    assert login(c, staff.email).json()["next"] == "enroll"
    assert enroll(c, key).status_code == 200
    c.staff, c.key = staff, key
    return c


# ---- Passkey authentication -------------------------------------------------------------------


def test_passkey_is_mandatory_and_enrolment_comes_first(client):
    staff = make_staff("ops@lux.test", Role.OPS)
    key = SoftAuthenticator()
    assert login(client, staff.email).json() == {"next": "enroll"}
    assert call(client, "get", "overview").json()["code"] == "PASSKEY_ENROLLMENT_REQUIRED"
    assert enroll(client, key).status_code == 200
    assert call(client, "get", "overview").status_code == 200
    call(client, "post", "auth/logout")
    assert login(client, staff.email).json() == {"next": "passkey"}
    assert call(client, "get", "overview").json()["code"] == "PASSKEY_REQUIRED"
    assert assert_passkey(client, key).status_code == 200
    assert call(client, "get", "overview").status_code == 200
    assert Passkey.objects.get().sign_count == 1


def test_challenges_are_single_use_and_origin_bound(client):
    c = signed_in()
    options = call(c, "post", "auth/passkey/options").json()
    good = c.key.get(options)
    assert call(c, "post", "auth/passkey/verify", {"credential": good}).status_code == 200
    replay = call(c, "post", "auth/passkey/verify", {"credential": good})
    assert replay.json()["code"] == "CHALLENGE_EXPIRED"
    phished = assert_passkey(c, c.key, origin="https://lux-rocket-login.evil")
    assert phished.json()["code"] == "PASSKEY_INVALID"


def test_cloned_authenticator_is_refused(client):
    c = signed_in()
    assert assert_passkey(c, c.key).status_code == 200  # counter 1
    assert assert_passkey(c, c.key, counter=1).json()["code"] == "PASSKEY_INVALID"


def test_another_users_key_does_not_work(client):
    a = signed_in(email="a@lux.test")
    b = signed_in(email="b@lux.test")
    options = call(a, "post", "auth/passkey/options").json()
    stolen = b.key.get(options)
    assert call(a, "post", "auth/passkey/verify", {"credential": stolen}).status_code == 401


def test_login_lockout_and_uniform_errors(client):
    make_staff("x@lux.test")
    for _ in range(5):
        assert login(client, "x@lux.test", "wrong").status_code == 401
    assert login(client, "x@lux.test").status_code == 429
    assert login(client, "nobody@lux.test").json()["code"] == "INVALID_CREDENTIALS"


def test_step_up_expires(client):
    c = signed_in()
    PlatformSession.objects.update(mfa_at=timezone.now() - timedelta(minutes=10))
    r = call(c, "put", "markets/ZW", {"status": "SANDBOX"})
    assert r.status_code == 403  # superadmin: FORBIDDEN before step-up
    owner = signed_in(Role.OWNER)
    PlatformSession.objects.filter(staff=owner.staff).update(
        mfa_at=timezone.now() - timedelta(minutes=10)
    )
    assert call(owner, "put", "markets/ZW", {"status": "SANDBOX"}).json()["code"] == (
        "STEP_UP_REQUIRED"
    )
    assert assert_passkey(owner, owner.key).status_code == 200
    assert call(owner, "put", "markets/ZW", {"status": "SANDBOX"}).status_code == 200


# ---- Authorization matrix (AC-ADM-1) and route inventory (AC-ADM-2) ---------------------------

MATRIX = [
    ("get", "overview", "overview.read"),
    ("get", "markets", "markets.read"),
    ("put", "markets/QQ", "markets.write"),
    ("get", "operators", "operators.read"),
    ("post", "operators", "operators.manage"),
    ("get", "operators/op_x", "operators.read"),
    ("post", "operators/op_x/suspend", "operators.manage"),
    ("post", "operators/op_x/promote", "operators.manage"),
    ("post", "operators/op_x/credentials/k_x/revoke", "credentials.manage"),
    ("get", "finance/pending", "finance.read"),
    ("post", "finance/transactions/tx_x/retry", "finance.retry"),
    ("get", "finance/bets", "finance.read"),
    ("get", "finance/bets?player_id=p", "players.search"),
    ("get", "finance/bets/bet_x", "finance.read"),
    ("get", "finance/discrepancies", "finance.read"),
    ("post", "finance/discrepancies/x/resolve", "reconciliation.resolve"),
    ("get", "rounds", "overview.read"),
    ("get", "rounds/x", "overview.read"),
    ("get", "staff", "staff.manage"),
    ("post", "staff", "staff.manage"),
    ("patch", "staff/x", "staff.manage"),
    ("post", "staff/x/reset-passkeys", "staff.manage"),
    ("get", "audit", "audit.read"),
    ("get", "audit/verify", "audit.read"),
]
# Routes whose permission is decided inside the view (per action) or needs only a session.
SELF_CHECKED = {
    "auth/login",
    "auth/passkey/options",
    "auth/passkey/verify",
    "auth/passkey/register/options",
    "auth/passkey/register",
    "auth/logout",
    "me",
    "me/password",
    "approvals",
    "approvals/<str:approval_id>/<str:decision>",
    "operators/<str:op_id>/approvals",
}


def _route_of(path):
    path = path.split("?")[0]
    for p in console_urls.urlpatterns:
        if isinstance(p, URLPattern) and p.resolve(path):
            return str(p.pattern)
    raise AssertionError(path)


def test_every_route_is_in_the_matrix_or_self_checked():
    routes = {str(p.pattern) for p in console_urls.urlpatterns if isinstance(p, URLPattern)}
    covered = {_route_of(path) for _, path, _ in MATRIX}
    assert routes - covered - SELF_CHECKED == set(), "new admin route without a matrix entry"


def test_no_route_can_write_round_data():
    for p in console_urls.urlpatterns:
        if "round" in str(p.pattern):
            assert p.callback.__name__ in {"rounds", "round_detail"}
    c = signed_in(Role.OWNER)
    for method in ("post", "put", "patch", "delete"):
        for path in ("rounds", "rounds/00000000-0000-0000-0000-000000000000"):
            assert call(c, method, path).status_code == 405


@pytest.mark.parametrize("role", list(Role))
def test_authorization_matrix(role):
    c = signed_in(role)
    for method, path, perm in MATRIX:
        r = call(c, method, path, {})
        allowed = role in PERMISSIONS[perm]
        code = r.json().get("code") if r.headers.get("content-type", "").endswith("json") else None
        if allowed:
            assert code != "FORBIDDEN", f"{role} should reach {method} {path}"
        else:
            assert r.status_code == 403 and code == "FORBIDDEN", f"{role} reached {method} {path}"


# ---- Markets (owner only) ---------------------------------------------------------------------


def test_only_the_owner_changes_markets_and_closing_real_revokes_sessions(client):
    demo = make_operator("Market Op")
    Market.objects.filter(country_code="ZW").update(status="REAL")
    op = demo.operator
    op.status, op.real_money_enabled = "LIVE", True
    op.wallet_kind, op.wallet_base_url = "SEAMLESS_V1", "http://127.0.0.1:9/wallet"
    op.save()
    body = json.dumps(
        {
            "player": {"id": "p-real", "country": "ZW"},
            "currency": "USD",
            "game": "lux-rocket",
            "mode": "REAL",
        }
    ).encode()
    path = "/operator/v1/sessions"
    r = client.post(path, body, content_type="application/json", **demo.headers("POST", path, body))
    assert r.status_code == 201
    sa = signed_in(Role.SUPERADMIN)
    assert call(sa, "put", "markets/ZW", {"status": "SANDBOX"}).status_code == 403
    owner = signed_in(Role.OWNER)
    assert (
        call(owner, "put", "markets/ZW", {"status": "REAL"}).json()["code"] == "EVIDENCE_REQUIRED"
    )
    assert call(owner, "put", "markets/ZW", {"status": "SANDBOX"}).status_code == 200
    s = GameSession.objects.get(mode="REAL")
    assert s.status == "REVOKED" and s.revoked_reason == "MARKET_CLOSED"
    event = AuditEvent.objects.filter(action="market.changed").last()
    assert event.data["before"]["status"] == "REAL" and event.data["sessions_revoked"] == 1


# ---- Operators and four-eyes ------------------------------------------------------------------


def _ready_for_real_money(op: Operator):
    Market.objects.filter(country_code="ZW").update(status="REAL", evidence_ref="licence-1")
    op.wallet_kind, op.wallet_base_url = "SEAMLESS_V1", "https://wallet.op.test"
    op.wallet_conformance_passed_at = timezone.now()
    op.save()


EVIDENCE = {
    "contract_ref": "C-1",
    "licence_ref": "L-1",
    "certification_ref": "GLI-1",
    "security_signoff_ref": "SEC-1",
}


def test_real_money_needs_two_different_people(client):
    op = make_operator("Go Live Op").operator
    requester = signed_in(Role.SUPERADMIN, "req@lux.test")
    r = call(
        requester,
        "post",
        f"operators/{op.public_id}/approvals",
        {"action": "ENABLE_REAL_MONEY", "reason": "go live", "payload": EVIDENCE},
    )
    assert r.json()["code"] == "PRECONDITION_FAILED"  # no conformance yet
    _ready_for_real_money(op)
    missing = call(
        requester,
        "post",
        f"operators/{op.public_id}/approvals",
        {"action": "ENABLE_REAL_MONEY", "reason": "go live", "payload": {}},
    )
    assert "missing evidence" in missing.json()["detail"]
    r = call(
        requester,
        "post",
        f"operators/{op.public_id}/approvals",
        {"action": "ENABLE_REAL_MONEY", "reason": "go live", "payload": EVIDENCE},
    )
    assert r.status_code == 201
    approval_id = r.json()["id"]
    assert (
        call(requester, "post", f"approvals/{approval_id}/approve", {"note": "me"}).json()["code"]
        == "SELF_APPROVAL"
    )
    finance = signed_in(Role.FINANCE, "fin@lux.test")
    assert (
        call(finance, "post", f"approvals/{approval_id}/approve", {"note": "x"}).json()["code"]
        == "FORBIDDEN"
    )
    risk = signed_in(Role.RISK, "risk@lux.test")
    assert call(risk, "post", f"approvals/{approval_id}/approve", {}).json()["code"] == (
        "NOTE_REQUIRED"
    )
    assert (
        call(
            risk, "post", f"approvals/{approval_id}/approve", {"note": "evidence checked"}
        ).status_code
        == 200
    )
    op.refresh_from_db()
    assert op.real_money_enabled and op.status == "LIVE"
    assert AuditEvent.objects.filter(action="approval.approved").count() == 1


def test_the_database_refuses_self_approval_too():
    op = make_operator().operator
    s = make_staff("self@lux.test")
    a = ApprovalRequest.objects.create(
        action="REACTIVATE_OPERATOR", operator=op, reason="r", requested_by=s
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        ApprovalRequest.objects.filter(pk=a.pk).update(decided_by=s, status="APPROVED")


def test_suspend_is_immediate_and_reactivation_is_four_eyes(client, sandbox_world):  # noqa: F811
    op = sandbox_world["demo"].operator
    ops = signed_in(Role.OPS, "ops@lux.test")
    assert call(ops, "post", f"operators/{op.public_id}/suspend", {}).json()["code"] == (
        "REASON_REQUIRED"
    )
    r = call(ops, "post", f"operators/{op.public_id}/suspend", {"reason": "credential leak"})
    assert r.status_code == 200
    assert GameSession.objects.get(public_id=sandbox_world["session_id"]).status == "REVOKED"
    assert bet(client, sandbox_world)["code"] == "SESSION_INACTIVE"
    req = call(
        ops,
        "post",
        f"operators/{op.public_id}/approvals",
        {"action": "REACTIVATE_OPERATOR", "reason": "keys rotated"},
    )
    assert req.status_code == 201
    assert (
        call(ops, "post", f"approvals/{req.json()['id']}/approve", {"note": "x"}).json()["code"]
        == "SELF_APPROVAL"
    )
    sa = signed_in(Role.SUPERADMIN, "sa@lux.test")
    assert (
        call(
            sa, "post", f"approvals/{req.json()['id']}/approve", {"note": "rotation verified"}
        ).status_code
        == 200
    )
    op.refresh_from_db()
    assert op.status == "SANDBOX"


def test_onboarding_creates_operator_and_first_portal_owner(client):
    Market.objects.get_or_create(country_code="ZW", defaults={"status": "SANDBOX"})
    Market.objects.get_or_create(country_code="FR", defaults={"status": "DISABLED"})
    ops = signed_in(Role.OPS, "ops@lux.test")
    payload = {
        "legal_name": "New Casino Ltd",
        "owner_email": "owner@newcasino.test",
        "jurisdictions": ["ZW"],
        "currencies": [
            {
                "currency": "USD",
                "min_stake": 10,
                "max_stake": 10000,
                "max_win": 1000000,
                "round_exposure": 50000000,
            }
        ],
    }
    closed = call(ops, "post", "operators", payload | {"jurisdictions": ["FR"]})
    assert closed.json()["code"] == "JURISDICTION_NOT_PERMITTED"
    bad = call(
        ops,
        "post",
        "operators",
        payload
        | {
            "currencies": [
                {
                    "currency": "USD",
                    "min_stake": 100,
                    "max_stake": 10,
                    "max_win": 1,
                    "round_exposure": 1,
                }
            ]
        },
    )
    assert (
        bad.status_code == 422 and not Operator.objects.filter(legal_name="New Casino Ltd").exists()
    )
    r = call(ops, "post", "operators", payload)
    assert r.status_code == 201 and r.json()["status"] == "SANDBOX"
    assert len(r.json()["owner_temporary_password"]) >= 12
    owner = StaffUser.objects.get(email="owner@newcasino.test")
    assert owner.role == "OP_OWNER" and owner.must_change_password
    detail = call(ops, "get", f"operators/{r.json()['id']}").json()
    assert "owner_temporary_password" not in detail


# ---- Finance ---------------------------------------------------------------------------------


def test_retry_re_drives_a_stuck_credit(client, sandbox_world):  # noqa: F811
    w = sandbox_world
    a = bet(client, w)
    from tests.test_money_path import send

    send(client, w["sim"].admitted(a["bet_id"]), w["sim"].launched())
    send(client, w["sim"].cashout(a["bet_id"], 20_000, 1000))
    WalletTransaction.objects.filter(type="CREDIT").update(status="NEEDS_ATTENTION")
    fin = signed_in(Role.FINANCE, "fin@lux.test")
    pending = call(fin, "get", "finance/pending").json()["transactions"]
    credit = WalletTransaction.objects.get(type="CREDIT")
    assert [t["transaction_id"] for t in pending] == [tx_public_id(credit.id)]
    r = call(fin, "post", f"finance/transactions/{tx_public_id(credit.id)}/retry")
    assert r.status_code == 200 and r.json()["status"] == "UNKNOWN"
    assert call(fin, "post", "finance/transactions/tx_bogus/retry").status_code == 404
    timeline = call(fin, "get", f"finance/bets/{a['bet_id']}").json()
    assert timeline["ledger"] and timeline["attempts"]


def test_player_search_is_audited_and_support_sees_masked_bets(client, sandbox_world):  # noqa: F811
    bet(client, sandbox_world)
    risk = signed_in(Role.RISK, "risk@lux.test")
    rows = call(risk, "get", "finance/bets?player_id=alice").json()["bets"]
    assert rows and rows[0]["player_id"] == "alice"
    assert AuditEvent.objects.filter(action="player.searched", target="alice").exists()
    support = signed_in(Role.SUPPORT, "support@lux.test")
    assert "player_id" not in call(support, "get", "finance/bets").json()["bets"][0]


def test_resolving_a_discrepancy_needs_a_note(client):
    run = ReconciliationRun.objects.create(kind="INTERNAL")
    d = Discrepancy.objects.create(
        run=run, kind="X", severity="CRITICAL", subject="s", status="OPEN"
    )
    fin = signed_in(Role.FINANCE, "fin@lux.test")
    assert call(fin, "post", f"finance/discrepancies/{d.id}/resolve").status_code == 422
    assert (
        call(
            fin,
            "post",
            f"finance/discrepancies/{d.id}/resolve",
            {"note": "operator confirmed credit landed"},
        ).status_code
        == 200
    )
    d.refresh_from_db()
    assert d.status == "RESOLVED" and d.resolved_by == "fin@lux.test"


# ---- Staff and audit -------------------------------------------------------------------------


def test_staff_rules(client):
    owner = signed_in(Role.OWNER)
    sa = signed_in(Role.SUPERADMIN, "sa1@lux.test")
    assert (
        call(sa, "post", "staff", {"email": "o2@lux.test", "role": "PLAT_OWNER"}).status_code == 403
    )
    assert (
        call(sa, "post", "staff", {"email": "s@lux.test", "role": "PLAT_SUPERADMIN"}).status_code
        == 403
    )
    for i in (2, 3):
        assert (
            call(
                owner, "post", "staff", {"email": f"sa{i}@lux.test", "role": "PLAT_SUPERADMIN"}
            ).status_code
            == 201
        )
    assert (
        call(owner, "post", "staff", {"email": "sa4@lux.test", "role": "PLAT_SUPERADMIN"}).json()[
            "code"
        ]
        == "SUPERADMIN_CAP"
    )
    r = call(sa, "post", "staff", {"email": "aud@lux.test", "role": "PLAT_AUDITOR"})
    assert r.status_code == 201 and r.json()["temporary_password"]
    assert call(sa, "patch", f"staff/{sa.staff.id}", {"status": "DISABLED"}).status_code == 403
    assert call(sa, "patch", f"staff/{owner.staff.id}", {"status": "DISABLED"}).status_code == 403
    target = PlatformStaff.objects.get(email="aud@lux.test")
    assert call(sa, "post", f"staff/{target.id}/reset-passkeys").status_code == 200


def test_audit_chain_verification_endpoint(client):
    owner = signed_in(Role.OWNER)
    call(owner, "put", "markets/ZW", {"status": "SANDBOX"})
    r = call(owner, "get", "audit/verify").json()
    assert r["ok"] is True and r["events"] >= 2
    assert audit.verify_chain() == (True, None)
    _ = create_session  # factories import kept for other tests
