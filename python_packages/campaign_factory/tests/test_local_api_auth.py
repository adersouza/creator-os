from __future__ import annotations

from campaign_factory import app as app_module
from fastapi.testclient import TestClient


def test_non_loopback_request_without_token_is_rejected(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)

    client = TestClient(app_module.app, client=("10.10.10.10", 50000))

    response = client.get("/")

    assert response.status_code == 401


def test_valid_bearer_token_is_accepted(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.setenv("CREATOR_OS_API_TOKEN", "test-token")
    client = TestClient(app_module.app, client=("10.10.10.10", 50000))

    response = client.get("/", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json() == {
        "service": "campaign_factory",
        "mode": "headless",
        "docs": "/docs",
        "operatorCommand": "scripts/creator-os",
    }


def test_explicit_insecure_loopback_dev_is_accepted(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)
    client = TestClient(app_module.app, client=("127.0.0.1", 50000))

    response = client.get("/")

    assert response.status_code == 200


def test_framework_and_static_routes_without_token_are_rejected(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)
    client = TestClient(app_module.app, client=("10.10.10.10", 50000))

    for path in ("/docs", "/openapi.json", "/static/index.html"):
        response = client.get(path)

        assert response.status_code == 401


def test_removed_static_dashboard_is_not_served(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    client = TestClient(app_module.app, client=("127.0.0.1", 50000))

    assert client.get("/static/index.html").status_code == 404
    assert client.get("/favicon.ico").status_code == 404
