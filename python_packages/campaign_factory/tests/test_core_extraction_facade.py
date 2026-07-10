from __future__ import annotations

import ast
import inspect

from campaign_factory import audit_payload, exports
from campaign_factory.acceptance_suite import AcceptanceSuiteRepository
from campaign_factory.account_health import AccountHealthRepository
from campaign_factory.account_memory import AccountMemoryRepository
from campaign_factory.account_planning import AccountPlanningRepository
from campaign_factory.archive_quality import ArchiveQualityRepository
from campaign_factory.asset_import import AssetImportRepository
from campaign_factory.audio_operations import AudioOperationsRepository
from campaign_factory.audio_recommendations import AudioRecommendationRepository
from campaign_factory.autonomy import AutonomyPolicyRepository
from campaign_factory.campaign_overview import CampaignOverviewRepository
from campaign_factory.caption import CaptionFamilyRepository
from campaign_factory.carousel_integrity import CarouselIntegrityRepository
from campaign_factory.certification import CertificationRepository
from campaign_factory.config import Settings
from campaign_factory.contentforge_visual_qc import ContentForgeVisualQCRepository
from campaign_factory.core import CampaignFactory
from campaign_factory.core_complexity import CoreComplexityRepository
from campaign_factory.creative_knowledge import CreativeKnowledgeRepository
from campaign_factory.creative_planning import CreativePlanningRepository
from campaign_factory.creator_os_drafts import CreatorOSDraftRepository
from campaign_factory.creator_os_recommendations import (
    CreatorOSRecommendationRepository,
)
from campaign_factory.daily_plan import DailyPlanRepository
from campaign_factory.decision_ledger import DecisionLedgerRepository
from campaign_factory.discoverability import DiscoverabilityRepository
from campaign_factory.distribution import DistributionRepository
from campaign_factory.draft_inventory_gap import DraftInventoryGapRepository
from campaign_factory.events import EventRepository
from campaign_factory.exceptions import ExceptionRepository
from campaign_factory.execution_readiness import ExecutionReadinessRepository
from campaign_factory.export_summary import ExportSummaryRepository
from campaign_factory.finished_video import FinishedVideoRepository
from campaign_factory.fresh_reel_production import FreshReelProductionRepository
from campaign_factory.graph import GraphRepository
from campaign_factory.inventory_perceptual import InventoryPerceptualRepository
from campaign_factory.inventory_planning import InventoryPlanningRepository
from campaign_factory.inventory_recovery import InventoryRecoveryRepository
from campaign_factory.inventory_reservations import InventoryReservationRepository
from campaign_factory.lifecycle_reporting import LifecycleReportingRepository
from campaign_factory.live_acceptance import LiveAcceptanceRepository
from campaign_factory.live_scale import LiveScaleRepository
from campaign_factory.make_batch import MakeBatchRepository
from campaign_factory.models import ModelRepository
from campaign_factory.multi_blocker_unlock import MultiBlockerUnlockRepository
from campaign_factory.operational_proofs import OperationalProofRepository
from campaign_factory.operator_review import OperatorReviewRepository
from campaign_factory.parent_factory_reports import ParentFactoryReportRepository
from campaign_factory.performance_summary import PerformanceSummaryRepository
from campaign_factory.publishability import PublishabilityRepository
from campaign_factory.readiness_report import ReadinessReportRepository
from campaign_factory.recommendation_accuracy import RecommendationAccuracyRepository
from campaign_factory.recommendations import RecommendationRepository
from campaign_factory.recommended_inventory_request import (
    RecommendedInventoryRequestRepository,
)
from campaign_factory.reel_execution import ReelExecutionRepository
from campaign_factory.reel_factory_reports import ReelFactoryReportRepository
from campaign_factory.reference import ReferenceRepository
from campaign_factory.schedule_safe_production import ScheduleSafeProductionRepository
from campaign_factory.services import CoreServices
from campaign_factory.story_management import StoryManagementRepository
from campaign_factory.surface_handoff import SurfaceHandoffRepository
from campaign_factory.surface_inventory import SurfaceInventoryRepository
from campaign_factory.surface_registration import SurfaceRegistrationRepository
from campaign_factory.surface_requirements import SurfaceRequirementsRepository
from campaign_factory.surface_summary import SurfaceSummaryRepository
from campaign_factory.tribev2 import TribeV2Repository
from campaign_factory.variant_lineage import VariantLineageRepository
from campaign_factory.winner_expansion import WinnerExpansionRepository


