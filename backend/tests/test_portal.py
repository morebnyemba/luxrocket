"""Operator portal: auth, MFA, step-up, RBAC, audit chain and cross-tenant isolation (doc 13)."""

import json
import time
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.contrib.auth.hashers import make_password
from django.db import DatabaseError, connection, transaction
from django.test import Client
from django.urls import URLPattern
from django.utils import timezone

from luxrocket.core.lr1 import b64url
from luxrocket.core.multiplier import payout_minor
from luxrocket.operators.models import OperatorCredential, WebhookDelivery, WebhookEndpoint
from luxrocket.portal import audit, totp
from luxrocket.portal import urls as portal_urls
from luxrocket.portal.models import AuditEvent, StaffSession, StaffUser
from luxrocket.wallet.models import Discrepancy, ReconciliationRun
from tests.factories import make_operator
from tests.test_money_path import bet, send
from tests.test_money_path import world as sandbox_world  # noqa: F401 (fixture)

pytestmark = pytest.mark.django_db
API = "/api/portal/v1"
PASSWORD = "correct horse battery"
H = {"HTTP_X_LR_PORTAL": "1"}


def staff(operator, email, role="OP_OWNER", *, change=False):
    return StaffUser.objects.create(
        operator=operator,
        email=email,
        role=role,
        password_hash=make_password(PASSWORD),
        must_change_password=change,
    )


def login(client, email, password=PASSWORD):
    return client.post(
        f"{API}/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
        **H,
    )


def post(client, path, data=None, method="post"):
    return getattr(client, method)(
        f"{API}/{path}", json.dumps(data or {}), content_type="application/json", **H
    )


