from __future__ import annotations

from pathlib import Path

from campaign_factory import audit_payload, exports, readiness
from campaign_factory.asset_import import AssetImportRepository
from campaign_factory.caption import CaptionFamilyRepository
from campaign_factory.carousel_integrity import CarouselIntegrityRepository
from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory
from campaign_factory.creative_knowledge import CreativeKnowledgeRepository
from campaign_factory.creative_planning import CreativePlanningRepository
from campaign_factory.decision_ledger import DecisionLedgerRepository
from campaign_factory.discoverability import DiscoverabilityRepository
from campaign_factory.distribution import DistributionRepository
from campaign_factory.events import EventRepository
from campaign_factory.exceptions import ExceptionRepository
from campaign_factory.graph import GraphRepository
from campaign_factory.models import ModelRepository
from campaign_factory.reference import ReferenceRepository
from campaign_factory.services import CoreServices
from campaign_factory.surface_registration import SurfaceRegistrationRepository
from campaign_factory.winner_expansion import WinnerExpansionRepository


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
        assert isinstance(factory.services.reference, ReferenceRepository)
        assert factory.services.reference.conn is factory.conn
        assert isinstance(factory.services.caption_family, CaptionFamilyRepository)
        assert factory.services.caption_family.conn is factory.conn
        assert isinstance(factory.services.distribution, DistributionRepository)
        assert factory.services.distribution.conn is factory.conn
        assert isinstance(factory.services.decision_ledger, DecisionLedgerRepository)
        assert factory.services.decision_ledger.conn is factory.conn
        assert isinstance(factory.services.exceptions, ExceptionRepository)
        assert factory.services.exceptions.conn is factory.conn
        assert isinstance(factory.services.discoverability, DiscoverabilityRepository)
        assert factory.services.discoverability.conn is factory.conn
        assert isinstance(factory.services.surface_registration, SurfaceRegistrationRepository)
        assert factory.services.surface_registration.conn is factory.conn
        assert isinstance(factory.services.carousel_integrity, CarouselIntegrityRepository)
        assert factory.services.carousel_integrity.conn is factory.conn
        assert isinstance(factory.services.winner_expansion, WinnerExpansionRepository)
        assert factory.services.winner_expansion.conn is factory.conn
        assert isinstance(factory.services.creative_knowledge, CreativeKnowledgeRepository)
        assert factory.services.creative_knowledge.conn is factory.conn
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

        def import_reference_bank(self, *args, **kwargs):
            calls.append(("import_reference_bank", args, kwargs))
            return {"schema": "campaign_factory.reference_bank_import.v1"}

        def reference_patterns(self, *args, **kwargs):
            calls.append(("reference_patterns", args, kwargs))
            return {"schema": "campaign_factory.reference_patterns.v1"}

        def select_reference_pattern(self, *args, **kwargs):
            calls.append(("select_reference_pattern", args, kwargs))
            return {"schema": "campaign_factory.reference_pattern_selection.v1"}

        def campaign_reference_plan(self, *args, **kwargs):
            calls.append(("campaign_reference_plan", args, kwargs))
            return {"schema": "campaign_factory.reference_plan.v1"}

        def prepare_reel_from_reference(self, *args, **kwargs):
            calls.append(("prepare_reel_from_reference", args, kwargs))
            return {"schema": "campaign_factory.prepare_from_reference.v1"}

        def active_reference_pattern_for_campaign(self, *args, **kwargs):
            calls.append(("active_reference_pattern_for_campaign", args, kwargs))
            return {"id": "refpat_1"}

        def reference_hooks(self, *args, **kwargs):
            calls.append(("reference_hooks", args, kwargs))
            return [{"text": "mirror check"}]

        def reference_pattern_payload(self, *args, **kwargs):
            calls.append(("reference_pattern_payload", args, kwargs))
            return {"id": args[0]["id"]}

        def reference_hook_is_schedule_safe(self, *args, **kwargs):
            calls.append(("reference_hook_is_schedule_safe", args, kwargs))
            return True

        def caption_family_plan(self, *args, **kwargs):
            calls.append(("caption_family_plan", args, kwargs))
            return {"schema": "campaign_factory.caption_family_plan.v1"}

        def caption_family_create(self, *args, **kwargs):
            calls.append(("caption_family_create", args, kwargs))
            return {"schema": "campaign_factory.caption_family_create.v1"}

        def planned_caption_version(self, *args, **kwargs):
            calls.append(("planned_caption_version", args, kwargs))
            return {"captionVersionId": "cver_1"}

        def caption_family_hashtags(self, *args, **kwargs):
            calls.append(("caption_family_hashtags", args, kwargs))
            return ["#one"]

        def caption_version_by_id(self, *args, **kwargs):
            calls.append(("caption_version_by_id", args, kwargs))
            return {"captionVersionId": args[0]}

        def caption_version_payload(self, *args, **kwargs):
            calls.append(("caption_version_payload", args, kwargs))
            return {"captionVersionId": args[0]["id"]}

        def decision_ledger_preview(self, *args, **kwargs):
            calls.append(("decision_ledger_preview", args, kwargs))
            return {"schema": "creator_os.decision_ledger_preview.v1"}

        def decision_ledger_report(self, *args, **kwargs):
            calls.append(("decision_ledger_report", args, kwargs))
            return {"schema": "creator_os.decision_ledger_report.v1"}

        def decision_ledger_summary(self, *args, **kwargs):
            calls.append(("decision_ledger_summary", args, kwargs))
            return {"schema": "creator_os.decision_ledger_summary.v1"}

        def decision_ledger_by_creator(self, *args, **kwargs):
            calls.append(("decision_ledger_by_creator", args, kwargs))
            return {"schema": "creator_os.decision_ledger_by_creator.v1"}

        def decision_ledger_by_account(self, *args, **kwargs):
            calls.append(("decision_ledger_by_account", args, kwargs))
            return {"schema": "creator_os.decision_ledger_by_account.v1"}

        def decision_ledger_by_surface(self, *args, **kwargs):
            calls.append(("decision_ledger_by_surface", args, kwargs))
            return {"schema": "creator_os.decision_ledger_by_surface.v1"}

        def decision_ledger_by_decision_type(self, *args, **kwargs):
            calls.append(("decision_ledger_by_decision_type", args, kwargs))
            return {"schema": "creator_os.decision_ledger_by_decision_type.v1"}

        def query_decision_ledger(self, *args, **kwargs):
            calls.append(("query_decision_ledger", args, kwargs))
            return {"decisionCount": 0}

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
    assert factory.import_reference_bank(Path("/tmp/bank.json"), Path("/tmp/prompts.json")) == {
        "schema": "campaign_factory.reference_bank_import.v1",
    }
    assert factory.reference_patterns(limit=3) == {"schema": "campaign_factory.reference_patterns.v1"}
    assert factory.select_reference_pattern("may", cluster_key="cluster", variant_count=2, notes="notes") == {
        "schema": "campaign_factory.reference_pattern_selection.v1",
    }
    assert factory.campaign_reference_plan("may") == {"schema": "campaign_factory.reference_plan.v1"}
    assert factory.prepare_reel_from_reference(
        campaign_slug="may",
        cluster_key="cluster",
        variant_count=2,
        recipes=["v01_original"],
        caption_color="white",
        notes="notes",
        force_new=False,
    ) == {"schema": "campaign_factory.prepare_from_reference.v1"}
    assert factory.active_reference_pattern_for_campaign("camp_1") == {"id": "refpat_1"}
    assert factory.reference_hooks({"clusterKey": "cluster", "label": "Cluster"}, count=2) == [
        {"text": "mirror check"},
    ]
    assert factory._reference_pattern_payload({"id": "refpat_1"}) == {"id": "refpat_1"}
    assert factory._reference_hook_is_schedule_safe("mirror check") is True
    assert factory.caption_family_plan(
        creator="Stacey",
        parent_asset_id="asset_1",
        requested_caption_versions=2,
        style="ig_short",
        dry_run=True,
    ) == {"schema": "campaign_factory.caption_family_plan.v1"}
    assert factory.caption_family_create(
        creator="Stacey",
        parent_asset_id="asset_1",
        requested_caption_versions=2,
        style="ig_short",
        dry_run=False,
    ) == {"schema": "campaign_factory.caption_family_create.v1"}
    assert factory._planned_caption_version(
        caption_family_id="cfam_1",
        parent={"id": "asset_1"},
        concept={"parentReelId": "preel_1"},
        index=1,
        angle="question_bait",
        base_burned="caption",
        base_hashtags=["#one"],
        style="ig_short",
        caption_source="test",
    ) == {"captionVersionId": "cver_1"}
    assert factory._caption_family_hashtags(["#one", "two"]) == ["#one"]
    assert factory._caption_version_by_id("cver_1") == {"captionVersionId": "cver_1"}
    assert factory._caption_version_payload({"id": "cver_1"}) == {"captionVersionId": "cver_1"}
    assert factory.decision_ledger_preview(creator="Stacey", date="2026-06-06") == {
        "schema": "creator_os.decision_ledger_preview.v1",
    }
    assert factory.decision_ledger_report(creator="Stacey") == {"schema": "creator_os.decision_ledger_report.v1"}
    assert factory.decision_ledger_summary(creator="Stacey") == {"schema": "creator_os.decision_ledger_summary.v1"}
    assert factory.decision_ledger_by_creator(creator="Stacey") == {
        "schema": "creator_os.decision_ledger_by_creator.v1",
    }
    assert factory.decision_ledger_by_account(creator="Stacey", account_id="acct_1") == {
        "schema": "creator_os.decision_ledger_by_account.v1",
    }
    assert factory.decision_ledger_by_surface(creator="Stacey", surface="story") == {
        "schema": "creator_os.decision_ledger_by_surface.v1",
    }
    assert factory.decision_ledger_by_decision_type(creator="Stacey", decision_type="account_needs_story") == {
        "schema": "creator_os.decision_ledger_by_decision_type.v1",
    }
    assert factory._query_decision_ledger(creator="Stacey") == {"decisionCount": 0}

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
        ("import_reference_bank", (Path("/tmp/bank.json"), Path("/tmp/prompts.json")), {}),
        ("reference_patterns", (), {"limit": 3}),
        ("select_reference_pattern", ("may",), {
            "cluster_key": "cluster",
            "reference_pattern_id": None,
            "variant_count": 2,
            "notes": "notes",
        }),
        ("campaign_reference_plan", ("may",), {}),
        ("prepare_reel_from_reference", (), {
            "campaign_slug": "may",
            "cluster_key": "cluster",
            "reference_pattern_id": None,
            "variant_count": 2,
            "recipes": ["v01_original"],
            "caption_color": "white",
            "notes": "notes",
            "force_new": False,
        }),
        ("active_reference_pattern_for_campaign", ("camp_1",), {}),
        ("reference_hooks", ({"clusterKey": "cluster", "label": "Cluster"},), {"count": 2}),
        ("reference_pattern_payload", ({"id": "refpat_1"},), {}),
        ("reference_hook_is_schedule_safe", ("mirror check",), {}),
        ("caption_family_plan", (), {
            "creator": "Stacey",
            "parent_asset_id": "asset_1",
            "requested_caption_versions": 2,
            "style": "ig_short",
            "dry_run": True,
        }),
        ("caption_family_create", (), {
            "creator": "Stacey",
            "parent_asset_id": "asset_1",
            "requested_caption_versions": 2,
            "style": "ig_short",
            "dry_run": False,
        }),
        ("planned_caption_version", (), {
            "caption_family_id": "cfam_1",
            "parent": {"id": "asset_1"},
            "concept": {"parentReelId": "preel_1"},
            "index": 1,
            "angle": "question_bait",
            "base_burned": "caption",
            "base_hashtags": ["#one"],
            "style": "ig_short",
            "caption_source": "test",
        }),
        ("caption_family_hashtags", (["#one", "two"],), {}),
        ("caption_version_by_id", ("cver_1",), {}),
        ("caption_version_payload", ({"id": "cver_1"},), {}),
        ("decision_ledger_preview", (), {
            "creator": "Stacey",
            "date": "2026-06-06",
            "threadsdash_report": {},
            "schedule_plan": None,
            "time_plan": None,
            "winner_expansion_report": None,
            "winner_expansion_plan": None,
            "variant_inventory_plan": None,
            "variant_metrics_rollup": None,
            "account_tiers": None,
            "generated_at": None,
        }),
        ("decision_ledger_report", (), {"creator": "Stacey"}),
        ("decision_ledger_summary", (), {"creator": "Stacey"}),
        ("decision_ledger_by_creator", (), {"creator": "Stacey"}),
        ("decision_ledger_by_account", (), {"creator": "Stacey", "account_id": "acct_1"}),
        ("decision_ledger_by_surface", (), {"creator": "Stacey", "surface": "story"}),
        ("decision_ledger_by_decision_type", (), {"creator": "Stacey", "decision_type": "account_needs_story"}),
        ("query_decision_ledger", (), {
            "creator": "Stacey",
            "account_id": None,
            "surface": None,
            "decision_type": None,
        }),
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


