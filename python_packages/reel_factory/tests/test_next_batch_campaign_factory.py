from __future__ import annotations

import types
import sys

from next_batch import campaign_factory_next_batch


def test_campaign_factory_next_batch_prefers_canonical_recommendations(monkeypatch):
    config = types.ModuleType("campaign_factory.config")
    config.get_settings = lambda: {"db": "settings"}

    core = types.ModuleType("campaign_factory.core")

    class FakeCampaignFactory:
        def __init__(self, settings):
            self.settings = settings

        def recommend_next_batch(self, campaign, *, count, persist):
            assert campaign == "may"
            assert count == 2
            assert persist is False
            return {
                "schema": "campaign_factory.recommendations.next_batch.v1",
                "campaign": campaign,
                "items": [{"recommendationId": "recitem_1"}],
            }

        def close(self):
            pass

    core.CampaignFactory = FakeCampaignFactory
    package = types.ModuleType("campaign_factory")
    monkeypatch.setitem(sys.modules, "campaign_factory", package)
    monkeypatch.setitem(sys.modules, "campaign_factory.config", config)
    monkeypatch.setitem(sys.modules, "campaign_factory.core", core)

    result = campaign_factory_next_batch("may", count=2)

    assert result["source"] == "campaign_factory"
    assert result["fallbackAvailable"] == "reel_factory.local_next_batch"
    assert result["items"] == [{"recommendationId": "recitem_1"}]


def test_campaign_factory_next_batch_can_be_disabled(monkeypatch):
    monkeypatch.setenv("REEL_FACTORY_LOCAL_NEXT_BATCH_ONLY", "1")

    assert campaign_factory_next_batch("may", count=2) is None