def test_campaign_factory_core_stays_composition_root_facade() -> None:
    source = inspect.getsource(CampaignFactory)
    parsed = ast.parse(source)
    cls = parsed.body[0]
    allowed = {"__init__", "close", "_load_source_lineage"}
    simple_compat = {
        "_reel_caption_account_safety_violations": "discoverability_safe_content_contract"
    }
    non_facade: list[str] = []

    for method in [node for node in cls.body if isinstance(node, ast.FunctionDef)]:
        body = [
            stmt
            for stmt in method.body
            if not (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            )
        ]
        if method.name in allowed:
            continue
        if len(body) != 1:
            non_facade.append(method.name)
            continue
        stmt_source = ast.get_source_segment(source, body[0]) or ""
        compat_call = simple_compat.get(method.name)
        if "self.services." not in stmt_source and (
            not compat_call or compat_call not in stmt_source
        ):
            non_facade.append(method.name)

    assert non_facade == []


def test_campaign_factory_initializes_core_services(tmp_path) -> None:
    factory = CampaignFactory(
        Settings(
            root=tmp_path,
            db_path=tmp_path / "campaign_factory.sqlite",
            reel_factory_root=tmp_path / "reel_factory",
            contentforge_root=tmp_path / "contentforge",
            threadsdash_root=tmp_path / "ThreadsDashboard",
            campaigns_dir=tmp_path / "campaigns",
        )
    )
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
        assert isinstance(factory.services.export_summary, ExportSummaryRepository)
        assert isinstance(
            factory.services.creative_planning, CreativePlanningRepository
        )
        assert factory.services.creative_planning.conn is factory.conn
        assert isinstance(factory.services.reference, ReferenceRepository)
        assert factory.services.reference.conn is factory.conn
        assert isinstance(factory.services.reel_execution, ReelExecutionRepository)
        assert factory.services.reel_execution.conn is factory.conn
        assert isinstance(factory.services.variant_lineage, VariantLineageRepository)
        assert factory.services.variant_lineage.conn is factory.conn
        assert isinstance(factory.services.publishability, PublishabilityRepository)
        assert factory.services.publishability.conn is factory.conn
        assert isinstance(factory.services.caption_family, CaptionFamilyRepository)
        assert factory.services.caption_family.conn is factory.conn
        assert isinstance(factory.services.distribution, DistributionRepository)
        assert factory.services.distribution.conn is factory.conn
        assert isinstance(factory.services.decision_ledger, DecisionLedgerRepository)
        assert factory.services.decision_ledger.conn is factory.conn
        assert isinstance(factory.services.exceptions, ExceptionRepository)
        assert factory.services.exceptions.conn is factory.conn
        assert isinstance(factory.services.finished_video, FinishedVideoRepository)
        assert factory.services.finished_video.conn is factory.conn
        assert isinstance(factory.services.discoverability, DiscoverabilityRepository)
        assert factory.services.discoverability.conn is factory.conn
        assert isinstance(
            factory.services.surface_registration, SurfaceRegistrationRepository
        )
        assert factory.services.surface_registration.conn is factory.conn
        assert isinstance(
            factory.services.carousel_integrity, CarouselIntegrityRepository
        )
        assert factory.services.carousel_integrity.conn is factory.conn
        assert isinstance(factory.services.winner_expansion, WinnerExpansionRepository)
        assert factory.services.winner_expansion.conn is factory.conn
        assert isinstance(
            factory.services.creator_os_recommendations,
            CreatorOSRecommendationRepository,
        )
        assert isinstance(
            factory.services.recommended_inventory_request,
            RecommendedInventoryRequestRepository,
        )
        assert isinstance(
            factory.services.creative_knowledge, CreativeKnowledgeRepository
        )
        assert factory.services.creative_knowledge.conn is factory.conn
        assert isinstance(factory.services.tribev2, TribeV2Repository)
        assert factory.services.tribev2.conn is factory.conn
        assert isinstance(factory.services.operator_review, OperatorReviewRepository)
        assert factory.services.operator_review.conn is factory.conn
        assert isinstance(factory.services.story_management, StoryManagementRepository)
        assert factory.services.story_management.conn is factory.conn
        assert isinstance(factory.services.surface_handoff, SurfaceHandoffRepository)
        assert factory.services.surface_handoff.conn is factory.conn
        assert isinstance(
            factory.services.surface_inventory, SurfaceInventoryRepository
        )
        assert factory.services.surface_inventory.conn is factory.conn
        assert isinstance(
            factory.services.surface_requirements, SurfaceRequirementsRepository
        )
        assert factory.services.surface_requirements.conn is factory.conn
        assert isinstance(factory.services.surface_summary, SurfaceSummaryRepository)
        assert factory.services.surface_summary.conn is factory.conn
        assert isinstance(factory.services.creator_os_drafts, CreatorOSDraftRepository)
        assert isinstance(
            factory.services.draft_inventory_gap, DraftInventoryGapRepository
        )
        assert factory.services.draft_inventory_gap.conn is factory.conn
        assert isinstance(factory.services.daily_plan, DailyPlanRepository)
        assert factory.services.daily_plan.conn is factory.conn
        assert isinstance(
            factory.services.execution_readiness, ExecutionReadinessRepository
        )
        assert factory.services.execution_readiness.conn is factory.conn
        assert isinstance(factory.services.acceptance_suite, AcceptanceSuiteRepository)
        assert factory.services.acceptance_suite.conn is factory.conn
        assert isinstance(factory.services.readiness_report, ReadinessReportRepository)
        assert factory.services.readiness_report.conn is factory.conn
        assert isinstance(factory.services.live_scale, LiveScaleRepository)
        assert factory.services.live_scale.conn is factory.conn
        assert isinstance(factory.services.live_acceptance, LiveAcceptanceRepository)
        assert factory.services.live_acceptance.conn is factory.conn
        assert isinstance(
            factory.services.lifecycle_reporting, LifecycleReportingRepository
        )
        assert factory.services.lifecycle_reporting.conn is factory.conn
        assert isinstance(factory.services.make_batch_repo, MakeBatchRepository)
        assert factory.services.make_batch_repo.conn is factory.conn
        assert isinstance(factory.services.certification, CertificationRepository)
        assert factory.services.certification.conn is factory.conn
        assert isinstance(
            factory.services.operational_proofs, OperationalProofRepository
        )
        assert factory.services.operational_proofs.conn is factory.conn
        assert isinstance(factory.services.core_complexity, CoreComplexityRepository)
        assert factory.services.core_complexity.conn is factory.conn
        assert isinstance(factory.services.account_health, AccountHealthRepository)
        assert factory.services.account_health.conn is factory.conn
        assert isinstance(factory.services.autonomy, AutonomyPolicyRepository)
        assert factory.services.autonomy.conn is factory.conn
        assert isinstance(factory.services.account_memory, AccountMemoryRepository)
        assert factory.services.account_memory.conn is factory.conn
        assert isinstance(factory.services.account_planning, AccountPlanningRepository)
        assert factory.services.account_planning.conn is factory.conn
        assert isinstance(
            factory.services.recommendation_accuracy_repo,
            RecommendationAccuracyRepository,
        )
        assert factory.services.recommendation_accuracy_repo.conn is factory.conn
        assert isinstance(factory.services.recommendations, RecommendationRepository)
        assert factory.services.recommendations.conn is factory.conn
        assert isinstance(factory.services.archive_quality, ArchiveQualityRepository)
        assert factory.services.archive_quality.conn is factory.conn
        assert isinstance(
            factory.services.inventory_planning, InventoryPlanningRepository
        )
        assert factory.services.inventory_planning.conn is factory.conn
        assert isinstance(
            factory.services.inventory_recovery, InventoryRecoveryRepository
        )
        assert factory.services.inventory_recovery.conn is factory.conn
        assert isinstance(
            factory.services.schedule_safe_production, ScheduleSafeProductionRepository
        )
        assert factory.services.schedule_safe_production.conn is factory.conn
        assert isinstance(
            factory.services.fresh_reel_production, FreshReelProductionRepository
        )
        assert factory.services.fresh_reel_production.conn is factory.conn
        assert isinstance(
            factory.services.reel_factory_reports, ReelFactoryReportRepository
        )
        assert factory.services.reel_factory_reports.conn is factory.conn
        assert isinstance(
            factory.services.parent_factory_reports, ParentFactoryReportRepository
        )
        assert factory.services.parent_factory_reports.conn is factory.conn
        assert isinstance(
            factory.services.contentforge_visual_qc, ContentForgeVisualQCRepository
        )
        assert factory.services.contentforge_visual_qc.conn is factory.conn
        assert isinstance(
            factory.services.multi_blocker_unlock, MultiBlockerUnlockRepository
        )
        assert factory.services.multi_blocker_unlock.conn is factory.conn
        assert isinstance(
            factory.services.performance_summary_repo, PerformanceSummaryRepository
        )
        assert factory.services.performance_summary_repo.conn is factory.conn
        assert isinstance(
            factory.services.audio_recommendations, AudioRecommendationRepository
        )
        assert factory.services.audio_recommendations.conn is factory.conn
        assert isinstance(factory.services.audio_operations, AudioOperationsRepository)
        assert factory.services.audio_operations.conn is factory.conn
        assert isinstance(
            factory.services.inventory_perceptual, InventoryPerceptualRepository
        )
        assert factory.services.inventory_perceptual.conn is factory.conn
        assert isinstance(
            factory.services.inventory_reservations, InventoryReservationRepository
        )
        assert factory.services.inventory_reservations.conn is factory.conn
        assert isinstance(
            factory.services.campaign_overview, CampaignOverviewRepository
        )
        assert factory.services.campaign_overview.conn is factory.conn
        assert (
            factory.services.variant_lineage._performance_snapshot_payload.__self__
            is factory.services
        )
        assert (
            factory.services.variant_lineage._aggregate_performance.__self__
            is factory.services
        )
        assert (
            factory.services.account_memory._performance_snapshot_payload.__self__
            is factory.services
        )
        assert (
            factory.services.account_memory._account_reward_baselines.__self__
            is factory.services
        )
        assert (
            factory.services.account_memory._aggregate_performance.__self__
            is factory.services
        )
        assert (
            factory.services.account_memory._performance_quality_score.__self__
            is factory.services
        )
        assert (
            factory.services.campaign_overview._performance_for_asset.__self__
            is factory.services
        )
        assert (
            factory.services.account_planning._performance_for_asset.__self__
            is factory.services
        )
        assert (
            factory.services.account_planning._performance_quality_score.__self__
            is factory.services
        )
        assert (
            factory.services.recommendations.performance_summary.__self__
            is factory.services
        )
        assert (
            factory.services.recommendations._performance_snapshot_payload.__self__
            is factory.services
        )
        assert (
            factory.services.recommendations._account_reward_baselines.__self__
            is factory.services
        )
        assert (
            factory.services.recommendations._aggregate_performance.__self__
            is factory.services
        )
        assert (
            factory.services.recommendations._performance_quality_score.__self__
            is factory.services
        )
        assert (
            factory.services.recommendations._performance_planning_score.__self__
            is factory.services
        )
        assert (
            factory.services.audio_operations._performance_snapshot_payload.__self__
            is factory.services
        )
        assert (
            factory.services.lifecycle_reporting._performance_snapshot_payload.__self__
            is factory.services
        )
    finally:
        factory.close()