def test_core_services_delegates_reference_methods_to_reference_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeReference:
        def import_reference_bank(self, *args, **kwargs):
            calls.append(("import_reference_bank", args, kwargs))
            return {"schema": "campaign_factory.reference_bank_import.v1"}

        def reference_patterns(self, *args, **kwargs):
            calls.append(("reference_patterns", args, kwargs))
            return {"schema": "campaign_factory.reference_patterns.v1"}

        def select_reference_pattern(self, *args, **kwargs):
            calls.append(("select_reference_pattern", args, kwargs))
            return {"schema": "campaign_factory.reference_pattern_selection.v1"}

        def campaign_reference_plan(self, *args, **kwargs):
            calls.append(("campaign_reference_plan", args, kwargs))
            return {"schema": "campaign_factory.reference_plan.v1"}

        def prepare_reel_from_reference(self, *args, **kwargs):
            calls.append(("prepare_reel_from_reference", args, kwargs))
            return {"schema": "campaign_factory.prepare_from_reference.v1"}

        def active_reference_pattern_for_campaign(self, *args, **kwargs):
            calls.append(("active_reference_pattern_for_campaign", args, kwargs))
            return {"id": "refpat_1"}

        def reference_hooks(self, *args, **kwargs):
            calls.append(("reference_hooks", args, kwargs))
            return [{"text": "mirror check"}]

        def reference_pattern_payload(self, *args, **kwargs):
            calls.append(("reference_pattern_payload", args, kwargs))
            return {"id": args[0]["id"]}

        def reference_hook_is_schedule_safe(self, *args, **kwargs):
            calls.append(("reference_hook_is_schedule_safe", args, kwargs))
            return True

    services.reference = FakeReference()

    assert services.import_reference_bank(Path("/tmp/bank.json"), Path("/tmp/prompts.json")) == {
        "schema": "campaign_factory.reference_bank_import.v1",
    }
    assert services.reference_patterns(limit=3) == {"schema": "campaign_factory.reference_patterns.v1"}
    assert services.select_reference_pattern("may", cluster_key="cluster", variant_count=2, notes="notes") == {
        "schema": "campaign_factory.reference_pattern_selection.v1",
    }
    assert services.campaign_reference_plan("may") == {"schema": "campaign_factory.reference_plan.v1"}
    assert services.prepare_reel_from_reference(
        campaign_slug="may",
        cluster_key="cluster",
        variant_count=2,
        recipes=["v01_original"],
        caption_color="white",
        notes="notes",
        force_new=False,
    ) == {"schema": "campaign_factory.prepare_from_reference.v1"}
    assert services.active_reference_pattern_for_campaign("camp_1") == {"id": "refpat_1"}
    assert services.reference_hooks({"clusterKey": "cluster", "label": "Cluster"}, count=2) == [
        {"text": "mirror check"},
    ]
    assert services.reference_pattern_payload({"id": "refpat_1"}) == {"id": "refpat_1"}
    assert services.reference_hook_is_schedule_safe("mirror check") is True

    assert calls == [
        ("import_reference_bank", (Path("/tmp/bank.json"), Path("/tmp/prompts.json")), {}),
        ("reference_patterns", (), {"limit": 3}),
        ("select_reference_pattern", ("may",), {
            "cluster_key": "cluster",
            "reference_pattern_id": None,
            "variant_count": 2,
            "notes": "notes",
        }),
        ("campaign_reference_plan", ("may",), {}),
        ("prepare_reel_from_reference", (), {
            "campaign_slug": "may",
            "cluster_key": "cluster",
            "reference_pattern_id": None,
            "variant_count": 2,
            "recipes": ["v01_original"],
            "caption_color": "white",
            "notes": "notes",
            "force_new": False,
        }),
        ("active_reference_pattern_for_campaign", ("camp_1",), {}),
        ("reference_hooks", ({"clusterKey": "cluster", "label": "Cluster"},), {"count": 2}),
        ("reference_pattern_payload", ({"id": "refpat_1"},), {}),
        ("reference_hook_is_schedule_safe", ("mirror check",), {}),
    ]


def test_core_services_delegates_caption_family_methods_to_caption_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeCaptionFamily:
        def caption_family_plan(self, *args, **kwargs):
            calls.append(("caption_family_plan", args, kwargs))
            return {"schema": "campaign_factory.caption_family_plan.v1"}

        def caption_family_create(self, *args, **kwargs):
            calls.append(("caption_family_create", args, kwargs))
            return {"schema": "campaign_factory.caption_family_create.v1"}

        def planned_caption_version(self, *args, **kwargs):
            calls.append(("planned_caption_version", args, kwargs))
            return {"captionVersionId": "cver_1"}

        def caption_family_hashtags(self, *args, **kwargs):
            calls.append(("caption_family_hashtags", args, kwargs))
            return ["#one"]

        def caption_version_by_id(self, *args, **kwargs):
            calls.append(("caption_version_by_id", args, kwargs))
            return {"captionVersionId": args[0]}

        def caption_version_payload(self, *args, **kwargs):
            calls.append(("caption_version_payload", args, kwargs))
            return {"captionVersionId": args[0]["id"]}

    services.caption_family = FakeCaptionFamily()

    assert services.caption_family_plan(
        creator="Stacey",
        parent_asset_id="asset_1",
        requested_caption_versions=2,
        style="ig_short",
        dry_run=True,
    ) == {"schema": "campaign_factory.caption_family_plan.v1"}
    assert services.caption_family_create(
        creator="Stacey",
        parent_asset_id="asset_1",
        requested_caption_versions=2,
        style="ig_short",
        dry_run=False,
    ) == {"schema": "campaign_factory.caption_family_create.v1"}
    assert services.planned_caption_version(
        caption_family_id="cfam_1",
        parent={"id": "asset_1"},
        concept={"parentReelId": "preel_1"},
        index=1,
        angle="question_bait",
        base_burned="caption",
        base_hashtags=["#one"],
        style="ig_short",
        caption_source="test",
    ) == {"captionVersionId": "cver_1"}
    assert services.caption_family_hashtags(["#one", "two"]) == ["#one"]
    assert services.caption_version_by_id("cver_1") == {"captionVersionId": "cver_1"}
    assert services.caption_version_payload({"id": "cver_1"}) == {"captionVersionId": "cver_1"}

    assert calls == [
        ("caption_family_plan", (), {
            "creator": "Stacey",
            "parent_asset_id": "asset_1",
            "requested_caption_versions": 2,
            "style": "ig_short",
            "dry_run": True,
        }),
        ("caption_family_create", (), {
            "creator": "Stacey",
            "parent_asset_id": "asset_1",
            "requested_caption_versions": 2,
            "style": "ig_short",
            "dry_run": False,
        }),
        ("planned_caption_version", (), {
            "caption_family_id": "cfam_1",
            "parent": {"id": "asset_1"},
            "concept": {"parentReelId": "preel_1"},
            "index": 1,
            "angle": "question_bait",
            "base_burned": "caption",
            "base_hashtags": ["#one"],
            "style": "ig_short",
            "caption_source": "test",
        }),
        ("caption_family_hashtags", (["#one", "two"],), {}),
        ("caption_version_by_id", ("cver_1",), {}),
        ("caption_version_payload", ({"id": "cver_1"},), {}),
    ]


