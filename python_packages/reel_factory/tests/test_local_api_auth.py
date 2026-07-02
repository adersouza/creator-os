from __future__ import annotations

import local_api_auth as local_api_auth_shim
import reel_gui
from fastapi.testclient import TestClient
from reel_factory import local_api_auth as packaged_local_api_auth


def test_top_level_local_api_auth_shim_reexports_packaged_helpers() -> None:
    assert (
        local_api_auth_shim.authorize_local_api_request
        is packaged_local_api_auth.authorize_local_api_request
    )
    assert (
        local_api_auth_shim.install_local_api_auth_middleware
        is packaged_local_api_auth.install_local_api_auth_middleware
    )
    assert (
        local_api_auth_shim.require_local_api_auth
        is packaged_local_api_auth.require_local_api_auth
    )


def test_non_loopback_request_without_token_is_rejected(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)

    client = TestClient(reel_gui.app, client=("10.10.10.10", 50000))

    response = client.get("/")

    assert response.status_code == 401


def test_valid_bearer_token_is_accepted(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.setenv("CREATOR_OS_API_TOKEN", "test-token")
    client = TestClient(reel_gui.app, client=("10.10.10.10", 50000))

    response = client.get("/", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200


def test_explicit_insecure_loopback_dev_is_accepted(monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)
    client = TestClient(reel_gui.app, client=("127.0.0.1", 50000))

    response = client.get("/")

    assert response.status_code == 200


def test_framework_and_static_routes_without_token_are_rejected(monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)
    client = TestClient(reel_gui.app, client=("10.10.10.10", 50000))

    for path in ("/docs", "/openapi.json", "/static/index.html"):
        response = client.get(path)

        assert response.status_code == 401
