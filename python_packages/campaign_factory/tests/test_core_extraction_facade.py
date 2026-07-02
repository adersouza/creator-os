from __future__ import annotations

import ast
import inspect
from pathlib import Path

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


def test_archive_quality_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def archive_inventory_report(self, *args, **kwargs):
            calls.append(("archive_inventory_report", args, kwargs))
            return {"schema": "campaign_factory.archive_inventory_report.v1"}

        def archive_existing_content_duplicate(self, *args, **kwargs):
            calls.append(("archive_existing_content_duplicate", args, kwargs))
            return {"table": "source_assets", "id": args[0]}

        def archive_recent_publish_duplicate(self, *args, **kwargs):
            calls.append(("archive_recent_publish_duplicate", args, kwargs))
            return {"table": "performance_snapshots", "id": args[0]}

        def archive_candidate_quality_report(self, *args, **kwargs):
            calls.append(("archive_candidate_quality_report", args, kwargs))
            return {"schema": "campaign_factory.archive_candidate_quality_report.v1"}

        def archive_crop_severity(self, *args, **kwargs):
            calls.append(("archive_crop_severity", args, kwargs))
            return ("low", 0, 0.0)

        def archive_visual_quality_score(self, *args, **kwargs):
            calls.append(("archive_visual_quality_score", args, kwargs))
            return 98

        def archive_duplicate_confidence(self, *args, **kwargs):
            calls.append(("archive_duplicate_confidence", args, kwargs))
            return "clear"

    factory.services = FakeServices()
    recent_cutoff = object()
    assert (
        factory.archive_inventory_report(
            folder=Path("/tmp/archive"),
            campaign_slug="stacey_archive_marketing_20260606",
            creator="Stacey",
            requested_count=2,
            model_slug="stacey",
            recent_days=14,
        )["schema"]
        == "campaign_factory.archive_inventory_report.v1"
    )
    assert factory._archive_existing_content_duplicate("hash_1") == {
        "table": "source_assets",
        "id": "hash_1",
    }
    assert factory._archive_recent_publish_duplicate("hash_1", recent_cutoff) == {
        "table": "performance_snapshots",
        "id": "hash_1",
    }
    assert (
        factory.archive_candidate_quality_report(
            inventory_report_path=Path("/tmp/archive_inventory.json"),
            requested_count=2,
            exclude_indices=[3],
        )["schema"]
        == "campaign_factory.archive_candidate_quality_report.v1"
    )
    assert factory._archive_crop_severity({"effectiveAspectRatio": 9 / 16}) == (
        "low",
        0,
        0.0,
    )
    assert factory._archive_visual_quality_score({"height": 1920}, [], 0) == 98
    assert factory._archive_duplicate_confidence({"duplicate": {}}) == "clear"

    assert calls == [
        (
            "archive_inventory_report",
            (),
            {
                "folder": Path("/tmp/archive"),
                "campaign_slug": "stacey_archive_marketing_20260606",
                "creator": "Stacey",
                "requested_count": 2,
                "model_slug": "stacey",
                "recent_days": 14,
            },
        ),
        ("archive_existing_content_duplicate", ("hash_1",), {}),
        ("archive_recent_publish_duplicate", ("hash_1", recent_cutoff), {}),
        (
            "archive_candidate_quality_report",
            (),
            {
                "inventory_report_path": Path("/tmp/archive_inventory.json"),
                "requested_count": 2,
                "exclude_indices": [3],
            },
        ),
        ("archive_crop_severity", ({"effectiveAspectRatio": 9 / 16},), {}),
        ("archive_visual_quality_score", ({"height": 1920}, [], 0), {}),
        ("archive_duplicate_confidence", ({"duplicate": {}},), {}),
    ]


def test_campaign_factory_delegates_campaign_overview_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def dashboard(self, *args, **kwargs):
            calls.append(("dashboard", args, kwargs))
            return {"campaign": {"slug": args[0]}, "rendered": []}

        def default_dashboard_campaign(self, *args, **kwargs):
            calls.append(("default_dashboard_campaign", args, kwargs))
            return args[0][0] if args[0] else None

        def campaign_health(self, *args, **kwargs):
            calls.append(("campaign_health", args, kwargs))
            return {
                "schema": "campaign_factory.campaign_health.v1",
                "campaign": args[0],
            }

        def asset_detail(self, *args, **kwargs):
            calls.append(("asset_detail", args, kwargs))
            return {
                "schema": "campaign_factory.asset_detail.v1",
                "asset": {"id": args[0]},
            }

        def assign_asset_account(self, *args, **kwargs):
            calls.append(("assign_asset_account", args, kwargs))
            return {
                "rendered_asset_id": args[0],
                "instagram_account_id": kwargs["instagram_account_id"],
            }

        def assignments_for_asset(self, *args, **kwargs):
            calls.append(("assignments_for_asset", args, kwargs))
            return [{"rendered_asset_id": args[0]}]

        def assignments_for_campaign(self, *args, **kwargs):
            calls.append(("assignments_for_campaign", args, kwargs))
            return [{"campaign": args[0]}]

    factory.services = FakeServices()

    assert factory.dashboard("may") == {"campaign": {"slug": "may"}, "rendered": []}
    assert factory._default_dashboard_campaign([{"id": "camp_1", "slug": "may"}]) == {
        "id": "camp_1",
        "slug": "may",
    }
    assert factory.campaign_health("may") == {
        "schema": "campaign_factory.campaign_health.v1",
        "campaign": "may",
    }
    assert factory.asset_detail("asset_1") == {
        "schema": "campaign_factory.asset_detail.v1",
        "asset": {"id": "asset_1"},
    }
    assert factory.assign_asset_account(
        "asset_1",
        account_id="acct_1",
        instagram_account_id="ig_1",
        planned_window_start="2026-05-15T10:00:00-04:00",
        planned_window_end="2026-05-15T12:00:00-04:00",
        notes="morning test",
    ) == {"rendered_asset_id": "asset_1", "instagram_account_id": "ig_1"}
    assert factory.assignments_for_asset("asset_1") == [
        {"rendered_asset_id": "asset_1"}
    ]
    assert factory.assignments_for_campaign("may") == [{"campaign": "may"}]

    assert calls == [
        ("dashboard", ("may",), {}),
        ("default_dashboard_campaign", ([{"id": "camp_1", "slug": "may"}],), {}),
        ("campaign_health", ("may",), {}),
        ("asset_detail", ("asset_1",), {}),
        (
            "assign_asset_account",
            ("asset_1",),
            {
                "account_id": "acct_1",
                "instagram_account_id": "ig_1",
                "planned_window_start": "2026-05-15T10:00:00-04:00",
                "planned_window_end": "2026-05-15T12:00:00-04:00",
                "notes": "morning test",
            },
        ),
        ("assignments_for_asset", ("asset_1",), {}),
        ("assignments_for_campaign", ("may",), {}),
    ]


def test_campaign_factory_delegates_account_planning_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def account_plan(self, *args, **kwargs):
            calls.append(("account_plan", args, kwargs))
            return {"schema": "campaign_factory.account_plan.v1"}

        def ranking(self, *args, **kwargs):
            calls.append(("ranking", args, kwargs))
            return {"schema": "campaign_factory.ranking.v1"}

        def quality_score_for_ranking(self, *args, **kwargs):
            calls.append(("quality_score_for_ranking", args, kwargs))
            return 91

        def history_score(self, *args, **kwargs):
            calls.append(("history_score", args, kwargs))
            return 72

        def account_fit_score(self, *args, **kwargs):
            calls.append(("account_fit_score", args, kwargs))
            return 58

        def novelty_score(self, *args, **kwargs):
            calls.append(("novelty_score", args, kwargs))
            return 90

        def dashboard_rendered_asset(self, *args, **kwargs):
            calls.append(("dashboard_rendered_asset", args, kwargs))
            return {"id": args[0]["id"], "enriched": True}

        def generated_asset_lineage(self, *args, **kwargs):
            calls.append(("generated_asset_lineage", args, kwargs))
            return {"schema": "reel_factory.generated_asset_lineage.v1"}

        def audio_recommendations_for_asset(self, *args, **kwargs):
            calls.append(("audio_recommendations_for_asset", args, kwargs))
            return {"schema": "campaign_factory.audio_recommendations.v1"}

    factory.services = FakeServices()
    asset = {"id": "asset_1"}
    source_prompt = {"promptId": "prompt_1"}
    reference_pattern = {"id": "ref_1"}

    assert factory.account_plan("may", user_id="user_1", usage={"assets": []}) == {
        "schema": "campaign_factory.account_plan.v1",
    }
    assert factory.ranking("may") == {"schema": "campaign_factory.ranking.v1"}
    assert factory._quality_score_for_ranking(asset) == 91
    assert factory._history_score({"count": 1}) == 72
    assert factory._account_fit_score(asset) == 58
    assert factory._novelty_score(asset) == 90
    assert factory._dashboard_rendered_asset(asset) == {
        "id": "asset_1",
        "enriched": True,
    }
    assert factory._generated_asset_lineage(source_prompt, reference_pattern) == {
        "schema": "reel_factory.generated_asset_lineage.v1",
    }
    assert factory._audio_recommendations_for_asset(
        caption_generation={},
        reference_pattern=reference_pattern,
        recipe="v01_original",
        account_tags=["stacey"],
    ) == {"schema": "campaign_factory.audio_recommendations.v1"}

    assert calls == [
        ("account_plan", ("may",), {"user_id": "user_1", "usage": {"assets": []}}),
        ("ranking", ("may",), {}),
        ("quality_score_for_ranking", (asset,), {}),
        ("history_score", ({"count": 1},), {}),
        ("account_fit_score", (asset,), {}),
        ("novelty_score", (asset,), {}),
        ("dashboard_rendered_asset", (asset,), {}),
        ("generated_asset_lineage", (source_prompt, reference_pattern), {}),
        (
            "audio_recommendations_for_asset",
            (),
            {
                "caption_generation": {},
                "reference_pattern": reference_pattern,
                "recipe": "v01_original",
                "account_tags": ["stacey"],
            },
        ),
    ]


def test_campaign_factory_delegates_jobs_for_campaign_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def jobs_for_campaign(self, *args, **kwargs):
            calls.append(("jobs_for_campaign", args, kwargs))
            return [{"id": "job_1"}]

    factory.services = FakeServices()

    assert factory.jobs_for_campaign("may", limit=5) == [{"id": "job_1"}]
    assert calls == [
        (
            "jobs_for_campaign",
            ("may",),
            {"limit": 5, "statuses": None, "stuck_hours": None},
        )
    ]


def test_campaign_factory_delegates_surface_summary_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def creator_surface_summary(self, *args, **kwargs):
            calls.append(("creator_surface_summary", args, kwargs))
            return {"schema": "creator_os.creator_surface_summary.v1"}

        def account_surface_summary(self, *args, **kwargs):
            calls.append(("account_surface_summary", args, kwargs))
            return {"schema": "creator_os.account_surface_summary.v1"}

        def creator_surface_gap_report(self, *args, **kwargs):
            calls.append(("creator_surface_gap_report", args, kwargs))
            return {"schema": "creator_os.creator_surface_gap_report.v1"}

    factory.services = FakeServices()

    assert factory.creator_surface_summary(creator="Stacey", date="2026-06-06") == {
        "schema": "creator_os.creator_surface_summary.v1",
    }
    assert factory.account_surface_summary(
        creator="Stacey", account_id="ig_1", generated_at="2026-06-06T12:00:00Z"
    ) == {
        "schema": "creator_os.account_surface_summary.v1",
    }
    assert factory.creator_surface_gap_report(creator="Stacey", date="2026-06-06") == {
        "schema": "creator_os.creator_surface_gap_report.v1",
    }
    assert calls == [
        (
            "creator_surface_summary",
            (),
            {"creator": "Stacey", "date": "2026-06-06", "generated_at": None},
        ),
        (
            "account_surface_summary",
            (),
            {
                "creator": "Stacey",
                "date": None,
                "account_id": "ig_1",
                "generated_at": "2026-06-06T12:00:00Z",
            },
        ),
        (
            "creator_surface_gap_report",
            (),
            {"creator": "Stacey", "date": "2026-06-06", "generated_at": None},
        ),
    ]


def test_campaign_factory_delegates_surface_inventory_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def multi_surface_inventory_audit(self, *args, **kwargs):
            calls.append(("multi_surface_inventory_audit", args, kwargs))
            return {"schema": "campaign_factory.multi_surface_inventory_audit.v1"}

        def build_surface_inventory(self, *args, **kwargs):
            calls.append(("build_surface_inventory", args, kwargs))
            return {"schema": "campaign_factory.surface_inventory.v1"}

    factory.services = FakeServices()

    assert factory.multi_surface_inventory_audit(
        creator="Stacey", campaign_slug="summer"
    ) == {
        "schema": "campaign_factory.multi_surface_inventory_audit.v1",
    }
    assert factory._build_surface_inventory(
        creator="Stacey", campaign_slug="summer"
    ) == {
        "schema": "campaign_factory.surface_inventory.v1",
    }
    assert calls == [
        (
            "multi_surface_inventory_audit",
            (),
            {"creator": "Stacey", "campaign_slug": "summer"},
        ),
        (
            "build_surface_inventory",
            (),
            {"creator": "Stacey", "campaign_slug": "summer"},
        ),
    ]


def test_campaign_factory_delegates_inventory_planning_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    factory.services = FakeServices()

    public_calls = [
        ("inventory_slo_report", {"accounts": 2}),
        ("inventory_buffer_report", {"accounts": 2}),
        ("inventory_factory_audit", {"creator": "Stacey"}),
        ("inventory_yield_analysis", {"campaign_slug": "summer"}),
        (
            "inventory_buffer_policy_plan",
            {"creator": "Stacey", "surface": "reel", "daily_demand": 4},
        ),
        ("inventory_slo_enforcement_audit", {"creators": ["Stacey"], "accounts": 2}),
        (
            "inventory_consumption_simulation",
            {"available_inventory": 8, "account_tiers": [1, 2]},
        ),
        ("inventory_production_requirements", {"accounts": 2}),
        ("road_to_200_accounts", {}),
        (
            "inventory_exception_audit",
            {"execution_readiness": {"blockers": ["missing_audio"]}},
        ),
        (
            "inventory_factory_readiness_report",
            {"accounts": 2, "available_inventory": 8},
        ),
        ("inventory_factory_master_report", {"accounts": 2, "available_inventory": 8}),
        ("inventory_autopilot_plan", {"accounts": 2, "available_inventory": 1}),
        ("inventory_shortage_repair_plan", {"accounts": 2, "available_inventory": 1}),
        (
            "inventory_buffer_protection_report",
            {"accounts": 2, "available_inventory": 1},
        ),
    ]
    for method, kwargs in public_calls:
        assert getattr(factory, method)(**kwargs) == {"method": method}

    assert factory._inventory_slo_surface_targets(8) == {
        "method": "inventory_slo_surface_targets"
    }
    assert factory._inventory_health(current=1, minimum=2) == {
        "method": "inventory_health"
    }
    assert factory._inventory_stage_counts(creator="Stacey") == {
        "method": "inventory_stage_counts"
    }
    assert factory._inventory_count_related(
        "caption_families", "parent_asset_id", {"asset_1"}
    ) == {
        "method": "inventory_count_related",
    }
    assert factory._inventory_limiting_stage({"scheduleSafeAssets": 0}) == {
        "method": "inventory_limiting_stage"
    }
    assert factory._inventory_loss_by_stage({"parentAssets": 1}) == {
        "method": "inventory_loss_by_stage"
    }
    assert factory._inventory_repair_actions({"shortfall": 1}) == {
        "method": "inventory_repair_actions"
    }

    assert calls == [
        (
            "inventory_slo_report",
            (),
            {
                "accounts": 2,
                "posts_per_account_per_day": 3,
                "creators": 3,
                "minimum_inventory_days": 3,
                "current_validated_drafts": 0,
                "current_drafts_by_surface": None,
            },
        ),
        ("inventory_buffer_report", (), {"accounts": 2}),
        (
            "inventory_factory_audit",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": None,
                "accounts": 200,
                "posts_per_account_per_day": 3,
            },
        ),
        ("inventory_yield_analysis", (), {"creator": None, "campaign_slug": "summer"}),
        (
            "inventory_buffer_policy_plan",
            (),
            {
                "creator": "Stacey",
                "surface": "reel",
                "daily_demand": 4,
                "buffer_target_days": 3,
                "available_inventory": None,
            },
        ),
        (
            "inventory_slo_enforcement_audit",
            (),
            {
                "creators": ["Stacey"],
                "accounts": 2,
                "posts_per_account_per_day": 3,
                "minimum_inventory_days": 3,
                "available_by_creator_surface": None,
            },
        ),
        (
            "inventory_consumption_simulation",
            (),
            {
                "available_inventory": 8,
                "account_tiers": [1, 2],
                "posts_per_account_per_day": 3,
            },
        ),
        (
            "inventory_production_requirements",
            (),
            {
                "accounts": 2,
                "posts_per_account_per_day": 3,
                "variants_per_parent": 15,
                "variant_to_validated_yield": 0.85,
                "validated_to_schedule_safe_yield": 0.90,
            },
        ),
        ("road_to_200_accounts", (), {}),
        (
            "inventory_exception_audit",
            (),
            {
                "execution_readiness": {"blockers": ["missing_audio"]},
                "surface_readiness_report": None,
                "publishability_report": None,
            },
        ),
        (
            "inventory_factory_readiness_report",
            (),
            {
                "accounts": 2,
                "posts_per_account_per_day": 3,
                "available_inventory": 8,
                "execution_readiness": None,
            },
        ),
        (
            "inventory_factory_master_report",
            (),
            {
                "accounts": 2,
                "posts_per_account_per_day": 3,
                "available_inventory": 8,
                "execution_readiness": None,
            },
        ),
        (
            "inventory_autopilot_plan",
            (),
            {
                "accounts": 2,
                "posts_per_account_per_day": 3,
                "available_inventory": 1,
                "buffer_target_days": 3,
                "surface": "reel",
            },
        ),
        (
            "inventory_shortage_repair_plan",
            (),
            {"accounts": 2, "available_inventory": 1},
        ),
        (
            "inventory_buffer_protection_report",
            (),
            {"accounts": 2, "available_inventory": 1},
        ),
        ("inventory_slo_surface_targets", (8,), {}),
        ("inventory_health", (), {"current": 1, "minimum": 2}),
        ("inventory_stage_counts", (), {"creator": "Stacey", "campaign_slug": None}),
        (
            "inventory_count_related",
            ("caption_families", "parent_asset_id", {"asset_1"}),
            {},
        ),
        ("inventory_limiting_stage", ({"scheduleSafeAssets": 0},), {}),
        ("inventory_loss_by_stage", ({"parentAssets": 1},), {}),
        ("inventory_repair_actions", ({"shortfall": 1},), {}),
    ]


def test_campaign_factory_delegates_inventory_recovery_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    factory.services = FakeServices()

    assert factory.inventory_recovery_report(
        creator="Stacey", required_inventory=3
    ) == {
        "method": "inventory_recovery_report",
    }
    assert factory.inventory_recovery_priority_report(creator="Stacey") == {
        "method": "inventory_recovery_priority_report",
    }
    assert factory.inventory_recovery_by_blocker(creator="Stacey") == {
        "method": "inventory_recovery_by_blocker",
    }
    assert factory.inventory_recovery_master_report(creator="Stacey") == {
        "method": "inventory_recovery_master_report",
    }
    assert factory._inventory_recovery_blocked_asset({"assetId": "asset_1"}) == {
        "method": "inventory_recovery_blocked_asset",
    }
    assert factory._inventory_recovery_class_for_blocker("missing_audio") == {
        "method": "inventory_recovery_class_for_blocker",
    }
    assert factory._inventory_recovery_class_rows([{"assetId": "asset_1"}]) == {
        "method": "inventory_recovery_class_rows",
    }
    assert factory._inventory_recovery_assets_unlocked(
        [{"repairClasses": ["audio_failure"]}],
        ["audio_failure"],
    ) == {"method": "inventory_recovery_assets_unlocked"}
    assert factory._inventory_recovery_priorities(
        [{"repairClass": "audio_failure"}]
    ) == {
        "method": "inventory_recovery_priorities",
    }

    assert calls == [
        (
            "inventory_recovery_report",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": None,
                "content_surface": None,
                "required_inventory": 3,
                "account_target": 25,
                "posts_per_account_per_day": 3,
                "buffer_days": 3,
            },
        ),
        ("inventory_recovery_priority_report", (), {"creator": "Stacey"}),
        ("inventory_recovery_by_blocker", (), {"creator": "Stacey"}),
        ("inventory_recovery_master_report", (), {"creator": "Stacey"}),
        ("inventory_recovery_blocked_asset", ({"assetId": "asset_1"},), {}),
        ("inventory_recovery_class_for_blocker", ("missing_audio",), {}),
        ("inventory_recovery_class_rows", ([{"assetId": "asset_1"}],), {}),
        (
            "inventory_recovery_assets_unlocked",
            ([{"repairClasses": ["audio_failure"]}], ["audio_failure"]),
            {},
        ),
        ("inventory_recovery_priorities", ([{"repairClass": "audio_failure"}],), {}),
    ]


def test_campaign_factory_delegates_inventory_reservation_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def reserve_inventory_asset(self, *args, **kwargs):
            calls.append(("reserve_inventory_asset", args, kwargs))
            return {"reservation_id": "invres_1"}

        def expire_inventory_reservations(self, *args, **kwargs):
            calls.append(("expire_inventory_reservations", args, kwargs))
            return 2

        def release_inventory_reservation(self, *args, **kwargs):
            calls.append(("release_inventory_reservation", args, kwargs))
            return {"status": "released"}

        def inventory_uniqueness_conflicts(self, *args, **kwargs):
            calls.append(("inventory_uniqueness_conflicts", args, kwargs))
            return [{"assetId": "asset_2"}]

        def reservation_adjusted_inventory(self, *args, **kwargs):
            calls.append(("reservation_adjusted_inventory", args, kwargs))
            return {"netInventory": 1}

    factory.services = FakeServices()

    assert factory.reserve_inventory_asset(
        "asset_1",
        account_id="acct_1",
        surface="feed_single",
        reserved_by="test",
        expires_at="2026-01-02T00:00:00+00:00",
        idempotency_key="idem_1",
        metadata={"sourceFamilyId": "family_1"},
        reuse_cooldown_days=3,
        override_reason="manual",
    ) == {"reservation_id": "invres_1"}
    assert (
        factory._expire_inventory_reservations(
            now="2026-01-03T00:00:00+00:00", commit=False
        )
        == 2
    )
    assert factory.release_inventory_reservation("invres_1", status="cancelled") == {
        "status": "released"
    }
    assert factory._inventory_uniqueness_conflicts(
        {"id": "asset_1", "campaign_id": "campaign_1"},
        uniqueness={"sourceFamilyId": "family_1"},
        surface="feed_single",
        cooldown_days=3,
        account_id="acct_1",
    ) == [{"assetId": "asset_2"}]
    assert factory._reservation_adjusted_inventory(
        [{"assetId": "asset_1", "canHandoff": True, "contentSurface": "feed_single"}],
        content_surface="feed_single",
    ) == {"netInventory": 1}

    assert calls == [
        (
            "reserve_inventory_asset",
            ("asset_1",),
            {
                "account_id": "acct_1",
                "surface": "feed_single",
                "reserved_by": "test",
                "expires_at": "2026-01-02T00:00:00+00:00",
                "idempotency_key": "idem_1",
                "metadata": {"sourceFamilyId": "family_1"},
                "reuse_cooldown_days": 3,
                "override_reason": "manual",
            },
        ),
        (
            "expire_inventory_reservations",
            (),
            {"now": "2026-01-03T00:00:00+00:00", "commit": False},
        ),
        ("release_inventory_reservation", ("invres_1",), {"status": "cancelled"}),
        (
            "inventory_uniqueness_conflicts",
            ({"id": "asset_1", "campaign_id": "campaign_1"},),
            {
                "uniqueness": {"sourceFamilyId": "family_1"},
                "surface": "feed_single",
                "cooldown_days": 3,
                "account_id": "acct_1",
            },
        ),
        (
            "reservation_adjusted_inventory",
            (
                [
                    {
                        "assetId": "asset_1",
                        "canHandoff": True,
                        "contentSurface": "feed_single",
                    }
                ],
            ),
            {"content_surface": "feed_single"},
        ),
    ]


def test_campaign_factory_delegates_schedule_safe_production_methods_to_services() -> (
    None
):
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    factory.services = FakeServices()

    assert factory.schedule_safe_production_report(
        creator="Stacey", required_inventory=3
    ) == {
        "method": "schedule_safe_production_report",
    }
    assert factory.schedule_safe_production_waterfall(creator="Stacey") == {
        "method": "schedule_safe_production_waterfall",
    }
    assert factory.schedule_safe_production_loss_analysis(creator="Stacey") == {
        "method": "schedule_safe_production_loss_analysis",
    }
    assert factory.schedule_safe_production_capacity_model(creator="Stacey") == {
        "method": "schedule_safe_production_capacity_model",
    }
    assert factory.schedule_safe_production_master_report(creator="Stacey") == {
        "method": "schedule_safe_production_master_report",
    }
    assert factory._schedule_safe_production_assets(
        creator="Stacey",
        campaign_slug="summer",
        content_surface="reel",
        lookback_days=1,
    ) == {"method": "schedule_safe_production_assets"}
    assert factory._schedule_safe_asset_created_at(
        {"created_at": "2026-01-01T00:00:00+00:00"}
    ) == {
        "method": "schedule_safe_asset_created_at",
    }
    assert factory._schedule_safe_production_waterfall_rows(
        [{"id": "asset_1"}], "reel"
    ) == {
        "method": "schedule_safe_production_waterfall_rows",
    }
    assert factory._schedule_safe_is_variant_asset({"variant_id": "variant_1"}) == {
        "method": "schedule_safe_is_variant_asset",
    }
    assert factory._schedule_safe_related_count(
        "caption_families", "parent_asset_id", {"asset_1"}
    ) == {
        "method": "schedule_safe_related_count",
    }
    assert factory._schedule_safe_production_variant_checks(
        {"id": "asset_1"}, "reel"
    ) == {
        "method": "schedule_safe_production_variant_checks",
    }
    assert factory._schedule_safe_production_largest_loss(
        [{"stage": "x", "lossCount": 1}]
    ) == {
        "method": "schedule_safe_production_largest_loss",
    }
    assert factory._schedule_safe_production_capacity(
        current_inventory=1,
        daily_production=2.0,
        required_for_25=3,
    ) == {"method": "schedule_safe_production_capacity"}
    assert factory._schedule_safe_required_parents_per_day(1.0, 1, 1) == {
        "method": "schedule_safe_required_parents_per_day",
    }
    assert factory._schedule_safe_required_variants_per_day(1.0, 1, 1) == {
        "method": "schedule_safe_required_variants_per_day",
    }
    assert factory._schedule_safe_production_summary_key("raw_parent_reels") == {
        "method": "schedule_safe_production_summary_key",
    }

    assert calls == [
        (
            "schedule_safe_production_report",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": None,
                "content_surface": "reel",
                "lookback_days": 1,
                "required_inventory": 3,
                "current_inventory": None,
            },
        ),
        ("schedule_safe_production_waterfall", (), {"creator": "Stacey"}),
        ("schedule_safe_production_loss_analysis", (), {"creator": "Stacey"}),
        ("schedule_safe_production_capacity_model", (), {"creator": "Stacey"}),
        ("schedule_safe_production_master_report", (), {"creator": "Stacey"}),
        (
            "schedule_safe_production_assets",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "summer",
                "content_surface": "reel",
                "lookback_days": 1,
            },
        ),
        (
            "schedule_safe_asset_created_at",
            ({"created_at": "2026-01-01T00:00:00+00:00"},),
            {},
        ),
        ("schedule_safe_production_waterfall_rows", ([{"id": "asset_1"}], "reel"), {}),
        ("schedule_safe_is_variant_asset", ({"variant_id": "variant_1"},), {}),
        (
            "schedule_safe_related_count",
            ("caption_families", "parent_asset_id", {"asset_1"}),
            {},
        ),
        ("schedule_safe_production_variant_checks", ({"id": "asset_1"}, "reel"), {}),
        (
            "schedule_safe_production_largest_loss",
            ([{"stage": "x", "lossCount": 1}],),
            {},
        ),
        (
            "schedule_safe_production_capacity",
            (),
            {"current_inventory": 1, "daily_production": 2.0, "required_for_25": 3},
        ),
        ("schedule_safe_required_parents_per_day", (1.0, 1, 1), {}),
        ("schedule_safe_required_variants_per_day", (1.0, 1, 1), {}),
        ("schedule_safe_production_summary_key", ("raw_parent_reels",), {}),
    ]


def test_campaign_factory_delegates_fresh_reel_production_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    factory.services = FakeServices()

    assert factory.fresh_schedule_safe_production_plan(
        creator="Stacey", current_inventory=11
    ) == {
        "method": "fresh_schedule_safe_production_plan",
    }
    assert factory.fresh_reel_production_batch_plan(creator="Stacey") == {
        "method": "fresh_reel_production_batch_plan",
    }
    assert factory.fresh_reel_production_capacity_plan(creator="Stacey") == {
        "method": "fresh_reel_production_capacity_plan",
    }
    assert factory.fresh_reel_production_master_report(creator="Stacey") == {
        "method": "fresh_reel_production_master_report",
    }
    assert factory._fresh_reel_current_schedule_safe_inventory(
        creator="Stacey", campaign_slug="summer"
    ) == {
        "method": "fresh_reel_current_schedule_safe_inventory",
    }
    assert factory._fresh_reel_downstream_schedule_safe_yield_pct() == {
        "method": "fresh_reel_downstream_schedule_safe_yield_pct",
    }
    assert factory._fresh_reel_expected_stage_rows(
        raw_parent_candidates_needed=1,
        parents_needed=1,
        caption_families_needed=1,
        caption_versions_needed=5,
        variants_needed=15,
    ) == {"method": "fresh_reel_expected_stage_rows"}
    assert factory._fresh_reel_stage_evidence("parent_accepted") == {
        "method": "fresh_reel_stage_evidence",
    }
    assert factory._fresh_reel_execution_batches(
        fresh_needed=90,
        downstream_yield_pct=68.1,
        variants_per_parent=15,
        batch_target=90,
    ) == {"method": "fresh_reel_execution_batches"}

    assert calls == [
        (
            "fresh_schedule_safe_production_plan",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": None,
                "target_schedule_safe_inventory": 270,
                "current_inventory": 11,
                "caption_versions_per_parent": 5,
                "variants_per_caption": 3,
                "batch_schedule_safe_target": 90,
            },
        ),
        ("fresh_reel_production_batch_plan", (), {"creator": "Stacey"}),
        ("fresh_reel_production_capacity_plan", (), {"creator": "Stacey"}),
        ("fresh_reel_production_master_report", (), {"creator": "Stacey"}),
        (
            "fresh_reel_current_schedule_safe_inventory",
            (),
            {"creator": "Stacey", "campaign_slug": "summer"},
        ),
        ("fresh_reel_downstream_schedule_safe_yield_pct", (), {}),
        (
            "fresh_reel_expected_stage_rows",
            (),
            {
                "raw_parent_candidates_needed": 1,
                "parents_needed": 1,
                "caption_families_needed": 1,
                "caption_versions_needed": 5,
                "variants_needed": 15,
            },
        ),
        ("fresh_reel_stage_evidence", ("parent_accepted",), {}),
        (
            "fresh_reel_execution_batches",
            (),
            {
                "fresh_needed": 90,
                "downstream_yield_pct": 68.1,
                "variants_per_parent": 15,
                "batch_target": 90,
            },
        ),
    ]


def test_campaign_factory_delegates_reel_factory_report_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    factory.services = FakeServices()
    metrics = {"rawCandidates": 25}
    yield_report = {"qcPassRate": 0.9}
    proof = {"confidence": "medium"}
    asset = {"id": "asset_1"}

    assert factory.reel_factory_parent_throughput_proof(
        required_parents_per_day=53, lookback_days=2
    ) == {
        "method": "reel_factory_parent_throughput_proof",
    }
    assert factory.reel_factory_yield_analysis(metrics=metrics) == {
        "method": "reel_factory_yield_analysis"
    }
    assert factory.reel_factory_failure_analysis() == {
        "method": "reel_factory_failure_analysis"
    }
    assert factory.reel_factory_capacity_model(required_parents_per_day=53) == {
        "method": "reel_factory_capacity_model"
    }
    assert factory.reel_factory_200_account_readiness() == {
        "method": "reel_factory_200_account_readiness"
    }
    assert factory.reel_factory_master_report() == {
        "method": "reel_factory_master_report"
    }
    assert factory._reel_factory_parent_metrics() == {
        "method": "reel_factory_parent_metrics"
    }
    assert factory._reel_factory_parent_qc_pass(asset) == {
        "method": "reel_factory_parent_qc_pass"
    }
    assert factory._reel_factory_confidence(metrics) == {
        "method": "reel_factory_confidence"
    }
    assert factory._operator_review_minutes_per_parent(metrics) == {
        "method": "operator_review_minutes_per_parent"
    }
    assert factory._reel_factory_intake_metrics(metrics) == {
        "method": "reel_factory_intake_metrics"
    }
    assert factory._reel_factory_parent_creation_metrics(metrics) == {
        "method": "reel_factory_parent_creation_metrics"
    }
    assert factory._reel_factory_quality_gate_metrics(yield_report) == {
        "method": "reel_factory_quality_gate_metrics"
    }
    assert factory._reel_factory_operational_readiness_metrics(yield_report) == {
        "method": "reel_factory_operational_readiness_metrics",
    }
    assert factory._reel_factory_human_cost(metrics) == {
        "method": "reel_factory_human_cost"
    }
    assert factory._reel_factory_rating(proof) == {"method": "reel_factory_rating"}

    assert calls == [
        (
            "reel_factory_parent_throughput_proof",
            (),
            {"required_parents_per_day": 53, "lookback_days": 2},
        ),
        ("reel_factory_yield_analysis", (), {"metrics": metrics}),
        ("reel_factory_failure_analysis", (), {}),
        ("reel_factory_capacity_model", (), {"required_parents_per_day": 53}),
        ("reel_factory_200_account_readiness", (), {}),
        ("reel_factory_master_report", (), {}),
        ("reel_factory_parent_metrics", (), {}),
        ("reel_factory_parent_qc_pass", (asset,), {}),
        ("reel_factory_confidence", (metrics,), {}),
        ("operator_review_minutes_per_parent", (metrics,), {}),
        ("reel_factory_intake_metrics", (metrics,), {}),
        ("reel_factory_parent_creation_metrics", (metrics,), {}),
        ("reel_factory_quality_gate_metrics", (yield_report,), {}),
        ("reel_factory_operational_readiness_metrics", (yield_report,), {}),
        ("reel_factory_human_cost", (metrics,), {}),
        ("reel_factory_rating", (proof,), {}),
    ]


def test_campaign_factory_delegates_parent_factory_report_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    factory.services = FakeServices()
    metrics = {"rawCandidates": 245}
    waterfall = {"stages": []}
    rejection = {"totalFailures": 1}
    loss = {"largestLossStage": "discoverability_safety_pass"}
    reasons = [{"repairable": True, "frequency": 1}]

    assert factory.parent_factory_yield_waterfall(required_parents_per_day=53) == {
        "method": "parent_factory_yield_waterfall",
    }
    assert factory.parent_factory_loss_analysis(required_parents_per_day=53) == {
        "method": "parent_factory_loss_analysis",
    }
    assert factory.parent_factory_rejection_report(waterfall=waterfall) == {
        "method": "parent_factory_rejection_report"
    }
    assert factory.parent_factory_quality_gate_analysis() == {
        "method": "parent_factory_quality_gate_analysis"
    }
    assert factory.parent_factory_optimization_plan(required_parents_per_day=53) == {
        "method": "parent_factory_optimization_plan",
    }
    assert factory.parent_factory_master_optimization_report(
        required_parents_per_day=53
    ) == {
        "method": "parent_factory_master_optimization_report",
    }
    assert factory.parent_factory_recoverable_yield() == {
        "method": "parent_factory_recoverable_yield"
    }
    assert factory.parent_factory_throughput_recovery_plan() == {
        "method": "parent_factory_throughput_recovery_plan"
    }
    assert factory.parent_factory_53_parent_feasibility() == {
        "method": "parent_factory_53_parent_feasibility"
    }
    assert factory.parent_factory_secondary_loss_analysis() == {
        "method": "parent_factory_secondary_loss_analysis"
    }
    assert factory.parent_factory_true_yield_model() == {
        "method": "parent_factory_true_yield_model"
    }
    assert factory.parent_factory_realistic_53_parent_plan() == {
        "method": "parent_factory_realistic_53_parent_plan"
    }
    assert factory._parent_factory_stage_order() == {
        "method": "parent_factory_stage_order"
    }
    assert factory._parent_factory_detailed_stage_counts(metrics) == {
        "method": "parent_factory_detailed_stage_counts"
    }
    assert factory._parent_factory_highest_roi(reasons) == {
        "method": "parent_factory_highest_roi"
    }
    assert factory._parent_factory_top_fixes(reasons) == {
        "method": "parent_factory_top_fixes"
    }
    assert factory._parent_factory_human_bottleneck(
        required=53, rejection=rejection
    ) == {
        "method": "parent_factory_human_bottleneck",
    }
    assert factory._parent_factory_yield_explanation(waterfall, loss) == {
        "method": "parent_factory_yield_explanation",
    }
    assert factory._secondary_loss_reason("handoff_ready", 0) == {
        "method": "secondary_loss_reason"
    }
    assert factory._parent_factory_trial_loss_buckets(waterfall) == {
        "method": "parent_factory_trial_loss_buckets"
    }
    assert factory._parent_factory_trial_stage_repairable("handoff_ready") == {
        "method": "parent_factory_trial_stage_repairable",
    }

    assert calls == [
        ("parent_factory_yield_waterfall", (), {"required_parents_per_day": 53}),
        ("parent_factory_loss_analysis", (), {"required_parents_per_day": 53}),
        ("parent_factory_rejection_report", (), {"waterfall": waterfall}),
        ("parent_factory_quality_gate_analysis", (), {}),
        ("parent_factory_optimization_plan", (), {"required_parents_per_day": 53}),
        (
            "parent_factory_master_optimization_report",
            (),
            {"required_parents_per_day": 53},
        ),
        ("parent_factory_recoverable_yield", (), {}),
        ("parent_factory_throughput_recovery_plan", (), {}),
        ("parent_factory_53_parent_feasibility", (), {}),
        ("parent_factory_secondary_loss_analysis", (), {}),
        ("parent_factory_true_yield_model", (), {}),
        ("parent_factory_realistic_53_parent_plan", (), {}),
        ("parent_factory_stage_order", (), {}),
        ("parent_factory_detailed_stage_counts", (metrics,), {}),
        ("parent_factory_highest_roi", (reasons,), {}),
        ("parent_factory_top_fixes", (reasons,), {}),
        (
            "parent_factory_human_bottleneck",
            (),
            {"required": 53, "rejection": rejection},
        ),
        ("parent_factory_yield_explanation", (waterfall, loss), {}),
        ("secondary_loss_reason", ("handoff_ready", 0), {}),
        ("parent_factory_trial_loss_buckets", (waterfall,), {}),
        ("parent_factory_trial_stage_repairable", ("handoff_ready",), {}),
    ]


def test_campaign_factory_delegates_parent_factory_trial_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    factory.services = FakeServices()
    sandbox = object()
    result = {"rejectionEvidenceCapture": {"evidenceIds": ["evidence_1"]}}

    assert factory.parent_factory_production_trial() == {
        "method": "parent_factory_production_trial"
    }
    assert factory._latest_measured_53_parent_production_trial() == {
        "method": "latest_measured_53_parent_production_trial",
    }
    assert factory.parent_factory_53_parent_trial() == {
        "method": "parent_factory_53_parent_trial"
    }
    assert factory.parent_factory_trial_results() == {
        "method": "parent_factory_trial_results"
    }
    assert factory.parent_factory_trial_analysis() == {
        "method": "parent_factory_trial_analysis"
    }
    assert factory.parent_factory_post_gate_fresh_batch_proof() == {
        "method": "parent_factory_post_gate_fresh_batch_proof",
    }
    assert factory.parent_factory_production_scorecard() == {
        "method": "parent_factory_production_scorecard"
    }
    assert factory.parent_factory_real_yield_report() == {
        "method": "parent_factory_real_yield_report"
    }
    assert factory._post_gate_fresh_batch_candidates() == {
        "method": "post_gate_fresh_batch_candidates"
    }
    assert factory._post_gate_blocked_candidate_evidence(sandbox, result) == {
        "method": "post_gate_blocked_candidate_evidence",
    }

    assert calls == [
        ("parent_factory_production_trial", (), {}),
        ("latest_measured_53_parent_production_trial", (), {}),
        ("parent_factory_53_parent_trial", (), {}),
        ("parent_factory_trial_results", (), {}),
        ("parent_factory_trial_analysis", (), {}),
        ("parent_factory_post_gate_fresh_batch_proof", (), {}),
        ("parent_factory_production_scorecard", (), {}),
        ("parent_factory_real_yield_report", (), {}),
        ("post_gate_fresh_batch_candidates", (), {}),
        ("post_gate_blocked_candidate_evidence", (sandbox, result), {}),
    ]


def test_campaign_factory_delegates_parent_factory_planning_methods_to_services() -> (
    None
):
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    factory.services = FakeServices()

    assert factory.parent_factory_autopilot_plan(
        accounts=50, posts_per_account_per_day=2
    ) == {
        "method": "parent_factory_autopilot_plan",
    }
    assert factory.parent_factory_shortfall_report(accounts=50) == {
        "method": "parent_factory_shortfall_report"
    }
    assert factory.parent_factory_production_targets(accounts=50) == {
        "method": "parent_factory_production_targets"
    }

    assert calls == [
        (
            "parent_factory_autopilot_plan",
            (),
            {"accounts": 50, "posts_per_account_per_day": 2},
        ),
        ("parent_factory_shortfall_report", (), {"accounts": 50}),
        ("parent_factory_production_targets", (), {"accounts": 50}),
    ]


def test_campaign_factory_delegates_contentforge_visual_qc_methods_to_services() -> (
    None
):
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    factory.services = FakeServices()

    assert factory.contentforge_visual_qc_failure_report(
        creator="Stacey", current_inventory=11
    ) == {
        "method": "contentforge_visual_qc_failure_report",
    }
    assert factory.contentforge_visual_qc_waterfall(creator="Stacey") == {
        "method": "contentforge_visual_qc_waterfall",
    }
    assert factory.contentforge_visual_qc_loss_analysis(creator="Stacey") == {
        "method": "contentforge_visual_qc_loss_analysis",
    }
    assert factory.contentforge_visual_qc_repair_plan(creator="Stacey") == {
        "method": "contentforge_visual_qc_repair_plan",
    }
    assert factory.contentforge_visual_qc_master_report(creator="Stacey") == {
        "method": "contentforge_visual_qc_master_report",
    }
    assert factory._contentforge_visual_qc_failure_for_asset(
        {"id": "asset_1"}, "reel"
    ) == {
        "method": "contentforge_visual_qc_failure_for_asset",
    }
    assert factory._contentforge_visual_qc_failure_category(
        {"id": "asset_1"},
        ["operator_visual_review_required"],
        {"canHandoff": False},
        {"publishableCandidate": False},
    ) == {"method": "contentforge_visual_qc_failure_category"}
    assert factory._contentforge_non_visual_gates_pass({}, {}, {}, []) == {
        "method": "contentforge_non_visual_gates_pass",
    }
    assert factory._contentforge_visual_qc_category_rows(
        [
            {"failureCategory": "operator_visual_review_required"},
        ]
    ) == {"method": "contentforge_visual_qc_category_rows"}
    assert factory._contentforge_visual_qc_recovered_inventory(
        [
            {
                "failureCategory": "operator_visual_review_required",
                "estimatedInventoryGain": 1,
            },
        ],
        ["operator_visual_review_required"],
    ) == {"method": "contentforge_visual_qc_recovered_inventory"}
    assert factory._contentforge_visual_qc_answer(
        {"failureCategory": "operator_visual_review_required"}, 1
    ) == {
        "method": "contentforge_visual_qc_answer",
    }

    assert calls == [
        (
            "contentforge_visual_qc_failure_report",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": None,
                "content_surface": "reel",
                "lookback_days": 1,
                "current_inventory": 11,
                "required_inventory": 225,
            },
        ),
        ("contentforge_visual_qc_waterfall", (), {"creator": "Stacey"}),
        ("contentforge_visual_qc_loss_analysis", (), {"creator": "Stacey"}),
        ("contentforge_visual_qc_repair_plan", (), {"creator": "Stacey"}),
        ("contentforge_visual_qc_master_report", (), {"creator": "Stacey"}),
        ("contentforge_visual_qc_failure_for_asset", ({"id": "asset_1"}, "reel"), {}),
        (
            "contentforge_visual_qc_failure_category",
            (
                {"id": "asset_1"},
                ["operator_visual_review_required"],
                {"canHandoff": False},
                {"publishableCandidate": False},
            ),
            {},
        ),
        ("contentforge_non_visual_gates_pass", ({}, {}, {}, []), {}),
        (
            "contentforge_visual_qc_category_rows",
            ([{"failureCategory": "operator_visual_review_required"}],),
            {},
        ),
        (
            "contentforge_visual_qc_recovered_inventory",
            (
                [
                    {
                        "failureCategory": "operator_visual_review_required",
                        "estimatedInventoryGain": 1,
                    }
                ],
                ["operator_visual_review_required"],
            ),
            {},
        ),
        (
            "contentforge_visual_qc_answer",
            ({"failureCategory": "operator_visual_review_required"}, 1),
            {},
        ),
    ]


def test_campaign_factory_delegates_multi_blocker_unlock_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    factory.services = FakeServices()

    assert factory.multi_blocker_inventory_unlock_report(
        creator="Stacey", current_inventory=11
    ) == {
        "method": "multi_blocker_inventory_unlock_report",
    }
    assert factory.multi_blocker_inventory_unlock_plan(creator="Stacey") == {
        "method": "multi_blocker_inventory_unlock_plan",
    }
    assert factory.inventory_unlock_minimal_fix_set(creator="Stacey") == {
        "method": "inventory_unlock_minimal_fix_set",
    }
    assert factory.inventory_unlock_master_report(creator="Stacey") == {
        "method": "inventory_unlock_master_report",
    }
    assert factory._multi_blocker_asset_row(
        {"assetId": "asset_1", "blockingReasons": ["missing_audio"]}
    ) == {
        "method": "multi_blocker_asset_row",
    }
    assert factory._multi_blocker_repair_class("missing_audio") == {
        "method": "multi_blocker_repair_class"
    }
    assert factory._multi_blocker_combo_rows(
        [], current_inventory=0, required_inventory=1
    ) == {
        "method": "multi_blocker_combo_rows",
    }
    assert factory._multi_blocker_assets_unlocked([], ["audio_failure"]) == {
        "method": "multi_blocker_assets_unlocked",
    }
    assert factory._multi_blocker_estimated_minutes([], ["audio_failure"]) == {
        "method": "multi_blocker_estimated_minutes",
    }
    assert factory._multi_blocker_combo_difficulty(["audio_failure"]) == {
        "method": "multi_blocker_combo_difficulty",
    }
    assert factory._multi_blocker_best_combo([], 1) == {
        "method": "multi_blocker_best_combo",
    }
    assert factory._multi_blocker_minimal_fix_set(
        [], current_inventory=0, required_inventory=1
    ) == {
        "method": "multi_blocker_minimal_fix_set",
    }

    assert calls == [
        (
            "multi_blocker_inventory_unlock_report",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": None,
                "content_surface": "reel",
                "required_inventory": 225,
                "current_inventory": 11,
            },
        ),
        ("multi_blocker_inventory_unlock_plan", (), {"creator": "Stacey"}),
        ("inventory_unlock_minimal_fix_set", (), {"creator": "Stacey"}),
        ("inventory_unlock_master_report", (), {"creator": "Stacey"}),
        (
            "multi_blocker_asset_row",
            ({"assetId": "asset_1", "blockingReasons": ["missing_audio"]},),
            {},
        ),
        ("multi_blocker_repair_class", ("missing_audio",), {}),
        (
            "multi_blocker_combo_rows",
            ([],),
            {"current_inventory": 0, "required_inventory": 1},
        ),
        ("multi_blocker_assets_unlocked", ([], ["audio_failure"]), {}),
        ("multi_blocker_estimated_minutes", ([], ["audio_failure"]), {}),
        ("multi_blocker_combo_difficulty", (["audio_failure"],), {}),
        ("multi_blocker_best_combo", ([], 1), {}),
        (
            "multi_blocker_minimal_fix_set",
            ([],),
            {"current_inventory": 0, "required_inventory": 1},
        ),
    ]


def test_campaign_factory_delegates_lifecycle_reporting_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    factory.services = FakeServices()
    asset = {"id": "asset_1"}
    plan = {"id": "plan_1"}
    post = {"id": "post_1"}
    snapshot = {"id": "snapshot_1"}

    assert factory.campaign_readiness("may", user_id="user_1") == {
        "method": "campaign_readiness"
    }
    assert factory.lifecycle_report(
        "may", user_id="user_1", include_threadsdash="off"
    ) == {"method": "lifecycle_report"}
    assert factory.creator_os_lifecycle_dashboard(campaign="may", user_id="user_1") == {
        "method": "creator_os_lifecycle_dashboard"
    }
    assert factory._creator_os_lifecycle_bucket({"currentState": "published"}) == {
        "method": "creator_os_lifecycle_bucket"
    }
    assert factory._lifecycle_snapshots_by_asset("campaign_1") == {
        "method": "lifecycle_snapshots_by_asset"
    }
    assert factory._lifecycle_threadsdash_indexes(
        campaign_slug="may",
        user_id="user_1",
        include_threadsdash="off",
        threadsdash_posts=[],
    ) == {
        "method": "lifecycle_threadsdash_indexes",
    }
    assert factory._lifecycle_row(
        campaign={"id": "campaign_1", "slug": "may"},
        asset=asset,
        plan=plan,
        assignments=[],
        snapshots=[],
        threadsdash_posts=[],
    ) == {
        "method": "lifecycle_row",
    }
    assert factory._derive_lifecycle_state(
        asset=asset,
        plan=plan,
        assignments=[],
        readiness={},
        post=post,
        snapshot=snapshot,
        mismatch={},
        media_issue=None,
    ) == {
        "method": "derive_lifecycle_state",
    }
    assert factory._lifecycle_blocking_reason(["missing_audit"]) == {
        "method": "lifecycle_blocking_reason"
    }
    assert factory._lifecycle_media_validation_issue(asset=asset, post=post) == {
        "method": "lifecycle_media_validation_issue"
    }
    assert factory._latest_lifecycle_post([post]) == {"method": "latest_lifecycle_post"}
    assert factory._lifecycle_snapshot_has_metrics(snapshot) == {
        "method": "lifecycle_snapshot_has_metrics"
    }
    assert factory._lifecycle_is_past_due("2026-01-01T00:00:00+00:00") == {
        "method": "lifecycle_is_past_due"
    }
    assert factory._lifecycle_past_due_resolved(post) == {
        "method": "lifecycle_past_due_resolved"
    }
    assert factory._lifecycle_last_state_change(
        asset=asset, plan=plan, post=post, snapshot=snapshot
    ) == {"method": "lifecycle_last_state_change"}
    assert factory._parse_lifecycle_time("2026-01-01T00:00:00+00:00") == {
        "method": "parse_lifecycle_time"
    }
    assert factory._lifecycle_mismatch(
        asset=asset, plan=plan, post=post, snapshot=snapshot, context_fingerprint="abc"
    ) == {
        "method": "lifecycle_mismatch",
    }
    assert factory._lifecycle_post_meta(post) == {"method": "lifecycle_post_meta"}
    assert factory._lifecycle_fingerprint({"caption": "hello"}) == {
        "method": "lifecycle_fingerprint"
    }
    assert factory._canonical_lifecycle_context(
        {"render_recipe": None, "caption": "hello"}
    ) == {"method": "canonical_lifecycle_context"}
    assert factory._compact_lifecycle_post(post) == {"method": "compact_lifecycle_post"}
    assert factory._compact_lifecycle_snapshot(snapshot) == {
        "method": "compact_lifecycle_snapshot"
    }

    assert calls == [
        ("campaign_readiness", ("may",), {"user_id": "user_1"}),
        (
            "lifecycle_report",
            ("may",),
            {
                "user_id": "user_1",
                "threadsdash_posts": None,
                "include_threadsdash": "off",
                "state": None,
                "blocking_reason": None,
                "rendered_asset_id": None,
            },
        ),
        (
            "creator_os_lifecycle_dashboard",
            (),
            {
                "campaign": "may",
                "user_id": "user_1",
                "threadsdash_posts": None,
                "include_threadsdash": "auto",
                "generated_at": None,
            },
        ),
        ("creator_os_lifecycle_bucket", ({"currentState": "published"},), {}),
        ("lifecycle_snapshots_by_asset", ("campaign_1",), {}),
        (
            "lifecycle_threadsdash_indexes",
            (),
            {
                "campaign_slug": "may",
                "user_id": "user_1",
                "include_threadsdash": "off",
                "threadsdash_posts": [],
            },
        ),
        (
            "lifecycle_row",
            (),
            {
                "campaign": {"id": "campaign_1", "slug": "may"},
                "asset": asset,
                "plan": plan,
                "assignments": [],
                "snapshots": [],
                "threadsdash_posts": [],
            },
        ),
        (
            "derive_lifecycle_state",
            (),
            {
                "asset": asset,
                "plan": plan,
                "assignments": [],
                "readiness": {},
                "post": post,
                "snapshot": snapshot,
                "mismatch": {},
                "media_issue": None,
            },
        ),
        ("lifecycle_blocking_reason", (["missing_audit"],), {}),
        ("lifecycle_media_validation_issue", (), {"asset": asset, "post": post}),
        ("latest_lifecycle_post", ([post],), {}),
        ("lifecycle_snapshot_has_metrics", (snapshot,), {}),
        ("lifecycle_is_past_due", ("2026-01-01T00:00:00+00:00",), {}),
        ("lifecycle_past_due_resolved", (post,), {}),
        (
            "lifecycle_last_state_change",
            (),
            {"asset": asset, "plan": plan, "post": post, "snapshot": snapshot},
        ),
        ("parse_lifecycle_time", ("2026-01-01T00:00:00+00:00",), {}),
        (
            "lifecycle_mismatch",
            (),
            {
                "asset": asset,
                "plan": plan,
                "post": post,
                "snapshot": snapshot,
                "context_fingerprint": "abc",
            },
        ),
        ("lifecycle_post_meta", (post,), {}),
        ("lifecycle_fingerprint", ({"caption": "hello"},), {}),
        (
            "canonical_lifecycle_context",
            ({"render_recipe": None, "caption": "hello"},),
            {},
        ),
        ("compact_lifecycle_post", (post,), {}),
        ("compact_lifecycle_snapshot", (snapshot,), {}),
    ]


def test_campaign_factory_delegates_inventory_perceptual_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def asset_uniqueness_values(self, *args, **kwargs):
            calls.append(("asset_uniqueness_values", args, kwargs))
            return {"perceptualClusterId": "pdq:abc"}

        def ensure_rendered_asset_perceptual_metadata(self, *args, **kwargs):
            calls.append(("ensure_rendered_asset_perceptual_metadata", args, kwargs))
            return {"id": "asset_1"}

        def pdq_cluster_id_for_fingerprint(self, *args, **kwargs):
            calls.append(("pdq_cluster_id_for_fingerprint", args, kwargs))
            return "pdq:abc"

    factory.services = FakeServices()

    assert factory._asset_uniqueness_values(
        {"id": "asset_1"},
        metadata={"sourceFamilyId": "family_1"},
    ) == {"perceptualClusterId": "pdq:abc"}
    assert factory.ensure_rendered_asset_perceptual_metadata(
        "asset_1", commit=False
    ) == {"id": "asset_1"}
    assert (
        factory._pdq_cluster_id_for_fingerprint(
            campaign_id="campaign_1",
            rendered_asset_id="asset_1",
            fingerprint="0" * 64,
        )
        == "pdq:abc"
    )

    assert calls == [
        (
            "asset_uniqueness_values",
            ({"id": "asset_1"},),
            {"metadata": {"sourceFamilyId": "family_1"}},
        ),
        ("ensure_rendered_asset_perceptual_metadata", ("asset_1",), {"commit": False}),
        (
            "pdq_cluster_id_for_fingerprint",
            (),
            {
                "campaign_id": "campaign_1",
                "rendered_asset_id": "asset_1",
                "fingerprint": "0" * 64,
            },
        ),
    ]


def test_campaign_factory_delegates_make_batch_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def make_batch(self, *args, **kwargs):
            calls.append(("make_batch", args, kwargs))
            return {
                "schema": "campaign_factory.make_batch.v1",
                "campaign": kwargs["campaign_slug"],
            }

        def run_slideshow_pack(self, *args, **kwargs):
            calls.append(("run_slideshow_pack", args, kwargs))
            return {
                "schema": "campaign_factory.slideshow_pack.v1",
                "campaign": kwargs["campaign_slug"],
            }

        def campaign_source_media_summary(self, *args, **kwargs):
            calls.append(("campaign_source_media_summary", args, kwargs))
            return {"video": 1, "image": 2}

        def formats_for_batch(self, *args, **kwargs):
            calls.append(("formats_for_batch", args, kwargs))
            return ["reel", "slideshow"]

    factory.services = FakeServices()

    assert factory.make_batch(
        folder=Path("/tmp/input"),
        campaign_slug="daily",
        model_slug="stacey",
        output_format="auto",
        variant_count=3,
        reference_pattern="auto",
        contentforge_base_url="http://contentforge.test",
        user_id="user_1",
        dry_run_export=False,
        workers=2,
        recipes=["v01_original"],
        auto_approve_warning_only=False,
        source_prompt="/tmp/prompt.json",
        import_notes="notes",
    ) == {"schema": "campaign_factory.make_batch.v1", "campaign": "daily"}
    assert factory._run_slideshow_pack(
        campaign_slug="daily",
        variant_count=3,
        title="Daily",
        cluster_key="cluster_1",
        media_types={"image"},
    ) == {"schema": "campaign_factory.slideshow_pack.v1", "campaign": "daily"}
    assert factory._campaign_source_media_summary("campaign_1") == {
        "video": 1,
        "image": 2,
    }
    assert factory._formats_for_batch("auto", {"video": 1, "image": 1}) == [
        "reel",
        "slideshow",
    ]

    assert calls == [
        (
            "make_batch",
            (),
            {
                "folder": Path("/tmp/input"),
                "campaign_slug": "daily",
                "model_slug": "stacey",
                "output_format": "auto",
                "variant_count": 3,
                "reference_pattern": "auto",
                "contentforge_base_url": "http://contentforge.test",
                "user_id": "user_1",
                "dry_run_export": False,
                "workers": 2,
                "recipes": ["v01_original"],
                "auto_approve_warning_only": False,
                "source_prompt": "/tmp/prompt.json",
                "import_notes": "notes",
            },
        ),
        (
            "run_slideshow_pack",
            (),
            {
                "campaign_slug": "daily",
                "variant_count": 3,
                "title": "Daily",
                "cluster_key": "cluster_1",
                "media_types": {"image"},
            },
        ),
        ("campaign_source_media_summary", ("campaign_1",), {}),
        ("formats_for_batch", ("auto", {"video": 1, "image": 1}), {}),
    ]


def test_core_services_delegates_make_batch_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeMakeBatch:
        def make_batch(self, *args, **kwargs):
            calls.append(("make_batch", args, kwargs))
            return {
                "schema": "campaign_factory.make_batch.v1",
                "campaign": kwargs["campaign_slug"],
            }

        def run_slideshow_pack(self, *args, **kwargs):
            calls.append(("run_slideshow_pack", args, kwargs))
            return {
                "schema": "campaign_factory.slideshow_pack.v1",
                "campaign": kwargs["campaign_slug"],
            }

        def campaign_source_media_summary(self, *args, **kwargs):
            calls.append(("campaign_source_media_summary", args, kwargs))
            return {"video": 2, "image": 1}

        def formats_for_batch(self, *args, **kwargs):
            calls.append(("formats_for_batch", args, kwargs))
            return ["reel"]

    services.make_batch_repo = FakeMakeBatch()

    assert services.make_batch(
        folder=Path("/tmp/input"),
        campaign_slug="daily",
        model_slug="stacey",
    ) == {"schema": "campaign_factory.make_batch.v1", "campaign": "daily"}
    assert services.run_slideshow_pack(
        campaign_slug="daily",
        variant_count=2,
        title="Daily",
    ) == {"schema": "campaign_factory.slideshow_pack.v1", "campaign": "daily"}
    assert services.campaign_source_media_summary("campaign_1") == {
        "video": 2,
        "image": 1,
    }
    assert services.formats_for_batch("reel", {"video": 1, "image": 0}) == ["reel"]

    assert calls == [
        (
            "make_batch",
            (),
            {
                "folder": Path("/tmp/input"),
                "campaign_slug": "daily",
                "model_slug": "stacey",
                "output_format": "auto",
                "variant_count": 20,
                "reference_pattern": "auto",
                "contentforge_base_url": None,
                "user_id": None,
                "dry_run_export": True,
                "workers": 3,
                "recipes": None,
                "auto_approve_warning_only": True,
                "source_prompt": None,
                "import_notes": None,
            },
        ),
        (
            "run_slideshow_pack",
            (),
            {
                "campaign_slug": "daily",
                "variant_count": 2,
                "title": "Daily",
                "cluster_key": None,
                "media_types": None,
            },
        ),
        ("campaign_source_media_summary", ("campaign_1",), {}),
        ("formats_for_batch", ("reel", {"video": 1, "image": 0}), {}),
    ]


def test_campaign_factory_delegates_finished_video_intake_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def intake_finished_video(self, *args, **kwargs):
            calls.append(("intake_finished_video", args, kwargs))
            return {
                "schema": "campaign_factory.finished_video_intake.v1",
                "campaign": kwargs["campaign_slug"],
            }

        def finished_video_hooks(self, *args, **kwargs):
            calls.append(("finished_video_hooks", args, kwargs))
            return [{"text": "hook"}]

        def finished_video_preflight(self, *args, **kwargs):
            calls.append(("finished_video_preflight", args, kwargs))
            return [{"code": "finished_video_not_reels_canvas"}]

        def finished_video_style_lane_format(self, *args, **kwargs):
            calls.append(("finished_video_style_lane_format", args, kwargs))
            return "mirror_selfie"

        def finished_video_caption_band(self, *args, **kwargs):
            calls.append(("finished_video_caption_band", args, kwargs))
            return "auto"

        def finished_video_caption_font(self, *args, **kwargs):
            calls.append(("finished_video_caption_font", args, kwargs))
            return "Instagram Sans Condensed"

        def classify_finished_video_format(self, *args, **kwargs):
            calls.append(("classify_finished_video_format", args, kwargs))
            return "selfie_video"

    factory.services = FakeServices()

    assert factory.intake_finished_video(
        input_path=Path("/tmp/source.mp4"),
        model_slug="stacey",
        platform="instagram",
        goal="reach",
        reference_pattern="auto",
        campaign_slug="daily",
        contentforge_base_url="http://contentforge.test",
        user_id="user_1",
        dry_run_export=True,
        variant_count=3,
        workers=2,
        recipes=["v01_original"],
        creative_plan="plan_1",
        style_lane="mirror",
        source_lineage_path=Path("/tmp/lineage.json"),
    ) == {"schema": "campaign_factory.finished_video_intake.v1", "campaign": "daily"}
    assert factory.finished_video_hooks(
        "mirror_selfie", {"clusterKey": "cluster"}, count=2
    ) == [{"text": "hook"}]
    assert factory._finished_video_preflight({"effectiveAspectRatio": 1.0}) == [
        {"code": "finished_video_not_reels_canvas"},
    ]
    assert factory._finished_video_style_lane_format("mirror") == "mirror_selfie"
    assert factory._finished_video_caption_band("mirror_selfie") == "auto"
    assert (
        factory._finished_video_caption_font("mirror_selfie")
        == "Instagram Sans Condensed"
    )
    assert (
        factory._classify_finished_video_format(Path("/tmp/selfie.mp4"))
        == "selfie_video"
    )

    assert calls == [
        (
            "intake_finished_video",
            (),
            {
                "input_path": Path("/tmp/source.mp4"),
                "model_slug": "stacey",
                "platform": "instagram",
                "goal": "reach",
                "reference_pattern": "auto",
                "campaign_slug": "daily",
                "contentforge_base_url": "http://contentforge.test",
                "user_id": "user_1",
                "dry_run_export": True,
                "variant_count": 3,
                "workers": 2,
                "recipes": ["v01_original"],
                "creative_plan": "plan_1",
                "style_lane": "mirror",
                "source_lineage_path": Path("/tmp/lineage.json"),
            },
        ),
        (
            "finished_video_hooks",
            ("mirror_selfie", {"clusterKey": "cluster"}),
            {"count": 2},
        ),
        ("finished_video_preflight", ({"effectiveAspectRatio": 1.0},), {}),
        ("finished_video_style_lane_format", ("mirror",), {}),
        ("finished_video_caption_band", ("mirror_selfie",), {}),
        ("finished_video_caption_font", ("mirror_selfie",), {}),
        ("classify_finished_video_format", (Path("/tmp/selfie.mp4"),), {}),
    ]


def test_core_services_delegates_finished_video_intake_methods_to_repository(
    tmp_path,
) -> None:
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
        calls = []

        def fake_intake_finished_video(*args, **kwargs):
            calls.append(("intake_finished_video", args, kwargs))
            return {
                "schema": "campaign_factory.finished_video_intake.v1",
                "campaign": kwargs["campaign_slug"],
            }

        def fake_hooks(*args, **kwargs):
            calls.append(("finished_video_hooks", args, kwargs))
            return [{"text": "hook"}]

        def fake_preflight(*args, **kwargs):
            calls.append(("finished_video_preflight", args, kwargs))
            return [{"code": "finished_video_probe_unavailable"}]

        def fake_style(*args, **kwargs):
            calls.append(("finished_video_style_lane_format", args, kwargs))
            return "pov"

        def fake_band(*args, **kwargs):
            calls.append(("finished_video_caption_band", args, kwargs))
            return "auto"

        def fake_font(*args, **kwargs):
            calls.append(("finished_video_caption_font", args, kwargs))
            return "Instagram Sans Condensed"

        def fake_classify(*args, **kwargs):
            calls.append(("classify_finished_video_format", args, kwargs))
            return "selfie_video"

        factory.services.finished_video.intake_finished_video = (
            fake_intake_finished_video
        )
        factory.services.finished_video.finished_video_hooks = fake_hooks
        factory.services.finished_video.finished_video_preflight = fake_preflight
        factory.services.finished_video.finished_video_style_lane_format = fake_style
        factory.services.finished_video.finished_video_caption_band = fake_band
        factory.services.finished_video.finished_video_caption_font = fake_font
        factory.services.finished_video.classify_finished_video_format = fake_classify

        assert factory.services.intake_finished_video(
            input_path=Path("/tmp/source.mp4"),
            model_slug="stacey",
            campaign_slug="daily",
        ) == {
            "schema": "campaign_factory.finished_video_intake.v1",
            "campaign": "daily",
        }
        assert factory.services.finished_video_hooks(
            "pov", {"clusterKey": "cluster"}
        ) == [{"text": "hook"}]
        assert factory.services.finished_video_preflight({}) == [
            {"code": "finished_video_probe_unavailable"}
        ]
        assert factory.services.finished_video_style_lane_format("pov") == "pov"
        assert factory.services.finished_video_caption_band("pov") == "auto"
        assert (
            factory.services.finished_video_caption_font("pov")
            == "Instagram Sans Condensed"
        )
        assert (
            factory.services.classify_finished_video_format(Path("/tmp/selfie.mp4"))
            == "selfie_video"
        )

        assert calls == [
            (
                "intake_finished_video",
                (),
                {
                    "input_path": Path("/tmp/source.mp4"),
                    "model_slug": "stacey",
                    "platform": "instagram",
                    "goal": "reach",
                    "reference_pattern": "auto",
                    "campaign_slug": "daily",
                    "contentforge_base_url": None,
                    "user_id": None,
                    "dry_run_export": True,
                    "variant_count": 10,
                    "workers": 3,
                    "recipes": None,
                    "creative_plan": None,
                    "style_lane": None,
                    "source_lineage_path": None,
                },
            ),
            ("finished_video_hooks", ("pov", {"clusterKey": "cluster"}), {"count": 5}),
            ("finished_video_preflight", ({},), {}),
            ("finished_video_style_lane_format", ("pov",), {}),
            ("finished_video_caption_band", ("pov",), {}),
            ("finished_video_caption_font", ("pov",), {}),
            ("classify_finished_video_format", (Path("/tmp/selfie.mp4"),), {}),
        ]
    finally:
        factory.close()


def test_campaign_factory_delegates_finished_video_registration_review_methods_to_services() -> (
    None
):
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def review_rendered_asset(self, *args, **kwargs):
            calls.append(("review_rendered_asset", args, kwargs))
            return {"id": args[0], "review_state": kwargs["decision"]}

        def approve_rendered_asset(self, *args, **kwargs):
            calls.append(("approve_rendered_asset", args, kwargs))
            return {"id": args[0], "review_state": "approved"}

        def register_finished_video(self, *args, **kwargs):
            calls.append(("register_finished_video", args, kwargs))
            return {
                "schema": "campaign_factory.register_finished_video.v1",
                "campaign": kwargs["campaign_slug"],
                "renderedAssetId": "asset_finished",
            }

    factory.services = FakeServices()

    assert factory.review_rendered_asset(
        "asset_1",
        decision="rejected",
        notes="not this one",
        require_safe_audit=True,
    ) == {"id": "asset_1", "review_state": "rejected"}
    assert factory.approve_rendered_asset(
        "asset_1", notes="approved", require_safe_audit=True
    ) == {
        "id": "asset_1",
        "review_state": "approved",
    }
    assert factory.register_finished_video(
        input_path=Path("/tmp/finished.mp4"),
        campaign_slug="daily",
        model_slug="stacey",
        caption="caption text",
        instagram_post_caption="post caption",
        caption_hash="hash_1",
        caption_bank="bank",
        creator_mix="Stacey",
        creator_model="Stacey",
        track_id="track_1",
        track_name="Track One",
        audio_source="operator_muxed_audio",
        selected_reason="operator selected",
        operator="op",
        approval_reason="looks good",
        review_batch="batch_1",
        caption_placement_policy="focal_safe_v1",
        caption_placement_decision={"status": "passed"},
    ) == {
        "schema": "campaign_factory.register_finished_video.v1",
        "campaign": "daily",
        "renderedAssetId": "asset_finished",
    }

    assert calls == [
        (
            "review_rendered_asset",
            ("asset_1",),
            {
                "decision": "rejected",
                "notes": "not this one",
                "require_safe_audit": True,
            },
        ),
        (
            "approve_rendered_asset",
            ("asset_1",),
            {"notes": "approved", "require_safe_audit": True},
        ),
        (
            "register_finished_video",
            (),
            {
                "input_path": Path("/tmp/finished.mp4"),
                "campaign_slug": "daily",
                "model_slug": "stacey",
                "caption": "caption text",
                "instagram_post_caption": "post caption",
                "caption_hash": "hash_1",
                "caption_bank": "bank",
                "creator_mix": "Stacey",
                "creator_model": "Stacey",
                "track_id": "track_1",
                "track_name": "Track One",
                "audio_source": "operator_muxed_audio",
                "selected_reason": "operator selected",
                "operator": "op",
                "approval_reason": "looks good",
                "review_batch": "batch_1",
                "caption_placement_policy": "focal_safe_v1",
                "caption_placement_decision": {"status": "passed"},
            },
        ),
    ]


def test_core_services_delegates_finished_video_registration_review_methods_to_repository() -> (
    None
):
    services = object.__new__(CoreServices)
    calls = []

    class FakeFinishedVideo:
        def review_rendered_asset(self, *args, **kwargs):
            calls.append(("review_rendered_asset", args, kwargs))
            return {"id": args[0], "review_state": kwargs["decision"]}

        def approve_rendered_asset(self, *args, **kwargs):
            calls.append(("approve_rendered_asset", args, kwargs))
            return {"id": args[0], "review_state": "approved"}

        def register_finished_video(self, *args, **kwargs):
            calls.append(("register_finished_video", args, kwargs))
            return {
                "schema": "campaign_factory.register_finished_video.v1",
                "campaign": kwargs["campaign_slug"],
            }

        def record_lineage_costs(self, *args, **kwargs):
            calls.append(("record_lineage_costs", args, kwargs))

    services.finished_video = FakeFinishedVideo()
    lineage = {"schema": "lineage.v1"}

    assert services.review_rendered_asset(
        "asset_1", decision="rejected", notes="no"
    ) == {
        "id": "asset_1",
        "review_state": "rejected",
    }
    assert services.approve_rendered_asset(
        "asset_1", notes="ok", require_safe_audit=True
    ) == {
        "id": "asset_1",
        "review_state": "approved",
    }
    assert services.register_finished_video(
        input_path=Path("/tmp/finished.mp4"),
        campaign_slug="daily",
        model_slug="stacey",
        caption="caption text",
    ) == {"schema": "campaign_factory.register_finished_video.v1", "campaign": "daily"}
    assert services.record_lineage_costs(lineage) is None

    assert calls == [
        (
            "review_rendered_asset",
            ("asset_1",),
            {"decision": "rejected", "notes": "no", "require_safe_audit": False},
        ),
        (
            "approve_rendered_asset",
            ("asset_1",),
            {"notes": "ok", "require_safe_audit": True},
        ),
        (
            "register_finished_video",
            (),
            {
                "input_path": Path("/tmp/finished.mp4"),
                "campaign_slug": "daily",
                "model_slug": "stacey",
                "caption": "caption text",
                "instagram_post_caption": None,
                "caption_hash": None,
                "caption_bank": None,
                "creator_mix": None,
                "creator_model": None,
                "track_id": None,
                "track_name": None,
                "audio_source": None,
                "selected_reason": None,
                "operator": None,
                "approval_reason": None,
                "review_batch": None,
                "caption_placement_policy": None,
                "caption_placement_decision": None,
            },
        ),
        ("record_lineage_costs", (lineage,), {}),
    ]


def test_campaign_factory_delegates_reel_execution_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def prepare_reel_inputs(self, *args, **kwargs):
            calls.append(("prepare_reel_inputs", args, kwargs))
            return {
                "schema": "campaign_factory.prepare_reel_inputs.v1",
                "campaign": kwargs["campaign_slug"],
            }

        def rotate_hooks_for_source(self, *args, **kwargs):
            calls.append(("rotate_hooks_for_source", args, kwargs))
            return ["second", "first"]

        def reel_sidecar_hooks(self, *args, **kwargs):
            calls.append(("reel_sidecar_hooks", args, kwargs))
            return ["hook"], [{"hookIndex": 0}]

        def next_reel_clip_number(self, *args, **kwargs):
            calls.append(("next_reel_clip_number", args, kwargs))
            return 4

        def run_reel_factory(self, *args, **kwargs):
            calls.append(("run_reel_factory", args, kwargs))
            return {"returncode": 0, "pipelineJobId": "job_run"}

        def sync_reel_outputs(self, *args, **kwargs):
            calls.append(("sync_reel_outputs", args, kwargs))
            return {"synced": [{"id": "asset_1"}], "pipelineJobId": "job_sync"}

        def model_slug_for_campaign(self, *args, **kwargs):
            calls.append(("model_slug_for_campaign", args, kwargs))
            return "stacey"

        def ratio_from_filename(self, *args, **kwargs):
            calls.append(("ratio_from_filename", args, kwargs))
            return "4:5"

        def caption_generation_for_clip(self, *args, **kwargs):
            calls.append(("caption_generation_for_clip", args, kwargs))
            return {"generationId": "gen_1"}

        def caption_outcome_context_for_reel_output(self, *args, **kwargs):
            calls.append(("caption_outcome_context_for_reel_output", args, kwargs))
            return {"caption_bank": "reel_factory_reference"}

        def lineage_first_present(self, *args, **kwargs):
            calls.append(("lineage_first_present", args, kwargs))
            return "value"

        def lineage_placement_decision(self, *args, **kwargs):
            calls.append(("lineage_placement_decision", args, kwargs))
            return {"status": "passed"}

        def caption_lane_from_render_recipe(self, *args, **kwargs):
            calls.append(("caption_lane_from_render_recipe", args, kwargs))
            return "bottom"

        def audio_intent_from_reference_recommendations(self, *args, **kwargs):
            calls.append(("audio_intent_from_reference_recommendations", args, kwargs))
            return {"schema": "pipeline.audio_intent.v1", "status": "attached"}

        def backfill_synced_reel_output_lineage(self, *args, **kwargs):
            calls.append(("backfill_synced_reel_output_lineage", args, kwargs))
            return True

    factory.services = FakeServices()

    assert factory.prepare_reel_inputs(
        campaign_slug="daily",
        hooks=["first", "second"],
        recipes=["v01_original"],
        caption_color="auto",
        notes="notes",
        force_new=True,
    ) == {"schema": "campaign_factory.prepare_reel_inputs.v1", "campaign": "daily"}
    assert factory._rotate_hooks_for_source(["first", "second"], 1) == [
        "second",
        "first",
    ]
    assert factory._reel_sidecar_hooks([{"text": "hook"}]) == (
        ["hook"],
        [{"hookIndex": 0}],
    )
    assert factory._next_reel_clip_number(Path("/tmp/raw")) == 4
    assert factory.run_reel_factory(
        campaign_slug="daily",
        workers=2,
        dry_run=True,
        caption_band="safe",
        caption_color="light",
        caption_style="ig",
        caption_font="Instagram Sans Condensed",
        caption_placement_qc=False,
        phone_finalize=False,
        rerender_all=True,
        max_outputs_per_clip=2,
    ) == {"returncode": 0, "pipelineJobId": "job_run"}
    assert factory.sync_reel_outputs(campaign_slug="daily") == {
        "synced": [{"id": "asset_1"}],
        "pipelineJobId": "job_sync",
    }
    assert factory._model_slug_for_campaign("camp_1") == "stacey"
    assert factory._ratio_from_filename("clip_4x5_v01.mp4") == "4:5"
    assert factory._caption_generation_for_clip("clip_001") == {"generationId": "gen_1"}
    assert factory._caption_outcome_context_for_reel_output(
        clip_stem="clip_001",
        caption_text="caption",
        caption_hash="hash_1",
        recipe="caption_bg",
        source_path="/tmp/source.mp4",
        rendered_path="/tmp/rendered.mp4",
        creator_model="stacey",
        lineage={"captionPlacementPolicy": "focal_safe_v1"},
    ) == {"caption_bank": "reel_factory_reference"}
    assert (
        factory._lineage_first_present({"captionBank": {"x": "value"}}, "x") == "value"
    )
    assert factory._lineage_placement_decision(
        {"captionPlacementDecision": {"status": "passed"}}
    ) == {
        "status": "passed",
    }
    assert factory._caption_lane_from_render_recipe("caption_bg") == "bottom"
    assert factory._audio_intent_from_reference_recommendations(
        {"audioRecommendations": {"recommendations": [{"audioId": "track_1"}]}},
        now="2026-06-01T00:00:00+00:00",
    ) == {"schema": "pipeline.audio_intent.v1", "status": "attached"}
    assert (
        factory._backfill_synced_reel_output_lineage(
            asset={"id": "asset_1"},
            clip_stem="clip_001",
            caption_text="caption",
            recipe="caption_bg",
            output_path="/tmp/output.mp4",
            rendered_path="/tmp/rendered.mp4",
            creator_model="stacey",
            lineage={},
        )
        is True
    )

    assert calls == [
        (
            "prepare_reel_inputs",
            (),
            {
                "campaign_slug": "daily",
                "hooks": ["first", "second"],
                "recipes": ["v01_original"],
                "caption_color": "auto",
                "notes": "notes",
                "force_new": True,
            },
        ),
        ("rotate_hooks_for_source", (["first", "second"], 1), {}),
        ("reel_sidecar_hooks", ([{"text": "hook"}],), {}),
        ("next_reel_clip_number", (Path("/tmp/raw"),), {}),
        (
            "run_reel_factory",
            (),
            {
                "campaign_slug": "daily",
                "workers": 2,
                "dry_run": True,
                "caption_band": "safe",
                "caption_color": "light",
                "caption_style": "ig",
                "caption_font": "Instagram Sans Condensed",
                "caption_placement_qc": False,
                "phone_finalize": False,
                "rerender_all": True,
                "max_outputs_per_clip": 2,
            },
        ),
        ("sync_reel_outputs", (), {"campaign_slug": "daily"}),
        ("model_slug_for_campaign", ("camp_1",), {}),
        ("ratio_from_filename", ("clip_4x5_v01.mp4",), {}),
        ("caption_generation_for_clip", ("clip_001",), {}),
        (
            "caption_outcome_context_for_reel_output",
            (),
            {
                "clip_stem": "clip_001",
                "caption_text": "caption",
                "caption_hash": "hash_1",
                "recipe": "caption_bg",
                "source_path": "/tmp/source.mp4",
                "rendered_path": "/tmp/rendered.mp4",
                "creator_model": "stacey",
                "lineage": {"captionPlacementPolicy": "focal_safe_v1"},
            },
        ),
        ("lineage_first_present", ({"captionBank": {"x": "value"}}, "x"), {}),
        (
            "lineage_placement_decision",
            ({"captionPlacementDecision": {"status": "passed"}},),
            {},
        ),
        ("caption_lane_from_render_recipe", ("caption_bg",), {}),
        (
            "audio_intent_from_reference_recommendations",
            ({"audioRecommendations": {"recommendations": [{"audioId": "track_1"}]}},),
            {"now": "2026-06-01T00:00:00+00:00"},
        ),
        (
            "backfill_synced_reel_output_lineage",
            (),
            {
                "asset": {"id": "asset_1"},
                "clip_stem": "clip_001",
                "caption_text": "caption",
                "recipe": "caption_bg",
                "output_path": "/tmp/output.mp4",
                "rendered_path": "/tmp/rendered.mp4",
                "creator_model": "stacey",
                "lineage": {},
            },
        ),
    ]


def test_core_services_delegates_reel_execution_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeReelExecution:
        def prepare_reel_inputs(self, *args, **kwargs):
            calls.append(("prepare_reel_inputs", args, kwargs))
            return {
                "schema": "campaign_factory.prepare_reel_inputs.v1",
                "campaign": kwargs["campaign_slug"],
            }

        def rotate_hooks_for_source(self, *args, **kwargs):
            calls.append(("rotate_hooks_for_source", args, kwargs))
            return ["second", "first"]

        def reel_sidecar_hooks(self, *args, **kwargs):
            calls.append(("reel_sidecar_hooks", args, kwargs))
            return ["hook"], [{"hookIndex": 0}]

        def next_reel_clip_number(self, *args, **kwargs):
            calls.append(("next_reel_clip_number", args, kwargs))
            return 4

        def run_reel_factory(self, *args, **kwargs):
            calls.append(("run_reel_factory", args, kwargs))
            return {"returncode": 0, "pipelineJobId": "job_run"}

        def sync_reel_outputs(self, *args, **kwargs):
            calls.append(("sync_reel_outputs", args, kwargs))
            return {"synced": [{"id": "asset_1"}], "pipelineJobId": "job_sync"}

        def model_slug_for_campaign(self, *args, **kwargs):
            calls.append(("model_slug_for_campaign", args, kwargs))
            return "stacey"

        def ratio_from_filename(self, *args, **kwargs):
            calls.append(("ratio_from_filename", args, kwargs))
            return "4:5"

        def caption_generation_for_clip(self, *args, **kwargs):
            calls.append(("caption_generation_for_clip", args, kwargs))
            return {"generationId": "gen_1"}

        def caption_outcome_context_for_reel_output(self, *args, **kwargs):
            calls.append(("caption_outcome_context_for_reel_output", args, kwargs))
            return {"caption_bank": "reel_factory_reference"}

        def lineage_first_present(self, *args, **kwargs):
            calls.append(("lineage_first_present", args, kwargs))
            return "value"

        def lineage_placement_decision(self, *args, **kwargs):
            calls.append(("lineage_placement_decision", args, kwargs))
            return {"status": "passed"}

        def caption_lane_from_render_recipe(self, *args, **kwargs):
            calls.append(("caption_lane_from_render_recipe", args, kwargs))
            return "bottom"

        def audio_intent_from_reference_recommendations(self, *args, **kwargs):
            calls.append(("audio_intent_from_reference_recommendations", args, kwargs))
            return {"schema": "pipeline.audio_intent.v1", "status": "attached"}

        def backfill_synced_reel_output_lineage(self, *args, **kwargs):
            calls.append(("backfill_synced_reel_output_lineage", args, kwargs))
            return True

    services.reel_execution = FakeReelExecution()

    assert services.prepare_reel_inputs(
        campaign_slug="daily",
        hooks=["first", "second"],
        recipes=["v01_original"],
        caption_color="auto",
        notes="notes",
        force_new=True,
    ) == {"schema": "campaign_factory.prepare_reel_inputs.v1", "campaign": "daily"}
    assert services.rotate_hooks_for_source(["first", "second"], 1) == [
        "second",
        "first",
    ]
    assert services.reel_sidecar_hooks([{"text": "hook"}]) == (
        ["hook"],
        [{"hookIndex": 0}],
    )
    assert services.next_reel_clip_number(Path("/tmp/raw")) == 4
    assert services.run_reel_factory(
        campaign_slug="daily",
        workers=2,
        dry_run=True,
        caption_band="safe",
        caption_color="light",
        caption_style="ig",
        caption_font="Instagram Sans Condensed",
        caption_placement_qc=False,
        phone_finalize=False,
        rerender_all=True,
        max_outputs_per_clip=2,
    ) == {"returncode": 0, "pipelineJobId": "job_run"}
    assert services.sync_reel_outputs(campaign_slug="daily") == {
        "synced": [{"id": "asset_1"}],
        "pipelineJobId": "job_sync",
    }
    assert services.model_slug_for_campaign("camp_1") == "stacey"
    assert services.ratio_from_filename("clip_4x5_v01.mp4") == "4:5"
    assert services.caption_generation_for_clip("clip_001") == {"generationId": "gen_1"}
    assert services.caption_outcome_context_for_reel_output(
        clip_stem="clip_001",
        caption_text="caption",
        caption_hash="hash_1",
        recipe="caption_bg",
        source_path="/tmp/source.mp4",
        rendered_path="/tmp/rendered.mp4",
        creator_model="stacey",
        lineage={"captionPlacementPolicy": "focal_safe_v1"},
    ) == {"caption_bank": "reel_factory_reference"}
    assert (
        services.lineage_first_present({"captionBank": {"x": "value"}}, "x") == "value"
    )
    assert services.lineage_placement_decision(
        {"captionPlacementDecision": {"status": "passed"}}
    ) == {
        "status": "passed",
    }
    assert services.caption_lane_from_render_recipe("caption_bg") == "bottom"
    assert services.audio_intent_from_reference_recommendations(
        {"audioRecommendations": {"recommendations": [{"audioId": "track_1"}]}},
        now="2026-06-01T00:00:00+00:00",
    ) == {"schema": "pipeline.audio_intent.v1", "status": "attached"}
    assert (
        services.backfill_synced_reel_output_lineage(
            asset={"id": "asset_1"},
            clip_stem="clip_001",
            caption_text="caption",
            recipe="caption_bg",
            output_path="/tmp/output.mp4",
            rendered_path="/tmp/rendered.mp4",
            creator_model="stacey",
            lineage={},
        )
        is True
    )

    assert calls == [
        (
            "prepare_reel_inputs",
            (),
            {
                "campaign_slug": "daily",
                "hooks": ["first", "second"],
                "recipes": ["v01_original"],
                "caption_color": "auto",
                "notes": "notes",
                "force_new": True,
            },
        ),
        ("rotate_hooks_for_source", (["first", "second"], 1), {}),
        ("reel_sidecar_hooks", ([{"text": "hook"}],), {}),
        ("next_reel_clip_number", (Path("/tmp/raw"),), {}),
        (
            "run_reel_factory",
            (),
            {
                "campaign_slug": "daily",
                "workers": 2,
                "dry_run": True,
                "caption_band": "safe",
                "caption_color": "light",
                "caption_style": "ig",
                "caption_font": "Instagram Sans Condensed",
                "caption_placement_qc": False,
                "phone_finalize": False,
                "rerender_all": True,
                "max_outputs_per_clip": 2,
            },
        ),
        ("sync_reel_outputs", (), {"campaign_slug": "daily"}),
        ("model_slug_for_campaign", ("camp_1",), {}),
        ("ratio_from_filename", ("clip_4x5_v01.mp4",), {}),
        ("caption_generation_for_clip", ("clip_001",), {}),
        (
            "caption_outcome_context_for_reel_output",
            (),
            {
                "clip_stem": "clip_001",
                "caption_text": "caption",
                "caption_hash": "hash_1",
                "recipe": "caption_bg",
                "source_path": "/tmp/source.mp4",
                "rendered_path": "/tmp/rendered.mp4",
                "creator_model": "stacey",
                "lineage": {"captionPlacementPolicy": "focal_safe_v1"},
            },
        ),
        ("lineage_first_present", ({"captionBank": {"x": "value"}}, "x"), {}),
        (
            "lineage_placement_decision",
            ({"captionPlacementDecision": {"status": "passed"}},),
            {},
        ),
        ("caption_lane_from_render_recipe", ("caption_bg",), {}),
        (
            "audio_intent_from_reference_recommendations",
            ({"audioRecommendations": {"recommendations": [{"audioId": "track_1"}]}},),
            {"now": "2026-06-01T00:00:00+00:00"},
        ),
        (
            "backfill_synced_reel_output_lineage",
            (),
            {
                "asset": {"id": "asset_1"},
                "clip_stem": "clip_001",
                "caption_text": "caption",
                "recipe": "caption_bg",
                "output_path": "/tmp/output.mp4",
                "rendered_path": "/tmp/rendered.mp4",
                "creator_model": "stacey",
                "lineage": {},
            },
        ),
    ]


def test_campaign_factory_delegates_variant_lineage_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def register_parent_reel(self, *args, **kwargs):
            calls.append(("register_parent_reel", args, kwargs))
            return {
                "schema": "campaign_factory.parent_reel.v1",
                "parentAssetId": args[0],
            }

        def variant_plan(self, *args, **kwargs):
            calls.append(("variant_plan", args, kwargs))
            return {
                "schema": "campaign_factory.variant_plan.v1",
                "parentAssetId": kwargs["parent_asset_id"],
            }

        def generate_variants(self, *args, **kwargs):
            calls.append(("generate_variants", args, kwargs))
            return {
                "schema": "campaign_factory.generate_variants.v1",
                "status": "completed",
            }

        def contentforge_variant_pack_blocked_result(self, *args, **kwargs):
            calls.append(("contentforge_variant_pack_blocked_result", args, kwargs))
            return {
                "schema": "campaign_factory.generate_variants.v1",
                "status": "blocked",
            }

        def register_variant_asset(self, *args, **kwargs):
            calls.append(("register_variant_asset", args, kwargs))
            return {"variantId": "var_1"}

        def parent_variant_inventory(self, *args, **kwargs):
            calls.append(("parent_variant_inventory", args, kwargs))
            return {"schema": "campaign_factory.parent_variant_inventory.v1"}

        def variant_metrics_rollup(self, *args, **kwargs):
            calls.append(("variant_metrics_rollup", args, kwargs))
            return {"schema": "campaign_factory.variant_metrics_rollup.v1"}

        def concept_for_parent_asset(self, *args, **kwargs):
            calls.append(("concept_for_parent_asset", args, kwargs))
            return {"conceptId": "concept_1"}

        def variant_lineage_for_asset(self, *args, **kwargs):
            calls.append(("variant_lineage_for_asset", args, kwargs))
            return {"variantId": "var_1"}

        def concept_payload(self, *args, **kwargs):
            calls.append(("concept_payload", args, kwargs))
            return {"conceptId": "concept_1"}

        def variant_family_payload(self, *args, **kwargs):
            calls.append(("variant_family_payload", args, kwargs))
            return {"variantFamilyId": "vfam_1"}

        def variant_lineage_asset_payload(self, *args, **kwargs):
            calls.append(("variant_lineage_asset_payload", args, kwargs))
            return {"variantId": "var_1"}

        def variant_usage_payload(self, *args, **kwargs):
            calls.append(("variant_usage_payload", args, kwargs))
            return {"id": "usage_1"}

        def variant_rollup_group(self, *args, **kwargs):
            calls.append(("variant_rollup_group", args, kwargs))
            return [{"variantId": "var_1"}]

    factory.services = FakeServices()
    error = TimeoutError("boom")

    assert factory.register_parent_reel(
        "asset_1", operator="tester", status="active", metadata={"ok": True}
    ) == {
        "schema": "campaign_factory.parent_reel.v1",
        "parentAssetId": "asset_1",
    }
    assert factory.variant_plan(
        parent_asset_id="asset_1",
        caption_version_id="cver_1",
        count=2,
        contentforge_preset="caption_safe_v2",
        cooldown_days=7,
    ) == {"schema": "campaign_factory.variant_plan.v1", "parentAssetId": "asset_1"}
    assert factory.generate_variants(
        parent_asset_id="asset_1",
        caption_version_id="cver_1",
        count=2,
        contentforge_preset="caption_safe_v2",
        contentforge_base_url="http://contentforge.test",
        source_media_path="/tmp/source.mp4",
        contentforge_timeout_seconds=3,
    ) == {"schema": "campaign_factory.generate_variants.v1", "status": "completed"}
    assert factory._contentforge_variant_pack_blocked_result(
        plan={"parentAssetId": "asset_1"},
        blocking_reason="timeout",
        endpoint="http://contentforge.test/api/variant-pack/jobs",
        staged_source="source.mp4",
        timeout_seconds=3,
        error=error,
        extra={"runId": "run_1"},
    ) == {"schema": "campaign_factory.generate_variants.v1", "status": "blocked"}
    assert factory.register_variant_asset(
        parent_asset_id="asset_1",
        variant_asset_id="asset_2",
        variant_family_id="vfam_1",
        variant_index=1,
        operations=[{"type": "caption_safe"}],
        caption_family_id="cfam_1",
        caption_version_id="cver_1",
        contentforge_run_id="run_1",
        contentforge_preset="caption_safe_v2",
        qc_status="passed",
        cooldown_days=9,
        commit=False,
    ) == {"variantId": "var_1"}
    assert factory.parent_variant_inventory("may") == {
        "schema": "campaign_factory.parent_variant_inventory.v1"
    }
    assert factory.variant_metrics_rollup("may") == {
        "schema": "campaign_factory.variant_metrics_rollup.v1"
    }
    assert factory._concept_for_parent_asset("asset_1") == {"conceptId": "concept_1"}
    assert factory._variant_lineage_for_asset("asset_2") == {"variantId": "var_1"}
    assert factory._concept_payload({"id": "concept_1"}) == {"conceptId": "concept_1"}
    assert factory._variant_family_payload({"id": "vfam_1"}) == {
        "variantFamilyId": "vfam_1"
    }
    assert factory._variant_asset_payload({"id": "var_1"}) == {"variantId": "var_1"}
    assert factory._variant_usage_payload({"id": "usage_1"}) == {"id": "usage_1"}
    assert factory._variant_rollup_group(
        [{"variantId": "var_1"}], "variantId", "variantId"
    ) == [{"variantId": "var_1"}]

    assert calls == [
        (
            "register_parent_reel",
            ("asset_1",),
            {"operator": "tester", "status": "active", "metadata": {"ok": True}},
        ),
        (
            "variant_plan",
            (),
            {
                "parent_asset_id": "asset_1",
                "caption_version_id": "cver_1",
                "count": 2,
                "contentforge_preset": "caption_safe_v2",
                "cooldown_days": 7,
            },
        ),
        (
            "generate_variants",
            (),
            {
                "parent_asset_id": "asset_1",
                "caption_version_id": "cver_1",
                "count": 2,
                "contentforge_preset": "caption_safe_v2",
                "contentforge_base_url": "http://contentforge.test",
                "source_media_path": "/tmp/source.mp4",
                "contentforge_timeout_seconds": 3,
            },
        ),
        (
            "contentforge_variant_pack_blocked_result",
            (),
            {
                "plan": {"parentAssetId": "asset_1"},
                "blocking_reason": "timeout",
                "endpoint": "http://contentforge.test/api/variant-pack/jobs",
                "staged_source": "source.mp4",
                "timeout_seconds": 3,
                "error": error,
                "extra": {"runId": "run_1"},
            },
        ),
        (
            "register_variant_asset",
            (),
            {
                "parent_asset_id": "asset_1",
                "variant_asset_id": "asset_2",
                "variant_family_id": "vfam_1",
                "variant_index": 1,
                "operations": [{"type": "caption_safe"}],
                "caption_family_id": "cfam_1",
                "caption_version_id": "cver_1",
                "contentforge_run_id": "run_1",
                "contentforge_preset": "caption_safe_v2",
                "qc_status": "passed",
                "cooldown_days": 9,
                "commit": False,
            },
        ),
        ("parent_variant_inventory", ("may",), {}),
        ("variant_metrics_rollup", ("may",), {}),
        ("concept_for_parent_asset", ("asset_1",), {}),
        ("variant_lineage_for_asset", ("asset_2",), {}),
        ("concept_payload", ({"id": "concept_1"},), {}),
        ("variant_family_payload", ({"id": "vfam_1"},), {}),
        ("variant_lineage_asset_payload", ({"id": "var_1"},), {}),
        ("variant_usage_payload", ({"id": "usage_1"},), {}),
        (
            "variant_rollup_group",
            ([{"variantId": "var_1"}], "variantId", "variantId"),
            {},
        ),
    ]


def test_core_services_delegates_variant_lineage_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeVariantLineage:
        def register_parent_reel(self, *args, **kwargs):
            calls.append(("register_parent_reel", args, kwargs))
            return {
                "schema": "campaign_factory.parent_reel.v1",
                "parentAssetId": args[0],
            }

        def variant_plan(self, *args, **kwargs):
            calls.append(("variant_plan", args, kwargs))
            return {
                "schema": "campaign_factory.variant_plan.v1",
                "parentAssetId": kwargs["parent_asset_id"],
            }

        def generate_variants(self, *args, **kwargs):
            calls.append(("generate_variants", args, kwargs))
            return {
                "schema": "campaign_factory.generate_variants.v1",
                "status": "completed",
            }

        def contentforge_variant_pack_blocked_result(self, *args, **kwargs):
            calls.append(("contentforge_variant_pack_blocked_result", args, kwargs))
            return {
                "schema": "campaign_factory.generate_variants.v1",
                "status": "blocked",
            }

        def register_variant_asset(self, *args, **kwargs):
            calls.append(("register_variant_asset", args, kwargs))
            return {"variantId": "var_1"}

        def parent_variant_inventory(self, *args, **kwargs):
            calls.append(("parent_variant_inventory", args, kwargs))
            return {"schema": "campaign_factory.parent_variant_inventory.v1"}

        def variant_metrics_rollup(self, *args, **kwargs):
            calls.append(("variant_metrics_rollup", args, kwargs))
            return {"schema": "campaign_factory.variant_metrics_rollup.v1"}

        def concept_for_parent_asset(self, *args, **kwargs):
            calls.append(("concept_for_parent_asset", args, kwargs))
            return {"conceptId": "concept_1"}

        def variant_lineage_for_asset(self, *args, **kwargs):
            calls.append(("variant_lineage_for_asset", args, kwargs))
            return {"variantId": "var_1"}

        def concept_payload(self, *args, **kwargs):
            calls.append(("concept_payload", args, kwargs))
            return {"conceptId": "concept_1"}

        def variant_family_payload(self, *args, **kwargs):
            calls.append(("variant_family_payload", args, kwargs))
            return {"variantFamilyId": "vfam_1"}

        def variant_lineage_asset_payload(self, *args, **kwargs):
            calls.append(("variant_lineage_asset_payload", args, kwargs))
            return {"variantId": "var_1"}

        def variant_usage_payload(self, *args, **kwargs):
            calls.append(("variant_usage_payload", args, kwargs))
            return {"id": "usage_1"}

        def variant_rollup_group(self, *args, **kwargs):
            calls.append(("variant_rollup_group", args, kwargs))
            return [{"variantId": "var_1"}]

    services.variant_lineage = FakeVariantLineage()
    error = TimeoutError("boom")

    assert services.register_parent_reel(
        "asset_1", operator="tester", status="active", metadata={"ok": True}
    ) == {
        "schema": "campaign_factory.parent_reel.v1",
        "parentAssetId": "asset_1",
    }
    assert services.variant_plan(
        parent_asset_id="asset_1",
        caption_version_id="cver_1",
        count=2,
        contentforge_preset="caption_safe_v2",
        cooldown_days=7,
    ) == {"schema": "campaign_factory.variant_plan.v1", "parentAssetId": "asset_1"}
    assert services.generate_variants(
        parent_asset_id="asset_1",
        caption_version_id="cver_1",
        count=2,
        contentforge_preset="caption_safe_v2",
        contentforge_base_url="http://contentforge.test",
        source_media_path="/tmp/source.mp4",
        contentforge_timeout_seconds=3,
    ) == {"schema": "campaign_factory.generate_variants.v1", "status": "completed"}
    assert services.contentforge_variant_pack_blocked_result(
        plan={"parentAssetId": "asset_1"},
        blocking_reason="timeout",
        endpoint="http://contentforge.test/api/variant-pack/jobs",
        staged_source="source.mp4",
        timeout_seconds=3,
        error=error,
        extra={"runId": "run_1"},
    ) == {"schema": "campaign_factory.generate_variants.v1", "status": "blocked"}
    assert services.register_variant_asset(
        parent_asset_id="asset_1",
        variant_asset_id="asset_2",
        variant_family_id="vfam_1",
        variant_index=1,
        operations=[{"type": "caption_safe"}],
        caption_family_id="cfam_1",
        caption_version_id="cver_1",
        contentforge_run_id="run_1",
        contentforge_preset="caption_safe_v2",
        qc_status="passed",
        cooldown_days=9,
        commit=False,
    ) == {"variantId": "var_1"}
    assert services.parent_variant_inventory("may") == {
        "schema": "campaign_factory.parent_variant_inventory.v1"
    }
    assert services.variant_metrics_rollup("may") == {
        "schema": "campaign_factory.variant_metrics_rollup.v1"
    }
    assert services.concept_for_parent_asset("asset_1") == {"conceptId": "concept_1"}
    assert services.variant_lineage_for_asset("asset_2") == {"variantId": "var_1"}
    assert services.concept_payload({"id": "concept_1"}) == {"conceptId": "concept_1"}
    assert services.variant_family_payload({"id": "vfam_1"}) == {
        "variantFamilyId": "vfam_1"
    }
    assert services.variant_lineage_asset_payload({"id": "var_1"}) == {
        "variantId": "var_1"
    }
    assert services.variant_usage_payload({"id": "usage_1"}) == {"id": "usage_1"}
    assert services.variant_rollup_group(
        [{"variantId": "var_1"}], "variantId", "variantId"
    ) == [{"variantId": "var_1"}]

    assert calls == [
        (
            "register_parent_reel",
            ("asset_1",),
            {"operator": "tester", "status": "active", "metadata": {"ok": True}},
        ),
        (
            "variant_plan",
            (),
            {
                "parent_asset_id": "asset_1",
                "caption_version_id": "cver_1",
                "count": 2,
                "contentforge_preset": "caption_safe_v2",
                "cooldown_days": 7,
            },
        ),
        (
            "generate_variants",
            (),
            {
                "parent_asset_id": "asset_1",
                "caption_version_id": "cver_1",
                "count": 2,
                "contentforge_preset": "caption_safe_v2",
                "contentforge_base_url": "http://contentforge.test",
                "source_media_path": "/tmp/source.mp4",
                "contentforge_timeout_seconds": 3,
            },
        ),
        (
            "contentforge_variant_pack_blocked_result",
            (),
            {
                "plan": {"parentAssetId": "asset_1"},
                "blocking_reason": "timeout",
                "endpoint": "http://contentforge.test/api/variant-pack/jobs",
                "staged_source": "source.mp4",
                "timeout_seconds": 3,
                "error": error,
                "extra": {"runId": "run_1"},
            },
        ),
        (
            "register_variant_asset",
            (),
            {
                "parent_asset_id": "asset_1",
                "variant_asset_id": "asset_2",
                "variant_family_id": "vfam_1",
                "variant_index": 1,
                "operations": [{"type": "caption_safe"}],
                "caption_family_id": "cfam_1",
                "caption_version_id": "cver_1",
                "contentforge_run_id": "run_1",
                "contentforge_preset": "caption_safe_v2",
                "qc_status": "passed",
                "cooldown_days": 9,
                "commit": False,
            },
        ),
        ("parent_variant_inventory", ("may",), {}),
        ("variant_metrics_rollup", ("may",), {}),
        ("concept_for_parent_asset", ("asset_1",), {}),
        ("variant_lineage_for_asset", ("asset_2",), {}),
        ("concept_payload", ({"id": "concept_1"},), {}),
        ("variant_family_payload", ({"id": "vfam_1"},), {}),
        ("variant_lineage_asset_payload", ({"id": "var_1"},), {}),
        ("variant_usage_payload", ({"id": "usage_1"},), {}),
        (
            "variant_rollup_group",
            ([{"variantId": "var_1"}], "variantId", "variantId"),
            {},
        ),
    ]


def test_campaign_factory_delegates_publishability_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def local_export_readiness(self, *args, **kwargs):
            calls.append(("local_export_readiness", args, kwargs))
            return {"state": "ready"}

        def latest_audit_for_asset(self, *args, **kwargs):
            calls.append(("latest_audit_for_asset", args, kwargs))
            return {"id": args[0], "overallVerdict": "pass"}

        def active_quarantine_for_asset(self, *args, **kwargs):
            calls.append(("active_quarantine_for_asset", args, kwargs))
            return {"rendered_asset_id": args[0]}

        def quarantine_asset(self, *args, **kwargs):
            calls.append(("quarantine_asset", args, kwargs))
            return {"id": "qasset_1", "rendered_asset_id": args[0]}

        def verification_id(self, *args, **kwargs):
            calls.append(("verification_id", args, kwargs))
            return "proof_abc123"

        def text_hash(self, *args, **kwargs):
            calls.append(("text_hash", args, kwargs))
            return "hash_caption"

        def instagram_post_caption_for_asset(self, *args, **kwargs):
            calls.append(("instagram_post_caption_for_asset", args, kwargs))
            return {"instagram_post_caption": "caption"}

        def caption_lineage_sidecar(self, *args, **kwargs):
            calls.append(("caption_lineage_sidecar", args, kwargs))
            return {"captionOutcomeContext": {}}

        def explain_publishability(self, *args, **kwargs):
            calls.append(("explain_publishability", args, kwargs))
            return {"schema": "campaign_factory.publishability_check.v1"}

        def capture_publishability_rejection_evidence(self, *args, **kwargs):
            calls.append(("capture_publishability_rejection_evidence", args, kwargs))
            return {"schema": "campaign_factory.rejection_evidence_capture.v1"}

        def capture_publishability_rejection_evidence_from_result(
            self, *args, **kwargs
        ):
            calls.append(
                ("capture_publishability_rejection_evidence_from_result", args, kwargs)
            )
            return {"capturedCount": 1}

        def capture_discoverability_gate_rejection_evidence(self, *args, **kwargs):
            calls.append(
                ("capture_discoverability_gate_rejection_evidence", args, kwargs)
            )
            return {
                "schema": "campaign_factory.discoverability_gate_rejection_capture.v1"
            }

        def record_proof_run(self, *args, **kwargs):
            calls.append(("record_proof_run", args, kwargs))
            return {"id": "proof_1"}

        def publishability_discoverability_fields(self, *args, **kwargs):
            calls.append(("publishability_discoverability_fields", args, kwargs))
            return [("asset_caption", "caption")]

        def instagram_post_caption_quality(self, *args, **kwargs):
            calls.append(("instagram_post_caption_quality", args, kwargs))
            return {"passed": True}

        def caption_quality_repair_plan(self, *args, **kwargs):
            calls.append(("caption_quality_repair_plan", args, kwargs))
            return {"schema": "campaign_factory.caption_quality_repair_plan.v1"}

        def caption_quality_recovery_class(self, *args, **kwargs):
            calls.append(("caption_quality_recovery_class", args, kwargs))
            return "recoverableByCaptionRewrite"

        def suggest_simple_instagram_post_caption(self, *args, **kwargs):
            calls.append(("suggest_simple_instagram_post_caption", args, kwargs))
            return "Simple caption."

        def publishability_check(self, *args, **kwargs):
            calls.append(("publishability_check", args, kwargs))
            return {"decision": "pass"}

    factory.services = FakeServices()

    assert factory._local_export_readiness(
        {"id": "asset_1", "review_state": "approved"}, {"overallVerdict": "pass"}
    ) == {"state": "ready"}
    assert factory._latest_audit_for_asset("asset_1") == {
        "id": "asset_1",
        "overallVerdict": "pass",
    }
    assert factory._active_quarantine_for_asset("asset_1") == {
        "rendered_asset_id": "asset_1"
    }
    assert factory.quarantine_asset(
        "asset_1",
        reason="operator_quarantine",
        root_cause="qc_failure",
        blocking_reason="caption_quality",
        distribution_plan_id="plan_1",
        threadsdash_post_id="post_1",
        created_by="operator",
        metadata={"source": "test"},
        commit=False,
    ) == {"id": "qasset_1", "rendered_asset_id": "asset_1"}
    assert factory._verification_id("proof", "asset_1") == "proof_abc123"
    assert factory._text_hash("Caption") == "hash_caption"
    assert factory._instagram_post_caption_for_asset(
        {"id": "asset_1"}, {}, distribution_plan={"id": "plan_1"}
    ) == {
        "instagram_post_caption": "caption",
    }
    assert factory._caption_lineage_sidecar("/tmp/out.mp4") == {
        "captionOutcomeContext": {}
    }
    assert factory.explain_publishability("asset_1", distribution_plan_id="plan_1") == {
        "schema": "campaign_factory.publishability_check.v1",
    }
    assert factory.capture_publishability_rejection_evidence("asset_1") == {
        "schema": "campaign_factory.rejection_evidence_capture.v1",
    }
    assert factory._capture_publishability_rejection_evidence_from_result(
        "asset_1", {"decision": "blocked"}, commit=False
    ) == {
        "capturedCount": 1,
    }
    assert factory._capture_discoverability_gate_rejection_evidence(
        gate_result={"violations": []},
        failed_stage="pre_render",
        campaign_id="camp_1",
        source_asset_id="src_1",
        rendered_asset_id="asset_1",
        content_surface="reel",
        commit=False,
    ) == {"schema": "campaign_factory.discoverability_gate_rejection_capture.v1"}
    assert factory.record_proof_run(
        campaign_id="camp_1",
        rendered_asset_id="asset_1",
        distribution_plan_id="plan_1",
        threadsdash_draft_id="draft_1",
        threadsdash_post_id="post_1",
        status="passed",
        current_state="publishable_candidate",
        blocking_reason=None,
        root_cause=None,
        metrics_eligible=True,
        metadata={"ok": True},
        proof_run_id="proof_1",
        commit=False,
    ) == {"id": "proof_1"}
    assert factory._publishability_discoverability_fields(
        asset={"caption": "caption"},
        caption_text="caption",
        caption_context={},
        post_caption={},
    ) == [("asset_caption", "caption")]
    assert factory._instagram_post_caption_quality(
        {"instagram_post_caption": "caption"}
    ) == {"passed": True}
    assert factory.caption_quality_repair_plan(
        creator="Stacey", campaign_slug="daily", content_surface="reel", limit=1
    ) == {
        "schema": "campaign_factory.caption_quality_repair_plan.v1",
    }
    assert (
        factory._caption_quality_recovery_class(["instagram_post_caption_too_long"])
        == "recoverableByCaptionRewrite"
    )
    assert (
        factory._suggest_simple_instagram_post_caption(
            asset_id="asset_1",
            current_caption="old caption",
            burned_caption="burned caption",
        )
        == "Simple caption."
    )
    assert factory._publishability_check(
        {"id": "asset_1"},
        {"overallVerdict": "pass"},
        distribution_plan={"id": "plan_1"},
    ) == {
        "decision": "pass",
    }

    assert calls == [
        (
            "local_export_readiness",
            ({"id": "asset_1", "review_state": "approved"}, {"overallVerdict": "pass"}),
            {},
        ),
        ("latest_audit_for_asset", ("asset_1",), {}),
        ("active_quarantine_for_asset", ("asset_1",), {}),
        (
            "quarantine_asset",
            ("asset_1",),
            {
                "reason": "operator_quarantine",
                "root_cause": "qc_failure",
                "blocking_reason": "caption_quality",
                "distribution_plan_id": "plan_1",
                "threadsdash_post_id": "post_1",
                "created_by": "operator",
                "metadata": {"source": "test"},
                "commit": False,
            },
        ),
        ("verification_id", ("proof", "asset_1"), {}),
        ("text_hash", ("Caption",), {}),
        (
            "instagram_post_caption_for_asset",
            ({"id": "asset_1"}, {}),
            {"distribution_plan": {"id": "plan_1"}},
        ),
        ("caption_lineage_sidecar", ("/tmp/out.mp4",), {}),
        ("explain_publishability", ("asset_1",), {"distribution_plan_id": "plan_1"}),
        ("capture_publishability_rejection_evidence", ("asset_1",), {}),
        (
            "capture_publishability_rejection_evidence_from_result",
            ("asset_1", {"decision": "blocked"}),
            {"commit": False},
        ),
        (
            "capture_discoverability_gate_rejection_evidence",
            (),
            {
                "gate_result": {"violations": []},
                "failed_stage": "pre_render",
                "campaign_id": "camp_1",
                "source_asset_id": "src_1",
                "rendered_asset_id": "asset_1",
                "content_surface": "reel",
                "commit": False,
            },
        ),
        (
            "record_proof_run",
            (),
            {
                "campaign_id": "camp_1",
                "rendered_asset_id": "asset_1",
                "distribution_plan_id": "plan_1",
                "threadsdash_draft_id": "draft_1",
                "threadsdash_post_id": "post_1",
                "status": "passed",
                "current_state": "publishable_candidate",
                "blocking_reason": None,
                "root_cause": None,
                "metrics_eligible": True,
                "metadata": {"ok": True},
                "proof_run_id": "proof_1",
                "commit": False,
            },
        ),
        (
            "publishability_discoverability_fields",
            (),
            {
                "asset": {"caption": "caption"},
                "caption_text": "caption",
                "caption_context": {},
                "post_caption": {},
            },
        ),
        (
            "instagram_post_caption_quality",
            ({"instagram_post_caption": "caption"},),
            {},
        ),
        (
            "caption_quality_repair_plan",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "daily",
                "content_surface": "reel",
                "limit": 1,
            },
        ),
        ("caption_quality_recovery_class", (["instagram_post_caption_too_long"],), {}),
        (
            "suggest_simple_instagram_post_caption",
            (),
            {
                "asset_id": "asset_1",
                "current_caption": "old caption",
                "burned_caption": "burned caption",
            },
        ),
        (
            "publishability_check",
            ({"id": "asset_1"}, {"overallVerdict": "pass"}),
            {"distribution_plan": {"id": "plan_1"}},
        ),
    ]


def test_core_services_delegates_publishability_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakePublishability:
        def local_export_readiness(self, *args, **kwargs):
            calls.append(("local_export_readiness", args, kwargs))
            return {"state": "ready"}

        def latest_audit_for_asset(self, *args, **kwargs):
            calls.append(("latest_audit_for_asset", args, kwargs))
            return {"id": args[0], "overallVerdict": "pass"}

        def active_quarantine_for_asset(self, *args, **kwargs):
            calls.append(("active_quarantine_for_asset", args, kwargs))
            return {"rendered_asset_id": args[0]}

        def quarantine_asset(self, *args, **kwargs):
            calls.append(("quarantine_asset", args, kwargs))
            return {"id": "qasset_1", "rendered_asset_id": args[0]}

        def verification_id(self, *args, **kwargs):
            calls.append(("verification_id", args, kwargs))
            return "proof_abc123"

        def text_hash(self, *args, **kwargs):
            calls.append(("text_hash", args, kwargs))
            return "hash_caption"

        def instagram_post_caption_for_asset(self, *args, **kwargs):
            calls.append(("instagram_post_caption_for_asset", args, kwargs))
            return {"instagram_post_caption": "caption"}

        def caption_lineage_sidecar(self, *args, **kwargs):
            calls.append(("caption_lineage_sidecar", args, kwargs))
            return {"captionOutcomeContext": {}}

        def explain_publishability(self, *args, **kwargs):
            calls.append(("explain_publishability", args, kwargs))
            return {"schema": "campaign_factory.publishability_check.v1"}

        def capture_publishability_rejection_evidence(self, *args, **kwargs):
            calls.append(("capture_publishability_rejection_evidence", args, kwargs))
            return {"schema": "campaign_factory.rejection_evidence_capture.v1"}

        def capture_publishability_rejection_evidence_from_result(
            self, *args, **kwargs
        ):
            calls.append(
                ("capture_publishability_rejection_evidence_from_result", args, kwargs)
            )
            return {"capturedCount": 1}

        def capture_discoverability_gate_rejection_evidence(self, *args, **kwargs):
            calls.append(
                ("capture_discoverability_gate_rejection_evidence", args, kwargs)
            )
            return {
                "schema": "campaign_factory.discoverability_gate_rejection_capture.v1"
            }

        def record_proof_run(self, *args, **kwargs):
            calls.append(("record_proof_run", args, kwargs))
            return {"id": "proof_1"}

        def publishability_discoverability_fields(self, *args, **kwargs):
            calls.append(("publishability_discoverability_fields", args, kwargs))
            return [("asset_caption", "caption")]

        def instagram_post_caption_quality(self, *args, **kwargs):
            calls.append(("instagram_post_caption_quality", args, kwargs))
            return {"passed": True}

        def caption_quality_repair_plan(self, *args, **kwargs):
            calls.append(("caption_quality_repair_plan", args, kwargs))
            return {"schema": "campaign_factory.caption_quality_repair_plan.v1"}

        def caption_quality_recovery_class(self, *args, **kwargs):
            calls.append(("caption_quality_recovery_class", args, kwargs))
            return "recoverableByCaptionRewrite"

        def suggest_simple_instagram_post_caption(self, *args, **kwargs):
            calls.append(("suggest_simple_instagram_post_caption", args, kwargs))
            return "Simple caption."

        def publishability_check(self, *args, **kwargs):
            calls.append(("publishability_check", args, kwargs))
            return {"decision": "pass"}

    services.publishability = FakePublishability()

    assert services.local_export_readiness({"id": "asset_1"}, None) == {
        "state": "ready"
    }
    assert services.latest_audit_for_asset("asset_1") == {
        "id": "asset_1",
        "overallVerdict": "pass",
    }
    assert services.active_quarantine_for_asset("asset_1") == {
        "rendered_asset_id": "asset_1"
    }
    assert services.quarantine_asset(
        "asset_1",
        reason="operator_quarantine",
        root_cause="qc_failure",
        blocking_reason="caption_quality",
        distribution_plan_id="plan_1",
        threadsdash_post_id="post_1",
        created_by="operator",
        metadata={"source": "test"},
        commit=False,
    ) == {"id": "qasset_1", "rendered_asset_id": "asset_1"}
    assert services.verification_id("proof", "asset_1") == "proof_abc123"
    assert services.text_hash("Caption") == "hash_caption"
    assert services.instagram_post_caption_for_asset(
        {"id": "asset_1"}, {}, distribution_plan={"id": "plan_1"}
    ) == {
        "instagram_post_caption": "caption",
    }
    assert services.caption_lineage_sidecar("/tmp/out.mp4") == {
        "captionOutcomeContext": {}
    }
    assert services.explain_publishability(
        "asset_1", distribution_plan_id="plan_1"
    ) == {
        "schema": "campaign_factory.publishability_check.v1",
    }
    assert services.capture_publishability_rejection_evidence("asset_1") == {
        "schema": "campaign_factory.rejection_evidence_capture.v1",
    }
    assert services.capture_publishability_rejection_evidence_from_result(
        "asset_1", {"decision": "blocked"}, commit=False
    ) == {
        "capturedCount": 1,
    }
    assert services.capture_discoverability_gate_rejection_evidence(
        gate_result={"violations": []},
        failed_stage="pre_render",
        commit=False,
    ) == {"schema": "campaign_factory.discoverability_gate_rejection_capture.v1"}
    assert services.record_proof_run(
        campaign_id="camp_1", rendered_asset_id="asset_1"
    ) == {"id": "proof_1"}
    assert services.publishability_discoverability_fields(
        asset={"caption": "caption"},
        caption_text="caption",
        caption_context={},
        post_caption={},
    ) == [("asset_caption", "caption")]
    assert services.instagram_post_caption_quality(
        {"instagram_post_caption": "caption"}
    ) == {"passed": True}
    assert services.caption_quality_repair_plan(creator="Stacey") == {
        "schema": "campaign_factory.caption_quality_repair_plan.v1",
    }
    assert (
        services.caption_quality_recovery_class(["instagram_post_caption_too_long"])
        == "recoverableByCaptionRewrite"
    )
    assert (
        services.suggest_simple_instagram_post_caption(
            asset_id="asset_1",
            current_caption="old caption",
            burned_caption="burned caption",
        )
        == "Simple caption."
    )
    assert services.publishability_check(
        {"id": "asset_1"}, distribution_plan={"id": "plan_1"}
    ) == {"decision": "pass"}

    assert calls == [
        ("local_export_readiness", ({"id": "asset_1"}, None), {}),
        ("latest_audit_for_asset", ("asset_1",), {}),
        ("active_quarantine_for_asset", ("asset_1",), {}),
        (
            "quarantine_asset",
            ("asset_1",),
            {
                "reason": "operator_quarantine",
                "root_cause": "qc_failure",
                "blocking_reason": "caption_quality",
                "distribution_plan_id": "plan_1",
                "threadsdash_post_id": "post_1",
                "created_by": "operator",
                "metadata": {"source": "test"},
                "commit": False,
            },
        ),
        ("verification_id", ("proof", "asset_1"), {}),
        ("text_hash", ("Caption",), {}),
        (
            "instagram_post_caption_for_asset",
            ({"id": "asset_1"}, {}),
            {"distribution_plan": {"id": "plan_1"}},
        ),
        ("caption_lineage_sidecar", ("/tmp/out.mp4",), {}),
        ("explain_publishability", ("asset_1",), {"distribution_plan_id": "plan_1"}),
        ("capture_publishability_rejection_evidence", ("asset_1",), {}),
        (
            "capture_publishability_rejection_evidence_from_result",
            ("asset_1", {"decision": "blocked"}),
            {"commit": False},
        ),
        (
            "capture_discoverability_gate_rejection_evidence",
            (),
            {
                "gate_result": {"violations": []},
                "failed_stage": "pre_render",
                "commit": False,
            },
        ),
        (
            "record_proof_run",
            (),
            {
                "campaign_id": "camp_1",
                "rendered_asset_id": "asset_1",
                "distribution_plan_id": None,
                "threadsdash_draft_id": None,
                "threadsdash_post_id": None,
                "status": "started",
                "current_state": "creative_approved",
                "blocking_reason": None,
                "root_cause": None,
                "metrics_eligible": False,
                "metadata": None,
                "proof_run_id": None,
                "commit": True,
            },
        ),
        (
            "publishability_discoverability_fields",
            (),
            {
                "asset": {"caption": "caption"},
                "caption_text": "caption",
                "caption_context": {},
                "post_caption": {},
            },
        ),
        (
            "instagram_post_caption_quality",
            ({"instagram_post_caption": "caption"},),
            {},
        ),
        (
            "caption_quality_repair_plan",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": None,
                "content_surface": None,
                "limit": 200,
            },
        ),
        ("caption_quality_recovery_class", (["instagram_post_caption_too_long"],), {}),
        (
            "suggest_simple_instagram_post_caption",
            (),
            {
                "asset_id": "asset_1",
                "current_caption": "old caption",
                "burned_caption": "burned caption",
            },
        ),
        (
            "publishability_check",
            ({"id": "asset_1"}, None),
            {"distribution_plan": {"id": "plan_1"}},
        ),
    ]


def test_campaign_factory_delegates_surface_requirement_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def account_surface_obligations_plan(self, *args, **kwargs):
            calls.append(("account_surface_obligations_plan", args, kwargs))
            return {"schema": "campaign_factory.account_surface_obligations_plan.v1"}

        def account_content_needs(self, *args, **kwargs):
            calls.append(("account_content_needs", args, kwargs))
            return {"schema": "campaign_factory.account_content_needs.v1"}

        def account_surface_status(self, *args, **kwargs):
            calls.append(("account_surface_status", args, kwargs))
            return {"schema": "campaign_factory.account_surface_status.v1"}

        def creator_content_needs(self, *args, **kwargs):
            calls.append(("creator_content_needs", args, kwargs))
            return {"schema": "campaign_factory.creator_content_needs.v1"}

        def surface_gap_report(self, *args, **kwargs):
            calls.append(("surface_gap_report", args, kwargs))
            return {"schema": "campaign_factory.surface_gap_report.v1"}

        def build_surface_status(self, *args, **kwargs):
            calls.append(("build_surface_status", args, kwargs))
            return {"schema": "campaign_factory.surface_status.v1"}

        def account_content_requirement_rows(self, *args, **kwargs):
            calls.append(("account_content_requirement_rows", args, kwargs))
            return [{"id": "req_1"}]

        def account_row_for_requirement_account(self, *args, **kwargs):
            calls.append(("account_row_for_requirement_account", args, kwargs))
            return {"id": "acct_1"}

        def content_obligation_for_requirement(self, *args, **kwargs):
            calls.append(("content_obligation_for_requirement", args, kwargs))
            return {"surface": "story"}

        def required_content_count(self, *args, **kwargs):
            calls.append(("required_content_count", args, kwargs))
            return 2

        def empty_surface_totals(self, *args, **kwargs):
            calls.append(("empty_surface_totals", args, kwargs))
            return {"story": {"required": 0}}

        def add_obligation_to_totals(self, *args, **kwargs):
            calls.append(("add_obligation_to_totals", args, kwargs))

        def requirement_active_on_date(self, *args, **kwargs):
            calls.append(("requirement_active_on_date", args, kwargs))
            return True

        def surface_scheduled_count(self, *args, **kwargs):
            calls.append(("surface_scheduled_count", args, kwargs))
            return 1

        def surface_completed_count(self, *args, **kwargs):
            calls.append(("surface_completed_count", args, kwargs))
            return 0

        def last_surface_posted_at(self, *args, **kwargs):
            calls.append(("last_surface_posted_at", args, kwargs))
            return "2026-06-05T12:00:00+00:00"

        def surface_scheduled_for_account(self, *args, **kwargs):
            calls.append(("surface_scheduled_for_account", args, kwargs))
            return True

        def surface_completed_for_account(self, *args, **kwargs):
            calls.append(("surface_completed_for_account", args, kwargs))
            return False

    factory.services = FakeServices()

    assert factory.account_surface_obligations_plan(
        creator="Stacey", date="2026-06-06"
    ) == {
        "schema": "campaign_factory.account_surface_obligations_plan.v1",
    }
    assert factory.account_content_needs(
        account_id="acct_1", creator="Stacey", date="2026-06-06"
    ) == {
        "schema": "campaign_factory.account_content_needs.v1",
    }
    assert factory.account_surface_status(account_id="acct_1", date="2026-06-06") == {
        "schema": "campaign_factory.account_surface_status.v1",
    }
    assert factory.creator_content_needs(creator="Stacey", date="2026-06-06") == {
        "schema": "campaign_factory.creator_content_needs.v1",
    }
    assert factory.surface_gap_report(creator="Stacey", date="2026-06-06") == {
        "schema": "campaign_factory.surface_gap_report.v1",
    }
    assert factory._build_surface_status(creator="Stacey", date="2026-06-06") == {
        "schema": "campaign_factory.surface_status.v1",
    }
    assert factory._account_content_requirement_rows(creator="Stacey") == [
        {"id": "req_1"}
    ]
    assert factory._account_row_for_requirement_account("acct_1") == {"id": "acct_1"}
    assert factory._content_obligation_for_requirement(
        {"id": "req_1"}, "2026-06-06"
    ) == {"surface": "story"}
    assert factory._required_content_count({"id": "req_1"}, "2026-06-06") == 2
    assert factory._empty_surface_totals() == {"story": {"required": 0}}
    totals = {"story": {"required": 0}}
    factory._add_obligation_to_totals(totals, {"surface": "story"})
    assert factory._requirement_active_on_date({"id": "req_1"}, "2026-06-06") is True
    assert (
        factory._surface_scheduled_count("acct_1", "ig_1", "story", "2026-06-06") == 1
    )
    assert (
        factory._surface_completed_count("acct_1", "ig_1", "story", "2026-06-06") == 0
    )
    assert (
        factory._last_surface_posted_at(
            account_id="acct_1",
            instagram_account_id="ig_1",
            surface="story",
            before_date="2026-06-06",
        )
        == "2026-06-05T12:00:00+00:00"
    )
    assert (
        factory._surface_scheduled_for_account("acct_1", "ig_1", "story", "2026-06-06")
        is True
    )
    assert (
        factory._surface_completed_for_account("acct_1", "ig_1", "story", "2026-06-06")
        is False
    )

    assert calls == [
        (
            "account_surface_obligations_plan",
            (),
            {"creator": "Stacey", "date": "2026-06-06"},
        ),
        (
            "account_content_needs",
            (),
            {"account_id": "acct_1", "creator": "Stacey", "date": "2026-06-06"},
        ),
        (
            "account_surface_status",
            (),
            {"account_id": "acct_1", "creator": None, "date": "2026-06-06"},
        ),
        ("creator_content_needs", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("surface_gap_report", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("build_surface_status", (), {"creator": "Stacey", "date": "2026-06-06"}),
        (
            "account_content_requirement_rows",
            (),
            {"creator": "Stacey", "account_id": None},
        ),
        ("account_row_for_requirement_account", ("acct_1",), {}),
        ("content_obligation_for_requirement", ({"id": "req_1"}, "2026-06-06"), {}),
        ("required_content_count", ({"id": "req_1"}, "2026-06-06"), {}),
        ("empty_surface_totals", (), {}),
        ("add_obligation_to_totals", (totals, {"surface": "story"}), {}),
        ("requirement_active_on_date", ({"id": "req_1"}, "2026-06-06"), {}),
        ("surface_scheduled_count", ("acct_1", "ig_1", "story", "2026-06-06"), {}),
        ("surface_completed_count", ("acct_1", "ig_1", "story", "2026-06-06"), {}),
        (
            "last_surface_posted_at",
            (),
            {
                "account_id": "acct_1",
                "instagram_account_id": "ig_1",
                "surface": "story",
                "before_date": "2026-06-06",
            },
        ),
        (
            "surface_scheduled_for_account",
            ("acct_1", "ig_1", "story", "2026-06-06"),
            {},
        ),
        (
            "surface_completed_for_account",
            ("acct_1", "ig_1", "story", "2026-06-06"),
            {},
        ),
    ]


def test_campaign_factory_delegates_creator_os_draft_inventory_gap_to_services() -> (
    None
):
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def creator_os_draft_inventory_gap(self, *args, **kwargs):
            calls.append(("creator_os_draft_inventory_gap", args, kwargs))
            return {"schema": "creator_os.draft_inventory_gap.v1"}

    factory.services = FakeServices()

    assert factory.creator_os_draft_inventory_gap(
        creator="Stacey",
        threadsdash_report={"schema": "threadsdash.report.v1"},
        schedule_plan={"schema": "creator_os.schedule_plan.v1"},
        time_plan={"schema": "creator_os.time_plan.v1"},
        generated_at="2026-06-06T12:00:00Z",
    ) == {"schema": "creator_os.draft_inventory_gap.v1"}
    assert calls == [
        (
            "creator_os_draft_inventory_gap",
            (),
            {
                "creator": "Stacey",
                "threadsdash_report": {"schema": "threadsdash.report.v1"},
                "schedule_plan": {"schema": "creator_os.schedule_plan.v1"},
                "time_plan": {"schema": "creator_os.time_plan.v1"},
                "generated_at": "2026-06-06T12:00:00Z",
            },
        ),
    ]


def test_campaign_factory_delegates_creator_os_daily_plan_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def creator_os_daily_plan(self, *args, **kwargs):
            calls.append(("creator_os_daily_plan", args, kwargs))
            return {"schema": "creator_os.daily_plan.v1"}

    factory.services = FakeServices()

    assert factory.creator_os_daily_plan(
        creators=["Stacey"],
        threadsdash_report={"schema": "threadsdash.report.v1"},
        schedule_plan={"schema": "creator_os.schedule_plan.v1"},
        time_plan={"schema": "creator_os.time_plan.v1"},
        winner_expansion_report={"schema": "winner.report.v1"},
        winner_expansion_plan={"schema": "winner.plan.v1"},
        variant_metrics_rollup={"schema": "variant.rollup.v1"},
        date="2026-06-06",
        generated_at="2026-06-06T12:00:00Z",
    ) == {"schema": "creator_os.daily_plan.v1"}
    assert calls == [
        (
            "creator_os_daily_plan",
            (),
            {
                "creators": ["Stacey"],
                "threadsdash_report": {"schema": "threadsdash.report.v1"},
                "schedule_plan": {"schema": "creator_os.schedule_plan.v1"},
                "time_plan": {"schema": "creator_os.time_plan.v1"},
                "winner_expansion_report": {"schema": "winner.report.v1"},
                "winner_expansion_plan": {"schema": "winner.plan.v1"},
                "variant_metrics_rollup": {"schema": "variant.rollup.v1"},
                "date": "2026-06-06",
                "generated_at": "2026-06-06T12:00:00Z",
            },
        ),
    ]


def test_core_services_delegates_creator_os_daily_plan_to_repository(tmp_path) -> None:
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
        calls = []

        def fake_daily_plan(*args, **kwargs):
            calls.append(("creator_os_daily_plan", args, kwargs))
            return {"schema": "creator_os.daily_plan.v1"}

        factory.services.daily_plan.creator_os_daily_plan = fake_daily_plan

        assert factory.services.creator_os_daily_plan(
            creators=["Stacey"],
            threadsdash_report={"schema": "threadsdash.report.v1"},
            schedule_plan={"schema": "creator_os.schedule_plan.v1"},
            time_plan={"schema": "creator_os.time_plan.v1"},
            winner_expansion_report={"schema": "winner.report.v1"},
            winner_expansion_plan={"schema": "winner.plan.v1"},
            variant_metrics_rollup={"schema": "variant.rollup.v1"},
            date="2026-06-06",
            generated_at="2026-06-06T12:00:00Z",
        ) == {"schema": "creator_os.daily_plan.v1"}
        assert calls == [
            (
                "creator_os_daily_plan",
                (),
                {
                    "creators": ["Stacey"],
                    "threadsdash_report": {"schema": "threadsdash.report.v1"},
                    "schedule_plan": {"schema": "creator_os.schedule_plan.v1"},
                    "time_plan": {"schema": "creator_os.time_plan.v1"},
                    "winner_expansion_report": {"schema": "winner.report.v1"},
                    "winner_expansion_plan": {"schema": "winner.plan.v1"},
                    "variant_metrics_rollup": {"schema": "variant.rollup.v1"},
                    "date": "2026-06-06",
                    "generated_at": "2026-06-06T12:00:00Z",
                },
            ),
        ]
    finally:
        factory.close()


def test_campaign_factory_delegates_recommended_inventory_request_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def recommended_inventory_request_plan(self, *args, **kwargs):
            calls.append(("recommended_inventory_request_plan", args, kwargs))
            return {"schema": "creator_os.recommended_inventory_request_plan.v1"}

        def recommended_inventory_creator_row(self, *args, **kwargs):
            calls.append(("recommended_inventory_creator_row", args, kwargs))
            return {"creator": "Stacey"}

        def recommended_inventory_existing_by_parent(self, *args, **kwargs):
            calls.append(("recommended_inventory_existing_by_parent", args, kwargs))
            return {"asset_parent": 3}

        def recommended_inventory_variant_batch(self, *args, **kwargs):
            calls.append(("recommended_inventory_variant_batch", args, kwargs))
            return {"parentAssetId": "asset_parent", "wouldWrite": False}

        def recommended_inventory_action(self, *args, **kwargs):
            calls.append(("recommended_inventory_action", args, kwargs))
            return "create_more_reels"

    factory.services = FakeServices()
    daily_plan = {"schema": "creator_os.daily_plan.v1"}
    variant_inventory_plan = {"schema": "campaign_factory.variant_inventory_plan.v1"}

    assert factory.recommended_inventory_request_plan(
        creator="Stacey",
        target_count=5,
        daily_plan=daily_plan,
        variant_inventory_plan=variant_inventory_plan,
    ) == {"schema": "creator_os.recommended_inventory_request_plan.v1"}
    assert factory._recommended_inventory_creator_row(daily_plan, "Stacey") == {
        "creator": "Stacey"
    }
    assert factory._recommended_inventory_existing_by_parent(
        variant_inventory_plan
    ) == {"asset_parent": 3}
    assert factory._recommended_inventory_variant_batch(
        "asset_parent", variant_inventory_plan
    ) == {
        "parentAssetId": "asset_parent",
        "wouldWrite": False,
    }
    assert (
        factory._recommended_inventory_action(surface="reel", story_intent="")
        == "create_more_reels"
    )

    assert calls == [
        (
            "recommended_inventory_request_plan",
            (),
            {
                "creator": "Stacey",
                "target_count": 5,
                "daily_plan": daily_plan,
                "variant_inventory_plan": variant_inventory_plan,
            },
        ),
        ("recommended_inventory_creator_row", (daily_plan, "Stacey"), {}),
        ("recommended_inventory_existing_by_parent", (variant_inventory_plan,), {}),
        (
            "recommended_inventory_variant_batch",
            ("asset_parent", variant_inventory_plan),
            {},
        ),
        ("recommended_inventory_action", (), {"surface": "reel", "story_intent": ""}),
    ]


def test_core_services_delegates_recommended_inventory_request_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeRecommendedInventoryRequest:
        def recommended_inventory_request_plan(self, *args, **kwargs):
            calls.append(("recommended_inventory_request_plan", args, kwargs))
            return {"schema": "creator_os.recommended_inventory_request_plan.v1"}

        def recommended_inventory_creator_row(self, *args, **kwargs):
            calls.append(("recommended_inventory_creator_row", args, kwargs))
            return {"creator": "Stacey"}

        def recommended_inventory_existing_by_parent(self, *args, **kwargs):
            calls.append(("recommended_inventory_existing_by_parent", args, kwargs))
            return {"asset_parent": 3}

        def recommended_inventory_variant_batch(self, *args, **kwargs):
            calls.append(("recommended_inventory_variant_batch", args, kwargs))
            return {"parentAssetId": "asset_parent", "wouldWrite": False}

        def recommended_inventory_action(self, *args, **kwargs):
            calls.append(("recommended_inventory_action", args, kwargs))
            return "create_more_reels"

    services.recommended_inventory_request = FakeRecommendedInventoryRequest()
    daily_plan = {"schema": "creator_os.daily_plan.v1"}
    variant_inventory_plan = {"schema": "campaign_factory.variant_inventory_plan.v1"}

    assert services.recommended_inventory_request_plan(
        creator="Stacey",
        target_count=5,
        daily_plan=daily_plan,
        variant_inventory_plan=variant_inventory_plan,
    ) == {"schema": "creator_os.recommended_inventory_request_plan.v1"}
    assert services.recommended_inventory_creator_row(daily_plan, "Stacey") == {
        "creator": "Stacey"
    }
    assert services.recommended_inventory_existing_by_parent(
        variant_inventory_plan
    ) == {"asset_parent": 3}
    assert services.recommended_inventory_variant_batch(
        "asset_parent", variant_inventory_plan
    ) == {
        "parentAssetId": "asset_parent",
        "wouldWrite": False,
    }
    assert (
        services.recommended_inventory_action(surface="reel", story_intent="")
        == "create_more_reels"
    )

    assert calls == [
        (
            "recommended_inventory_request_plan",
            (),
            {
                "creator": "Stacey",
                "target_count": 5,
                "daily_plan": daily_plan,
                "variant_inventory_plan": variant_inventory_plan,
            },
        ),
        ("recommended_inventory_creator_row", (daily_plan, "Stacey"), {}),
        ("recommended_inventory_existing_by_parent", (variant_inventory_plan,), {}),
        (
            "recommended_inventory_variant_batch",
            ("asset_parent", variant_inventory_plan),
            {},
        ),
        ("recommended_inventory_action", (), {"surface": "reel", "story_intent": ""}),
    ]


def test_campaign_factory_delegates_creator_os_recommendation_helpers_to_services() -> (
    None
):
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def creator_os_winner_recommendations(self, *args, **kwargs):
            calls.append(("creator_os_winner_recommendations", args, kwargs))
            return [{"recommendedAction": "generate_more_variants"}]

        def creator_os_winner_action(self, *args, **kwargs):
            calls.append(("creator_os_winner_action", args, kwargs))
            return "generate_more_variants"

        def creator_os_best_rollup_family(self, *args, **kwargs):
            calls.append(("creator_os_best_rollup_family", args, kwargs))
            return {"variantFamilyId": "vfam_1"}

        def creator_os_recommended_inventory(self, *args, **kwargs):
            calls.append(("creator_os_recommended_inventory", args, kwargs))
            return [{"surface": "reel"}]

        def creator_os_lineage_posting_window(self, *args, **kwargs):
            calls.append(("creator_os_lineage_posting_window", args, kwargs))
            return "6pm"

    factory.services = FakeServices()
    winner_report = {"schema": "campaign_factory.winner_expansion_report.v1"}
    winner_plan = {"schema": "campaign_factory.winner_expansion_plan.v1"}
    variant_rollup = {"schema": "campaign_factory.variant_metrics_rollup.v1"}
    pattern = {"lineage": {"postingWindows": ["6pm"]}}

    assert factory._creator_os_winner_recommendations(
        creator="Stacey",
        inventory_shortfall=4,
        variant_available=1,
        winner_expansion_report=winner_report,
        winner_expansion_plan=winner_plan,
        variant_metrics_rollup=variant_rollup,
    ) == [{"recommendedAction": "generate_more_variants"}]
    assert (
        factory._creator_os_winner_action("create_more_variants")
        == "generate_more_variants"
    )
    assert factory._creator_os_best_rollup_family(variant_rollup) == {
        "variantFamilyId": "vfam_1"
    }
    assert factory._creator_os_recommended_inventory(creator="Stacey", limit=3) == [
        {"surface": "reel"}
    ]
    assert factory._creator_os_lineage_posting_window(pattern) == "6pm"

    assert calls == [
        (
            "creator_os_winner_recommendations",
            (),
            {
                "creator": "Stacey",
                "inventory_shortfall": 4,
                "variant_available": 1,
                "winner_expansion_report": winner_report,
                "winner_expansion_plan": winner_plan,
                "variant_metrics_rollup": variant_rollup,
            },
        ),
        ("creator_os_winner_action", ("create_more_variants",), {}),
        ("creator_os_best_rollup_family", (variant_rollup,), {}),
        ("creator_os_recommended_inventory", (), {"creator": "Stacey", "limit": 3}),
        ("creator_os_lineage_posting_window", (pattern,), {}),
    ]


def test_core_services_delegates_creator_os_recommendation_helpers_to_repository() -> (
    None
):
    services = object.__new__(CoreServices)
    calls = []

    class FakeCreatorOSRecommendations:
        def creator_os_winner_recommendations(self, *args, **kwargs):
            calls.append(("creator_os_winner_recommendations", args, kwargs))
            return [{"recommendedAction": "generate_more_variants"}]

        def creator_os_winner_action(self, *args, **kwargs):
            calls.append(("creator_os_winner_action", args, kwargs))
            return "generate_more_variants"

        def creator_os_best_rollup_family(self, *args, **kwargs):
            calls.append(("creator_os_best_rollup_family", args, kwargs))
            return {"variantFamilyId": "vfam_1"}

        def creator_os_recommended_inventory(self, *args, **kwargs):
            calls.append(("creator_os_recommended_inventory", args, kwargs))
            return [{"surface": "reel"}]

        def creator_os_lineage_posting_window(self, *args, **kwargs):
            calls.append(("creator_os_lineage_posting_window", args, kwargs))
            return "6pm"

    services.creator_os_recommendations = FakeCreatorOSRecommendations()
    winner_report = {"schema": "campaign_factory.winner_expansion_report.v1"}
    winner_plan = {"schema": "campaign_factory.winner_expansion_plan.v1"}
    variant_rollup = {"schema": "campaign_factory.variant_metrics_rollup.v1"}
    pattern = {"lineage": {"postingWindows": ["6pm"]}}

    assert services.creator_os_winner_recommendations(
        creator="Stacey",
        inventory_shortfall=4,
        variant_available=1,
        winner_expansion_report=winner_report,
        winner_expansion_plan=winner_plan,
        variant_metrics_rollup=variant_rollup,
    ) == [{"recommendedAction": "generate_more_variants"}]
    assert (
        services.creator_os_winner_action("create_more_variants")
        == "generate_more_variants"
    )
    assert services.creator_os_best_rollup_family(variant_rollup) == {
        "variantFamilyId": "vfam_1"
    }
    assert services.creator_os_recommended_inventory(creator="Stacey", limit=3) == [
        {"surface": "reel"}
    ]
    assert services.creator_os_lineage_posting_window(pattern) == "6pm"

    assert calls == [
        (
            "creator_os_winner_recommendations",
            (),
            {
                "creator": "Stacey",
                "inventory_shortfall": 4,
                "variant_available": 1,
                "winner_expansion_report": winner_report,
                "winner_expansion_plan": winner_plan,
                "variant_metrics_rollup": variant_rollup,
            },
        ),
        ("creator_os_winner_action", ("create_more_variants",), {}),
        ("creator_os_best_rollup_family", (variant_rollup,), {}),
        ("creator_os_recommended_inventory", (), {"creator": "Stacey", "limit": 3}),
        ("creator_os_lineage_posting_window", (pattern,), {}),
    ]


def test_core_services_delegates_creator_os_draft_inventory_gap_to_repository(
    tmp_path,
) -> None:
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
        calls = []

        def fake_gap(*args, **kwargs):
            calls.append(("creator_os_draft_inventory_gap", args, kwargs))
            return {"schema": "creator_os.draft_inventory_gap.v1"}

        factory.services.draft_inventory_gap.creator_os_draft_inventory_gap = fake_gap

        assert factory.services.creator_os_draft_inventory_gap(
            creator="Stacey",
            threadsdash_report={"schema": "threadsdash.report.v1"},
            schedule_plan={"schema": "creator_os.schedule_plan.v1"},
            time_plan={"schema": "creator_os.time_plan.v1"},
            generated_at="2026-06-06T12:00:00Z",
        ) == {"schema": "creator_os.draft_inventory_gap.v1"}
        assert calls == [
            (
                "creator_os_draft_inventory_gap",
                (),
                {
                    "creator": "Stacey",
                    "threadsdash_report": {"schema": "threadsdash.report.v1"},
                    "schedule_plan": {"schema": "creator_os.schedule_plan.v1"},
                    "time_plan": {"schema": "creator_os.time_plan.v1"},
                    "generated_at": "2026-06-06T12:00:00Z",
                },
            ),
        ]
    finally:
        factory.close()


def test_core_services_delegates_creator_os_draft_helpers_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeCreatorOSDrafts:
        def creator_os_local_schedule_safe_assets(self, *args, **kwargs):
            calls.append(("creator_os_local_schedule_safe_assets", args, kwargs))
            return [{"renderedAssetId": "asset_1"}]

        def creator_os_target_date(self, *args, **kwargs):
            calls.append(("creator_os_target_date", args, kwargs))
            return "2026-06-06"

        def creator_os_account_surface_status(self, *args, **kwargs):
            calls.append(("creator_os_account_surface_status", args, kwargs))
            return {"reel": {"needed": True}}

        def creator_os_surface_summary_for_creator(self, *args, **kwargs):
            calls.append(("creator_os_surface_summary_for_creator", args, kwargs))
            return {"accountsNeedingReels": 1, "wouldWrite": False}

        def creator_os_gap_blocking_reason(self, *args, **kwargs):
            calls.append(("creator_os_gap_blocking_reason", args, kwargs))
            return "missing_handoff_manifest"

        def creator_os_draft_items(self, *args, **kwargs):
            calls.append(("creator_os_draft_items", args, kwargs))
            return [{"postId": "post_1"}]

        def creator_os_draft_has_instagram_post_caption(self, *args, **kwargs):
            calls.append(("creator_os_draft_has_instagram_post_caption", args, kwargs))
            return True

        def creator_os_draft_exclusion_reason(self, *args, **kwargs):
            calls.append(("creator_os_draft_exclusion_reason", args, kwargs))
            return ""

        def creator_os_draft_exclusion_counts(self, *args, **kwargs):
            calls.append(("creator_os_draft_exclusion_counts", args, kwargs))
            return {"missingInstagramPostCaption": 1}

        def creator_os_schedule_safe_drafts(self, *args, **kwargs):
            calls.append(("creator_os_schedule_safe_drafts", args, kwargs))
            return [{"postId": "post_1"}]

        def creator_os_execution_draft_blockers(self, *args, **kwargs):
            calls.append(("creator_os_execution_draft_blockers", args, kwargs))
            return ["missing_campaign_factory_asset_id"]

        def creator_os_explicit_false(self, *args, **kwargs):
            calls.append(("creator_os_explicit_false", args, kwargs))
            return True

        def creator_os_inventory_for_creator(self, *args, **kwargs):
            calls.append(("creator_os_inventory_for_creator", args, kwargs))
            return {"validatedDraftsAvailable": 1, "variantDraftsAvailable": 1}

        def creator_os_blocked_account_breakdown(self, *args, **kwargs):
            calls.append(("creator_os_blocked_account_breakdown", args, kwargs))
            return {"restricted": 1}

        def creator_os_manager_decision(self, *args, **kwargs):
            calls.append(("creator_os_manager_decision", args, kwargs))
            return {"managerDecision": "ready_to_schedule", "managerReason": "ready"}

        def creator_os_account_state(self, *args, **kwargs):
            calls.append(("creator_os_account_state", args, kwargs))
            return "safe"

        def creator_os_post_time(self, *args, **kwargs):
            calls.append(("creator_os_post_time", args, kwargs))
            return "2026-06-06T12:00:00Z"

        def creator_os_recommended_post_count(self, *args, **kwargs):
            calls.append(("creator_os_recommended_post_count", args, kwargs))
            return 1

        def recommended_story_intent_for_date(self, *args, **kwargs):
            calls.append(("recommended_story_intent_for_date", args, kwargs))
            return "reel_teaser"

        def recommended_story_style_for_intent(self, *args, **kwargs):
            calls.append(("recommended_story_style_for_intent", args, kwargs))
            return "raw_phone"

    services.creator_os_drafts = FakeCreatorOSDrafts()

    draft = {"postId": "post_1"}
    planner_inputs = [{"items": [draft]}]
    assert services.creator_os_local_schedule_safe_assets("Stacey") == [
        {"renderedAssetId": "asset_1"}
    ]
    assert services.creator_os_target_date(date="2026-06-06T12:00:00Z") == "2026-06-06"
    assert services.creator_os_account_surface_status(
        {"surfaceStatus": {}}, reel_needed=True
    ) == {"reel": {"needed": True}}
    assert services.creator_os_surface_summary_for_creator(
        creator="Stacey",
        date="2026-06-06",
        report={},
        creator_accounts=[],
        draft_items=[draft],
    ) == {"accountsNeedingReels": 1, "wouldWrite": False}
    assert (
        services.creator_os_gap_blocking_reason("missingHandoffManifest", [], draft)
        == "missing_handoff_manifest"
    )
    assert services.creator_os_draft_items(planner_inputs) == [{"postId": "post_1"}]
    assert services.creator_os_draft_has_instagram_post_caption(draft) is True
    assert services.creator_os_draft_exclusion_reason(draft) == ""
    assert services.creator_os_draft_exclusion_counts("Stacey", [draft]) == {
        "missingInstagramPostCaption": 1
    }
    assert services.creator_os_schedule_safe_drafts("Stacey", [draft]) == [
        {"postId": "post_1"}
    ]
    assert services.creator_os_execution_draft_blockers("Stacey", [draft]) == [
        "missing_campaign_factory_asset_id"
    ]
    assert services.creator_os_explicit_false(draft, "burnedCaptionTextPresent") is True
    assert services.creator_os_inventory_for_creator(
        "Stacey", planner_inputs, [draft]
    ) == {
        "validatedDraftsAvailable": 1,
        "variantDraftsAvailable": 1,
    }
    assert services.creator_os_blocked_account_breakdown(
        [{"blockedReason": "restricted"}]
    ) == {"restricted": 1}
    assert services.creator_os_manager_decision(
        safe_accounts=1,
        needs_posts=1,
        validated_available=1,
        shortfall=0,
        missed_dispatches=[],
        winner_recommendations=[],
    ) == {"managerDecision": "ready_to_schedule", "managerReason": "ready"}
    assert (
        services.creator_os_account_state({"bucket": "safe_to_schedule_today"}, "")
        == "safe"
    )
    assert (
        services.creator_os_post_time({"scheduledFor": "2026-06-06T12:00:00Z"})
        == "2026-06-06T12:00:00Z"
    )
    assert services.creator_os_recommended_post_count("safe", True) == 1
    assert (
        services.recommended_story_intent_for_date("2026-06-06", creator="Stacey")
        == "reel_teaser"
    )
    assert services.recommended_story_style_for_intent("reel_teaser") == "raw_phone"

    assert calls == [
        ("creator_os_local_schedule_safe_assets", ("Stacey",), {}),
        (
            "creator_os_target_date",
            (),
            {"date": "2026-06-06T12:00:00Z", "generated_at": None},
        ),
        (
            "creator_os_account_surface_status",
            ({"surfaceStatus": {}},),
            {"reel_needed": True},
        ),
        (
            "creator_os_surface_summary_for_creator",
            (),
            {
                "creator": "Stacey",
                "date": "2026-06-06",
                "report": {},
                "creator_accounts": [],
                "draft_items": [draft],
            },
        ),
        ("creator_os_gap_blocking_reason", ("missingHandoffManifest", [], draft), {}),
        ("creator_os_draft_items", (planner_inputs,), {}),
        ("creator_os_draft_has_instagram_post_caption", (draft,), {}),
        ("creator_os_draft_exclusion_reason", (draft,), {}),
        ("creator_os_draft_exclusion_counts", ("Stacey", [draft]), {}),
        ("creator_os_schedule_safe_drafts", ("Stacey", [draft]), {}),
        ("creator_os_execution_draft_blockers", ("Stacey", [draft]), {}),
        ("creator_os_explicit_false", (draft, "burnedCaptionTextPresent"), {}),
        ("creator_os_inventory_for_creator", ("Stacey", planner_inputs, [draft]), {}),
        (
            "creator_os_blocked_account_breakdown",
            ([{"blockedReason": "restricted"}],),
            {},
        ),
        (
            "creator_os_manager_decision",
            (),
            {
                "safe_accounts": 1,
                "needs_posts": 1,
                "validated_available": 1,
                "shortfall": 0,
                "missed_dispatches": [],
                "winner_recommendations": [],
            },
        ),
        ("creator_os_account_state", ({"bucket": "safe_to_schedule_today"}, ""), {}),
        ("creator_os_post_time", ({"scheduledFor": "2026-06-06T12:00:00Z"},), {}),
        ("creator_os_recommended_post_count", ("safe", True), {}),
        ("recommended_story_intent_for_date", ("2026-06-06",), {"creator": "Stacey"}),
        ("recommended_story_style_for_intent", ("reel_teaser",), {}),
    ]


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

        def ensure_graph_edge_strict(self, *args, **kwargs):
            calls.append(("ensure_graph_edge_strict", args, kwargs))
            return "edge_strict_1"

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

        def autonomy_level(self, *args, **kwargs):
            calls.append(("autonomy_level", args, kwargs))
            return "level_2"

        def set_autonomy_level(self, *args, **kwargs):
            calls.append(("set_autonomy_level", args, kwargs))
            return {"schema": "campaign_factory.autonomy_policy.v1", "level": args[0]}

        def autonomy_policy(self, *args, **kwargs):
            calls.append(("autonomy_policy", args, kwargs))
            return {"schema": "campaign_factory.autonomy_policy.v1", "level": "level_2"}

        def rebuild_account_memory(self, *args, **kwargs):
            calls.append(("rebuild_account_memory", args, kwargs))
            return {
                "schema": "campaign_factory.account_memory_rebuild.v1",
                "campaign": args[0],
            }

        def account_memory_report(self, *args, **kwargs):
            calls.append(("account_memory_report", args, kwargs))
            return {"schema": "campaign_factory.account_memory.v1", "campaign": args[0]}

        def account_memory_payload(self, *args, **kwargs):
            calls.append(("account_memory_payload", args, kwargs))
            return {"id": args[0]["id"], "accountId": args[0]["account_id"]}

        def account_memory_for(self, *args, **kwargs):
            calls.append(("account_memory_for", args, kwargs))
            return {"accountId": args[1]}

        def account_pattern_stats_from_snapshots(self, *args, **kwargs):
            calls.append(("account_pattern_stats_from_snapshots", args, kwargs))
            return [{"patternType": "recipe"}]

        def account_posting_windows_from_snapshots(self, *args, **kwargs):
            calls.append(("account_posting_windows_from_snapshots", args, kwargs))
            return [{"weekday": 0}]

        def account_fatigue_from_pattern_stats(self, *args, **kwargs):
            calls.append(("account_fatigue_from_pattern_stats", args, kwargs))
            return {"level": "low"}

        def account_recommendation_outcomes(self, *args, **kwargs):
            calls.append(("account_recommendation_outcomes", args, kwargs))
            return {"measuredTotal": 0}

        def account_memory_confidence(self, *args, **kwargs):
            calls.append(("account_memory_confidence", args, kwargs))
            return "low"

        def recommendation_accuracy(self, *args, **kwargs):
            calls.append(("recommendation_accuracy", args, kwargs))
            return {
                "schema": "campaign_factory.recommendation_accuracy_report.v1",
                "campaign": args[0],
            }

        def rebuild_recommendation_accuracy(self, *args, **kwargs):
            calls.append(("rebuild_recommendation_accuracy", args, kwargs))
            return {
                "schema": "campaign_factory.recommendation_accuracy_report.v1",
                "campaign": args[0],
            }

        def recommendation_proof_summary(self, *args, **kwargs):
            calls.append(("recommendation_proof_summary", args, kwargs))
            return {"measuredCount": 1}

        def rebuild_recommendation_accuracy_observations(self, *args, **kwargs):
            calls.append(("rebuild_recommendation_accuracy_observations", args, kwargs))
            return [{"id": "obs_1"}]

        def upsert_recommendation_accuracy_observation(self, *args, **kwargs):
            calls.append(("upsert_recommendation_accuracy_observation", args, kwargs))
            return {"id": "obs_1"}

        def recommendation_accuracy_observations(self, *args, **kwargs):
            calls.append(("recommendation_accuracy_observations", args, kwargs))
            return [{"id": "obs_1"}]

        def recommendation_accuracy_report_payload(self, *args, **kwargs):
            calls.append(("recommendation_accuracy_report_payload", args, kwargs))
            return {"schema": "campaign_factory.recommendation_accuracy_report.v1"}

        def persist_recommendation_accuracy_report(self, *args, **kwargs):
            calls.append(("persist_recommendation_accuracy_report", args, kwargs))
            return "recacc_report_1"

        def recommendation_accuracy_drift(self, *args, **kwargs):
            calls.append(("recommendation_accuracy_drift", args, kwargs))
            return []

        def recommendation_trust_score(self, *args, **kwargs):
            calls.append(("recommendation_trust_score", args, kwargs))
            return 80

        def recommendation_trust_confidence(self, *args, **kwargs):
            calls.append(("recommendation_trust_confidence", args, kwargs))
            return "usable"

        def recommendation_confidence_bucket(self, *args, **kwargs):
            calls.append(("recommendation_confidence_bucket", args, kwargs))
            return "usable"

        def recommendation_audio_selection(self, *args, **kwargs):
            calls.append(("recommendation_audio_selection", args, kwargs))
            return {"id": "audsel_1"}

        def recommendation_audio_match_status(self, *args, **kwargs):
            calls.append(("recommendation_audio_match_status", args, kwargs))
            return "recommended_audio_selected"

        def recommendation_outcome_snapshot_ids(self, *args, **kwargs):
            calls.append(("recommendation_outcome_snapshot_ids", args, kwargs))
            return ["perf_1"]

        def create_creative_plan(self, *args, **kwargs):
            calls.append(("create_creative_plan", args, kwargs))
            return {
                "schema": "campaign_factory.creative_plan.v1",
                "name": kwargs["name"],
            }

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

    assert (
        factory.graph_id_for(
            "campaigns", "camp_1", entity_type="campaign", payload={"slug": "may"}
        )
        == "graph_1"
    )
    assert (
        factory.ensure_graph_edge(
            "from", "to", "contains", evidence={"ok": True}, commit=True
        )
        == "edge_1"
    )
    assert factory.set_graph_sync_state("threadsdash", {"cursor": "next"}) is None
    assert factory.record_event(
        "evt", campaign_id="camp_1", status="success", metadata={"ok": True}
    ) == {"id": "evt_1"}
    assert factory.events_for_campaign("may", limit=3) == [{"id": "evt_1"}]
    assert factory.events_for_asset("asset_1", limit=2) == [{"id": "evt_2"}]
    assert factory.create_pipeline_job("render", "camp_1", {"step": 1}) == {
        "id": "job_1"
    }
    assert factory.start_pipeline_job("job_1") == {"id": "job_1", "status": "running"}
    assert factory.finish_pipeline_job("job_1", {"ok": True}) == {
        "id": "job_1",
        "status": "succeeded",
    }
    assert factory.fail_pipeline_job("job_1", "boom", {"ok": False}) == {
        "id": "job_1",
        "status": "failed",
    }
    assert factory.set_pipeline_job_campaign("job_1", "camp_1") == {
        "id": "job_1",
        "campaignId": "camp_1",
    }
    assert factory.pipeline_job("job_1") == {"id": "job_1"}
    assert factory.pipeline_job_payload({"id": "job_1"}) == {"id": "job_1"}
    assert factory.upsert_model("model-a", name="Model A", notes="notes") == {
        "slug": "model-a"
    }
    assert factory.upsert_campaign(
        "may", "model-a", name="May", platform="threads"
    ) == {"slug": "may", "model_slug": "model-a"}
    assert factory.upsert_account(
        "@creator", platform="instagram", external_id="ig_1", model_id="model_1"
    ) == {"handle": "@creator"}
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
    assert factory.autonomy_level() == "level_2"
    assert factory.set_autonomy_level("level_3") == {
        "schema": "campaign_factory.autonomy_policy.v1",
        "level": "level_3",
    }
    assert factory.autonomy_policy() == {
        "schema": "campaign_factory.autonomy_policy.v1",
        "level": "level_2",
    }
    assert factory.rebuild_account_memory("may") == {
        "schema": "campaign_factory.account_memory_rebuild.v1",
        "campaign": "may",
    }
    assert factory.account_memory("may", account="ig_1") == {
        "schema": "campaign_factory.account_memory.v1",
        "campaign": "may",
    }
    assert factory._account_memory_payload(
        {"id": "acctmem_1", "account_id": "ig_1"}
    ) == {"id": "acctmem_1", "accountId": "ig_1"}
    assert factory._account_memory_for("camp_1", "ig_1") == {"accountId": "ig_1"}
    assert factory._account_pattern_stats_from_snapshots(
        "camp_1", "ig_1", [], "now"
    ) == [{"patternType": "recipe"}]
    assert factory._account_posting_windows_from_snapshots(
        "camp_1", "ig_1", [], "now"
    ) == [{"weekday": 0}]
    assert factory._account_fatigue_from_pattern_stats([]) == {"level": "low"}
    assert factory._account_recommendation_outcomes("camp_1", "ig_1", "now") == {
        "measuredTotal": 0
    }
    assert factory._account_memory_confidence(1, {"measuredTotal": 0}) == "low"
    assert factory.recommendation_accuracy(
        "may", account="ig_1", window_days=7, persist=False
    ) == {
        "schema": "campaign_factory.recommendation_accuracy_report.v1",
        "campaign": "may",
    }
    assert factory.rebuild_recommendation_accuracy(
        "may", account="ig_1", window_days=7
    ) == {
        "schema": "campaign_factory.recommendation_accuracy_report.v1",
        "campaign": "may",
    }
    assert factory._recommendation_proof_summary("camp_1") == {"measuredCount": 1}
    assert factory._rebuild_recommendation_accuracy_observations(
        "camp_1", account="ig_1"
    ) == [{"id": "obs_1"}]
    assert factory._upsert_recommendation_accuracy_observation(
        {"id": "rec_1"}, commit=True
    ) == {"id": "obs_1"}
    assert factory._recommendation_accuracy_observations(
        "camp_1", account="ig_1", window_days=7
    ) == [{"id": "obs_1"}]
    assert factory._recommendation_accuracy_report_payload(
        {"id": "camp_1", "slug": "may"}, [], [], account="ig_1", window_days=7
    ) == {
        "schema": "campaign_factory.recommendation_accuracy_report.v1",
    }
    assert (
        factory._persist_recommendation_accuracy_report(
            {"observations": []}, "camp_1", account="ig_1", window_days=7
        )
        == "recacc_report_1"
    )
    assert factory._recommendation_accuracy_drift([], []) == []
    assert factory._recommendation_trust_score([], []) == 80
    assert factory._recommendation_trust_confidence(10) == "usable"
    assert factory._recommendation_confidence_bucket("medium", "high") == "usable"
    assert factory._recommendation_audio_selection("rec_1") == {"id": "audsel_1"}
    assert (
        factory._recommendation_audio_match_status(
            {"audioRecommendations": {"recommendations": []}}, {"id": "audsel_1"}
        )
        == "recommended_audio_selected"
    )
    assert factory._recommendation_outcome_snapshot_ids(
        {"snapshots": [{"id": "perf_1"}]}, {}
    ) == ["perf_1"]
    assert factory.create_creative_plan(name="daily", target_account="@creator") == {
        "schema": "campaign_factory.creative_plan.v1",
        "name": "daily",
    }
    assert factory.creative_plan("daily") == {
        "schema": "campaign_factory.creative_plan.v1",
        "name": "daily",
    }
    assert factory.update_creative_plan_status(
        name="daily", status="prompts_ready"
    ) == {"status": "prompts_ready"}
    assert factory.sync_creative_plan_progress(
        name="daily", prompt_export_path=Path("/tmp/prompts.json")
    ) == {
        "schema": "campaign_factory.creative_plan_progress_sync.v1",
    }
    assert factory.creative_plan_for_campaign(
        "may", dashboard={"campaign": {"slug": "may"}}
    ) == {"linked_campaign": "may"}
    assert (
        factory._record_creative_plan_event(
            "cplan_1", "creative_plan_created", metadata={"ok": True}
        )
        is None
    )
    assert factory._creative_plan_payload({"id": "cplan_1"}) == {"id": "cplan_1"}
    assert (
        factory._source_prompt_creative_plan_id(
            {"source_prompt": '{"creativePlanId":"cplan_1"}'}
        )
        == "cplan_1"
    )
    assert (
        factory._asset_creative_plan_id(
            {"source_prompt": '{"creativePlanId":"cplan_2"}'}
        )
        == "cplan_2"
    )
    assert factory.import_reference_bank(
        Path("/tmp/bank.json"), Path("/tmp/prompts.json")
    ) == {
        "schema": "campaign_factory.reference_bank_import.v1",
    }
    assert factory.reference_patterns(limit=3) == {
        "schema": "campaign_factory.reference_patterns.v1"
    }
    assert factory.select_reference_pattern(
        "may", cluster_key="cluster", variant_count=2, notes="notes"
    ) == {
        "schema": "campaign_factory.reference_pattern_selection.v1",
    }
    assert factory.campaign_reference_plan("may") == {
        "schema": "campaign_factory.reference_plan.v1"
    }
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
    assert factory.reference_hooks(
        {"clusterKey": "cluster", "label": "Cluster"}, count=2
    ) == [
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
    assert factory._caption_version_payload({"id": "cver_1"}) == {
        "captionVersionId": "cver_1"
    }
    assert factory.decision_ledger_preview(creator="Stacey", date="2026-06-06") == {
        "schema": "creator_os.decision_ledger_preview.v1",
    }
    assert factory.decision_ledger_report(creator="Stacey") == {
        "schema": "creator_os.decision_ledger_report.v1"
    }
    assert factory.decision_ledger_summary(creator="Stacey") == {
        "schema": "creator_os.decision_ledger_summary.v1"
    }
    assert factory.decision_ledger_by_creator(creator="Stacey") == {
        "schema": "creator_os.decision_ledger_by_creator.v1",
    }
    assert factory.decision_ledger_by_account(
        creator="Stacey", account_id="acct_1"
    ) == {
        "schema": "creator_os.decision_ledger_by_account.v1",
    }
    assert factory.decision_ledger_by_surface(creator="Stacey", surface="story") == {
        "schema": "creator_os.decision_ledger_by_surface.v1",
    }
    assert factory.decision_ledger_by_decision_type(
        creator="Stacey", decision_type="account_needs_story"
    ) == {
        "schema": "creator_os.decision_ledger_by_decision_type.v1",
    }
    assert factory._query_decision_ledger(creator="Stacey") == {"decisionCount": 0}

    assert calls == [
        (
            "graph_id_for",
            ("campaigns", "camp_1"),
            {"entity_type": "campaign", "payload": {"slug": "may"}},
        ),
        (
            "ensure_graph_edge",
            ("from", "to", "contains"),
            {"evidence": {"ok": True}, "commit": True},
        ),
        ("set_graph_sync_state", ("threadsdash", {"cursor": "next"}), {}),
        (
            "record_event",
            ("evt",),
            {
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
            },
        ),
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
        (
            "upsert_account",
            ("@creator",),
            {"platform": "instagram", "external_id": "ig_1", "model_id": "model_1"},
        ),
        (
            "upsert_model_account_profile",
            ("model-a",),
            {
                "label": "Model A",
                "allowed_instagram_account_ids": ["ig_1"],
                "allowed_account_group_names": ["warm"],
                "allowed_handle_patterns": ["creator"],
                "default_smart_link": "https://example.test",
                "story_cta_text": "new post",
            },
        ),
        ("model_account_profile", ("model-a",), {}),
        (
            "account_compatible_with_model",
            ("model-a",),
            {
                "instagram_account_id": "ig_1",
                "account_handle": "creator",
                "account_group_name": "warm",
            },
        ),
        ("campaign_by_slug", ("may",), {}),
        ("rendered_asset", ("asset_1",), {}),
        (
            "import_folder",
            (Path("/tmp/import"),),
            {
                "campaign_slug": "may",
                "model_slug": "model-a",
                "model_name": "Model A",
                "platform": "threads",
                "account_handles": ["ig_a"],
                "source_prompt": "prompt",
                "notes": "notes",
            },
        ),
        ("assets_for_campaign", ("camp_1",), {}),
        ("autonomy_level", (), {}),
        ("set_autonomy_level", ("level_3",), {}),
        ("autonomy_policy", (), {}),
        ("rebuild_account_memory", ("may",), {}),
        ("account_memory_report", ("may",), {"account": "ig_1"}),
        ("account_memory_payload", ({"id": "acctmem_1", "account_id": "ig_1"},), {}),
        ("account_memory_for", ("camp_1", "ig_1"), {}),
        (
            "account_pattern_stats_from_snapshots",
            ("camp_1", "ig_1", [], "now"),
            {"account_baselines": None},
        ),
        (
            "account_posting_windows_from_snapshots",
            ("camp_1", "ig_1", [], "now"),
            {"account_baselines": None},
        ),
        ("account_fatigue_from_pattern_stats", ([],), {}),
        ("account_recommendation_outcomes", ("camp_1", "ig_1", "now"), {}),
        ("account_memory_confidence", (1, {"measuredTotal": 0}), {}),
        (
            "recommendation_accuracy",
            ("may",),
            {"account": "ig_1", "window_days": 7, "persist": False},
        ),
        (
            "rebuild_recommendation_accuracy",
            ("may",),
            {"account": "ig_1", "window_days": 7},
        ),
        ("recommendation_proof_summary", ("camp_1",), {}),
        (
            "rebuild_recommendation_accuracy_observations",
            ("camp_1",),
            {"account": "ig_1", "commit": True},
        ),
        (
            "upsert_recommendation_accuracy_observation",
            ({"id": "rec_1"},),
            {"commit": True},
        ),
        (
            "recommendation_accuracy_observations",
            ("camp_1",),
            {"account": "ig_1", "window_days": 7, "before_window_days": None},
        ),
        (
            "recommendation_accuracy_report_payload",
            ({"id": "camp_1", "slug": "may"}, [], []),
            {"account": "ig_1", "window_days": 7},
        ),
        (
            "persist_recommendation_accuracy_report",
            ({"observations": []}, "camp_1"),
            {"account": "ig_1", "window_days": 7},
        ),
        (
            "recommendation_accuracy_drift",
            ([], []),
            {"min_sample": 5, "drop_threshold": 0.15},
        ),
        ("recommendation_trust_score", ([], []), {}),
        ("recommendation_trust_confidence", (10,), {}),
        ("recommendation_confidence_bucket", ("medium", "high"), {}),
        ("recommendation_audio_selection", ("rec_1",), {}),
        (
            "recommendation_audio_match_status",
            ({"audioRecommendations": {"recommendations": []}}, {"id": "audsel_1"}),
            {},
        ),
        (
            "recommendation_outcome_snapshot_ids",
            ({"snapshots": [{"id": "perf_1"}]}, {}),
            {},
        ),
        (
            "create_creative_plan",
            (),
            {
                "name": "daily",
                "platform": "instagram",
                "target_account": "@creator",
                "daily_base_video_target": 10,
                "style_lanes": None,
                "model_profile": "",
                "source_accounts": None,
                "goal": "views_reach",
                "linked_campaign": None,
            },
        ),
        ("creative_plan", ("daily",), {}),
        (
            "update_creative_plan_status",
            (),
            {"name": "daily", "status": "prompts_ready"},
        ),
        (
            "sync_creative_plan_progress",
            (),
            {"name": "daily", "prompt_export_path": Path("/tmp/prompts.json")},
        ),
        (
            "creative_plan_for_campaign",
            ("may",),
            {"dashboard": {"campaign": {"slug": "may"}}},
        ),
        (
            "record_creative_plan_event",
            ("cplan_1", "creative_plan_created"),
            {
                "status": "info",
                "message": "",
                "metadata": {"ok": True},
                "commit": True,
            },
        ),
        ("creative_plan_payload", ({"id": "cplan_1"},), {"dashboard": None}),
        (
            "source_prompt_creative_plan_id",
            ({"source_prompt": '{"creativePlanId":"cplan_1"}'},),
            {},
        ),
        (
            "asset_creative_plan_id",
            ({"source_prompt": '{"creativePlanId":"cplan_2"}'},),
            {},
        ),
        (
            "import_reference_bank",
            (Path("/tmp/bank.json"), Path("/tmp/prompts.json")),
            {},
        ),
        ("reference_patterns", (), {"limit": 3}),
        (
            "select_reference_pattern",
            ("may",),
            {
                "cluster_key": "cluster",
                "reference_pattern_id": None,
                "variant_count": 2,
                "notes": "notes",
            },
        ),
        ("campaign_reference_plan", ("may",), {}),
        (
            "prepare_reel_from_reference",
            (),
            {
                "campaign_slug": "may",
                "cluster_key": "cluster",
                "reference_pattern_id": None,
                "variant_count": 2,
                "recipes": ["v01_original"],
                "caption_color": "white",
                "notes": "notes",
                "force_new": False,
            },
        ),
        ("active_reference_pattern_for_campaign", ("camp_1",), {}),
        (
            "reference_hooks",
            ({"clusterKey": "cluster", "label": "Cluster"},),
            {"count": 2},
        ),
        ("reference_pattern_payload", ({"id": "refpat_1"},), {}),
        ("reference_hook_is_schedule_safe", ("mirror check",), {}),
        (
            "caption_family_plan",
            (),
            {
                "creator": "Stacey",
                "parent_asset_id": "asset_1",
                "requested_caption_versions": 2,
                "style": "ig_short",
                "dry_run": True,
            },
        ),
        (
            "caption_family_create",
            (),
            {
                "creator": "Stacey",
                "parent_asset_id": "asset_1",
                "requested_caption_versions": 2,
                "style": "ig_short",
                "dry_run": False,
            },
        ),
        (
            "planned_caption_version",
            (),
            {
                "caption_family_id": "cfam_1",
                "parent": {"id": "asset_1"},
                "concept": {"parentReelId": "preel_1"},
                "index": 1,
                "angle": "question_bait",
                "base_burned": "caption",
                "base_hashtags": ["#one"],
                "style": "ig_short",
                "caption_source": "test",
            },
        ),
        ("caption_family_hashtags", (["#one", "two"],), {}),
        ("caption_version_by_id", ("cver_1",), {}),
        ("caption_version_payload", ({"id": "cver_1"},), {}),
        (
            "decision_ledger_preview",
            (),
            {
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
            },
        ),
        ("decision_ledger_report", (), {"creator": "Stacey"}),
        ("decision_ledger_summary", (), {"creator": "Stacey"}),
        ("decision_ledger_by_creator", (), {"creator": "Stacey"}),
        (
            "decision_ledger_by_account",
            (),
            {"creator": "Stacey", "account_id": "acct_1"},
        ),
        ("decision_ledger_by_surface", (), {"creator": "Stacey", "surface": "story"}),
        (
            "decision_ledger_by_decision_type",
            (),
            {"creator": "Stacey", "decision_type": "account_needs_story"},
        ),
        (
            "query_decision_ledger",
            (),
            {
                "creator": "Stacey",
                "account_id": None,
                "surface": None,
                "decision_type": None,
            },
        ),
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

    assert (
        services.ensure_graph_node(
            "campaign",
            local_table="campaigns",
            local_id="camp_1",
            payload={"slug": "may"},
        )
        == "node_1"
    )
    assert (
        services.graph_id_for(
            "campaigns", "camp_1", entity_type="campaign", payload={"slug": "may"}
        )
        == "node_2"
    )
    assert (
        services.ensure_graph_edge(
            "node_1", "node_2", "contains", evidence={"ok": True}, commit=True
        )
        == "edge_1"
    )
    assert services.set_graph_sync_state("threadsdash", {"cursor": "next"}) is None

    assert calls == [
        (
            "ensure_graph_node",
            ("campaign",),
            {
                "local_table": "campaigns",
                "local_id": "camp_1",
                "external_system": None,
                "external_id": None,
                "payload": {"slug": "may"},
                "commit": False,
            },
        ),
        (
            "graph_id_for",
            ("campaigns", "camp_1"),
            {"entity_type": "campaign", "payload": {"slug": "may"}},
        ),
        (
            "ensure_graph_edge",
            ("node_1", "node_2", "contains"),
            {"evidence": {"ok": True}, "commit": True},
        ),
        ("set_sync_state", ("threadsdash", {"cursor": "next"}), {}),
    ]


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


def test_campaign_factory_strict_graph_edge_delegates_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def ensure_graph_edge_strict(self, *args, **kwargs):
            calls.append(("ensure_graph_edge_strict", args, kwargs))
            return "edge_strict_1"

    factory.services = FakeServices()

    assert (
        factory.ensure_graph_edge_strict(
            "from",
            "to",
            "references",
            evidence={"api_key": "secret"},
            campaign_id="camp_1",
            account_id="acct_1",
            recommendation_item_id="rec_1",
            source_operation="recommendation sync",
            commit=True,
        )
        == "edge_strict_1"
    )

    assert calls == [
        (
            "ensure_graph_edge_strict",
            ("from", "to", "references"),
            {
                "evidence": {"api_key": "secret"},
                "campaign_id": "camp_1",
                "account_id": "acct_1",
                "recommendation_item_id": "rec_1",
                "source_operation": "recommendation sync",
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
    assert services.create_pipeline_job("render", "camp_1", {"step": 1}) == {
        "id": "job_1"
    }
    assert services.start_pipeline_job("job_1") == {"id": "job_1"}
    assert services.finish_pipeline_job("job_1", {"ok": True}) == {"id": "job_1"}
    assert services.fail_pipeline_job("job_1", "boom", {"ok": False}) == {"id": "job_1"}
    assert services.set_pipeline_job_campaign("job_1", "camp_1") == {"id": "job_1"}
    assert services.pipeline_job("job_1") == {"id": "job_1"}
    assert services.pipeline_job_payload({"id": "job_1"}) == {"id": "job_1"}

    assert calls == [
        (
            "record_event",
            ("evt",),
            {
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
            },
        ),
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

    assert services.upsert_model("model-a", name="Model A", notes="notes") == {
        "slug": "model-a"
    }
    assert services.upsert_campaign(
        "may", "model-a", name="May", platform="threads"
    ) == {"slug": "may"}
    assert services.upsert_account(
        "@creator", platform="instagram", external_id="ig_1", model_id="model_1"
    ) == {"handle": "@creator"}
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
        (
            "upsert_account",
            ("@creator",),
            {"platform": "instagram", "external_id": "ig_1", "model_id": "model_1"},
        ),
        (
            "upsert_model_account_profile",
            ("model-a",),
            {
                "label": "Model A",
                "allowed_instagram_account_ids": ["ig_1"],
                "allowed_account_group_names": ["warm"],
                "allowed_handle_patterns": ["creator"],
                "default_smart_link": "https://example.test",
                "story_cta_text": "new post",
            },
        ),
        ("model_account_profile", ("model-a",), {}),
        (
            "account_compatible_with_model",
            ("model-a",),
            {
                "instagram_account_id": "ig_1",
                "account_handle": "creator",
                "account_group_name": "warm",
            },
        ),
    ]


def test_core_services_delegates_asset_import_methods_to_asset_import_repository() -> (
    None
):
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
        (
            "import_folder",
            (Path("/tmp/import"),),
            {
                "campaign_slug": "may",
                "model_slug": "model-a",
                "model_name": "Model A",
                "platform": "threads",
                "account_handles": ["ig_a"],
                "source_prompt": "prompt",
                "notes": "notes",
            },
        ),
        ("assets_for_campaign", ("camp_1",), {}),
    ]


def test_core_services_delegates_autonomy_methods_to_autonomy_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeAutonomy:
        def autonomy_level(self, *args, **kwargs):
            calls.append(("autonomy_level", args, kwargs))
            return "level_2"

        def set_autonomy_level(self, *args, **kwargs):
            calls.append(("set_autonomy_level", args, kwargs))
            return {"schema": "campaign_factory.autonomy_policy.v1", "level": args[0]}

        def autonomy_policy(self, *args, **kwargs):
            calls.append(("autonomy_policy", args, kwargs))
            return {"schema": "campaign_factory.autonomy_policy.v1", "level": "level_2"}

    services.autonomy = FakeAutonomy()

    assert services.autonomy_level() == "level_2"
    assert services.set_autonomy_level("level_3") == {
        "schema": "campaign_factory.autonomy_policy.v1",
        "level": "level_3",
    }
    assert services.autonomy_policy() == {
        "schema": "campaign_factory.autonomy_policy.v1",
        "level": "level_2",
    }

    assert calls == [
        ("autonomy_level", (), {}),
        ("set_autonomy_level", ("level_3",), {}),
        ("autonomy_policy", (), {}),
    ]


def test_core_services_delegates_account_memory_methods_to_account_memory_repository() -> (
    None
):
    services = object.__new__(CoreServices)
    calls = []

    class FakeAccountMemory:
        def rebuild_account_memory(self, *args, **kwargs):
            calls.append(("rebuild_account_memory", args, kwargs))
            return {
                "schema": "campaign_factory.account_memory_rebuild.v1",
                "campaign": args[0],
            }

        def account_memory(self, *args, **kwargs):
            calls.append(("account_memory", args, kwargs))
            return {"schema": "campaign_factory.account_memory.v1", "campaign": args[0]}

        def account_memory_payload(self, *args, **kwargs):
            calls.append(("account_memory_payload", args, kwargs))
            return {"id": args[0]["id"]}

        def account_memory_for(self, *args, **kwargs):
            calls.append(("account_memory_for", args, kwargs))
            return {"accountId": args[1]}

        def account_pattern_stats_from_snapshots(self, *args, **kwargs):
            calls.append(("account_pattern_stats_from_snapshots", args, kwargs))
            return [{"patternType": "recipe"}]

        def account_posting_windows_from_snapshots(self, *args, **kwargs):
            calls.append(("account_posting_windows_from_snapshots", args, kwargs))
            return [{"weekday": 0}]

        def account_fatigue_from_pattern_stats(self, *args, **kwargs):
            calls.append(("account_fatigue_from_pattern_stats", args, kwargs))
            return {"level": "low"}

        def account_recommendation_outcomes(self, *args, **kwargs):
            calls.append(("account_recommendation_outcomes", args, kwargs))
            return {"measuredTotal": 0}

        def account_memory_confidence(self, *args, **kwargs):
            calls.append(("account_memory_confidence", args, kwargs))
            return "low"

    services.account_memory = FakeAccountMemory()

    assert services.rebuild_account_memory("may") == {
        "schema": "campaign_factory.account_memory_rebuild.v1",
        "campaign": "may",
    }
    assert services.account_memory_report("may", account="ig_1") == {
        "schema": "campaign_factory.account_memory.v1",
        "campaign": "may",
    }
    assert services.account_memory_payload({"id": "acctmem_1"}) == {"id": "acctmem_1"}
    assert services.account_memory_for("camp_1", "ig_1") == {"accountId": "ig_1"}
    assert services.account_pattern_stats_from_snapshots(
        "camp_1", "ig_1", [], "now"
    ) == [{"patternType": "recipe"}]
    assert services.account_posting_windows_from_snapshots(
        "camp_1", "ig_1", [], "now"
    ) == [{"weekday": 0}]
    assert services.account_fatigue_from_pattern_stats([]) == {"level": "low"}
    assert services.account_recommendation_outcomes("camp_1", "ig_1", "now") == {
        "measuredTotal": 0
    }
    assert services.account_memory_confidence(1, {"measuredTotal": 0}) == "low"

    assert calls == [
        ("rebuild_account_memory", ("may",), {}),
        ("account_memory", ("may",), {"account": "ig_1"}),
        ("account_memory_payload", ({"id": "acctmem_1"},), {}),
        ("account_memory_for", ("camp_1", "ig_1"), {}),
        (
            "account_pattern_stats_from_snapshots",
            ("camp_1", "ig_1", [], "now"),
            {"account_baselines": None},
        ),
        (
            "account_posting_windows_from_snapshots",
            ("camp_1", "ig_1", [], "now"),
            {"account_baselines": None},
        ),
        ("account_fatigue_from_pattern_stats", ([],), {}),
        ("account_recommendation_outcomes", ("camp_1", "ig_1", "now"), {}),
        ("account_memory_confidence", (1, {"measuredTotal": 0}), {}),
    ]


def test_core_services_delegates_jobs_for_campaign_to_event_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeEvents:
        def jobs_for_campaign(self, *args, **kwargs):
            calls.append(("jobs_for_campaign", args, kwargs))
            return [{"id": "job_1"}]

    services.events = FakeEvents()

    assert services.jobs_for_campaign("may", limit=5) == [{"id": "job_1"}]
    assert calls == [
        (
            "jobs_for_campaign",
            ("may",),
            {"limit": 5, "statuses": None, "stuck_hours": None},
        )
    ]


def test_core_services_delegates_surface_summary_methods_to_surface_summary_repository() -> (
    None
):
    services = object.__new__(CoreServices)
    calls = []

    class FakeSurfaceSummary:
        def creator_surface_summary(self, *args, **kwargs):
            calls.append(("creator_surface_summary", args, kwargs))
            return {"schema": "creator_os.creator_surface_summary.v1"}

        def account_surface_summary(self, *args, **kwargs):
            calls.append(("account_surface_summary", args, kwargs))
            return {"schema": "creator_os.account_surface_summary.v1"}

        def creator_surface_gap_report(self, *args, **kwargs):
            calls.append(("creator_surface_gap_report", args, kwargs))
            return {"schema": "creator_os.creator_surface_gap_report.v1"}

    services.surface_summary = FakeSurfaceSummary()

    assert services.creator_surface_summary(creator="Stacey", date="2026-06-06") == {
        "schema": "creator_os.creator_surface_summary.v1",
    }
    assert services.account_surface_summary(
        creator="Stacey", account_id="ig_1", generated_at="2026-06-06T12:00:00Z"
    ) == {
        "schema": "creator_os.account_surface_summary.v1",
    }
    assert services.creator_surface_gap_report(creator="Stacey", date="2026-06-06") == {
        "schema": "creator_os.creator_surface_gap_report.v1",
    }
    assert calls == [
        (
            "creator_surface_summary",
            (),
            {"creator": "Stacey", "date": "2026-06-06", "generated_at": None},
        ),
        (
            "account_surface_summary",
            (),
            {
                "creator": "Stacey",
                "date": None,
                "account_id": "ig_1",
                "generated_at": "2026-06-06T12:00:00Z",
            },
        ),
        (
            "creator_surface_gap_report",
            (),
            {"creator": "Stacey", "date": "2026-06-06", "generated_at": None},
        ),
    ]


def test_core_services_delegates_surface_inventory_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeSurfaceInventory:
        def multi_surface_inventory_audit(self, *args, **kwargs):
            calls.append(("multi_surface_inventory_audit", args, kwargs))
            return {"schema": "campaign_factory.multi_surface_inventory_audit.v1"}

        def build_surface_inventory(self, *args, **kwargs):
            calls.append(("build_surface_inventory", args, kwargs))
            return {"schema": "campaign_factory.surface_inventory.v1"}

    services.surface_inventory = FakeSurfaceInventory()

    assert services.multi_surface_inventory_audit(
        creator="Stacey", campaign_slug="summer"
    ) == {
        "schema": "campaign_factory.multi_surface_inventory_audit.v1",
    }
    assert services.build_surface_inventory(
        creator="Stacey", campaign_slug="summer"
    ) == {
        "schema": "campaign_factory.surface_inventory.v1",
    }
    assert calls == [
        (
            "multi_surface_inventory_audit",
            (),
            {"creator": "Stacey", "campaign_slug": "summer"},
        ),
        (
            "build_surface_inventory",
            (),
            {"creator": "Stacey", "campaign_slug": "summer"},
        ),
    ]


def test_core_services_delegates_inventory_planning_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeInventoryPlanning:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    services.inventory_planning = FakeInventoryPlanning()

    public_calls = [
        ("inventory_slo_report", {"accounts": 2}),
        ("inventory_buffer_report", {"accounts": 2}),
        ("inventory_factory_audit", {"creator": "Stacey"}),
        ("inventory_yield_analysis", {"campaign_slug": "summer"}),
        (
            "inventory_buffer_policy_plan",
            {"creator": "Stacey", "surface": "reel", "daily_demand": 4},
        ),
        ("inventory_slo_enforcement_audit", {"creators": ["Stacey"], "accounts": 2}),
        (
            "inventory_consumption_simulation",
            {"available_inventory": 8, "account_tiers": [1, 2]},
        ),
        ("inventory_production_requirements", {"accounts": 2}),
        ("road_to_200_accounts", {}),
        (
            "inventory_exception_audit",
            {"execution_readiness": {"blockers": ["missing_audio"]}},
        ),
        (
            "inventory_factory_readiness_report",
            {"accounts": 2, "available_inventory": 8},
        ),
        ("inventory_factory_master_report", {"accounts": 2, "available_inventory": 8}),
        ("inventory_autopilot_plan", {"accounts": 2, "available_inventory": 1}),
        ("inventory_shortage_repair_plan", {"accounts": 2, "available_inventory": 1}),
        (
            "inventory_buffer_protection_report",
            {"accounts": 2, "available_inventory": 1},
        ),
    ]
    for method, kwargs in public_calls:
        assert getattr(services, method)(**kwargs) == {"method": method}

    assert services.inventory_slo_surface_targets(8) == {
        "method": "inventory_slo_surface_targets"
    }
    assert services.inventory_health(current=1, minimum=2) == {
        "method": "inventory_health"
    }
    assert services.inventory_stage_counts(creator="Stacey") == {
        "method": "inventory_stage_counts"
    }
    assert services.inventory_count_related(
        "caption_families", "parent_asset_id", {"asset_1"}
    ) == {
        "method": "inventory_count_related",
    }
    assert services.inventory_limiting_stage({"scheduleSafeAssets": 0}) == {
        "method": "inventory_limiting_stage"
    }
    assert services.inventory_loss_by_stage({"parentAssets": 1}) == {
        "method": "inventory_loss_by_stage"
    }
    assert services.inventory_repair_actions({"shortfall": 1}) == {
        "method": "inventory_repair_actions"
    }

    assert calls == [
        *[(method, (), kwargs) for method, kwargs in public_calls],
        ("inventory_slo_surface_targets", (8,), {}),
        ("inventory_health", (), {"current": 1, "minimum": 2}),
        ("inventory_stage_counts", (), {"creator": "Stacey", "campaign_slug": None}),
        (
            "inventory_count_related",
            ("caption_families", "parent_asset_id", {"asset_1"}),
            {},
        ),
        ("inventory_limiting_stage", ({"scheduleSafeAssets": 0},), {}),
        ("inventory_loss_by_stage", ({"parentAssets": 1},), {}),
        ("inventory_repair_actions", ({"shortfall": 1},), {}),
    ]


def test_core_services_delegates_inventory_reservation_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeInventoryReservations:
        def reserve_inventory_asset(self, *args, **kwargs):
            calls.append(("reserve_inventory_asset", args, kwargs))
            return {"reservation_id": "invres_1"}

        def expire_inventory_reservations(self, *args, **kwargs):
            calls.append(("expire_inventory_reservations", args, kwargs))
            return 2

        def release_inventory_reservation(self, *args, **kwargs):
            calls.append(("release_inventory_reservation", args, kwargs))
            return {"status": "released"}

        def inventory_uniqueness_conflicts(self, *args, **kwargs):
            calls.append(("inventory_uniqueness_conflicts", args, kwargs))
            return [{"assetId": "asset_2"}]

        def reservation_adjusted_inventory(self, *args, **kwargs):
            calls.append(("reservation_adjusted_inventory", args, kwargs))
            return {"netInventory": 1}

    services.inventory_reservations = FakeInventoryReservations()

    assert services.reserve_inventory_asset(
        "asset_1",
        account_id="acct_1",
        surface="feed_single",
        reserved_by="test",
        expires_at="2026-01-02T00:00:00+00:00",
        idempotency_key="idem_1",
        metadata={"sourceFamilyId": "family_1"},
        reuse_cooldown_days=3,
        override_reason="manual",
    ) == {"reservation_id": "invres_1"}
    assert (
        services.expire_inventory_reservations(
            now="2026-01-03T00:00:00+00:00", commit=False
        )
        == 2
    )
    assert services.release_inventory_reservation("invres_1", status="cancelled") == {
        "status": "released"
    }
    assert services.inventory_uniqueness_conflicts(
        {"id": "asset_1", "campaign_id": "campaign_1"},
        uniqueness={"sourceFamilyId": "family_1"},
        surface="feed_single",
        cooldown_days=3,
        account_id="acct_1",
    ) == [{"assetId": "asset_2"}]
    assert services.reservation_adjusted_inventory(
        [{"assetId": "asset_1", "canHandoff": True, "contentSurface": "feed_single"}],
        content_surface="feed_single",
    ) == {"netInventory": 1}

    assert calls == [
        (
            "reserve_inventory_asset",
            ("asset_1",),
            {
                "account_id": "acct_1",
                "surface": "feed_single",
                "reserved_by": "test",
                "expires_at": "2026-01-02T00:00:00+00:00",
                "idempotency_key": "idem_1",
                "metadata": {"sourceFamilyId": "family_1"},
                "reuse_cooldown_days": 3,
                "override_reason": "manual",
            },
        ),
        (
            "expire_inventory_reservations",
            (),
            {"now": "2026-01-03T00:00:00+00:00", "commit": False},
        ),
        ("release_inventory_reservation", ("invres_1",), {"status": "cancelled"}),
        (
            "inventory_uniqueness_conflicts",
            ({"id": "asset_1", "campaign_id": "campaign_1"},),
            {
                "uniqueness": {"sourceFamilyId": "family_1"},
                "surface": "feed_single",
                "cooldown_days": 3,
                "account_id": "acct_1",
            },
        ),
        (
            "reservation_adjusted_inventory",
            (
                [
                    {
                        "assetId": "asset_1",
                        "canHandoff": True,
                        "contentSurface": "feed_single",
                    }
                ],
            ),
            {"content_surface": "feed_single"},
        ),
    ]


def test_core_services_delegates_inventory_recovery_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeInventoryRecovery:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    services.inventory_recovery = FakeInventoryRecovery()

    assert services.inventory_recovery_report(
        creator="Stacey", required_inventory=3
    ) == {
        "method": "inventory_recovery_report",
    }
    assert services.inventory_recovery_priority_report(creator="Stacey") == {
        "method": "inventory_recovery_priority_report",
    }
    assert services.inventory_recovery_by_blocker(creator="Stacey") == {
        "method": "inventory_recovery_by_blocker",
    }
    assert services.inventory_recovery_master_report(creator="Stacey") == {
        "method": "inventory_recovery_master_report",
    }
    assert services.inventory_recovery_blocked_asset({"assetId": "asset_1"}) == {
        "method": "inventory_recovery_blocked_asset",
    }
    assert services.inventory_recovery_class_for_blocker("missing_audio") == {
        "method": "inventory_recovery_class_for_blocker",
    }
    assert services.inventory_recovery_class_rows([{"assetId": "asset_1"}]) == {
        "method": "inventory_recovery_class_rows",
    }
    assert services.inventory_recovery_assets_unlocked(
        [{"repairClasses": ["audio_failure"]}],
        ["audio_failure"],
    ) == {"method": "inventory_recovery_assets_unlocked"}
    assert services.inventory_recovery_priorities(
        [{"repairClass": "audio_failure"}]
    ) == {
        "method": "inventory_recovery_priorities",
    }

    assert calls == [
        (
            "inventory_recovery_report",
            (),
            {"creator": "Stacey", "required_inventory": 3},
        ),
        ("inventory_recovery_priority_report", (), {"creator": "Stacey"}),
        ("inventory_recovery_by_blocker", (), {"creator": "Stacey"}),
        ("inventory_recovery_master_report", (), {"creator": "Stacey"}),
        ("inventory_recovery_blocked_asset", ({"assetId": "asset_1"},), {}),
        ("inventory_recovery_class_for_blocker", ("missing_audio",), {}),
        ("inventory_recovery_class_rows", ([{"assetId": "asset_1"}],), {}),
        (
            "inventory_recovery_assets_unlocked",
            ([{"repairClasses": ["audio_failure"]}], ["audio_failure"]),
            {},
        ),
        ("inventory_recovery_priorities", ([{"repairClass": "audio_failure"}],), {}),
    ]


def test_core_services_delegates_schedule_safe_production_methods_to_repository() -> (
    None
):
    services = object.__new__(CoreServices)
    calls = []

    class FakeScheduleSafeProduction:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    services.schedule_safe_production = FakeScheduleSafeProduction()

    assert services.schedule_safe_production_report(
        creator="Stacey", required_inventory=3
    ) == {
        "method": "schedule_safe_production_report",
    }
    assert services.schedule_safe_production_waterfall(creator="Stacey") == {
        "method": "schedule_safe_production_waterfall",
    }
    assert services.schedule_safe_production_loss_analysis(creator="Stacey") == {
        "method": "schedule_safe_production_loss_analysis",
    }
    assert services.schedule_safe_production_capacity_model(creator="Stacey") == {
        "method": "schedule_safe_production_capacity_model",
    }
    assert services.schedule_safe_production_master_report(creator="Stacey") == {
        "method": "schedule_safe_production_master_report",
    }
    assert services.schedule_safe_production_assets(
        creator="Stacey",
        campaign_slug="summer",
        content_surface="reel",
        lookback_days=1,
    ) == {"method": "schedule_safe_production_assets"}
    assert services.schedule_safe_asset_created_at(
        {"created_at": "2026-01-01T00:00:00+00:00"}
    ) == {
        "method": "schedule_safe_asset_created_at",
    }
    assert services.schedule_safe_production_waterfall_rows(
        [{"id": "asset_1"}], "reel"
    ) == {
        "method": "schedule_safe_production_waterfall_rows",
    }
    assert services.schedule_safe_is_variant_asset({"variant_id": "variant_1"}) == {
        "method": "schedule_safe_is_variant_asset",
    }
    assert services.schedule_safe_related_count(
        "caption_families", "parent_asset_id", {"asset_1"}
    ) == {
        "method": "schedule_safe_related_count",
    }
    assert services.schedule_safe_production_variant_checks(
        {"id": "asset_1"}, "reel"
    ) == {
        "method": "schedule_safe_production_variant_checks",
    }
    assert services.schedule_safe_production_largest_loss(
        [{"stage": "x", "lossCount": 1}]
    ) == {
        "method": "schedule_safe_production_largest_loss",
    }
    assert services.schedule_safe_production_capacity(
        current_inventory=1,
        daily_production=2.0,
        required_for_25=3,
    ) == {"method": "schedule_safe_production_capacity"}
    assert services.schedule_safe_required_parents_per_day(1.0, 1, 1) == {
        "method": "schedule_safe_required_parents_per_day",
    }
    assert services.schedule_safe_required_variants_per_day(1.0, 1, 1) == {
        "method": "schedule_safe_required_variants_per_day",
    }
    assert services.schedule_safe_production_summary_key("raw_parent_reels") == {
        "method": "schedule_safe_production_summary_key",
    }

    assert calls == [
        (
            "schedule_safe_production_report",
            (),
            {"creator": "Stacey", "required_inventory": 3},
        ),
        ("schedule_safe_production_waterfall", (), {"creator": "Stacey"}),
        ("schedule_safe_production_loss_analysis", (), {"creator": "Stacey"}),
        ("schedule_safe_production_capacity_model", (), {"creator": "Stacey"}),
        ("schedule_safe_production_master_report", (), {"creator": "Stacey"}),
        (
            "schedule_safe_production_assets",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "summer",
                "content_surface": "reel",
                "lookback_days": 1,
            },
        ),
        (
            "schedule_safe_asset_created_at",
            ({"created_at": "2026-01-01T00:00:00+00:00"},),
            {},
        ),
        ("schedule_safe_production_waterfall_rows", ([{"id": "asset_1"}], "reel"), {}),
        ("schedule_safe_is_variant_asset", ({"variant_id": "variant_1"},), {}),
        (
            "schedule_safe_related_count",
            ("caption_families", "parent_asset_id", {"asset_1"}),
            {},
        ),
        ("schedule_safe_production_variant_checks", ({"id": "asset_1"}, "reel"), {}),
        (
            "schedule_safe_production_largest_loss",
            ([{"stage": "x", "lossCount": 1}],),
            {},
        ),
        (
            "schedule_safe_production_capacity",
            (),
            {"current_inventory": 1, "daily_production": 2.0, "required_for_25": 3},
        ),
        ("schedule_safe_required_parents_per_day", (1.0, 1, 1), {}),
        ("schedule_safe_required_variants_per_day", (1.0, 1, 1), {}),
        ("schedule_safe_production_summary_key", ("raw_parent_reels",), {}),
    ]


def test_core_services_delegates_fresh_reel_production_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeFreshReelProduction:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    services.fresh_reel_production = FakeFreshReelProduction()

    assert services.fresh_schedule_safe_production_plan(
        creator="Stacey", current_inventory=11
    ) == {
        "method": "fresh_schedule_safe_production_plan",
    }
    assert services.fresh_reel_production_batch_plan(creator="Stacey") == {
        "method": "fresh_reel_production_batch_plan",
    }
    assert services.fresh_reel_production_capacity_plan(creator="Stacey") == {
        "method": "fresh_reel_production_capacity_plan",
    }
    assert services.fresh_reel_production_master_report(creator="Stacey") == {
        "method": "fresh_reel_production_master_report",
    }
    assert services.fresh_reel_current_schedule_safe_inventory(
        creator="Stacey", campaign_slug="summer"
    ) == {
        "method": "fresh_reel_current_schedule_safe_inventory",
    }
    assert services.fresh_reel_downstream_schedule_safe_yield_pct() == {
        "method": "fresh_reel_downstream_schedule_safe_yield_pct",
    }
    assert services.fresh_reel_expected_stage_rows(
        raw_parent_candidates_needed=1,
        parents_needed=1,
        caption_families_needed=1,
        caption_versions_needed=5,
        variants_needed=15,
    ) == {"method": "fresh_reel_expected_stage_rows"}
    assert services.fresh_reel_stage_evidence("parent_accepted") == {
        "method": "fresh_reel_stage_evidence",
    }
    assert services.fresh_reel_execution_batches(
        fresh_needed=90,
        downstream_yield_pct=68.1,
        variants_per_parent=15,
        batch_target=90,
    ) == {"method": "fresh_reel_execution_batches"}

    assert calls == [
        (
            "fresh_schedule_safe_production_plan",
            (),
            {"creator": "Stacey", "current_inventory": 11},
        ),
        ("fresh_reel_production_batch_plan", (), {"creator": "Stacey"}),
        ("fresh_reel_production_capacity_plan", (), {"creator": "Stacey"}),
        ("fresh_reel_production_master_report", (), {"creator": "Stacey"}),
        (
            "fresh_reel_current_schedule_safe_inventory",
            (),
            {"creator": "Stacey", "campaign_slug": "summer"},
        ),
        ("fresh_reel_downstream_schedule_safe_yield_pct", (), {}),
        (
            "fresh_reel_expected_stage_rows",
            (),
            {
                "raw_parent_candidates_needed": 1,
                "parents_needed": 1,
                "caption_families_needed": 1,
                "caption_versions_needed": 5,
                "variants_needed": 15,
            },
        ),
        ("fresh_reel_stage_evidence", ("parent_accepted",), {}),
        (
            "fresh_reel_execution_batches",
            (),
            {
                "fresh_needed": 90,
                "downstream_yield_pct": 68.1,
                "variants_per_parent": 15,
                "batch_target": 90,
            },
        ),
    ]


def test_core_services_delegates_reel_factory_report_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeReelFactoryReports:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    services.reel_factory_reports = FakeReelFactoryReports()
    metrics = {"rawCandidates": 25}
    yield_report = {"qcPassRate": 0.9}
    proof = {"confidence": "medium"}
    asset = {"id": "asset_1"}

    assert services.reel_factory_parent_throughput_proof(
        required_parents_per_day=53, lookback_days=2
    ) == {
        "method": "reel_factory_parent_throughput_proof",
    }
    assert services.reel_factory_yield_analysis(metrics=metrics) == {
        "method": "reel_factory_yield_analysis"
    }
    assert services.reel_factory_failure_analysis() == {
        "method": "reel_factory_failure_analysis"
    }
    assert services.reel_factory_capacity_model(required_parents_per_day=53) == {
        "method": "reel_factory_capacity_model"
    }
    assert services.reel_factory_200_account_readiness() == {
        "method": "reel_factory_200_account_readiness"
    }
    assert services.reel_factory_master_report() == {
        "method": "reel_factory_master_report"
    }
    assert services.reel_factory_parent_metrics() == {
        "method": "reel_factory_parent_metrics"
    }
    assert services.reel_factory_parent_qc_pass(asset) == {
        "method": "reel_factory_parent_qc_pass"
    }
    assert services.reel_factory_confidence(metrics) == {
        "method": "reel_factory_confidence"
    }
    assert services.operator_review_minutes_per_parent(metrics) == {
        "method": "operator_review_minutes_per_parent"
    }
    assert services.reel_factory_intake_metrics(metrics) == {
        "method": "reel_factory_intake_metrics"
    }
    assert services.reel_factory_parent_creation_metrics(metrics) == {
        "method": "reel_factory_parent_creation_metrics"
    }
    assert services.reel_factory_quality_gate_metrics(yield_report) == {
        "method": "reel_factory_quality_gate_metrics"
    }
    assert services.reel_factory_operational_readiness_metrics(yield_report) == {
        "method": "reel_factory_operational_readiness_metrics",
    }
    assert services.reel_factory_human_cost(metrics) == {
        "method": "reel_factory_human_cost"
    }
    assert services.reel_factory_rating(proof) == {"method": "reel_factory_rating"}

    assert calls == [
        (
            "reel_factory_parent_throughput_proof",
            (),
            {"required_parents_per_day": 53, "lookback_days": 2},
        ),
        ("reel_factory_yield_analysis", (), {"metrics": metrics}),
        ("reel_factory_failure_analysis", (), {}),
        ("reel_factory_capacity_model", (), {"required_parents_per_day": 53}),
        ("reel_factory_200_account_readiness", (), {}),
        ("reel_factory_master_report", (), {}),
        ("reel_factory_parent_metrics", (), {}),
        ("reel_factory_parent_qc_pass", (asset,), {}),
        ("reel_factory_confidence", (metrics,), {}),
        ("operator_review_minutes_per_parent", (metrics,), {}),
        ("reel_factory_intake_metrics", (metrics,), {}),
        ("reel_factory_parent_creation_metrics", (metrics,), {}),
        ("reel_factory_quality_gate_metrics", (yield_report,), {}),
        ("reel_factory_operational_readiness_metrics", (yield_report,), {}),
        ("reel_factory_human_cost", (metrics,), {}),
        ("reel_factory_rating", (proof,), {}),
    ]


def test_core_services_delegates_parent_factory_report_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeParentFactoryReports:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    services.parent_factory_reports = FakeParentFactoryReports()
    metrics = {"rawCandidates": 245}
    waterfall = {"stages": []}
    rejection = {"totalFailures": 1}
    loss = {"largestLossStage": "discoverability_safety_pass"}
    reasons = [{"repairable": True, "frequency": 1}]

    assert services.parent_factory_yield_waterfall(required_parents_per_day=53) == {
        "method": "parent_factory_yield_waterfall",
    }
    assert services.parent_factory_loss_analysis(required_parents_per_day=53) == {
        "method": "parent_factory_loss_analysis",
    }
    assert services.parent_factory_rejection_report(waterfall=waterfall) == {
        "method": "parent_factory_rejection_report"
    }
    assert services.parent_factory_quality_gate_analysis() == {
        "method": "parent_factory_quality_gate_analysis"
    }
    assert services.parent_factory_optimization_plan(required_parents_per_day=53) == {
        "method": "parent_factory_optimization_plan",
    }
    assert services.parent_factory_master_optimization_report(
        required_parents_per_day=53
    ) == {
        "method": "parent_factory_master_optimization_report",
    }
    assert services.parent_factory_recoverable_yield() == {
        "method": "parent_factory_recoverable_yield"
    }
    assert services.parent_factory_throughput_recovery_plan() == {
        "method": "parent_factory_throughput_recovery_plan"
    }
    assert services.parent_factory_53_parent_feasibility() == {
        "method": "parent_factory_53_parent_feasibility"
    }
    assert services.parent_factory_secondary_loss_analysis() == {
        "method": "parent_factory_secondary_loss_analysis"
    }
    assert services.parent_factory_true_yield_model() == {
        "method": "parent_factory_true_yield_model"
    }
    assert services.parent_factory_realistic_53_parent_plan() == {
        "method": "parent_factory_realistic_53_parent_plan"
    }
    assert services.parent_factory_stage_order() == {
        "method": "parent_factory_stage_order"
    }
    assert services.parent_factory_detailed_stage_counts(metrics) == {
        "method": "parent_factory_detailed_stage_counts"
    }
    assert services.parent_factory_highest_roi(reasons) == {
        "method": "parent_factory_highest_roi"
    }
    assert services.parent_factory_top_fixes(reasons) == {
        "method": "parent_factory_top_fixes"
    }
    assert services.parent_factory_human_bottleneck(
        required=53, rejection=rejection
    ) == {
        "method": "parent_factory_human_bottleneck",
    }
    assert services.parent_factory_yield_explanation(waterfall, loss) == {
        "method": "parent_factory_yield_explanation",
    }
    assert services.secondary_loss_reason("handoff_ready", 0) == {
        "method": "secondary_loss_reason"
    }
    assert services.parent_factory_trial_loss_buckets(waterfall) == {
        "method": "parent_factory_trial_loss_buckets"
    }
    assert services.parent_factory_trial_stage_repairable("handoff_ready") == {
        "method": "parent_factory_trial_stage_repairable",
    }

    assert calls == [
        ("parent_factory_yield_waterfall", (), {"required_parents_per_day": 53}),
        ("parent_factory_loss_analysis", (), {"required_parents_per_day": 53}),
        ("parent_factory_rejection_report", (), {"waterfall": waterfall}),
        ("parent_factory_quality_gate_analysis", (), {}),
        ("parent_factory_optimization_plan", (), {"required_parents_per_day": 53}),
        (
            "parent_factory_master_optimization_report",
            (),
            {"required_parents_per_day": 53},
        ),
        ("parent_factory_recoverable_yield", (), {}),
        ("parent_factory_throughput_recovery_plan", (), {}),
        ("parent_factory_53_parent_feasibility", (), {}),
        ("parent_factory_secondary_loss_analysis", (), {}),
        ("parent_factory_true_yield_model", (), {}),
        ("parent_factory_realistic_53_parent_plan", (), {}),
        ("parent_factory_stage_order", (), {}),
        ("parent_factory_detailed_stage_counts", (metrics,), {}),
        ("parent_factory_highest_roi", (reasons,), {}),
        ("parent_factory_top_fixes", (reasons,), {}),
        (
            "parent_factory_human_bottleneck",
            (),
            {"required": 53, "rejection": rejection},
        ),
        ("parent_factory_yield_explanation", (waterfall, loss), {}),
        ("secondary_loss_reason", ("handoff_ready", 0), {}),
        ("parent_factory_trial_loss_buckets", (waterfall,), {}),
        ("parent_factory_trial_stage_repairable", ("handoff_ready",), {}),
    ]


def test_core_services_delegates_parent_factory_trial_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeParentFactoryTrials:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    services.parent_factory_trials = FakeParentFactoryTrials()
    sandbox = object()
    result = {"rejectionEvidenceCapture": {"evidenceIds": ["evidence_1"]}}

    assert services.parent_factory_production_trial() == {
        "method": "parent_factory_production_trial"
    }
    assert services.latest_measured_53_parent_production_trial() == {
        "method": "latest_measured_53_parent_production_trial",
    }
    assert services.parent_factory_53_parent_trial() == {
        "method": "parent_factory_53_parent_trial"
    }
    assert services.parent_factory_trial_results() == {
        "method": "parent_factory_trial_results"
    }
    assert services.parent_factory_trial_analysis() == {
        "method": "parent_factory_trial_analysis"
    }
    assert services.parent_factory_post_gate_fresh_batch_proof() == {
        "method": "parent_factory_post_gate_fresh_batch_proof",
    }
    assert services.parent_factory_production_scorecard() == {
        "method": "parent_factory_production_scorecard"
    }
    assert services.parent_factory_real_yield_report() == {
        "method": "parent_factory_real_yield_report"
    }
    assert services.post_gate_fresh_batch_candidates() == {
        "method": "post_gate_fresh_batch_candidates"
    }
    assert services.post_gate_blocked_candidate_evidence(sandbox, result) == {
        "method": "post_gate_blocked_candidate_evidence",
    }

    assert calls == [
        ("parent_factory_production_trial", (), {}),
        ("latest_measured_53_parent_production_trial", (), {}),
        ("parent_factory_53_parent_trial", (), {}),
        ("parent_factory_trial_results", (), {}),
        ("parent_factory_trial_analysis", (), {}),
        ("parent_factory_post_gate_fresh_batch_proof", (), {}),
        ("parent_factory_production_scorecard", (), {}),
        ("parent_factory_real_yield_report", (), {}),
        ("post_gate_fresh_batch_candidates", (), {}),
        ("post_gate_blocked_candidate_evidence", (sandbox, result), {}),
    ]


def test_core_services_delegates_parent_factory_planning_methods_to_repository() -> (
    None
):
    services = object.__new__(CoreServices)
    calls = []

    class FakeParentFactoryPlanning:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    services.parent_factory_planning = FakeParentFactoryPlanning()

    assert services.parent_factory_autopilot_plan(
        accounts=50, posts_per_account_per_day=2
    ) == {
        "method": "parent_factory_autopilot_plan",
    }
    assert services.parent_factory_shortfall_report(accounts=50) == {
        "method": "parent_factory_shortfall_report"
    }
    assert services.parent_factory_production_targets(accounts=50) == {
        "method": "parent_factory_production_targets"
    }

    assert calls == [
        (
            "parent_factory_autopilot_plan",
            (),
            {"accounts": 50, "posts_per_account_per_day": 2},
        ),
        ("parent_factory_shortfall_report", (), {"accounts": 50}),
        ("parent_factory_production_targets", (), {"accounts": 50}),
    ]


def test_core_services_delegates_contentforge_visual_qc_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeContentForgeVisualQC:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    services.contentforge_visual_qc = FakeContentForgeVisualQC()

    assert services.contentforge_visual_qc_failure_report(
        creator="Stacey", current_inventory=11
    ) == {
        "method": "contentforge_visual_qc_failure_report",
    }
    assert services.contentforge_visual_qc_waterfall(creator="Stacey") == {
        "method": "contentforge_visual_qc_waterfall",
    }
    assert services.contentforge_visual_qc_loss_analysis(creator="Stacey") == {
        "method": "contentforge_visual_qc_loss_analysis",
    }
    assert services.contentforge_visual_qc_repair_plan(creator="Stacey") == {
        "method": "contentforge_visual_qc_repair_plan",
    }
    assert services.contentforge_visual_qc_master_report(creator="Stacey") == {
        "method": "contentforge_visual_qc_master_report",
    }
    assert services.contentforge_visual_qc_failure_for_asset(
        {"id": "asset_1"}, "reel"
    ) == {
        "method": "contentforge_visual_qc_failure_for_asset",
    }
    assert services.contentforge_visual_qc_failure_category(
        {"id": "asset_1"},
        ["operator_visual_review_required"],
        {"canHandoff": False},
        {"publishableCandidate": False},
    ) == {"method": "contentforge_visual_qc_failure_category"}
    assert services.contentforge_non_visual_gates_pass({}, {}, {}, []) == {
        "method": "contentforge_non_visual_gates_pass",
    }
    assert services.contentforge_visual_qc_category_rows(
        [
            {"failureCategory": "operator_visual_review_required"},
        ]
    ) == {"method": "contentforge_visual_qc_category_rows"}
    assert services.contentforge_visual_qc_recovered_inventory(
        [
            {
                "failureCategory": "operator_visual_review_required",
                "estimatedInventoryGain": 1,
            },
        ],
        ["operator_visual_review_required"],
    ) == {"method": "contentforge_visual_qc_recovered_inventory"}
    assert services.contentforge_visual_qc_answer(
        {"failureCategory": "operator_visual_review_required"}, 1
    ) == {
        "method": "contentforge_visual_qc_answer",
    }

    assert calls == [
        (
            "contentforge_visual_qc_failure_report",
            (),
            {"creator": "Stacey", "current_inventory": 11},
        ),
        ("contentforge_visual_qc_waterfall", (), {"creator": "Stacey"}),
        ("contentforge_visual_qc_loss_analysis", (), {"creator": "Stacey"}),
        ("contentforge_visual_qc_repair_plan", (), {"creator": "Stacey"}),
        ("contentforge_visual_qc_master_report", (), {"creator": "Stacey"}),
        ("contentforge_visual_qc_failure_for_asset", ({"id": "asset_1"}, "reel"), {}),
        (
            "contentforge_visual_qc_failure_category",
            (
                {"id": "asset_1"},
                ["operator_visual_review_required"],
                {"canHandoff": False},
                {"publishableCandidate": False},
            ),
            {},
        ),
        ("contentforge_non_visual_gates_pass", ({}, {}, {}, []), {}),
        (
            "contentforge_visual_qc_category_rows",
            ([{"failureCategory": "operator_visual_review_required"}],),
            {},
        ),
        (
            "contentforge_visual_qc_recovered_inventory",
            (
                [
                    {
                        "failureCategory": "operator_visual_review_required",
                        "estimatedInventoryGain": 1,
                    }
                ],
                ["operator_visual_review_required"],
            ),
            {},
        ),
        (
            "contentforge_visual_qc_answer",
            ({"failureCategory": "operator_visual_review_required"}, 1),
            {},
        ),
    ]


def test_core_services_delegates_multi_blocker_unlock_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeMultiBlockerUnlock:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    services.multi_blocker_unlock = FakeMultiBlockerUnlock()

    assert services.multi_blocker_inventory_unlock_report(
        creator="Stacey", current_inventory=11
    ) == {
        "method": "multi_blocker_inventory_unlock_report",
    }
    assert services.multi_blocker_inventory_unlock_plan(creator="Stacey") == {
        "method": "multi_blocker_inventory_unlock_plan",
    }
    assert services.inventory_unlock_minimal_fix_set(creator="Stacey") == {
        "method": "inventory_unlock_minimal_fix_set",
    }
    assert services.inventory_unlock_master_report(creator="Stacey") == {
        "method": "inventory_unlock_master_report",
    }
    assert services.multi_blocker_asset_row(
        {"assetId": "asset_1", "blockingReasons": ["missing_audio"]}
    ) == {
        "method": "multi_blocker_asset_row",
    }
    assert services.multi_blocker_repair_class("missing_audio") == {
        "method": "multi_blocker_repair_class"
    }
    assert services.multi_blocker_combo_rows(
        [], current_inventory=0, required_inventory=1
    ) == {
        "method": "multi_blocker_combo_rows",
    }
    assert services.multi_blocker_assets_unlocked([], ["audio_failure"]) == {
        "method": "multi_blocker_assets_unlocked",
    }
    assert services.multi_blocker_estimated_minutes([], ["audio_failure"]) == {
        "method": "multi_blocker_estimated_minutes",
    }
    assert services.multi_blocker_combo_difficulty(["audio_failure"]) == {
        "method": "multi_blocker_combo_difficulty",
    }
    assert services.multi_blocker_best_combo([], 1) == {
        "method": "multi_blocker_best_combo",
    }
    assert services.multi_blocker_minimal_fix_set(
        [], current_inventory=0, required_inventory=1
    ) == {
        "method": "multi_blocker_minimal_fix_set",
    }

    assert calls == [
        (
            "multi_blocker_inventory_unlock_report",
            (),
            {"creator": "Stacey", "current_inventory": 11},
        ),
        ("multi_blocker_inventory_unlock_plan", (), {"creator": "Stacey"}),
        ("inventory_unlock_minimal_fix_set", (), {"creator": "Stacey"}),
        ("inventory_unlock_master_report", (), {"creator": "Stacey"}),
        (
            "multi_blocker_asset_row",
            ({"assetId": "asset_1", "blockingReasons": ["missing_audio"]},),
            {},
        ),
        ("multi_blocker_repair_class", ("missing_audio",), {}),
        (
            "multi_blocker_combo_rows",
            ([],),
            {"current_inventory": 0, "required_inventory": 1},
        ),
        ("multi_blocker_assets_unlocked", ([], ["audio_failure"]), {}),
        ("multi_blocker_estimated_minutes", ([], ["audio_failure"]), {}),
        ("multi_blocker_combo_difficulty", (["audio_failure"],), {}),
        ("multi_blocker_best_combo", ([], 1), {}),
        (
            "multi_blocker_minimal_fix_set",
            ([],),
            {"current_inventory": 0, "required_inventory": 1},
        ),
    ]


def test_core_services_delegates_lifecycle_reporting_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeLifecycleReporting:
        def __getattr__(self, name):
            def recorder(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return recorder

    services.lifecycle_reporting = FakeLifecycleReporting()
    asset = {"id": "asset_1"}
    plan = {"id": "plan_1"}
    post = {"id": "post_1"}
    snapshot = {"id": "snapshot_1"}

    assert services.campaign_readiness("may", user_id="user_1") == {
        "method": "campaign_readiness"
    }
    assert services.lifecycle_report(
        "may", user_id="user_1", include_threadsdash="off"
    ) == {"method": "lifecycle_report"}
    assert services.creator_os_lifecycle_dashboard(
        campaign="may", user_id="user_1"
    ) == {"method": "creator_os_lifecycle_dashboard"}
    assert services.creator_os_lifecycle_bucket({"currentState": "published"}) == {
        "method": "creator_os_lifecycle_bucket"
    }
    assert services.lifecycle_snapshots_by_asset("campaign_1") == {
        "method": "lifecycle_snapshots_by_asset"
    }
    assert services.lifecycle_threadsdash_indexes(
        campaign_slug="may",
        user_id="user_1",
        include_threadsdash="off",
        threadsdash_posts=[],
    ) == {
        "method": "lifecycle_threadsdash_indexes",
    }
    assert services.lifecycle_row(
        campaign={"id": "campaign_1", "slug": "may"},
        asset=asset,
        plan=plan,
        assignments=[],
        snapshots=[],
        threadsdash_posts=[],
    ) == {
        "method": "lifecycle_row",
    }
    assert services.derive_lifecycle_state(
        asset=asset,
        plan=plan,
        assignments=[],
        readiness={},
        post=post,
        snapshot=snapshot,
        mismatch={},
        media_issue=None,
    ) == {
        "method": "derive_lifecycle_state",
    }
    assert services.lifecycle_blocking_reason(["missing_audit"]) == {
        "method": "lifecycle_blocking_reason"
    }
    assert services.lifecycle_media_validation_issue(asset=asset, post=post) == {
        "method": "lifecycle_media_validation_issue"
    }
    assert services.latest_lifecycle_post([post]) == {"method": "latest_lifecycle_post"}
    assert services.lifecycle_snapshot_has_metrics(snapshot) == {
        "method": "lifecycle_snapshot_has_metrics"
    }
    assert services.lifecycle_is_past_due("2026-01-01T00:00:00+00:00") == {
        "method": "lifecycle_is_past_due"
    }
    assert services.lifecycle_past_due_resolved(post) == {
        "method": "lifecycle_past_due_resolved"
    }
    assert services.lifecycle_last_state_change(
        asset=asset, plan=plan, post=post, snapshot=snapshot
    ) == {"method": "lifecycle_last_state_change"}
    assert services.parse_lifecycle_time("2026-01-01T00:00:00+00:00") == {
        "method": "parse_lifecycle_time"
    }
    assert services.lifecycle_mismatch(
        asset=asset, plan=plan, post=post, snapshot=snapshot, context_fingerprint="abc"
    ) == {
        "method": "lifecycle_mismatch",
    }
    assert services.lifecycle_post_meta(post) == {"method": "lifecycle_post_meta"}
    assert services.lifecycle_fingerprint({"caption": "hello"}) == {
        "method": "lifecycle_fingerprint"
    }
    assert services.canonical_lifecycle_context(
        {"render_recipe": None, "caption": "hello"}
    ) == {"method": "canonical_lifecycle_context"}
    assert services.compact_lifecycle_post(post) == {"method": "compact_lifecycle_post"}
    assert services.compact_lifecycle_snapshot(snapshot) == {
        "method": "compact_lifecycle_snapshot"
    }

    assert calls == [
        ("campaign_readiness", ("may",), {"user_id": "user_1"}),
        (
            "lifecycle_report",
            ("may",),
            {"user_id": "user_1", "include_threadsdash": "off"},
        ),
        (
            "creator_os_lifecycle_dashboard",
            (),
            {"campaign": "may", "user_id": "user_1"},
        ),
        ("creator_os_lifecycle_bucket", ({"currentState": "published"},), {}),
        ("lifecycle_snapshots_by_asset", ("campaign_1",), {}),
        (
            "lifecycle_threadsdash_indexes",
            (),
            {
                "campaign_slug": "may",
                "user_id": "user_1",
                "include_threadsdash": "off",
                "threadsdash_posts": [],
            },
        ),
        (
            "lifecycle_row",
            (),
            {
                "campaign": {"id": "campaign_1", "slug": "may"},
                "asset": asset,
                "plan": plan,
                "assignments": [],
                "snapshots": [],
                "threadsdash_posts": [],
            },
        ),
        (
            "derive_lifecycle_state",
            (),
            {
                "asset": asset,
                "plan": plan,
                "assignments": [],
                "readiness": {},
                "post": post,
                "snapshot": snapshot,
                "mismatch": {},
                "media_issue": None,
            },
        ),
        ("lifecycle_blocking_reason", (["missing_audit"],), {}),
        ("lifecycle_media_validation_issue", (), {"asset": asset, "post": post}),
        ("latest_lifecycle_post", ([post],), {}),
        ("lifecycle_snapshot_has_metrics", (snapshot,), {}),
        ("lifecycle_is_past_due", ("2026-01-01T00:00:00+00:00",), {}),
        ("lifecycle_past_due_resolved", (post,), {}),
        (
            "lifecycle_last_state_change",
            (),
            {"asset": asset, "plan": plan, "post": post, "snapshot": snapshot},
        ),
        ("parse_lifecycle_time", ("2026-01-01T00:00:00+00:00",), {}),
        (
            "lifecycle_mismatch",
            (),
            {
                "asset": asset,
                "plan": plan,
                "post": post,
                "snapshot": snapshot,
                "context_fingerprint": "abc",
            },
        ),
        ("lifecycle_post_meta", (post,), {}),
        ("lifecycle_fingerprint", ({"caption": "hello"},), {}),
        (
            "canonical_lifecycle_context",
            ({"render_recipe": None, "caption": "hello"},),
            {},
        ),
        ("compact_lifecycle_post", (post,), {}),
        ("compact_lifecycle_snapshot", (snapshot,), {}),
    ]


def test_campaign_factory_delegates_performance_summary_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def _fake(*args, **kwargs):
                calls.append((name, args, kwargs))
                if name == "add_leaderboard_snapshot":
                    return None
                return {"method": name, "args": args, "kwargs": kwargs}

            return _fake

    factory.services = FakeServices()
    snapshots = [{"renderedAssetId": "asset_1", "postId": "post_1"}]
    row = {"raw_json": "{}", "content_surface": "reel"}
    summary = {"count": 3, "totals": {"views": 100}, "rates": {"engagementRate": 0.05}}
    source = {"count": 1}
    caption = {"count": 1}
    recipe = {"count": 1}
    items = {}
    campaign_meta = {"hook_key": "hook_1"}

    assert factory.performance_summary("may")["method"] == "performance_summary"
    assert factory.caption_outcome_report("may")["method"] == "caption_outcome_report"
    assert (
        factory._performance_for_asset(
            {"id": "asset_1", "caption": "Hi", "source_asset_id": "src_1"}
        )["method"]
        == "performance_for_asset"
    )
    assert (
        factory._performance_snapshot_payload(row)["method"]
        == "performance_snapshot_payload"
    )
    assert (
        factory._group_performance(snapshots, "renderedAssetId")["method"]
        == "group_performance"
    )
    assert (
        factory._aggregate_performance(snapshots)["method"] == "aggregate_performance"
    )
    assert (
        factory._performance_metric_contract(row)["method"]
        == "performance_metric_contract"
    )
    assert (
        factory._default_performance_metric_names("reel")["method"]
        == "default_performance_metric_names"
    )
    assert (
        factory._performance_leaderboards(snapshots)["method"]
        == "performance_leaderboards"
    )
    assert (
        factory._caption_outcome_manual_review(snapshots)["method"]
        == "caption_outcome_manual_review"
    )
    assert (
        factory._has_caption_outcome_context(snapshots[0])["method"]
        == "has_caption_outcome_context"
    )
    assert (
        factory._caption_outcome_snapshot_with_placement(snapshots[0])["method"]
        == "caption_outcome_snapshot_with_placement"
    )
    assert (
        factory._caption_outcome_group(snapshots, "captionBank", "captionBank")[
            "method"
        ]
        == "caption_outcome_group"
    )
    assert (
        factory._caption_outcome_contexts_for_group(snapshots)["method"]
        == "caption_outcome_contexts_for_group"
    )
    assert (
        factory._add_leaderboard_snapshot(
            items, "hook_1", snapshots[0], {"hook": {"key": "hook_1"}}
        )
        is None
    )
    assert (
        factory._rank_leaderboard_entries(items)["method"] == "rank_leaderboard_entries"
    )
    assert (
        factory._performance_recommendation_label(summary)["method"]
        == "performance_recommendation_label"
    )
    assert (
        factory._performance_quality_score(summary)["method"]
        == "performance_quality_score"
    )
    assert (
        factory._performance_planning_score(summary)["method"]
        == "performance_planning_score"
    )
    assert (
        factory._performance_snapshot_dimensions(row)["method"]
        == "performance_snapshot_dimensions"
    )
    assert (
        factory._performance_hook_dimension(campaign_meta)["method"]
        == "performance_hook_dimension"
    )
    assert (
        factory._performance_audio_dimension(campaign_meta)["method"]
        == "performance_audio_dimension"
    )
    assert (
        factory._performance_reference_format_dimension(campaign_meta)["method"]
        == "performance_reference_format_dimension"
    )
    assert (
        factory._performance_prompt_pattern_dimension(campaign_meta)["method"]
        == "performance_prompt_pattern_dimension"
    )
    assert (
        factory._performance_pattern_card_dimension(campaign_meta)["method"]
        == "performance_pattern_card_dimension"
    )
    assert (
        factory._performance_model_account_dimension(campaign_meta, row)["method"]
        == "performance_model_account_dimension"
    )
    assert (
        factory._performance_caption_formula_dimension(campaign_meta)["method"]
        == "performance_caption_formula_dimension"
    )
    assert (
        factory._performance_variation_preset_dimension(campaign_meta, row)["method"]
        == "performance_variation_preset_dimension"
    )
    assert (
        factory._performance_score(source=source, caption=caption, recipe=recipe)[
            "method"
        ]
        == "performance_score"
    )

    assert calls == [
        ("performance_summary", ("may",), {}),
        ("caption_outcome_report", ("may",), {}),
        (
            "performance_for_asset",
            ({"id": "asset_1", "caption": "Hi", "source_asset_id": "src_1"},),
            {},
        ),
        ("performance_snapshot_payload", (row,), {}),
        (
            "group_performance",
            (snapshots, "renderedAssetId"),
            {"account_baselines": None},
        ),
        ("aggregate_performance", (snapshots,), {"account_baselines": None}),
        ("performance_metric_contract", (row,), {}),
        ("default_performance_metric_names", ("reel",), {}),
        ("performance_leaderboards", (snapshots,), {"account_baselines": None}),
        ("caption_outcome_manual_review", (snapshots,), {}),
        ("has_caption_outcome_context", (snapshots[0],), {}),
        ("caption_outcome_snapshot_with_placement", (snapshots[0],), {}),
        ("caption_outcome_group", (snapshots, "captionBank", "captionBank"), {}),
        ("caption_outcome_contexts_for_group", (snapshots,), {}),
        (
            "add_leaderboard_snapshot",
            (items, "hook_1", snapshots[0], {"hook": {"key": "hook_1"}}),
            {},
        ),
        (
            "rank_leaderboard_entries",
            (items,),
            {"limit": 20, "account_baselines": None},
        ),
        ("performance_recommendation_label", (summary,), {}),
        ("performance_quality_score", (summary,), {}),
        ("performance_planning_score", (summary,), {}),
        ("performance_snapshot_dimensions", (row,), {}),
        ("performance_hook_dimension", (campaign_meta,), {}),
        ("performance_audio_dimension", (campaign_meta,), {}),
        ("performance_reference_format_dimension", (campaign_meta,), {}),
        ("performance_prompt_pattern_dimension", (campaign_meta,), {}),
        ("performance_pattern_card_dimension", (campaign_meta,), {}),
        ("performance_model_account_dimension", (campaign_meta, row), {}),
        ("performance_caption_formula_dimension", (campaign_meta,), {}),
        ("performance_variation_preset_dimension", (campaign_meta, row), {}),
        (
            "performance_score",
            (),
            {"source": source, "caption": caption, "recipe": recipe},
        ),
    ]


def test_core_services_delegates_performance_summary_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakePerformanceSummary:
        def __getattr__(self, name):
            def _fake(*args, **kwargs):
                calls.append((name, args, kwargs))
                if name == "add_leaderboard_snapshot":
                    return None
                return {"method": name, "args": args, "kwargs": kwargs}

            return _fake

    services.performance_summary_repo = FakePerformanceSummary()
    snapshots = [{"renderedAssetId": "asset_1", "postId": "post_1"}]
    row = {"raw_json": "{}", "content_surface": "reel"}
    summary = {"count": 3, "totals": {"views": 100}, "rates": {"engagementRate": 0.05}}
    source = {"count": 1}
    caption = {"count": 1}
    recipe = {"count": 1}
    items = {}
    campaign_meta = {"hook_key": "hook_1"}

    assert services.performance_summary("may")["method"] == "performance_summary"
    assert services.caption_outcome_report("may")["method"] == "caption_outcome_report"
    assert (
        services.performance_for_asset(
            {"id": "asset_1", "caption": "Hi", "source_asset_id": "src_1"}
        )["method"]
        == "performance_for_asset"
    )
    assert (
        services.performance_snapshot_payload(row)["method"]
        == "performance_snapshot_payload"
    )
    assert (
        services.group_performance(snapshots, "renderedAssetId")["method"]
        == "group_performance"
    )
    assert (
        services.aggregate_performance(snapshots)["method"] == "aggregate_performance"
    )
    assert (
        services.performance_metric_contract(row)["method"]
        == "performance_metric_contract"
    )
    assert (
        services.default_performance_metric_names("reel")["method"]
        == "default_performance_metric_names"
    )
    assert (
        services.performance_leaderboards(snapshots)["method"]
        == "performance_leaderboards"
    )
    assert (
        services.caption_outcome_manual_review(snapshots)["method"]
        == "caption_outcome_manual_review"
    )
    assert (
        services.has_caption_outcome_context(snapshots[0])["method"]
        == "has_caption_outcome_context"
    )
    assert (
        services.caption_outcome_snapshot_with_placement(snapshots[0])["method"]
        == "caption_outcome_snapshot_with_placement"
    )
    assert (
        services.caption_outcome_group(snapshots, "captionBank", "captionBank")[
            "method"
        ]
        == "caption_outcome_group"
    )
    assert (
        services.caption_outcome_contexts_for_group(snapshots)["method"]
        == "caption_outcome_contexts_for_group"
    )
    assert (
        services.add_leaderboard_snapshot(
            items, "hook_1", snapshots[0], {"hook": {"key": "hook_1"}}
        )
        is None
    )
    assert (
        services.rank_leaderboard_entries(items)["method"] == "rank_leaderboard_entries"
    )
    assert (
        services.performance_recommendation_label(summary)["method"]
        == "performance_recommendation_label"
    )
    assert (
        services.performance_quality_score(summary)["method"]
        == "performance_quality_score"
    )
    assert (
        services.performance_planning_score(summary)["method"]
        == "performance_planning_score"
    )
    assert (
        services.performance_snapshot_dimensions(row)["method"]
        == "performance_snapshot_dimensions"
    )
    assert (
        services.performance_hook_dimension(campaign_meta)["method"]
        == "performance_hook_dimension"
    )
    assert (
        services.performance_audio_dimension(campaign_meta)["method"]
        == "performance_audio_dimension"
    )
    assert (
        services.performance_reference_format_dimension(campaign_meta)["method"]
        == "performance_reference_format_dimension"
    )
    assert (
        services.performance_prompt_pattern_dimension(campaign_meta)["method"]
        == "performance_prompt_pattern_dimension"
    )
    assert (
        services.performance_pattern_card_dimension(campaign_meta)["method"]
        == "performance_pattern_card_dimension"
    )
    assert (
        services.performance_model_account_dimension(campaign_meta, row)["method"]
        == "performance_model_account_dimension"
    )
    assert (
        services.performance_caption_formula_dimension(campaign_meta)["method"]
        == "performance_caption_formula_dimension"
    )
    assert (
        services.performance_variation_preset_dimension(campaign_meta, row)["method"]
        == "performance_variation_preset_dimension"
    )
    assert (
        services.performance_score(source=source, caption=caption, recipe=recipe)[
            "method"
        ]
        == "performance_score"
    )

    assert calls == [
        ("performance_summary", ("may",), {}),
        ("caption_outcome_report", ("may",), {}),
        (
            "performance_for_asset",
            ({"id": "asset_1", "caption": "Hi", "source_asset_id": "src_1"},),
            {},
        ),
        ("performance_snapshot_payload", (row,), {}),
        (
            "group_performance",
            (snapshots, "renderedAssetId"),
            {"account_baselines": None},
        ),
        ("aggregate_performance", (snapshots,), {"account_baselines": None}),
        ("performance_metric_contract", (row,), {}),
        ("default_performance_metric_names", ("reel",), {}),
        ("performance_leaderboards", (snapshots,), {"account_baselines": None}),
        ("caption_outcome_manual_review", (snapshots,), {}),
        ("has_caption_outcome_context", (snapshots[0],), {}),
        ("caption_outcome_snapshot_with_placement", (snapshots[0],), {}),
        ("caption_outcome_group", (snapshots, "captionBank", "captionBank"), {}),
        ("caption_outcome_contexts_for_group", (snapshots,), {}),
        (
            "add_leaderboard_snapshot",
            (items, "hook_1", snapshots[0], {"hook": {"key": "hook_1"}}),
            {},
        ),
        (
            "rank_leaderboard_entries",
            (items,),
            {"limit": 20, "account_baselines": None},
        ),
        ("performance_recommendation_label", (summary,), {}),
        ("performance_quality_score", (summary,), {}),
        ("performance_planning_score", (summary,), {}),
        ("performance_snapshot_dimensions", (row,), {}),
        ("performance_hook_dimension", (campaign_meta,), {}),
        ("performance_audio_dimension", (campaign_meta,), {}),
        ("performance_reference_format_dimension", (campaign_meta,), {}),
        ("performance_prompt_pattern_dimension", (campaign_meta,), {}),
        ("performance_pattern_card_dimension", (campaign_meta,), {}),
        ("performance_model_account_dimension", (campaign_meta, row), {}),
        ("performance_caption_formula_dimension", (campaign_meta,), {}),
        ("performance_variation_preset_dimension", (campaign_meta, row), {}),
        (
            "performance_score",
            (),
            {"source": source, "caption": caption, "recipe": recipe},
        ),
    ]


def test_campaign_factory_delegates_audio_recommendation_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def _fake(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name, "args": args, "kwargs": kwargs}

            return _fake

    factory.services = FakeServices()
    item = {"id": "aud_1", "title": "Runway Pop", "platform": "instagram"}
    row = {"id": "aud_1", "raw_json": "{}"}
    recs = [{"audioTitle": "Runway Pop"}]
    risks = ["needs_ig_lookup"]
    components = {"trend": 90.0}

    assert (
        factory.import_audio_catalog(Path("audio.json"))["method"]
        == "import_audio_catalog"
    )
    assert (
        factory.import_audio_memory(Path("audio.json"))["method"]
        == "import_audio_memory"
    )
    assert (
        factory.audio_catalog(platform="instagram", limit=3)["method"]
        == "audio_catalog"
    )
    assert (
        factory.audio_memory(platform="instagram", account="ig_1", limit=3)["method"]
        == "audio_memory"
    )
    assert (
        factory.recommend_audio(
            platform="instagram",
            content_tags=["mirror"],
            account_tags=["ig_1"],
            limit=2,
        )["method"]
        == "recommend_audio"
    )
    assert (
        factory.decide_audio(
            platform="instagram", recommendation_item_id="rec_1", select=True
        )["method"]
        == "decide_audio"
    )
    assert (
        factory.decide_audio_from_recommendations(recs, requested_platform="instagram")[
            "method"
        ]
        == "decide_audio_from_recommendations"
    )
    assert (
        factory._audio_decision_score(item, requested_platform="instagram")["method"]
        == "audio_decision_score"
    )
    assert (
        factory._audio_decision_confidence(item)["method"]
        == "audio_decision_confidence"
    )
    assert factory._audio_when_to_use(item, risks)["method"] == "audio_when_to_use"
    assert (
        factory._audio_when_not_to_use(item, risks)["method"] == "audio_when_not_to_use"
    )
    assert (
        factory._audio_operator_instruction(item)["method"]
        == "audio_operator_instruction"
    )
    assert (
        factory._is_generic_audio_title("Instagram audio abc", "instagram")["method"]
        == "is_generic_audio_title"
    )
    assert factory._audio_catalog_payload(row)["method"] == "audio_catalog_payload"
    assert (
        factory._audio_performance_summary(item, campaign_id="camp_1", account="ig_1")[
            "method"
        ]
        == "audio_performance_summary"
    )
    assert (
        factory._audio_fatigue_summary(item, campaign_id="camp_1", account="ig_1")[
            "method"
        ]
        == "audio_fatigue_summary"
    )
    assert factory._audio_key(item)["method"] == "audio_key"
    assert (
        factory._score_audio_catalog_item(item, {"mirror"}, {"ig_1"})["method"]
        == "score_audio_catalog_item"
    )
    assert (
        factory._score_audio_catalog_item_v2(
            item, {"mirror"}, {"ig_1"}, account="ig_1"
        )["method"]
        == "score_audio_catalog_item_v2"
    )
    assert factory._audio_trend_component(item)["method"] == "audio_trend_component"
    assert (
        factory._audio_velocity_component(item)["method"] == "audio_velocity_component"
    )
    assert (
        factory._audio_performance_component(item)["method"]
        == "audio_performance_component"
    )
    assert (
        factory._audio_account_fit_component(item, {"ig_1"})["method"]
        == "audio_account_fit_component"
    )
    assert (
        factory._audio_creator_fit_component(item, {"mirror"})["method"]
        == "audio_creator_fit_component"
    )
    assert (
        factory._audio_fatigue_safety_component(item)["method"]
        == "audio_fatigue_safety_component"
    )
    assert (
        factory._audio_recommendation_confidence(item, components)["method"]
        == "audio_recommendation_confidence"
    )
    assert (
        factory._latest_audio_trend_snapshot_payload(item)["method"]
        == "latest_audio_trend_snapshot_payload"
    )
    assert (
        factory._audio_memory_trust_summary([item])["method"]
        == "audio_memory_trust_summary"
    )
    assert (
        factory._contentforge_audio_fit_for_item(
            item, {"mirror"}, visual_signal={"energy": "high"}
        )["method"]
        == "contentforge_audio_fit_for_item"
    )
    assert (
        factory._audio_catalog_recommendation(item)["method"]
        == "audio_catalog_recommendation"
    )
    assert factory._norm_tag("Fit Check")["method"] == "norm_tag"

    assert calls == [
        ("import_audio_catalog", (Path("audio.json"),), {}),
        ("import_audio_memory", (Path("audio.json"),), {}),
        ("audio_catalog", (), {"platform": "instagram", "limit": 3}),
        ("audio_memory", (), {"platform": "instagram", "account": "ig_1", "limit": 3}),
        (
            "recommend_audio",
            (),
            {
                "platform": "instagram",
                "content_tags": ["mirror"],
                "account_tags": ["ig_1"],
                "campaign_slug": None,
                "recommendation_item_id": None,
                "account": None,
                "visual_signal": None,
                "limit": 2,
            },
        ),
        (
            "decide_audio",
            (),
            {
                "platform": "instagram",
                "campaign_slug": None,
                "recommendation_item_id": "rec_1",
                "account": None,
                "content_tags": None,
                "account_tags": None,
                "visual_signal": None,
                "limit": 5,
                "select": True,
                "operator": None,
            },
        ),
        (
            "decide_audio_from_recommendations",
            (recs,),
            {
                "requested_platform": "instagram",
                "content_tags": None,
                "account_tags": None,
            },
        ),
        ("audio_decision_score", (item,), {"requested_platform": "instagram"}),
        ("audio_decision_confidence", (item,), {}),
        ("audio_when_to_use", (item, risks), {}),
        ("audio_when_not_to_use", (item, risks), {}),
        ("audio_operator_instruction", (item,), {}),
        ("is_generic_audio_title", ("Instagram audio abc", "instagram"), {}),
        ("audio_catalog_payload", (row,), {}),
        (
            "audio_performance_summary",
            (item,),
            {"campaign_id": "camp_1", "account": "ig_1"},
        ),
        (
            "audio_fatigue_summary",
            (item,),
            {"campaign_id": "camp_1", "account": "ig_1"},
        ),
        ("audio_key", (item,), {}),
        ("score_audio_catalog_item", (item, {"mirror"}, {"ig_1"}), {}),
        (
            "score_audio_catalog_item_v2",
            (item, {"mirror"}, {"ig_1"}),
            {"account": "ig_1"},
        ),
        ("audio_trend_component", (item,), {}),
        ("audio_velocity_component", (item,), {}),
        ("audio_performance_component", (item,), {}),
        ("audio_account_fit_component", (item, {"ig_1"}), {}),
        ("audio_creator_fit_component", (item, {"mirror"}), {}),
        ("audio_fatigue_safety_component", (item,), {}),
        ("audio_recommendation_confidence", (item, components), {}),
        ("latest_audio_trend_snapshot_payload", (item,), {}),
        ("audio_memory_trust_summary", ([item],), {}),
        (
            "contentforge_audio_fit_for_item",
            (item, {"mirror"}),
            {"visual_signal": {"energy": "high"}},
        ),
        ("audio_catalog_recommendation", (item,), {}),
        ("norm_tag", ("Fit Check",), {}),
    ]


def test_core_services_delegates_audio_recommendation_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeAudioRecommendations:
        def __getattr__(self, name):
            def _fake(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name, "args": args, "kwargs": kwargs}

            return _fake

    services.audio_recommendations = FakeAudioRecommendations()
    item = {"id": "aud_1", "title": "Runway Pop", "platform": "instagram"}
    row = {"id": "aud_1", "raw_json": "{}"}
    recs = [{"audioTitle": "Runway Pop"}]
    risks = ["needs_ig_lookup"]
    components = {"trend": 90.0}

    assert (
        services.import_audio_catalog(Path("audio.json"))["method"]
        == "import_audio_catalog"
    )
    assert (
        services.import_audio_memory(Path("audio.json"))["method"]
        == "import_audio_memory"
    )
    assert (
        services.audio_catalog(platform="instagram", limit=3)["method"]
        == "audio_catalog"
    )
    assert (
        services.audio_memory(platform="instagram", account="ig_1", limit=3)["method"]
        == "audio_memory"
    )
    assert (
        services.recommend_audio(
            platform="instagram",
            content_tags=["mirror"],
            account_tags=["ig_1"],
            limit=2,
        )["method"]
        == "recommend_audio"
    )
    assert (
        services.decide_audio(
            platform="instagram", recommendation_item_id="rec_1", select=True
        )["method"]
        == "decide_audio"
    )
    assert (
        services.decide_audio_from_recommendations(
            recs, requested_platform="instagram"
        )["method"]
        == "decide_audio_from_recommendations"
    )
    assert (
        services.audio_decision_score(item, requested_platform="instagram")["method"]
        == "audio_decision_score"
    )
    assert (
        services.audio_decision_confidence(item)["method"]
        == "audio_decision_confidence"
    )
    assert services.audio_when_to_use(item, risks)["method"] == "audio_when_to_use"
    assert (
        services.audio_when_not_to_use(item, risks)["method"] == "audio_when_not_to_use"
    )
    assert (
        services.audio_operator_instruction(item)["method"]
        == "audio_operator_instruction"
    )
    assert (
        services.is_generic_audio_title("Instagram audio abc", "instagram")["method"]
        == "is_generic_audio_title"
    )
    assert services.audio_catalog_payload(row)["method"] == "audio_catalog_payload"
    assert (
        services.audio_performance_summary(item, campaign_id="camp_1", account="ig_1")[
            "method"
        ]
        == "audio_performance_summary"
    )
    assert (
        services.audio_fatigue_summary(item, campaign_id="camp_1", account="ig_1")[
            "method"
        ]
        == "audio_fatigue_summary"
    )
    assert services.audio_key(item)["method"] == "audio_key"
    assert (
        services.score_audio_catalog_item(item, {"mirror"}, {"ig_1"})["method"]
        == "score_audio_catalog_item"
    )
    assert (
        services.score_audio_catalog_item_v2(
            item, {"mirror"}, {"ig_1"}, account="ig_1"
        )["method"]
        == "score_audio_catalog_item_v2"
    )
    assert services.audio_trend_component(item)["method"] == "audio_trend_component"
    assert (
        services.audio_velocity_component(item)["method"] == "audio_velocity_component"
    )
    assert (
        services.audio_performance_component(item)["method"]
        == "audio_performance_component"
    )
    assert (
        services.audio_account_fit_component(item, {"ig_1"})["method"]
        == "audio_account_fit_component"
    )
    assert (
        services.audio_creator_fit_component(item, {"mirror"})["method"]
        == "audio_creator_fit_component"
    )
    assert (
        services.audio_fatigue_safety_component(item)["method"]
        == "audio_fatigue_safety_component"
    )
    assert (
        services.audio_recommendation_confidence(item, components)["method"]
        == "audio_recommendation_confidence"
    )
    assert (
        services.latest_audio_trend_snapshot_payload(item)["method"]
        == "latest_audio_trend_snapshot_payload"
    )
    assert (
        services.audio_memory_trust_summary([item])["method"]
        == "audio_memory_trust_summary"
    )
    assert (
        services.contentforge_audio_fit_for_item(
            item, {"mirror"}, visual_signal={"energy": "high"}
        )["method"]
        == "contentforge_audio_fit_for_item"
    )
    assert (
        services.audio_catalog_recommendation(item)["method"]
        == "audio_catalog_recommendation"
    )
    assert services.norm_tag("Fit Check")["method"] == "norm_tag"

    assert calls == [
        ("import_audio_catalog", (Path("audio.json"),), {}),
        ("import_audio_memory", (Path("audio.json"),), {}),
        ("audio_catalog", (), {"platform": "instagram", "limit": 3}),
        ("audio_memory", (), {"platform": "instagram", "account": "ig_1", "limit": 3}),
        (
            "recommend_audio",
            (),
            {
                "platform": "instagram",
                "content_tags": ["mirror"],
                "account_tags": ["ig_1"],
                "campaign_slug": None,
                "recommendation_item_id": None,
                "account": None,
                "visual_signal": None,
                "limit": 2,
            },
        ),
        (
            "decide_audio",
            (),
            {
                "platform": "instagram",
                "campaign_slug": None,
                "recommendation_item_id": "rec_1",
                "account": None,
                "content_tags": None,
                "account_tags": None,
                "visual_signal": None,
                "limit": 5,
                "select": True,
                "operator": None,
            },
        ),
        (
            "decide_audio_from_recommendations",
            (recs,),
            {
                "requested_platform": "instagram",
                "content_tags": None,
                "account_tags": None,
            },
        ),
        ("audio_decision_score", (item,), {"requested_platform": "instagram"}),
        ("audio_decision_confidence", (item,), {}),
        ("audio_when_to_use", (item, risks), {}),
        ("audio_when_not_to_use", (item, risks), {}),
        ("audio_operator_instruction", (item,), {}),
        ("is_generic_audio_title", ("Instagram audio abc", "instagram"), {}),
        ("audio_catalog_payload", (row,), {}),
        (
            "audio_performance_summary",
            (item,),
            {"campaign_id": "camp_1", "account": "ig_1"},
        ),
        (
            "audio_fatigue_summary",
            (item,),
            {"campaign_id": "camp_1", "account": "ig_1"},
        ),
        ("audio_key", (item,), {}),
        ("score_audio_catalog_item", (item, {"mirror"}, {"ig_1"}), {}),
        (
            "score_audio_catalog_item_v2",
            (item, {"mirror"}, {"ig_1"}),
            {"account": "ig_1"},
        ),
        ("audio_trend_component", (item,), {}),
        ("audio_velocity_component", (item,), {}),
        ("audio_performance_component", (item,), {}),
        ("audio_account_fit_component", (item, {"ig_1"}), {}),
        ("audio_creator_fit_component", (item, {"mirror"}), {}),
        ("audio_fatigue_safety_component", (item,), {}),
        ("audio_recommendation_confidence", (item, components), {}),
        ("latest_audio_trend_snapshot_payload", (item,), {}),
        ("audio_memory_trust_summary", ([item],), {}),
        (
            "contentforge_audio_fit_for_item",
            (item, {"mirror"}),
            {"visual_signal": {"energy": "high"}},
        ),
        ("audio_catalog_recommendation", (item,), {}),
        ("norm_tag", ("Fit Check",), {}),
    ]


def test_campaign_factory_delegates_audio_operation_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def _fake(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name, "args": args, "kwargs": kwargs}

            return _fake

    factory.services = FakeServices()
    asset = {"id": "asset_1", "captionGeneration": {}}
    intent = {
        "status": "attached",
        "operator_selection": {
            "audio_id": "aud_1",
            "selected_at": "now",
            "attached_at": "now",
        },
    }
    snapshot = {"campaign_id": "camp_1", "views": 100, "likes": 5}

    assert (
        factory.attach_audio_to_distribution_plan("dist_1", track_id="aud_1")["method"]
        == "attach_audio_to_distribution_plan"
    )
    assert (
        factory.attach_cover_frame_to_rendered_asset("asset_1", seconds=1.5)["method"]
        == "attach_cover_frame_to_rendered_asset"
    )
    assert (
        factory.select_audio_for_recommendation("rec_1", "aud_1", operator="tester")[
            "method"
        ]
        == "select_audio_for_recommendation"
    )
    assert (
        factory.verify_audio_for_post("post_1", proof_url="https://proof.example/aud")[
            "method"
        ]
        == "verify_audio_for_post"
    )
    assert (
        factory._audio_catalog_row("aud_1", allow_locator=True)["method"]
        == "audio_catalog_row"
    )
    assert (
        factory._audio_selection_payload("sel_1")["method"] == "audio_selection_payload"
    )
    assert (
        factory._link_audio_selection_graph(
            selection_id="sel_1", audio_catalog_id="aud_1", campaign_id="camp_1"
        )["method"]
        == "link_audio_selection_graph"
    )
    assert (
        factory._resolve_audio_exception_for_recommendation(
            "rec_1", operator="tester", proof_url="https://proof.example/aud"
        )["method"]
        == "resolve_audio_exception_for_recommendation"
    )
    assert (
        factory.record_audio_performance_snapshot(snapshot, commit=False)["method"]
        == "record_audio_performance_snapshot"
    )
    assert (
        factory._performance_snapshot_score(snapshot)["method"]
        == "performance_snapshot_score"
    )
    assert factory.audio_workflow_summary([asset])["method"] == "audio_workflow_summary"
    assert (
        factory._dashboard_audio_intent_for_asset(asset)["method"]
        == "dashboard_audio_intent_for_asset"
    )
    assert (
        factory._audio_task_for_dashboard_intent(intent)["method"]
        == "audio_task_for_dashboard_intent"
    )
    assert factory._normalize_seconds("1.25")["method"] == "normalize_seconds"
    assert (
        factory._first_metadata_value({"x": "y"}, "x")["method"]
        == "first_metadata_value"
    )
    assert (
        factory._normalize_audio_segment({"start_seconds": 1})["method"]
        == "normalize_audio_segment"
    )
    assert (
        factory._audio_segment_for_asset(intent)["method"] == "audio_segment_for_asset"
    )
    assert (
        factory._normalize_cover_frame({"seconds": 2})["method"]
        == "normalize_cover_frame"
    )
    assert factory._cover_frame_for_asset(asset)["method"] == "cover_frame_for_asset"
    assert (
        factory._audio_selection_for_asset(asset)["method"]
        == "audio_selection_for_asset"
    )
    assert (
        factory._audio_intent_is_attached(intent, "aud_1")["method"]
        == "audio_intent_is_attached"
    )
    assert (
        factory._audio_intent_claims_embedded_media(intent)["method"]
        == "audio_intent_claims_embedded_media"
    )
    assert (
        factory._embedded_audio_verified("/tmp/reel.mp4")["method"]
        == "embedded_audio_verified"
    )

    assert calls == [
        (
            "attach_audio_to_distribution_plan",
            ("dist_1",),
            {
                "track_id": "aud_1",
                "track_name": None,
                "source": None,
                "audio_url": None,
                "native_audio_id": None,
                "local_winner_audio_id": None,
                "selected_reason": None,
                "segment_start_seconds": None,
                "segment_duration_seconds": None,
                "segment_label": None,
                "segment_reason": None,
                "operator": None,
                "notes": None,
            },
        ),
        (
            "attach_cover_frame_to_rendered_asset",
            ("asset_1",),
            {
                "seconds": 1.5,
                "cover_image_path": None,
                "cover_image_url": None,
                "cover_image_hash": None,
                "reason": None,
                "operator": None,
            },
        ),
        (
            "select_audio_for_recommendation",
            ("rec_1", "aud_1"),
            {"operator": "tester", "notes": None},
        ),
        (
            "verify_audio_for_post",
            ("post_1",),
            {
                "proof_url": "https://proof.example/aud",
                "proof_note": None,
                "operator": None,
            },
        ),
        ("audio_catalog_row", ("aud_1",), {"allow_locator": True}),
        ("audio_selection_payload", ("sel_1",), {}),
        (
            "link_audio_selection_graph",
            (),
            {
                "selection_id": "sel_1",
                "recommendation_item_id": None,
                "recommendation_graph_id": None,
                "audio_catalog_id": "aud_1",
                "post_id": None,
                "performance_snapshot_id": None,
                "campaign_id": "camp_1",
            },
        ),
        (
            "resolve_audio_exception_for_recommendation",
            ("rec_1",),
            {"operator": "tester", "proof_url": "https://proof.example/aud"},
        ),
        ("record_audio_performance_snapshot", (snapshot,), {"commit": False}),
        ("performance_snapshot_score", (snapshot,), {}),
        ("audio_workflow_summary", ([asset],), {}),
        ("dashboard_audio_intent_for_asset", (asset,), {}),
        ("audio_task_for_dashboard_intent", (intent,), {}),
        ("normalize_seconds", ("1.25",), {}),
        ("first_metadata_value", ({"x": "y"}, "x"), {}),
        ("normalize_audio_segment", ({"start_seconds": 1},), {}),
        ("audio_segment_for_asset", (intent,), {}),
        ("normalize_cover_frame", ({"seconds": 2},), {}),
        ("cover_frame_for_asset", (asset,), {"caption_context": None}),
        ("audio_selection_for_asset", (asset,), {}),
        ("audio_intent_is_attached", (intent, "aud_1"), {}),
        ("audio_intent_claims_embedded_media", (intent,), {}),
        ("embedded_audio_verified", ("/tmp/reel.mp4",), {}),
    ]


def test_core_services_delegates_audio_operation_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeAudioOperations:
        def __getattr__(self, name):
            def _fake(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name, "args": args, "kwargs": kwargs}

            return _fake

    services.audio_operations = FakeAudioOperations()
    asset = {"id": "asset_1", "captionGeneration": {}}
    intent = {
        "status": "attached",
        "operator_selection": {
            "audio_id": "aud_1",
            "selected_at": "now",
            "attached_at": "now",
        },
    }
    snapshot = {"campaign_id": "camp_1", "views": 100, "likes": 5}

    assert (
        services.attach_audio_to_distribution_plan("dist_1", track_id="aud_1")["method"]
        == "attach_audio_to_distribution_plan"
    )
    assert (
        services.attach_cover_frame_to_rendered_asset("asset_1", seconds=1.5)["method"]
        == "attach_cover_frame_to_rendered_asset"
    )
    assert (
        services.select_audio_for_recommendation("rec_1", "aud_1", operator="tester")[
            "method"
        ]
        == "select_audio_for_recommendation"
    )
    assert (
        services.verify_audio_for_post("post_1", proof_url="https://proof.example/aud")[
            "method"
        ]
        == "verify_audio_for_post"
    )
    assert (
        services.audio_catalog_row("aud_1", allow_locator=True)["method"]
        == "audio_catalog_row"
    )
    assert (
        services.audio_selection_payload("sel_1")["method"] == "audio_selection_payload"
    )
    assert (
        services.link_audio_selection_graph(
            selection_id="sel_1", audio_catalog_id="aud_1", campaign_id="camp_1"
        )["method"]
        == "link_audio_selection_graph"
    )
    assert (
        services.resolve_audio_exception_for_recommendation(
            "rec_1", operator="tester", proof_url="https://proof.example/aud"
        )["method"]
        == "resolve_audio_exception_for_recommendation"
    )
    assert (
        services.record_audio_performance_snapshot(snapshot, commit=False)["method"]
        == "record_audio_performance_snapshot"
    )
    assert (
        services.performance_snapshot_score(snapshot)["method"]
        == "performance_snapshot_score"
    )
    assert (
        services.audio_workflow_summary([asset])["method"] == "audio_workflow_summary"
    )
    assert (
        services.dashboard_audio_intent_for_asset(asset)["method"]
        == "dashboard_audio_intent_for_asset"
    )
    assert (
        services.audio_task_for_dashboard_intent(intent)["method"]
        == "audio_task_for_dashboard_intent"
    )
    assert services.normalize_seconds("1.25")["method"] == "normalize_seconds"
    assert (
        services.first_metadata_value({"x": "y"}, "x")["method"]
        == "first_metadata_value"
    )
    assert (
        services.normalize_audio_segment({"start_seconds": 1})["method"]
        == "normalize_audio_segment"
    )
    assert (
        services.audio_segment_for_asset(intent)["method"] == "audio_segment_for_asset"
    )
    assert (
        services.normalize_cover_frame({"seconds": 2})["method"]
        == "normalize_cover_frame"
    )
    assert services.cover_frame_for_asset(asset)["method"] == "cover_frame_for_asset"
    assert (
        services.audio_selection_for_asset(asset)["method"]
        == "audio_selection_for_asset"
    )
    assert (
        services.audio_intent_is_attached(intent, "aud_1")["method"]
        == "audio_intent_is_attached"
    )
    assert (
        services.audio_intent_claims_embedded_media(intent)["method"]
        == "audio_intent_claims_embedded_media"
    )
    assert (
        services.embedded_audio_verified("/tmp/reel.mp4")["method"]
        == "embedded_audio_verified"
    )

    assert calls == [
        ("attach_audio_to_distribution_plan", ("dist_1",), {"track_id": "aud_1"}),
        ("attach_cover_frame_to_rendered_asset", ("asset_1",), {"seconds": 1.5}),
        ("select_audio_for_recommendation", ("rec_1", "aud_1"), {"operator": "tester"}),
        (
            "verify_audio_for_post",
            ("post_1",),
            {"proof_url": "https://proof.example/aud"},
        ),
        ("audio_catalog_row", ("aud_1",), {"allow_locator": True}),
        ("audio_selection_payload", ("sel_1",), {}),
        (
            "link_audio_selection_graph",
            (),
            {
                "selection_id": "sel_1",
                "audio_catalog_id": "aud_1",
                "campaign_id": "camp_1",
            },
        ),
        (
            "resolve_audio_exception_for_recommendation",
            ("rec_1",),
            {"operator": "tester", "proof_url": "https://proof.example/aud"},
        ),
        ("record_audio_performance_snapshot", (snapshot,), {"commit": False}),
        ("performance_snapshot_score", (snapshot,), {}),
        ("audio_workflow_summary", ([asset],), {}),
        ("dashboard_audio_intent_for_asset", (asset,), {}),
        ("audio_task_for_dashboard_intent", (intent,), {}),
        ("normalize_seconds", ("1.25",), {}),
        ("first_metadata_value", ({"x": "y"}, "x"), {}),
        ("normalize_audio_segment", ({"start_seconds": 1},), {}),
        ("audio_segment_for_asset", (intent,), {}),
        ("normalize_cover_frame", ({"seconds": 2},), {}),
        ("cover_frame_for_asset", (asset,), {"caption_context": None}),
        ("audio_selection_for_asset", (asset,), {}),
        ("audio_intent_is_attached", (intent, "aud_1"), {}),
        ("audio_intent_claims_embedded_media", (intent,), {}),
        ("embedded_audio_verified", ("/tmp/reel.mp4",), {}),
    ]


def test_core_services_delegates_inventory_perceptual_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeInventoryPerceptual:
        def asset_uniqueness_values(self, *args, **kwargs):
            calls.append(("asset_uniqueness_values", args, kwargs))
            return {"perceptualClusterId": "pdq:abc"}

        def ensure_rendered_asset_perceptual_metadata(self, *args, **kwargs):
            calls.append(("ensure_rendered_asset_perceptual_metadata", args, kwargs))
            return {"id": "asset_1"}

        def pdq_cluster_id_for_fingerprint(self, *args, **kwargs):
            calls.append(("pdq_cluster_id_for_fingerprint", args, kwargs))
            return "pdq:abc"

    services.inventory_perceptual = FakeInventoryPerceptual()

    assert services.asset_uniqueness_values(
        {"id": "asset_1"},
        metadata={"sourceFamilyId": "family_1"},
    ) == {"perceptualClusterId": "pdq:abc"}
    assert services.ensure_rendered_asset_perceptual_metadata(
        "asset_1", commit=False
    ) == {"id": "asset_1"}
    assert (
        services.pdq_cluster_id_for_fingerprint(
            campaign_id="campaign_1",
            rendered_asset_id="asset_1",
            fingerprint="0" * 64,
        )
        == "pdq:abc"
    )

    assert calls == [
        (
            "asset_uniqueness_values",
            ({"id": "asset_1"},),
            {"metadata": {"sourceFamilyId": "family_1"}},
        ),
        ("ensure_rendered_asset_perceptual_metadata", ("asset_1",), {"commit": False}),
        (
            "pdq_cluster_id_for_fingerprint",
            (),
            {
                "campaign_id": "campaign_1",
                "rendered_asset_id": "asset_1",
                "fingerprint": "0" * 64,
            },
        ),
    ]


def test_core_services_delegates_surface_requirement_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeSurfaceRequirements:
        def account_surface_obligations_plan(self, *args, **kwargs):
            calls.append(("account_surface_obligations_plan", args, kwargs))
            return {"schema": "campaign_factory.account_surface_obligations_plan.v1"}

        def account_content_needs(self, *args, **kwargs):
            calls.append(("account_content_needs", args, kwargs))
            return {"schema": "campaign_factory.account_content_needs.v1"}

        def account_surface_status(self, *args, **kwargs):
            calls.append(("account_surface_status", args, kwargs))
            return {"schema": "campaign_factory.account_surface_status.v1"}

        def creator_content_needs(self, *args, **kwargs):
            calls.append(("creator_content_needs", args, kwargs))
            return {"schema": "campaign_factory.creator_content_needs.v1"}

        def surface_gap_report(self, *args, **kwargs):
            calls.append(("surface_gap_report", args, kwargs))
            return {"schema": "campaign_factory.surface_gap_report.v1"}

        def build_surface_status(self, *args, **kwargs):
            calls.append(("build_surface_status", args, kwargs))
            return {"schema": "campaign_factory.surface_status.v1"}

        def account_content_requirement_rows(self, *args, **kwargs):
            calls.append(("account_content_requirement_rows", args, kwargs))
            return [{"id": "req_1"}]

        def account_row_for_requirement_account(self, *args, **kwargs):
            calls.append(("account_row_for_requirement_account", args, kwargs))
            return {"id": "acct_1"}

        def content_obligation_for_requirement(self, *args, **kwargs):
            calls.append(("content_obligation_for_requirement", args, kwargs))
            return {"surface": "story"}

        def required_content_count(self, *args, **kwargs):
            calls.append(("required_content_count", args, kwargs))
            return 2

        def empty_surface_totals(self, *args, **kwargs):
            calls.append(("empty_surface_totals", args, kwargs))
            return {"story": {"required": 0}}

        def add_obligation_to_totals(self, *args, **kwargs):
            calls.append(("add_obligation_to_totals", args, kwargs))

        def requirement_active_on_date(self, *args, **kwargs):
            calls.append(("requirement_active_on_date", args, kwargs))
            return True

        def surface_scheduled_count(self, *args, **kwargs):
            calls.append(("surface_scheduled_count", args, kwargs))
            return 1

        def surface_completed_count(self, *args, **kwargs):
            calls.append(("surface_completed_count", args, kwargs))
            return 0

        def last_surface_posted_at(self, *args, **kwargs):
            calls.append(("last_surface_posted_at", args, kwargs))
            return "2026-06-05T12:00:00+00:00"

        def surface_scheduled_for_account(self, *args, **kwargs):
            calls.append(("surface_scheduled_for_account", args, kwargs))
            return True

        def surface_completed_for_account(self, *args, **kwargs):
            calls.append(("surface_completed_for_account", args, kwargs))
            return False

    services.surface_requirements = FakeSurfaceRequirements()

    assert services.account_surface_obligations_plan(
        creator="Stacey", date="2026-06-06"
    ) == {
        "schema": "campaign_factory.account_surface_obligations_plan.v1",
    }
    assert services.account_content_needs(
        account_id="acct_1", creator="Stacey", date="2026-06-06"
    ) == {
        "schema": "campaign_factory.account_content_needs.v1",
    }
    assert services.account_surface_status(account_id="acct_1", date="2026-06-06") == {
        "schema": "campaign_factory.account_surface_status.v1",
    }
    assert services.creator_content_needs(creator="Stacey", date="2026-06-06") == {
        "schema": "campaign_factory.creator_content_needs.v1",
    }
    assert services.surface_gap_report(creator="Stacey", date="2026-06-06") == {
        "schema": "campaign_factory.surface_gap_report.v1",
    }
    assert services.build_surface_status(creator="Stacey", date="2026-06-06") == {
        "schema": "campaign_factory.surface_status.v1",
    }
    assert services.account_content_requirement_rows(creator="Stacey") == [
        {"id": "req_1"}
    ]
    assert services.account_row_for_requirement_account("acct_1") == {"id": "acct_1"}
    assert services.content_obligation_for_requirement(
        {"id": "req_1"}, "2026-06-06"
    ) == {"surface": "story"}
    assert services.required_content_count({"id": "req_1"}, "2026-06-06") == 2
    assert services.empty_surface_totals() == {"story": {"required": 0}}
    totals = {"story": {"required": 0}}
    services.add_obligation_to_totals(totals, {"surface": "story"})
    assert services.requirement_active_on_date({"id": "req_1"}, "2026-06-06") is True
    assert (
        services.surface_scheduled_count("acct_1", "ig_1", "story", "2026-06-06") == 1
    )
    assert (
        services.surface_completed_count("acct_1", "ig_1", "story", "2026-06-06") == 0
    )
    assert (
        services.last_surface_posted_at(
            account_id="acct_1",
            instagram_account_id="ig_1",
            surface="story",
            before_date="2026-06-06",
        )
        == "2026-06-05T12:00:00+00:00"
    )
    assert (
        services.surface_scheduled_for_account("acct_1", "ig_1", "story", "2026-06-06")
        is True
    )
    assert (
        services.surface_completed_for_account("acct_1", "ig_1", "story", "2026-06-06")
        is False
    )

    assert calls == [
        (
            "account_surface_obligations_plan",
            (),
            {"creator": "Stacey", "date": "2026-06-06"},
        ),
        (
            "account_content_needs",
            (),
            {"account_id": "acct_1", "creator": "Stacey", "date": "2026-06-06"},
        ),
        (
            "account_surface_status",
            (),
            {"account_id": "acct_1", "creator": None, "date": "2026-06-06"},
        ),
        ("creator_content_needs", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("surface_gap_report", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("build_surface_status", (), {"creator": "Stacey", "date": "2026-06-06"}),
        (
            "account_content_requirement_rows",
            (),
            {"creator": "Stacey", "account_id": None},
        ),
        ("account_row_for_requirement_account", ("acct_1",), {}),
        ("content_obligation_for_requirement", ({"id": "req_1"}, "2026-06-06"), {}),
        ("required_content_count", ({"id": "req_1"}, "2026-06-06"), {}),
        ("empty_surface_totals", (), {}),
        ("add_obligation_to_totals", (totals, {"surface": "story"}), {}),
        ("requirement_active_on_date", ({"id": "req_1"}, "2026-06-06"), {}),
        ("surface_scheduled_count", ("acct_1", "ig_1", "story", "2026-06-06"), {}),
        ("surface_completed_count", ("acct_1", "ig_1", "story", "2026-06-06"), {}),
        (
            "last_surface_posted_at",
            (),
            {
                "account_id": "acct_1",
                "instagram_account_id": "ig_1",
                "surface": "story",
                "before_date": "2026-06-06",
            },
        ),
        (
            "surface_scheduled_for_account",
            ("acct_1", "ig_1", "story", "2026-06-06"),
            {},
        ),
        (
            "surface_completed_for_account",
            ("acct_1", "ig_1", "story", "2026-06-06"),
            {},
        ),
    ]


def test_core_services_delegates_recommendation_accuracy_methods_to_recommendation_accuracy_repository() -> (
    None
):
    services = object.__new__(CoreServices)
    calls = []

    class FakeRecommendationAccuracy:
        def recommendation_accuracy(self, *args, **kwargs):
            calls.append(("recommendation_accuracy", args, kwargs))
            return {
                "schema": "campaign_factory.recommendation_accuracy_report.v1",
                "campaign": args[0],
            }

        def rebuild_recommendation_accuracy(self, *args, **kwargs):
            calls.append(("rebuild_recommendation_accuracy", args, kwargs))
            return {
                "schema": "campaign_factory.recommendation_accuracy_report.v1",
                "campaign": args[0],
            }

        def recommendation_proof_summary(self, *args, **kwargs):
            calls.append(("recommendation_proof_summary", args, kwargs))
            return {"measuredCount": 1}

        def rebuild_recommendation_accuracy_observations(self, *args, **kwargs):
            calls.append(("rebuild_recommendation_accuracy_observations", args, kwargs))
            return [{"id": "obs_1"}]

        def upsert_recommendation_accuracy_observation(self, *args, **kwargs):
            calls.append(("upsert_recommendation_accuracy_observation", args, kwargs))
            return {"id": "obs_1"}

        def recommendation_accuracy_observations(self, *args, **kwargs):
            calls.append(("recommendation_accuracy_observations", args, kwargs))
            return [{"id": "obs_1"}]

        def recommendation_accuracy_report_payload(self, *args, **kwargs):
            calls.append(("recommendation_accuracy_report_payload", args, kwargs))
            return {"schema": "campaign_factory.recommendation_accuracy_report.v1"}

        def persist_recommendation_accuracy_report(self, *args, **kwargs):
            calls.append(("persist_recommendation_accuracy_report", args, kwargs))
            return "recacc_report_1"

        def recommendation_accuracy_drift(self, *args, **kwargs):
            calls.append(("recommendation_accuracy_drift", args, kwargs))
            return []

        def recommendation_trust_score(self, *args, **kwargs):
            calls.append(("recommendation_trust_score", args, kwargs))
            return 80

        def recommendation_trust_confidence(self, *args, **kwargs):
            calls.append(("recommendation_trust_confidence", args, kwargs))
            return "usable"

        def recommendation_confidence_bucket(self, *args, **kwargs):
            calls.append(("recommendation_confidence_bucket", args, kwargs))
            return "usable"

        def recommendation_audio_selection(self, *args, **kwargs):
            calls.append(("recommendation_audio_selection", args, kwargs))
            return {"id": "audsel_1"}

        def recommendation_audio_match_status(self, *args, **kwargs):
            calls.append(("recommendation_audio_match_status", args, kwargs))
            return "recommended_audio_selected"

        def recommendation_outcome_snapshot_ids(self, *args, **kwargs):
            calls.append(("recommendation_outcome_snapshot_ids", args, kwargs))
            return ["perf_1"]

    services.recommendation_accuracy_repo = FakeRecommendationAccuracy()

    assert services.recommendation_accuracy(
        "may", account="ig_1", window_days=7, persist=False
    ) == {
        "schema": "campaign_factory.recommendation_accuracy_report.v1",
        "campaign": "may",
    }
    assert services.rebuild_recommendation_accuracy(
        "may", account="ig_1", window_days=7
    ) == {
        "schema": "campaign_factory.recommendation_accuracy_report.v1",
        "campaign": "may",
    }
    assert services.recommendation_proof_summary("camp_1") == {"measuredCount": 1}
    assert services.rebuild_recommendation_accuracy_observations(
        "camp_1", account="ig_1"
    ) == [{"id": "obs_1"}]
    assert services.upsert_recommendation_accuracy_observation(
        {"id": "rec_1"}, commit=True
    ) == {"id": "obs_1"}
    assert services.recommendation_accuracy_observations(
        "camp_1", account="ig_1", window_days=7
    ) == [{"id": "obs_1"}]
    assert services.recommendation_accuracy_report_payload(
        {"id": "camp_1", "slug": "may"}, [], [], account="ig_1", window_days=7
    ) == {
        "schema": "campaign_factory.recommendation_accuracy_report.v1",
    }
    assert (
        services.persist_recommendation_accuracy_report(
            {"observations": []}, "camp_1", account="ig_1", window_days=7
        )
        == "recacc_report_1"
    )
    assert services.recommendation_accuracy_drift([], []) == []
    assert services.recommendation_trust_score([], []) == 80
    assert services.recommendation_trust_confidence(10) == "usable"
    assert services.recommendation_confidence_bucket("medium", "high") == "usable"
    assert services.recommendation_audio_selection("rec_1") == {"id": "audsel_1"}
    assert (
        services.recommendation_audio_match_status(
            {"audioRecommendations": {"recommendations": []}}, {"id": "audsel_1"}
        )
        == "recommended_audio_selected"
    )
    assert services.recommendation_outcome_snapshot_ids(
        {"snapshots": [{"id": "perf_1"}]}, {}
    ) == ["perf_1"]

    assert calls == [
        (
            "recommendation_accuracy",
            ("may",),
            {"account": "ig_1", "window_days": 7, "persist": False},
        ),
        (
            "rebuild_recommendation_accuracy",
            ("may",),
            {"account": "ig_1", "window_days": 7},
        ),
        ("recommendation_proof_summary", ("camp_1",), {}),
        (
            "rebuild_recommendation_accuracy_observations",
            ("camp_1",),
            {"account": "ig_1", "commit": True},
        ),
        (
            "upsert_recommendation_accuracy_observation",
            ({"id": "rec_1"},),
            {"commit": True},
        ),
        (
            "recommendation_accuracy_observations",
            ("camp_1",),
            {"account": "ig_1", "window_days": 7, "before_window_days": None},
        ),
        (
            "recommendation_accuracy_report_payload",
            ({"id": "camp_1", "slug": "may"}, [], []),
            {"account": "ig_1", "window_days": 7},
        ),
        (
            "persist_recommendation_accuracy_report",
            ({"observations": []}, "camp_1"),
            {"account": "ig_1", "window_days": 7},
        ),
        (
            "recommendation_accuracy_drift",
            ([], []),
            {"min_sample": 5, "drop_threshold": 0.15},
        ),
        ("recommendation_trust_score", ([], []), {}),
        ("recommendation_trust_confidence", (10,), {}),
        ("recommendation_confidence_bucket", ("medium", "high"), {}),
        ("recommendation_audio_selection", ("rec_1",), {}),
        (
            "recommendation_audio_match_status",
            ({"audioRecommendations": {"recommendations": []}}, {"id": "audsel_1"}),
            {},
        ),
        (
            "recommendation_outcome_snapshot_ids",
            ({"snapshots": [{"id": "perf_1"}]}, {}),
            {},
        ),
    ]


def test_campaign_factory_delegates_recommendation_execution_methods_to_services() -> (
    None
):
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def _fake(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name, "args": args, "kwargs": kwargs}

            return _fake

    factory.services = FakeServices()
    item_payload_kwargs = {
        "campaign": {"id": "camp_1"},
        "campaign_graph_id": "cg_campaign",
        "run_graph_id": "cg_run",
        "rank": 1,
        "account": "ig_1",
        "candidate": {"renderedAssetId": "asset_1"},
        "asset": {"id": "asset_1", "campaign_id": "camp_1"},
        "reference_pattern": {"id": "pattern_1"},
        "reference_pattern_graph_id": "cg_pattern",
        "reference_pattern_rankings": [],
        "variation_preset_rankings": [],
        "recommendation_trust": {"status": "unmeasured"},
        "persist": False,
        "run_id": "run_1",
    }
    reference_only_kwargs = {
        "campaign": {"id": "camp_1"},
        "campaign_graph_id": "cg_campaign",
        "run_graph_id": "cg_run",
        "account": "ig_1",
        "reference_pattern": {"id": "pattern_1"},
        "reference_pattern_graph_id": "cg_pattern",
        "reference_pattern_rankings": [],
        "variation_preset_rankings": [],
        "recommendation_trust": {"status": "unmeasured"},
        "persist": False,
        "run_id": "run_1",
    }

    assert (
        factory.recommend_next_batch("may", count=2)["method"] == "recommend_next_batch"
    )
    assert (
        factory.recommendation_runs("may", limit=3)["method"] == "recommendation_runs"
    )
    assert factory._top_reference_pattern()["method"] == "top_reference_pattern"
    assert (
        factory._ranked_reference_patterns_for_campaign("camp_1")["method"]
        == "ranked_reference_patterns_for_campaign"
    )
    assert (
        factory._ranked_variation_presets_for_campaign("camp_1", account="ig_1")[
            "method"
        ]
        == "ranked_variation_presets_for_campaign"
    )
    assert (
        factory._compact_recommendation_rankings({"referencePatterns": []})["method"]
        == "compact_recommendation_rankings"
    )
    assert (
        factory._latest_recommendation_trust_context("camp_1", account=None)["method"]
        == "latest_recommendation_trust_context"
    )
    assert (
        factory._recommendation_item_payload(**item_payload_kwargs)["method"]
        == "recommendation_item_payload"
    )
    assert (
        factory._reference_only_recommendation_item(**reference_only_kwargs)["method"]
        == "reference_only_recommendation_item"
    )
    assert factory.recommendation_item("rec_1")["method"] == "recommendation_item"
    assert (
        factory.accept_recommendation_item("rec_1", operator="ade")["method"]
        == "accept_recommendation_item"
    )
    assert (
        factory.reject_recommendation_item("rec_1", reason="bad fit")["method"]
        == "reject_recommendation_item"
    )
    assert (
        factory.link_recommendation_item("rec_1", rendered_asset_id="asset_1")["method"]
        == "link_recommendation_item"
    )
    assert (
        factory.measure_recommendation_item("rec_1", performance_snapshot_id="perf_1")[
            "method"
        ]
        == "measure_recommendation_item"
    )
    assert (
        factory.execute_accepted_recommendation("rec_1", force=True)["method"]
        == "execute_accepted_recommendation"
    )
    assert (
        factory._update_recommendation_lifecycle(
            "rec_1",
            status="accepted",
            decision={"operator": "ade"},
            event_type="recommendation_item_accepted",
            message="accepted",
        )["method"]
        == "update_recommendation_lifecycle"
    )
    assert (
        factory._recommendation_account_fit_evidence(
            "camp_1", {"id": "asset_1"}, "ig_1"
        )["method"]
        == "recommendation_account_fit_evidence"
    )

    assert calls == [
        (
            "recommend_next_batch",
            ("may",),
            {"count": 2, "account": None, "persist": False},
        ),
        ("recommendation_runs", ("may",), {"limit": 3}),
        ("top_reference_pattern", (), {}),
        ("ranked_reference_patterns_for_campaign", ("camp_1",), {}),
        ("ranked_variation_presets_for_campaign", ("camp_1",), {"account": "ig_1"}),
        ("compact_recommendation_rankings", ({"referencePatterns": []},), {"limit": 5}),
        ("latest_recommendation_trust_context", ("camp_1",), {"account": None}),
        ("recommendation_item_payload", (), item_payload_kwargs),
        ("reference_only_recommendation_item", (), reference_only_kwargs),
        ("recommendation_item", ("rec_1",), {}),
        (
            "accept_recommendation_item",
            ("rec_1",),
            {
                "operator": "ade",
                "notes": None,
                "admin_override": False,
                "override_reason": None,
            },
        ),
        (
            "reject_recommendation_item",
            ("rec_1",),
            {
                "reason": "bad fit",
                "operator": None,
                "notes": None,
                "admin_override": False,
                "override_reason": None,
            },
        ),
        (
            "link_recommendation_item",
            ("rec_1",),
            {
                "source_asset_id": None,
                "render_job_id": None,
                "rendered_asset_id": "asset_1",
                "post_id": None,
                "performance_snapshot_id": None,
                "evidence": None,
                "admin_override": False,
                "override_reason": None,
            },
        ),
        (
            "measure_recommendation_item",
            ("rec_1",),
            {
                "performance_snapshot_id": "perf_1",
                "admin_override": False,
                "override_reason": None,
            },
        ),
        (
            "execute_accepted_recommendation",
            ("rec_1",),
            {
                "mode": "level_2",
                "force": True,
                "dry_run_render": False,
                "run_audit": True,
                "contentforge_base_url": None,
            },
        ),
        (
            "update_recommendation_lifecycle",
            ("rec_1",),
            {
                "status": "accepted",
                "decision": {"operator": "ade"},
                "outcome": None,
                "baseline": None,
                "measurement_version": None,
                "timestamp_column": None,
                "event_type": "recommendation_item_accepted",
                "message": "accepted",
                "admin_override": False,
                "override_reason": None,
            },
        ),
        (
            "recommendation_account_fit_evidence",
            ("camp_1", {"id": "asset_1"}, "ig_1"),
            {},
        ),
    ]


def test_core_services_delegates_recommendation_execution_methods_to_repository() -> (
    None
):
    services = object.__new__(CoreServices)
    calls = []

    class FakeRecommendations:
        def __getattr__(self, name):
            def _fake(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name, "args": args, "kwargs": kwargs}

            return _fake

    services.recommendations = FakeRecommendations()
    item_payload_kwargs = {
        "campaign": {"id": "camp_1"},
        "campaign_graph_id": "cg_campaign",
        "run_graph_id": "cg_run",
        "rank": 1,
        "account": "ig_1",
        "candidate": {"renderedAssetId": "asset_1"},
        "asset": {"id": "asset_1", "campaign_id": "camp_1"},
        "reference_pattern": {"id": "pattern_1"},
        "reference_pattern_graph_id": "cg_pattern",
        "reference_pattern_rankings": [],
        "variation_preset_rankings": [],
        "recommendation_trust": {"status": "unmeasured"},
        "persist": False,
        "run_id": "run_1",
    }
    reference_only_kwargs = {
        "campaign": {"id": "camp_1"},
        "campaign_graph_id": "cg_campaign",
        "run_graph_id": "cg_run",
        "account": "ig_1",
        "reference_pattern": {"id": "pattern_1"},
        "reference_pattern_graph_id": "cg_pattern",
        "reference_pattern_rankings": [],
        "variation_preset_rankings": [],
        "recommendation_trust": {"status": "unmeasured"},
        "persist": False,
        "run_id": "run_1",
    }

    assert (
        services.recommend_next_batch("may", count=2)["method"]
        == "recommend_next_batch"
    )
    assert (
        services.recommendation_runs("may", limit=3)["method"] == "recommendation_runs"
    )
    assert services.top_reference_pattern()["method"] == "top_reference_pattern"
    assert (
        services.ranked_reference_patterns_for_campaign("camp_1")["method"]
        == "ranked_reference_patterns_for_campaign"
    )
    assert (
        services.ranked_variation_presets_for_campaign("camp_1", account="ig_1")[
            "method"
        ]
        == "ranked_variation_presets_for_campaign"
    )
    assert (
        services.compact_recommendation_rankings({"referencePatterns": []})["method"]
        == "compact_recommendation_rankings"
    )
    assert (
        services.latest_recommendation_trust_context("camp_1", account=None)["method"]
        == "latest_recommendation_trust_context"
    )
    assert (
        services.recommendation_item_payload(**item_payload_kwargs)["method"]
        == "recommendation_item_payload"
    )
    assert (
        services.reference_only_recommendation_item(**reference_only_kwargs)["method"]
        == "reference_only_recommendation_item"
    )
    assert services.recommendation_item("rec_1")["method"] == "recommendation_item"
    assert (
        services.accept_recommendation_item("rec_1", operator="ade")["method"]
        == "accept_recommendation_item"
    )
    assert (
        services.reject_recommendation_item("rec_1", reason="bad fit")["method"]
        == "reject_recommendation_item"
    )
    assert (
        services.link_recommendation_item("rec_1", rendered_asset_id="asset_1")[
            "method"
        ]
        == "link_recommendation_item"
    )
    assert (
        services.measure_recommendation_item("rec_1", performance_snapshot_id="perf_1")[
            "method"
        ]
        == "measure_recommendation_item"
    )
    assert (
        services.execute_accepted_recommendation("rec_1", force=True)["method"]
        == "execute_accepted_recommendation"
    )
    assert (
        services.update_recommendation_lifecycle(
            "rec_1",
            status="accepted",
            decision={"operator": "ade"},
            event_type="recommendation_item_accepted",
            message="accepted",
        )["method"]
        == "update_recommendation_lifecycle"
    )
    assert (
        services.recommendation_account_fit_evidence(
            "camp_1", {"id": "asset_1"}, "ig_1"
        )["method"]
        == "recommendation_account_fit_evidence"
    )

    assert calls == [
        (
            "recommend_next_batch",
            ("may",),
            {"count": 2, "account": None, "persist": False},
        ),
        ("recommendation_runs", ("may",), {"limit": 3}),
        ("top_reference_pattern", (), {}),
        ("ranked_reference_patterns_for_campaign", ("camp_1",), {}),
        ("ranked_variation_presets_for_campaign", ("camp_1",), {"account": "ig_1"}),
        ("compact_recommendation_rankings", ({"referencePatterns": []},), {"limit": 5}),
        ("latest_recommendation_trust_context", ("camp_1",), {"account": None}),
        ("recommendation_item_payload", (), item_payload_kwargs),
        ("reference_only_recommendation_item", (), reference_only_kwargs),
        ("recommendation_item", ("rec_1",), {}),
        (
            "accept_recommendation_item",
            ("rec_1",),
            {
                "operator": "ade",
                "notes": None,
                "admin_override": False,
                "override_reason": None,
            },
        ),
        (
            "reject_recommendation_item",
            ("rec_1",),
            {
                "reason": "bad fit",
                "operator": None,
                "notes": None,
                "admin_override": False,
                "override_reason": None,
            },
        ),
        (
            "link_recommendation_item",
            ("rec_1",),
            {
                "source_asset_id": None,
                "render_job_id": None,
                "rendered_asset_id": "asset_1",
                "post_id": None,
                "performance_snapshot_id": None,
                "evidence": None,
                "admin_override": False,
                "override_reason": None,
            },
        ),
        (
            "measure_recommendation_item",
            ("rec_1",),
            {
                "performance_snapshot_id": "perf_1",
                "admin_override": False,
                "override_reason": None,
            },
        ),
        (
            "execute_accepted_recommendation",
            ("rec_1",),
            {
                "mode": "level_2",
                "force": True,
                "dry_run_render": False,
                "run_audit": True,
                "contentforge_base_url": None,
            },
        ),
        (
            "update_recommendation_lifecycle",
            ("rec_1",),
            {
                "status": "accepted",
                "decision": {"operator": "ade"},
                "event_type": "recommendation_item_accepted",
                "message": "accepted",
            },
        ),
        (
            "recommendation_account_fit_evidence",
            ("camp_1", {"id": "asset_1"}, "ig_1"),
            {},
        ),
    ]


def test_core_services_delegates_campaign_overview_methods_to_campaign_overview_repository() -> (
    None
):
    services = object.__new__(CoreServices)
    calls = []

    class FakeCampaignOverview:
        def dashboard(self, *args, **kwargs):
            calls.append(("dashboard", args, kwargs))
            return {"campaign": {"slug": args[0]}, "rendered": []}

        def default_dashboard_campaign(self, *args, **kwargs):
            calls.append(("default_dashboard_campaign", args, kwargs))
            return args[0][0] if args[0] else None

        def campaign_health(self, *args, **kwargs):
            calls.append(("campaign_health", args, kwargs))
            return {
                "schema": "campaign_factory.campaign_health.v1",
                "campaign": args[0],
            }

        def asset_detail(self, *args, **kwargs):
            calls.append(("asset_detail", args, kwargs))
            return {
                "schema": "campaign_factory.asset_detail.v1",
                "asset": {"id": args[0]},
            }

        def assign_asset_account(self, *args, **kwargs):
            calls.append(("assign_asset_account", args, kwargs))
            return {
                "rendered_asset_id": args[0],
                "instagram_account_id": kwargs["instagram_account_id"],
            }

        def assignments_for_asset(self, *args, **kwargs):
            calls.append(("assignments_for_asset", args, kwargs))
            return [{"rendered_asset_id": args[0]}]

        def assignments_for_campaign(self, *args, **kwargs):
            calls.append(("assignments_for_campaign", args, kwargs))
            return [{"campaign": args[0]}]

    services.campaign_overview = FakeCampaignOverview()

    assert services.dashboard("may") == {"campaign": {"slug": "may"}, "rendered": []}
    assert services.default_dashboard_campaign([{"id": "camp_1", "slug": "may"}]) == {
        "id": "camp_1",
        "slug": "may",
    }
    assert services.campaign_health("may") == {
        "schema": "campaign_factory.campaign_health.v1",
        "campaign": "may",
    }
    assert services.asset_detail("asset_1") == {
        "schema": "campaign_factory.asset_detail.v1",
        "asset": {"id": "asset_1"},
    }
    assert services.assign_asset_account(
        "asset_1",
        account_id="acct_1",
        instagram_account_id="ig_1",
        planned_window_start="2026-05-15T10:00:00-04:00",
        planned_window_end="2026-05-15T12:00:00-04:00",
        notes="morning test",
    ) == {"rendered_asset_id": "asset_1", "instagram_account_id": "ig_1"}
    assert services.assignments_for_asset("asset_1") == [
        {"rendered_asset_id": "asset_1"}
    ]
    assert services.assignments_for_campaign("may") == [{"campaign": "may"}]

    assert calls == [
        ("dashboard", ("may",), {}),
        ("default_dashboard_campaign", ([{"id": "camp_1", "slug": "may"}],), {}),
        ("campaign_health", ("may",), {}),
        ("asset_detail", ("asset_1",), {}),
        (
            "assign_asset_account",
            ("asset_1",),
            {
                "account_id": "acct_1",
                "instagram_account_id": "ig_1",
                "planned_window_start": "2026-05-15T10:00:00-04:00",
                "planned_window_end": "2026-05-15T12:00:00-04:00",
                "notes": "morning test",
            },
        ),
        ("assignments_for_asset", ("asset_1",), {}),
        ("assignments_for_campaign", ("may",), {}),
    ]


def test_core_services_delegates_account_planning_methods_to_account_planning_repository() -> (
    None
):
    services = object.__new__(CoreServices)
    calls = []

    class FakeAccountPlanning:
        def account_plan(self, *args, **kwargs):
            calls.append(("account_plan", args, kwargs))
            return {"schema": "campaign_factory.account_plan.v1"}

        def ranking(self, *args, **kwargs):
            calls.append(("ranking", args, kwargs))
            return {"schema": "campaign_factory.ranking.v1"}

        def quality_score_for_ranking(self, *args, **kwargs):
            calls.append(("quality_score_for_ranking", args, kwargs))
            return 91

        def history_score(self, *args, **kwargs):
            calls.append(("history_score", args, kwargs))
            return 72

        def account_fit_score(self, *args, **kwargs):
            calls.append(("account_fit_score", args, kwargs))
            return 58

        def novelty_score(self, *args, **kwargs):
            calls.append(("novelty_score", args, kwargs))
            return 90

        def dashboard_rendered_asset(self, *args, **kwargs):
            calls.append(("dashboard_rendered_asset", args, kwargs))
            return {"id": args[0]["id"], "enriched": True}

        def generated_asset_lineage(self, *args, **kwargs):
            calls.append(("generated_asset_lineage", args, kwargs))
            return {"schema": "reel_factory.generated_asset_lineage.v1"}

        def audio_recommendations_for_asset(self, *args, **kwargs):
            calls.append(("audio_recommendations_for_asset", args, kwargs))
            return {"schema": "campaign_factory.audio_recommendations.v1"}

    services.account_planning = FakeAccountPlanning()
    asset = {"id": "asset_1"}
    source_prompt = {"promptId": "prompt_1"}
    reference_pattern = {"id": "ref_1"}

    assert services.account_plan("may", user_id="user_1", usage={"assets": []}) == {
        "schema": "campaign_factory.account_plan.v1",
    }
    assert services.ranking("may") == {"schema": "campaign_factory.ranking.v1"}
    assert services.quality_score_for_ranking(asset) == 91
    assert services.history_score({"count": 1}) == 72
    assert services.account_fit_score(asset) == 58
    assert services.novelty_score(asset) == 90
    assert services.dashboard_rendered_asset(asset) == {
        "id": "asset_1",
        "enriched": True,
    }
    assert services.generated_asset_lineage(source_prompt, reference_pattern) == {
        "schema": "reel_factory.generated_asset_lineage.v1",
    }
    assert services.audio_recommendations_for_asset(
        caption_generation={},
        reference_pattern=reference_pattern,
        recipe="v01_original",
        account_tags=["stacey"],
    ) == {"schema": "campaign_factory.audio_recommendations.v1"}

    assert calls == [
        ("account_plan", ("may",), {"user_id": "user_1", "usage": {"assets": []}}),
        ("ranking", ("may",), {}),
        ("quality_score_for_ranking", (asset,), {}),
        ("history_score", ({"count": 1},), {}),
        ("account_fit_score", (asset,), {}),
        ("novelty_score", (asset,), {}),
        ("dashboard_rendered_asset", (asset,), {}),
        ("generated_asset_lineage", (source_prompt, reference_pattern), {}),
        (
            "audio_recommendations_for_asset",
            (),
            {
                "caption_generation": {},
                "reference_pattern": reference_pattern,
                "recipe": "v01_original",
                "account_tags": ["stacey"],
            },
        ),
    ]


def test_core_services_delegates_creative_planning_methods_to_creative_planning_repository() -> (
    None
):
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

    assert services.create_creative_plan(name="daily", target_account="@creator") == {
        "name": "daily"
    }
    assert services.creative_plan("daily") == {"name": "daily"}
    assert services.update_creative_plan_status(
        name="daily", status="prompts_ready"
    ) == {"status": "prompts_ready"}
    assert services.sync_creative_plan_progress(
        name="daily", prompt_export_path=Path("/tmp/prompts.json")
    ) == {
        "schema": "campaign_factory.creative_plan_progress_sync.v1",
    }
    assert services.creative_plan_for_campaign(
        "may", dashboard={"campaign": {"slug": "may"}}
    ) == {"linked_campaign": "may"}
    assert (
        services.record_creative_plan_event(
            "cplan_1", "creative_plan_created", metadata={"ok": True}
        )
        is None
    )
    assert services.creative_plan_payload({"id": "cplan_1"}) == {"id": "cplan_1"}
    assert (
        services.source_prompt_creative_plan_id(
            {"source_prompt": '{"creativePlanId":"cplan_1"}'}
        )
        == "cplan_1"
    )
    assert (
        services.asset_creative_plan_id(
            {"source_prompt": '{"creativePlanId":"cplan_2"}'}
        )
        == "cplan_2"
    )

    assert calls == [
        (
            "create_creative_plan",
            (),
            {
                "name": "daily",
                "platform": "instagram",
                "target_account": "@creator",
                "daily_base_video_target": 10,
                "style_lanes": None,
                "model_profile": "",
                "source_accounts": None,
                "goal": "views_reach",
                "linked_campaign": None,
            },
        ),
        ("creative_plan", ("daily",), {}),
        (
            "update_creative_plan_status",
            (),
            {"name": "daily", "status": "prompts_ready"},
        ),
        (
            "sync_creative_plan_progress",
            (),
            {"name": "daily", "prompt_export_path": Path("/tmp/prompts.json")},
        ),
        (
            "creative_plan_for_campaign",
            ("may",),
            {"dashboard": {"campaign": {"slug": "may"}}},
        ),
        (
            "record_creative_plan_event",
            ("cplan_1", "creative_plan_created"),
            {
                "status": "info",
                "message": "",
                "metadata": {"ok": True},
                "commit": True,
            },
        ),
        ("creative_plan_payload", ({"id": "cplan_1"},), {"dashboard": None}),
        (
            "source_prompt_creative_plan_id",
            ({"source_prompt": '{"creativePlanId":"cplan_1"}'},),
            {},
        ),
        (
            "asset_creative_plan_id",
            ({"source_prompt": '{"creativePlanId":"cplan_2"}'},),
            {},
        ),
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

    assert services.import_reference_bank(
        Path("/tmp/bank.json"), Path("/tmp/prompts.json")
    ) == {
        "schema": "campaign_factory.reference_bank_import.v1",
    }
    assert services.reference_patterns(limit=3) == {
        "schema": "campaign_factory.reference_patterns.v1"
    }
    assert services.select_reference_pattern(
        "may", cluster_key="cluster", variant_count=2, notes="notes"
    ) == {
        "schema": "campaign_factory.reference_pattern_selection.v1",
    }
    assert services.campaign_reference_plan("may") == {
        "schema": "campaign_factory.reference_plan.v1"
    }
    assert services.prepare_reel_from_reference(
        campaign_slug="may",
        cluster_key="cluster",
        variant_count=2,
        recipes=["v01_original"],
        caption_color="white",
        notes="notes",
        force_new=False,
    ) == {"schema": "campaign_factory.prepare_from_reference.v1"}
    assert services.active_reference_pattern_for_campaign("camp_1") == {
        "id": "refpat_1"
    }
    assert services.reference_hooks(
        {"clusterKey": "cluster", "label": "Cluster"}, count=2
    ) == [
        {"text": "mirror check"},
    ]
    assert services.reference_pattern_payload({"id": "refpat_1"}) == {"id": "refpat_1"}
    assert services.reference_hook_is_schedule_safe("mirror check") is True

    assert calls == [
        (
            "import_reference_bank",
            (Path("/tmp/bank.json"), Path("/tmp/prompts.json")),
            {},
        ),
        ("reference_patterns", (), {"limit": 3}),
        (
            "select_reference_pattern",
            ("may",),
            {
                "cluster_key": "cluster",
                "reference_pattern_id": None,
                "variant_count": 2,
                "notes": "notes",
            },
        ),
        ("campaign_reference_plan", ("may",), {}),
        (
            "prepare_reel_from_reference",
            (),
            {
                "campaign_slug": "may",
                "cluster_key": "cluster",
                "reference_pattern_id": None,
                "variant_count": 2,
                "recipes": ["v01_original"],
                "caption_color": "white",
                "notes": "notes",
                "force_new": False,
            },
        ),
        ("active_reference_pattern_for_campaign", ("camp_1",), {}),
        (
            "reference_hooks",
            ({"clusterKey": "cluster", "label": "Cluster"},),
            {"count": 2},
        ),
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
    assert services.caption_version_payload({"id": "cver_1"}) == {
        "captionVersionId": "cver_1"
    }

    assert calls == [
        (
            "caption_family_plan",
            (),
            {
                "creator": "Stacey",
                "parent_asset_id": "asset_1",
                "requested_caption_versions": 2,
                "style": "ig_short",
                "dry_run": True,
            },
        ),
        (
            "caption_family_create",
            (),
            {
                "creator": "Stacey",
                "parent_asset_id": "asset_1",
                "requested_caption_versions": 2,
                "style": "ig_short",
                "dry_run": False,
            },
        ),
        (
            "planned_caption_version",
            (),
            {
                "caption_family_id": "cfam_1",
                "parent": {"id": "asset_1"},
                "concept": {"parentReelId": "preel_1"},
                "index": 1,
                "angle": "question_bait",
                "base_burned": "caption",
                "base_hashtags": ["#one"],
                "style": "ig_short",
                "caption_source": "test",
            },
        ),
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
    assert factory.distribution_plans_for_asset("asset_1") == [
        {"renderedAssetId": "asset_1"}
    ]
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
    assert (
        factory._next_distribution_account(
            {"allowedInstagramAccountIds": ["ig_1"]}, "model", {}
        )
        == "ig_1"
    )
    assert factory._distribution_slots([10], 1) == ["slot_1"]
    assert factory._next_valid_distribution_slot(
        [], 0, "ig_1", {"id": "asset_1"}, {}, {}, {}, {}, []
    ) == ("slot_1", 1)
    assert factory.distribution_summary("may") == {
        "schema": "campaign_factory.distribution_summary.v1"
    }
    assert factory._latest_distribution_plan_for_asset("asset_1") == {
        "renderedAssetId": "asset_1"
    }

    assert calls == [
        (
            "create_distribution_plan",
            ("asset_1",),
            {
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
            },
        ),
        ("distribution_plan", ("dist_1",), {}),
        ("distribution_plans_for_asset", ("asset_1",), {}),
        ("distribution_plans_for_campaign", ("may",), {}),
        ("clear_distribution_plans_for_campaign", ("may",), {}),
        ("distribution_plan_payload", ({"id": "dist_1"},), {}),
        (
            "plan_distribution",
            ("may",),
            {
                "user_id": "user_1",
                "mode": "preview",
                "strategy": "trial-heavy",
                "replace": False,
                "fallback_hours": [9],
            },
        ),
        (
            "next_distribution_account",
            ({"allowedInstagramAccountIds": ["ig_1"]}, "model", {}),
            {},
        ),
        ("distribution_slots", ([10], 1), {}),
        (
            "next_valid_distribution_slot",
            ([], 0, "ig_1", {"id": "asset_1"}, {}, {}, {}, {}, []),
            {},
        ),
        ("distribution_summary", ("may",), {}),
        ("latest_distribution_plan_for_asset", ("asset_1",), {}),
    ]


def test_core_services_delegates_distribution_methods_to_distribution_repository() -> (
    None
):
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

        def validate_instagram_trial_reel_intent(self, *args, **kwargs):
            calls.append(("validate_instagram_trial_reel_intent", args, kwargs))
            return "MANUAL"

    services.distribution = FakeDistribution()

    assert services.create_distribution_plan(
        "asset_1", instagram_account_id="ig_1"
    ) == {"id": "dist_1"}
    assert services.distribution_plan("dist_1") == {"id": "dist_1"}
    assert services.distribution_plans_for_asset("asset_1") == [
        {"renderedAssetId": "asset_1"}
    ]
    assert services.distribution_plans_for_campaign("may") == [{"campaign": "may"}]
    assert services.clear_distribution_plans_for_campaign("may") == 2
    assert services.distribution_plan_payload({"id": "dist_1"}) == {"id": "dist_1"}
    assert services.plan_distribution("may", user_id="user_1") == {
        "schema": "campaign_factory.distribution_plan_run.v1"
    }
    assert (
        services.next_distribution_account(
            {"allowedInstagramAccountIds": ["ig_1"]}, "model", {}
        )
        == "ig_1"
    )
    assert services.distribution_slots([10], 1) == ["slot_1"]
    assert services.next_valid_distribution_slot(
        [], 0, "ig_1", {"id": "asset_1"}, {}, {}, {}, {}, []
    ) == ("slot_1", 1)
    assert services.distribution_summary("may") == {
        "schema": "campaign_factory.distribution_summary.v1"
    }
    assert services.latest_distribution_plan_for_asset("asset_1") == {
        "renderedAssetId": "asset_1"
    }
    assert (
        services.validate_instagram_trial_reel_intent(
            content_surface="reel",
            distribution_surface="trial_reel",
            media_type="video",
            instagram_trial_reels=True,
            trial_graduation_strategy="manual",
        )
        == "MANUAL"
    )

    assert calls == [
        (
            "create_distribution_plan",
            ("asset_1",),
            {
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
            },
        ),
        ("distribution_plan", ("dist_1",), {}),
        ("distribution_plans_for_asset", ("asset_1",), {}),
        ("distribution_plans_for_campaign", ("may",), {}),
        ("clear_distribution_plans_for_campaign", ("may",), {}),
        ("distribution_plan_payload", ({"id": "dist_1"},), {}),
        (
            "plan_distribution",
            ("may",),
            {
                "user_id": "user_1",
                "mode": "preview",
                "strategy": "trial-heavy",
                "replace": True,
                "fallback_hours": None,
            },
        ),
        (
            "next_distribution_account",
            ({"allowedInstagramAccountIds": ["ig_1"]}, "model", {}),
            {},
        ),
        ("distribution_slots", ([10], 1), {}),
        (
            "next_valid_distribution_slot",
            ([], 0, "ig_1", {"id": "asset_1"}, {}, {}, {}, {}, []),
            {},
        ),
        ("distribution_summary", ("may",), {}),
        ("latest_distribution_plan_for_asset", ("asset_1",), {}),
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
    ]


def test_core_services_delegates_decision_ledger_methods_to_decision_repository() -> (
    None
):
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
    assert services.decision_ledger_report(creator="Stacey") == {
        "schema": "creator_os.decision_ledger_report.v1"
    }
    assert services.decision_ledger_summary(creator="Stacey") == {
        "schema": "creator_os.decision_ledger_summary.v1"
    }
    assert services.decision_ledger_by_creator(creator="Stacey") == {
        "schema": "creator_os.decision_ledger_by_creator.v1",
    }
    assert services.decision_ledger_by_account(
        creator="Stacey", account_id="acct_1"
    ) == {
        "schema": "creator_os.decision_ledger_by_account.v1",
    }
    assert services.decision_ledger_by_surface(creator="Stacey", surface="story") == {
        "schema": "creator_os.decision_ledger_by_surface.v1",
    }
    assert services.decision_ledger_by_decision_type(
        creator="Stacey", decision_type="account_needs_story"
    ) == {
        "schema": "creator_os.decision_ledger_by_decision_type.v1",
    }
    assert services.query_decision_ledger(creator="Stacey") == {"decisionCount": 0}

    assert calls == [
        (
            "decision_ledger_preview",
            (),
            {
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
            },
        ),
        ("decision_ledger_report", (), {"creator": "Stacey"}),
        ("decision_ledger_summary", (), {"creator": "Stacey"}),
        ("decision_ledger_by_creator", (), {"creator": "Stacey"}),
        (
            "decision_ledger_by_account",
            (),
            {"creator": "Stacey", "account_id": "acct_1"},
        ),
        ("decision_ledger_by_surface", (), {"creator": "Stacey", "surface": "story"}),
        (
            "decision_ledger_by_decision_type",
            (),
            {"creator": "Stacey", "decision_type": "account_needs_story"},
        ),
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

        def variant_inventory_plan(self, *args, **kwargs):
            calls.append(("variant_inventory_plan", args, kwargs))
            return {"schema": "campaign_factory.variant_inventory_plan.v1"}

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
    assert services.winner_expansion_report(
        "may", min_views=100, min_reach=200, min_followers=3
    ) == {
        "schema": "campaign_factory.winner_expansion_report.v1",
    }
    assert services.variant_inventory_plan(
        creator="Stacey",
        campaign="may",
        target_draft_shortfall=12,
        preset="strong_safe",
        max_variants_per_parent=6,
        minimum_recommended_per_parent=2,
        dry_run=True,
    ) == {"schema": "campaign_factory.variant_inventory_plan.v1"}
    assert services.winner_variant_candidate(
        {"variantAssetId": "asset_variant"}, {"id": "asset_variant"}
    ) == {
        "variantAssetId": "asset_variant",
    }
    assert services.winner_variant_candidate_decision({"uploadReady": True}) == {
        "recommended": True,
        "blockingReasons": [],
    }
    assert services.latest_variant_audit_result("asset_variant") == {
        "qualityScore": 100
    }
    assert services.contentforge_result_from_operations(
        [{"type": "contentforge_result"}]
    ) == {"familyName": "cover_frame"}
    assert (
        services.operation_family_from_operations([{"familyName": "cover_frame"}])
        == "cover_frame"
    )
    assert services.score_value("95") == 95
    assert (
        services.variant_inventory_primary_blocking_reason(["missing_audio"])
        == "missing_audio"
    )
    assert services.variant_inventory_quality_risk("asset_1") == "low"
    assert services.variant_inventory_winner_rank(
        campaign_id="camp_1",
        parent_asset_id="asset_1",
        parent_reel_id="preel_1",
    ) == {"hasWinnerMetrics": True, "score": 10, "metrics": {"views": 10}}
    assert services.variant_asset_payload({"id": "var_1"}) == {"variantId": "var_1"}

    assert calls == [
        (
            "winner_expansion_plan",
            (),
            {
                "creator": "Stacey",
                "parent_asset_id": "asset_1",
                "target_variants": 3,
                "preset": "strong_safe",
            },
        ),
        (
            "winner_expansion_report",
            ("may",),
            {"min_views": 100, "min_reach": 200, "min_followers": 3},
        ),
        (
            "variant_inventory_plan",
            (),
            {
                "creator": "Stacey",
                "campaign": "may",
                "target_draft_shortfall": 12,
                "preset": "strong_safe",
                "max_variants_per_parent": 6,
                "minimum_recommended_per_parent": 2,
                "dry_run": True,
            },
        ),
        (
            "winner_variant_candidate",
            ({"variantAssetId": "asset_variant"}, {"id": "asset_variant"}),
            {},
        ),
        ("winner_variant_candidate_decision", ({"uploadReady": True},), {}),
        ("latest_variant_audit_result", ("asset_variant",), {}),
        (
            "contentforge_result_from_operations",
            ([{"type": "contentforge_result"}],),
            {},
        ),
        ("operation_family_from_operations", ([{"familyName": "cover_frame"}],), {}),
        ("score_value", ("95",), {}),
        ("variant_inventory_primary_blocking_reason", (["missing_audio"],), {}),
        ("variant_inventory_quality_risk", ("asset_1",), {}),
        (
            "variant_inventory_winner_rank",
            (),
            {
                "campaign_id": "camp_1",
                "parent_asset_id": "asset_1",
                "parent_reel_id": "preel_1",
            },
        ),
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

        def variant_inventory_plan(self, *args, **kwargs):
            calls.append(("variant_inventory_plan", args, kwargs))
            return {"schema": "campaign_factory.variant_inventory_plan.v1"}

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
    assert factory.winner_expansion_report(
        "may", min_views=100, min_reach=200, min_followers=3
    ) == {
        "schema": "campaign_factory.winner_expansion_report.v1",
    }
    assert factory.variant_inventory_plan(
        creator="Stacey",
        campaign="may",
        target_draft_shortfall=12,
        preset="strong_safe",
        max_variants_per_parent=6,
        minimum_recommended_per_parent=2,
        dry_run=True,
    ) == {"schema": "campaign_factory.variant_inventory_plan.v1"}
    assert factory._winner_variant_candidate(
        {"variantAssetId": "asset_variant"}, {"id": "asset_variant"}
    ) == {
        "variantAssetId": "asset_variant",
    }
    assert factory._winner_variant_candidate_decision({"uploadReady": True}) == {
        "recommended": True,
        "blockingReasons": [],
    }
    assert factory._latest_variant_audit_result("asset_variant") == {
        "qualityScore": 100
    }
    assert factory._contentforge_result_from_operations(
        [{"type": "contentforge_result"}]
    ) == {
        "familyName": "cover_frame",
    }
    assert (
        factory._operation_family_from_operations([{"familyName": "cover_frame"}])
        == "cover_frame"
    )
    assert factory._score_value("95") == 95
    assert (
        factory._variant_inventory_primary_blocking_reason(["missing_audio"])
        == "missing_audio"
    )
    assert factory._variant_inventory_quality_risk("asset_1") == "low"
    assert factory._variant_inventory_winner_rank(
        campaign_id="camp_1",
        parent_asset_id="asset_1",
        parent_reel_id="preel_1",
    ) == {"hasWinnerMetrics": True, "score": 10, "metrics": {"views": 10}}

    assert calls == [
        (
            "winner_expansion_plan",
            (),
            {
                "creator": "Stacey",
                "parent_asset_id": "asset_1",
                "target_variants": 3,
                "preset": "strong_safe",
            },
        ),
        (
            "winner_expansion_report",
            ("may",),
            {"min_views": 100, "min_reach": 200, "min_followers": 3},
        ),
        (
            "variant_inventory_plan",
            (),
            {
                "creator": "Stacey",
                "campaign": "may",
                "target_draft_shortfall": 12,
                "preset": "strong_safe",
                "max_variants_per_parent": 6,
                "minimum_recommended_per_parent": 2,
                "dry_run": True,
            },
        ),
        (
            "winner_variant_candidate",
            ({"variantAssetId": "asset_variant"}, {"id": "asset_variant"}),
            {},
        ),
        ("winner_variant_candidate_decision", ({"uploadReady": True},), {}),
        ("latest_variant_audit_result", ("asset_variant",), {}),
        (
            "contentforge_result_from_operations",
            ([{"type": "contentforge_result"}],),
            {},
        ),
        ("operation_family_from_operations", ([{"familyName": "cover_frame"}],), {}),
        ("score_value", ("95",), {}),
        ("variant_inventory_primary_blocking_reason", (["missing_audio"],), {}),
        ("variant_inventory_quality_risk", ("asset_1",), {}),
        (
            "variant_inventory_winner_rank",
            (),
            {
                "campaign_id": "camp_1",
                "parent_asset_id": "asset_1",
                "parent_reel_id": "preel_1",
            },
        ),
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

    assert services.winner_registry(
        creator="Stacey", campaign_slug="May", min_views=10
    ) == {
        "schema": "campaign_factory.winner_registry.v1",
    }
    assert services.concept_registry(
        creator="Stacey", campaign_slug="May", min_views=10
    ) == {
        "schema": "campaign_factory.concept_registry.v1",
    }
    assert services.winner_patterns(
        creator="Stacey", campaign_slug="May", min_views=10
    ) == {
        "schema": "campaign_factory.winner_patterns.v1",
    }
    assert services.winner_knowledge_base(
        creator="Stacey", campaign_slug="May", min_views=10
    ) == {
        "schema": "campaign_factory.winner_knowledge_base.v1",
    }
    assert services.winner_memory_rows(creator="Stacey", campaign_slug="May") == [
        {"post_id": "post_1"}
    ]
    assert services.winner_memory_item(
        {"post_id": "post_1"}, min_views=10, min_reach=10, min_followers=1
    ) == {
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
        (
            "winner_registry",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "min_views": 10,
                "min_reach": None,
                "min_followers": 1,
            },
        ),
        (
            "concept_registry",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "min_views": 10,
                "min_reach": None,
                "min_followers": 1,
            },
        ),
        (
            "winner_patterns",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "min_views": 10,
                "min_reach": None,
                "min_followers": 1,
            },
        ),
        (
            "winner_knowledge_base",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "min_views": 10,
                "min_reach": None,
                "min_followers": 1,
            },
        ),
        ("winner_memory_rows", (), {"creator": "Stacey", "campaign_slug": "May"}),
        (
            "winner_memory_item",
            ({"post_id": "post_1"},),
            {
                "min_views": 10,
                "min_reach": 10,
                "min_followers": 1,
            },
        ),
        ("winner_concept_name", ({"concept_id": "concept_1"},), {}),
        ("posting_window_label", ("2026-06-06T18:12:00+00:00",), {}),
        (
            "winner_pattern_group",
            ([{"conceptId": "concept_1"}],),
            {
                "key_field": "conceptId",
                "label_field": None,
                "output_key": "conceptId",
                "output_label": None,
            },
        ),
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

    assert factory.winner_registry(
        creator="Stacey", campaign_slug="May", min_views=10
    ) == {
        "schema": "campaign_factory.winner_registry.v1",
    }
    assert factory.concept_registry(
        creator="Stacey", campaign_slug="May", min_views=10
    ) == {
        "schema": "campaign_factory.concept_registry.v1",
    }
    assert factory.winner_patterns(
        creator="Stacey", campaign_slug="May", min_views=10
    ) == {
        "schema": "campaign_factory.winner_patterns.v1",
    }
    assert factory.winner_knowledge_base(
        creator="Stacey", campaign_slug="May", min_views=10
    ) == {
        "schema": "campaign_factory.winner_knowledge_base.v1",
    }
    assert factory._winner_memory_rows(creator="Stacey", campaign_slug="May") == [
        {"post_id": "post_1"}
    ]
    assert factory._winner_memory_item(
        {"post_id": "post_1"}, min_views=10, min_reach=10, min_followers=1
    ) == {
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
        (
            "winner_registry",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "min_views": 10,
                "min_reach": None,
                "min_followers": 1,
            },
        ),
        (
            "concept_registry",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "min_views": 10,
                "min_reach": None,
                "min_followers": 1,
            },
        ),
        (
            "winner_patterns",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "min_views": 10,
                "min_reach": None,
                "min_followers": 1,
            },
        ),
        (
            "winner_knowledge_base",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "min_views": 10,
                "min_reach": None,
                "min_followers": 1,
            },
        ),
        ("winner_memory_rows", (), {"creator": "Stacey", "campaign_slug": "May"}),
        (
            "winner_memory_item",
            ({"post_id": "post_1"},),
            {
                "min_views": 10,
                "min_reach": 10,
                "min_followers": 1,
            },
        ),
        ("winner_concept_name", ({"concept_id": "concept_1"},), {}),
        ("posting_window_label", ("2026-06-06T18:12:00+00:00",), {}),
        (
            "winner_pattern_group",
            ([{"conceptId": "concept_1"}],),
            {
                "key_field": "conceptId",
                "label_field": None,
                "output_key": "conceptId",
                "output_label": None,
            },
        ),
    ]


def test_core_services_delegates_creative_learning_reports_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeCreativeKnowledge:
        def __getattr__(self, name):
            def delegated(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"schema": f"campaign_factory.{name}.v1"}

            return delegated

    services.creative_knowledge = FakeCreativeKnowledge()

    report_kwargs = {
        "creator": "Stacey",
        "campaign_slug": "May",
        "minimum_sample_size": 4,
        "limit": 7,
    }
    for method_name in [
        "creative_knowledge_base",
        "creative_pattern_report",
        "creative_caption_report",
        "creative_audio_report",
        "creative_surface_report",
        "creative_account_tier_report",
        "creative_window_report",
        "creative_performance_analysis",
        "creator_learning_summary",
        "next_content_recommendations",
        "recommendation_quality_audit",
    ]:
        assert getattr(services, method_name)(**report_kwargs) == {
            "schema": f"campaign_factory.{method_name}.v1",
        }

    confidence_kwargs = {
        "creator": "Stacey",
        "campaign_slug": "May",
        "minimum_sample_size": 4,
    }
    assert services.creative_learning_confidence_model(**confidence_kwargs) == {
        "schema": "campaign_factory.creative_learning_confidence_model.v1",
    }

    compact_report_kwargs = {
        "creator": "Stacey",
        "campaign_slug": "May",
        "limit": 7,
    }
    assert services.creative_fatigue_report(**compact_report_kwargs) == {
        "schema": "campaign_factory.creative_fatigue_report.v1",
    }
    assert services.creative_surface_comparison_report(**compact_report_kwargs) == {
        "schema": "campaign_factory.creative_surface_comparison_report.v1",
    }

    assert calls == [
        ("creative_knowledge_base", (), report_kwargs),
        ("creative_pattern_report", (), report_kwargs),
        ("creative_caption_report", (), report_kwargs),
        ("creative_audio_report", (), report_kwargs),
        ("creative_surface_report", (), report_kwargs),
        ("creative_account_tier_report", (), report_kwargs),
        ("creative_window_report", (), report_kwargs),
        ("creative_performance_analysis", (), report_kwargs),
        ("creator_learning_summary", (), report_kwargs),
        ("next_content_recommendations", (), report_kwargs),
        ("recommendation_quality_audit", (), report_kwargs),
        ("creative_learning_confidence_model", (), confidence_kwargs),
        ("creative_fatigue_report", (), compact_report_kwargs),
        ("creative_surface_comparison_report", (), compact_report_kwargs),
    ]


def test_creative_learning_report_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def delegated(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"schema": f"campaign_factory.{name}.v1"}

            return delegated

    factory.services = FakeServices()

    for method_name in [
        "creative_knowledge_base",
        "creative_pattern_report",
        "creative_caption_report",
        "creative_audio_report",
        "creative_surface_report",
        "creative_account_tier_report",
        "creative_window_report",
        "creative_performance_analysis",
        "creator_learning_summary",
        "next_content_recommendations",
    ]:
        assert getattr(factory, method_name)(creator="Stacey") == {
            "schema": f"campaign_factory.{method_name}.v1",
        }

    assert factory.creative_learning_confidence_model(creator="Stacey") == {
        "schema": "campaign_factory.creative_learning_confidence_model.v1",
    }
    assert factory.creative_fatigue_report(creator="Stacey") == {
        "schema": "campaign_factory.creative_fatigue_report.v1",
    }
    assert factory.creative_surface_comparison_report(creator="Stacey") == {
        "schema": "campaign_factory.creative_surface_comparison_report.v1",
    }
    assert factory.recommendation_quality_audit(creator="Stacey") == {
        "schema": "campaign_factory.recommendation_quality_audit.v1",
    }

    base_kwargs = {
        "creator": "Stacey",
        "campaign_slug": None,
        "minimum_sample_size": 3,
        "limit": 10,
    }
    assert calls == [
        ("creative_knowledge_base", (), base_kwargs),
        ("creative_pattern_report", (), base_kwargs),
        ("creative_caption_report", (), base_kwargs),
        ("creative_audio_report", (), base_kwargs),
        ("creative_surface_report", (), base_kwargs),
        ("creative_account_tier_report", (), base_kwargs),
        ("creative_window_report", (), base_kwargs),
        ("creative_performance_analysis", (), base_kwargs),
        ("creator_learning_summary", (), base_kwargs),
        ("next_content_recommendations", (), base_kwargs),
        (
            "creative_learning_confidence_model",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": None,
                "minimum_sample_size": 3,
            },
        ),
        (
            "creative_fatigue_report",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": None,
                "limit": 20,
            },
        ),
        (
            "creative_surface_comparison_report",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": None,
                "limit": 20,
            },
        ),
        (
            "recommendation_quality_audit",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": None,
                "minimum_sample_size": 3,
                "limit": 20,
            },
        ),
    ]


def test_core_services_delegates_creative_learning_helpers_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeCreativeKnowledge:
        def __getattr__(self, name):
            def delegated(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return delegated

    services.creative_knowledge = FakeCreativeKnowledge()
    results = [{"postId": "post_1", "metrics": {"views": 10}}]
    row = {"post_id": "post_1"}
    kb = {"creator": "Stacey", "insufficientData": False}

    cases = [
        (
            "build_creative_knowledge_base",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "minimum_sample_size": 3,
                "limit": 10,
            },
        ),
        (
            "build_creative_performance_analysis",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "minimum_sample_size": 3,
                "limit": 10,
            },
        ),
        ("creative_performance_baseline", (results,), {}),
        (
            "creative_performance_assessment",
            ({"key": "tease"}, {"score": 10}),
            {"dimension": "captionAngle"},
        ),
        ("creative_more_recommendations", (results, "high"), {"limit": 3}),
        ("creative_less_recommendations", (results, "low"), {"limit": 2}),
        (
            "recommendation_explainability",
            ({"reason": "because"},),
            {"item": {"score": 10}, "confidence": "medium"},
        ),
        ("confidence_score", ("high",), {}),
        ("learning_confidence_classification", (results,), {}),
        (
            "creative_fatigue_signals",
            (results,),
            {"field": "conceptId", "fatigue_type": "concept_fatigue"},
        ),
        ("metric_decline_pct", (results, results, "reach"), {}),
        ("engagement_decline_pct", (results, results), {}),
        ("avg_result_metric", (results, "views"), {}),
        ("creative_surface_rows", (results,), {}),
        ("recommendation_quality_bucket", ({"confidence": 90},), {}),
        ("creative_analysis_confidence", (12,), {}),
        ("creative_dimension_label", ("concept",), {}),
        ("creative_pattern_priority", ("concept",), {}),
        ("creative_knowledge_results_for_report", (kb, "Stacey", "May"), {}),
        ("creative_knowledge_rows", (), {"creator": "Stacey", "campaign_slug": "May"}),
        ("creative_knowledge_result", (row,), {}),
        ("creative_knowledge_score_weights", (), {}),
        ("creative_knowledge_score", ({"views": 10},), {}),
        ("creative_result_group", (results, "postId"), {"limit": 3}),
        ("creative_result_lineage", (results,), {}),
    ]

    for name, args, kwargs in cases:
        assert getattr(services, name)(*args, **kwargs) == {"method": name}

    assert calls == [(name, args, kwargs) for name, args, kwargs in cases]


def test_creative_learning_helper_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def __getattr__(self, name):
            def delegated(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return delegated

    factory.services = FakeServices()
    results = [{"postId": "post_1", "metrics": {"views": 10}}]
    row = {"post_id": "post_1"}
    kb = {"creator": "Stacey", "insufficientData": False}

    cases = [
        (
            "_build_creative_knowledge_base",
            "build_creative_knowledge_base",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "minimum_sample_size": 3,
                "limit": 10,
            },
        ),
        (
            "_build_creative_performance_analysis",
            "build_creative_performance_analysis",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "minimum_sample_size": 3,
                "limit": 10,
            },
        ),
        (
            "_creative_performance_baseline",
            "creative_performance_baseline",
            (results,),
            {},
        ),
        (
            "_creative_performance_assessment",
            "creative_performance_assessment",
            ({"key": "tease"}, {"score": 10}),
            {"dimension": "captionAngle"},
        ),
        (
            "_creative_more_recommendations",
            "creative_more_recommendations",
            (results, "high"),
            {"limit": 3},
        ),
        (
            "_creative_less_recommendations",
            "creative_less_recommendations",
            (results, "low"),
            {"limit": 2},
        ),
        (
            "_recommendation_explainability",
            "recommendation_explainability",
            ({"reason": "because"},),
            {"item": {"score": 10}, "confidence": "medium"},
        ),
        ("_confidence_score", "confidence_score", ("high",), {}),
        (
            "_learning_confidence_classification",
            "learning_confidence_classification",
            (results,),
            {},
        ),
        (
            "_creative_fatigue_signals",
            "creative_fatigue_signals",
            (results,),
            {"field": "conceptId", "fatigue_type": "concept_fatigue"},
        ),
        ("_metric_decline_pct", "metric_decline_pct", (results, results, "reach"), {}),
        ("_engagement_decline_pct", "engagement_decline_pct", (results, results), {}),
        ("_avg_result_metric", "avg_result_metric", (results, "views"), {}),
        ("_creative_surface_rows", "creative_surface_rows", (results,), {}),
        (
            "_recommendation_quality_bucket",
            "recommendation_quality_bucket",
            ({"confidence": 90},),
            {},
        ),
        ("_creative_analysis_confidence", "creative_analysis_confidence", (12,), {}),
        ("_creative_dimension_label", "creative_dimension_label", ("concept",), {}),
        ("_creative_pattern_priority", "creative_pattern_priority", ("concept",), {}),
        (
            "_creative_knowledge_results_for_report",
            "creative_knowledge_results_for_report",
            (kb, "Stacey", "May"),
            {},
        ),
        (
            "_creative_knowledge_rows",
            "creative_knowledge_rows",
            (),
            {"creator": "Stacey", "campaign_slug": "May"},
        ),
        ("_creative_knowledge_result", "creative_knowledge_result", (row,), {}),
        (
            "_creative_knowledge_score_weights",
            "creative_knowledge_score_weights",
            (),
            {},
        ),
        ("_creative_knowledge_score", "creative_knowledge_score", ({"views": 10},), {}),
        (
            "_creative_result_group",
            "creative_result_group",
            (results, "postId"),
            {"limit": 3},
        ),
        ("_creative_result_lineage", "creative_result_lineage", (results,), {}),
    ]

    for facade_name, service_name, args, kwargs in cases:
        assert getattr(factory, facade_name)(*args, **kwargs) == {
            "method": service_name
        }

    assert calls == [
        (service_name, args, kwargs) for _, service_name, args, kwargs in cases
    ]


def test_core_services_delegates_tribev2_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeTribeV2:
        def tribev2_reel_analysis(self, *args, **kwargs):
            calls.append(("tribev2_reel_analysis", args, kwargs))
            return {"schema": "campaign_factory.tribev2_reel_analysis.v1"}

        def tribev2_reel_review(self, *args, **kwargs):
            calls.append(("tribev2_reel_review", args, kwargs))
            return {"schema": "campaign_factory.tribev2_reel_review.v1"}

        def tribev2_holdout_pilot_review(self, *args, **kwargs):
            calls.append(("tribev2_holdout_pilot_review", args, kwargs))
            return {"schema": "campaign_factory.tribev2_holdout_pilot_review.v1"}

        def tribev2_review_both_bucket(self, *args, **kwargs):
            calls.append(("tribev2_review_both_bucket", args, kwargs))
            return [{"renderedAssetId": "asset_1"}]

        def tribev2_review_item(self, *args, **kwargs):
            calls.append(("tribev2_review_item", args, kwargs))
            return {"renderedAssetId": "asset_1"}

        def tribev2_holdout_bucket_rows(self, *args, **kwargs):
            calls.append(("tribev2_holdout_bucket_rows", args, kwargs))
            return {"top20": [], "middle20": [], "bottom20": []}

        def tribev2_holdout_bucket_summary(self, *args, **kwargs):
            calls.append(("tribev2_holdout_bucket_summary", args, kwargs))
            return {"bucket": args[0]}

        def tribev2_average_metrics(self, *args, **kwargs):
            calls.append(("tribev2_average_metrics", args, kwargs))
            return {"views": 10.0}

        def tribev2_average_scores(self, *args, **kwargs):
            calls.append(("tribev2_average_scores", args, kwargs))
            return {"meanAbsActivation": 0.1}

        def average_row_field(self, *args, **kwargs):
            calls.append(("average_row_field", args, kwargs))
            return 10.0

        def tribev2_preview_path(self, *args, **kwargs):
            calls.append(("tribev2_preview_path", args, kwargs))
            return "/tmp/preview.mp4"

        def write_tribev2_review_contact_sheet(self, *args, **kwargs):
            calls.append(("write_tribev2_review_contact_sheet", args, kwargs))
            return "/tmp/review.html"

        def write_tribev2_holdout_contact_sheet(self, *args, **kwargs):
            calls.append(("write_tribev2_holdout_contact_sheet", args, kwargs))
            return "/tmp/holdout.html"

        def tribev2_contact_sheet_cards(self, *args, **kwargs):
            calls.append(("tribev2_contact_sheet_cards", args, kwargs))
            return ["<article></article>"]

        def tribev2_contact_sheet_html(self, *args, **kwargs):
            calls.append(("tribev2_contact_sheet_html", args, kwargs))
            return "<html></html>"

        def tribev2_extract_thumbnail(self, *args, **kwargs):
            calls.append(("tribev2_extract_thumbnail", args, kwargs))
            return "/tmp/thumb.jpg"

        def tribev2_reel_analysis_rows(self, *args, **kwargs):
            calls.append(("tribev2_reel_analysis_rows", args, kwargs))
            return [{"renderedAssetId": "asset_1"}]

        def tribev2_score_for_snapshot(self, *args, **kwargs):
            calls.append(("tribev2_score_for_snapshot", args, kwargs))
            return {"id": "tribe_1"}

        def pearson_correlation(self, *args, **kwargs):
            calls.append(("pearson_correlation", args, kwargs))
            return 0.5

        def tribev2_bucket_summary(self, *args, **kwargs):
            calls.append(("tribev2_bucket_summary", args, kwargs))
            return {"sampleSize": 1}

        def tribev2_bucket_lift(self, *args, **kwargs):
            calls.append(("tribev2_bucket_lift", args, kwargs))
            return {"avgViews": 100.0}

        def tribev2_metric_quality(self, *args, **kwargs):
            calls.append(("tribev2_metric_quality", args, kwargs))
            return {"views": {"usableForCorrelation": True}}

        def tribev2_signal_summary(self, *args, **kwargs):
            calls.append(("tribev2_signal_summary", args, kwargs))
            return {"strongestSignal": "meanAbsActivation:views"}

        def tribev2_confidence_level(self, *args, **kwargs):
            calls.append(("tribev2_confidence_level", args, kwargs))
            return "medium"

    services.tribev2 = FakeTribeV2()

    ranked = [{"renderedAssetId": "asset_1"}]
    item = {"rank": 1, "previewPath": "/tmp/preview.mp4"}
    buckets = {"top20": {"items": []}}

    assert services.tribev2_reel_analysis(
        creator="Stacey", campaign_slug="May", limit=2
    ) == {
        "schema": "campaign_factory.tribev2_reel_analysis.v1",
    }
    assert services.tribev2_reel_review(
        creator="Stacey", campaign_slug="May", bucket="both"
    ) == {
        "schema": "campaign_factory.tribev2_reel_review.v1",
    }
    assert services.tribev2_holdout_pilot_review(
        creator="Stacey", campaign_slug="May"
    ) == {
        "schema": "campaign_factory.tribev2_holdout_pilot_review.v1",
    }
    assert services.tribev2_review_both_bucket(ranked, 1) == [
        {"renderedAssetId": "asset_1"}
    ]
    assert services.tribev2_review_item(
        ranked[0],
        rank=1,
        sort_field="meanAbsActivation",
        show_metrics=False,
        show_tribe_score=True,
    ) == {"renderedAssetId": "asset_1"}
    assert services.tribev2_holdout_bucket_rows(ranked) == {
        "top20": [],
        "middle20": [],
        "bottom20": [],
    }
    assert services.tribev2_holdout_bucket_summary("top20", ranked, limit=1) == {
        "bucket": "top20"
    }
    assert services.tribev2_average_metrics(ranked) == {"views": 10.0}
    assert services.tribev2_average_scores(ranked) == {"meanAbsActivation": 0.1}
    assert services.average_row_field(ranked, "views") == 10.0
    assert services.tribev2_preview_path(ranked[0]) == "/tmp/preview.mp4"
    assert (
        services.write_tribev2_review_contact_sheet(
            [item],
            creator="Stacey",
            title="Review",
            blind_mode=True,
            show_metrics=False,
            show_tribe_score=True,
        )
        == "/tmp/review.html"
    )
    assert (
        services.write_tribev2_holdout_contact_sheet(buckets, creator="Stacey")
        == "/tmp/holdout.html"
    )
    assert services.tribev2_contact_sheet_cards(
        [item],
        Path("/tmp"),
        show_metrics=False,
        show_tribe_score=True,
    ) == ["<article></article>"]
    assert (
        services.tribev2_contact_sheet_html(title="Review", body="<p>body</p>")
        == "<html></html>"
    )
    assert (
        services.tribev2_extract_thumbnail("/tmp/preview.mp4", Path("/tmp"), item)
        == "/tmp/thumb.jpg"
    )
    assert services.tribev2_reel_analysis_rows(
        creator="Stacey", campaign_slug="May"
    ) == [
        {"renderedAssetId": "asset_1"},
    ]
    assert services.tribev2_score_for_snapshot({"rendered_asset_id": "asset_1"}) == {
        "id": "tribe_1"
    }
    assert services.pearson_correlation([1.0, 2.0], [3.0, 4.0]) == 0.5
    assert services.tribev2_bucket_summary(ranked) == {"sampleSize": 1}
    assert services.tribev2_bucket_lift({"avgViews": 2}, {"avgViews": 1}) == {
        "avgViews": 100.0
    }
    assert services.tribev2_metric_quality(ranked, ["views"]) == {
        "views": {"usableForCorrelation": True}
    }
    assert services.tribev2_signal_summary(
        {"meanAbsActivation": {"views": 0.5}},
        sample_size=20,
        metric_quality={"views": {"usableForCorrelation": True}},
    ) == {"strongestSignal": "meanAbsActivation:views"}
    assert services.tribev2_confidence_level(20, True) == "medium"

    assert calls == [
        (
            "tribev2_reel_analysis",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "minimum_sample_size": 3,
                "limit": 2,
            },
        ),
        (
            "tribev2_reel_review",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "sort_by": "meanAbsActivation",
                "bucket": "both",
                "limit": 12,
                "contact_sheet": False,
                "show_metrics": None,
                "show_tribe_score": True,
                "blind_mode": False,
            },
        ),
        (
            "tribev2_holdout_pilot_review",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "limit": 20,
                "contact_sheet": False,
            },
        ),
        ("tribev2_review_both_bucket", (ranked, 1), {}),
        (
            "tribev2_review_item",
            (ranked[0],),
            {
                "rank": 1,
                "sort_field": "meanAbsActivation",
                "show_metrics": False,
                "show_tribe_score": True,
            },
        ),
        ("tribev2_holdout_bucket_rows", (ranked,), {}),
        ("tribev2_holdout_bucket_summary", ("top20", ranked), {"limit": 1}),
        ("tribev2_average_metrics", (ranked,), {}),
        ("tribev2_average_scores", (ranked,), {}),
        ("average_row_field", (ranked, "views"), {}),
        ("tribev2_preview_path", (ranked[0],), {}),
        (
            "write_tribev2_review_contact_sheet",
            ([item],),
            {
                "creator": "Stacey",
                "title": "Review",
                "blind_mode": True,
                "show_metrics": False,
                "show_tribe_score": True,
            },
        ),
        ("write_tribev2_holdout_contact_sheet", (buckets,), {"creator": "Stacey"}),
        (
            "tribev2_contact_sheet_cards",
            ([item], Path("/tmp")),
            {
                "show_metrics": False,
                "show_tribe_score": True,
            },
        ),
        ("tribev2_contact_sheet_html", (), {"title": "Review", "body": "<p>body</p>"}),
        ("tribev2_extract_thumbnail", ("/tmp/preview.mp4", Path("/tmp"), item), {}),
        (
            "tribev2_reel_analysis_rows",
            (),
            {"creator": "Stacey", "campaign_slug": "May"},
        ),
        ("tribev2_score_for_snapshot", ({"rendered_asset_id": "asset_1"},), {}),
        ("pearson_correlation", ([1.0, 2.0], [3.0, 4.0]), {}),
        ("tribev2_bucket_summary", (ranked,), {}),
        ("tribev2_bucket_lift", ({"avgViews": 2}, {"avgViews": 1}), {}),
        ("tribev2_metric_quality", (ranked, ["views"]), {}),
        (
            "tribev2_signal_summary",
            ({"meanAbsActivation": {"views": 0.5}},),
            {
                "sample_size": 20,
                "metric_quality": {"views": {"usableForCorrelation": True}},
            },
        ),
        ("tribev2_confidence_level", (20, True), {}),
    ]


def test_tribev2_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def tribev2_reel_analysis(self, *args, **kwargs):
            calls.append(("tribev2_reel_analysis", args, kwargs))
            return {"schema": "campaign_factory.tribev2_reel_analysis.v1"}

        def tribev2_reel_review(self, *args, **kwargs):
            calls.append(("tribev2_reel_review", args, kwargs))
            return {"schema": "campaign_factory.tribev2_reel_review.v1"}

        def tribev2_holdout_pilot_review(self, *args, **kwargs):
            calls.append(("tribev2_holdout_pilot_review", args, kwargs))
            return {"schema": "campaign_factory.tribev2_holdout_pilot_review.v1"}

        def tribev2_review_both_bucket(self, *args, **kwargs):
            calls.append(("tribev2_review_both_bucket", args, kwargs))
            return [{"renderedAssetId": "asset_1"}]

        def tribev2_review_item(self, *args, **kwargs):
            calls.append(("tribev2_review_item", args, kwargs))
            return {"renderedAssetId": "asset_1"}

        def tribev2_holdout_bucket_rows(self, *args, **kwargs):
            calls.append(("tribev2_holdout_bucket_rows", args, kwargs))
            return {"top20": [], "middle20": [], "bottom20": []}

        def tribev2_holdout_bucket_summary(self, *args, **kwargs):
            calls.append(("tribev2_holdout_bucket_summary", args, kwargs))
            return {"bucket": args[0]}

        def tribev2_average_metrics(self, *args, **kwargs):
            calls.append(("tribev2_average_metrics", args, kwargs))
            return {"views": 10.0}

        def tribev2_average_scores(self, *args, **kwargs):
            calls.append(("tribev2_average_scores", args, kwargs))
            return {"meanAbsActivation": 0.1}

        def average_row_field(self, *args, **kwargs):
            calls.append(("average_row_field", args, kwargs))
            return 10.0

        def tribev2_preview_path(self, *args, **kwargs):
            calls.append(("tribev2_preview_path", args, kwargs))
            return "/tmp/preview.mp4"

        def write_tribev2_review_contact_sheet(self, *args, **kwargs):
            calls.append(("write_tribev2_review_contact_sheet", args, kwargs))
            return "/tmp/review.html"

        def write_tribev2_holdout_contact_sheet(self, *args, **kwargs):
            calls.append(("write_tribev2_holdout_contact_sheet", args, kwargs))
            return "/tmp/holdout.html"

        def tribev2_contact_sheet_cards(self, *args, **kwargs):
            calls.append(("tribev2_contact_sheet_cards", args, kwargs))
            return ["<article></article>"]

        def tribev2_contact_sheet_html(self, *args, **kwargs):
            calls.append(("tribev2_contact_sheet_html", args, kwargs))
            return "<html></html>"

        def tribev2_extract_thumbnail(self, *args, **kwargs):
            calls.append(("tribev2_extract_thumbnail", args, kwargs))
            return "/tmp/thumb.jpg"

        def tribev2_reel_analysis_rows(self, *args, **kwargs):
            calls.append(("tribev2_reel_analysis_rows", args, kwargs))
            return [{"renderedAssetId": "asset_1"}]

        def tribev2_score_for_snapshot(self, *args, **kwargs):
            calls.append(("tribev2_score_for_snapshot", args, kwargs))
            return {"id": "tribe_1"}

        def pearson_correlation(self, *args, **kwargs):
            calls.append(("pearson_correlation", args, kwargs))
            return 0.5

        def tribev2_bucket_summary(self, *args, **kwargs):
            calls.append(("tribev2_bucket_summary", args, kwargs))
            return {"sampleSize": 1}

        def tribev2_bucket_lift(self, *args, **kwargs):
            calls.append(("tribev2_bucket_lift", args, kwargs))
            return {"avgViews": 100.0}

        def tribev2_metric_quality(self, *args, **kwargs):
            calls.append(("tribev2_metric_quality", args, kwargs))
            return {"views": {"usableForCorrelation": True}}

        def tribev2_signal_summary(self, *args, **kwargs):
            calls.append(("tribev2_signal_summary", args, kwargs))
            return {"strongestSignal": "meanAbsActivation:views"}

        def tribev2_confidence_level(self, *args, **kwargs):
            calls.append(("tribev2_confidence_level", args, kwargs))
            return "medium"

    factory.services = FakeServices()
    ranked = [{"renderedAssetId": "asset_1"}]
    item = {"rank": 1, "previewPath": "/tmp/preview.mp4"}
    buckets = {"top20": {"items": []}}

    assert factory.tribev2_reel_analysis(
        creator="Stacey", campaign_slug="May", limit=2
    ) == {
        "schema": "campaign_factory.tribev2_reel_analysis.v1",
    }
    assert factory.tribev2_reel_review(
        creator="Stacey", campaign_slug="May", bucket="both"
    ) == {
        "schema": "campaign_factory.tribev2_reel_review.v1",
    }
    assert factory.tribev2_holdout_pilot_review(
        creator="Stacey", campaign_slug="May"
    ) == {
        "schema": "campaign_factory.tribev2_holdout_pilot_review.v1",
    }
    assert factory._tribev2_review_both_bucket(ranked, 1) == [
        {"renderedAssetId": "asset_1"}
    ]
    assert factory._tribev2_review_item(
        ranked[0],
        rank=1,
        sort_field="meanAbsActivation",
        show_metrics=False,
        show_tribe_score=True,
    ) == {"renderedAssetId": "asset_1"}
    assert factory._tribev2_holdout_bucket_rows(ranked) == {
        "top20": [],
        "middle20": [],
        "bottom20": [],
    }
    assert factory._tribev2_holdout_bucket_summary("top20", ranked, limit=1) == {
        "bucket": "top20"
    }
    assert factory._tribev2_average_metrics(ranked) == {"views": 10.0}
    assert factory._tribev2_average_scores(ranked) == {"meanAbsActivation": 0.1}
    assert factory._average_row_field(ranked, "views") == 10.0
    assert factory._tribev2_preview_path(ranked[0]) == "/tmp/preview.mp4"
    assert (
        factory._write_tribev2_review_contact_sheet(
            [item],
            creator="Stacey",
            title="Review",
            blind_mode=True,
            show_metrics=False,
            show_tribe_score=True,
        )
        == "/tmp/review.html"
    )
    assert (
        factory._write_tribev2_holdout_contact_sheet(buckets, creator="Stacey")
        == "/tmp/holdout.html"
    )
    assert factory._tribev2_contact_sheet_cards(
        [item],
        Path("/tmp"),
        show_metrics=False,
        show_tribe_score=True,
    ) == ["<article></article>"]
    assert (
        factory._tribev2_contact_sheet_html(title="Review", body="<p>body</p>")
        == "<html></html>"
    )
    assert (
        factory._tribev2_extract_thumbnail("/tmp/preview.mp4", Path("/tmp"), item)
        == "/tmp/thumb.jpg"
    )
    assert factory._tribev2_reel_analysis_rows(
        creator="Stacey", campaign_slug="May"
    ) == [
        {"renderedAssetId": "asset_1"},
    ]
    assert factory._tribev2_score_for_snapshot({"rendered_asset_id": "asset_1"}) == {
        "id": "tribe_1"
    }
    assert factory._pearson_correlation([1.0, 2.0], [3.0, 4.0]) == 0.5
    assert factory._tribev2_bucket_summary(ranked) == {"sampleSize": 1}
    assert factory._tribev2_bucket_lift({"avgViews": 2}, {"avgViews": 1}) == {
        "avgViews": 100.0
    }
    assert factory._tribev2_metric_quality(ranked, ["views"]) == {
        "views": {"usableForCorrelation": True}
    }
    assert factory._tribev2_signal_summary(
        {"meanAbsActivation": {"views": 0.5}},
        sample_size=20,
        metric_quality={"views": {"usableForCorrelation": True}},
    ) == {"strongestSignal": "meanAbsActivation:views"}
    assert factory._tribev2_confidence_level(20, True) == "medium"

    assert calls == [
        (
            "tribev2_reel_analysis",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "minimum_sample_size": 3,
                "limit": 2,
            },
        ),
        (
            "tribev2_reel_review",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "sort_by": "meanAbsActivation",
                "bucket": "both",
                "limit": 12,
                "contact_sheet": False,
                "show_metrics": None,
                "show_tribe_score": True,
                "blind_mode": False,
            },
        ),
        (
            "tribev2_holdout_pilot_review",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "May",
                "limit": 20,
                "contact_sheet": False,
            },
        ),
        ("tribev2_review_both_bucket", (ranked, 1), {}),
        (
            "tribev2_review_item",
            (ranked[0],),
            {
                "rank": 1,
                "sort_field": "meanAbsActivation",
                "show_metrics": False,
                "show_tribe_score": True,
            },
        ),
        ("tribev2_holdout_bucket_rows", (ranked,), {}),
        ("tribev2_holdout_bucket_summary", ("top20", ranked), {"limit": 1}),
        ("tribev2_average_metrics", (ranked,), {}),
        ("tribev2_average_scores", (ranked,), {}),
        ("average_row_field", (ranked, "views"), {}),
        ("tribev2_preview_path", (ranked[0],), {}),
        (
            "write_tribev2_review_contact_sheet",
            ([item],),
            {
                "creator": "Stacey",
                "title": "Review",
                "blind_mode": True,
                "show_metrics": False,
                "show_tribe_score": True,
            },
        ),
        ("write_tribev2_holdout_contact_sheet", (buckets,), {"creator": "Stacey"}),
        (
            "tribev2_contact_sheet_cards",
            ([item], Path("/tmp")),
            {
                "show_metrics": False,
                "show_tribe_score": True,
            },
        ),
        ("tribev2_contact_sheet_html", (), {"title": "Review", "body": "<p>body</p>"}),
        ("tribev2_extract_thumbnail", ("/tmp/preview.mp4", Path("/tmp"), item), {}),
        (
            "tribev2_reel_analysis_rows",
            (),
            {"creator": "Stacey", "campaign_slug": "May"},
        ),
        ("tribev2_score_for_snapshot", ({"rendered_asset_id": "asset_1"},), {}),
        ("pearson_correlation", ([1.0, 2.0], [3.0, 4.0]), {}),
        ("tribev2_bucket_summary", (ranked,), {}),
        ("tribev2_bucket_lift", ({"avgViews": 2}, {"avgViews": 1}), {}),
        ("tribev2_metric_quality", (ranked, ["views"]), {}),
        (
            "tribev2_signal_summary",
            ({"meanAbsActivation": {"views": 0.5}},),
            {
                "sample_size": 20,
                "metric_quality": {"views": {"usableForCorrelation": True}},
            },
        ),
        ("tribev2_confidence_level", (20, True), {}),
    ]


def test_discoverability_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def discoverability_safe_content_contract(self, *args, **kwargs):
            calls.append(("discoverability_safe_content_contract", args, kwargs))
            return {
                "schema": "campaign_factory.discoverability_safe_content_contract.v1"
            }

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
            return {
                "schema": "creator_os.parent_factory_discoverability_loss_analysis.v1"
            }

        def parent_factory_waterfall_after_discoverability(self, *args, **kwargs):
            calls.append(
                ("parent_factory_waterfall_after_discoverability", args, kwargs)
            )
            return {
                "schema": "creator_os.parent_factory_waterfall_after_discoverability.v1"
            }

        def discoverability_prevention_audit(self, *args, **kwargs):
            calls.append(("discoverability_prevention_audit", args, kwargs))
            return {"schema": "creator_os.discoverability_prevention_audit.v1"}

        def discoverability_prevention_scorecard(self, *args, **kwargs):
            calls.append(("discoverability_prevention_scorecard", args, kwargs))
            return {"schema": "creator_os.discoverability_prevention_scorecard.v1"}

        def parent_factory_observed_discoverability_terms(self, *args, **kwargs):
            calls.append(
                ("parent_factory_observed_discoverability_terms", args, kwargs)
            )
            return [{"reason": "dm_reference", "matchedText": "dm"}]

        def parent_factory_captured_discoverability_evidence(self, *args, **kwargs):
            calls.append(
                ("parent_factory_captured_discoverability_evidence", args, kwargs)
            )
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
    assert factory.parent_factory_discoverability_loss_analysis(
        waterfall={"stages": []}
    ) == {
        "schema": "creator_os.parent_factory_discoverability_loss_analysis.v1",
    }
    assert factory.parent_factory_waterfall_after_discoverability() == {
        "schema": "creator_os.parent_factory_waterfall_after_discoverability.v1",
    }
    assert factory.discoverability_prevention_audit() == {
        "schema": "creator_os.discoverability_prevention_audit.v1"
    }
    assert factory.discoverability_prevention_scorecard() == {
        "schema": "creator_os.discoverability_prevention_scorecard.v1",
    }
    assert factory._parent_factory_observed_discoverability_terms() == [
        {"reason": "dm_reference", "matchedText": "dm"}
    ]
    assert factory._parent_factory_captured_discoverability_evidence() == [
        {"reason": "dm_reference", "matchedText": "dm"}
    ]
    assert factory._discoverability_text_values({"caption": "caption"}) == ["caption"]
    assert factory._discoverability_loss_category("dm_reference", "dm") == "dm_language"
    assert (
        factory._discoverability_prevention_stage("dm_language") == "caption_creation"
    )
    assert factory._discoverability_gate_fields({"caption": "dm me"}, {"caption"}) == [
        ("caption", "dm me")
    ]
    assert factory._discoverability_gate_result("intake", [("caption", "dm me")]) == {
        "gate": "intake"
    }
    assert (
        factory._discoverability_origin_stage("caption", "dm_reference")
        == "caption_generation"
    )
    assert factory._post_discoverability_downstream_confidence() == {
        "confidenceMethod": "wilson_lower_bound_95pct"
    }
    assert factory._discoverability_evidence_for_fields([("caption", "dm me")]) == [
        {"failureCategory": "dm_language"}
    ]

    assert calls == [
        ("discoverability_safe_content_contract", ("dm me",), {}),
        ("discoverability_intake_gate", ({"source_caption": "dm me"},), {}),
        ("discoverability_generation_gate", ({"caption_text": "dm me"},), {}),
        ("discoverability_pre_render_gate", ({"caption": "dm me"},), {}),
        ("discoverability_violation_origin_map", (), {}),
        (
            "parent_factory_discoverability_loss_analysis",
            (),
            {"waterfall": {"stages": []}},
        ),
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
            return {
                "schema": "campaign_factory.discoverability_safe_content_contract.v1"
            }

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
            return {
                "schema": "creator_os.parent_factory_discoverability_loss_analysis.v1"
            }

        def parent_factory_waterfall_after_discoverability(self, *args, **kwargs):
            calls.append(
                ("parent_factory_waterfall_after_discoverability", args, kwargs)
            )
            return {
                "schema": "creator_os.parent_factory_waterfall_after_discoverability.v1"
            }

        def discoverability_prevention_audit(self, *args, **kwargs):
            calls.append(("discoverability_prevention_audit", args, kwargs))
            return {"schema": "creator_os.discoverability_prevention_audit.v1"}

        def discoverability_prevention_scorecard(self, *args, **kwargs):
            calls.append(("discoverability_prevention_scorecard", args, kwargs))
            return {"schema": "creator_os.discoverability_prevention_scorecard.v1"}

        def parent_factory_observed_discoverability_terms(self, *args, **kwargs):
            calls.append(
                ("parent_factory_observed_discoverability_terms", args, kwargs)
            )
            return [{"reason": "dm_reference", "matchedText": "dm"}]

        def parent_factory_captured_discoverability_evidence(self, *args, **kwargs):
            calls.append(
                ("parent_factory_captured_discoverability_evidence", args, kwargs)
            )
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
    assert services.parent_factory_discoverability_loss_analysis(
        waterfall={"stages": []}
    ) == {
        "schema": "creator_os.parent_factory_discoverability_loss_analysis.v1",
    }
    assert services.parent_factory_waterfall_after_discoverability() == {
        "schema": "creator_os.parent_factory_waterfall_after_discoverability.v1",
    }
    assert services.discoverability_prevention_audit() == {
        "schema": "creator_os.discoverability_prevention_audit.v1"
    }
    assert services.discoverability_prevention_scorecard() == {
        "schema": "creator_os.discoverability_prevention_scorecard.v1",
    }
    assert services.parent_factory_observed_discoverability_terms() == [
        {"reason": "dm_reference", "matchedText": "dm"}
    ]
    assert services.parent_factory_captured_discoverability_evidence() == [
        {"reason": "dm_reference", "matchedText": "dm"}
    ]
    assert services.discoverability_text_values({"caption": "caption"}) == ["caption"]
    assert services.discoverability_loss_category("dm_reference", "dm") == "dm_language"
    assert (
        services.discoverability_prevention_stage("dm_language") == "caption_creation"
    )
    assert services.discoverability_gate_fields({"caption": "dm me"}, {"caption"}) == [
        ("caption", "dm me")
    ]
    assert services.discoverability_gate_result("intake", [("caption", "dm me")]) == {
        "gate": "intake"
    }
    assert (
        services.discoverability_origin_stage("caption", "dm_reference")
        == "caption_generation"
    )
    assert services.post_discoverability_downstream_confidence() == {
        "confidenceMethod": "wilson_lower_bound_95pct"
    }
    assert services.discoverability_evidence_for_fields([("caption", "dm me")]) == [
        {"failureCategory": "dm_language"}
    ]

    assert calls == [
        ("discoverability_safe_content_contract", ("dm me",), {}),
        ("discoverability_intake_gate", ({"source_caption": "dm me"},), {}),
        ("discoverability_generation_gate", ({"caption_text": "dm me"},), {}),
        ("discoverability_pre_render_gate", ({"caption": "dm me"},), {}),
        ("discoverability_violation_origin_map", (), {}),
        (
            "parent_factory_discoverability_loss_analysis",
            (),
            {"waterfall": {"stages": []}},
        ),
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
        (
            "register_surface_asset",
            (),
            {
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
            },
        ),
        (
            "surface_registration_components",
            (),
            {
                "input_path": Path("/tmp/surface.png"),
                "surface": "feed_single",
                "target_ratio": "1:1",
            },
        ),
        (
            "surface_registration_component",
            (Path("/tmp/surface.png"),),
            {
                "surface": "feed_single",
                "target_ratio": "1:1",
            },
        ),
        (
            "stage_surface_registration_file",
            (Path("/tmp/surface.png"), Path("/tmp/rendered")),
            {
                "content_surface": "feed_single",
                "content_hash": "abc123",
                "component_index": 0,
            },
        ),
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
        (
            "register_surface_asset",
            (),
            {
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
            },
        ),
        (
            "surface_registration_components",
            (),
            {
                "input_path": Path("/tmp/surface.png"),
                "surface": "feed_single",
                "target_ratio": "1:1",
            },
        ),
        (
            "surface_registration_component",
            (Path("/tmp/surface.png"),),
            {
                "surface": "feed_single",
                "target_ratio": "1:1",
            },
        ),
        (
            "stage_surface_registration_file",
            (Path("/tmp/surface.png"), Path("/tmp/rendered")),
            {
                "content_surface": "feed_single",
                "content_hash": "abc123",
                "component_index": 0,
            },
        ),
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

        def carousel_certification_proof(self, *args, **kwargs):
            calls.append(("carousel_certification_proof", args, kwargs))
            return {"schema": "creator_os.carousel_certification_proof.v1"}

        def certification_asset_for_surface(self, *args, **kwargs):
            calls.append(("certification_asset_for_surface", args, kwargs))
            return {"id": "asset_carousel"}

        def latest_proof_run_for_asset(self, *args, **kwargs):
            calls.append(("latest_proof_run_for_asset", args, kwargs))
            return {"id": "proof_carousel"}

        def latest_surface_metric_for_asset(self, *args, **kwargs):
            calls.append(("latest_surface_metric_for_asset", args, kwargs))
            return {"id": "metric_carousel"}

        def empty_surface_certification_audit(self, *args, **kwargs):
            calls.append(("empty_surface_certification_audit", args, kwargs))
            return {"contentSurface": args[0]}

        def surface_certification_audit(self, *args, **kwargs):
            calls.append(("surface_certification_audit", args, kwargs))
            return {"contentSurface": kwargs["asset"]["content_surface"]}

        def carousel_production_readiness(self, *args, **kwargs):
            calls.append(("carousel_production_readiness", args, kwargs))
            return {"schema": "creator_os.carousel_production_readiness.v1"}

        def carousel_proof_gap_analysis(self, *args, **kwargs):
            calls.append(("carousel_proof_gap_analysis", args, kwargs))
            return {"schema": "creator_os.carousel_proof_gap_analysis.v1"}

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
    assert factory._carousel_integrity_for_asset({"id": "asset_carousel"}) == {
        "assetId": "asset_carousel"
    }
    assert factory._carousel_component_signature([{"component_index": 0}]) == [
        {"componentIndex": 0}
    ]
    assert factory._carousel_media_item_signature([{"componentIndex": 0}]) == [
        {"componentIndex": 0}
    ]
    assert factory._carousel_signature_payload(
        [{"componentIndex": 0}], extra={"ok": True}
    ) == {"slideCount": 1}
    assert factory._carousel_boundary_result(
        "a_to_b", [{"componentIndex": 0}], [{"componentIndex": 0}]
    ) == {
        "boundary": "a_to_b",
    }
    assert factory._carousel_meta_child_payload_preview(
        asset={"id": "asset_carousel"},
        draft={},
        components=[],
    ) == {"children": []}
    assert factory.carousel_certification_proof(rendered_asset_id="asset_carousel") == {
        "schema": "creator_os.carousel_certification_proof.v1",
    }
    assert factory._certification_asset_for_surface(
        "feed_carousel", rendered_asset_id="asset_carousel"
    ) == {
        "id": "asset_carousel",
    }
    assert factory._latest_proof_run_for_asset("asset_carousel") == {
        "id": "proof_carousel"
    }
    assert factory._latest_surface_metric_for_asset(
        "asset_carousel", "feed_carousel"
    ) == {"id": "metric_carousel"}
    assert factory._empty_surface_certification_audit("feed_carousel") == {
        "contentSurface": "feed_carousel"
    }
    assert factory._surface_certification_audit(
        asset={"content_surface": "feed_carousel"},
        readiness={},
        draft_payload={},
        proof_run=None,
        metrics=None,
        carousel_integrity={},
    ) == {"contentSurface": "feed_carousel"}
    assert factory.carousel_production_readiness() == {
        "schema": "creator_os.carousel_production_readiness.v1"
    }
    assert factory.carousel_proof_gap_analysis() == {
        "schema": "creator_os.carousel_proof_gap_analysis.v1"
    }

    assert calls == [
        (
            "carousel_integrity_report",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "may",
                "rendered_asset_id": "asset_carousel",
            },
        ),
        (
            "carousel_child_metrics_plan",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "may",
                "rendered_asset_id": "asset_carousel",
            },
        ),
        (
            "carousel_report_assets",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "may",
                "rendered_asset_id": "asset_carousel",
            },
        ),
        ("carousel_integrity_for_asset", ({"id": "asset_carousel"},), {}),
        ("carousel_component_signature", ([{"component_index": 0}],), {}),
        ("carousel_media_item_signature", ([{"componentIndex": 0}],), {}),
        (
            "carousel_signature_payload",
            ([{"componentIndex": 0}],),
            {"extra": {"ok": True}},
        ),
        (
            "carousel_boundary_result",
            ("a_to_b", [{"componentIndex": 0}], [{"componentIndex": 0}]),
            {},
        ),
        (
            "carousel_meta_child_payload_preview",
            (),
            {
                "asset": {"id": "asset_carousel"},
                "draft": {},
                "components": [],
            },
        ),
        ("carousel_certification_proof", (), {"rendered_asset_id": "asset_carousel"}),
        (
            "certification_asset_for_surface",
            ("feed_carousel",),
            {"rendered_asset_id": "asset_carousel"},
        ),
        ("latest_proof_run_for_asset", ("asset_carousel",), {}),
        ("latest_surface_metric_for_asset", ("asset_carousel", "feed_carousel"), {}),
        ("empty_surface_certification_audit", ("feed_carousel",), {}),
        (
            "surface_certification_audit",
            (),
            {
                "asset": {"content_surface": "feed_carousel"},
                "readiness": {},
                "draft_payload": {},
                "proof_run": None,
                "metrics": None,
                "carousel_integrity": {},
            },
        ),
        ("carousel_production_readiness", (), {}),
        ("carousel_proof_gap_analysis", (), {}),
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

        def carousel_certification_proof(self, *args, **kwargs):
            calls.append(("carousel_certification_proof", args, kwargs))
            return {"schema": "creator_os.carousel_certification_proof.v1"}

        def certification_asset_for_surface(self, *args, **kwargs):
            calls.append(("certification_asset_for_surface", args, kwargs))
            return {"id": "asset_carousel"}

        def latest_proof_run_for_asset(self, *args, **kwargs):
            calls.append(("latest_proof_run_for_asset", args, kwargs))
            return {"id": "proof_carousel"}

        def latest_surface_metric_for_asset(self, *args, **kwargs):
            calls.append(("latest_surface_metric_for_asset", args, kwargs))
            return {"id": "metric_carousel"}

        def empty_surface_certification_audit(self, *args, **kwargs):
            calls.append(("empty_surface_certification_audit", args, kwargs))
            return {"contentSurface": args[0]}

        def surface_certification_audit(self, *args, **kwargs):
            calls.append(("surface_certification_audit", args, kwargs))
            return {"contentSurface": kwargs["asset"]["content_surface"]}

        def carousel_production_readiness(self, *args, **kwargs):
            calls.append(("carousel_production_readiness", args, kwargs))
            return {"schema": "creator_os.carousel_production_readiness.v1"}

        def carousel_proof_gap_analysis(self, *args, **kwargs):
            calls.append(("carousel_proof_gap_analysis", args, kwargs))
            return {"schema": "creator_os.carousel_proof_gap_analysis.v1"}

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
    assert services.carousel_integrity_for_asset({"id": "asset_carousel"}) == {
        "assetId": "asset_carousel"
    }
    assert services.carousel_component_signature([{"component_index": 0}]) == [
        {"componentIndex": 0}
    ]
    assert services.carousel_media_item_signature([{"componentIndex": 0}]) == [
        {"componentIndex": 0}
    ]
    assert services.carousel_signature_payload(
        [{"componentIndex": 0}], extra={"ok": True}
    ) == {"slideCount": 1}
    assert services.carousel_boundary_result(
        "a_to_b", [{"componentIndex": 0}], [{"componentIndex": 0}]
    ) == {
        "boundary": "a_to_b",
    }
    assert services.carousel_meta_child_payload_preview(
        asset={"id": "asset_carousel"},
        draft={},
        components=[],
    ) == {"children": []}
    assert services.carousel_certification_proof(
        rendered_asset_id="asset_carousel"
    ) == {
        "schema": "creator_os.carousel_certification_proof.v1",
    }
    assert services.certification_asset_for_surface(
        "feed_carousel", rendered_asset_id="asset_carousel"
    ) == {
        "id": "asset_carousel",
    }
    assert services.latest_proof_run_for_asset("asset_carousel") == {
        "id": "proof_carousel"
    }
    assert services.latest_surface_metric_for_asset(
        "asset_carousel", "feed_carousel"
    ) == {"id": "metric_carousel"}
    assert services.empty_surface_certification_audit("feed_carousel") == {
        "contentSurface": "feed_carousel"
    }
    assert services.surface_certification_audit(
        asset={"content_surface": "feed_carousel"},
        readiness={},
        draft_payload={},
        proof_run=None,
        metrics=None,
        carousel_integrity={},
    ) == {"contentSurface": "feed_carousel"}
    assert services.carousel_production_readiness() == {
        "schema": "creator_os.carousel_production_readiness.v1"
    }
    assert services.carousel_proof_gap_analysis() == {
        "schema": "creator_os.carousel_proof_gap_analysis.v1"
    }

    assert calls == [
        (
            "carousel_integrity_report",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "may",
                "rendered_asset_id": "asset_carousel",
            },
        ),
        (
            "carousel_child_metrics_plan",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "may",
                "rendered_asset_id": "asset_carousel",
            },
        ),
        (
            "carousel_report_assets",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "may",
                "rendered_asset_id": "asset_carousel",
            },
        ),
        ("carousel_integrity_for_asset", ({"id": "asset_carousel"},), {}),
        ("carousel_component_signature", ([{"component_index": 0}],), {}),
        ("carousel_media_item_signature", ([{"componentIndex": 0}],), {}),
        (
            "carousel_signature_payload",
            ([{"componentIndex": 0}],),
            {"extra": {"ok": True}},
        ),
        (
            "carousel_boundary_result",
            ("a_to_b", [{"componentIndex": 0}], [{"componentIndex": 0}]),
            {},
        ),
        (
            "carousel_meta_child_payload_preview",
            (),
            {
                "asset": {"id": "asset_carousel"},
                "draft": {},
                "components": [],
            },
        ),
        ("carousel_certification_proof", (), {"rendered_asset_id": "asset_carousel"}),
        (
            "certification_asset_for_surface",
            ("feed_carousel",),
            {"rendered_asset_id": "asset_carousel"},
        ),
        ("latest_proof_run_for_asset", ("asset_carousel",), {}),
        ("latest_surface_metric_for_asset", ("asset_carousel", "feed_carousel"), {}),
        ("empty_surface_certification_audit", ("feed_carousel",), {}),
        (
            "surface_certification_audit",
            (),
            {
                "asset": {"content_surface": "feed_carousel"},
                "readiness": {},
                "draft_payload": {},
                "proof_run": None,
                "metrics": None,
                "carousel_integrity": {},
            },
        ),
        ("carousel_production_readiness", (), {}),
        ("carousel_proof_gap_analysis", (), {}),
    ]


def test_surface_handoff_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def surface_handoff_readiness_report(self, *args, **kwargs):
            calls.append(("surface_handoff_readiness_report", args, kwargs))
            return {"schema": "campaign_factory.surface_handoff_readiness_report.v1"}

        def surface_draft_proof(self, *args, **kwargs):
            calls.append(("surface_draft_proof", args, kwargs))
            return {"schema": "campaign_factory.surface_draft_proof.v1"}

        def surface_report_assets(self, *args, **kwargs):
            calls.append(("surface_report_assets", args, kwargs))
            return [{"id": "asset_surface"}]

        def build_surface_readiness(self, *args, **kwargs):
            calls.append(("build_surface_readiness", args, kwargs))
            return [{"assetId": "asset_surface"}]

        def surface_draft_payload_for_readiness(self, *args, **kwargs):
            calls.append(("surface_draft_payload_for_readiness", args, kwargs))
            return {"assetId": args[0]["assetId"]}

        def surface_handoff_readiness_for_asset(self, *args, **kwargs):
            calls.append(("surface_handoff_readiness_for_asset", args, kwargs))
            return {"assetId": args[0]["id"], "canHandoff": True}

        def requires_operator_visual_review_for_handoff(self, *args, **kwargs):
            calls.append(("requires_operator_visual_review_for_handoff", args, kwargs))
            return False

        def asset_matches_creator(self, *args, **kwargs):
            calls.append(("asset_matches_creator", args, kwargs))
            return True

        def asset_components(self, *args, **kwargs):
            calls.append(("asset_components", args, kwargs))
            return [{"asset_id": args[0], "component_index": 0}]

    factory.services = FakeServices()

    assert factory.surface_handoff_readiness_report(
        creator="Stacey",
        campaign_slug="may",
        rendered_asset_id="asset_surface",
    ) == {"schema": "campaign_factory.surface_handoff_readiness_report.v1"}
    assert factory.surface_draft_proof(
        creator="Stacey",
        campaign="may",
        rendered_asset_id="asset_surface",
    ) == {"schema": "campaign_factory.surface_draft_proof.v1"}
    assert factory._surface_report_assets(creator="Stacey", campaign_slug="may") == [
        {"id": "asset_surface"}
    ]
    assert factory._build_surface_readiness([{"id": "asset_surface"}]) == [
        {"assetId": "asset_surface"}
    ]
    assert factory._surface_draft_payload_for_readiness(
        {"assetId": "asset_surface"}
    ) == {"assetId": "asset_surface"}
    assert factory._surface_handoff_readiness_for_asset({"id": "asset_surface"}) == {
        "assetId": "asset_surface",
        "canHandoff": True,
    }
    assert (
        factory._requires_operator_visual_review_for_handoff({"id": "asset_surface"})
        is False
    )
    assert factory._asset_matches_creator({"id": "asset_surface"}, "Stacey") is True
    assert factory._asset_components("asset_surface") == [
        {"asset_id": "asset_surface", "component_index": 0}
    ]

    assert calls == [
        (
            "surface_handoff_readiness_report",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "may",
                "rendered_asset_id": "asset_surface",
            },
        ),
        (
            "surface_draft_proof",
            (),
            {
                "creator": "Stacey",
                "campaign": "may",
                "rendered_asset_id": "asset_surface",
            },
        ),
        ("surface_report_assets", (), {"creator": "Stacey", "campaign_slug": "may"}),
        ("build_surface_readiness", ([{"id": "asset_surface"}],), {}),
        ("surface_draft_payload_for_readiness", ({"assetId": "asset_surface"},), {}),
        ("surface_handoff_readiness_for_asset", ({"id": "asset_surface"},), {}),
        ("requires_operator_visual_review_for_handoff", ({"id": "asset_surface"},), {}),
        ("asset_matches_creator", ({"id": "asset_surface"}, "Stacey"), {}),
        ("asset_components", ("asset_surface",), {}),
    ]


def test_core_services_delegates_surface_handoff_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeSurfaceHandoff:
        def surface_handoff_readiness_report(self, *args, **kwargs):
            calls.append(("surface_handoff_readiness_report", args, kwargs))
            return {"schema": "campaign_factory.surface_handoff_readiness_report.v1"}

        def surface_draft_proof(self, *args, **kwargs):
            calls.append(("surface_draft_proof", args, kwargs))
            return {"schema": "campaign_factory.surface_draft_proof.v1"}

        def surface_report_assets(self, *args, **kwargs):
            calls.append(("surface_report_assets", args, kwargs))
            return [{"id": "asset_surface"}]

        def build_surface_readiness(self, *args, **kwargs):
            calls.append(("build_surface_readiness", args, kwargs))
            return [{"assetId": "asset_surface"}]

        def surface_draft_payload_for_readiness(self, *args, **kwargs):
            calls.append(("surface_draft_payload_for_readiness", args, kwargs))
            return {"assetId": args[0]["assetId"]}

        def surface_handoff_readiness_for_asset(self, *args, **kwargs):
            calls.append(("surface_handoff_readiness_for_asset", args, kwargs))
            return {"assetId": args[0]["id"], "canHandoff": True}

        def requires_operator_visual_review_for_handoff(self, *args, **kwargs):
            calls.append(("requires_operator_visual_review_for_handoff", args, kwargs))
            return False

        def asset_matches_creator(self, *args, **kwargs):
            calls.append(("asset_matches_creator", args, kwargs))
            return True

        def asset_components(self, *args, **kwargs):
            calls.append(("asset_components", args, kwargs))
            return [{"asset_id": args[0], "component_index": 0}]

    services.surface_handoff = FakeSurfaceHandoff()

    assert services.surface_handoff_readiness_report(
        creator="Stacey",
        campaign_slug="may",
        rendered_asset_id="asset_surface",
    ) == {"schema": "campaign_factory.surface_handoff_readiness_report.v1"}
    assert services.surface_draft_proof(
        creator="Stacey",
        campaign="may",
        rendered_asset_id="asset_surface",
    ) == {"schema": "campaign_factory.surface_draft_proof.v1"}
    assert services.surface_report_assets(creator="Stacey", campaign_slug="may") == [
        {"id": "asset_surface"}
    ]
    assert services.build_surface_readiness([{"id": "asset_surface"}]) == [
        {"assetId": "asset_surface"}
    ]
    assert services.surface_draft_payload_for_readiness(
        {"assetId": "asset_surface"}
    ) == {"assetId": "asset_surface"}
    assert services.surface_handoff_readiness_for_asset({"id": "asset_surface"}) == {
        "assetId": "asset_surface",
        "canHandoff": True,
    }
    assert (
        services.requires_operator_visual_review_for_handoff({"id": "asset_surface"})
        is False
    )
    assert services.asset_matches_creator({"id": "asset_surface"}, "Stacey") is True
    assert services.asset_components("asset_surface") == [
        {"asset_id": "asset_surface", "component_index": 0}
    ]

    assert calls == [
        (
            "surface_handoff_readiness_report",
            (),
            {
                "creator": "Stacey",
                "campaign_slug": "may",
                "rendered_asset_id": "asset_surface",
            },
        ),
        (
            "surface_draft_proof",
            (),
            {
                "creator": "Stacey",
                "campaign": "may",
                "rendered_asset_id": "asset_surface",
            },
        ),
        ("surface_report_assets", (), {"creator": "Stacey", "campaign_slug": "may"}),
        ("build_surface_readiness", ([{"id": "asset_surface"}],), {}),
        ("surface_draft_payload_for_readiness", ({"assetId": "asset_surface"},), {}),
        ("surface_handoff_readiness_for_asset", ({"id": "asset_surface"},), {}),
        ("requires_operator_visual_review_for_handoff", ({"id": "asset_surface"},), {}),
        ("asset_matches_creator", ({"id": "asset_surface"}, "Stacey"), {}),
        ("asset_components", ("asset_surface",), {}),
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

        def exception_queue_report(self, *args, **kwargs):
            calls.append(("exception_queue_report", args, kwargs))
            return {"schema": "creator_os.exception_queue_report.v1"}

        def exception_queue_summary(self, *args, **kwargs):
            calls.append(("exception_queue_summary", args, kwargs))
            return {"schema": "creator_os.exception_queue_summary.v1"}

        def exception_queue_priority_report(self, *args, **kwargs):
            calls.append(("exception_queue_priority_report", args, kwargs))
            return {"schema": "creator_os.exception_queue_priority_report.v1"}

        def exception_queue_owner_report(self, *args, **kwargs):
            calls.append(("exception_queue_owner_report", args, kwargs))
            return {"schema": "creator_os.exception_queue_owner_report.v1"}

        def exception_severity_for_reason(self, *args, **kwargs):
            calls.append(("exception_severity_for_reason", args, kwargs))
            return "critical"

        def exception_next_action(self, *args, **kwargs):
            calls.append(("exception_next_action", args, kwargs))
            return "repair_caption_contract"

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
    assert factory.trust_summary("may") == {
        "schema": "campaign_factory.trust_summary.v1"
    }
    assert factory.resolve_exception("ex_1", resolution="fixed", operator="op") == {
        "status": "resolved"
    }
    assert factory.snooze_exception(
        "ex_1", until="2026-01-03T00:00:00+00:00", reason="wait", operator="op"
    ) == {"status": "snoozed"}
    assert factory.reopen_exception("ex_1", reason="ready", operator="op") == {
        "status": "open"
    }
    assert factory._update_exception_status(
        "ex_1",
        "resolved",
        resolution={"resolution": "fixed"},
        snoozed_until=None,
    ) == {"status": "resolved"}
    assert factory._exception_payload({"id": "ex_1"}) == {"id": "ex_1"}
    assert factory.exception_queue_report(daily_plan={"accounts": []}) == {
        "schema": "creator_os.exception_queue_report.v1"
    }
    assert factory.exception_queue_summary(execution_readiness={"blockers": []}) == {
        "schema": "creator_os.exception_queue_summary.v1"
    }
    assert factory.exception_queue_priority_report(
        publishability_report={"assets": []}
    ) == {
        "schema": "creator_os.exception_queue_priority_report.v1",
    }
    assert factory.exception_queue_owner_report(
        surface_readiness_report={"items": []}
    ) == {
        "schema": "creator_os.exception_queue_owner_report.v1",
    }
    assert factory._exception_severity_for_reason("inventory_shortfall") == "critical"
    assert (
        factory._exception_next_action("caption_blocked") == "repair_caption_contract"
    )

    assert calls == [
        (
            "create_exception",
            (),
            {
                "reason_code": "missing_account_assignment",
                "severity": "high",
                "campaign_id": "camp_1",
                "account_id": "acct_1",
                "entity_graph_id": "graph_1",
                "recommendation_item_id": "rec_1",
                "payload": {"source": "test"},
                "commit": False,
            },
        ),
        ("exception", ("ex_1",), {}),
        ("exceptions", ("may",), {"status": "all"}),
        ("trust_summary", ("may",), {}),
        ("resolve_exception", ("ex_1",), {"resolution": "fixed", "operator": "op"}),
        (
            "snooze_exception",
            ("ex_1",),
            {
                "until": "2026-01-03T00:00:00+00:00",
                "reason": "wait",
                "operator": "op",
            },
        ),
        ("reopen_exception", ("ex_1",), {"reason": "ready", "operator": "op"}),
        (
            "update_exception_status",
            ("ex_1", "resolved"),
            {
                "resolution": {"resolution": "fixed"},
                "snoozed_until": None,
            },
        ),
        ("exception_payload", ({"id": "ex_1"},), {}),
        (
            "exception_queue_report",
            (),
            {
                "daily_plan": {"accounts": []},
                "execution_readiness": None,
                "publishability_report": None,
                "surface_readiness_report": None,
            },
        ),
        ("exception_queue_summary", (), {"execution_readiness": {"blockers": []}}),
        (
            "exception_queue_priority_report",
            (),
            {"publishability_report": {"assets": []}},
        ),
        (
            "exception_queue_owner_report",
            (),
            {"surface_readiness_report": {"items": []}},
        ),
        ("exception_severity_for_reason", ("inventory_shortfall",), {}),
        ("exception_next_action", ("caption_blocked",), {}),
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

        def exception_queue_report(self, *args, **kwargs):
            calls.append(("exception_queue_report", args, kwargs))
            return {"schema": "creator_os.exception_queue_report.v1"}

        def exception_queue_summary(self, *args, **kwargs):
            calls.append(("exception_queue_summary", args, kwargs))
            return {"schema": "creator_os.exception_queue_summary.v1"}

        def exception_queue_priority_report(self, *args, **kwargs):
            calls.append(("exception_queue_priority_report", args, kwargs))
            return {"schema": "creator_os.exception_queue_priority_report.v1"}

        def exception_queue_owner_report(self, *args, **kwargs):
            calls.append(("exception_queue_owner_report", args, kwargs))
            return {"schema": "creator_os.exception_queue_owner_report.v1"}

        def exception_queue_item(self, *args, **kwargs):
            calls.append(("exception_queue_item", args, kwargs))
            return {"exceptionId": "exception_1"}

        def exception_severity_for_reason(self, *args, **kwargs):
            calls.append(("exception_severity_for_reason", args, kwargs))
            return "critical"

        def exception_next_action(self, *args, **kwargs):
            calls.append(("exception_next_action", args, kwargs))
            return "fill_validated_inventory_buffer"

        def exception_category_for_reason(self, *args, **kwargs):
            calls.append(("exception_category_for_reason", args, kwargs))
            return "inventory"

        def exception_owner_for_category(self, *args, **kwargs):
            calls.append(("exception_owner_for_category", args, kwargs))
            return "campaign_factory_operator"

        def exception_repairable(self, *args, **kwargs):
            calls.append(("exception_repairable", args, kwargs))
            return True

        def exception_resolution_minutes(self, *args, **kwargs):
            calls.append(("exception_resolution_minutes", args, kwargs))
            return 30

    services.exceptions = FakeExceptions()

    assert services.create_exception(
        reason_code="missing_account_assignment", severity="high"
    ) == {"id": "ex_1"}
    assert services.exception("ex_1") == {"id": "ex_1"}
    assert services.exceptions_report("may", status="open") == {"exceptions": []}
    assert services.trust_summary("may") == {
        "schema": "campaign_factory.trust_summary.v1"
    }
    assert services.resolve_exception("ex_1", resolution="fixed", operator="op") == {
        "status": "resolved"
    }
    assert services.snooze_exception(
        "ex_1", until="2026-01-03T00:00:00+00:00", reason="wait", operator="op"
    ) == {
        "status": "snoozed",
    }
    assert services.reopen_exception("ex_1", reason="ready", operator="op") == {
        "status": "open"
    }
    assert services.update_exception_status(
        "ex_1", "resolved", resolution={"resolution": "fixed"}
    ) == {
        "status": "resolved",
    }
    assert services.exception_payload({"id": "ex_1"}) == {"id": "ex_1"}
    assert services.exception_queue_report(daily_plan={"accounts": []}) == {
        "schema": "creator_os.exception_queue_report.v1"
    }
    assert services.exception_queue_summary(execution_readiness={"blockers": []}) == {
        "schema": "creator_os.exception_queue_summary.v1"
    }
    assert services.exception_queue_priority_report(
        publishability_report={"assets": []}
    ) == {
        "schema": "creator_os.exception_queue_priority_report.v1",
    }
    assert services.exception_queue_owner_report(
        surface_readiness_report={"items": []}
    ) == {
        "schema": "creator_os.exception_queue_owner_report.v1",
    }
    assert services.exception_queue_item(
        severity="critical",
        system="inventory",
        account="",
        asset="asset_1",
        reason="inventory_shortfall",
        next_action="fill_validated_inventory_buffer",
        count=2,
    ) == {"exceptionId": "exception_1"}
    assert services.exception_severity_for_reason("inventory_shortfall") == "critical"
    assert (
        services.exception_next_action("inventory_shortfall")
        == "fill_validated_inventory_buffer"
    )
    assert (
        services.exception_category_for_reason("inventory_shortfall", "inventory")
        == "inventory"
    )
    assert (
        services.exception_owner_for_category("inventory", "daily_plan")
        == "campaign_factory_operator"
    )
    assert services.exception_repairable("inventory_shortfall") is True
    assert services.exception_resolution_minutes("inventory_shortfall", count=2) == 30

    assert calls == [
        (
            "create_exception",
            (),
            {
                "reason_code": "missing_account_assignment",
                "severity": "high",
                "campaign_id": None,
                "account_id": None,
                "entity_graph_id": None,
                "recommendation_item_id": None,
                "payload": None,
                "commit": True,
            },
        ),
        ("exception", ("ex_1",), {}),
        ("exceptions", ("may",), {"status": "open"}),
        ("trust_summary", ("may",), {}),
        ("resolve_exception", ("ex_1",), {"resolution": "fixed", "operator": "op"}),
        (
            "snooze_exception",
            ("ex_1",),
            {
                "until": "2026-01-03T00:00:00+00:00",
                "reason": "wait",
                "operator": "op",
            },
        ),
        ("reopen_exception", ("ex_1",), {"reason": "ready", "operator": "op"}),
        (
            "update_exception_status",
            ("ex_1", "resolved"),
            {
                "resolution": {"resolution": "fixed"},
                "snoozed_until": None,
            },
        ),
        ("exception_payload", ({"id": "ex_1"},), {}),
        (
            "exception_queue_report",
            (),
            {
                "daily_plan": {"accounts": []},
                "execution_readiness": None,
                "publishability_report": None,
                "surface_readiness_report": None,
            },
        ),
        ("exception_queue_summary", (), {"execution_readiness": {"blockers": []}}),
        (
            "exception_queue_priority_report",
            (),
            {"publishability_report": {"assets": []}},
        ),
        (
            "exception_queue_owner_report",
            (),
            {"surface_readiness_report": {"items": []}},
        ),
        (
            "exception_queue_item",
            (),
            {
                "severity": "critical",
                "system": "inventory",
                "account": "",
                "asset": "asset_1",
                "reason": "inventory_shortfall",
                "next_action": "fill_validated_inventory_buffer",
                "count": 2,
            },
        ),
        ("exception_severity_for_reason", ("inventory_shortfall",), {}),
        ("exception_next_action", ("inventory_shortfall",), {}),
        ("exception_category_for_reason", ("inventory_shortfall", "inventory"), {}),
        ("exception_owner_for_category", ("inventory", "daily_plan"), {}),
        ("exception_repairable", ("inventory_shortfall",), {}),
        ("exception_resolution_minutes", ("inventory_shortfall",), {"count": 2}),
    ]


def test_campaign_factory_delegates_creator_os_execution_readiness_to_services() -> (
    None
):
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def creator_os_execution_readiness(self, **kwargs):
            calls.append(("creator_os_execution_readiness", kwargs))
            return {"schema": "creator_os.execution_readiness.v1", "ok": True}

    factory.services = FakeServices()

    assert factory.creator_os_execution_readiness(
        creator="Stacey",
        requested_count=2,
        threadsdash_report={"schema": "threadsdash.report.v1"},
        schedule_plan={"schema": "creator_os.schedule_plan.v1"},
        time_plan={"schema": "creator_os.time_plan.v1"},
        generated_at="2026-06-06T12:00:00Z",
    ) == {"schema": "creator_os.execution_readiness.v1", "ok": True}
    assert calls == [
        (
            "creator_os_execution_readiness",
            {
                "creator": "Stacey",
                "requested_count": 2,
                "threadsdash_report": {"schema": "threadsdash.report.v1"},
                "schedule_plan": {"schema": "creator_os.schedule_plan.v1"},
                "time_plan": {"schema": "creator_os.time_plan.v1"},
                "generated_at": "2026-06-06T12:00:00Z",
            },
        )
    ]


def test_core_services_delegates_creator_os_execution_readiness_to_repository(
    tmp_path,
) -> None:
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
    calls = []

    try:

        def fake_execution_readiness(**kwargs):
            calls.append(("creator_os_execution_readiness", kwargs))
            return {"schema": "creator_os.execution_readiness.v1", "ok": True}

        factory.services.execution_readiness.creator_os_execution_readiness = (
            fake_execution_readiness
        )

        assert factory.services.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=2,
            threadsdash_report={"schema": "threadsdash.report.v1"},
            schedule_plan={"schema": "creator_os.schedule_plan.v1"},
            time_plan={"schema": "creator_os.time_plan.v1"},
            generated_at="2026-06-06T12:00:00Z",
        ) == {"schema": "creator_os.execution_readiness.v1", "ok": True}
        assert calls == [
            (
                "creator_os_execution_readiness",
                {
                    "creator": "Stacey",
                    "requested_count": 2,
                    "threadsdash_report": {"schema": "threadsdash.report.v1"},
                    "schedule_plan": {"schema": "creator_os.schedule_plan.v1"},
                    "time_plan": {"schema": "creator_os.time_plan.v1"},
                    "generated_at": "2026-06-06T12:00:00Z",
                },
            )
        ]
    finally:
        factory.close()


def test_campaign_factory_delegates_creator_os_200_account_acceptance_suite_to_services() -> (
    None
):
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def creator_os_200_account_acceptance_suite(self, **kwargs):
            calls.append(("creator_os_200_account_acceptance_suite", kwargs))
            return {"schema": "creator_os.200_account_acceptance_suite.v1", "ok": True}

    factory.services = FakeServices()

    assert factory.creator_os_200_account_acceptance_suite(
        accounts=50,
        creators=2,
        daily_obligations=100,
        draft_inventory=300,
        warming_accounts=4,
        restricted_accounts=3,
        manual_review_accounts=2,
        mixed_surfaces=False,
        generated_at="2026-06-08T12:00:00+00:00",
    ) == {"schema": "creator_os.200_account_acceptance_suite.v1", "ok": True}
    assert calls == [
        (
            "creator_os_200_account_acceptance_suite",
            {
                "accounts": 50,
                "creators": 2,
                "daily_obligations": 100,
                "draft_inventory": 300,
                "warming_accounts": 4,
                "restricted_accounts": 3,
                "manual_review_accounts": 2,
                "mixed_surfaces": False,
                "generated_at": "2026-06-08T12:00:00+00:00",
            },
        )
    ]


def test_core_services_delegates_creator_os_200_account_acceptance_suite_to_repository(
    tmp_path,
) -> None:
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
    calls = []

    try:

        def fake_acceptance_suite(**kwargs):
            calls.append(("creator_os_200_account_acceptance_suite", kwargs))
            return {"schema": "creator_os.200_account_acceptance_suite.v1", "ok": True}

        factory.services.acceptance_suite.creator_os_200_account_acceptance_suite = (
            fake_acceptance_suite
        )

        assert factory.services.creator_os_200_account_acceptance_suite(
            accounts=50,
            creators=2,
            daily_obligations=100,
            draft_inventory=300,
            warming_accounts=4,
            restricted_accounts=3,
            manual_review_accounts=2,
            mixed_surfaces=False,
            generated_at="2026-06-08T12:00:00+00:00",
        ) == {"schema": "creator_os.200_account_acceptance_suite.v1", "ok": True}
        assert calls == [
            (
                "creator_os_200_account_acceptance_suite",
                {
                    "accounts": 50,
                    "creators": 2,
                    "daily_obligations": 100,
                    "draft_inventory": 300,
                    "warming_accounts": 4,
                    "restricted_accounts": 3,
                    "manual_review_accounts": 2,
                    "mixed_surfaces": False,
                    "generated_at": "2026-06-08T12:00:00+00:00",
                },
            )
        ]
    finally:
        factory.close()


def test_campaign_factory_delegates_readiness_report_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def creator_os_100_account_proof(self):
            calls.append(("creator_os_100_account_proof", (), {}))
            return {"schema": "creator_os.100_account_proof.v1"}

        def creator_os_volume_acceptance_suite(self):
            calls.append(("creator_os_volume_acceptance_suite", (), {}))
            return {"schema": "creator_os.volume_acceptance_suite.v1"}

        def surface_readiness_scorecard(self):
            calls.append(("surface_readiness_scorecard", (), {}))
            return {"schema": "creator_os.surface_readiness_scorecard.v1"}

        def creator_os_10_0_readiness_report(self):
            calls.append(("creator_os_10_0_readiness_report", (), {}))
            return {"schema": "creator_os.10_0_readiness_report.v1"}

        def creator_os_9_5_readiness_report(self):
            calls.append(("creator_os_9_5_readiness_report", (), {}))
            return {"schema": "creator_os.9_5_readiness_report.v1"}

    factory.services = FakeServices()

    assert factory.creator_os_100_account_proof() == {
        "schema": "creator_os.100_account_proof.v1"
    }
    assert factory.creator_os_volume_acceptance_suite() == {
        "schema": "creator_os.volume_acceptance_suite.v1"
    }
    assert factory.surface_readiness_scorecard() == {
        "schema": "creator_os.surface_readiness_scorecard.v1"
    }
    assert factory.creator_os_10_0_readiness_report() == {
        "schema": "creator_os.10_0_readiness_report.v1"
    }
    assert factory.creator_os_9_5_readiness_report() == {
        "schema": "creator_os.9_5_readiness_report.v1"
    }
    assert calls == [
        ("creator_os_100_account_proof", (), {}),
        ("creator_os_volume_acceptance_suite", (), {}),
        ("surface_readiness_scorecard", (), {}),
        ("creator_os_10_0_readiness_report", (), {}),
        ("creator_os_9_5_readiness_report", (), {}),
    ]


def test_core_services_delegates_readiness_report_methods_to_repository(
    tmp_path,
) -> None:
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
    calls = []

    try:

        class FakeReadinessReport:
            conn = factory.conn

            def creator_os_100_account_proof(self):
                calls.append(("creator_os_100_account_proof", (), {}))
                return {"schema": "creator_os.100_account_proof.v1"}

            def creator_os_volume_acceptance_suite(self):
                calls.append(("creator_os_volume_acceptance_suite", (), {}))
                return {"schema": "creator_os.volume_acceptance_suite.v1"}

            def surface_readiness_scorecard(self):
                calls.append(("surface_readiness_scorecard", (), {}))
                return {"schema": "creator_os.surface_readiness_scorecard.v1"}

            def creator_os_10_0_readiness_report(self):
                calls.append(("creator_os_10_0_readiness_report", (), {}))
                return {"schema": "creator_os.10_0_readiness_report.v1"}

            def creator_os_9_5_readiness_report(self):
                calls.append(("creator_os_9_5_readiness_report", (), {}))
                return {"schema": "creator_os.9_5_readiness_report.v1"}

        factory.services.readiness_report = FakeReadinessReport()

        assert factory.services.creator_os_100_account_proof() == {
            "schema": "creator_os.100_account_proof.v1"
        }
        assert factory.services.creator_os_volume_acceptance_suite() == {
            "schema": "creator_os.volume_acceptance_suite.v1"
        }
        assert factory.services.surface_readiness_scorecard() == {
            "schema": "creator_os.surface_readiness_scorecard.v1"
        }
        assert factory.services.creator_os_10_0_readiness_report() == {
            "schema": "creator_os.10_0_readiness_report.v1"
        }
        assert factory.services.creator_os_9_5_readiness_report() == {
            "schema": "creator_os.9_5_readiness_report.v1"
        }
        assert calls == [
            ("creator_os_100_account_proof", (), {}),
            ("creator_os_volume_acceptance_suite", (), {}),
            ("surface_readiness_scorecard", (), {}),
            ("creator_os_10_0_readiness_report", (), {}),
            ("creator_os_9_5_readiness_report", (), {}),
        ]
    finally:
        factory.close()


def test_campaign_factory_delegates_live_scale_report_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def creator_os_live_100_account_readiness(self):
            calls.append(("creator_os_live_100_account_readiness", (), {}))
            return {"schema": "creator_os.live_100_account_readiness.v1"}

        def creator_os_live_scale_runbook(self):
            calls.append(("creator_os_live_scale_runbook", (), {}))
            return {"schema": "creator_os.live_scale_runbook.v1"}

        def creator_os_live_scale_scorecard(self):
            calls.append(("creator_os_live_scale_scorecard", (), {}))
            return {"schema": "creator_os.live_scale_scorecard.v1"}

        def actual_account_operational_counts(self):
            calls.append(("actual_account_operational_counts", (), {}))
            return {
                "totalAccounts": 100,
                "blockedAccounts": 0,
                "safeAccounts": 100,
                "warmingAccounts": 0,
            }

        def live_100_exact_shortfall(self, **kwargs):
            calls.append(("live_100_exact_shortfall", (), kwargs))
            return "accounts:5"

    factory.services = FakeServices()

    assert factory.creator_os_live_100_account_readiness() == {
        "schema": "creator_os.live_100_account_readiness.v1"
    }
    assert factory.creator_os_live_scale_runbook() == {
        "schema": "creator_os.live_scale_runbook.v1"
    }
    assert factory.creator_os_live_scale_scorecard() == {
        "schema": "creator_os.live_scale_scorecard.v1"
    }
    assert factory._actual_account_operational_counts() == {
        "totalAccounts": 100,
        "blockedAccounts": 0,
        "safeAccounts": 100,
        "warmingAccounts": 0,
    }
    assert (
        factory._live_100_exact_shortfall(
            accounts={"totalAccounts": 95, "blockedAccounts": 0},
            available_inventory=100,
            required_inventory=900,
            available_parents=20,
            required_parents=30,
        )
        == "accounts:5"
    )
    assert calls == [
        ("creator_os_live_100_account_readiness", (), {}),
        ("creator_os_live_scale_runbook", (), {}),
        ("creator_os_live_scale_scorecard", (), {}),
        ("actual_account_operational_counts", (), {}),
        (
            "live_100_exact_shortfall",
            (),
            {
                "accounts": {"totalAccounts": 95, "blockedAccounts": 0},
                "available_inventory": 100,
                "required_inventory": 900,
                "available_parents": 20,
                "required_parents": 30,
            },
        ),
    ]


def test_core_services_delegates_live_scale_report_methods_to_repository(
    tmp_path,
) -> None:
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
    calls = []

    try:

        class FakeLiveScale:
            conn = factory.conn

            def creator_os_live_100_account_readiness(self):
                calls.append(("creator_os_live_100_account_readiness", (), {}))
                return {"schema": "creator_os.live_100_account_readiness.v1"}

            def creator_os_live_scale_runbook(self):
                calls.append(("creator_os_live_scale_runbook", (), {}))
                return {"schema": "creator_os.live_scale_runbook.v1"}

            def creator_os_live_scale_scorecard(self):
                calls.append(("creator_os_live_scale_scorecard", (), {}))
                return {"schema": "creator_os.live_scale_scorecard.v1"}

            def actual_account_operational_counts(self):
                calls.append(("actual_account_operational_counts", (), {}))
                return {
                    "totalAccounts": 100,
                    "blockedAccounts": 0,
                    "safeAccounts": 100,
                    "warmingAccounts": 0,
                }

            def live_100_exact_shortfall(self, **kwargs):
                calls.append(("live_100_exact_shortfall", (), kwargs))
                return "parent_inventory:10"

        factory.services.live_scale = FakeLiveScale()

        assert factory.services.creator_os_live_100_account_readiness() == {
            "schema": "creator_os.live_100_account_readiness.v1"
        }
        assert factory.services.creator_os_live_scale_runbook() == {
            "schema": "creator_os.live_scale_runbook.v1"
        }
        assert factory.services.creator_os_live_scale_scorecard() == {
            "schema": "creator_os.live_scale_scorecard.v1"
        }
        assert factory.services.actual_account_operational_counts() == {
            "totalAccounts": 100,
            "blockedAccounts": 0,
            "safeAccounts": 100,
            "warmingAccounts": 0,
        }
        assert (
            factory.services.live_100_exact_shortfall(
                accounts={"totalAccounts": 100, "blockedAccounts": 0},
                available_inventory=900,
                required_inventory=900,
                available_parents=20,
                required_parents=30,
            )
            == "parent_inventory:10"
        )
        assert calls == [
            ("creator_os_live_100_account_readiness", (), {}),
            ("creator_os_live_scale_runbook", (), {}),
            ("creator_os_live_scale_scorecard", (), {}),
            ("actual_account_operational_counts", (), {}),
            (
                "live_100_exact_shortfall",
                (),
                {
                    "accounts": {"totalAccounts": 100, "blockedAccounts": 0},
                    "available_inventory": 900,
                    "required_inventory": 900,
                    "available_parents": 20,
                    "required_parents": 30,
                },
            ),
        ]
    finally:
        factory.close()


def test_campaign_factory_delegates_live_account_acceptance_methods_to_services() -> (
    None
):
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def creator_os_live_account_acceptance(self, **kwargs):
            calls.append(("creator_os_live_account_acceptance", (), kwargs))
            return {"schema": "creator_os.live_account_acceptance.v1"}

        def creator_os_staged_live_acceptance(self, **kwargs):
            calls.append(("creator_os_staged_live_acceptance", (), kwargs))
            return {"schema": "creator_os.staged_live_acceptance.v1"}

        def live_acceptance_actuals(self, **kwargs):
            calls.append(("live_acceptance_actuals", (), kwargs))
            return {"metricsImported": True}

        def live_acceptance_missed_dispatches(self, report):
            calls.append(("live_acceptance_missed_dispatches", (report,), {}))
            return 1

        def live_acceptance_duplicate_publishes(self, report):
            calls.append(("live_acceptance_duplicate_publishes", (report,), {}))
            return 2

        def live_acceptance_restricted_scheduled(self, report):
            calls.append(("live_acceptance_restricted_scheduled", (report,), {}))
            return 3

        def live_acceptance_surface_contract_violations(self, report):
            calls.append(("live_acceptance_surface_contract_violations", (report,), {}))
            return 4

        def live_acceptance_metrics_imported(self):
            calls.append(("live_acceptance_metrics_imported", (), {}))
            return True

        def live_acceptance_blocker_for(self, key):
            calls.append(("live_acceptance_blocker_for", (key,), {}))
            return "metrics_not_imported"

    factory.services = FakeServices()

    assert factory.creator_os_live_account_acceptance(
        account_target=10, content_surface="reel"
    ) == {
        "schema": "creator_os.live_account_acceptance.v1",
    }
    assert factory.creator_os_staged_live_acceptance(
        stages=[10], content_surface="reel"
    ) == {
        "schema": "creator_os.staged_live_acceptance.v1",
    }
    assert factory._live_acceptance_actuals(
        account_target=10,
        threadsdash_report={"missedDispatchCount": 1},
        required_inventory=30,
        available_inventory=20,
        exception_count=1,
    ) == {"metricsImported": True}
    assert factory._live_acceptance_missed_dispatches({"missedDispatchCount": 1}) == 1
    assert factory._live_acceptance_duplicate_publishes({"duplicatePublishes": 2}) == 2
    assert (
        factory._live_acceptance_restricted_scheduled(
            {"restrictedAccountsScheduled": 3}
        )
        == 3
    )
    assert (
        factory._live_acceptance_surface_contract_violations(
            {"surfaceContractViolations": 4}
        )
        == 4
    )
    assert factory._live_acceptance_metrics_imported() is True
    assert (
        factory._live_acceptance_blocker_for("metricsImported")
        == "metrics_not_imported"
    )

    assert calls == [
        (
            "creator_os_live_account_acceptance",
            (),
            {
                "account_target": 10,
                "posts_per_account_per_day": 3,
                "buffer_days": 3,
                "content_surface": "reel",
                "threadsdash_report": None,
            },
        ),
        (
            "creator_os_staged_live_acceptance",
            (),
            {"stages": [10], "content_surface": "reel", "threadsdash_report": None},
        ),
        (
            "live_acceptance_actuals",
            (),
            {
                "account_target": 10,
                "threadsdash_report": {"missedDispatchCount": 1},
                "required_inventory": 30,
                "available_inventory": 20,
                "exception_count": 1,
            },
        ),
        ("live_acceptance_missed_dispatches", ({"missedDispatchCount": 1},), {}),
        ("live_acceptance_duplicate_publishes", ({"duplicatePublishes": 2},), {}),
        (
            "live_acceptance_restricted_scheduled",
            ({"restrictedAccountsScheduled": 3},),
            {},
        ),
        (
            "live_acceptance_surface_contract_violations",
            ({"surfaceContractViolations": 4},),
            {},
        ),
        ("live_acceptance_metrics_imported", (), {}),
        ("live_acceptance_blocker_for", ("metricsImported",), {}),
    ]


def test_core_services_delegates_live_account_acceptance_methods_to_repository(
    tmp_path,
) -> None:
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
    calls = []

    try:

        class FakeLiveAcceptance:
            conn = factory.conn

            def creator_os_live_account_acceptance(self, **kwargs):
                calls.append(("creator_os_live_account_acceptance", (), kwargs))
                return {"schema": "creator_os.live_account_acceptance.v1"}

            def creator_os_staged_live_acceptance(self, **kwargs):
                calls.append(("creator_os_staged_live_acceptance", (), kwargs))
                return {"schema": "creator_os.staged_live_acceptance.v1"}

            def live_acceptance_actuals(self, **kwargs):
                calls.append(("live_acceptance_actuals", (), kwargs))
                return {"metricsImported": True}

            def live_acceptance_missed_dispatches(self, report):
                calls.append(("live_acceptance_missed_dispatches", (report,), {}))
                return 1

            def live_acceptance_duplicate_publishes(self, report):
                calls.append(("live_acceptance_duplicate_publishes", (report,), {}))
                return 2

            def live_acceptance_restricted_scheduled(self, report):
                calls.append(("live_acceptance_restricted_scheduled", (report,), {}))
                return 3

            def live_acceptance_surface_contract_violations(self, report):
                calls.append(
                    ("live_acceptance_surface_contract_violations", (report,), {})
                )
                return 4

            def live_acceptance_metrics_imported(self):
                calls.append(("live_acceptance_metrics_imported", (), {}))
                return True

            def live_acceptance_blocker_for(self, key):
                calls.append(("live_acceptance_blocker_for", (key,), {}))
                return "metrics_not_imported"

        factory.services.live_acceptance = FakeLiveAcceptance()

        assert factory.services.creator_os_live_account_acceptance(
            account_target=10, content_surface="feed_single"
        ) == {
            "schema": "creator_os.live_account_acceptance.v1",
        }
        assert factory.services.creator_os_staged_live_acceptance(
            stages=[10], content_surface="feed_single"
        ) == {
            "schema": "creator_os.staged_live_acceptance.v1",
        }
        assert factory.services.live_acceptance_actuals(
            account_target=10,
            threadsdash_report={},
            required_inventory=30,
            available_inventory=20,
            exception_count=1,
        ) == {"metricsImported": True}
        assert (
            factory.services.live_acceptance_missed_dispatches(
                {"missedDispatchCount": 1}
            )
            == 1
        )
        assert (
            factory.services.live_acceptance_duplicate_publishes(
                {"duplicatePublishes": 2}
            )
            == 2
        )
        assert (
            factory.services.live_acceptance_restricted_scheduled(
                {"restrictedAccountsScheduled": 3}
            )
            == 3
        )
        assert (
            factory.services.live_acceptance_surface_contract_violations(
                {"surfaceContractViolations": 4}
            )
            == 4
        )
        assert factory.services.live_acceptance_metrics_imported() is True
        assert (
            factory.services.live_acceptance_blocker_for("metricsImported")
            == "metrics_not_imported"
        )

        assert calls == [
            (
                "creator_os_live_account_acceptance",
                (),
                {
                    "account_target": 10,
                    "posts_per_account_per_day": 3,
                    "buffer_days": 3,
                    "content_surface": "feed_single",
                    "threadsdash_report": None,
                },
            ),
            (
                "creator_os_staged_live_acceptance",
                (),
                {
                    "stages": [10],
                    "content_surface": "feed_single",
                    "threadsdash_report": None,
                },
            ),
            (
                "live_acceptance_actuals",
                (),
                {
                    "account_target": 10,
                    "threadsdash_report": {},
                    "required_inventory": 30,
                    "available_inventory": 20,
                    "exception_count": 1,
                },
            ),
            ("live_acceptance_missed_dispatches", ({"missedDispatchCount": 1},), {}),
            ("live_acceptance_duplicate_publishes", ({"duplicatePublishes": 2},), {}),
            (
                "live_acceptance_restricted_scheduled",
                ({"restrictedAccountsScheduled": 3},),
                {},
            ),
            (
                "live_acceptance_surface_contract_violations",
                ({"surfaceContractViolations": 4},),
                {},
            ),
            ("live_acceptance_metrics_imported", (), {}),
            ("live_acceptance_blocker_for", ("metricsImported",), {}),
        ]
    finally:
        factory.close()


def test_campaign_factory_delegates_creator_os_certification_report_to_services() -> (
    None
):
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def creator_os_certification_report(self):
            calls.append(("creator_os_certification_report", (), {}))
            return {"schema": "creator_os.certification_report.v1"}

    factory.services = FakeServices()

    assert factory.creator_os_certification_report() == {
        "schema": "creator_os.certification_report.v1"
    }
    assert calls == [("creator_os_certification_report", (), {})]


def test_core_services_delegates_creator_os_certification_report_to_repository(
    tmp_path,
) -> None:
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
    calls = []

    try:

        class FakeCertification:
            conn = factory.conn

            def creator_os_certification_report(self):
                calls.append(("creator_os_certification_report", (), {}))
                return {"schema": "creator_os.certification_report.v1"}

        factory.services.certification = FakeCertification()

        assert factory.services.creator_os_certification_report() == {
            "schema": "creator_os.certification_report.v1"
        }
        assert calls == [("creator_os_certification_report", (), {})]
    finally:
        factory.close()


def test_campaign_factory_delegates_operational_proof_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def failure_injection_suite(self):
            calls.append(("failure_injection_suite", (), {}))
            return {"schema": "creator_os.failure_injection_suite.v1"}

        def idempotency_proof(self):
            calls.append(("idempotency_proof", (), {}))
            return {"schema": "creator_os.idempotency_proof.v1"}

        def surface_maturity_audit(self):
            calls.append(("surface_maturity_audit", (), {}))
            return {"schema": "creator_os.surface_maturity_audit.v1"}

        def operator_load_audit(self):
            calls.append(("operator_load_audit", (), {}))
            return {"schema": "creator_os.operator_load_audit.v1"}

        def idempotency_evidence_for_path(self, name):
            calls.append(("idempotency_evidence_for_path", (name,), {}))
            return f"evidence:{name}"

    factory.services = FakeServices()

    assert factory.failure_injection_suite() == {
        "schema": "creator_os.failure_injection_suite.v1"
    }
    assert factory.idempotency_proof() == {"schema": "creator_os.idempotency_proof.v1"}
    assert factory.surface_maturity_audit() == {
        "schema": "creator_os.surface_maturity_audit.v1"
    }
    assert factory.operator_load_audit() == {
        "schema": "creator_os.operator_load_audit.v1"
    }
    assert factory._idempotency_evidence_for_path("schedule") == "evidence:schedule"
    assert calls == [
        ("failure_injection_suite", (), {}),
        ("idempotency_proof", (), {}),
        ("surface_maturity_audit", (), {}),
        ("operator_load_audit", (), {}),
        ("idempotency_evidence_for_path", ("schedule",), {}),
    ]


def test_core_services_delegates_operational_proof_methods_to_repository(
    tmp_path,
) -> None:
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
    calls = []

    try:

        class FakeOperationalProofs:
            conn = factory.conn

            def failure_injection_suite(self):
                calls.append(("failure_injection_suite", (), {}))
                return {"schema": "creator_os.failure_injection_suite.v1"}

            def idempotency_proof(self):
                calls.append(("idempotency_proof", (), {}))
                return {"schema": "creator_os.idempotency_proof.v1"}

            def surface_maturity_audit(self):
                calls.append(("surface_maturity_audit", (), {}))
                return {"schema": "creator_os.surface_maturity_audit.v1"}

            def operator_load_audit(self):
                calls.append(("operator_load_audit", (), {}))
                return {"schema": "creator_os.operator_load_audit.v1"}

            def idempotency_evidence_for_path(self, name):
                calls.append(("idempotency_evidence_for_path", (name,), {}))
                return f"evidence:{name}"

        factory.services.operational_proofs = FakeOperationalProofs()

        assert factory.services.failure_injection_suite() == {
            "schema": "creator_os.failure_injection_suite.v1"
        }
        assert factory.services.idempotency_proof() == {
            "schema": "creator_os.idempotency_proof.v1"
        }
        assert factory.services.surface_maturity_audit() == {
            "schema": "creator_os.surface_maturity_audit.v1"
        }
        assert factory.services.operator_load_audit() == {
            "schema": "creator_os.operator_load_audit.v1"
        }
        assert (
            factory.services.idempotency_evidence_for_path("schedule")
            == "evidence:schedule"
        )
        assert calls == [
            ("failure_injection_suite", (), {}),
            ("idempotency_proof", (), {}),
            ("surface_maturity_audit", (), {}),
            ("operator_load_audit", (), {}),
            ("idempotency_evidence_for_path", ("schedule",), {}),
        ]
    finally:
        factory.close()


def test_campaign_factory_delegates_core_complexity_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def single_source_of_truth_audit(self):
            calls.append(("single_source_of_truth_audit", (), {}))
            return {"schema": "creator_os.single_source_of_truth_audit.v1"}

        def core_complexity_reduction_plan(self):
            calls.append(("core_complexity_reduction_plan", (), {}))
            return {"schema": "creator_os.core_complexity_reduction_plan.v1"}

        def largest_project_files(self):
            calls.append(("largest_project_files", (), {}))
            return [{"file": "campaign_factory/core.py", "lines": 1, "risk": "low"}]

    factory.services = FakeServices()

    assert factory.single_source_of_truth_audit() == {
        "schema": "creator_os.single_source_of_truth_audit.v1"
    }
    assert factory.core_complexity_reduction_plan() == {
        "schema": "creator_os.core_complexity_reduction_plan.v1"
    }
    assert factory._largest_project_files() == [
        {"file": "campaign_factory/core.py", "lines": 1, "risk": "low"}
    ]
    assert calls == [
        ("single_source_of_truth_audit", (), {}),
        ("core_complexity_reduction_plan", (), {}),
        ("largest_project_files", (), {}),
    ]


def test_core_services_delegates_core_complexity_methods_to_repository(
    tmp_path,
) -> None:
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
    calls = []

    try:

        class FakeCoreComplexity:
            conn = factory.conn

            def single_source_of_truth_audit(self):
                calls.append(("single_source_of_truth_audit", (), {}))
                return {"schema": "creator_os.single_source_of_truth_audit.v1"}

            def core_complexity_reduction_plan(self):
                calls.append(("core_complexity_reduction_plan", (), {}))
                return {"schema": "creator_os.core_complexity_reduction_plan.v1"}

            def largest_project_files(self):
                calls.append(("largest_project_files", (), {}))
                return [{"file": "campaign_factory/core.py", "lines": 1, "risk": "low"}]

        factory.services.core_complexity = FakeCoreComplexity()

        assert factory.services.single_source_of_truth_audit() == {
            "schema": "creator_os.single_source_of_truth_audit.v1"
        }
        assert factory.services.core_complexity_reduction_plan() == {
            "schema": "creator_os.core_complexity_reduction_plan.v1"
        }
        assert factory.services.largest_project_files() == [
            {"file": "campaign_factory/core.py", "lines": 1, "risk": "low"}
        ]
        assert calls == [
            ("single_source_of_truth_audit", (), {}),
            ("core_complexity_reduction_plan", (), {}),
            ("largest_project_files", (), {}),
        ]
    finally:
        factory.close()


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


def test_export_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def batch_summary(self, *args, **kwargs):
            calls.append(("batch_summary", args, kwargs))
            return {"schema": "campaign_factory.batch_summary.v1"}

        def daily_production_counters(self, *args, **kwargs):
            calls.append(("daily_production_counters", args, kwargs))
            return {"schema": "campaign_factory.daily_production_counters.v1"}

        def variant_pack_groups(self, *args, **kwargs):
            calls.append(("variant_pack_groups", args, kwargs))
            return [{"sourceAssetId": "asset_1"}]

        def export_manifest(self, *args, **kwargs):
            calls.append(("export_manifest", args, kwargs))
            return {"schema": "campaign_factory.export.v1"}

    factory.services = FakeServices()

    assert (
        factory.batch_summary("campaign")["schema"]
        == "campaign_factory.batch_summary.v1"
    )
    assert (
        factory.daily_production_counters("campaign", dashboard={"rendered": []})[
            "schema"
        ]
        == "campaign_factory.daily_production_counters.v1"
    )
    assert factory._variant_pack_groups([{"id": "asset_1"}]) == [
        {"sourceAssetId": "asset_1"}
    ]
    assert (
        factory.export_manifest(campaign_slug="campaign")["schema"]
        == "campaign_factory.export.v1"
    )
    assert calls == [
        ("batch_summary", ("campaign",), {}),
        ("daily_production_counters", ("campaign",), {"dashboard": {"rendered": []}}),
        ("variant_pack_groups", ([{"id": "asset_1"}],), {}),
        ("export_manifest", (), {"campaign_slug": "campaign"}),
    ]


def test_core_services_delegates_export_summary_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeExportSummary:
        def batch_summary(self, *args, **kwargs):
            calls.append(("batch_summary", args, kwargs))
            return {"schema": "campaign_factory.batch_summary.v1"}

        def daily_production_counters(self, *args, **kwargs):
            calls.append(("daily_production_counters", args, kwargs))
            return {"schema": "campaign_factory.daily_production_counters.v1"}

        def variant_pack_groups(self, *args, **kwargs):
            calls.append(("variant_pack_groups", args, kwargs))
            return [{"sourceAssetId": "asset_1"}]

        def export_manifest(self, *args, **kwargs):
            calls.append(("export_manifest", args, kwargs))
            return {"schema": "campaign_factory.export.v1"}

    services.export_summary = FakeExportSummary()

    assert (
        services.batch_summary("campaign")["schema"]
        == "campaign_factory.batch_summary.v1"
    )
    assert (
        services.daily_production_counters("campaign", dashboard={"rendered": []})[
            "schema"
        ]
        == "campaign_factory.daily_production_counters.v1"
    )
    assert services.variant_pack_groups([{"id": "asset_1"}]) == [
        {"sourceAssetId": "asset_1"}
    ]
    assert (
        services.export_manifest(campaign_slug="campaign")["schema"]
        == "campaign_factory.export.v1"
    )
    assert calls == [
        ("batch_summary", ("campaign",), {}),
        ("daily_production_counters", ("campaign",), {"dashboard": {"rendered": []}}),
        ("variant_pack_groups", ([{"id": "asset_1"}],), {}),
        ("export_manifest", (), {"campaign_slug": "campaign"}),
    ]


def test_campaign_factory_delegates_core_utility_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def campaign_dirs(self, *args, **kwargs):
            calls.append(("campaign_dirs", args, kwargs))
            return {"root": Path("/tmp/campaign")}

        def list_campaigns(self, *args, **kwargs):
            calls.append(("list_campaigns", args, kwargs))
            return [{"slug": "may"}]

        def rendered_for_campaign(self, *args, **kwargs):
            calls.append(("rendered_for_campaign", args, kwargs))
            return [{"id": "rendered_1"}]

        def ratio(self, *args, **kwargs):
            calls.append(("ratio", args, kwargs))
            return 0.5

        def score_fraction(self, *args, **kwargs):
            calls.append(("score_fraction", args, kwargs))
            return 5.0

        def road_to_accounts_payload(self, *args, **kwargs):
            calls.append(("road_to_accounts_payload", args, kwargs))
            return {"schema": "creator_os.road_to_25_accounts.v1"}

        def wilson_lower_bound(self, *args, **kwargs):
            calls.append(("wilson_lower_bound", args, kwargs))
            return 0.42

        def creator_label(self, *args, **kwargs):
            calls.append(("creator_label", args, kwargs))
            return "Stacey"

        def truthy(self, *args, **kwargs):
            calls.append(("truthy", args, kwargs))
            return True

        def surface_from_pattern(self, *args, **kwargs):
            calls.append(("surface_from_pattern", args, kwargs))
            return "story"

        def first_lineage_value(self, *args, **kwargs):
            calls.append(("first_lineage_value", args, kwargs))
            return "lineage_value"

        def audit_report(self, *args, **kwargs):
            calls.append(("audit_report", args, kwargs))
            return {"id": "audit_1"}

        def audit_report_payload(self, *args, **kwargs):
            calls.append(("audit_report_payload", args, kwargs))
            return {"id": "audit_2"}

    factory.services = FakeServices()

    assert factory.campaign_dirs("model-a", "may") == {"root": Path("/tmp/campaign")}
    assert factory.list_campaigns() == [{"slug": "may"}]
    assert factory.rendered_for_campaign("camp_1") == [{"id": "rendered_1"}]
    assert factory._ratio(1, 2) == 0.5
    assert factory._score_fraction(1, 2) == 5.0
    assert factory._road_to_accounts_payload(
        accounts=25, production={"postsPerDay": 8}
    ) == {
        "schema": "creator_os.road_to_25_accounts.v1",
    }
    assert factory._wilson_lower_bound(successes=4, trials=10, z=1.0) == 0.42
    assert factory._creator_label("stacey") == "Stacey"
    assert factory._truthy("yes") is True
    assert factory._surface_from_pattern({"dimension": "storyIntent"}, {}) == "story"
    assert (
        factory._first_lineage_value(
            {"keys": ["lineage_value"]}, "keys", fallback="fallback"
        )
        == "lineage_value"
    )
    assert factory.audit_report("audit_1") == {"id": "audit_1"}
    assert factory._audit_report_payload({"id": "audit_2"}) == {"id": "audit_2"}

    assert calls == [
        ("campaign_dirs", ("model-a", "may"), {}),
        ("list_campaigns", (), {}),
        ("rendered_for_campaign", ("camp_1",), {}),
        ("ratio", (1, 2), {}),
        ("score_fraction", (1, 2), {}),
        (
            "road_to_accounts_payload",
            (),
            {"accounts": 25, "production": {"postsPerDay": 8}},
        ),
        ("wilson_lower_bound", (), {"successes": 4, "trials": 10, "z": 1.0}),
        ("creator_label", ("stacey",), {}),
        ("truthy", ("yes",), {}),
        ("surface_from_pattern", ({"dimension": "storyIntent"}, {}), {}),
        (
            "first_lineage_value",
            ({"keys": ["lineage_value"]}, "keys"),
            {"fallback": "fallback"},
        ),
        ("audit_report", ("audit_1",), {}),
        ("audit_report_payload", ({"id": "audit_2"},), {}),
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


def test_operator_review_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def operator_inventory_review_batch_plan(self, *args, **kwargs):
            calls.append(("operator_inventory_review_batch_plan", args, kwargs))
            return {"schema": "creator_os.operator_inventory_review_batch_plan.v1"}

        def operator_inventory_review_batch_summary(self, *args, **kwargs):
            calls.append(("operator_inventory_review_batch_summary", args, kwargs))
            return {"schema": "creator_os.operator_inventory_review_batch_summary.v1"}

        def operator_review_simulator(self, *args, **kwargs):
            calls.append(("operator_review_simulator", args, kwargs))
            return {
                "schema": "creator_os.operator_review_simulator.v1",
                "reviewBatch": [],
            }

        def operator_review_scenarios(self, *args, **kwargs):
            calls.append(("operator_review_scenarios", args, kwargs))
            return {"schema": "creator_os.operator_review_scenarios.v1"}

        def operator_review_efficiency_report(self, *args, **kwargs):
            calls.append(("operator_review_efficiency_report", args, kwargs))
            return {"schema": "creator_os.operator_review_efficiency_report.v1"}

        def operator_review_minimum_certification_path(self, *args, **kwargs):
            calls.append(("operator_review_minimum_certification_path", args, kwargs))
            return {
                "schema": "creator_os.operator_review_minimum_certification_path.v1"
            }

        def operator_review_master_report(self, *args, **kwargs):
            calls.append(("operator_review_master_report", args, kwargs))
            return {"schema": "creator_os.operator_review_master_report.v1"}

        def operator_review_execution_order(self, *args, **kwargs):
            calls.append(("operator_review_execution_order", args, kwargs))
            return [{"assetId": "asset_1"}]

        def operator_review_batch_priority(self, *args, **kwargs):
            calls.append(("operator_review_batch_priority", args, kwargs))
            return 1

        def operator_review_batch_type(self, *args, **kwargs):
            calls.append(("operator_review_batch_type", args, kwargs))
            return "caption_only"

        def operator_review_scenario(self, *args, **kwargs):
            calls.append(("operator_review_scenario", args, kwargs))
            return {"approvalRate": kwargs["approval_rate"]}

        def operator_review_minimum_path(self, *args, **kwargs):
            calls.append(("operator_review_minimum_path", args, kwargs))
            return {"minimumAssetsReviewedToPass25Gate": 1}

        def operator_review_highest_roi_batch_type(self, *args, **kwargs):
            calls.append(("operator_review_highest_roi_batch_type", args, kwargs))
            return "caption_only"

        def operator_review_lowest_risk_batch_type(self, *args, **kwargs):
            calls.append(("operator_review_lowest_risk_batch_type", args, kwargs))
            return "caption_only"

        def operator_review_batch_order_labels(self, *args, **kwargs):
            calls.append(("operator_review_batch_order_labels", args, kwargs))
            return ["caption_only"]

        def operator_review_candidate_eligible(self, *args, **kwargs):
            calls.append(("operator_review_candidate_eligible", args, kwargs))
            return True

        def operator_review_candidate_row(self, *args, **kwargs):
            calls.append(("operator_review_candidate_row", args, kwargs))
            return {"assetId": args[0]["assetId"]}

        def operator_review_actions(self, *args, **kwargs):
            calls.append(("operator_review_actions", args, kwargs))
            return ["operator_visual_review"]

    factory.services = FakeServices()

    assert (
        factory.operator_inventory_review_batch_plan(creator="Test")["schema"]
        == "creator_os.operator_inventory_review_batch_plan.v1"
    )
    assert (
        factory.operator_inventory_review_batch_summary(creator="Test")["schema"]
        == "creator_os.operator_inventory_review_batch_summary.v1"
    )
    assert (
        factory.operator_review_simulator(creator="Test")["schema"]
        == "creator_os.operator_review_simulator.v1"
    )
    assert (
        factory.operator_review_scenarios(creator="Test")["schema"]
        == "creator_os.operator_review_scenarios.v1"
    )
    assert (
        factory.operator_review_efficiency_report(creator="Test")["schema"]
        == "creator_os.operator_review_efficiency_report.v1"
    )
    assert (
        factory.operator_review_minimum_certification_path(creator="Test")["schema"]
        == "creator_os.operator_review_minimum_certification_path.v1"
    )
    assert (
        factory.operator_review_master_report(creator="Test")["schema"]
        == "creator_os.operator_review_master_report.v1"
    )
    assert factory._operator_review_execution_order([{"assetId": "asset_1"}]) == [
        {"assetId": "asset_1"}
    ]
    assert factory._operator_review_batch_priority(["discoverability_failure"]) == 1
    assert (
        factory._operator_review_batch_type(["instagram_post_caption_quality_failed"])
        == "caption_only"
    )
    assert factory._operator_review_scenario(
        [], current_inventory=0, required_inventory=1, approval_rate=50
    ) == {"approvalRate": 50}
    assert factory._operator_review_minimum_path(
        [], current_inventory=0, required_inventory=1
    ) == {"minimumAssetsReviewedToPass25Gate": 1}
    assert factory._operator_review_highest_roi_batch_type([]) == "caption_only"
    assert factory._operator_review_lowest_risk_batch_type([]) == "caption_only"
    assert factory._operator_review_batch_order_labels([]) == ["caption_only"]
    assert factory._operator_review_candidate_eligible({"assetId": "asset_1"}) is True
    assert factory._operator_review_candidate_row({"assetId": "asset_1"}) == {
        "assetId": "asset_1"
    }
    assert factory._operator_review_actions(["operator_visual_review_required"]) == [
        "operator_visual_review"
    ]

    assert calls == [
        (
            "operator_inventory_review_batch_plan",
            (),
            {
                "creator": "Test",
                "campaign_slug": None,
                "content_surface": "reel",
                "required_inventory": 225,
                "current_inventory": None,
                "target_unlock": None,
                "max_batch_size": None,
            },
        ),
        ("operator_inventory_review_batch_summary", (), {"creator": "Test"}),
        (
            "operator_review_simulator",
            (),
            {
                "creator": "Test",
                "campaign_slug": None,
                "content_surface": "reel",
                "required_inventory": 225,
                "current_inventory": None,
                "approval_rates": None,
            },
        ),
        ("operator_review_scenarios", (), {"creator": "Test"}),
        ("operator_review_efficiency_report", (), {"creator": "Test"}),
        ("operator_review_minimum_certification_path", (), {"creator": "Test"}),
        ("operator_review_master_report", (), {"creator": "Test"}),
        ("operator_review_execution_order", ([{"assetId": "asset_1"}],), {}),
        ("operator_review_batch_priority", (["discoverability_failure"],), {}),
        (
            "operator_review_batch_type",
            (["instagram_post_caption_quality_failed"],),
            {},
        ),
        (
            "operator_review_scenario",
            ([],),
            {
                "current_inventory": 0,
                "required_inventory": 1,
                "approval_rate": 50,
            },
        ),
        (
            "operator_review_minimum_path",
            ([],),
            {"current_inventory": 0, "required_inventory": 1},
        ),
        ("operator_review_highest_roi_batch_type", ([],), {}),
        ("operator_review_lowest_risk_batch_type", ([],), {}),
        ("operator_review_batch_order_labels", ([],), {}),
        ("operator_review_candidate_eligible", ({"assetId": "asset_1"},), {}),
        ("operator_review_candidate_row", ({"assetId": "asset_1"},), {}),
        ("operator_review_actions", (["operator_visual_review_required"],), {}),
    ]


def test_core_services_delegates_operator_review_methods_to_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeOperatorReview:
        def operator_inventory_review_batch_plan(self, *args, **kwargs):
            calls.append(("operator_inventory_review_batch_plan", args, kwargs))
            return {"schema": "creator_os.operator_inventory_review_batch_plan.v1"}

        def operator_inventory_review_batch_summary(self, *args, **kwargs):
            calls.append(("operator_inventory_review_batch_summary", args, kwargs))
            return {"schema": "creator_os.operator_inventory_review_batch_summary.v1"}

        def operator_review_simulator(self, *args, **kwargs):
            calls.append(("operator_review_simulator", args, kwargs))
            return {"schema": "creator_os.operator_review_simulator.v1"}

        def operator_review_scenarios(self, *args, **kwargs):
            calls.append(("operator_review_scenarios", args, kwargs))
            return {"schema": "creator_os.operator_review_scenarios.v1"}

        def operator_review_efficiency_report(self, *args, **kwargs):
            calls.append(("operator_review_efficiency_report", args, kwargs))
            return {"schema": "creator_os.operator_review_efficiency_report.v1"}

        def operator_review_minimum_certification_path(self, *args, **kwargs):
            calls.append(("operator_review_minimum_certification_path", args, kwargs))
            return {
                "schema": "creator_os.operator_review_minimum_certification_path.v1"
            }

        def operator_review_master_report(self, *args, **kwargs):
            calls.append(("operator_review_master_report", args, kwargs))
            return {"schema": "creator_os.operator_review_master_report.v1"}

        def operator_review_execution_order(self, *args, **kwargs):
            calls.append(("operator_review_execution_order", args, kwargs))
            return []

        def operator_review_batch_priority(self, *args, **kwargs):
            calls.append(("operator_review_batch_priority", args, kwargs))
            return 1

        def operator_review_batch_type(self, *args, **kwargs):
            calls.append(("operator_review_batch_type", args, kwargs))
            return "caption_only"

        def operator_review_scenario(self, *args, **kwargs):
            calls.append(("operator_review_scenario", args, kwargs))
            return {"approvalRate": kwargs["approval_rate"]}

        def operator_review_minimum_path(self, *args, **kwargs):
            calls.append(("operator_review_minimum_path", args, kwargs))
            return {}

        def operator_review_highest_roi_batch_type(self, *args, **kwargs):
            calls.append(("operator_review_highest_roi_batch_type", args, kwargs))
            return "caption_only"

        def operator_review_lowest_risk_batch_type(self, *args, **kwargs):
            calls.append(("operator_review_lowest_risk_batch_type", args, kwargs))
            return "caption_only"

        def operator_review_batch_order_labels(self, *args, **kwargs):
            calls.append(("operator_review_batch_order_labels", args, kwargs))
            return ["caption_only"]

        def operator_review_candidate_eligible(self, *args, **kwargs):
            calls.append(("operator_review_candidate_eligible", args, kwargs))
            return True

        def operator_review_candidate_row(self, *args, **kwargs):
            calls.append(("operator_review_candidate_row", args, kwargs))
            return {"assetId": args[0]["assetId"]}

        def operator_review_actions(self, *args, **kwargs):
            calls.append(("operator_review_actions", args, kwargs))
            return ["operator_visual_review"]

    services.operator_review = FakeOperatorReview()

    assert (
        services.operator_inventory_review_batch_plan(creator="Test")["schema"]
        == "creator_os.operator_inventory_review_batch_plan.v1"
    )
    assert (
        services.operator_inventory_review_batch_summary(creator="Test")["schema"]
        == "creator_os.operator_inventory_review_batch_summary.v1"
    )
    assert (
        services.operator_review_simulator(creator="Test")["schema"]
        == "creator_os.operator_review_simulator.v1"
    )
    assert (
        services.operator_review_scenarios(creator="Test")["schema"]
        == "creator_os.operator_review_scenarios.v1"
    )
    assert (
        services.operator_review_efficiency_report(creator="Test")["schema"]
        == "creator_os.operator_review_efficiency_report.v1"
    )
    assert (
        services.operator_review_minimum_certification_path(creator="Test")["schema"]
        == "creator_os.operator_review_minimum_certification_path.v1"
    )
    assert (
        services.operator_review_master_report(creator="Test")["schema"]
        == "creator_os.operator_review_master_report.v1"
    )
    assert services.operator_review_execution_order([]) == []
    assert services.operator_review_batch_priority(["discoverability_failure"]) == 1
    assert (
        services.operator_review_batch_type(["instagram_post_caption_quality_failed"])
        == "caption_only"
    )
    assert services.operator_review_scenario(
        [], current_inventory=0, required_inventory=1, approval_rate=75
    ) == {"approvalRate": 75}
    assert (
        services.operator_review_minimum_path(
            [], current_inventory=0, required_inventory=1
        )
        == {}
    )
    assert services.operator_review_highest_roi_batch_type([]) == "caption_only"
    assert services.operator_review_lowest_risk_batch_type([]) == "caption_only"
    assert services.operator_review_batch_order_labels([]) == ["caption_only"]
    assert services.operator_review_candidate_eligible({"assetId": "asset_1"}) is True
    assert services.operator_review_candidate_row({"assetId": "asset_1"}) == {
        "assetId": "asset_1"
    }
    assert services.operator_review_actions(["operator_visual_review_required"]) == [
        "operator_visual_review"
    ]

    assert calls == [
        ("operator_inventory_review_batch_plan", (), {"creator": "Test"}),
        ("operator_inventory_review_batch_summary", (), {"creator": "Test"}),
        ("operator_review_simulator", (), {"creator": "Test"}),
        ("operator_review_scenarios", (), {"creator": "Test"}),
        ("operator_review_efficiency_report", (), {"creator": "Test"}),
        ("operator_review_minimum_certification_path", (), {"creator": "Test"}),
        ("operator_review_master_report", (), {"creator": "Test"}),
        ("operator_review_execution_order", ([],), {}),
        ("operator_review_batch_priority", (["discoverability_failure"],), {}),
        (
            "operator_review_batch_type",
            (["instagram_post_caption_quality_failed"],),
            {},
        ),
        (
            "operator_review_scenario",
            ([],),
            {
                "current_inventory": 0,
                "required_inventory": 1,
                "approval_rate": 75,
            },
        ),
        (
            "operator_review_minimum_path",
            ([],),
            {"current_inventory": 0, "required_inventory": 1},
        ),
        ("operator_review_highest_roi_batch_type", ([],), {}),
        ("operator_review_lowest_risk_batch_type", ([],), {}),
        ("operator_review_batch_order_labels", ([],), {}),
        ("operator_review_candidate_eligible", ({"assetId": "asset_1"},), {}),
        ("operator_review_candidate_row", ({"assetId": "asset_1"},), {}),
        ("operator_review_actions", (["operator_visual_review_required"],), {}),
    ]


def test_story_management_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def story_inventory_report(self, *args, **kwargs):
            calls.append(("story_inventory_report", args, kwargs))
            return {"schema": "campaign_factory.story_inventory_report.v1"}

        def story_intent_report(self, *args, **kwargs):
            calls.append(("story_intent_report", args, kwargs))
            return {"schema": "campaign_factory.story_intent_report.v1"}

        def story_mix_plan(self, *args, **kwargs):
            calls.append(("story_mix_plan", args, kwargs))
            return {"schema": "campaign_factory.story_mix_plan.v1"}

        def story_calendar_plan(self, *args, **kwargs):
            calls.append(("story_calendar_plan", args, kwargs))
            return {"schema": "campaign_factory.story_calendar_plan.v1"}

        def story_intent_summary(self, *args, **kwargs):
            calls.append(("story_intent_summary", args, kwargs))
            return {"schema": "campaign_factory.story_intent_summary.v1"}

        def story_metadata_payload(self, *args, **kwargs):
            calls.append(("story_metadata_payload", args, kwargs))
            return {"storyIntent": "reel_teaser"}

        def story_intent_value(self, *args, **kwargs):
            calls.append(("story_intent_value", args, kwargs))
            return "reel_teaser"

        def story_goal_value(self, *args, **kwargs):
            calls.append(("story_goal_value", args, kwargs))
            return "reel_support"

        def story_style_value(self, *args, **kwargs):
            calls.append(("story_style_value", args, kwargs))
            return "raw_phone"

        def normalize_story_enum(self, *args, **kwargs):
            calls.append(("normalize_story_enum", args, kwargs))
            return "reel_teaser"

        def story_quality_gate_v1(self, *args, **kwargs):
            calls.append(("story_quality_gate_v1", args, kwargs))
            return {"schema": "campaign_factory.story_quality_gate_v1"}

        def story_quality_report(self, *args, **kwargs):
            calls.append(("story_quality_report", args, kwargs))
            return {"schema": "campaign_factory.story_quality_report.v1"}

        def story_quality_gate_for_asset(self, *args, **kwargs):
            calls.append(("story_quality_gate_for_asset", args, kwargs))
            return {"storyQualityGatePassed": True}

        def story_quality_metadata(self, *args, **kwargs):
            calls.append(("story_quality_metadata", args, kwargs))
            return {"storySafeZoneScore": 100}

        def bounded_score(self, *args, **kwargs):
            calls.append(("bounded_score", args, kwargs))
            return 95

        def story_black_bar_check(self, *args, **kwargs):
            calls.append(("story_black_bar_check", args, kwargs))
            return {"blackBarsDetected": False}

        def story_no_text_check(self, *args, **kwargs):
            calls.append(("story_no_text_check", args, kwargs))
            return {"required": False, "passed": True}

        def story_ocr_frame_paths(self, *args, **kwargs):
            calls.append(("story_ocr_frame_paths", args, kwargs))
            return [Path("/tmp/frame.png")]

        def story_ocr_detect_text(self, *args, **kwargs):
            calls.append(("story_ocr_detect_text", args, kwargs))
            return []

        def pixel_region_black(self, *args, **kwargs):
            calls.append(("pixel_region_black", args, kwargs))
            return False

        def story_gap_report(self, *args, **kwargs):
            calls.append(("story_gap_report", args, kwargs))
            return {"schema": "campaign_factory.story_gap_report.v1"}

        def account_story_status(self, *args, **kwargs):
            calls.append(("account_story_status", args, kwargs))
            return {"schema": "campaign_factory.account_story_status.v1"}

        def creator_story_summary(self, *args, **kwargs):
            calls.append(("creator_story_summary", args, kwargs))
            return {"schema": "campaign_factory.creator_story_summary.v1"}

        def story_certification_proof(self, *args, **kwargs):
            calls.append(("story_certification_proof", args, kwargs))
            return {"schema": "creator_os.story_certification_proof.v1"}

        def story_production_readiness(self, *args, **kwargs):
            calls.append(("story_production_readiness", args, kwargs))
            return {"schema": "creator_os.story_production_readiness.v1"}

        def story_proof_gap_analysis(self, *args, **kwargs):
            calls.append(("story_proof_gap_analysis", args, kwargs))
            return {"schema": "creator_os.story_proof_gap_analysis.v1"}

        def story_source_blockers(self, *args, **kwargs):
            calls.append(("story_source_blockers", args, kwargs))
            return ["story_source_must_be_raw_not_rendered_reel_asset"]

        def story_existing_asset_source_blockers(self, *args, **kwargs):
            calls.append(("story_existing_asset_source_blockers", args, kwargs))
            return ["story_source_must_be_raw_not_approved_reel_asset"]

    factory.services = FakeServices()

    assert (
        factory.story_inventory_report(creator="Stacey")["schema"]
        == "campaign_factory.story_inventory_report.v1"
    )
    assert (
        factory.story_intent_report(creator="Stacey")["schema"]
        == "campaign_factory.story_intent_report.v1"
    )
    assert (
        factory.story_mix_plan(creator="Stacey")["schema"]
        == "campaign_factory.story_mix_plan.v1"
    )
    assert (
        factory.story_calendar_plan(creator="Stacey")["schema"]
        == "campaign_factory.story_calendar_plan.v1"
    )
    assert (
        factory.story_intent_summary(creator="Stacey")["schema"]
        == "campaign_factory.story_intent_summary.v1"
    )
    assert factory._story_metadata_payload({"id": "asset_1"}) == {
        "storyIntent": "reel_teaser"
    }
    assert factory._story_intent_value({"id": "asset_1"}) == "reel_teaser"
    assert factory._story_goal_value({"id": "asset_1"}) == "reel_support"
    assert factory._story_style_value({"id": "asset_1"}) == "raw_phone"
    assert (
        factory._normalize_story_enum("Reel Teaser", {"reel_teaser"}) == "reel_teaser"
    )
    assert (
        factory.story_quality_gate_v1("asset_1")["schema"]
        == "campaign_factory.story_quality_gate_v1"
    )
    assert (
        factory.story_quality_report(creator="Stacey")["schema"]
        == "campaign_factory.story_quality_report.v1"
    )
    assert factory._story_quality_gate_for_asset({"id": "asset_1"}) == {
        "storyQualityGatePassed": True
    }
    assert factory._story_quality_metadata({"id": "asset_1"}) == {
        "storySafeZoneScore": 100
    }
    assert factory._bounded_score("95", default=100) == 95
    assert factory._story_black_bar_check(
        Path("/tmp/story.png"), media_type="image"
    ) == {"blackBarsDetected": False}
    assert factory._story_no_text_check(
        Path("/tmp/story.png"), media_type="image", quality={}
    ) == {"required": False, "passed": True}
    assert factory._story_ocr_frame_paths(
        Path("/tmp/story.mp4"), media_type="video"
    ) == [Path("/tmp/frame.png")]
    assert factory._story_ocr_detect_text(Path("/tmp/frame.png"), frame_index=0) == []
    assert factory._pixel_region_black([], x0=0, x1=1, y0=0, y1=1) is False
    assert (
        factory.story_gap_report(creator="Stacey", date="2026-06-06")["schema"]
        == "campaign_factory.story_gap_report.v1"
    )
    assert (
        factory.account_story_status(
            account_id="acct_1", creator="Stacey", date="2026-06-06"
        )["schema"]
        == "campaign_factory.account_story_status.v1"
    )
    assert (
        factory.creator_story_summary(creator="Stacey", date="2026-06-06")["schema"]
        == "campaign_factory.creator_story_summary.v1"
    )
    assert (
        factory.story_certification_proof(rendered_asset_id="asset_1")["schema"]
        == "creator_os.story_certification_proof.v1"
    )
    assert (
        factory.story_production_readiness()["schema"]
        == "creator_os.story_production_readiness.v1"
    )
    assert (
        factory.story_proof_gap_analysis()["schema"]
        == "creator_os.story_proof_gap_analysis.v1"
    )
    assert factory._story_source_blockers(
        [{"path": "/campaign_factory/02_rendered/story.png"}]
    ) == ["story_source_must_be_raw_not_rendered_reel_asset"]
    assert factory._story_existing_asset_source_blockers({"id": "asset_1"}) == [
        "story_source_must_be_raw_not_approved_reel_asset"
    ]

    assert calls == [
        ("story_inventory_report", (), {"creator": "Stacey", "campaign_slug": None}),
        ("story_intent_report", (), {"creator": "Stacey", "campaign_slug": None}),
        ("story_mix_plan", (), {"creator": "Stacey"}),
        ("story_calendar_plan", (), {"creator": "Stacey"}),
        ("story_intent_summary", (), {"creator": "Stacey", "campaign_slug": None}),
        ("story_metadata_payload", ({"id": "asset_1"},), {}),
        ("story_intent_value", ({"id": "asset_1"},), {}),
        ("story_goal_value", ({"id": "asset_1"},), {}),
        ("story_style_value", ({"id": "asset_1"},), {}),
        ("normalize_story_enum", ("Reel Teaser", {"reel_teaser"}), {}),
        ("story_quality_gate_v1", ("asset_1",), {}),
        ("story_quality_report", (), {"creator": "Stacey", "campaign_slug": None}),
        ("story_quality_gate_for_asset", ({"id": "asset_1"},), {}),
        ("story_quality_metadata", ({"id": "asset_1"},), {}),
        ("bounded_score", ("95",), {"default": 100}),
        ("story_black_bar_check", (Path("/tmp/story.png"),), {"media_type": "image"}),
        (
            "story_no_text_check",
            (Path("/tmp/story.png"),),
            {"media_type": "image", "quality": {}},
        ),
        ("story_ocr_frame_paths", (Path("/tmp/story.mp4"),), {"media_type": "video"}),
        ("story_ocr_detect_text", (Path("/tmp/frame.png"),), {"frame_index": 0}),
        ("pixel_region_black", ([],), {"x0": 0, "x1": 1, "y0": 0, "y1": 1}),
        ("story_gap_report", (), {"creator": "Stacey", "date": "2026-06-06"}),
        (
            "account_story_status",
            (),
            {"account_id": "acct_1", "creator": "Stacey", "date": "2026-06-06"},
        ),
        ("creator_story_summary", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("story_certification_proof", (), {"rendered_asset_id": "asset_1"}),
        ("story_production_readiness", (), {}),
        ("story_proof_gap_analysis", (), {}),
        (
            "story_source_blockers",
            ([{"path": "/campaign_factory/02_rendered/story.png"}],),
            {},
        ),
        ("story_existing_asset_source_blockers", ({"id": "asset_1"},), {}),
    ]


def test_campaign_factory_delegates_creator_os_draft_helpers_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def creator_os_local_schedule_safe_assets(self, *args, **kwargs):
            calls.append(("creator_os_local_schedule_safe_assets", args, kwargs))
            return [{"renderedAssetId": "asset_1"}]

        def creator_os_target_date(self, *args, **kwargs):
            calls.append(("creator_os_target_date", args, kwargs))
            return "2026-06-06"

        def creator_os_account_surface_status(self, *args, **kwargs):
            calls.append(("creator_os_account_surface_status", args, kwargs))
            return {"reel": {"needed": True}}

        def creator_os_surface_summary_for_creator(self, *args, **kwargs):
            calls.append(("creator_os_surface_summary_for_creator", args, kwargs))
            return {"accountsNeedingReels": 1, "wouldWrite": False}

        def creator_os_gap_blocking_reason(self, *args, **kwargs):
            calls.append(("creator_os_gap_blocking_reason", args, kwargs))
            return "missing_handoff_manifest"

        def creator_os_draft_items(self, *args, **kwargs):
            calls.append(("creator_os_draft_items", args, kwargs))
            return [{"postId": "post_1"}]

        def creator_os_draft_has_instagram_post_caption(self, *args, **kwargs):
            calls.append(("creator_os_draft_has_instagram_post_caption", args, kwargs))
            return True

        def creator_os_draft_exclusion_reason(self, *args, **kwargs):
            calls.append(("creator_os_draft_exclusion_reason", args, kwargs))
            return ""

        def creator_os_draft_exclusion_counts(self, *args, **kwargs):
            calls.append(("creator_os_draft_exclusion_counts", args, kwargs))
            return {"missingInstagramPostCaption": 1}

        def creator_os_schedule_safe_drafts(self, *args, **kwargs):
            calls.append(("creator_os_schedule_safe_drafts", args, kwargs))
            return [{"postId": "post_1"}]

        def creator_os_execution_draft_blockers(self, *args, **kwargs):
            calls.append(("creator_os_execution_draft_blockers", args, kwargs))
            return ["missing_campaign_factory_asset_id"]

        def creator_os_explicit_false(self, *args, **kwargs):
            calls.append(("creator_os_explicit_false", args, kwargs))
            return True

        def creator_os_inventory_for_creator(self, *args, **kwargs):
            calls.append(("creator_os_inventory_for_creator", args, kwargs))
            return {"validatedDraftsAvailable": 1, "variantDraftsAvailable": 1}

        def creator_os_blocked_account_breakdown(self, *args, **kwargs):
            calls.append(("creator_os_blocked_account_breakdown", args, kwargs))
            return {"restricted": 1}

        def creator_os_manager_decision(self, *args, **kwargs):
            calls.append(("creator_os_manager_decision", args, kwargs))
            return {"managerDecision": "ready_to_schedule", "managerReason": "ready"}

        def creator_os_account_state(self, *args, **kwargs):
            calls.append(("creator_os_account_state", args, kwargs))
            return "safe"

        def creator_os_post_time(self, *args, **kwargs):
            calls.append(("creator_os_post_time", args, kwargs))
            return "2026-06-06T12:00:00Z"

        def creator_os_recommended_post_count(self, *args, **kwargs):
            calls.append(("creator_os_recommended_post_count", args, kwargs))
            return 1

        def recommended_story_intent_for_date(self, *args, **kwargs):
            calls.append(("recommended_story_intent_for_date", args, kwargs))
            return "reel_teaser"

        def recommended_story_style_for_intent(self, *args, **kwargs):
            calls.append(("recommended_story_style_for_intent", args, kwargs))
            return "raw_phone"

    factory.services = FakeServices()

    draft = {"postId": "post_1"}
    planner_inputs = [{"items": [draft]}]
    assert factory._creator_os_local_schedule_safe_assets("Stacey") == [
        {"renderedAssetId": "asset_1"}
    ]
    assert factory._creator_os_target_date(date="2026-06-06T12:00:00Z") == "2026-06-06"
    assert factory._creator_os_account_surface_status(
        {"surfaceStatus": {}}, reel_needed=True
    ) == {"reel": {"needed": True}}
    assert factory._creator_os_surface_summary_for_creator(
        creator="Stacey",
        date="2026-06-06",
        report={},
        creator_accounts=[],
        draft_items=[draft],
    ) == {"accountsNeedingReels": 1, "wouldWrite": False}
    assert (
        factory._creator_os_gap_blocking_reason("missingHandoffManifest", [], draft)
        == "missing_handoff_manifest"
    )
    assert factory._creator_os_draft_items(planner_inputs) == [{"postId": "post_1"}]
    assert factory._creator_os_draft_has_instagram_post_caption(draft) is True
    assert factory._creator_os_draft_exclusion_reason(draft) == ""
    assert factory._creator_os_draft_exclusion_counts("Stacey", [draft]) == {
        "missingInstagramPostCaption": 1
    }
    assert factory._creator_os_schedule_safe_drafts("Stacey", [draft]) == [
        {"postId": "post_1"}
    ]
    assert factory._creator_os_execution_draft_blockers("Stacey", [draft]) == [
        "missing_campaign_factory_asset_id"
    ]
    assert factory._creator_os_explicit_false(draft, "burnedCaptionTextPresent") is True
    assert factory._creator_os_inventory_for_creator(
        "Stacey", planner_inputs, [draft]
    ) == {
        "validatedDraftsAvailable": 1,
        "variantDraftsAvailable": 1,
    }
    assert factory._creator_os_blocked_account_breakdown(
        [{"blockedReason": "restricted"}]
    ) == {"restricted": 1}
    assert factory._creator_os_manager_decision(
        safe_accounts=1,
        needs_posts=1,
        validated_available=1,
        shortfall=0,
        missed_dispatches=[],
        winner_recommendations=[],
    ) == {"managerDecision": "ready_to_schedule", "managerReason": "ready"}
    assert (
        factory._creator_os_account_state({"bucket": "safe_to_schedule_today"}, "")
        == "safe"
    )
    assert (
        factory._creator_os_post_time({"scheduledFor": "2026-06-06T12:00:00Z"})
        == "2026-06-06T12:00:00Z"
    )
    assert factory._creator_os_recommended_post_count("safe", True) == 1
    assert (
        factory._recommended_story_intent_for_date("2026-06-06", creator="Stacey")
        == "reel_teaser"
    )
    assert factory._recommended_story_style_for_intent("reel_teaser") == "raw_phone"

    assert calls == [
        ("creator_os_local_schedule_safe_assets", ("Stacey",), {}),
        (
            "creator_os_target_date",
            (),
            {"date": "2026-06-06T12:00:00Z", "generated_at": None},
        ),
        (
            "creator_os_account_surface_status",
            ({"surfaceStatus": {}},),
            {"reel_needed": True},
        ),
        (
            "creator_os_surface_summary_for_creator",
            (),
            {
                "creator": "Stacey",
                "date": "2026-06-06",
                "report": {},
                "creator_accounts": [],
                "draft_items": [draft],
            },
        ),
        ("creator_os_gap_blocking_reason", ("missingHandoffManifest", [], draft), {}),
        ("creator_os_draft_items", (planner_inputs,), {}),
        ("creator_os_draft_has_instagram_post_caption", (draft,), {}),
        ("creator_os_draft_exclusion_reason", (draft,), {}),
        ("creator_os_draft_exclusion_counts", ("Stacey", [draft]), {}),
        ("creator_os_schedule_safe_drafts", ("Stacey", [draft]), {}),
        ("creator_os_execution_draft_blockers", ("Stacey", [draft]), {}),
        ("creator_os_explicit_false", (draft, "burnedCaptionTextPresent"), {}),
        ("creator_os_inventory_for_creator", ("Stacey", planner_inputs, [draft]), {}),
        (
            "creator_os_blocked_account_breakdown",
            ([{"blockedReason": "restricted"}],),
            {},
        ),
        (
            "creator_os_manager_decision",
            (),
            {
                "safe_accounts": 1,
                "needs_posts": 1,
                "validated_available": 1,
                "shortfall": 0,
                "missed_dispatches": [],
                "winner_recommendations": [],
            },
        ),
        ("creator_os_account_state", ({"bucket": "safe_to_schedule_today"}, ""), {}),
        ("creator_os_post_time", ({"scheduledFor": "2026-06-06T12:00:00Z"},), {}),
        ("creator_os_recommended_post_count", ("safe", True), {}),
        ("recommended_story_intent_for_date", ("2026-06-06",), {"creator": "Stacey"}),
        ("recommended_story_style_for_intent", ("reel_teaser",), {}),
    ]


def test_account_health_facade_delegates_to_core_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def creator_os_account_tiers(self, *args, **kwargs):
            calls.append(("creator_os_account_tiers", args, kwargs))
            return {"schema": "creator_os.account_tiers.v1"}

        def creator_os_account_health_report(self, *args, **kwargs):
            calls.append(("creator_os_account_health_report", args, kwargs))
            return {"schema": "creator_os.account_health_report.v1"}

        def creator_os_restricted_account_report(self, *args, **kwargs):
            calls.append(("creator_os_restricted_account_report", args, kwargs))
            return {"schema": "creator_os.restricted_account_report.v1"}

        def creator_os_manual_review_queue(self, *args, **kwargs):
            calls.append(("creator_os_manual_review_queue", args, kwargs))
            return {"schema": "creator_os.manual_review_queue.v1"}

        def creator_os_account_warmup_report(self, *args, **kwargs):
            calls.append(("creator_os_account_warmup_report", args, kwargs))
            return {"schema": "creator_os.account_warmup_report.v1"}

        def creator_os_execution_account_health_blockers(self, *args, **kwargs):
            calls.append(("creator_os_execution_account_health_blockers", args, kwargs))
            return ["account_link_sharing_restricted"]

        def creator_os_execution_account_health_warnings(self, *args, **kwargs):
            calls.append(("creator_os_execution_account_health_warnings", args, kwargs))
            return ["recommendation_eligibility_unknown_conservative_cadence"]

        def creator_os_account_tier_summary(self, *args, **kwargs):
            calls.append(("creator_os_account_tier_summary", args, kwargs))
            return {
                "warming": 1,
                "normal": 0,
                "growth": 0,
                "winner": 0,
                "resting": 0,
                "blocked": 0,
            }

        def creator_os_account_health_decision(self, *args, **kwargs):
            calls.append(("creator_os_account_health_decision", args, kwargs))
            return {"accountId": args[0]["accountId"], "safeToSchedule": False}

        def creator_os_account_health_summary(self, *args, **kwargs):
            calls.append(("creator_os_account_health_summary", args, kwargs))
            return {"accounts": 1}

        def creator_os_recommendation_eligibility(self, *args, **kwargs):
            calls.append(("creator_os_recommendation_eligibility", args, kwargs))
            return "eligible"

        def creator_os_restriction_status(self, *args, **kwargs):
            calls.append(("creator_os_restriction_status", args, kwargs))
            return {"active": False}

        def creator_os_maturity_score(self, *args, **kwargs):
            calls.append(("creator_os_maturity_score", args, kwargs))
            return 60

        def creator_os_warming_stage(self, *args, **kwargs):
            calls.append(("creator_os_warming_stage", args, kwargs))
            return "mature"

        def creator_os_creative_risk(self, *args, **kwargs):
            calls.append(("creator_os_creative_risk", args, kwargs))
            return {"creativeRiskScore": 0}

        def creator_os_similarity_budget(self, *args, **kwargs):
            calls.append(("creator_os_similarity_budget", args, kwargs))
            return {"blocked": False}

        def creator_os_account_tier_from_health(self, *args, **kwargs):
            calls.append(("creator_os_account_tier_from_health", args, kwargs))
            return "normal"

        def creator_os_cadence_overrides(self, *args, **kwargs):
            calls.append(("creator_os_cadence_overrides", args, kwargs))
            return {"maxPostsPerDay": 1}

        def creator_os_account_over_cadence(self, *args, **kwargs):
            calls.append(("creator_os_account_over_cadence", args, kwargs))
            return False

        def creator_os_account_tier(self, *args, **kwargs):
            calls.append(("creator_os_account_tier", args, kwargs))
            return "normal"

        def creator_os_numeric(self, *args, **kwargs):
            calls.append(("creator_os_numeric", args, kwargs))
            return 3.0

        def creator_os_tier_posting_guidance(self, *args, **kwargs):
            calls.append(("creator_os_tier_posting_guidance", args, kwargs))
            return {"recommendedPostCount": 1}

    factory.services = FakeServices()

    assert (
        factory.creator_os_account_tiers(creator="Stacey")["schema"]
        == "creator_os.account_tiers.v1"
    )
    assert (
        factory.creator_os_account_health_report(creator="Stacey")["schema"]
        == "creator_os.account_health_report.v1"
    )
    assert (
        factory.creator_os_restricted_account_report(creator="Stacey")["schema"]
        == "creator_os.restricted_account_report.v1"
    )
    assert (
        factory.creator_os_manual_review_queue(creator="Stacey")["schema"]
        == "creator_os.manual_review_queue.v1"
    )
    assert (
        factory.creator_os_account_warmup_report(creator="Stacey")["schema"]
        == "creator_os.account_warmup_report.v1"
    )
    assert factory._creator_os_execution_account_health_blockers({"accounts": []}) == [
        "account_link_sharing_restricted"
    ]
    assert factory._creator_os_execution_account_health_warnings({"accounts": []}) == [
        "recommendation_eligibility_unknown_conservative_cadence"
    ]
    assert (
        factory._creator_os_account_tier_summary([{"accountTier": "warming"}])[
            "warming"
        ]
        == 1
    )
    assert factory._creator_os_account_health_decision(
        {"accountId": "ig_1"}, missed=[]
    ) == {"accountId": "ig_1", "safeToSchedule": False}
    assert factory._creator_os_account_health_summary([{"safeToSchedule": False}]) == {
        "accounts": 1
    }
    assert (
        factory._creator_os_recommendation_eligibility({"recommendationEligible": True})
        == "eligible"
    )
    assert factory._creator_os_restriction_status({}) == {"active": False}
    assert factory._creator_os_maturity_score({"accountAgeDays": 30}) == 60
    assert factory._creator_os_warming_stage({}, maturity_score=60) == "mature"
    assert factory._creator_os_creative_risk({}) == {"creativeRiskScore": 0}
    assert factory._creator_os_similarity_budget({}) == {"blocked": False}
    assert (
        factory._creator_os_account_tier_from_health(
            {}, trust_state="normal", maturity_score=60
        )
        == "normal"
    )
    assert factory._creator_os_cadence_overrides(
        {}, warming_stage="mature", maturity_score=60
    ) == {"maxPostsPerDay": 1}
    assert factory._creator_os_account_over_cadence({}, {"maxPostsPerDay": 1}) is False
    assert (
        factory._creator_os_account_tier({}, state="safe", blocked_reason="")
        == "normal"
    )
    assert factory._creator_os_numeric("3") == 3.0
    assert factory._creator_os_tier_posting_guidance("normal") == {
        "recommendedPostCount": 1
    }

    assert calls == [
        (
            "creator_os_account_tiers",
            (),
            {"creator": "Stacey", "threadsdash_report": None, "generated_at": None},
        ),
        (
            "creator_os_account_health_report",
            (),
            {"creator": "Stacey", "threadsdash_report": None, "generated_at": None},
        ),
        (
            "creator_os_restricted_account_report",
            (),
            {"creator": "Stacey", "threadsdash_report": None, "generated_at": None},
        ),
        (
            "creator_os_manual_review_queue",
            (),
            {"creator": "Stacey", "threadsdash_report": None, "generated_at": None},
        ),
        (
            "creator_os_account_warmup_report",
            (),
            {"creator": "Stacey", "threadsdash_report": None, "generated_at": None},
        ),
        ("creator_os_execution_account_health_blockers", ({"accounts": []},), {}),
        ("creator_os_execution_account_health_warnings", ({"accounts": []},), {}),
        (
            "creator_os_account_tier_summary",
            ([{"accountTier": "warming"}],),
            {"key": "accountTier"},
        ),
        (
            "creator_os_account_health_decision",
            ({"accountId": "ig_1"},),
            {"missed": []},
        ),
        ("creator_os_account_health_summary", ([{"safeToSchedule": False}],), {}),
        (
            "creator_os_recommendation_eligibility",
            ({"recommendationEligible": True},),
            {},
        ),
        ("creator_os_restriction_status", ({},), {}),
        ("creator_os_maturity_score", ({"accountAgeDays": 30},), {}),
        ("creator_os_warming_stage", ({},), {"maturity_score": 60}),
        ("creator_os_creative_risk", ({},), {}),
        ("creator_os_similarity_budget", ({},), {}),
        (
            "creator_os_account_tier_from_health",
            ({},),
            {"trust_state": "normal", "maturity_score": 60},
        ),
        (
            "creator_os_cadence_overrides",
            ({},),
            {"warming_stage": "mature", "maturity_score": 60},
        ),
        ("creator_os_account_over_cadence", ({}, {"maxPostsPerDay": 1}), {}),
        ("creator_os_account_tier", ({},), {"state": "safe", "blocked_reason": ""}),
        ("creator_os_numeric", ("3",), {}),
        ("creator_os_tier_posting_guidance", ("normal",), {}),
    ]
