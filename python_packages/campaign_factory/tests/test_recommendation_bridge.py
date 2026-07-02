from __future__ import annotations

import json

import pytest
from campaign_factory import recommendation_bridge


def test_next_batch_request_from_env_parses_json_payload():
    request = json.dumps({"campaign": "may", "count": 2})

    assert recommendation_bridge.next_batch_request_from_env(
        {recommendation_bridge.NEXT_BATCH_REQUEST_ENV: request}
    ) == ("may", 2)


def test_next_batch_request_from_env_rejects_missing_campaign():
    request = json.dumps({"campaign": "", "count": 2})

    with pytest.raises(ValueError, match="campaign"):
        recommendation_bridge.next_batch_request_from_env(
            {recommendation_bridge.NEXT_BATCH_REQUEST_ENV: request}
        )


def test_recommend_next_batch_from_env_closes_factory(monkeypatch):
    calls = []

    class FakeCampaignFactory:
        def __init__(self, settings):
            calls.append(("init", settings))

        def recommend_next_batch(self, campaign, *, count, persist):
            calls.append(("recommend", campaign, count, persist))
            return {"items": [{"recommendationId": "recitem_1"}]}

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(
        recommendation_bridge, "get_settings", lambda: {"db": "settings"}
    )
    monkeypatch.setattr(recommendation_bridge, "CampaignFactory", FakeCampaignFactory)

    result = recommendation_bridge.recommend_next_batch_from_env(
        {
            recommendation_bridge.NEXT_BATCH_REQUEST_ENV: json.dumps(
                {"campaign": "may", "count": 2}
            )
        }
    )

    assert result == {"items": [{"recommendationId": "recitem_1"}]}
    assert calls == [
        ("init", {"db": "settings"}),
        ("recommend", "may", 2, False),
        ("close",),
    ]