def test_core_services_constructor_owns_performance_helper_seams() -> None:
    params = inspect.signature(CoreServices).parameters
    for name in [
        "performance_summary",
        "performance_snapshot_payload",
        "account_reward_baselines",
        "aggregate_performance",
        "performance_quality_score",
        "performance_planning_score",
        "performance_for_asset",
    ]:
        assert name not in params


def test_core_services_strict_graph_edge_records_exception_for_missing_endpoint() -> (
    None
):
    services = object.__new__(CoreServices)
    calls = []

    class FakeGraph:
        def ensure_graph_edge(self, *args, **kwargs):
            calls.append(("ensure_graph_edge", args, kwargs))
            return "edge_1"

    class FakeExceptions:
        def create_exception(self, *args, **kwargs):
            calls.append(("create_exception", args, kwargs))
            return {"id": "ex_1"}

    services.graph = FakeGraph()
    services.exceptions = FakeExceptions()
    services._slugify = lambda value: str(value).strip().lower().replace(" ", "_")
    services._sanitize_for_storage = lambda value: (
        {"token": "<redacted>"} if value == {"token": "secret"} else value
    )

    assert (
        services.ensure_graph_edge_strict(
            None,
            "to",
            "needs review",
            evidence={"token": "secret"},
            campaign_id="camp_1",
            account_id="acct_1",
            recommendation_item_id="rec_1",
            source_operation="Recommendation Sync",
            commit=True,
        )
        is None
    )

    assert calls == [
        (
            "create_exception",
            (),
            {
                "reason_code": "graph_edge_missing_endpoint:recommendation_sync:needs_review:from_global_id",
                "severity": "high",
                "campaign_id": "camp_1",
                "account_id": "acct_1",
                "entity_graph_id": "to",
                "recommendation_item_id": "rec_1",
                "payload": {
                    "relationType": "needs review",
                    "sourceOperation": "Recommendation Sync",
                    "missing": ["from_global_id"],
                    "fromGlobalId": None,
                    "toGlobalId": "to",
                    "evidence": {"token": "<redacted>"},
                },
                "commit": True,
            },
        ),
    ]