def test_distribution_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def create_distribution_plan(self, *args, **kwargs):
            calls.append(("create_distribution_plan", args, kwargs))
            return {"id": "dist_1"}

        def distribution_plan(self, *args, **kwargs):
            calls.append(("distribution_plan", args, kwargs))
            return {"id": args[0]}

        def distribution_plans_for_asset(self, *args, **kwargs):
            calls.append(("distribution_plans_for_asset", args, kwargs))
            return [{"renderedAssetId": args[0]}]

        def distribution_plans_for_campaign(self, *args, **kwargs):
            calls.append(("distribution_plans_for_campaign", args, kwargs))
            return [{"campaign": args[0]}]

        def clear_distribution_plans_for_campaign(self, *args, **kwargs):
            calls.append(("clear_distribution_plans_for_campaign", args, kwargs))
            return 2

        def distribution_plan_payload(self, *args, **kwargs):
            calls.append(("distribution_plan_payload", args, kwargs))
            return {"id": args[0]["id"]}

        def plan_distribution(self, *args, **kwargs):
            calls.append(("plan_distribution", args, kwargs))
            return {"schema": "campaign_factory.distribution_plan_run.v1"}

        def next_distribution_account(self, *args, **kwargs):
            calls.append(("next_distribution_account", args, kwargs))
            return "ig_1"

        def distribution_slots(self, *args, **kwargs):
            calls.append(("distribution_slots", args, kwargs))
            return ["slot_1"]

        def next_valid_distribution_slot(self, *args, **kwargs):
            calls.append(("next_valid_distribution_slot", args, kwargs))
            return "slot_1", 1

        def distribution_summary(self, *args, **kwargs):
            calls.append(("distribution_summary", args, kwargs))
            return {"schema": "campaign_factory.distribution_summary.v1"}

        def latest_distribution_plan_for_asset(self, *args, **kwargs):
            calls.append(("latest_distribution_plan_for_asset", args, kwargs))
            return {"renderedAssetId": args[0]}

    factory.services = FakeServices()

    assert factory.create_distribution_plan(
        "asset_1",
        surface="trial_reel",
        account_id="acct_1",
        instagram_account_id="ig_1",
        planned_window_start="2026-01-02T10:00:00+00:00",
        planned_window_end="2026-01-02T11:00:00+00:00",
        paired_rendered_asset_id="asset_2",
        reason_code="test",
        smart_link="https://example.test",
        cta_text="new post",
        instagram_trial_reels=True,
        trial_graduation_strategy="MANUAL",
    ) == {"id": "dist_1"}
    assert factory.distribution_plan("dist_1") == {"id": "dist_1"}
    assert factory.distribution_plans_for_asset("asset_1") == [{"renderedAssetId": "asset_1"}]
    assert factory.distribution_plans_for_campaign("may") == [{"campaign": "may"}]
    assert factory.clear_distribution_plans_for_campaign("may") == 2
    assert factory._distribution_plan_payload({"id": "dist_1"}) == {"id": "dist_1"}
    assert factory.plan_distribution(
        "may",
        user_id="user_1",
        mode="preview",
        strategy="trial-heavy",
        replace=False,
        fallback_hours=[9],
    ) == {"schema": "campaign_factory.distribution_plan_run.v1"}
    assert factory._next_distribution_account({"allowedInstagramAccountIds": ["ig_1"]}, "model", {}) == "ig_1"
    assert factory._distribution_slots([10], 1) == ["slot_1"]
    assert factory._next_valid_distribution_slot([], 0, "ig_1", {"id": "asset_1"}, {}, {}, {}, {}, []) == ("slot_1", 1)
    assert factory.distribution_summary("may") == {"schema": "campaign_factory.distribution_summary.v1"}
    assert factory._latest_distribution_plan_for_asset("asset_1") == {"renderedAssetId": "asset_1"}

    assert calls == [
        ("create_distribution_plan", ("asset_1",), {
            "surface": "trial_reel",
            "account_id": "acct_1",
            "instagram_account_id": "ig_1",
            "planned_window_start": "2026-01-02T10:00:00+00:00",
            "planned_window_end": "2026-01-02T11:00:00+00:00",
            "paired_rendered_asset_id": "asset_2",
            "reason_code": "test",
            "smart_link": "https://example.test",
            "cta_text": "new post",
            "instagram_trial_reels": True,
            "trial_graduation_strategy": "MANUAL",
        }),
        ("distribution_plan", ("dist_1",), {}),
        ("distribution_plans_for_asset", ("asset_1",), {}),
        ("distribution_plans_for_campaign", ("may",), {}),
        ("clear_distribution_plans_for_campaign", ("may",), {}),
        ("distribution_plan_payload", ({"id": "dist_1"},), {}),
        ("plan_distribution", ("may",), {
            "user_id": "user_1",
            "mode": "preview",
            "strategy": "trial-heavy",
            "replace": False,
            "fallback_hours": [9],
        }),
        ("next_distribution_account", ({"allowedInstagramAccountIds": ["ig_1"]}, "model", {}), {}),
        ("distribution_slots", ([10], 1), {}),
        ("next_valid_distribution_slot", ([], 0, "ig_1", {"id": "asset_1"}, {}, {}, {}, {}, []), {}),
        ("distribution_summary", ("may",), {}),
        ("latest_distribution_plan_for_asset", ("asset_1",), {}),
    ]


def test_core_services_delegates_distribution_methods_to_distribution_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeDistribution:
        def create_distribution_plan(self, *args, **kwargs):
            calls.append(("create_distribution_plan", args, kwargs))
            return {"id": "dist_1"}

        def distribution_plan(self, *args, **kwargs):
            calls.append(("distribution_plan", args, kwargs))
            return {"id": args[0]}

        def distribution_plans_for_asset(self, *args, **kwargs):
            calls.append(("distribution_plans_for_asset", args, kwargs))
            return [{"renderedAssetId": args[0]}]

        def distribution_plans_for_campaign(self, *args, **kwargs):
            calls.append(("distribution_plans_for_campaign", args, kwargs))
            return [{"campaign": args[0]}]

        def clear_distribution_plans_for_campaign(self, *args, **kwargs):
            calls.append(("clear_distribution_plans_for_campaign", args, kwargs))
            return 2

        def distribution_plan_payload(self, *args, **kwargs):
            calls.append(("distribution_plan_payload", args, kwargs))
            return {"id": args[0]["id"]}

        def plan_distribution(self, *args, **kwargs):
            calls.append(("plan_distribution", args, kwargs))
            return {"schema": "campaign_factory.distribution_plan_run.v1"}

        def next_distribution_account(self, *args, **kwargs):
            calls.append(("next_distribution_account", args, kwargs))
            return "ig_1"

        def distribution_slots(self, *args, **kwargs):
            calls.append(("distribution_slots", args, kwargs))
            return ["slot_1"]

        def next_valid_distribution_slot(self, *args, **kwargs):
            calls.append(("next_valid_distribution_slot", args, kwargs))
            return "slot_1", 1

        def distribution_summary(self, *args, **kwargs):
            calls.append(("distribution_summary", args, kwargs))
            return {"schema": "campaign_factory.distribution_summary.v1"}

        def latest_distribution_plan_for_asset(self, *args, **kwargs):
            calls.append(("latest_distribution_plan_for_asset", args, kwargs))
            return {"renderedAssetId": args[0]}

    services.distribution = FakeDistribution()

    assert services.create_distribution_plan("asset_1", instagram_account_id="ig_1") == {"id": "dist_1"}
    assert services.distribution_plan("dist_1") == {"id": "dist_1"}
    assert services.distribution_plans_for_asset("asset_1") == [{"renderedAssetId": "asset_1"}]
    assert services.distribution_plans_for_campaign("may") == [{"campaign": "may"}]
    assert services.clear_distribution_plans_for_campaign("may") == 2
    assert services.distribution_plan_payload({"id": "dist_1"}) == {"id": "dist_1"}
    assert services.plan_distribution("may", user_id="user_1") == {"schema": "campaign_factory.distribution_plan_run.v1"}
    assert services.next_distribution_account({"allowedInstagramAccountIds": ["ig_1"]}, "model", {}) == "ig_1"
    assert services.distribution_slots([10], 1) == ["slot_1"]
    assert services.next_valid_distribution_slot([], 0, "ig_1", {"id": "asset_1"}, {}, {}, {}, {}, []) == ("slot_1", 1)
    assert services.distribution_summary("may") == {"schema": "campaign_factory.distribution_summary.v1"}
    assert services.latest_distribution_plan_for_asset("asset_1") == {"renderedAssetId": "asset_1"}

    assert calls == [
        ("create_distribution_plan", ("asset_1",), {
            "surface": "regular_reel",
            "account_id": None,
            "instagram_account_id": "ig_1",
            "planned_window_start": None,
            "planned_window_end": None,
            "paired_rendered_asset_id": None,
            "reason_code": None,
            "smart_link": None,
            "cta_text": None,
            "instagram_trial_reels": False,
            "trial_graduation_strategy": None,
        }),
        ("distribution_plan", ("dist_1",), {}),
        ("distribution_plans_for_asset", ("asset_1",), {}),
        ("distribution_plans_for_campaign", ("may",), {}),
        ("clear_distribution_plans_for_campaign", ("may",), {}),
        ("distribution_plan_payload", ({"id": "dist_1"},), {}),
        ("plan_distribution", ("may",), {
            "user_id": "user_1",
            "mode": "preview",
            "strategy": "trial-heavy",
            "replace": True,
            "fallback_hours": None,
        }),
        ("next_distribution_account", ({"allowedInstagramAccountIds": ["ig_1"]}, "model", {}), {}),
        ("distribution_slots", ([10], 1), {}),
        ("next_valid_distribution_slot", ([], 0, "ig_1", {"id": "asset_1"}, {}, {}, {}, {}, []), {}),
        ("distribution_summary", ("may",), {}),
        ("latest_distribution_plan_for_asset", ("asset_1",), {}),
    ]


def test_core_services_delegates_decision_ledger_methods_to_decision_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeDecisionLedger:
        def decision_ledger_preview(self, *args, **kwargs):
            calls.append(("decision_ledger_preview", args, kwargs))
            return {"schema": "creator_os.decision_ledger_preview.v1"}

        def decision_ledger_report(self, *args, **kwargs):
            calls.append(("decision_ledger_report", args, kwargs))
            return {"schema": "creator_os.decision_ledger_report.v1"}

        def decision_ledger_summary(self, *args, **kwargs):
            calls.append(("decision_ledger_summary", args, kwargs))
            return {"schema": "creator_os.decision_ledger_summary.v1"}

        def decision_ledger_by_creator(self, *args, **kwargs):
            calls.append(("decision_ledger_by_creator", args, kwargs))
            return {"schema": "creator_os.decision_ledger_by_creator.v1"}

        def decision_ledger_by_account(self, *args, **kwargs):
            calls.append(("decision_ledger_by_account", args, kwargs))
            return {"schema": "creator_os.decision_ledger_by_account.v1"}

        def decision_ledger_by_surface(self, *args, **kwargs):
            calls.append(("decision_ledger_by_surface", args, kwargs))
            return {"schema": "creator_os.decision_ledger_by_surface.v1"}

        def decision_ledger_by_decision_type(self, *args, **kwargs):
            calls.append(("decision_ledger_by_decision_type", args, kwargs))
            return {"schema": "creator_os.decision_ledger_by_decision_type.v1"}

        def query_decision_ledger(self, *args, **kwargs):
            calls.append(("query_decision_ledger", args, kwargs))
            return {"decisionCount": 0}

    services.decision_ledger = FakeDecisionLedger()

    assert services.decision_ledger_preview(creator="Stacey", date="2026-06-06") == {
        "schema": "creator_os.decision_ledger_preview.v1",
    }
    assert services.decision_ledger_report(creator="Stacey") == {"schema": "creator_os.decision_ledger_report.v1"}
    assert services.decision_ledger_summary(creator="Stacey") == {"schema": "creator_os.decision_ledger_summary.v1"}
    assert services.decision_ledger_by_creator(creator="Stacey") == {
        "schema": "creator_os.decision_ledger_by_creator.v1",
    }
    assert services.decision_ledger_by_account(creator="Stacey", account_id="acct_1") == {
        "schema": "creator_os.decision_ledger_by_account.v1",
    }
    assert services.decision_ledger_by_surface(creator="Stacey", surface="story") == {
        "schema": "creator_os.decision_ledger_by_surface.v1",
    }
    assert services.decision_ledger_by_decision_type(creator="Stacey", decision_type="account_needs_story") == {
        "schema": "creator_os.decision_ledger_by_decision_type.v1",
    }
    assert services.query_decision_ledger(creator="Stacey") == {"decisionCount": 0}

    assert calls == [
        ("decision_ledger_preview", (), {
            "creator": "Stacey",
            "date": "2026-06-06",
            "threadsdash_report": None,
            "schedule_plan": None,
            "time_plan": None,
            "winner_expansion_report": None,
            "winner_expansion_plan": None,
            "variant_inventory_plan": None,
            "variant_metrics_rollup": None,
            "account_tiers": None,
            "generated_at": None,
        }),
        ("decision_ledger_report", (), {"creator": "Stacey"}),
        ("decision_ledger_summary", (), {"creator": "Stacey"}),
        ("decision_ledger_by_creator", (), {"creator": "Stacey"}),
        ("decision_ledger_by_account", (), {"creator": "Stacey", "account_id": "acct_1"}),
        ("decision_ledger_by_surface", (), {"creator": "Stacey", "surface": "story"}),
        ("decision_ledger_by_decision_type", (), {"creator": "Stacey", "decision_type": "account_needs_story"}),
        ("query_decision_ledger", (), {"creator": "Stacey"}),
    ]


