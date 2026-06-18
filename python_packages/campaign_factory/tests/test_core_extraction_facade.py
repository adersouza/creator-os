from __future__ import annotations

from campaign_factory import audit_payload, exports, readiness
from campaign_factory.core import CampaignFactory


def test_execution_readiness_facade_delegates_to_readiness_module(monkeypatch) -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    def fake_execution_readiness(self, **kwargs):
        calls.append((self, kwargs))
        return {"schema": "creator_os.execution_readiness.v1", "ok": True}

    monkeypatch.setattr(readiness, "creator_os_execution_readiness", fake_execution_readiness)

    result = factory.creator_os_execution_readiness(creator="Stacey", requested_count=2)

    assert result["schema"] == "creator_os.execution_readiness.v1"
    assert calls == [(factory, {
        "creator": "Stacey",
        "requested_count": 2,
        "threadsdash_report": None,
        "schedule_plan": None,
        "time_plan": None,
        "generated_at": None,
    })]


def test_export_facade_delegates_to_export_module(monkeypatch) -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    def fake_batch_summary(self, campaign_slug):
        calls.append(("batch", self, campaign_slug))
        return {"schema": "campaign_factory.batch_summary.v1"}

    def fake_daily(self, campaign_slug, *, dashboard=None):
        calls.append(("daily", self, campaign_slug, dashboard))
        return {"schema": "campaign_factory.daily_production_counters.v1"}

    def fake_groups(self, rendered):
        calls.append(("groups", self, rendered))
        return [{"sourceAssetId": "asset_1"}]

    def fake_manifest(self, *, campaign_slug):
        calls.append(("manifest", self, campaign_slug))
        return {"schema": "campaign_factory.export.v1"}

    monkeypatch.setattr(exports, "batch_summary", fake_batch_summary)
    monkeypatch.setattr(exports, "daily_production_counters", fake_daily)
    monkeypatch.setattr(exports, "_variant_pack_groups", fake_groups)
    monkeypatch.setattr(exports, "export_manifest", fake_manifest)

    assert factory.batch_summary("campaign")["schema"] == "campaign_factory.batch_summary.v1"
    assert factory.daily_production_counters("campaign", dashboard={"rendered": []})["schema"] == "campaign_factory.daily_production_counters.v1"
    assert factory._variant_pack_groups([{"id": "asset_1"}]) == [{"sourceAssetId": "asset_1"}]
    assert factory.export_manifest(campaign_slug="campaign")["schema"] == "campaign_factory.export.v1"
    assert calls == [
        ("batch", factory, "campaign"),
        ("daily", factory, "campaign", {"rendered": []}),
        ("groups", factory, [{"id": "asset_1"}]),
        ("manifest", factory, "campaign"),
    ]


def test_audit_report_facade_delegates_to_audit_payload_module(monkeypatch) -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    def fake_audit_report(self, audit_report_id):
        calls.append(("audit", self, audit_report_id))
        return {"id": audit_report_id}

    def fake_payload(self, row):
        calls.append(("payload", self, row))
        return {"id": row["id"]}

    monkeypatch.setattr(audit_payload, "audit_report", fake_audit_report)
    monkeypatch.setattr(audit_payload, "_audit_report_payload", fake_payload)

    assert factory.audit_report("audit_1") == {"id": "audit_1"}
    assert factory._audit_report_payload({"id": "audit_2"}) == {"id": "audit_2"}
    assert calls == [
        ("audit", factory, "audit_1"),
        ("payload", factory, {"id": "audit_2"}),
    ]
