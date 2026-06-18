from __future__ import annotations

from pathlib import Path

from campaign_factory import audit_payload, exports, readiness
from campaign_factory.asset_import import AssetImportRepository
from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory
from campaign_factory.creative_planning import CreativePlanningRepository
from campaign_factory.events import EventRepository
from campaign_factory.graph import GraphRepository
from campaign_factory.models import ModelRepository
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
        assert isinstance(factory.services.events, EventRepository)
        assert factory.services.events.conn is factory.conn
        assert isinstance(factory.services.models, ModelRepository)
        assert factory.services.models.conn is factory.conn
        assert isinstance(factory.services.asset_import, AssetImportRepository)
        assert factory.services.asset_import.conn is factory.conn
        assert isinstance(factory.services.creative_planning, CreativePlanningRepository)
        assert factory.services.creative_planning.conn is factory.conn
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

        def events_for_campaign(self, *args, **kwargs):
            calls.append(("events_for_campaign", args, kwargs))
            return [{"id": "evt_1"}]

        def events_for_asset(self, *args, **kwargs):
            calls.append(("events_for_asset", args, kwargs))
            return [{"id": "evt_2"}]

        def create_pipeline_job(self, *args, **kwargs):
            calls.append(("create_pipeline_job", args, kwargs))
            return {"id": "job_1"}

        def start_pipeline_job(self, *args, **kwargs):
            calls.append(("start_pipeline_job", args, kwargs))
            return {"id": "job_1", "status": "running"}

        def finish_pipeline_job(self, *args, **kwargs):
            calls.append(("finish_pipeline_job", args, kwargs))
            return {"id": "job_1", "status": "succeeded"}

        def fail_pipeline_job(self, *args, **kwargs):
            calls.append(("fail_pipeline_job", args, kwargs))
            return {"id": "job_1", "status": "failed"}

        def set_pipeline_job_campaign(self, *args, **kwargs):
            calls.append(("set_pipeline_job_campaign", args, kwargs))
            return {"id": "job_1", "campaignId": "camp_1"}

        def pipeline_job(self, *args, **kwargs):
            calls.append(("pipeline_job", args, kwargs))
            return {"id": "job_1"}

        def pipeline_job_payload(self, *args, **kwargs):
            calls.append(("pipeline_job_payload", args, kwargs))
            return {"id": args[0]["id"]}

        def upsert_model(self, *args, **kwargs):
            calls.append(("upsert_model", args, kwargs))
            return {"slug": args[0]}

        def upsert_campaign(self, *args, **kwargs):
            calls.append(("upsert_campaign", args, kwargs))
            return {"slug": args[0], "model_slug": args[1]}

        def upsert_account(self, *args, **kwargs):
            calls.append(("upsert_account", args, kwargs))
            return {"handle": args[0]}

        def upsert_model_account_profile(self, *args, **kwargs):
            calls.append(("upsert_model_account_profile", args, kwargs))
            return {"modelSlug": args[0]}

        def model_account_profile(self, *args, **kwargs):
            calls.append(("model_account_profile", args, kwargs))
            return {"modelSlug": args[0]}

        def account_compatible_with_model(self, *args, **kwargs):
            calls.append(("account_compatible_with_model", args, kwargs))
            return True, None, {"modelSlug": args[0]}

        def campaign_by_slug(self, *args, **kwargs):
            calls.append(("campaign_by_slug", args, kwargs))
            return {"slug": args[0]}

        def rendered_asset(self, *args, **kwargs):
            calls.append(("rendered_asset", args, kwargs))
            return {"id": args[0]}

        def import_folder(self, *args, **kwargs):
            calls.append(("import_folder", args, kwargs))
            return {"imported": []}

        def assets_for_campaign(self, *args, **kwargs):
            calls.append(("assets_for_campaign", args, kwargs))
            return [{"id": "src_1"}]

        def create_creative_plan(self, *args, **kwargs):
            calls.append(("create_creative_plan", args, kwargs))
            return {"schema": "campaign_factory.creative_plan.v1", "name": kwargs["name"]}

        def creative_plan(self, *args, **kwargs):
            calls.append(("creative_plan", args, kwargs))
            return {"schema": "campaign_factory.creative_plan.v1", "name": args[0]}

        def update_creative_plan_status(self, *args, **kwargs):
            calls.append(("update_creative_plan_status", args, kwargs))
            return {"status": kwargs["status"]}

        def sync_creative_plan_progress(self, *args, **kwargs):
            calls.append(("sync_creative_plan_progress", args, kwargs))
            return {"schema": "campaign_factory.creative_plan_progress_sync.v1"}

        def creative_plan_for_campaign(self, *args, **kwargs):
            calls.append(("creative_plan_for_campaign", args, kwargs))
            return {"linked_campaign": args[0]}

        def record_creative_plan_event(self, *args, **kwargs):
            calls.append(("record_creative_plan_event", args, kwargs))

        def creative_plan_payload(self, *args, **kwargs):
            calls.append(("creative_plan_payload", args, kwargs))
            return {"id": args[0]["id"]}

        def source_prompt_creative_plan_id(self, *args, **kwargs):
            calls.append(("source_prompt_creative_plan_id", args, kwargs))
            return "cplan_1"

        def asset_creative_plan_id(self, *args, **kwargs):
            calls.append(("asset_creative_plan_id", args, kwargs))
            return "cplan_2"

    factory.services = FakeServices()

    assert factory.graph_id_for("campaigns", "camp_1", entity_type="campaign", payload={"slug": "may"}) == "graph_1"
    assert factory.ensure_graph_edge("from", "to", "contains", evidence={"ok": True}, commit=True) == "edge_1"
    assert factory.set_graph_sync_state("threadsdash", {"cursor": "next"}) is None
    assert factory.record_event("evt", campaign_id="camp_1", status="success", metadata={"ok": True}) == {"id": "evt_1"}
    assert factory.events_for_campaign("may", limit=3) == [{"id": "evt_1"}]
    assert factory.events_for_asset("asset_1", limit=2) == [{"id": "evt_2"}]
    assert factory.create_pipeline_job("render", "camp_1", {"step": 1}) == {"id": "job_1"}
    assert factory.start_pipeline_job("job_1") == {"id": "job_1", "status": "running"}
    assert factory.finish_pipeline_job("job_1", {"ok": True}) == {"id": "job_1", "status": "succeeded"}
    assert factory.fail_pipeline_job("job_1", "boom", {"ok": False}) == {"id": "job_1", "status": "failed"}
    assert factory.set_pipeline_job_campaign("job_1", "camp_1") == {"id": "job_1", "campaignId": "camp_1"}
    assert factory.pipeline_job("job_1") == {"id": "job_1"}
    assert factory.pipeline_job_payload({"id": "job_1"}) == {"id": "job_1"}
    assert factory.upsert_model("model-a", name="Model A", notes="notes") == {"slug": "model-a"}
    assert factory.upsert_campaign("may", "model-a", name="May", platform="threads") == {"slug": "may", "model_slug": "model-a"}
    assert factory.upsert_account("@creator", platform="instagram", external_id="ig_1", model_id="model_1") == {"handle": "@creator"}
    assert factory.upsert_model_account_profile(
        "model-a",
        label="Model A",
        allowed_instagram_account_ids=["ig_1"],
        allowed_account_group_names=["warm"],
        allowed_handle_patterns=["creator"],
        default_smart_link="https://example.test",
        story_cta_text="new post",
    ) == {"modelSlug": "model-a"}
    assert factory.model_account_profile("model-a") == {"modelSlug": "model-a"}
    assert factory.account_compatible_with_model(
        "model-a",
        instagram_account_id="ig_1",
        account_handle="creator",
        account_group_name="warm",
    ) == (True, None, {"modelSlug": "model-a"})
    assert factory.campaign_by_slug("may") == {"slug": "may"}
    assert factory.rendered_asset("asset_1") == {"id": "asset_1"}
    assert factory.import_folder(
        Path("/tmp/import"),
        campaign_slug="may",
        model_slug="model-a",
        model_name="Model A",
        platform="threads",
        account_handles=["ig_a"],
        source_prompt="prompt",
        notes="notes",
    ) == {"imported": []}
    assert factory.assets_for_campaign("camp_1") == [{"id": "src_1"}]
    assert factory.create_creative_plan(name="daily", target_account="@creator") == {
        "schema": "campaign_factory.creative_plan.v1",
        "name": "daily",
    }
    assert factory.creative_plan("daily") == {"schema": "campaign_factory.creative_plan.v1", "name": "daily"}
    assert factory.update_creative_plan_status(name="daily", status="prompts_ready") == {"status": "prompts_ready"}
    assert factory.sync_creative_plan_progress(name="daily", prompt_export_path=Path("/tmp/prompts.json")) == {
        "schema": "campaign_factory.creative_plan_progress_sync.v1",
    }
    assert factory.creative_plan_for_campaign("may", dashboard={"campaign": {"slug": "may"}}) == {"linked_campaign": "may"}
    assert factory._record_creative_plan_event("cplan_1", "creative_plan_created", metadata={"ok": True}) is None
    assert factory._creative_plan_payload({"id": "cplan_1"}) == {"id": "cplan_1"}
    assert factory._source_prompt_creative_plan_id({"source_prompt": "{\"creativePlanId\":\"cplan_1\"}"}) == "cplan_1"
    assert factory._asset_creative_plan_id({"source_prompt": "{\"creativePlanId\":\"cplan_2\"}"}) == "cplan_2"

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
        ("events_for_campaign", ("may",), {"limit": 3}),
        ("events_for_asset", ("asset_1",), {"limit": 2}),
        ("create_pipeline_job", ("render", "camp_1", {"step": 1}), {}),
        ("start_pipeline_job", ("job_1",), {}),
        ("finish_pipeline_job", ("job_1", {"ok": True}), {}),
        ("fail_pipeline_job", ("job_1", "boom", {"ok": False}), {}),
        ("set_pipeline_job_campaign", ("job_1", "camp_1"), {}),
        ("pipeline_job", ("job_1",), {}),
        ("pipeline_job_payload", ({"id": "job_1"},), {}),
        ("upsert_model", ("model-a",), {"name": "Model A", "notes": "notes"}),
        ("upsert_campaign", ("may", "model-a"), {"name": "May", "platform": "threads"}),
        ("upsert_account", ("@creator",), {"platform": "instagram", "external_id": "ig_1", "model_id": "model_1"}),
        ("upsert_model_account_profile", ("model-a",), {
            "label": "Model A",
            "allowed_instagram_account_ids": ["ig_1"],
            "allowed_account_group_names": ["warm"],
            "allowed_handle_patterns": ["creator"],
            "default_smart_link": "https://example.test",
            "story_cta_text": "new post",
        }),
        ("model_account_profile", ("model-a",), {}),
        ("account_compatible_with_model", ("model-a",), {
            "instagram_account_id": "ig_1",
            "account_handle": "creator",
            "account_group_name": "warm",
        }),
        ("campaign_by_slug", ("may",), {}),
        ("rendered_asset", ("asset_1",), {}),
        ("import_folder", (Path("/tmp/import"),), {
            "campaign_slug": "may",
            "model_slug": "model-a",
            "model_name": "Model A",
            "platform": "threads",
            "account_handles": ["ig_a"],
            "source_prompt": "prompt",
            "notes": "notes",
        }),
        ("assets_for_campaign", ("camp_1",), {}),
        ("create_creative_plan", (), {
            "name": "daily",
            "platform": "instagram",
            "target_account": "@creator",
            "daily_base_video_target": 10,
            "style_lanes": None,
            "model_profile": "",
            "source_accounts": None,
            "goal": "views_reach",
            "linked_campaign": None,
        }),
        ("creative_plan", ("daily",), {}),
        ("update_creative_plan_status", (), {"name": "daily", "status": "prompts_ready"}),
        ("sync_creative_plan_progress", (), {"name": "daily", "prompt_export_path": Path("/tmp/prompts.json")}),
        ("creative_plan_for_campaign", ("may",), {"dashboard": {"campaign": {"slug": "may"}}}),
        ("record_creative_plan_event", ("cplan_1", "creative_plan_created"), {
            "status": "info",
            "message": "",
            "metadata": {"ok": True},
            "commit": True,
        }),
        ("creative_plan_payload", ({"id": "cplan_1"},), {"dashboard": None}),
        ("source_prompt_creative_plan_id", ({"source_prompt": "{\"creativePlanId\":\"cplan_1\"}"},), {}),
        ("asset_creative_plan_id", ({"source_prompt": "{\"creativePlanId\":\"cplan_2\"}"},), {}),
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