def test_core_services_delegates_winner_expansion_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeWinnerExpansion:
        def winner_expansion_plan(self, *args, **kwargs):
            calls.append(("winner_expansion_plan", args, kwargs))
            return {"schema": "campaign_factory.winner_expansion_plan.v1"}

        def winner_expansion_report(self, *args, **kwargs):
            calls.append(("winner_expansion_report", args, kwargs))
            return {"schema": "campaign_factory.winner_expansion_report.v1"}

        def winner_variant_candidate(self, *args, **kwargs):
            calls.append(("winner_variant_candidate", args, kwargs))
            return {"variantAssetId": "asset_variant"}

        def winner_variant_candidate_decision(self, *args, **kwargs):
            calls.append(("winner_variant_candidate_decision", args, kwargs))
            return {"recommended": True, "blockingReasons": []}

        def latest_variant_audit_result(self, *args, **kwargs):
            calls.append(("latest_variant_audit_result", args, kwargs))
            return {"qualityScore": 100}

        def contentforge_result_from_operations(self, *args, **kwargs):
            calls.append(("contentforge_result_from_operations", args, kwargs))
            return {"familyName": "cover_frame"}

        def operation_family_from_operations(self, *args, **kwargs):
            calls.append(("operation_family_from_operations", args, kwargs))
            return "cover_frame"

        def score_value(self, *args, **kwargs):
            calls.append(("score_value", args, kwargs))
            return 95

        def variant_inventory_primary_blocking_reason(self, *args, **kwargs):
            calls.append(("variant_inventory_primary_blocking_reason", args, kwargs))
            return "missing_audio"

        def variant_inventory_quality_risk(self, *args, **kwargs):
            calls.append(("variant_inventory_quality_risk", args, kwargs))
            return "low"

        def variant_inventory_winner_rank(self, *args, **kwargs):
            calls.append(("variant_inventory_winner_rank", args, kwargs))
            return {"hasWinnerMetrics": True, "score": 10, "metrics": {"views": 10}}

        def variant_asset_payload(self, *args, **kwargs):
            calls.append(("variant_asset_payload", args, kwargs))
            return {"variantId": "var_1"}

    services.winner_expansion = FakeWinnerExpansion()

    assert services.winner_expansion_plan(
        creator="Stacey",
        parent_asset_id="asset_1",
        target_variants=3,
        preset="strong_safe",
    ) == {"schema": "campaign_factory.winner_expansion_plan.v1"}
    assert services.winner_expansion_report("may", min_views=100, min_reach=200, min_followers=3) == {
        "schema": "campaign_factory.winner_expansion_report.v1",
    }
    assert services.winner_variant_candidate({"variantAssetId": "asset_variant"}, {"id": "asset_variant"}) == {
        "variantAssetId": "asset_variant",
    }
    assert services.winner_variant_candidate_decision({"uploadReady": True}) == {
        "recommended": True,
        "blockingReasons": [],
    }
    assert services.latest_variant_audit_result("asset_variant") == {"qualityScore": 100}
    assert services.contentforge_result_from_operations([{"type": "contentforge_result"}]) == {"familyName": "cover_frame"}
    assert services.operation_family_from_operations([{"familyName": "cover_frame"}]) == "cover_frame"
    assert services.score_value("95") == 95
    assert services.variant_inventory_primary_blocking_reason(["missing_audio"]) == "missing_audio"
    assert services.variant_inventory_quality_risk("asset_1") == "low"
    assert services.variant_inventory_winner_rank(
        campaign_id="camp_1",
        parent_asset_id="asset_1",
        parent_reel_id="preel_1",
    ) == {"hasWinnerMetrics": True, "score": 10, "metrics": {"views": 10}}
    assert services.variant_asset_payload({"id": "var_1"}) == {"variantId": "var_1"}

    assert calls == [
        ("winner_expansion_plan", (), {
            "creator": "Stacey",
            "parent_asset_id": "asset_1",
            "target_variants": 3,
            "preset": "strong_safe",
        }),
        ("winner_expansion_report", ("may",), {"min_views": 100, "min_reach": 200, "min_followers": 3}),
        ("winner_variant_candidate", ({"variantAssetId": "asset_variant"}, {"id": "asset_variant"}), {}),
        ("winner_variant_candidate_decision", ({"uploadReady": True},), {}),
        ("latest_variant_audit_result", ("asset_variant",), {}),
        ("contentforge_result_from_operations", ([{"type": "contentforge_result"}],), {}),
        ("operation_family_from_operations", ([{"familyName": "cover_frame"}],), {}),
        ("score_value", ("95",), {}),
        ("variant_inventory_primary_blocking_reason", (["missing_audio"],), {}),
        ("variant_inventory_quality_risk", ("asset_1",), {}),
        ("variant_inventory_winner_rank", (), {
            "campaign_id": "camp_1",
            "parent_asset_id": "asset_1",
            "parent_reel_id": "preel_1",
        }),
        ("variant_asset_payload", ({"id": "var_1"},), {}),
    ]


def test_winner_expansion_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def winner_expansion_plan(self, *args, **kwargs):
            calls.append(("winner_expansion_plan", args, kwargs))
            return {"schema": "campaign_factory.winner_expansion_plan.v1"}

        def winner_expansion_report(self, *args, **kwargs):
            calls.append(("winner_expansion_report", args, kwargs))
            return {"schema": "campaign_factory.winner_expansion_report.v1"}

        def winner_variant_candidate(self, *args, **kwargs):
            calls.append(("winner_variant_candidate", args, kwargs))
            return {"variantAssetId": "asset_variant"}

        def winner_variant_candidate_decision(self, *args, **kwargs):
            calls.append(("winner_variant_candidate_decision", args, kwargs))
            return {"recommended": True, "blockingReasons": []}

        def latest_variant_audit_result(self, *args, **kwargs):
            calls.append(("latest_variant_audit_result", args, kwargs))
            return {"qualityScore": 100}

        def contentforge_result_from_operations(self, *args, **kwargs):
            calls.append(("contentforge_result_from_operations", args, kwargs))
            return {"familyName": "cover_frame"}

        def operation_family_from_operations(self, *args, **kwargs):
            calls.append(("operation_family_from_operations", args, kwargs))
            return "cover_frame"

        def score_value(self, *args, **kwargs):
            calls.append(("score_value", args, kwargs))
            return 95

        def variant_inventory_primary_blocking_reason(self, *args, **kwargs):
            calls.append(("variant_inventory_primary_blocking_reason", args, kwargs))
            return "missing_audio"

        def variant_inventory_quality_risk(self, *args, **kwargs):
            calls.append(("variant_inventory_quality_risk", args, kwargs))
            return "low"

        def variant_inventory_winner_rank(self, *args, **kwargs):
            calls.append(("variant_inventory_winner_rank", args, kwargs))
            return {"hasWinnerMetrics": True, "score": 10, "metrics": {"views": 10}}

    factory.services = FakeServices()

    assert factory.winner_expansion_plan(
        creator="Stacey",
        parent_asset_id="asset_1",
        target_variants=3,
        preset="strong_safe",
    ) == {"schema": "campaign_factory.winner_expansion_plan.v1"}
    assert factory.winner_expansion_report("may", min_views=100, min_reach=200, min_followers=3) == {
        "schema": "campaign_factory.winner_expansion_report.v1",
    }
    assert factory._winner_variant_candidate({"variantAssetId": "asset_variant"}, {"id": "asset_variant"}) == {
        "variantAssetId": "asset_variant",
    }
    assert factory._winner_variant_candidate_decision({"uploadReady": True}) == {
        "recommended": True,
        "blockingReasons": [],
    }
    assert factory._latest_variant_audit_result("asset_variant") == {"qualityScore": 100}
    assert factory._contentforge_result_from_operations([{"type": "contentforge_result"}]) == {
        "familyName": "cover_frame",
    }
    assert factory._operation_family_from_operations([{"familyName": "cover_frame"}]) == "cover_frame"
    assert factory._score_value("95") == 95
    assert factory._variant_inventory_primary_blocking_reason(["missing_audio"]) == "missing_audio"
    assert factory._variant_inventory_quality_risk("asset_1") == "low"
    assert factory._variant_inventory_winner_rank(
        campaign_id="camp_1",
        parent_asset_id="asset_1",
        parent_reel_id="preel_1",
    ) == {"hasWinnerMetrics": True, "score": 10, "metrics": {"views": 10}}

    assert calls == [
        ("winner_expansion_plan", (), {
            "creator": "Stacey",
            "parent_asset_id": "asset_1",
            "target_variants": 3,
            "preset": "strong_safe",
        }),
        ("winner_expansion_report", ("may",), {"min_views": 100, "min_reach": 200, "min_followers": 3}),
        ("winner_variant_candidate", ({"variantAssetId": "asset_variant"}, {"id": "asset_variant"}), {}),
        ("winner_variant_candidate_decision", ({"uploadReady": True},), {}),
        ("latest_variant_audit_result", ("asset_variant",), {}),
        ("contentforge_result_from_operations", ([{"type": "contentforge_result"}],), {}),
        ("operation_family_from_operations", ([{"familyName": "cover_frame"}],), {}),
        ("score_value", ("95",), {}),
        ("variant_inventory_primary_blocking_reason", (["missing_audio"],), {}),
        ("variant_inventory_quality_risk", ("asset_1",), {}),
        ("variant_inventory_winner_rank", (), {
            "campaign_id": "camp_1",
            "parent_asset_id": "asset_1",
            "parent_reel_id": "preel_1",
        }),
    ]


