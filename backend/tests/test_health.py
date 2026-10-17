import pytest


@pytest.mark.django_db
def test_healthz_reports_db(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": True}
