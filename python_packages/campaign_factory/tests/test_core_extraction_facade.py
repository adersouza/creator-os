from __future__ import annotations

from campaign_factory import audit_payload, exports, readiness
from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory
from campaign_factory.graph import GraphRepository
from campaign_factory.services import CoreServices


def test_campaign_factory_initializes_core_services(tmp_path) -> None:
    factory = CampaignFactory(Settings(
        root=tmp_path,
        db_path=tmp_path / "campaign_factory.sqlite",
        reel_factory_root=tmp_path / "reel_factory",
        contentforge_root=tmp_path / "contentforge",
        threadsdash_root=tmp_path / "ThreadsDashboard",
        campaigns_dir=tmp_path / "campaigns",
    ))
    try:
        assert isinstance(factory.services, CoreServices)
        assert factory.services.conn is factory.conn
        assert factory.services.settings is factory.settings
        assert isinstance(factory.services.graph, GraphRepository)
        assert factory.services.graph.conn is factory.conn
    finally:
        factory.close()


def test_core_service_facade_methods_delegate_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def graph_id_for(self, *args, **kwargs):
            calls.append(("graph_id_for", args, kwargs))
            return "graph_1"

        def ensure_graph_edge(self, *args, **kwargs):
            calls.append(("ensure_graph_edge", args, kwargs))
            return "edge_1"

        def set_graph_sync_state(self, *args, **kwargs):
            calls.append(("set_graph_sync_state", args, kwargs))

        def record_event(self, *args, **kwargs):
            calls.append(("record_event", args, kwargs))
            return {"id": "evt_1"}

        def campaign_by_slug(self, *args, **kwargs):
            calls.append(("campaign_by_slug", args, kwargs))
            return {"slug": args[0]}

        def rendered_asset(self, *args, **kwargs):
            calls.append(("rendered_asset", args, kwargs))
            return {"id": args[0]}

    factory.services = FakeServices()

    assert factory.graph_id_for("campaigns", "camp_1", entity_type="campaign", payload={"slug": "may"}) == "graph_1"
    assert factory.ensure_graph_edge("from", "to", "contains", evidence={"ok": True}, commit=True) == "edge_1"
    assert factory.set_graph_sync_state("threadsdash", {"cursor": "next"}) is None
    assert factory.record_event("evt", campaign_id="camp_1", status="success", metadata={"ok": True}) == {"id": "evt_1"}
    assert factory.campaign_by_slug("may") == {"slug": "may"}
    assert factory.rendered_asset("asset_1") == {"id": "asset_1"}

    assert calls == [
        ("graph_id_for", ("campaigns", "camp_1"), {"entity_type": "campaign", "payload": {"slug": "may"}}),
        ("ensure_graph_edge", ("from", "to", "contains"), {"evidence": {"ok": True}, "commit": True}),
        ("set_graph_sync_state", ("threadsdash", {"cursor": "next"}), {}),
        ("record_event", ("evt",), {
            "campaign_id": "camp_1",
            "source_asset_id": None,
            "rendered_asset_id": None,
            "render_job_id": None,
            "audit_report_id": None,
            "threadsdash_export_id": None,
            "pipeline_job_id": None,
            "status": "success",
            "message": "",
            "metadata": {"ok": True},
            "commit": True,
        }),
        ("campaign_by_slug", ("may",), {}),
        ("rendered_asset", ("asset_1",), {}),
    ]


def test_core_services_delegates_graph_methods_to_graph_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeGraph:
        def ensure_graph_node(self, *args, **kwargs):
            calls.append(("ensure_graph_node", args, kwargs))
            return "node_1"

        def graph_id_for(self, *args, **kwargs):
            calls.append(("graph_id_for", args, kwargs))
            return "node_2"

        def ensure_graph_edge(self, *args, **kwargs):
            calls.append(("ensure_graph_edge", args, kwargs))
            return "edge_1"

        def set_sync_state(self, *args, **kwargs):
            calls.append(("set_sync_state", args, kwargs))

    services.graph = FakeGraph()

    assert services.ensure_graph_node("campaign", local_table="campaigns", local_id="camp_1", payload={"slug": "may"}) == "node_1"
    assert services.graph_id_for("campaigns", "camp_1", entity_type="campaign", payload={"slug": "may"}) == "node_2"
    assert services.ensure_graph_edge("node_1", "node_2", "contains", evidence={"ok": True}, commit=True) == "edge_1"
    assert services.set_graph_sync_state("threadsdash", {"cursor": "next"}) is None

    assert calls == [
        ("ensure_graph_node", ("campaign",), {
            "local_table": "campaigns",
            "local_id": "camp_1",
            "external_system": None,
            "external_id": None,
            "payload": {"slug": "may"},
            "commit": False,
        }),
        ("graph_id_for", ("campaigns", "camp_1"), {"entity_type": "campaign", "payload": {"slug": "may"}}),
        ("ensure_graph_edge", ("node_1", "node_2", "contains"), {"evidence": {"ok": True}, "commit": True}),
        ("set_sync_state", ("threadsdash", {"cursor": "next"}), {}),
    ]


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