def test_core_services_delegates_creative_knowledge_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeCreativeKnowledge:
        def winner_registry(self, *args, **kwargs):
            calls.append(("winner_registry", args, kwargs))
            return {"schema": "campaign_factory.winner_registry.v1"}

        def concept_registry(self, *args, **kwargs):
            calls.append(("concept_registry", args, kwargs))
            return {"schema": "campaign_factory.concept_registry.v1"}

        def winner_patterns(self, *args, **kwargs):
            calls.append(("winner_patterns", args, kwargs))
            return {"schema": "campaign_factory.winner_patterns.v1"}

        def winner_knowledge_base(self, *args, **kwargs):
            calls.append(("winner_knowledge_base", args, kwargs))
            return {"schema": "campaign_factory.winner_knowledge_base.v1"}

        def winner_memory_rows(self, *args, **kwargs):
            calls.append(("winner_memory_rows", args, kwargs))
            return [{"post_id": "post_1"}]

        def winner_memory_item(self, *args, **kwargs):
            calls.append(("winner_memory_item", args, kwargs))
            return {"postId": "post_1"}

        def winner_concept_name(self, *args, **kwargs):
            calls.append(("winner_concept_name", args, kwargs))
            return "mirror selfie"

        def posting_window_label(self, *args, **kwargs):
            calls.append(("posting_window_label", args, kwargs))
            return "6pm"

        def winner_pattern_group(self, *args, **kwargs):
            calls.append(("winner_pattern_group", args, kwargs))
            return [{"conceptId": "concept_1"}]

    services.creative_knowledge = FakeCreativeKnowledge()

    assert services.winner_registry(creator="Stacey", campaign_slug="May", min_views=10) == {
        "schema": "campaign_factory.winner_registry.v1",
    }
    assert services.concept_registry(creator="Stacey", campaign_slug="May", min_views=10) == {
        "schema": "campaign_factory.concept_registry.v1",
    }
    assert services.winner_patterns(creator="Stacey", campaign_slug="May", min_views=10) == {
        "schema": "campaign_factory.winner_patterns.v1",
    }
    assert services.winner_knowledge_base(creator="Stacey", campaign_slug="May", min_views=10) == {
        "schema": "campaign_factory.winner_knowledge_base.v1",
    }
    assert services.winner_memory_rows(creator="Stacey", campaign_slug="May") == [{"post_id": "post_1"}]
    assert services.winner_memory_item({"post_id": "post_1"}, min_views=10, min_reach=10, min_followers=1) == {
        "postId": "post_1",
    }
    assert services.winner_concept_name({"concept_id": "concept_1"}) == "mirror selfie"
    assert services.posting_window_label("2026-06-06T18:12:00+00:00") == "6pm"
    assert services.winner_pattern_group(
        [{"conceptId": "concept_1"}],
        key_field="conceptId",
        label_field=None,
        output_key="conceptId",
        output_label=None,
    ) == [{"conceptId": "concept_1"}]

    assert calls == [
        ("winner_registry", (), {
            "creator": "Stacey",
            "campaign_slug": "May",
            "min_views": 10,
            "min_reach": None,
            "min_followers": 1,
        }),
        ("concept_registry", (), {
            "creator": "Stacey",
            "campaign_slug": "May",
            "min_views": 10,
            "min_reach": None,
            "min_followers": 1,
        }),
        ("winner_patterns", (), {
            "creator": "Stacey",
            "campaign_slug": "May",
            "min_views": 10,
            "min_reach": None,
            "min_followers": 1,
        }),
        ("winner_knowledge_base", (), {
            "creator": "Stacey",
            "campaign_slug": "May",
            "min_views": 10,
            "min_reach": None,
            "min_followers": 1,
        }),
        ("winner_memory_rows", (), {"creator": "Stacey", "campaign_slug": "May"}),
        ("winner_memory_item", ({"post_id": "post_1"},), {
            "min_views": 10,
            "min_reach": 10,
            "min_followers": 1,
        }),
        ("winner_concept_name", ({"concept_id": "concept_1"},), {}),
        ("posting_window_label", ("2026-06-06T18:12:00+00:00",), {}),
        ("winner_pattern_group", ([{"conceptId": "concept_1"}],), {
            "key_field": "conceptId",
            "label_field": None,
            "output_key": "conceptId",
            "output_label": None,
        }),
    ]


def test_creative_knowledge_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def winner_registry(self, *args, **kwargs):
            calls.append(("winner_registry", args, kwargs))
            return {"schema": "campaign_factory.winner_registry.v1"}

        def concept_registry(self, *args, **kwargs):
            calls.append(("concept_registry", args, kwargs))
            return {"schema": "campaign_factory.concept_registry.v1"}

        def winner_patterns(self, *args, **kwargs):
            calls.append(("winner_patterns", args, kwargs))
            return {"schema": "campaign_factory.winner_patterns.v1"}

        def winner_knowledge_base(self, *args, **kwargs):
            calls.append(("winner_knowledge_base", args, kwargs))
            return {"schema": "campaign_factory.winner_knowledge_base.v1"}

        def winner_memory_rows(self, *args, **kwargs):
            calls.append(("winner_memory_rows", args, kwargs))
            return [{"post_id": "post_1"}]

        def winner_memory_item(self, *args, **kwargs):
            calls.append(("winner_memory_item", args, kwargs))
            return {"postId": "post_1"}

        def winner_concept_name(self, *args, **kwargs):
            calls.append(("winner_concept_name", args, kwargs))
            return "mirror selfie"

        def posting_window_label(self, *args, **kwargs):
            calls.append(("posting_window_label", args, kwargs))
            return "6pm"

        def winner_pattern_group(self, *args, **kwargs):
            calls.append(("winner_pattern_group", args, kwargs))
            return [{"conceptId": "concept_1"}]

    factory.services = FakeServices()

    assert factory.winner_registry(creator="Stacey", campaign_slug="May", min_views=10) == {
        "schema": "campaign_factory.winner_registry.v1",
    }
    assert factory.concept_registry(creator="Stacey", campaign_slug="May", min_views=10) == {
        "schema": "campaign_factory.concept_registry.v1",
    }
    assert factory.winner_patterns(creator="Stacey", campaign_slug="May", min_views=10) == {
        "schema": "campaign_factory.winner_patterns.v1",
    }
    assert factory.winner_knowledge_base(creator="Stacey", campaign_slug="May", min_views=10) == {
        "schema": "campaign_factory.winner_knowledge_base.v1",
    }
    assert factory._winner_memory_rows(creator="Stacey", campaign_slug="May") == [{"post_id": "post_1"}]
    assert factory._winner_memory_item({"post_id": "post_1"}, min_views=10, min_reach=10, min_followers=1) == {
        "postId": "post_1",
    }
    assert factory._winner_concept_name({"concept_id": "concept_1"}) == "mirror selfie"
    assert factory._posting_window_label("2026-06-06T18:12:00+00:00") == "6pm"
    assert factory._winner_pattern_group(
        [{"conceptId": "concept_1"}],
        key_field="conceptId",
        label_field=None,
        output_key="conceptId",
        output_label=None,
    ) == [{"conceptId": "concept_1"}]

    assert calls == [
        ("winner_registry", (), {
            "creator": "Stacey",
            "campaign_slug": "May",
            "min_views": 10,
            "min_reach": None,
            "min_followers": 1,
        }),
        ("concept_registry", (), {
            "creator": "Stacey",
            "campaign_slug": "May",
            "min_views": 10,
            "min_reach": None,
            "min_followers": 1,
        }),
        ("winner_patterns", (), {
            "creator": "Stacey",
            "campaign_slug": "May",
            "min_views": 10,
            "min_reach": None,
            "min_followers": 1,
        }),
        ("winner_knowledge_base", (), {
            "creator": "Stacey",
            "campaign_slug": "May",
            "min_views": 10,
            "min_reach": None,
            "min_followers": 1,
        }),
        ("winner_memory_rows", (), {"creator": "Stacey", "campaign_slug": "May"}),
        ("winner_memory_item", ({"post_id": "post_1"},), {
            "min_views": 10,
            "min_reach": 10,
            "min_followers": 1,
        }),
        ("winner_concept_name", ({"concept_id": "concept_1"},), {}),
        ("posting_window_label", ("2026-06-06T18:12:00+00:00",), {}),
        ("winner_pattern_group", ([{"conceptId": "concept_1"}],), {
            "key_field": "conceptId",
            "label_field": None,
            "output_key": "conceptId",
            "output_label": None,
        }),
    ]