def test_campaign_factory_operational_helpers_delegate_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    lineage = {"schema": "lineage.v1"}
    calls = []

    class FakeServices:
        def validate_instagram_trial_reel_intent(self, *args, **kwargs):
            calls.append(("validate_instagram_trial_reel_intent", args, kwargs))
            return "MANUAL"

        def record_lineage_costs(self, *args, **kwargs):
            calls.append(("record_lineage_costs", args, kwargs))

    factory.services = FakeServices()

    assert (
        factory._validate_instagram_trial_reel_intent(
            content_surface="reel",
            distribution_surface="trial_reel",
            media_type="video",
            instagram_trial_reels=True,
            trial_graduation_strategy="manual",
        )
        == "MANUAL"
    )
    assert factory._record_lineage_costs(lineage) is None

    assert calls == [
        (
            "validate_instagram_trial_reel_intent",
            (),
            {
                "content_surface": "reel",
                "distribution_surface": "trial_reel",
                "media_type": "video",
                "instagram_trial_reels": True,
                "trial_graduation_strategy": "manual",
            },
        ),
        ("record_lineage_costs", (lineage,), {}),
    ]


def test_export_summary_repository_preserves_export_module_seam(monkeypatch) -> None:
    factory = object()
    repository = ExportSummaryRepository(factory)
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

    assert (
        repository.batch_summary("campaign")["schema"]
        == "campaign_factory.batch_summary.v1"
    )
    assert (
        repository.daily_production_counters("campaign", dashboard={"rendered": []})[
            "schema"
        ]
        == "campaign_factory.daily_production_counters.v1"
    )
    assert repository.variant_pack_groups([{"id": "asset_1"}]) == [
        {"sourceAssetId": "asset_1"}
    ]
    assert (
        repository.export_manifest(campaign_slug="campaign")["schema"]
        == "campaign_factory.export.v1"
    )
    assert calls == [
        ("batch", factory, "campaign"),
        ("daily", factory, "campaign", {"rendered": []}),
        ("groups", factory, [{"id": "asset_1"}]),
        ("manifest", factory, "campaign"),
    ]


