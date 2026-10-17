import threading

import pytest
from django.db import connection

from tests.factories import INTERNAL, create_session, make_operator

pytestmark = pytest.mark.django_db


def exchange(client, token):
    return client.post(
        "/game/v1/sessions/exchange", {"launch_token": token}, content_type="application/json"
    )


def test_launch_token_is_single_use(client):
    demo = make_operator()
    token = create_session(client, demo)["launch_token"]
    first = exchange(client, token)
    assert first.status_code == 200
    body = first.json()
    assert body["session"]["currency"] == "USD"
    assert body["balance"] == "100000"
    assert exchange(client, token).status_code == 401


def test_game_token_and_ws_ticket_flow(client):
    demo = make_operator()
    token = create_session(client, demo)["launch_token"]
    game_token = exchange(client, token).json()["game_session_token"]
    auth = {"HTTP_AUTHORIZATION": f"Bearer {game_token}"}
    ticket = client.post("/game/v1/ws-tickets", **auth).json()["ticket"]
    consumed = client.post(
        "/internal/v1/ws-tickets/consume",
        {"ticket": ticket},
        content_type="application/json",
        **INTERNAL,
    )
    assert consumed.status_code == 200
    assert consumed.json()["session"]["panels"] == 2
    again = client.post(
        "/internal/v1/ws-tickets/consume",
        {"ticket": ticket},
        content_type="application/json",
        **INTERNAL,
    )
    assert again.status_code == 401


def test_internal_api_requires_service_token(client):
    r = client.post(
        "/internal/v1/ws-tickets/consume", {"ticket": "x"}, content_type="application/json"
    )
    assert r.status_code == 401


def test_revoked_session_token_stops_working(client):
    demo = make_operator()
    data = create_session(client, demo)
    game_token = exchange(client, data["launch_token"]).json()["game_session_token"]
    auth = {"HTTP_AUTHORIZATION": f"Bearer {game_token}"}
    assert client.get("/game/v1/config", **auth).status_code == 200
    path = f"/operator/v1/sessions/{data['session_id']}/revoke"
    assert (
        client.post(
            path, b"", content_type="application/json", **demo.headers("POST", path, b"")
        ).status_code
        == 200
    )
    assert client.get("/game/v1/config", **auth).status_code == 401


@pytest.mark.django_db(transaction=True)
def test_parallel_exchanges_have_exactly_one_winner(client):
    demo = make_operator()
    token = create_session(client, demo)["launch_token"]
    from django.test import Client

    results = []

    def attempt():
        try:
            results.append(
                Client()
                .post(
                    "/game/v1/sessions/exchange",
                    {"launch_token": token},
                    content_type="application/json",
                )
                .status_code
            )
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results).count(200) == 1
    assert results.count(401) == 11