def test_discoverability_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def discoverability_safe_content_contract(self, *args, **kwargs):
            calls.append(("discoverability_safe_content_contract", args, kwargs))
            return {"schema": "campaign_factory.discoverability_safe_content_contract.v1"}

        def discoverability_intake_gate(self, *args, **kwargs):
            calls.append(("discoverability_intake_gate", args, kwargs))
            return {"schema": "campaign_factory.discoverability_intake_gate.v1"}

        def discoverability_generation_gate(self, *args, **kwargs):
            calls.append(("discoverability_generation_gate", args, kwargs))
            return {"schema": "campaign_factory.discoverability_generation_gate.v1"}

        def discoverability_pre_render_gate(self, *args, **kwargs):
            calls.append(("discoverability_pre_render_gate", args, kwargs))
            return {"schema": "campaign_factory.discoverability_pre_render_gate.v1"}

        def discoverability_violation_origin_map(self, *args, **kwargs):
            calls.append(("discoverability_violation_origin_map", args, kwargs))
            return {"schema": "creator_os.discoverability_violation_origin_map.v1"}

        def parent_factory_discoverability_loss_analysis(self, *args, **kwargs):
            calls.append(("parent_factory_discoverability_loss_analysis", args, kwargs))
            return {"schema": "creator_os.parent_factory_discoverability_loss_analysis.v1"}

        def parent_factory_waterfall_after_discoverability(self, *args, **kwargs):
            calls.append(("parent_factory_waterfall_after_discoverability", args, kwargs))
            return {"schema": "creator_os.parent_factory_waterfall_after_discoverability.v1"}

        def discoverability_prevention_audit(self, *args, **kwargs):
            calls.append(("discoverability_prevention_audit", args, kwargs))
            return {"schema": "creator_os.discoverability_prevention_audit.v1"}

        def discoverability_prevention_scorecard(self, *args, **kwargs):
            calls.append(("discoverability_prevention_scorecard", args, kwargs))
            return {"schema": "creator_os.discoverability_prevention_scorecard.v1"}

        def parent_factory_observed_discoverability_terms(self, *args, **kwargs):
            calls.append(("parent_factory_observed_discoverability_terms", args, kwargs))
            return [{"reason": "dm_reference", "matchedText": "dm"}]

        def parent_factory_captured_discoverability_evidence(self, *args, **kwargs):
            calls.append(("parent_factory_captured_discoverability_evidence", args, kwargs))
            return [{"reason": "dm_reference", "matchedText": "dm"}]

        def discoverability_text_values(self, *args, **kwargs):
            calls.append(("discoverability_text_values", args, kwargs))
            return ["caption"]

        def discoverability_loss_category(self, *args, **kwargs):
            calls.append(("discoverability_loss_category", args, kwargs))
            return "dm_language"

        def discoverability_prevention_stage(self, *args, **kwargs):
            calls.append(("discoverability_prevention_stage", args, kwargs))
            return "caption_creation"

        def discoverability_gate_fields(self, *args, **kwargs):
            calls.append(("discoverability_gate_fields", args, kwargs))
            return [("caption", "dm me")]

        def discoverability_gate_result(self, *args, **kwargs):
            calls.append(("discoverability_gate_result", args, kwargs))
            return {"gate": args[0]}

        def discoverability_origin_stage(self, *args, **kwargs):
            calls.append(("discoverability_origin_stage", args, kwargs))
            return "caption_generation"

        def post_discoverability_downstream_confidence(self, *args, **kwargs):
            calls.append(("post_discoverability_downstream_confidence", args, kwargs))
            return {"confidenceMethod": "wilson_lower_bound_95pct"}

        def discoverability_evidence_for_fields(self, *args, **kwargs):
            calls.append(("discoverability_evidence_for_fields", args, kwargs))
            return [{"failureCategory": "dm_language"}]

    factory.services = FakeServices()

    assert factory.discoverability_safe_content_contract("dm me") == {
        "schema": "campaign_factory.discoverability_safe_content_contract.v1",
    }
    assert factory.discoverability_intake_gate({"source_caption": "dm me"}) == {
        "schema": "campaign_factory.discoverability_intake_gate.v1",
    }
    assert factory.discoverability_generation_gate({"caption_text": "dm me"}) == {
        "schema": "campaign_factory.discoverability_generation_gate.v1",
    }
    assert factory.discoverability_pre_render_gate({"caption": "dm me"}) == {
        "schema": "campaign_factory.discoverability_pre_render_gate.v1",
    }
    assert factory.discoverability_violation_origin_map() == {
        "schema": "creator_os.discoverability_violation_origin_map.v1",
    }
    assert factory.parent_factory_discoverability_loss_analysis(waterfall={"stages": []}) == {
        "schema": "creator_os.parent_factory_discoverability_loss_analysis.v1",
    }
    assert factory.parent_factory_waterfall_after_discoverability() == {
        "schema": "creator_os.parent_factory_waterfall_after_discoverability.v1",
    }
    assert factory.discoverability_prevention_audit() == {"schema": "creator_os.discoverability_prevention_audit.v1"}
    assert factory.discoverability_prevention_scorecard() == {
        "schema": "creator_os.discoverability_prevention_scorecard.v1",
    }
    assert factory._parent_factory_observed_discoverability_terms() == [{"reason": "dm_reference", "matchedText": "dm"}]
    assert factory._parent_factory_captured_discoverability_evidence() == [{"reason": "dm_reference", "matchedText": "dm"}]
    assert factory._discoverability_text_values({"caption": "caption"}) == ["caption"]
    assert factory._discoverability_loss_category("dm_reference", "dm") == "dm_language"
    assert factory._discoverability_prevention_stage("dm_language") == "caption_creation"
    assert factory._discoverability_gate_fields({"caption": "dm me"}, {"caption"}) == [("caption", "dm me")]
    assert factory._discoverability_gate_result("intake", [("caption", "dm me")]) == {"gate": "intake"}
    assert factory._discoverability_origin_stage("caption", "dm_reference") == "caption_generation"
    assert factory._post_discoverability_downstream_confidence() == {"confidenceMethod": "wilson_lower_bound_95pct"}
    assert factory._discoverability_evidence_for_fields([("caption", "dm me")]) == [{"failureCategory": "dm_language"}]

    assert calls == [
        ("discoverability_safe_content_contract", ("dm me",), {}),
        ("discoverability_intake_gate", ({"source_caption": "dm me"},), {}),
        ("discoverability_generation_gate", ({"caption_text": "dm me"},), {}),
        ("discoverability_pre_render_gate", ({"caption": "dm me"},), {}),
        ("discoverability_violation_origin_map", (), {}),
        ("parent_factory_discoverability_loss_analysis", (), {"waterfall": {"stages": []}}),
        ("parent_factory_waterfall_after_discoverability", (), {}),
        ("discoverability_prevention_audit", (), {}),
        ("discoverability_prevention_scorecard", (), {}),
        ("parent_factory_observed_discoverability_terms", (), {}),
        ("parent_factory_captured_discoverability_evidence", (), {}),
        ("discoverability_text_values", ({"caption": "caption"},), {}),
        ("discoverability_loss_category", ("dm_reference", "dm"), {}),
        ("discoverability_prevention_stage", ("dm_language",), {}),
        ("discoverability_gate_fields", ({"caption": "dm me"}, {"caption"}), {}),
        ("discoverability_gate_result", ("intake", [("caption", "dm me")]), {}),
        ("discoverability_origin_stage", ("caption", "dm_reference"), {}),
        ("post_discoverability_downstream_confidence", (), {}),
        ("discoverability_evidence_for_fields", ([("caption", "dm me")],), {}),
    ]


def test_core_services_delegates_discoverability_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeDiscoverability:
        def discoverability_safe_content_contract(self, *args, **kwargs):
            calls.append(("discoverability_safe_content_contract", args, kwargs))
            return {"schema": "campaign_factory.discoverability_safe_content_contract.v1"}

        def discoverability_intake_gate(self, *args, **kwargs):
            calls.append(("discoverability_intake_gate", args, kwargs))
            return {"schema": "campaign_factory.discoverability_intake_gate.v1"}

        def discoverability_generation_gate(self, *args, **kwargs):
            calls.append(("discoverability_generation_gate", args, kwargs))
            return {"schema": "campaign_factory.discoverability_generation_gate.v1"}

        def discoverability_pre_render_gate(self, *args, **kwargs):
            calls.append(("discoverability_pre_render_gate", args, kwargs))
            return {"schema": "campaign_factory.discoverability_pre_render_gate.v1"}

        def discoverability_violation_origin_map(self, *args, **kwargs):
            calls.append(("discoverability_violation_origin_map", args, kwargs))
            return {"schema": "creator_os.discoverability_violation_origin_map.v1"}

        def parent_factory_discoverability_loss_analysis(self, *args, **kwargs):
            calls.append(("parent_factory_discoverability_loss_analysis", args, kwargs))
            return {"schema": "creator_os.parent_factory_discoverability_loss_analysis.v1"}

        def parent_factory_waterfall_after_discoverability(self, *args, **kwargs):
            calls.append(("parent_factory_waterfall_after_discoverability", args, kwargs))
            return {"schema": "creator_os.parent_factory_waterfall_after_discoverability.v1"}

        def discoverability_prevention_audit(self, *args, **kwargs):
            calls.append(("discoverability_prevention_audit", args, kwargs))
            return {"schema": "creator_os.discoverability_prevention_audit.v1"}

        def discoverability_prevention_scorecard(self, *args, **kwargs):
            calls.append(("discoverability_prevention_scorecard", args, kwargs))
            return {"schema": "creator_os.discoverability_prevention_scorecard.v1"}

        def parent_factory_observed_discoverability_terms(self, *args, **kwargs):
            calls.append(("parent_factory_observed_discoverability_terms", args, kwargs))
            return [{"reason": "dm_reference", "matchedText": "dm"}]

        def parent_factory_captured_discoverability_evidence(self, *args, **kwargs):
            calls.append(("parent_factory_captured_discoverability_evidence", args, kwargs))
            return [{"reason": "dm_reference", "matchedText": "dm"}]

        def discoverability_text_values(self, *args, **kwargs):
            calls.append(("discoverability_text_values", args, kwargs))
            return ["caption"]

        def discoverability_loss_category(self, *args, **kwargs):
            calls.append(("discoverability_loss_category", args, kwargs))
            return "dm_language"

        def discoverability_prevention_stage(self, *args, **kwargs):
            calls.append(("discoverability_prevention_stage", args, kwargs))
            return "caption_creation"

        def discoverability_gate_fields(self, *args, **kwargs):
            calls.append(("discoverability_gate_fields", args, kwargs))
            return [("caption", "dm me")]

        def discoverability_gate_result(self, *args, **kwargs):
            calls.append(("discoverability_gate_result", args, kwargs))
            return {"gate": args[0]}

        def discoverability_origin_stage(self, *args, **kwargs):
            calls.append(("discoverability_origin_stage", args, kwargs))
            return "caption_generation"

        def post_discoverability_downstream_confidence(self, *args, **kwargs):
            calls.append(("post_discoverability_downstream_confidence", args, kwargs))
            return {"confidenceMethod": "wilson_lower_bound_95pct"}

        def discoverability_evidence_for_fields(self, *args, **kwargs):
            calls.append(("discoverability_evidence_for_fields", args, kwargs))
            return [{"failureCategory": "dm_language"}]

    services.discoverability = FakeDiscoverability()

    assert services.discoverability_safe_content_contract("dm me") == {
        "schema": "campaign_factory.discoverability_safe_content_contract.v1",
    }
    assert services.discoverability_intake_gate({"source_caption": "dm me"}) == {
        "schema": "campaign_factory.discoverability_intake_gate.v1",
    }
    assert services.discoverability_generation_gate({"caption_text": "dm me"}) == {
        "schema": "campaign_factory.discoverability_generation_gate.v1",
    }
    assert services.discoverability_pre_render_gate({"caption": "dm me"}) == {
        "schema": "campaign_factory.discoverability_pre_render_gate.v1",
    }
    assert services.discoverability_violation_origin_map() == {
        "schema": "creator_os.discoverability_violation_origin_map.v1",
    }
    assert services.parent_factory_discoverability_loss_analysis(waterfall={"stages": []}) == {
        "schema": "creator_os.parent_factory_discoverability_loss_analysis.v1",
    }
    assert services.parent_factory_waterfall_after_discoverability() == {
        "schema": "creator_os.parent_factory_waterfall_after_discoverability.v1",
    }
    assert services.discoverability_prevention_audit() == {"schema": "creator_os.discoverability_prevention_audit.v1"}
    assert services.discoverability_prevention_scorecard() == {
        "schema": "creator_os.discoverability_prevention_scorecard.v1",
    }
    assert services.parent_factory_observed_discoverability_terms() == [{"reason": "dm_reference", "matchedText": "dm"}]
    assert services.parent_factory_captured_discoverability_evidence() == [{"reason": "dm_reference", "matchedText": "dm"}]
    assert services.discoverability_text_values({"caption": "caption"}) == ["caption"]
    assert services.discoverability_loss_category("dm_reference", "dm") == "dm_language"
    assert services.discoverability_prevention_stage("dm_language") == "caption_creation"
    assert services.discoverability_gate_fields({"caption": "dm me"}, {"caption"}) == [("caption", "dm me")]
    assert services.discoverability_gate_result("intake", [("caption", "dm me")]) == {"gate": "intake"}
    assert services.discoverability_origin_stage("caption", "dm_reference") == "caption_generation"
    assert services.post_discoverability_downstream_confidence() == {"confidenceMethod": "wilson_lower_bound_95pct"}
    assert services.discoverability_evidence_for_fields([("caption", "dm me")]) == [{"failureCategory": "dm_language"}]

    assert calls == [
        ("discoverability_safe_content_contract", ("dm me",), {}),
        ("discoverability_intake_gate", ({"source_caption": "dm me"},), {}),
        ("discoverability_generation_gate", ({"caption_text": "dm me"},), {}),
        ("discoverability_pre_render_gate", ({"caption": "dm me"},), {}),
        ("discoverability_violation_origin_map", (), {}),
        ("parent_factory_discoverability_loss_analysis", (), {"waterfall": {"stages": []}}),
        ("parent_factory_waterfall_after_discoverability", (), {}),
        ("discoverability_prevention_audit", (), {}),
        ("discoverability_prevention_scorecard", (), {}),
        ("parent_factory_observed_discoverability_terms", (), {}),
        ("parent_factory_captured_discoverability_evidence", (), {}),
        ("discoverability_text_values", ({"caption": "caption"},), {}),
        ("discoverability_loss_category", ("dm_reference", "dm"), {}),
        ("discoverability_prevention_stage", ("dm_language",), {}),
        ("discoverability_gate_fields", ({"caption": "dm me"}, {"caption"}), {}),
        ("discoverability_gate_result", ("intake", [("caption", "dm me")]), {}),
        ("discoverability_origin_stage", ("caption", "dm_reference"), {}),
        ("post_discoverability_downstream_confidence", (), {}),
        ("discoverability_evidence_for_fields", ([("caption", "dm me")],), {}),
    ]