def test_core_services_delegates_event_methods_to_event_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeEvents:
        def record_event(self, *args, **kwargs):
            calls.append(("record_event", args, kwargs))
            return {"id": "evt_1"}

        def events_for_campaign(self, *args, **kwargs):
            calls.append(("events_for_campaign", args, kwargs))
            return []

        def events_for_asset(self, *args, **kwargs):
            calls.append(("events_for_asset", args, kwargs))
            return []

        def create_pipeline_job(self, *args, **kwargs):
            calls.append(("create_pipeline_job", args, kwargs))
            return {"id": "job_1"}

        def start_pipeline_job(self, *args, **kwargs):
            calls.append(("start_pipeline_job", args, kwargs))
            return {"id": "job_1"}

        def finish_pipeline_job(self, *args, **kwargs):
            calls.append(("finish_pipeline_job", args, kwargs))
            return {"id": "job_1"}

        def fail_pipeline_job(self, *args, **kwargs):
            calls.append(("fail_pipeline_job", args, kwargs))
            return {"id": "job_1"}

        def set_pipeline_job_campaign(self, *args, **kwargs):
            calls.append(("set_pipeline_job_campaign", args, kwargs))
            return {"id": "job_1"}

        def pipeline_job(self, *args, **kwargs):
            calls.append(("pipeline_job", args, kwargs))
            return {"id": "job_1"}

        def pipeline_job_payload(self, *args, **kwargs):
            calls.append(("pipeline_job_payload", args, kwargs))
            return {"id": args[0]["id"]}

    services.events = FakeEvents()

    assert services.record_event("evt", campaign_id="camp_1") == {"id": "evt_1"}
    assert services.events_for_campaign("may", limit=3) == []
    assert services.events_for_asset("asset_1", limit=2) == []
    assert services.create_pipeline_job("render", "camp_1", {"step": 1}) == {"id": "job_1"}
    assert services.start_pipeline_job("job_1") == {"id": "job_1"}
    assert services.finish_pipeline_job("job_1", {"ok": True}) == {"id": "job_1"}
    assert services.fail_pipeline_job("job_1", "boom", {"ok": False}) == {"id": "job_1"}
    assert services.set_pipeline_job_campaign("job_1", "camp_1") == {"id": "job_1"}
    assert services.pipeline_job("job_1") == {"id": "job_1"}
    assert services.pipeline_job_payload({"id": "job_1"}) == {"id": "job_1"}

    assert calls == [
        ("record_event", ("evt",), {
            "campaign_id": "camp_1",
            "source_asset_id": None,
            "rendered_asset_id": None,
            "render_job_id": None,
            "audit_report_id": None,
            "threadsdash_export_id": None,
            "pipeline_job_id": None,
            "status": "info",
            "message": "",
            "metadata": None,
            "commit": True,
        }),
        ("events_for_campaign", ("may",), {"limit": 3}),
        ("events_for_asset", ("asset_1",), {"limit": 2}),
        ("create_pipeline_job", ("render", "camp_1", {"step": 1}), {}),
        ("start_pipeline_job", ("job_1",), {}),
        ("finish_pipeline_job", ("job_1", {"ok": True}), {}),
        ("fail_pipeline_job", ("job_1", "boom", {"ok": False}), {}),
        ("set_pipeline_job_campaign", ("job_1", "camp_1"), {}),
        ("pipeline_job", ("job_1",), {}),
        ("pipeline_job_payload", ({"id": "job_1"},), {}),
    ]