def enroll(client):
    secret = post(client, "me/mfa/setup").json()["secret"]
    raw = __import__("base64").b32decode(secret + "=" * (-len(secret) % 8))
    code = totp.code_at(raw, int(time.time() // 30))
    assert post(client, "me/mfa/enable", {"code": code}).status_code == 200
    return raw


def next_code(raw):
    return totp.code_at(raw, int(time.time() // 30) + 1)


@pytest.fixture
def owner_client(db):
    demo = make_operator("Portal Op")
    staff(demo.operator, "owner@op.test")
    c = Client()
    assert login(c, "owner@op.test").status_code == 200
    return c, demo


# ---- Authentication --------------------------------------------------------------------------


def test_bad_password_locks_after_five(client):
    demo = make_operator()
    staff(demo.operator, "a@op.test")
    for _ in range(5):
        assert login(client, "a@op.test", "wrong").status_code == 401
    assert login(client, "a@op.test").status_code == 429
    assert AuditEvent.objects.filter(action="auth.login_failed").count() == 5


def test_unknown_user_and_wrong_password_look_the_same(client):
    demo = make_operator()
    staff(demo.operator, "a@op.test")
    a = login(client, "nobody@op.test")
    b = login(client, "a@op.test", "wrong")
    assert a.status_code == b.status_code == 401 and a.json()["code"] == b.json()["code"]


def test_login_requires_the_portal_header(client):
    demo = make_operator()
    staff(demo.operator, "a@op.test")
    r = client.post(
        f"{API}/auth/login",
        {"email": "a@op.test", "password": PASSWORD},
        content_type="application/json",
    )
    assert r.status_code == 403


def test_cookie_is_host_only_strict_and_httponly(client):
    demo = make_operator()
    staff(demo.operator, "a@op.test")
    r = login(client, "a@op.test")
    cookie = r.cookies["__Host-lr_portal"]
    assert cookie["httponly"] and cookie["secure"] and cookie["samesite"] == "Strict"
    assert cookie["path"] == "/" and not cookie["domain"]


def test_temporary_password_must_be_changed_first(client):
    demo = make_operator()
    staff(demo.operator, "new@op.test", change=True)
    assert login(client, "new@op.test").json()["must_change_password"] is True
    assert client.get(f"{API}/overview").json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert client.get(f"{API}/me").status_code == 200
    weak = post(client, "me/password", {"current": PASSWORD, "new": "short"})
    assert weak.status_code == 422
    ok = post(client, "me/password", {"current": PASSWORD, "new": "a much longer passphrase"})
    assert ok.status_code == 200
    assert client.get(f"{API}/overview").status_code == 200


def test_mfa_login_and_codes_are_single_use(owner_client):
    c, _ = owner_client
    raw = enroll(c)
    post(c, "auth/logout")
    r = login(c, "owner@op.test")
    assert r.json()["mfa_required"] is True
    assert c.get(f"{API}/overview").json()["code"] == "MFA_REQUIRED"
    assert post(c, "auth/mfa", {"code": "000000"}).status_code == 401
    code = next_code(raw)
    assert post(c, "auth/mfa", {"code": code}).status_code == 200
    assert c.get(f"{API}/overview").status_code == 200
    assert post(c, "auth/mfa", {"code": code}).status_code == 401  # replay refused


def test_mfa_secret_is_encrypted_at_rest(owner_client):
    c, _ = owner_client
    raw = enroll(c)
    stored = bytes(StaffUser.objects.get().totp_secret_enc)
    assert raw not in stored and totp.decrypt(stored) == raw


def test_logout_revokes_the_session(owner_client):
    c, _ = owner_client
    post(c, "auth/logout")
    assert c.get(f"{API}/me").status_code == 401
    assert StaffSession.objects.filter(revoked_at__isnull=False).count() == 1


def test_idle_sessions_expire(owner_client, settings):
    c, _ = owner_client
    StaffSession.objects.update(last_seen_at=timezone.now() - timedelta(hours=1))
    assert c.get(f"{API}/me").status_code == 401


# ---- Step-up, RBAC, CSRF --------------------------------------------------------------------


def _pubkey():
    key = Ed25519PrivateKey.generate().public_key()
    return b64url(key.public_bytes(Encoding.Raw, PublicFormat.Raw))


def test_credentials_need_enrolled_and_fresh_mfa(owner_client):
    c, _ = owner_client
    r = post(c, "credentials", {"public_key": _pubkey()})
    assert r.json()["code"] == "MFA_ENROLLMENT_REQUIRED"
    enroll(c)
    r = post(c, "credentials", {"public_key": _pubkey()})
    assert r.status_code == 201 and "public_key" not in r.json()
    StaffSession.objects.update(mfa_at=timezone.now() - timedelta(minutes=30))
    assert post(c, "credentials", {"public_key": _pubkey()}).json()["code"] == "STEP_UP_REQUIRED"


def test_credential_rotation_rules(owner_client):
    c, demo = owner_client
    enroll(c)
    assert post(c, "credentials", {"public_key": _pubkey()}).status_code == 201  # 2nd active
    assert post(c, "credentials", {"public_key": _pubkey()}).json()["code"] == "CREDENTIAL_LIMIT"
    assert post(c, "credentials", {"public_key": "not-a-key"}).status_code == 422
    kids = list(
        OperatorCredential.objects.filter(operator=demo.operator).values_list("kid", flat=True)
    )
    assert post(c, f"credentials/{kids[0]}/revoke").status_code == 200
    assert post(c, f"credentials/{kids[1]}/revoke").json()["code"] == "LAST_ACTIVE_KEY"
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {"credential.created", "credential.revoked"} <= actions


def test_mutations_without_the_portal_header_are_rejected(owner_client):
    c, _ = owner_client
    r = c.post(f"{API}/webhooks", {"url": "https://x.test/h"}, content_type="application/json")
    assert r.status_code == 403 and r.json()["code"] == "CSRF_REJECTED"
    r = c.post(
        f"{API}/webhooks",
        {"url": "https://x.test/h"},
        content_type="application/json",
        HTTP_ORIGIN="https://evil.example",
        **H,
    )
    assert r.json()["code"] == "CSRF_REJECTED"


def test_viewer_sees_no_player_detail_and_no_team(client, sandbox_world):  # noqa: F811
    staff(sandbox_world["demo"].operator, "viewer@op.test", role="OP_VIEWER")
    bet(client, sandbox_world)
    c = Client()
    login(c, "viewer@op.test")
    rows = c.get(f"{API}/bets").json()["bets"]
    assert rows and "player_id" not in rows[0]
    assert c.get(f"{API}/bets?player_id=alice").status_code == 403
    assert c.get(f"{API}/users").status_code == 403
    assert c.get(f"{API}/audit").status_code == 403
    assert "users.manage" not in c.get(f"{API}/me").json()["permissions"]


def test_admins_cannot_mint_or_demote_owners(client):
    demo = make_operator()
    owner = staff(demo.operator, "owner@op.test")
    staff(demo.operator, "admin@op.test", role="OP_ADMIN")
    c = Client()
    login(c, "admin@op.test")
    enroll(c)
    assert post(c, "users", {"email": "x@op.test", "role": "OP_OWNER"}).status_code == 403
    assert post(c, f"users/{owner.id}", {"role": "OP_VIEWER"}, "patch").status_code == 403
    r = post(c, "users", {"email": "dev@op.test", "role": "OP_DEVELOPER"})
    assert r.status_code == 201 and len(r.json()["temporary_password"]) >= 12
    assert "temporary_password" not in json.dumps(c.get(f"{API}/users").json())


def test_disabling_kills_sessions_and_nobody_edits_themselves(owner_client):
    c, demo = owner_client
    enroll(c)
    other = staff(demo.operator, "owner2@op.test")
    c2 = Client()
    login(c2, "owner2@op.test")
    assert post(c, f"users/{other.id}", {"status": "DISABLED"}, "patch").status_code == 200
    assert c2.get(f"{API}/me").status_code == 401
    assert login(c2, "owner2@op.test").status_code == 401
    me = StaffUser.objects.get(email="owner@op.test")
    assert post(c, f"users/{me.id}", {"role": "OP_VIEWER"}, "patch").status_code == 403
    assert post(c, f"users/{me.id}/reset-mfa").status_code == 403


# ---- Reporting -------------------------------------------------------------------------------


def test_overview_totals_match_the_ledger(client, sandbox_world):  # noqa: F811
    w = sandbox_world
    staff(w["demo"].operator, "fin@op.test", role="OP_FINANCE")
    a = bet(client, w, panel=0, stake="500")
    b = bet(client, w, panel=1, stake="300")
    send(
        client, w["sim"].admitted(a["bet_id"]), w["sim"].admitted(b["bet_id"]), w["sim"].launched()
    )
    send(client, w["sim"].cashout(a["bet_id"], 20_000, payout_minor(500, 20_000)))
    send(client, w["sim"].crashed())
    c = Client()
    login(c, "fin@op.test")
    (usd,) = c.get(f"{API}/overview").json()["currencies"]
    assert usd["turnover"] == "800" and usd["payouts"] == "1000"
    assert int(usd["ggr"]) == int(usd["turnover"]) - int(usd["payouts"]) == -200
    assert usd["rtp_bp"] == 12500
    detail = c.get(f"{API}/bets/{a['bet_id']}").json()
    assert detail["settlement"]["outcome"] == "WIN" and detail["attempts"]


# ---- Audit chain ----------------------------------------------------------------------------


def test_audit_chain_is_append_only_and_tamper_evident(owner_client):
    c, _ = owner_client
    enroll(c)
    post(c, "credentials", {"public_key": _pubkey()})
    assert audit.verify_chain() == (True, None)
    first = AuditEvent.objects.order_by("seq").first()
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditEvent.objects.filter(pk=first.pk).update(action="nothing.to.see")
    with connection.cursor() as cur:  # an attacker with DDL rights
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cur.execute("ALTER TABLE platform.portal_auditevent DISABLE TRIGGER audit_no_update_delete")
        cur.execute(
            "UPDATE platform.portal_auditevent SET actor='someone-else' WHERE seq=%s", [first.seq]
        )
        cur.execute("ALTER TABLE platform.portal_auditevent ENABLE TRIGGER audit_no_update_delete")
    assert audit.verify_chain() == (False, first.seq)


# ---- Cross-tenant isolation (AC-OP-1) -------------------------------------------------------

# Every parameterised route, the method that acts on it, and how to fetch a victim's id.
CROSS_TENANT = {
    "bets/<str:bet_id>": ("get", lambda v: v["bet_id"]),
    "me/sessions/<str:session_id>/revoke": ("post", lambda v: v["session_id"]),
    "credentials/<str:kid>/revoke": ("post", lambda v: v["kid"]),
    "webhooks/<str:endpoint_id>/disable": ("post", lambda v: v["endpoint_id"]),
    "webhook-deliveries/<str:delivery_id>/replay": ("post", lambda v: v["delivery_id"]),
    "users/<str:user_id>": ("patch", lambda v: v["user_id"]),
    "users/<str:user_id>/reset-mfa": ("post", lambda v: v["user_id"]),
}
LISTS = [
    "bets",
    "rounds",
    "discrepancies",
    "credentials",
    "webhooks",
    "webhook-deliveries",
    "users",
    "audit",
    "overview",
    "wallet",
    "me/sessions",
]


def test_every_portal_route_is_in_the_isolation_inventory():
    routes = {str(p.pattern) for p in portal_urls.urlpatterns if isinstance(p, URLPattern)}
    parameterised = {r for r in routes if "<" in r}
    assert parameterised == set(CROSS_TENANT), "new route without a cross-tenant test"
    plain = routes - parameterised
    auth_only = {
        "auth/login",
        "auth/mfa",
        "auth/logout",
        "me",
        "me/password",
        "me/mfa/setup",
        "me/mfa/enable",
        "wallet/conformance",
    }
    assert plain - auth_only == set(LISTS), "new list route without a cross-tenant test"


def test_operator_b_cannot_reach_operator_a(client, sandbox_world):  # noqa: F811
    # Victim: operator A with data of every kind.
    a = sandbox_world["demo"].operator
    victim_user = staff(a, "victim@op.test")
    va = Client()
    login(va, "victim@op.test")
    b_ = bet(client, sandbox_world)
    endpoint = WebhookEndpoint.objects.create(operator=a, url="https://a.test/hooks")
    delivery = WebhookDelivery.objects.create(
        event_id="evt_x",
        endpoint=endpoint,
        operator=a,
        type="bet.settled",
        payload={},
        next_attempt_at=timezone.now(),
    )
    run = ReconciliationRun.objects.create(kind="INTERNAL")
    Discrepancy.objects.create(
        run=run, operator=a, kind="X", severity="CRITICAL", subject=b_["bet_id"], status="OPEN"
    )
    victim = {
        "bet_id": b_["bet_id"],
        "session_id": str(StaffSession.objects.get(user=victim_user).id),
        "kid": OperatorCredential.objects.filter(operator=a).first().kid,
        "endpoint_id": str(endpoint.id),
        "delivery_id": str(delivery.id),
        "user_id": str(victim_user.id),
    }
    # Attacker: owner of operator B with a fresh second factor (maximum privilege).
    other = make_operator("Operator B")
    staff(other.operator, "attacker@op.test")
    atk = Client()
    login(atk, "attacker@op.test")
    enroll(atk)

    for route, (method, pick) in CROSS_TENANT.items():
        path = route.split("<")[0] + pick(victim) + route.split(">", 1)[1]
        r = (
            post(atk, path, {"role": "OP_VIEWER"}, method)
            if method != "get"
            else atk.get(f"{API}/{path}")
        )
        assert r.status_code == 404, f"{route}: {r.status_code}"

    secrets_of_a = [str(v) for v in victim.values()] + ["victim@op.test", "https://a.test/hooks"]
    for route in LISTS:
        body = atk.get(f"{API}/{route}").content.decode()
        leaked = [s for s in secrets_of_a if s in body]
        assert not leaked, f"{route} leaked {leaked}"
    # And nothing was changed on A's side.
    assert WebhookEndpoint.objects.get(pk=endpoint.pk).enabled
    assert StaffUser.objects.get(pk=victim_user.pk).role == "OP_OWNER"
    assert va.get(f"{API}/me").status_code == 200