def test_surface_registration_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def register_surface_asset(self, *args, **kwargs):
            calls.append(("register_surface_asset", args, kwargs))
            return {"schema": "campaign_factory.register_surface_asset.v1"}

        def surface_registration_components(self, *args, **kwargs):
            calls.append(("surface_registration_components", args, kwargs))
            return [{"path": Path("/tmp/surface.png")}]

        def surface_registration_component(self, *args, **kwargs):
            calls.append(("surface_registration_component", args, kwargs))
            return {"path": Path("/tmp/surface.png")}

        def stage_surface_registration_file(self, *args, **kwargs):
            calls.append(("stage_surface_registration_file", args, kwargs))
            return Path("/tmp/staged.png")

    factory.services = FakeServices()

    assert factory.register_surface_asset(
        input_path=Path("/tmp/surface.png"),
        surface="feed_single",
        creator="Stacey",
        campaign_slug="may",
        instagram_post_caption="caption",
        target_ratio="1:1",
        model_slug="stacey",
        operator="op",
        alt_text=["first"],
        story_asset_class="story_selfie",
        story_cta_type="none",
        story_cta_text="",
        story_cta_target_url="",
        story_intent="casual_selfie",
        story_goal="engagement",
        story_style="selfie",
        snapchat_username="snap",
        snapchat_display_name="Snap",
        snapchat_cta_text="add me",
    ) == {"schema": "campaign_factory.register_surface_asset.v1"}
    assert factory._surface_registration_components(
        input_path=Path("/tmp/surface.png"),
        surface="feed_single",
        target_ratio="1:1",
    ) == [{"path": Path("/tmp/surface.png")}]
    assert factory._surface_registration_component(
        Path("/tmp/surface.png"),
        surface="feed_single",
        target_ratio="1:1",
    ) == {"path": Path("/tmp/surface.png")}
    assert factory._stage_surface_registration_file(
        Path("/tmp/surface.png"),
        Path("/tmp/rendered"),
        content_surface="feed_single",
        content_hash="abc123",
        component_index=0,
    ) == Path("/tmp/staged.png")

    assert calls == [
        ("register_surface_asset", (), {
            "input_path": Path("/tmp/surface.png"),
            "surface": "feed_single",
            "creator": "Stacey",
            "campaign_slug": "may",
            "instagram_post_caption": "caption",
            "target_ratio": "1:1",
            "model_slug": "stacey",
            "operator": "op",
            "alt_text": ["first"],
            "story_asset_class": "story_selfie",
            "story_cta_type": "none",
            "story_cta_text": "",
            "story_cta_target_url": "",
            "story_intent": "casual_selfie",
            "story_goal": "engagement",
            "story_style": "selfie",
            "snapchat_username": "snap",
            "snapchat_display_name": "Snap",
            "snapchat_cta_text": "add me",
        }),
        ("surface_registration_components", (), {
            "input_path": Path("/tmp/surface.png"),
            "surface": "feed_single",
            "target_ratio": "1:1",
        }),
        ("surface_registration_component", (Path("/tmp/surface.png"),), {
            "surface": "feed_single",
            "target_ratio": "1:1",
        }),
        ("stage_surface_registration_file", (Path("/tmp/surface.png"), Path("/tmp/rendered")), {
            "content_surface": "feed_single",
            "content_hash": "abc123",
            "component_index": 0,
        }),
    ]


def test_core_services_delegates_surface_registration_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeSurfaceRegistration:
        def register_surface_asset(self, *args, **kwargs):
            calls.append(("register_surface_asset", args, kwargs))
            return {"schema": "campaign_factory.register_surface_asset.v1"}

        def surface_registration_components(self, *args, **kwargs):
            calls.append(("surface_registration_components", args, kwargs))
            return [{"path": Path("/tmp/surface.png")}]

        def surface_registration_component(self, *args, **kwargs):
            calls.append(("surface_registration_component", args, kwargs))
            return {"path": Path("/tmp/surface.png")}

        def stage_surface_registration_file(self, *args, **kwargs):
            calls.append(("stage_surface_registration_file", args, kwargs))
            return Path("/tmp/staged.png")

    services.surface_registration = FakeSurfaceRegistration()

    assert services.register_surface_asset(
        input_path=Path("/tmp/surface.png"),
        surface="feed_single",
        creator="Stacey",
        campaign_slug="may",
        instagram_post_caption="caption",
    ) == {"schema": "campaign_factory.register_surface_asset.v1"}
    assert services.surface_registration_components(
        input_path=Path("/tmp/surface.png"),
        surface="feed_single",
        target_ratio="1:1",
    ) == [{"path": Path("/tmp/surface.png")}]
    assert services.surface_registration_component(
        Path("/tmp/surface.png"),
        surface="feed_single",
        target_ratio="1:1",
    ) == {"path": Path("/tmp/surface.png")}
    assert services.stage_surface_registration_file(
        Path("/tmp/surface.png"),
        Path("/tmp/rendered"),
        content_surface="feed_single",
        content_hash="abc123",
        component_index=0,
    ) == Path("/tmp/staged.png")

    assert calls == [
        ("register_surface_asset", (), {
            "input_path": Path("/tmp/surface.png"),
            "surface": "feed_single",
            "creator": "Stacey",
            "campaign_slug": "may",
            "instagram_post_caption": "caption",
            "target_ratio": None,
            "model_slug": None,
            "operator": None,
            "alt_text": None,
            "story_asset_class": None,
            "story_cta_type": None,
            "story_cta_text": None,
            "story_cta_target_url": None,
            "story_intent": None,
            "story_goal": None,
            "story_style": None,
            "snapchat_username": None,
            "snapchat_display_name": None,
            "snapchat_cta_text": None,
        }),
        ("surface_registration_components", (), {
            "input_path": Path("/tmp/surface.png"),
            "surface": "feed_single",
            "target_ratio": "1:1",
        }),
        ("surface_registration_component", (Path("/tmp/surface.png"),), {
            "surface": "feed_single",
            "target_ratio": "1:1",
        }),
        ("stage_surface_registration_file", (Path("/tmp/surface.png"), Path("/tmp/rendered")), {
            "content_surface": "feed_single",
            "content_hash": "abc123",
            "component_index": 0,
        }),
    ]


def test_carousel_integrity_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def carousel_integrity_report(self, *args, **kwargs):
            calls.append(("carousel_integrity_report", args, kwargs))
            return {"schema": "campaign_factory.carousel_integrity_report.v1"}

        def carousel_child_metrics_plan(self, *args, **kwargs):
            calls.append(("carousel_child_metrics_plan", args, kwargs))
            return {"schema": "campaign_factory.carousel_child_metrics_plan.v1"}

        def carousel_report_assets(self, *args, **kwargs):
            calls.append(("carousel_report_assets", args, kwargs))
            return [{"id": "asset_carousel"}]

        def carousel_integrity_for_asset(self, *args, **kwargs):
            calls.append(("carousel_integrity_for_asset", args, kwargs))
            return {"assetId": "asset_carousel"}

        def carousel_component_signature(self, *args, **kwargs):
            calls.append(("carousel_component_signature", args, kwargs))
            return [{"componentIndex": 0}]

        def carousel_media_item_signature(self, *args, **kwargs):
            calls.append(("carousel_media_item_signature", args, kwargs))
            return [{"componentIndex": 0}]

        def carousel_signature_payload(self, *args, **kwargs):
            calls.append(("carousel_signature_payload", args, kwargs))
            return {"slideCount": 1}

        def carousel_boundary_result(self, *args, **kwargs):
            calls.append(("carousel_boundary_result", args, kwargs))
            return {"boundary": args[0]}

        def carousel_meta_child_payload_preview(self, *args, **kwargs):
            calls.append(("carousel_meta_child_payload_preview", args, kwargs))
            return {"children": []}

    factory.services = FakeServices()

    assert factory.carousel_integrity_report(
        creator="Stacey",
        campaign_slug="may",
        rendered_asset_id="asset_carousel",
    ) == {"schema": "campaign_factory.carousel_integrity_report.v1"}
    assert factory.carousel_child_metrics_plan(
        creator="Stacey",
        campaign_slug="may",
        rendered_asset_id="asset_carousel",
    ) == {"schema": "campaign_factory.carousel_child_metrics_plan.v1"}
    assert factory._carousel_report_assets(
        creator="Stacey",
        campaign_slug="may",
        rendered_asset_id="asset_carousel",
    ) == [{"id": "asset_carousel"}]
    assert factory._carousel_integrity_for_asset({"id": "asset_carousel"}) == {"assetId": "asset_carousel"}
    assert factory._carousel_component_signature([{"component_index": 0}]) == [{"componentIndex": 0}]
    assert factory._carousel_media_item_signature([{"componentIndex": 0}]) == [{"componentIndex": 0}]
    assert factory._carousel_signature_payload([{"componentIndex": 0}], extra={"ok": True}) == {"slideCount": 1}
    assert factory._carousel_boundary_result("a_to_b", [{"componentIndex": 0}], [{"componentIndex": 0}]) == {
        "boundary": "a_to_b",
    }
    assert factory._carousel_meta_child_payload_preview(
        asset={"id": "asset_carousel"},
        draft={},
        components=[],
    ) == {"children": []}

    assert calls == [
        ("carousel_integrity_report", (), {
            "creator": "Stacey",
            "campaign_slug": "may",
            "rendered_asset_id": "asset_carousel",
        }),
        ("carousel_child_metrics_plan", (), {
            "creator": "Stacey",
            "campaign_slug": "may",
            "rendered_asset_id": "asset_carousel",
        }),
        ("carousel_report_assets", (), {
            "creator": "Stacey",
            "campaign_slug": "may",
            "rendered_asset_id": "asset_carousel",
        }),
        ("carousel_integrity_for_asset", ({"id": "asset_carousel"},), {}),
        ("carousel_component_signature", ([{"component_index": 0}],), {}),
        ("carousel_media_item_signature", ([{"componentIndex": 0}],), {}),
        ("carousel_signature_payload", ([{"componentIndex": 0}],), {"extra": {"ok": True}}),
        ("carousel_boundary_result", ("a_to_b", [{"componentIndex": 0}], [{"componentIndex": 0}]), {}),
        ("carousel_meta_child_payload_preview", (), {
            "asset": {"id": "asset_carousel"},
            "draft": {},
            "components": [],
        }),
    ]


