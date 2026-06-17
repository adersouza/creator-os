from __future__ import annotations

from fastapi.testclient import TestClient

from reference_factory.server import create_app


def test_non_loopback_request_without_token_is_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)
    client = TestClient(create_app(tmp_path / "reference.sqlite"), client=("10.10.10.10", 50000))

    response = client.get("/")

    assert response.status_code == 401


def test_valid_bearer_token_is_accepted(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.setenv("CREATOR_OS_API_TOKEN", "test-token")
    client = TestClient(create_app(tmp_path / "reference.sqlite"), client=("10.10.10.10", 50000))

    response = client.get("/", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200


def test_explicit_insecure_loopback_dev_is_accepted(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)
    client = TestClient(create_app(tmp_path / "reference.sqlite"), client=("127.0.0.1", 50000))

    response = client.get("/")

    assert response.status_code == 200


def test_framework_routes_without_token_are_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("CREATOR_OS_API_TOKEN", raising=False)
    client = TestClient(create_app(tmp_path / "reference.sqlite"), client=("10.10.10.10", 50000))

    for path in ("/docs", "/openapi.json"):
        response = client.get(path)

        assert response.status_code == 401