def test_core_services_delegates_model_methods_to_model_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeModels:
        def upsert_model(self, *args, **kwargs):
            calls.append(("upsert_model", args, kwargs))
            return {"slug": args[0]}

        def upsert_campaign(self, *args, **kwargs):
            calls.append(("upsert_campaign", args, kwargs))
            return {"slug": args[0]}

        def upsert_account(self, *args, **kwargs):
            calls.append(("upsert_account", args, kwargs))
            return {"handle": args[0]}

        def upsert_model_account_profile(self, *args, **kwargs):
            calls.append(("upsert_model_account_profile", args, kwargs))
            return {"modelSlug": args[0]}

        def model_account_profile(self, *args, **kwargs):
            calls.append(("model_account_profile", args, kwargs))
            return {"modelSlug": args[0]}

        def account_compatible_with_model(self, *args, **kwargs):
            calls.append(("account_compatible_with_model", args, kwargs))
            return True, None, {"modelSlug": args[0]}

    services.models = FakeModels()

    assert services.upsert_model("model-a", name="Model A", notes="notes") == {"slug": "model-a"}
    assert services.upsert_campaign("may", "model-a", name="May", platform="threads") == {"slug": "may"}
    assert services.upsert_account("@creator", platform="instagram", external_id="ig_1", model_id="model_1") == {"handle": "@creator"}
    assert services.upsert_model_account_profile(
        "model-a",
        label="Model A",
        allowed_instagram_account_ids=["ig_1"],
        allowed_account_group_names=["warm"],
        allowed_handle_patterns=["creator"],
        default_smart_link="https://example.test",
        story_cta_text="new post",
    ) == {"modelSlug": "model-a"}
    assert services.model_account_profile("model-a") == {"modelSlug": "model-a"}
    assert services.account_compatible_with_model(
        "model-a",
        instagram_account_id="ig_1",
        account_handle="creator",
        account_group_name="warm",
    ) == (True, None, {"modelSlug": "model-a"})

    assert calls == [
        ("upsert_model", ("model-a",), {"name": "Model A", "notes": "notes"}),
        ("upsert_campaign", ("may", "model-a"), {"name": "May", "platform": "threads"}),
        ("upsert_account", ("@creator",), {"platform": "instagram", "external_id": "ig_1", "model_id": "model_1"}),
        ("upsert_model_account_profile", ("model-a",), {
            "label": "Model A",
            "allowed_instagram_account_ids": ["ig_1"],
            "allowed_account_group_names": ["warm"],
            "allowed_handle_patterns": ["creator"],
            "default_smart_link": "https://example.test",
            "story_cta_text": "new post",
        }),
        ("model_account_profile", ("model-a",), {}),
        ("account_compatible_with_model", ("model-a",), {
            "instagram_account_id": "ig_1",
            "account_handle": "creator",
            "account_group_name": "warm",
        }),
    ]


