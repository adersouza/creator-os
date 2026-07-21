from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from campaign_factory import app as app_module
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "handler",
    [
        app_module.accept_recommendation,
        app_module.reject_recommendation,
        app_module.measure_recommendation,
        app_module.execute_recommendation,
        app_module.resolve_exception,
        app_module.snooze_exception,
        app_module.reopen_exception,
    ],
)
def test_optional_request_bodies_use_distinct_default_dicts(handler):
    body_default = inspect.signature(handler).parameters["body"].default

    assert body_default.default_factory is dict
    first = body_default.default_factory()
    second = body_default.default_factory()
    assert first == second == {}
    assert first is not second


def test_optional_request_bodies_can_be_omitted(monkeypatch):
    class Recommendations:
        def accept_recommendation_item(self, _item_id, **kwargs):
            return kwargs

        def reject_recommendation_item(self, _item_id, **kwargs):
            return kwargs

        def measure_recommendation_item(self, _item_id, **kwargs):
            return kwargs

        def execute_accepted_recommendation(self, _item_id, **kwargs):
            return kwargs

    class Exceptions:
        def resolve_exception(self, _exception_id, **kwargs):
            return kwargs

        def snooze_exception(self, _exception_id, **kwargs):
            return kwargs

        def reopen_exception(self, _exception_id, **kwargs):
            return kwargs

    class FakeFactory:
        domains = SimpleNamespace(
            recommendations=Recommendations(),
            exceptions=Exceptions(),
        )

        def close(self):
            return None

    monkeypatch.setattr(app_module, "factory", FakeFactory)
    client = TestClient(app_module.app)

    for path in (
        "/api/recommendations/item_1/accept",
        "/api/recommendations/item_1/reject",
        "/api/recommendations/item_1/measure",
        "/api/recommendations/item_1/execute",
        "/api/exceptions/exception_1/resolve",
        "/api/exceptions/exception_1/snooze",
        "/api/exceptions/exception_1/reopen",
    ):
        response = client.post(path)
        assert response.status_code == 200, (path, response.text)
