"""Loopback and bearer-token rules for the shared local API auth middleware.

These previously ran against campaign_factory's local API. That surface was
removed, but the middleware still guards reference_factory's server, so the
rules are exercised here against a minimal app instead of losing the coverage.
"""

from __future__ import annotations

from creator_os_core.local_api_auth import install_local_api_auth_middleware
from fastapi import FastAPI
from fastapi.testclient import TestClient

REMOTE = ("10.10.10.10", 50000)
LOOPBACK = ("127.0.0.1", 50000)


def _app() -> FastAPI:
    app = FastAPI()
    install_local_api_auth_middleware(app)

    @app.get("/")
    def index() -> dict[str, str]:
        return {"service": "test"}

    return app


def test_non_loopback_request_without_token_is_rejected(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)

    response = TestClient(_app(), client=REMOTE).get("/")

    assert response.status_code == 401


def test_valid_bearer_token_is_accepted(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.setenv("CREATOR_OS_API_TOKEN", "test-token")

    response = TestClient(_app(), client=REMOTE).get(
        "/", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    assert response.json() == {"service": "test"}


def test_explicit_insecure_loopback_dev_is_accepted(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)

    response = TestClient(_app(), client=LOOPBACK).get("/")

    assert response.status_code == 200


def test_framework_and_static_routes_without_token_are_rejected(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)
    client = TestClient(_app(), client=REMOTE)

    for path in ("/docs", "/openapi.json", "/static/index.html"):
        assert client.get(path).status_code == 401


def test_no_static_dashboard_is_served(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    client = TestClient(_app(), client=LOOPBACK)

    assert client.get("/static/index.html").status_code == 404
    assert client.get("/favicon.ico").status_code == 404