def test_core_services_delegates_asset_import_methods_to_asset_import_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeAssetImport:
        def import_folder(self, *args, **kwargs):
            calls.append(("import_folder", args, kwargs))
            return {"imported": []}

        def assets_for_campaign(self, *args, **kwargs):
            calls.append(("assets_for_campaign", args, kwargs))
            return [{"id": "src_1"}]

    services.asset_import = FakeAssetImport()

    assert services.import_folder(
        Path("/tmp/import"),
        campaign_slug="may",
        model_slug="model-a",
        model_name="Model A",
        platform="threads",
        account_handles=["ig_a"],
        source_prompt="prompt",
        notes="notes",
    ) == {"imported": []}
    assert services.assets_for_campaign("camp_1") == [{"id": "src_1"}]

    assert calls == [
        ("import_folder", (Path("/tmp/import"),), {
            "campaign_slug": "may",
            "model_slug": "model-a",
            "model_name": "Model A",
            "platform": "threads",
            "account_handles": ["ig_a"],
            "source_prompt": "prompt",
            "notes": "notes",
        }),
        ("assets_for_campaign", ("camp_1",), {}),
    ]


def test_core_services_delegates_creative_planning_methods_to_creative_planning_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeCreativePlanning:
        def create_creative_plan(self, *args, **kwargs):
            calls.append(("create_creative_plan", args, kwargs))
            return {"name": kwargs["name"]}

        def creative_plan(self, *args, **kwargs):
            calls.append(("creative_plan", args, kwargs))
            return {"name": args[0]}

        def update_creative_plan_status(self, *args, **kwargs):
            calls.append(("update_creative_plan_status", args, kwargs))
            return {"status": kwargs["status"]}

        def sync_creative_plan_progress(self, *args, **kwargs):
            calls.append(("sync_creative_plan_progress", args, kwargs))
            return {"schema": "campaign_factory.creative_plan_progress_sync.v1"}

        def creative_plan_for_campaign(self, *args, **kwargs):
            calls.append(("creative_plan_for_campaign", args, kwargs))
            return {"linked_campaign": args[0]}

        def record_creative_plan_event(self, *args, **kwargs):
            calls.append(("record_creative_plan_event", args, kwargs))

        def creative_plan_payload(self, *args, **kwargs):
            calls.append(("creative_plan_payload", args, kwargs))
            return {"id": args[0]["id"]}

        def source_prompt_creative_plan_id(self, *args, **kwargs):
            calls.append(("source_prompt_creative_plan_id", args, kwargs))
            return "cplan_1"

        def asset_creative_plan_id(self, *args, **kwargs):
            calls.append(("asset_creative_plan_id", args, kwargs))
            return "cplan_2"

    services.creative_planning = FakeCreativePlanning()

    assert services.create_creative_plan(name="daily", target_account="@creator") == {"name": "daily"}
    assert services.creative_plan("daily") == {"name": "daily"}
    assert services.update_creative_plan_status(name="daily", status="prompts_ready") == {"status": "prompts_ready"}
    assert services.sync_creative_plan_progress(name="daily", prompt_export_path=Path("/tmp/prompts.json")) == {
        "schema": "campaign_factory.creative_plan_progress_sync.v1",
    }
    assert services.creative_plan_for_campaign("may", dashboard={"campaign": {"slug": "may"}}) == {"linked_campaign": "may"}
    assert services.record_creative_plan_event("cplan_1", "creative_plan_created", metadata={"ok": True}) is None
    assert services.creative_plan_payload({"id": "cplan_1"}) == {"id": "cplan_1"}
    assert services.source_prompt_creative_plan_id({"source_prompt": "{\"creativePlanId\":\"cplan_1\"}"}) == "cplan_1"
    assert services.asset_creative_plan_id({"source_prompt": "{\"creativePlanId\":\"cplan_2\"}"}) == "cplan_2"

    assert calls == [
        ("create_creative_plan", (), {
            "name": "daily",
            "platform": "instagram",
            "target_account": "@creator",
            "daily_base_video_target": 10,
            "style_lanes": None,
            "model_profile": "",
            "source_accounts": None,
            "goal": "views_reach",
            "linked_campaign": None,
        }),
        ("creative_plan", ("daily",), {}),
        ("update_creative_plan_status", (), {"name": "daily", "status": "prompts_ready"}),
        ("sync_creative_plan_progress", (), {"name": "daily", "prompt_export_path": Path("/tmp/prompts.json")}),
        ("creative_plan_for_campaign", ("may",), {"dashboard": {"campaign": {"slug": "may"}}}),
        ("record_creative_plan_event", ("cplan_1", "creative_plan_created"), {
            "status": "info",
            "message": "",
            "metadata": {"ok": True},
            "commit": True,
        }),
        ("creative_plan_payload", ({"id": "cplan_1"},), {"dashboard": None}),
        ("source_prompt_creative_plan_id", ({"source_prompt": "{\"creativePlanId\":\"cplan_1\"}"},), {}),
        ("asset_creative_plan_id", ({"source_prompt": "{\"creativePlanId\":\"cplan_2\"}"},), {}),
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