def test_core_services_core_utility_methods_preserve_behavior(tmp_path) -> None:
    services = object.__new__(CoreServices)
    services.settings = type(
        "SettingsStub", (), {"campaigns_dir": tmp_path / "campaigns"}
    )()
    execute_calls = []

    class FakeCursor:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeConn:
        def execute(self, query, params=()):
            execute_calls.append((query, params))
            if "FROM campaigns" in query:
                return FakeCursor([{"slug": "may"}])
            if "FROM rendered_assets" in query:
                return FakeCursor([{"id": "rendered_1"}])
            raise AssertionError(query)

    services.conn = FakeConn()

    dirs = services.campaign_dirs("model-a", "may")
    assert list(dirs) == [
        "root",
        "sources",
        "reel_inputs",
        "rendered",
        "audits",
        "approved",
        "exports",
    ]
    assert dirs["sources"] == tmp_path / "campaigns" / "model-a" / "may" / "00_sources"
    assert all(path.exists() for path in dirs.values())
    assert services.list_campaigns() == [{"slug": "may"}]
    assert services.rendered_for_campaign("camp_1") == [{"id": "rendered_1"}]
    assert execute_calls == [
        ("SELECT * FROM campaigns ORDER BY updated_at DESC", ()),
        (
            "SELECT * FROM rendered_assets WHERE campaign_id = ? ORDER BY created_at DESC",
            ("camp_1",),
        ),
    ]

    assert services.ratio(1, 2) == 0.5
    assert services.ratio(1, 0) == 0
    assert services.score_fraction(2, 4) == 5.0
    assert services.score_fraction(8, 4) == 10.0
    assert services.score_fraction(1, 0) == 0.0
    assert services.road_to_accounts_payload(
        accounts=25,
        production={
            "postsPerDay": 8,
            "requiredValidatedDraftsPerDay": 10,
            "requiredParentsPerDay": 3,
            "requiredCaptionFamiliesPerDay": 2,
            "requiredVariantsPerDay": 6,
        },
    ) == {
        "schema": "creator_os.road_to_25_accounts.v1",
        "accounts": 25,
        "requiredInventoryBuffer": "24 schedule-safe drafts",
        "requiredDailyProduction": "8 schedule-safe drafts/day",
        "requiredValidatedDrafts": "10 validated drafts/day",
        "requiredParentAssetsPerDay": 3,
        "requiredCaptionFamiliesPerDay": 2,
        "requiredVariantsPerDay": 6,
        "requiredExceptionRate": "<=2.0% inventory-blocking exceptions",
        "requiredOperatorLoad": "<=25 inventory exceptions/day per operator queue",
        "wouldWrite": False,
    }
    assert services.wilson_lower_bound(successes=0, trials=0) == 0.0
    assert round(services.wilson_lower_bound(successes=4, trials=10, z=1.0), 3) == 0.261
    assert services.creator_label("") == "unknown"
    assert services.creator_label("stacey") == "Stacey"
    assert services.truthy(True) is True
    assert services.truthy(None) is False
    assert services.truthy("on") is True
    assert services.truthy("off") is False
    assert (
        services.surface_from_pattern(
            {"dimension": "contentSurface", "key": "feed_single"}, {}
        )
        == "feed_single"
    )
    assert (
        services.surface_from_pattern(
            {"dimension": "captionAngle"}, {"contentSurfaces": ["story"]}
        )
        == "story"
    )
    assert services.surface_from_pattern({"dimension": "storyIntent"}, {}) == "story"
    assert services.surface_from_pattern({"dimension": "captionAngle"}, {}) == "reel"
    assert (
        services.first_lineage_value(
            {"angles": ["mirror"]}, "angles", fallback="fallback"
        )
        == "mirror"
    )
    assert (
        services.first_lineage_value({"angles": []}, "angles", fallback="fallback")
        == "fallback"
    )


def test_core_services_audit_report_delegates_to_audit_payload_module(
    monkeypatch,
) -> None:
    services = object.__new__(CoreServices)
    factory = object.__new__(CampaignFactory)
    services.factory_context = factory
    calls = []

    def fake_audit_report(self, audit_report_id):
        calls.append(("audit", self, audit_report_id))
        return {"id": audit_report_id}

    def fake_payload(self, row):
        calls.append(("payload", self, row))
        return {"id": row["id"]}

    monkeypatch.setattr(audit_payload, "audit_report", fake_audit_report)
    monkeypatch.setattr(audit_payload, "_audit_report_payload", fake_payload)

    assert services.audit_report("audit_1") == {"id": "audit_1"}
    assert services.audit_report_payload({"id": "audit_2"}) == {"id": "audit_2"}
    assert calls == [
        ("audit", factory, "audit_1"),
        ("payload", factory, {"id": "audit_2"}),
    ]
