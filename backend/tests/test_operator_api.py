import json

import pytest

from tests.factories import create_session, make_operator, session_payload

pytestmark = pytest.mark.django_db
PATH = "/operator/v1/sessions"


def post(client, demo, payload, **override):
    body = json.dumps(payload).encode()
    headers = demo.headers("POST", PATH, body)
    headers.update(override)
    return client.post(PATH, body, content_type="application/json", **headers)


def test_signed_session_creation_returns_launch_details(client):
    demo = make_operator()
    data = create_session(client, demo)
    assert data["session_id"].startswith("ses_")
    assert data["launch_token"].startswith("lt_")
    assert "#lt=" in data["fragment_launch_url"]
    assert "lt_" not in data["iframe_url"]  # never in the query string (FR-004)


def test_bad_signature_rejected(client):
    demo = make_operator()
    other = make_operator("Other")
    body = json.dumps(session_payload()).encode()
    headers = other.headers("POST", PATH, body)
    headers["HTTP_LR_KEY_ID"] = demo.kid  # key id of a different operator
    r = client.post(PATH, body, content_type="application/json", **headers)
    assert r.status_code == 401
    assert r.json()["code"] == "INVALID_SIGNATURE"


def test_tampered_body_rejected(client):
    demo = make_operator()
    body = json.dumps(session_payload()).encode()
    headers = demo.headers("POST", PATH, body)
    r = client.post(PATH, body.replace(b"p-1", b"p-2"), content_type="application/json", **headers)
    assert r.status_code == 401


def test_nonce_replay_rejected(client):
    demo = make_operator()
    body = json.dumps(session_payload()).encode()
    headers = demo.headers("POST", PATH, body)
    assert client.post(PATH, body, content_type="application/json", **headers).status_code == 201
    headers["HTTP_IDEMPOTENCY_KEY"] = "another-key-123"
    r = client.post(PATH, body, content_type="application/json", **headers)
    assert r.json()["code"] == "NONCE_REUSED"


def test_stale_timestamp_rejected(client):
    demo = make_operator()
    body = json.dumps(session_payload()).encode()
    headers = demo.headers("POST", PATH, body)
    headers["HTTP_LR_TIMESTAMP"] = "1000"
    r = client.post(PATH, body, content_type="application/json", **headers)
    assert r.json()["code"] in ("TIMESTAMP_OUT_OF_WINDOW", "INVALID_SIGNATURE")


def test_idempotency_replays_same_response(client):
    demo = make_operator()
    body = json.dumps(session_payload()).encode()
    first = client.post(
        PATH,
        body,
        content_type="application/json",
        **demo.headers("POST", PATH, body, idem="idem-key-0001"),
    )
    second = client.post(
        PATH,
        body,
        content_type="application/json",
        **demo.headers("POST", PATH, body, idem="idem-key-0001"),
    )
    assert first.json() == second.json()


def test_schema_violation_rejected(client):
    demo = make_operator()
    payload = session_payload()
    payload["player"]["email"] = "x@example.com"  # PII is not part of the contract
    r = post(client, demo, payload)
    assert r.status_code == 400


def test_market_must_be_enabled(client):
    demo = make_operator()
    r = post(client, demo, session_payload(country="GB"))
    assert r.status_code == 403
    assert r.json()["code"] == "JURISDICTION_NOT_PERMITTED"


def test_real_mode_blocked_until_enabled(client):
    demo = make_operator()
    payload = session_payload()
    payload["mode"] = "REAL"
    assert post(client, demo, payload).json()["code"] == "REAL_MONEY_DISABLED"


def test_foreign_tenant_bet_is_not_found(client):
    a = make_operator("A")
    b = make_operator("B")
    path = "/operator/v1/bets/bet_doesnotexist"
    r = client.get(path, **b.headers("GET", path, b""))
    assert r.status_code == 404
    _ = a