def test_core_services_delegates_carousel_integrity_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeCarouselIntegrity:
        def carousel_integrity_report(self, *args, **kwargs):
            calls.append(("carousel_integrity_report", args, kwargs))
            return {"schema": "campaign_factory.carousel_integrity_report.v1"}

        def carousel_child_metrics_plan(self, *args, **kwargs):
            calls.append(("carousel_child_metrics_plan", args, kwargs))
            return {"schema": "campaign_factory.carousel_child_metrics_plan.v1"}

        def carousel_report_assets(self, *args, **kwargs):
            calls.append(("carousel_report_assets", args, kwargs))
            return [{"id": "asset_carousel"}]

        def carousel_integrity_for_asset(self, *args, **kwargs):
            calls.append(("carousel_integrity_for_asset", args, kwargs))
            return {"assetId": "asset_carousel"}

        def carousel_component_signature(self, *args, **kwargs):
            calls.append(("carousel_component_signature", args, kwargs))
            return [{"componentIndex": 0}]

        def carousel_media_item_signature(self, *args, **kwargs):
            calls.append(("carousel_media_item_signature", args, kwargs))
            return [{"componentIndex": 0}]

        def carousel_signature_payload(self, *args, **kwargs):
            calls.append(("carousel_signature_payload", args, kwargs))
            return {"slideCount": 1}

        def carousel_boundary_result(self, *args, **kwargs):
            calls.append(("carousel_boundary_result", args, kwargs))
            return {"boundary": args[0]}

        def carousel_meta_child_payload_preview(self, *args, **kwargs):
            calls.append(("carousel_meta_child_payload_preview", args, kwargs))
            return {"children": []}

    services.carousel_integrity = FakeCarouselIntegrity()

    assert services.carousel_integrity_report(
        creator="Stacey",
        campaign_slug="may",
        rendered_asset_id="asset_carousel",
    ) == {"schema": "campaign_factory.carousel_integrity_report.v1"}
    assert services.carousel_child_metrics_plan(
        creator="Stacey",
        campaign_slug="may",
        rendered_asset_id="asset_carousel",
    ) == {"schema": "campaign_factory.carousel_child_metrics_plan.v1"}
    assert services.carousel_report_assets(
        creator="Stacey",
        campaign_slug="may",
        rendered_asset_id="asset_carousel",
    ) == [{"id": "asset_carousel"}]
    assert services.carousel_integrity_for_asset({"id": "asset_carousel"}) == {"assetId": "asset_carousel"}
    assert services.carousel_component_signature([{"component_index": 0}]) == [{"componentIndex": 0}]
    assert services.carousel_media_item_signature([{"componentIndex": 0}]) == [{"componentIndex": 0}]
    assert services.carousel_signature_payload([{"componentIndex": 0}], extra={"ok": True}) == {"slideCount": 1}
    assert services.carousel_boundary_result("a_to_b", [{"componentIndex": 0}], [{"componentIndex": 0}]) == {
        "boundary": "a_to_b",
    }
    assert services.carousel_meta_child_payload_preview(
        asset={"id": "asset_carousel"},
        draft={},
        components=[],
    ) == {"children": []}

    assert calls == [
        ("carousel_integrity_report", (), {
            "creator": "Stacey",
            "campaign_slug": "may",
            "rendered_asset_id": "asset_carousel",
        }),
        ("carousel_child_metrics_plan", (), {
            "creator": "Stacey",
            "campaign_slug": "may",
            "rendered_asset_id": "asset_carousel",
        }),
        ("carousel_report_assets", (), {
            "creator": "Stacey",
            "campaign_slug": "may",
            "rendered_asset_id": "asset_carousel",
        }),
        ("carousel_integrity_for_asset", ({"id": "asset_carousel"},), {}),
        ("carousel_component_signature", ([{"component_index": 0}],), {}),
        ("carousel_media_item_signature", ([{"componentIndex": 0}],), {}),
        ("carousel_signature_payload", ([{"componentIndex": 0}],), {"extra": {"ok": True}}),
        ("carousel_boundary_result", ("a_to_b", [{"componentIndex": 0}], [{"componentIndex": 0}]), {}),
        ("carousel_meta_child_payload_preview", (), {
            "asset": {"id": "asset_carousel"},
            "draft": {},
            "components": [],
        }),
    ]


def test_exception_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def create_exception(self, *args, **kwargs):
            calls.append(("create_exception", args, kwargs))
            return {"id": "ex_1"}

        def exception(self, *args, **kwargs):
            calls.append(("exception", args, kwargs))
            return {"id": args[0]}

        def exceptions_report(self, *args, **kwargs):
            calls.append(("exceptions", args, kwargs))
            return {"exceptions": []}

        def trust_summary(self, *args, **kwargs):
            calls.append(("trust_summary", args, kwargs))
            return {"schema": "campaign_factory.trust_summary.v1"}

        def resolve_exception(self, *args, **kwargs):
            calls.append(("resolve_exception", args, kwargs))
            return {"status": "resolved"}

        def snooze_exception(self, *args, **kwargs):
            calls.append(("snooze_exception", args, kwargs))
            return {"status": "snoozed"}

        def reopen_exception(self, *args, **kwargs):
            calls.append(("reopen_exception", args, kwargs))
            return {"status": "open"}

        def update_exception_status(self, *args, **kwargs):
            calls.append(("update_exception_status", args, kwargs))
            return {"status": args[1]}

        def exception_payload(self, *args, **kwargs):
            calls.append(("exception_payload", args, kwargs))
            return {"id": args[0]["id"]}

    factory.services = FakeServices()

    assert factory.create_exception(
        reason_code="missing_account_assignment",
        severity="high",
        campaign_id="camp_1",
        account_id="acct_1",
        entity_graph_id="graph_1",
        recommendation_item_id="rec_1",
        payload={"source": "test"},
        commit=False,
    ) == {"id": "ex_1"}
    assert factory.exception("ex_1") == {"id": "ex_1"}
    assert factory.exceptions("may", status="all") == {"exceptions": []}
    assert factory.trust_summary("may") == {"schema": "campaign_factory.trust_summary.v1"}
    assert factory.resolve_exception("ex_1", resolution="fixed", operator="op") == {"status": "resolved"}
    assert factory.snooze_exception("ex_1", until="2026-01-03T00:00:00+00:00", reason="wait", operator="op") == {"status": "snoozed"}
    assert factory.reopen_exception("ex_1", reason="ready", operator="op") == {"status": "open"}
    assert factory._update_exception_status(
        "ex_1",
        "resolved",
        resolution={"resolution": "fixed"},
        snoozed_until=None,
    ) == {"status": "resolved"}
    assert factory._exception_payload({"id": "ex_1"}) == {"id": "ex_1"}

    assert calls == [
        ("create_exception", (), {
            "reason_code": "missing_account_assignment",
            "severity": "high",
            "campaign_id": "camp_1",
            "account_id": "acct_1",
            "entity_graph_id": "graph_1",
            "recommendation_item_id": "rec_1",
            "payload": {"source": "test"},
            "commit": False,
        }),
        ("exception", ("ex_1",), {}),
        ("exceptions", ("may",), {"status": "all"}),
        ("trust_summary", ("may",), {}),
        ("resolve_exception", ("ex_1",), {"resolution": "fixed", "operator": "op"}),
        ("snooze_exception", ("ex_1",), {
            "until": "2026-01-03T00:00:00+00:00",
            "reason": "wait",
            "operator": "op",
        }),
        ("reopen_exception", ("ex_1",), {"reason": "ready", "operator": "op"}),
        ("update_exception_status", ("ex_1", "resolved"), {
            "resolution": {"resolution": "fixed"},
            "snoozed_until": None,
        }),
        ("exception_payload", ({"id": "ex_1"},), {}),
    ]


def test_core_services_delegates_exception_methods_to_exception_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeExceptions:
        def create_exception(self, *args, **kwargs):
            calls.append(("create_exception", args, kwargs))
            return {"id": "ex_1"}

        def exception(self, *args, **kwargs):
            calls.append(("exception", args, kwargs))
            return {"id": args[0]}

        def exceptions(self, *args, **kwargs):
            calls.append(("exceptions", args, kwargs))
            return {"exceptions": []}

        def trust_summary(self, *args, **kwargs):
            calls.append(("trust_summary", args, kwargs))
            return {"schema": "campaign_factory.trust_summary.v1"}

        def resolve_exception(self, *args, **kwargs):
            calls.append(("resolve_exception", args, kwargs))
            return {"status": "resolved"}

        def snooze_exception(self, *args, **kwargs):
            calls.append(("snooze_exception", args, kwargs))
            return {"status": "snoozed"}

        def reopen_exception(self, *args, **kwargs):
            calls.append(("reopen_exception", args, kwargs))
            return {"status": "open"}

        def update_exception_status(self, *args, **kwargs):
            calls.append(("update_exception_status", args, kwargs))
            return {"status": args[1]}

        def exception_payload(self, *args, **kwargs):
            calls.append(("exception_payload", args, kwargs))
            return {"id": args[0]["id"]}

    services.exceptions = FakeExceptions()

    assert services.create_exception(reason_code="missing_account_assignment", severity="high") == {"id": "ex_1"}
    assert services.exception("ex_1") == {"id": "ex_1"}
    assert services.exceptions_report("may", status="open") == {"exceptions": []}
    assert services.trust_summary("may") == {"schema": "campaign_factory.trust_summary.v1"}
    assert services.resolve_exception("ex_1", resolution="fixed", operator="op") == {"status": "resolved"}
    assert services.snooze_exception("ex_1", until="2026-01-03T00:00:00+00:00", reason="wait", operator="op") == {
        "status": "snoozed",
    }
    assert services.reopen_exception("ex_1", reason="ready", operator="op") == {"status": "open"}
    assert services.update_exception_status("ex_1", "resolved", resolution={"resolution": "fixed"}) == {
        "status": "resolved",
    }
    assert services.exception_payload({"id": "ex_1"}) == {"id": "ex_1"}

    assert calls == [
        ("create_exception", (), {
            "reason_code": "missing_account_assignment",
            "severity": "high",
            "campaign_id": None,
            "account_id": None,
            "entity_graph_id": None,
            "recommendation_item_id": None,
            "payload": None,
            "commit": True,
        }),
        ("exception", ("ex_1",), {}),
        ("exceptions", ("may",), {"status": "open"}),
        ("trust_summary", ("may",), {}),
        ("resolve_exception", ("ex_1",), {"resolution": "fixed", "operator": "op"}),
        ("snooze_exception", ("ex_1",), {
            "until": "2026-01-03T00:00:00+00:00",
            "reason": "wait",
            "operator": "op",
        }),
        ("reopen_exception", ("ex_1",), {"reason": "ready", "operator": "op"}),
        ("update_exception_status", ("ex_1", "resolved"), {
            "resolution": {"resolution": "fixed"},
            "snoozed_until": None,
        }),
        ("exception_payload", ({"id": "ex_1"},), {}),
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
