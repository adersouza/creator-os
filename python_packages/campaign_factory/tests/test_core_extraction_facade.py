from __future__ import annotations

from pathlib import Path

from campaign_factory import audit_payload, exports
from campaign_factory.acceptance_suite import AcceptanceSuiteRepository
from campaign_factory.account_health import AccountHealthRepository
from campaign_factory.account_memory import AccountMemoryRepository
from campaign_factory.asset_import import AssetImportRepository
from campaign_factory.autonomy import AutonomyPolicyRepository
from campaign_factory.caption import CaptionFamilyRepository
from campaign_factory.carousel_integrity import CarouselIntegrityRepository
from campaign_factory.campaign_overview import CampaignOverviewRepository
from campaign_factory.certification import CertificationRepository
from campaign_factory.config import Settings
from campaign_factory.core import CampaignFactory
from campaign_factory.core_complexity import CoreComplexityRepository
from campaign_factory.creative_knowledge import CreativeKnowledgeRepository
from campaign_factory.creative_planning import CreativePlanningRepository
from campaign_factory.decision_ledger import DecisionLedgerRepository
from campaign_factory.discoverability import DiscoverabilityRepository
from campaign_factory.distribution import DistributionRepository
from campaign_factory.daily_plan import DailyPlanRepository
from campaign_factory.draft_inventory_gap import DraftInventoryGapRepository
from campaign_factory.events import EventRepository
from campaign_factory.execution_readiness import ExecutionReadinessRepository
from campaign_factory.exceptions import ExceptionRepository
from campaign_factory.graph import GraphRepository
from campaign_factory.live_acceptance import LiveAcceptanceRepository
from campaign_factory.live_scale import LiveScaleRepository
from campaign_factory.models import ModelRepository
from campaign_factory.operational_proofs import OperationalProofRepository
from campaign_factory.operator_review import OperatorReviewRepository
from campaign_factory.reference import ReferenceRepository
from campaign_factory.recommendation_accuracy import RecommendationAccuracyRepository
from campaign_factory.readiness_report import ReadinessReportRepository
from campaign_factory.services import CoreServices
from campaign_factory.story_management import StoryManagementRepository
from campaign_factory.surface_handoff import SurfaceHandoffRepository
from campaign_factory.surface_inventory import SurfaceInventoryRepository
from campaign_factory.surface_requirements import SurfaceRequirementsRepository
from campaign_factory.surface_summary import SurfaceSummaryRepository
from campaign_factory.surface_registration import SurfaceRegistrationRepository
from campaign_factory.tribev2 import TribeV2Repository
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
        assert isinstance(factory.services.tribev2, TribeV2Repository)
        assert factory.services.tribev2.conn is factory.conn
        assert isinstance(factory.services.operator_review, OperatorReviewRepository)
        assert factory.services.operator_review.conn is factory.conn
        assert isinstance(factory.services.story_management, StoryManagementRepository)
        assert factory.services.story_management.conn is factory.conn
        assert isinstance(factory.services.surface_handoff, SurfaceHandoffRepository)
        assert factory.services.surface_handoff.conn is factory.conn
        assert isinstance(factory.services.surface_inventory, SurfaceInventoryRepository)
        assert factory.services.surface_inventory.conn is factory.conn
        assert isinstance(factory.services.surface_requirements, SurfaceRequirementsRepository)
        assert factory.services.surface_requirements.conn is factory.conn
        assert isinstance(factory.services.surface_summary, SurfaceSummaryRepository)
        assert factory.services.surface_summary.conn is factory.conn
        assert isinstance(factory.services.draft_inventory_gap, DraftInventoryGapRepository)
        assert factory.services.draft_inventory_gap.conn is factory.conn
        assert isinstance(factory.services.daily_plan, DailyPlanRepository)
        assert factory.services.daily_plan.conn is factory.conn
        assert isinstance(factory.services.execution_readiness, ExecutionReadinessRepository)
        assert factory.services.execution_readiness.conn is factory.conn
        assert isinstance(factory.services.acceptance_suite, AcceptanceSuiteRepository)
        assert factory.services.acceptance_suite.conn is factory.conn
        assert isinstance(factory.services.readiness_report, ReadinessReportRepository)
        assert factory.services.readiness_report.conn is factory.conn
        assert isinstance(factory.services.live_scale, LiveScaleRepository)
        assert factory.services.live_scale.conn is factory.conn
        assert isinstance(factory.services.live_acceptance, LiveAcceptanceRepository)
        assert factory.services.live_acceptance.conn is factory.conn
        assert isinstance(factory.services.certification, CertificationRepository)
        assert factory.services.certification.conn is factory.conn
        assert isinstance(factory.services.operational_proofs, OperationalProofRepository)
        assert factory.services.operational_proofs.conn is factory.conn
        assert isinstance(factory.services.core_complexity, CoreComplexityRepository)
        assert factory.services.core_complexity.conn is factory.conn
        assert isinstance(factory.services.account_health, AccountHealthRepository)
        assert factory.services.account_health.conn is factory.conn
        assert isinstance(factory.services.autonomy, AutonomyPolicyRepository)
        assert factory.services.autonomy.conn is factory.conn
        assert isinstance(factory.services.account_memory, AccountMemoryRepository)
        assert factory.services.account_memory.conn is factory.conn
        assert isinstance(factory.services.recommendation_accuracy_repo, RecommendationAccuracyRepository)
        assert factory.services.recommendation_accuracy_repo.conn is factory.conn
        assert isinstance(factory.services.campaign_overview, CampaignOverviewRepository)
        assert factory.services.campaign_overview.conn is factory.conn
    finally:
        factory.close()


def test_campaign_factory_delegates_campaign_overview_methods_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def campaign_health(self, *args, **kwargs):
            calls.append(("campaign_health", args, kwargs))
            return {"schema": "campaign_factory.campaign_health.v1", "campaign": args[0]}

        def asset_detail(self, *args, **kwargs):
            calls.append(("asset_detail", args, kwargs))
            return {"schema": "campaign_factory.asset_detail.v1", "asset": {"id": args[0]}}

        def assign_asset_account(self, *args, **kwargs):
            calls.append(("assign_asset_account", args, kwargs))
            return {"rendered_asset_id": args[0], "instagram_account_id": kwargs["instagram_account_id"]}

        def assignments_for_asset(self, *args, **kwargs):
            calls.append(("assignments_for_asset", args, kwargs))
            return [{"rendered_asset_id": args[0]}]

        def assignments_for_campaign(self, *args, **kwargs):
            calls.append(("assignments_for_campaign", args, kwargs))
            return [{"campaign": args[0]}]

    factory.services = FakeServices()

    assert factory.campaign_health("may") == {"schema": "campaign_factory.campaign_health.v1", "campaign": "may"}
    assert factory.asset_detail("asset_1") == {"schema": "campaign_factory.asset_detail.v1", "asset": {"id": "asset_1"}}
    assert factory.assign_asset_account(
        "asset_1",
        account_id="acct_1",
        instagram_account_id="ig_1",
        planned_window_start="2026-05-15T10:00:00-04:00",
        planned_window_end="2026-05-15T12:00:00-04:00",
        notes="morning test",
    ) == {"rendered_asset_id": "asset_1", "instagram_account_id": "ig_1"}
    assert factory.assignments_for_asset("asset_1") == [{"rendered_asset_id": "asset_1"}]
    assert factory.assignments_for_campaign("may") == [{"campaign": "may"}]

    assert calls == [
        ("campaign_health", ("may",), {}),
        ("asset_detail", ("asset_1",), {}),
        ("assign_asset_account", ("asset_1",), {
            "account_id": "acct_1",
            "instagram_account_id": "ig_1",
            "planned_window_start": "2026-05-15T10:00:00-04:00",
            "planned_window_end": "2026-05-15T12:00:00-04:00",
            "notes": "morning test",
        }),
        ("assignments_for_asset", ("asset_1",), {}),
        ("assignments_for_campaign", ("may",), {}),
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
    assert calls == [("jobs_for_campaign", ("may",), {"limit": 5})]


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
    assert factory.account_surface_summary(creator="Stacey", account_id="ig_1", generated_at="2026-06-06T12:00:00Z") == {
        "schema": "creator_os.account_surface_summary.v1",
    }
    assert factory.creator_surface_gap_report(creator="Stacey", date="2026-06-06") == {
        "schema": "creator_os.creator_surface_gap_report.v1",
    }
    assert calls == [
        ("creator_surface_summary", (), {"creator": "Stacey", "date": "2026-06-06", "generated_at": None}),
        (
            "account_surface_summary",
            (),
            {"creator": "Stacey", "date": None, "account_id": "ig_1", "generated_at": "2026-06-06T12:00:00Z"},
        ),
        ("creator_surface_gap_report", (), {"creator": "Stacey", "date": "2026-06-06", "generated_at": None}),
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

    assert factory.multi_surface_inventory_audit(creator="Stacey", campaign_slug="summer") == {
        "schema": "campaign_factory.multi_surface_inventory_audit.v1",
    }
    assert factory._build_surface_inventory(creator="Stacey", campaign_slug="summer") == {
        "schema": "campaign_factory.surface_inventory.v1",
    }
    assert calls == [
        ("multi_surface_inventory_audit", (), {"creator": "Stacey", "campaign_slug": "summer"}),
        ("build_surface_inventory", (), {"creator": "Stacey", "campaign_slug": "summer"}),
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

    assert factory.account_surface_obligations_plan(creator="Stacey", date="2026-06-06") == {
        "schema": "campaign_factory.account_surface_obligations_plan.v1",
    }
    assert factory.account_content_needs(account_id="acct_1", creator="Stacey", date="2026-06-06") == {
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
    assert factory._account_content_requirement_rows(creator="Stacey") == [{"id": "req_1"}]
    assert factory._account_row_for_requirement_account("acct_1") == {"id": "acct_1"}
    assert factory._content_obligation_for_requirement({"id": "req_1"}, "2026-06-06") == {"surface": "story"}
    assert factory._required_content_count({"id": "req_1"}, "2026-06-06") == 2
    assert factory._empty_surface_totals() == {"story": {"required": 0}}
    totals = {"story": {"required": 0}}
    factory._add_obligation_to_totals(totals, {"surface": "story"})
    assert factory._requirement_active_on_date({"id": "req_1"}, "2026-06-06") is True
    assert factory._surface_scheduled_count("acct_1", "ig_1", "story", "2026-06-06") == 1
    assert factory._surface_completed_count("acct_1", "ig_1", "story", "2026-06-06") == 0
    assert factory._last_surface_posted_at(
        account_id="acct_1",
        instagram_account_id="ig_1",
        surface="story",
        before_date="2026-06-06",
    ) == "2026-06-05T12:00:00+00:00"
    assert factory._surface_scheduled_for_account("acct_1", "ig_1", "story", "2026-06-06") is True
    assert factory._surface_completed_for_account("acct_1", "ig_1", "story", "2026-06-06") is False

    assert calls == [
        ("account_surface_obligations_plan", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("account_content_needs", (), {"account_id": "acct_1", "creator": "Stacey", "date": "2026-06-06"}),
        ("account_surface_status", (), {"account_id": "acct_1", "creator": None, "date": "2026-06-06"}),
        ("creator_content_needs", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("surface_gap_report", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("build_surface_status", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("account_content_requirement_rows", (), {"creator": "Stacey", "account_id": None}),
        ("account_row_for_requirement_account", ("acct_1",), {}),
        ("content_obligation_for_requirement", ({"id": "req_1"}, "2026-06-06"), {}),
        ("required_content_count", ({"id": "req_1"}, "2026-06-06"), {}),
        ("empty_surface_totals", (), {}),
        ("add_obligation_to_totals", (totals, {"surface": "story"}), {}),
        ("requirement_active_on_date", ({"id": "req_1"}, "2026-06-06"), {}),
        ("surface_scheduled_count", ("acct_1", "ig_1", "story", "2026-06-06"), {}),
        ("surface_completed_count", ("acct_1", "ig_1", "story", "2026-06-06"), {}),
        ("last_surface_posted_at", (), {
            "account_id": "acct_1",
            "instagram_account_id": "ig_1",
            "surface": "story",
            "before_date": "2026-06-06",
        }),
        ("surface_scheduled_for_account", ("acct_1", "ig_1", "story", "2026-06-06"), {}),
        ("surface_completed_for_account", ("acct_1", "ig_1", "story", "2026-06-06"), {}),
    ]


def test_campaign_factory_delegates_creator_os_draft_inventory_gap_to_services() -> None:
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
    factory = CampaignFactory(Settings(
        root=tmp_path,
        db_path=tmp_path / "campaign_factory.sqlite",
        reel_factory_root=tmp_path / "reel_factory",
        contentforge_root=tmp_path / "contentforge",
        threadsdash_root=tmp_path / "ThreadsDashboard",
        campaigns_dir=tmp_path / "campaigns",
    ))
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


def test_core_services_delegates_creator_os_draft_inventory_gap_to_repository(tmp_path) -> None:
    factory = CampaignFactory(Settings(
        root=tmp_path,
        db_path=tmp_path / "campaign_factory.sqlite",
        reel_factory_root=tmp_path / "reel_factory",
        contentforge_root=tmp_path / "contentforge",
        threadsdash_root=tmp_path / "ThreadsDashboard",
        campaigns_dir=tmp_path / "campaigns",
    ))
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
            return {"schema": "campaign_factory.account_memory_rebuild.v1", "campaign": args[0]}

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
            return {"schema": "campaign_factory.recommendation_accuracy_report.v1", "campaign": args[0]}

        def rebuild_recommendation_accuracy(self, *args, **kwargs):
            calls.append(("rebuild_recommendation_accuracy", args, kwargs))
            return {"schema": "campaign_factory.recommendation_accuracy_report.v1", "campaign": args[0]}

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
    assert factory.autonomy_level() == "level_2"
    assert factory.set_autonomy_level("level_3") == {"schema": "campaign_factory.autonomy_policy.v1", "level": "level_3"}
    assert factory.autonomy_policy() == {"schema": "campaign_factory.autonomy_policy.v1", "level": "level_2"}
    assert factory.rebuild_account_memory("may") == {"schema": "campaign_factory.account_memory_rebuild.v1", "campaign": "may"}
    assert factory.account_memory("may", account="ig_1") == {"schema": "campaign_factory.account_memory.v1", "campaign": "may"}
    assert factory._account_memory_payload({"id": "acctmem_1", "account_id": "ig_1"}) == {"id": "acctmem_1", "accountId": "ig_1"}
    assert factory._account_memory_for("camp_1", "ig_1") == {"accountId": "ig_1"}
    assert factory._account_pattern_stats_from_snapshots("camp_1", "ig_1", [], "now") == [{"patternType": "recipe"}]
    assert factory._account_posting_windows_from_snapshots("camp_1", "ig_1", [], "now") == [{"weekday": 0}]
    assert factory._account_fatigue_from_pattern_stats([]) == {"level": "low"}
    assert factory._account_recommendation_outcomes("camp_1", "ig_1", "now") == {"measuredTotal": 0}
    assert factory._account_memory_confidence(1, {"measuredTotal": 0}) == "low"
    assert factory.recommendation_accuracy("may", account="ig_1", window_days=7, persist=False) == {
        "schema": "campaign_factory.recommendation_accuracy_report.v1",
        "campaign": "may",
    }
    assert factory.rebuild_recommendation_accuracy("may", account="ig_1", window_days=7) == {
        "schema": "campaign_factory.recommendation_accuracy_report.v1",
        "campaign": "may",
    }
    assert factory._recommendation_proof_summary("camp_1") == {"measuredCount": 1}
    assert factory._rebuild_recommendation_accuracy_observations("camp_1", account="ig_1") == [{"id": "obs_1"}]
    assert factory._upsert_recommendation_accuracy_observation({"id": "rec_1"}, commit=True) == {"id": "obs_1"}
    assert factory._recommendation_accuracy_observations("camp_1", account="ig_1", window_days=7) == [{"id": "obs_1"}]
    assert factory._recommendation_accuracy_report_payload({"id": "camp_1", "slug": "may"}, [], [], account="ig_1", window_days=7) == {
        "schema": "campaign_factory.recommendation_accuracy_report.v1",
    }
    assert factory._persist_recommendation_accuracy_report({"observations": []}, "camp_1", account="ig_1", window_days=7) == "recacc_report_1"
    assert factory._recommendation_accuracy_drift([], []) == []
    assert factory._recommendation_trust_score([], []) == 80
    assert factory._recommendation_trust_confidence(10) == "usable"
    assert factory._recommendation_confidence_bucket("medium", "high") == "usable"
    assert factory._recommendation_audio_selection("rec_1") == {"id": "audsel_1"}
    assert factory._recommendation_audio_match_status({"audioRecommendations": {"recommendations": []}}, {"id": "audsel_1"}) == "recommended_audio_selected"
    assert factory._recommendation_outcome_snapshot_ids({"snapshots": [{"id": "perf_1"}]}, {}) == ["perf_1"]
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
        ("autonomy_level", (), {}),
        ("set_autonomy_level", ("level_3",), {}),
        ("autonomy_policy", (), {}),
        ("rebuild_account_memory", ("may",), {}),
        ("account_memory_report", ("may",), {"account": "ig_1"}),
        ("account_memory_payload", ({"id": "acctmem_1", "account_id": "ig_1"},), {}),
        ("account_memory_for", ("camp_1", "ig_1"), {}),
        ("account_pattern_stats_from_snapshots", ("camp_1", "ig_1", [], "now"), {"account_baselines": None}),
        ("account_posting_windows_from_snapshots", ("camp_1", "ig_1", [], "now"), {"account_baselines": None}),
        ("account_fatigue_from_pattern_stats", ([],), {}),
        ("account_recommendation_outcomes", ("camp_1", "ig_1", "now"), {}),
        ("account_memory_confidence", (1, {"measuredTotal": 0}), {}),
        ("recommendation_accuracy", ("may",), {"account": "ig_1", "window_days": 7, "persist": False}),
        ("rebuild_recommendation_accuracy", ("may",), {"account": "ig_1", "window_days": 7}),
        ("recommendation_proof_summary", ("camp_1",), {}),
        ("rebuild_recommendation_accuracy_observations", ("camp_1",), {"account": "ig_1", "commit": True}),
        ("upsert_recommendation_accuracy_observation", ({"id": "rec_1"},), {"commit": True}),
        ("recommendation_accuracy_observations", ("camp_1",), {"account": "ig_1", "window_days": 7, "before_window_days": None}),
        ("recommendation_accuracy_report_payload", ({"id": "camp_1", "slug": "may"}, [], []), {"account": "ig_1", "window_days": 7}),
        ("persist_recommendation_accuracy_report", ({"observations": []}, "camp_1"), {"account": "ig_1", "window_days": 7}),
        ("recommendation_accuracy_drift", ([], []), {"min_sample": 5, "drop_threshold": 0.15}),
        ("recommendation_trust_score", ([], []), {}),
        ("recommendation_trust_confidence", (10,), {}),
        ("recommendation_confidence_bucket", ("medium", "high"), {}),
        ("recommendation_audio_selection", ("rec_1",), {}),
        ("recommendation_audio_match_status", ({"audioRecommendations": {"recommendations": []}}, {"id": "audsel_1"}), {}),
        ("recommendation_outcome_snapshot_ids", ({"snapshots": [{"id": "perf_1"}]}, {}), {}),
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
    assert services.set_autonomy_level("level_3") == {"schema": "campaign_factory.autonomy_policy.v1", "level": "level_3"}
    assert services.autonomy_policy() == {"schema": "campaign_factory.autonomy_policy.v1", "level": "level_2"}

    assert calls == [
        ("autonomy_level", (), {}),
        ("set_autonomy_level", ("level_3",), {}),
        ("autonomy_policy", (), {}),
    ]


def test_core_services_delegates_account_memory_methods_to_account_memory_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeAccountMemory:
        def rebuild_account_memory(self, *args, **kwargs):
            calls.append(("rebuild_account_memory", args, kwargs))
            return {"schema": "campaign_factory.account_memory_rebuild.v1", "campaign": args[0]}

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

    assert services.rebuild_account_memory("may") == {"schema": "campaign_factory.account_memory_rebuild.v1", "campaign": "may"}
    assert services.account_memory_report("may", account="ig_1") == {"schema": "campaign_factory.account_memory.v1", "campaign": "may"}
    assert services.account_memory_payload({"id": "acctmem_1"}) == {"id": "acctmem_1"}
    assert services.account_memory_for("camp_1", "ig_1") == {"accountId": "ig_1"}
    assert services.account_pattern_stats_from_snapshots("camp_1", "ig_1", [], "now") == [{"patternType": "recipe"}]
    assert services.account_posting_windows_from_snapshots("camp_1", "ig_1", [], "now") == [{"weekday": 0}]
    assert services.account_fatigue_from_pattern_stats([]) == {"level": "low"}
    assert services.account_recommendation_outcomes("camp_1", "ig_1", "now") == {"measuredTotal": 0}
    assert services.account_memory_confidence(1, {"measuredTotal": 0}) == "low"

    assert calls == [
        ("rebuild_account_memory", ("may",), {}),
        ("account_memory", ("may",), {"account": "ig_1"}),
        ("account_memory_payload", ({"id": "acctmem_1"},), {}),
        ("account_memory_for", ("camp_1", "ig_1"), {}),
        ("account_pattern_stats_from_snapshots", ("camp_1", "ig_1", [], "now"), {"account_baselines": None}),
        ("account_posting_windows_from_snapshots", ("camp_1", "ig_1", [], "now"), {"account_baselines": None}),
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
    assert calls == [("jobs_for_campaign", ("may",), {"limit": 5})]


def test_core_services_delegates_surface_summary_methods_to_surface_summary_repository() -> None:
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
    assert services.account_surface_summary(creator="Stacey", account_id="ig_1", generated_at="2026-06-06T12:00:00Z") == {
        "schema": "creator_os.account_surface_summary.v1",
    }
    assert services.creator_surface_gap_report(creator="Stacey", date="2026-06-06") == {
        "schema": "creator_os.creator_surface_gap_report.v1",
    }
    assert calls == [
        ("creator_surface_summary", (), {"creator": "Stacey", "date": "2026-06-06", "generated_at": None}),
        (
            "account_surface_summary",
            (),
            {"creator": "Stacey", "date": None, "account_id": "ig_1", "generated_at": "2026-06-06T12:00:00Z"},
        ),
        ("creator_surface_gap_report", (), {"creator": "Stacey", "date": "2026-06-06", "generated_at": None}),
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

    assert services.multi_surface_inventory_audit(creator="Stacey", campaign_slug="summer") == {
        "schema": "campaign_factory.multi_surface_inventory_audit.v1",
    }
    assert services.build_surface_inventory(creator="Stacey", campaign_slug="summer") == {
        "schema": "campaign_factory.surface_inventory.v1",
    }
    assert calls == [
        ("multi_surface_inventory_audit", (), {"creator": "Stacey", "campaign_slug": "summer"}),
        ("build_surface_inventory", (), {"creator": "Stacey", "campaign_slug": "summer"}),
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

    assert services.account_surface_obligations_plan(creator="Stacey", date="2026-06-06") == {
        "schema": "campaign_factory.account_surface_obligations_plan.v1",
    }
    assert services.account_content_needs(account_id="acct_1", creator="Stacey", date="2026-06-06") == {
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
    assert services.account_content_requirement_rows(creator="Stacey") == [{"id": "req_1"}]
    assert services.account_row_for_requirement_account("acct_1") == {"id": "acct_1"}
    assert services.content_obligation_for_requirement({"id": "req_1"}, "2026-06-06") == {"surface": "story"}
    assert services.required_content_count({"id": "req_1"}, "2026-06-06") == 2
    assert services.empty_surface_totals() == {"story": {"required": 0}}
    totals = {"story": {"required": 0}}
    services.add_obligation_to_totals(totals, {"surface": "story"})
    assert services.requirement_active_on_date({"id": "req_1"}, "2026-06-06") is True
    assert services.surface_scheduled_count("acct_1", "ig_1", "story", "2026-06-06") == 1
    assert services.surface_completed_count("acct_1", "ig_1", "story", "2026-06-06") == 0
    assert services.last_surface_posted_at(
        account_id="acct_1",
        instagram_account_id="ig_1",
        surface="story",
        before_date="2026-06-06",
    ) == "2026-06-05T12:00:00+00:00"
    assert services.surface_scheduled_for_account("acct_1", "ig_1", "story", "2026-06-06") is True
    assert services.surface_completed_for_account("acct_1", "ig_1", "story", "2026-06-06") is False

    assert calls == [
        ("account_surface_obligations_plan", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("account_content_needs", (), {"account_id": "acct_1", "creator": "Stacey", "date": "2026-06-06"}),
        ("account_surface_status", (), {"account_id": "acct_1", "creator": None, "date": "2026-06-06"}),
        ("creator_content_needs", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("surface_gap_report", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("build_surface_status", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("account_content_requirement_rows", (), {"creator": "Stacey", "account_id": None}),
        ("account_row_for_requirement_account", ("acct_1",), {}),
        ("content_obligation_for_requirement", ({"id": "req_1"}, "2026-06-06"), {}),
        ("required_content_count", ({"id": "req_1"}, "2026-06-06"), {}),
        ("empty_surface_totals", (), {}),
        ("add_obligation_to_totals", (totals, {"surface": "story"}), {}),
        ("requirement_active_on_date", ({"id": "req_1"}, "2026-06-06"), {}),
        ("surface_scheduled_count", ("acct_1", "ig_1", "story", "2026-06-06"), {}),
        ("surface_completed_count", ("acct_1", "ig_1", "story", "2026-06-06"), {}),
        ("last_surface_posted_at", (), {
            "account_id": "acct_1",
            "instagram_account_id": "ig_1",
            "surface": "story",
            "before_date": "2026-06-06",
        }),
        ("surface_scheduled_for_account", ("acct_1", "ig_1", "story", "2026-06-06"), {}),
        ("surface_completed_for_account", ("acct_1", "ig_1", "story", "2026-06-06"), {}),
    ]


def test_core_services_delegates_recommendation_accuracy_methods_to_recommendation_accuracy_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeRecommendationAccuracy:
        def recommendation_accuracy(self, *args, **kwargs):
            calls.append(("recommendation_accuracy", args, kwargs))
            return {"schema": "campaign_factory.recommendation_accuracy_report.v1", "campaign": args[0]}

        def rebuild_recommendation_accuracy(self, *args, **kwargs):
            calls.append(("rebuild_recommendation_accuracy", args, kwargs))
            return {"schema": "campaign_factory.recommendation_accuracy_report.v1", "campaign": args[0]}

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

    assert services.recommendation_accuracy("may", account="ig_1", window_days=7, persist=False) == {
        "schema": "campaign_factory.recommendation_accuracy_report.v1",
        "campaign": "may",
    }
    assert services.rebuild_recommendation_accuracy("may", account="ig_1", window_days=7) == {
        "schema": "campaign_factory.recommendation_accuracy_report.v1",
        "campaign": "may",
    }
    assert services.recommendation_proof_summary("camp_1") == {"measuredCount": 1}
    assert services.rebuild_recommendation_accuracy_observations("camp_1", account="ig_1") == [{"id": "obs_1"}]
    assert services.upsert_recommendation_accuracy_observation({"id": "rec_1"}, commit=True) == {"id": "obs_1"}
    assert services.recommendation_accuracy_observations("camp_1", account="ig_1", window_days=7) == [{"id": "obs_1"}]
    assert services.recommendation_accuracy_report_payload({"id": "camp_1", "slug": "may"}, [], [], account="ig_1", window_days=7) == {
        "schema": "campaign_factory.recommendation_accuracy_report.v1",
    }
    assert services.persist_recommendation_accuracy_report({"observations": []}, "camp_1", account="ig_1", window_days=7) == "recacc_report_1"
    assert services.recommendation_accuracy_drift([], []) == []
    assert services.recommendation_trust_score([], []) == 80
    assert services.recommendation_trust_confidence(10) == "usable"
    assert services.recommendation_confidence_bucket("medium", "high") == "usable"
    assert services.recommendation_audio_selection("rec_1") == {"id": "audsel_1"}
    assert services.recommendation_audio_match_status({"audioRecommendations": {"recommendations": []}}, {"id": "audsel_1"}) == "recommended_audio_selected"
    assert services.recommendation_outcome_snapshot_ids({"snapshots": [{"id": "perf_1"}]}, {}) == ["perf_1"]

    assert calls == [
        ("recommendation_accuracy", ("may",), {"account": "ig_1", "window_days": 7, "persist": False}),
        ("rebuild_recommendation_accuracy", ("may",), {"account": "ig_1", "window_days": 7}),
        ("recommendation_proof_summary", ("camp_1",), {}),
        ("rebuild_recommendation_accuracy_observations", ("camp_1",), {"account": "ig_1", "commit": True}),
        ("upsert_recommendation_accuracy_observation", ({"id": "rec_1"},), {"commit": True}),
        ("recommendation_accuracy_observations", ("camp_1",), {"account": "ig_1", "window_days": 7, "before_window_days": None}),
        ("recommendation_accuracy_report_payload", ({"id": "camp_1", "slug": "may"}, [], []), {"account": "ig_1", "window_days": 7}),
        ("persist_recommendation_accuracy_report", ({"observations": []}, "camp_1"), {"account": "ig_1", "window_days": 7}),
        ("recommendation_accuracy_drift", ([], []), {"min_sample": 5, "drop_threshold": 0.15}),
        ("recommendation_trust_score", ([], []), {}),
        ("recommendation_trust_confidence", (10,), {}),
        ("recommendation_confidence_bucket", ("medium", "high"), {}),
        ("recommendation_audio_selection", ("rec_1",), {}),
        ("recommendation_audio_match_status", ({"audioRecommendations": {"recommendations": []}}, {"id": "audsel_1"}), {}),
        ("recommendation_outcome_snapshot_ids", ({"snapshots": [{"id": "perf_1"}]}, {}), {}),
    ]


def test_core_services_delegates_campaign_overview_methods_to_campaign_overview_repository() -> None:
    services = object.__new__(CoreServices)
    calls = []

    class FakeCampaignOverview:
        def campaign_health(self, *args, **kwargs):
            calls.append(("campaign_health", args, kwargs))
            return {"schema": "campaign_factory.campaign_health.v1", "campaign": args[0]}

        def asset_detail(self, *args, **kwargs):
            calls.append(("asset_detail", args, kwargs))
            return {"schema": "campaign_factory.asset_detail.v1", "asset": {"id": args[0]}}

        def assign_asset_account(self, *args, **kwargs):
            calls.append(("assign_asset_account", args, kwargs))
            return {"rendered_asset_id": args[0], "instagram_account_id": kwargs["instagram_account_id"]}

        def assignments_for_asset(self, *args, **kwargs):
            calls.append(("assignments_for_asset", args, kwargs))
            return [{"rendered_asset_id": args[0]}]

        def assignments_for_campaign(self, *args, **kwargs):
            calls.append(("assignments_for_campaign", args, kwargs))
            return [{"campaign": args[0]}]

    services.campaign_overview = FakeCampaignOverview()

    assert services.campaign_health("may") == {"schema": "campaign_factory.campaign_health.v1", "campaign": "may"}
    assert services.asset_detail("asset_1") == {"schema": "campaign_factory.asset_detail.v1", "asset": {"id": "asset_1"}}
    assert services.assign_asset_account(
        "asset_1",
        account_id="acct_1",
        instagram_account_id="ig_1",
        planned_window_start="2026-05-15T10:00:00-04:00",
        planned_window_end="2026-05-15T12:00:00-04:00",
        notes="morning test",
    ) == {"rendered_asset_id": "asset_1", "instagram_account_id": "ig_1"}
    assert services.assignments_for_asset("asset_1") == [{"rendered_asset_id": "asset_1"}]
    assert services.assignments_for_campaign("may") == [{"campaign": "may"}]

    assert calls == [
        ("campaign_health", ("may",), {}),
        ("asset_detail", ("asset_1",), {}),
        ("assign_asset_account", ("asset_1",), {
            "account_id": "acct_1",
            "instagram_account_id": "ig_1",
            "planned_window_start": "2026-05-15T10:00:00-04:00",
            "planned_window_end": "2026-05-15T12:00:00-04:00",
            "notes": "morning test",
        }),
        ("assignments_for_asset", ("asset_1",), {}),
        ("assignments_for_campaign", ("may",), {}),
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

    assert services.tribev2_reel_analysis(creator="Stacey", campaign_slug="May", limit=2) == {
        "schema": "campaign_factory.tribev2_reel_analysis.v1",
    }
    assert services.tribev2_reel_review(creator="Stacey", campaign_slug="May", bucket="both") == {
        "schema": "campaign_factory.tribev2_reel_review.v1",
    }
    assert services.tribev2_holdout_pilot_review(creator="Stacey", campaign_slug="May") == {
        "schema": "campaign_factory.tribev2_holdout_pilot_review.v1",
    }
    assert services.tribev2_review_both_bucket(ranked, 1) == [{"renderedAssetId": "asset_1"}]
    assert services.tribev2_review_item(
        ranked[0],
        rank=1,
        sort_field="meanAbsActivation",
        show_metrics=False,
        show_tribe_score=True,
    ) == {"renderedAssetId": "asset_1"}
    assert services.tribev2_holdout_bucket_rows(ranked) == {"top20": [], "middle20": [], "bottom20": []}
    assert services.tribev2_holdout_bucket_summary("top20", ranked, limit=1) == {"bucket": "top20"}
    assert services.tribev2_average_metrics(ranked) == {"views": 10.0}
    assert services.tribev2_average_scores(ranked) == {"meanAbsActivation": 0.1}
    assert services.average_row_field(ranked, "views") == 10.0
    assert services.tribev2_preview_path(ranked[0]) == "/tmp/preview.mp4"
    assert services.write_tribev2_review_contact_sheet(
        [item],
        creator="Stacey",
        title="Review",
        blind_mode=True,
        show_metrics=False,
        show_tribe_score=True,
    ) == "/tmp/review.html"
    assert services.write_tribev2_holdout_contact_sheet(buckets, creator="Stacey") == "/tmp/holdout.html"
    assert services.tribev2_contact_sheet_cards(
        [item],
        Path("/tmp"),
        show_metrics=False,
        show_tribe_score=True,
    ) == ["<article></article>"]
    assert services.tribev2_contact_sheet_html(title="Review", body="<p>body</p>") == "<html></html>"
    assert services.tribev2_extract_thumbnail("/tmp/preview.mp4", Path("/tmp"), item) == "/tmp/thumb.jpg"
    assert services.tribev2_reel_analysis_rows(creator="Stacey", campaign_slug="May") == [
        {"renderedAssetId": "asset_1"},
    ]
    assert services.tribev2_score_for_snapshot({"rendered_asset_id": "asset_1"}) == {"id": "tribe_1"}
    assert services.pearson_correlation([1.0, 2.0], [3.0, 4.0]) == 0.5
    assert services.tribev2_bucket_summary(ranked) == {"sampleSize": 1}
    assert services.tribev2_bucket_lift({"avgViews": 2}, {"avgViews": 1}) == {"avgViews": 100.0}
    assert services.tribev2_metric_quality(ranked, ["views"]) == {"views": {"usableForCorrelation": True}}
    assert services.tribev2_signal_summary(
        {"meanAbsActivation": {"views": 0.5}},
        sample_size=20,
        metric_quality={"views": {"usableForCorrelation": True}},
    ) == {"strongestSignal": "meanAbsActivation:views"}
    assert services.tribev2_confidence_level(20, True) == "medium"

    assert calls == [
        ("tribev2_reel_analysis", (), {
            "creator": "Stacey",
            "campaign_slug": "May",
            "minimum_sample_size": 3,
            "limit": 2,
        }),
        ("tribev2_reel_review", (), {
            "creator": "Stacey",
            "campaign_slug": "May",
            "sort_by": "meanAbsActivation",
            "bucket": "both",
            "limit": 12,
            "contact_sheet": False,
            "show_metrics": None,
            "show_tribe_score": True,
            "blind_mode": False,
        }),
        ("tribev2_holdout_pilot_review", (), {
            "creator": "Stacey",
            "campaign_slug": "May",
            "limit": 20,
            "contact_sheet": False,
        }),
        ("tribev2_review_both_bucket", (ranked, 1), {}),
        ("tribev2_review_item", (ranked[0],), {
            "rank": 1,
            "sort_field": "meanAbsActivation",
            "show_metrics": False,
            "show_tribe_score": True,
        }),
        ("tribev2_holdout_bucket_rows", (ranked,), {}),
        ("tribev2_holdout_bucket_summary", ("top20", ranked), {"limit": 1}),
        ("tribev2_average_metrics", (ranked,), {}),
        ("tribev2_average_scores", (ranked,), {}),
        ("average_row_field", (ranked, "views"), {}),
        ("tribev2_preview_path", (ranked[0],), {}),
        ("write_tribev2_review_contact_sheet", ([item],), {
            "creator": "Stacey",
            "title": "Review",
            "blind_mode": True,
            "show_metrics": False,
            "show_tribe_score": True,
        }),
        ("write_tribev2_holdout_contact_sheet", (buckets,), {"creator": "Stacey"}),
        ("tribev2_contact_sheet_cards", ([item], Path("/tmp")), {
            "show_metrics": False,
            "show_tribe_score": True,
        }),
        ("tribev2_contact_sheet_html", (), {"title": "Review", "body": "<p>body</p>"}),
        ("tribev2_extract_thumbnail", ("/tmp/preview.mp4", Path("/tmp"), item), {}),
        ("tribev2_reel_analysis_rows", (), {"creator": "Stacey", "campaign_slug": "May"}),
        ("tribev2_score_for_snapshot", ({"rendered_asset_id": "asset_1"},), {}),
        ("pearson_correlation", ([1.0, 2.0], [3.0, 4.0]), {}),
        ("tribev2_bucket_summary", (ranked,), {}),
        ("tribev2_bucket_lift", ({"avgViews": 2}, {"avgViews": 1}), {}),
        ("tribev2_metric_quality", (ranked, ["views"]), {}),
        ("tribev2_signal_summary", ({"meanAbsActivation": {"views": 0.5}},), {
            "sample_size": 20,
            "metric_quality": {"views": {"usableForCorrelation": True}},
        }),
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

    assert factory.tribev2_reel_analysis(creator="Stacey", campaign_slug="May", limit=2) == {
        "schema": "campaign_factory.tribev2_reel_analysis.v1",
    }
    assert factory.tribev2_reel_review(creator="Stacey", campaign_slug="May", bucket="both") == {
        "schema": "campaign_factory.tribev2_reel_review.v1",
    }
    assert factory.tribev2_holdout_pilot_review(creator="Stacey", campaign_slug="May") == {
        "schema": "campaign_factory.tribev2_holdout_pilot_review.v1",
    }
    assert factory._tribev2_review_both_bucket(ranked, 1) == [{"renderedAssetId": "asset_1"}]
    assert factory._tribev2_review_item(
        ranked[0],
        rank=1,
        sort_field="meanAbsActivation",
        show_metrics=False,
        show_tribe_score=True,
    ) == {"renderedAssetId": "asset_1"}
    assert factory._tribev2_holdout_bucket_rows(ranked) == {"top20": [], "middle20": [], "bottom20": []}
    assert factory._tribev2_holdout_bucket_summary("top20", ranked, limit=1) == {"bucket": "top20"}
    assert factory._tribev2_average_metrics(ranked) == {"views": 10.0}
    assert factory._tribev2_average_scores(ranked) == {"meanAbsActivation": 0.1}
    assert factory._average_row_field(ranked, "views") == 10.0
    assert factory._tribev2_preview_path(ranked[0]) == "/tmp/preview.mp4"
    assert factory._write_tribev2_review_contact_sheet(
        [item],
        creator="Stacey",
        title="Review",
        blind_mode=True,
        show_metrics=False,
        show_tribe_score=True,
    ) == "/tmp/review.html"
    assert factory._write_tribev2_holdout_contact_sheet(buckets, creator="Stacey") == "/tmp/holdout.html"
    assert factory._tribev2_contact_sheet_cards(
        [item],
        Path("/tmp"),
        show_metrics=False,
        show_tribe_score=True,
    ) == ["<article></article>"]
    assert factory._tribev2_contact_sheet_html(title="Review", body="<p>body</p>") == "<html></html>"
    assert factory._tribev2_extract_thumbnail("/tmp/preview.mp4", Path("/tmp"), item) == "/tmp/thumb.jpg"
    assert factory._tribev2_reel_analysis_rows(creator="Stacey", campaign_slug="May") == [
        {"renderedAssetId": "asset_1"},
    ]
    assert factory._tribev2_score_for_snapshot({"rendered_asset_id": "asset_1"}) == {"id": "tribe_1"}
    assert factory._pearson_correlation([1.0, 2.0], [3.0, 4.0]) == 0.5
    assert factory._tribev2_bucket_summary(ranked) == {"sampleSize": 1}
    assert factory._tribev2_bucket_lift({"avgViews": 2}, {"avgViews": 1}) == {"avgViews": 100.0}
    assert factory._tribev2_metric_quality(ranked, ["views"]) == {"views": {"usableForCorrelation": True}}
    assert factory._tribev2_signal_summary(
        {"meanAbsActivation": {"views": 0.5}},
        sample_size=20,
        metric_quality={"views": {"usableForCorrelation": True}},
    ) == {"strongestSignal": "meanAbsActivation:views"}
    assert factory._tribev2_confidence_level(20, True) == "medium"

    assert calls == [
        ("tribev2_reel_analysis", (), {
            "creator": "Stacey",
            "campaign_slug": "May",
            "minimum_sample_size": 3,
            "limit": 2,
        }),
        ("tribev2_reel_review", (), {
            "creator": "Stacey",
            "campaign_slug": "May",
            "sort_by": "meanAbsActivation",
            "bucket": "both",
            "limit": 12,
            "contact_sheet": False,
            "show_metrics": None,
            "show_tribe_score": True,
            "blind_mode": False,
        }),
        ("tribev2_holdout_pilot_review", (), {
            "creator": "Stacey",
            "campaign_slug": "May",
            "limit": 20,
            "contact_sheet": False,
        }),
        ("tribev2_review_both_bucket", (ranked, 1), {}),
        ("tribev2_review_item", (ranked[0],), {
            "rank": 1,
            "sort_field": "meanAbsActivation",
            "show_metrics": False,
            "show_tribe_score": True,
        }),
        ("tribev2_holdout_bucket_rows", (ranked,), {}),
        ("tribev2_holdout_bucket_summary", ("top20", ranked), {"limit": 1}),
        ("tribev2_average_metrics", (ranked,), {}),
        ("tribev2_average_scores", (ranked,), {}),
        ("average_row_field", (ranked, "views"), {}),
        ("tribev2_preview_path", (ranked[0],), {}),
        ("write_tribev2_review_contact_sheet", ([item],), {
            "creator": "Stacey",
            "title": "Review",
            "blind_mode": True,
            "show_metrics": False,
            "show_tribe_score": True,
        }),
        ("write_tribev2_holdout_contact_sheet", (buckets,), {"creator": "Stacey"}),
        ("tribev2_contact_sheet_cards", ([item], Path("/tmp")), {
            "show_metrics": False,
            "show_tribe_score": True,
        }),
        ("tribev2_contact_sheet_html", (), {"title": "Review", "body": "<p>body</p>"}),
        ("tribev2_extract_thumbnail", ("/tmp/preview.mp4", Path("/tmp"), item), {}),
        ("tribev2_reel_analysis_rows", (), {"creator": "Stacey", "campaign_slug": "May"}),
        ("tribev2_score_for_snapshot", ({"rendered_asset_id": "asset_1"},), {}),
        ("pearson_correlation", ([1.0, 2.0], [3.0, 4.0]), {}),
        ("tribev2_bucket_summary", (ranked,), {}),
        ("tribev2_bucket_lift", ({"avgViews": 2}, {"avgViews": 1}), {}),
        ("tribev2_metric_quality", (ranked, ["views"]), {}),
        ("tribev2_signal_summary", ({"meanAbsActivation": {"views": 0.5}},), {
            "sample_size": 20,
            "metric_quality": {"views": {"usableForCorrelation": True}},
        }),
        ("tribev2_confidence_level", (20, True), {}),
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
    assert factory.carousel_certification_proof(rendered_asset_id="asset_carousel") == {
        "schema": "creator_os.carousel_certification_proof.v1",
    }
    assert factory._certification_asset_for_surface("feed_carousel", rendered_asset_id="asset_carousel") == {
        "id": "asset_carousel",
    }
    assert factory._latest_proof_run_for_asset("asset_carousel") == {"id": "proof_carousel"}
    assert factory._latest_surface_metric_for_asset("asset_carousel", "feed_carousel") == {"id": "metric_carousel"}
    assert factory._empty_surface_certification_audit("feed_carousel") == {"contentSurface": "feed_carousel"}
    assert factory._surface_certification_audit(
        asset={"content_surface": "feed_carousel"},
        readiness={},
        draft_payload={},
        proof_run=None,
        metrics=None,
        carousel_integrity={},
    ) == {"contentSurface": "feed_carousel"}
    assert factory.carousel_production_readiness() == {"schema": "creator_os.carousel_production_readiness.v1"}
    assert factory.carousel_proof_gap_analysis() == {"schema": "creator_os.carousel_proof_gap_analysis.v1"}

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
        ("carousel_certification_proof", (), {"rendered_asset_id": "asset_carousel"}),
        ("certification_asset_for_surface", ("feed_carousel",), {"rendered_asset_id": "asset_carousel"}),
        ("latest_proof_run_for_asset", ("asset_carousel",), {}),
        ("latest_surface_metric_for_asset", ("asset_carousel", "feed_carousel"), {}),
        ("empty_surface_certification_audit", ("feed_carousel",), {}),
        ("surface_certification_audit", (), {
            "asset": {"content_surface": "feed_carousel"},
            "readiness": {},
            "draft_payload": {},
            "proof_run": None,
            "metrics": None,
            "carousel_integrity": {},
        }),
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
    assert services.carousel_certification_proof(rendered_asset_id="asset_carousel") == {
        "schema": "creator_os.carousel_certification_proof.v1",
    }
    assert services.certification_asset_for_surface("feed_carousel", rendered_asset_id="asset_carousel") == {
        "id": "asset_carousel",
    }
    assert services.latest_proof_run_for_asset("asset_carousel") == {"id": "proof_carousel"}
    assert services.latest_surface_metric_for_asset("asset_carousel", "feed_carousel") == {"id": "metric_carousel"}
    assert services.empty_surface_certification_audit("feed_carousel") == {"contentSurface": "feed_carousel"}
    assert services.surface_certification_audit(
        asset={"content_surface": "feed_carousel"},
        readiness={},
        draft_payload={},
        proof_run=None,
        metrics=None,
        carousel_integrity={},
    ) == {"contentSurface": "feed_carousel"}
    assert services.carousel_production_readiness() == {"schema": "creator_os.carousel_production_readiness.v1"}
    assert services.carousel_proof_gap_analysis() == {"schema": "creator_os.carousel_proof_gap_analysis.v1"}

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
        ("carousel_certification_proof", (), {"rendered_asset_id": "asset_carousel"}),
        ("certification_asset_for_surface", ("feed_carousel",), {"rendered_asset_id": "asset_carousel"}),
        ("latest_proof_run_for_asset", ("asset_carousel",), {}),
        ("latest_surface_metric_for_asset", ("asset_carousel", "feed_carousel"), {}),
        ("empty_surface_certification_audit", ("feed_carousel",), {}),
        ("surface_certification_audit", (), {
            "asset": {"content_surface": "feed_carousel"},
            "readiness": {},
            "draft_payload": {},
            "proof_run": None,
            "metrics": None,
            "carousel_integrity": {},
        }),
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
    assert factory._surface_report_assets(creator="Stacey", campaign_slug="may") == [{"id": "asset_surface"}]
    assert factory._build_surface_readiness([{"id": "asset_surface"}]) == [{"assetId": "asset_surface"}]
    assert factory._surface_draft_payload_for_readiness({"assetId": "asset_surface"}) == {"assetId": "asset_surface"}
    assert factory._surface_handoff_readiness_for_asset({"id": "asset_surface"}) == {"assetId": "asset_surface", "canHandoff": True}
    assert factory._requires_operator_visual_review_for_handoff({"id": "asset_surface"}) is False
    assert factory._asset_matches_creator({"id": "asset_surface"}, "Stacey") is True
    assert factory._asset_components("asset_surface") == [{"asset_id": "asset_surface", "component_index": 0}]

    assert calls == [
        ("surface_handoff_readiness_report", (), {
            "creator": "Stacey",
            "campaign_slug": "may",
            "rendered_asset_id": "asset_surface",
        }),
        ("surface_draft_proof", (), {
            "creator": "Stacey",
            "campaign": "may",
            "rendered_asset_id": "asset_surface",
        }),
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
    assert services.surface_report_assets(creator="Stacey", campaign_slug="may") == [{"id": "asset_surface"}]
    assert services.build_surface_readiness([{"id": "asset_surface"}]) == [{"assetId": "asset_surface"}]
    assert services.surface_draft_payload_for_readiness({"assetId": "asset_surface"}) == {"assetId": "asset_surface"}
    assert services.surface_handoff_readiness_for_asset({"id": "asset_surface"}) == {"assetId": "asset_surface", "canHandoff": True}
    assert services.requires_operator_visual_review_for_handoff({"id": "asset_surface"}) is False
    assert services.asset_matches_creator({"id": "asset_surface"}, "Stacey") is True
    assert services.asset_components("asset_surface") == [{"asset_id": "asset_surface", "component_index": 0}]

    assert calls == [
        ("surface_handoff_readiness_report", (), {
            "creator": "Stacey",
            "campaign_slug": "may",
            "rendered_asset_id": "asset_surface",
        }),
        ("surface_draft_proof", (), {
            "creator": "Stacey",
            "campaign": "may",
            "rendered_asset_id": "asset_surface",
        }),
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


def test_campaign_factory_delegates_creator_os_execution_readiness_to_services() -> None:
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
    assert calls == [(
        "creator_os_execution_readiness",
        {
            "creator": "Stacey",
            "requested_count": 2,
            "threadsdash_report": {"schema": "threadsdash.report.v1"},
            "schedule_plan": {"schema": "creator_os.schedule_plan.v1"},
            "time_plan": {"schema": "creator_os.time_plan.v1"},
            "generated_at": "2026-06-06T12:00:00Z",
        },
    )]


def test_core_services_delegates_creator_os_execution_readiness_to_repository(tmp_path) -> None:
    factory = CampaignFactory(Settings(
        root=tmp_path,
        db_path=tmp_path / "campaign_factory.sqlite",
        reel_factory_root=tmp_path / "reel_factory",
        contentforge_root=tmp_path / "contentforge",
        threadsdash_root=tmp_path / "ThreadsDashboard",
        campaigns_dir=tmp_path / "campaigns",
    ))
    calls = []

    try:
        def fake_execution_readiness(**kwargs):
            calls.append(("creator_os_execution_readiness", kwargs))
            return {"schema": "creator_os.execution_readiness.v1", "ok": True}

        factory.services.execution_readiness.creator_os_execution_readiness = fake_execution_readiness

        assert factory.services.creator_os_execution_readiness(
            creator="Stacey",
            requested_count=2,
            threadsdash_report={"schema": "threadsdash.report.v1"},
            schedule_plan={"schema": "creator_os.schedule_plan.v1"},
            time_plan={"schema": "creator_os.time_plan.v1"},
            generated_at="2026-06-06T12:00:00Z",
        ) == {"schema": "creator_os.execution_readiness.v1", "ok": True}
        assert calls == [(
            "creator_os_execution_readiness",
            {
                "creator": "Stacey",
                "requested_count": 2,
                "threadsdash_report": {"schema": "threadsdash.report.v1"},
                "schedule_plan": {"schema": "creator_os.schedule_plan.v1"},
                "time_plan": {"schema": "creator_os.time_plan.v1"},
                "generated_at": "2026-06-06T12:00:00Z",
            },
        )]
    finally:
        factory.close()


def test_campaign_factory_delegates_creator_os_200_account_acceptance_suite_to_services() -> None:
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
    assert calls == [(
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
    )]


def test_core_services_delegates_creator_os_200_account_acceptance_suite_to_repository(tmp_path) -> None:
    factory = CampaignFactory(Settings(
        root=tmp_path,
        db_path=tmp_path / "campaign_factory.sqlite",
        reel_factory_root=tmp_path / "reel_factory",
        contentforge_root=tmp_path / "contentforge",
        threadsdash_root=tmp_path / "ThreadsDashboard",
        campaigns_dir=tmp_path / "campaigns",
    ))
    calls = []

    try:
        def fake_acceptance_suite(**kwargs):
            calls.append(("creator_os_200_account_acceptance_suite", kwargs))
            return {"schema": "creator_os.200_account_acceptance_suite.v1", "ok": True}

        factory.services.acceptance_suite.creator_os_200_account_acceptance_suite = fake_acceptance_suite

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
        assert calls == [(
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
        )]
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

    assert factory.creator_os_100_account_proof() == {"schema": "creator_os.100_account_proof.v1"}
    assert factory.creator_os_volume_acceptance_suite() == {"schema": "creator_os.volume_acceptance_suite.v1"}
    assert factory.surface_readiness_scorecard() == {"schema": "creator_os.surface_readiness_scorecard.v1"}
    assert factory.creator_os_10_0_readiness_report() == {"schema": "creator_os.10_0_readiness_report.v1"}
    assert factory.creator_os_9_5_readiness_report() == {"schema": "creator_os.9_5_readiness_report.v1"}
    assert calls == [
        ("creator_os_100_account_proof", (), {}),
        ("creator_os_volume_acceptance_suite", (), {}),
        ("surface_readiness_scorecard", (), {}),
        ("creator_os_10_0_readiness_report", (), {}),
        ("creator_os_9_5_readiness_report", (), {}),
    ]


def test_core_services_delegates_readiness_report_methods_to_repository(tmp_path) -> None:
    factory = CampaignFactory(Settings(
        root=tmp_path,
        db_path=tmp_path / "campaign_factory.sqlite",
        reel_factory_root=tmp_path / "reel_factory",
        contentforge_root=tmp_path / "contentforge",
        threadsdash_root=tmp_path / "ThreadsDashboard",
        campaigns_dir=tmp_path / "campaigns",
    ))
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

        assert factory.services.creator_os_100_account_proof() == {"schema": "creator_os.100_account_proof.v1"}
        assert factory.services.creator_os_volume_acceptance_suite() == {"schema": "creator_os.volume_acceptance_suite.v1"}
        assert factory.services.surface_readiness_scorecard() == {"schema": "creator_os.surface_readiness_scorecard.v1"}
        assert factory.services.creator_os_10_0_readiness_report() == {"schema": "creator_os.10_0_readiness_report.v1"}
        assert factory.services.creator_os_9_5_readiness_report() == {"schema": "creator_os.9_5_readiness_report.v1"}
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
            return {"totalAccounts": 100, "blockedAccounts": 0, "safeAccounts": 100, "warmingAccounts": 0}

        def live_100_exact_shortfall(self, **kwargs):
            calls.append(("live_100_exact_shortfall", (), kwargs))
            return "accounts:5"

    factory.services = FakeServices()

    assert factory.creator_os_live_100_account_readiness() == {"schema": "creator_os.live_100_account_readiness.v1"}
    assert factory.creator_os_live_scale_runbook() == {"schema": "creator_os.live_scale_runbook.v1"}
    assert factory.creator_os_live_scale_scorecard() == {"schema": "creator_os.live_scale_scorecard.v1"}
    assert factory._actual_account_operational_counts() == {
        "totalAccounts": 100,
        "blockedAccounts": 0,
        "safeAccounts": 100,
        "warmingAccounts": 0,
    }
    assert factory._live_100_exact_shortfall(
        accounts={"totalAccounts": 95, "blockedAccounts": 0},
        available_inventory=100,
        required_inventory=900,
        available_parents=20,
        required_parents=30,
    ) == "accounts:5"
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


def test_core_services_delegates_live_scale_report_methods_to_repository(tmp_path) -> None:
    factory = CampaignFactory(Settings(
        root=tmp_path,
        db_path=tmp_path / "campaign_factory.sqlite",
        reel_factory_root=tmp_path / "reel_factory",
        contentforge_root=tmp_path / "contentforge",
        threadsdash_root=tmp_path / "ThreadsDashboard",
        campaigns_dir=tmp_path / "campaigns",
    ))
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
                return {"totalAccounts": 100, "blockedAccounts": 0, "safeAccounts": 100, "warmingAccounts": 0}

            def live_100_exact_shortfall(self, **kwargs):
                calls.append(("live_100_exact_shortfall", (), kwargs))
                return "parent_inventory:10"

        factory.services.live_scale = FakeLiveScale()

        assert factory.services.creator_os_live_100_account_readiness() == {"schema": "creator_os.live_100_account_readiness.v1"}
        assert factory.services.creator_os_live_scale_runbook() == {"schema": "creator_os.live_scale_runbook.v1"}
        assert factory.services.creator_os_live_scale_scorecard() == {"schema": "creator_os.live_scale_scorecard.v1"}
        assert factory.services.actual_account_operational_counts() == {
            "totalAccounts": 100,
            "blockedAccounts": 0,
            "safeAccounts": 100,
            "warmingAccounts": 0,
        }
        assert factory.services.live_100_exact_shortfall(
            accounts={"totalAccounts": 100, "blockedAccounts": 0},
            available_inventory=900,
            required_inventory=900,
            available_parents=20,
            required_parents=30,
        ) == "parent_inventory:10"
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


def test_campaign_factory_delegates_live_account_acceptance_methods_to_services() -> None:
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

    assert factory.creator_os_live_account_acceptance(account_target=10, content_surface="reel") == {
        "schema": "creator_os.live_account_acceptance.v1",
    }
    assert factory.creator_os_staged_live_acceptance(stages=[10], content_surface="reel") == {
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
    assert factory._live_acceptance_restricted_scheduled({"restrictedAccountsScheduled": 3}) == 3
    assert factory._live_acceptance_surface_contract_violations({"surfaceContractViolations": 4}) == 4
    assert factory._live_acceptance_metrics_imported() is True
    assert factory._live_acceptance_blocker_for("metricsImported") == "metrics_not_imported"

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
        ("live_acceptance_restricted_scheduled", ({"restrictedAccountsScheduled": 3},), {}),
        ("live_acceptance_surface_contract_violations", ({"surfaceContractViolations": 4},), {}),
        ("live_acceptance_metrics_imported", (), {}),
        ("live_acceptance_blocker_for", ("metricsImported",), {}),
    ]


def test_core_services_delegates_live_account_acceptance_methods_to_repository(tmp_path) -> None:
    factory = CampaignFactory(Settings(
        root=tmp_path,
        db_path=tmp_path / "campaign_factory.sqlite",
        reel_factory_root=tmp_path / "reel_factory",
        contentforge_root=tmp_path / "contentforge",
        threadsdash_root=tmp_path / "ThreadsDashboard",
        campaigns_dir=tmp_path / "campaigns",
    ))
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
                calls.append(("live_acceptance_surface_contract_violations", (report,), {}))
                return 4

            def live_acceptance_metrics_imported(self):
                calls.append(("live_acceptance_metrics_imported", (), {}))
                return True

            def live_acceptance_blocker_for(self, key):
                calls.append(("live_acceptance_blocker_for", (key,), {}))
                return "metrics_not_imported"

        factory.services.live_acceptance = FakeLiveAcceptance()

        assert factory.services.creator_os_live_account_acceptance(account_target=10, content_surface="feed_single") == {
            "schema": "creator_os.live_account_acceptance.v1",
        }
        assert factory.services.creator_os_staged_live_acceptance(stages=[10], content_surface="feed_single") == {
            "schema": "creator_os.staged_live_acceptance.v1",
        }
        assert factory.services.live_acceptance_actuals(
            account_target=10,
            threadsdash_report={},
            required_inventory=30,
            available_inventory=20,
            exception_count=1,
        ) == {"metricsImported": True}
        assert factory.services.live_acceptance_missed_dispatches({"missedDispatchCount": 1}) == 1
        assert factory.services.live_acceptance_duplicate_publishes({"duplicatePublishes": 2}) == 2
        assert factory.services.live_acceptance_restricted_scheduled({"restrictedAccountsScheduled": 3}) == 3
        assert factory.services.live_acceptance_surface_contract_violations({"surfaceContractViolations": 4}) == 4
        assert factory.services.live_acceptance_metrics_imported() is True
        assert factory.services.live_acceptance_blocker_for("metricsImported") == "metrics_not_imported"

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
                {"stages": [10], "content_surface": "feed_single", "threadsdash_report": None},
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
            ("live_acceptance_restricted_scheduled", ({"restrictedAccountsScheduled": 3},), {}),
            ("live_acceptance_surface_contract_violations", ({"surfaceContractViolations": 4},), {}),
            ("live_acceptance_metrics_imported", (), {}),
            ("live_acceptance_blocker_for", ("metricsImported",), {}),
        ]
    finally:
        factory.close()


def test_campaign_factory_delegates_creator_os_certification_report_to_services() -> None:
    factory = object.__new__(CampaignFactory)
    calls = []

    class FakeServices:
        def creator_os_certification_report(self):
            calls.append(("creator_os_certification_report", (), {}))
            return {"schema": "creator_os.certification_report.v1"}

    factory.services = FakeServices()

    assert factory.creator_os_certification_report() == {"schema": "creator_os.certification_report.v1"}
    assert calls == [("creator_os_certification_report", (), {})]


def test_core_services_delegates_creator_os_certification_report_to_repository(tmp_path) -> None:
    factory = CampaignFactory(Settings(
        root=tmp_path,
        db_path=tmp_path / "campaign_factory.sqlite",
        reel_factory_root=tmp_path / "reel_factory",
        contentforge_root=tmp_path / "contentforge",
        threadsdash_root=tmp_path / "ThreadsDashboard",
        campaigns_dir=tmp_path / "campaigns",
    ))
    calls = []

    try:
        class FakeCertification:
            conn = factory.conn

            def creator_os_certification_report(self):
                calls.append(("creator_os_certification_report", (), {}))
                return {"schema": "creator_os.certification_report.v1"}

        factory.services.certification = FakeCertification()

        assert factory.services.creator_os_certification_report() == {"schema": "creator_os.certification_report.v1"}
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

    assert factory.failure_injection_suite() == {"schema": "creator_os.failure_injection_suite.v1"}
    assert factory.idempotency_proof() == {"schema": "creator_os.idempotency_proof.v1"}
    assert factory.surface_maturity_audit() == {"schema": "creator_os.surface_maturity_audit.v1"}
    assert factory.operator_load_audit() == {"schema": "creator_os.operator_load_audit.v1"}
    assert factory._idempotency_evidence_for_path("schedule") == "evidence:schedule"
    assert calls == [
        ("failure_injection_suite", (), {}),
        ("idempotency_proof", (), {}),
        ("surface_maturity_audit", (), {}),
        ("operator_load_audit", (), {}),
        ("idempotency_evidence_for_path", ("schedule",), {}),
    ]


def test_core_services_delegates_operational_proof_methods_to_repository(tmp_path) -> None:
    factory = CampaignFactory(Settings(
        root=tmp_path,
        db_path=tmp_path / "campaign_factory.sqlite",
        reel_factory_root=tmp_path / "reel_factory",
        contentforge_root=tmp_path / "contentforge",
        threadsdash_root=tmp_path / "ThreadsDashboard",
        campaigns_dir=tmp_path / "campaigns",
    ))
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

        assert factory.services.failure_injection_suite() == {"schema": "creator_os.failure_injection_suite.v1"}
        assert factory.services.idempotency_proof() == {"schema": "creator_os.idempotency_proof.v1"}
        assert factory.services.surface_maturity_audit() == {"schema": "creator_os.surface_maturity_audit.v1"}
        assert factory.services.operator_load_audit() == {"schema": "creator_os.operator_load_audit.v1"}
        assert factory.services.idempotency_evidence_for_path("schedule") == "evidence:schedule"
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

    assert factory.single_source_of_truth_audit() == {"schema": "creator_os.single_source_of_truth_audit.v1"}
    assert factory.core_complexity_reduction_plan() == {"schema": "creator_os.core_complexity_reduction_plan.v1"}
    assert factory._largest_project_files() == [{"file": "campaign_factory/core.py", "lines": 1, "risk": "low"}]
    assert calls == [
        ("single_source_of_truth_audit", (), {}),
        ("core_complexity_reduction_plan", (), {}),
        ("largest_project_files", (), {}),
    ]


def test_core_services_delegates_core_complexity_methods_to_repository(tmp_path) -> None:
    factory = CampaignFactory(Settings(
        root=tmp_path,
        db_path=tmp_path / "campaign_factory.sqlite",
        reel_factory_root=tmp_path / "reel_factory",
        contentforge_root=tmp_path / "contentforge",
        threadsdash_root=tmp_path / "ThreadsDashboard",
        campaigns_dir=tmp_path / "campaigns",
    ))
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

        assert factory.services.single_source_of_truth_audit() == {"schema": "creator_os.single_source_of_truth_audit.v1"}
        assert factory.services.core_complexity_reduction_plan() == {"schema": "creator_os.core_complexity_reduction_plan.v1"}
        assert factory.services.largest_project_files() == [{"file": "campaign_factory/core.py", "lines": 1, "risk": "low"}]
        assert calls == [
            ("single_source_of_truth_audit", (), {}),
            ("core_complexity_reduction_plan", (), {}),
            ("largest_project_files", (), {}),
        ]
    finally:
        factory.close()


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
            return {"schema": "creator_os.operator_review_simulator.v1", "reviewBatch": []}

        def operator_review_scenarios(self, *args, **kwargs):
            calls.append(("operator_review_scenarios", args, kwargs))
            return {"schema": "creator_os.operator_review_scenarios.v1"}

        def operator_review_efficiency_report(self, *args, **kwargs):
            calls.append(("operator_review_efficiency_report", args, kwargs))
            return {"schema": "creator_os.operator_review_efficiency_report.v1"}

        def operator_review_minimum_certification_path(self, *args, **kwargs):
            calls.append(("operator_review_minimum_certification_path", args, kwargs))
            return {"schema": "creator_os.operator_review_minimum_certification_path.v1"}

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

    assert factory.operator_inventory_review_batch_plan(creator="Test")["schema"] == "creator_os.operator_inventory_review_batch_plan.v1"
    assert factory.operator_inventory_review_batch_summary(creator="Test")["schema"] == "creator_os.operator_inventory_review_batch_summary.v1"
    assert factory.operator_review_simulator(creator="Test")["schema"] == "creator_os.operator_review_simulator.v1"
    assert factory.operator_review_scenarios(creator="Test")["schema"] == "creator_os.operator_review_scenarios.v1"
    assert factory.operator_review_efficiency_report(creator="Test")["schema"] == "creator_os.operator_review_efficiency_report.v1"
    assert factory.operator_review_minimum_certification_path(creator="Test")["schema"] == "creator_os.operator_review_minimum_certification_path.v1"
    assert factory.operator_review_master_report(creator="Test")["schema"] == "creator_os.operator_review_master_report.v1"
    assert factory._operator_review_execution_order([{"assetId": "asset_1"}]) == [{"assetId": "asset_1"}]
    assert factory._operator_review_batch_priority(["discoverability_failure"]) == 1
    assert factory._operator_review_batch_type(["instagram_post_caption_quality_failed"]) == "caption_only"
    assert factory._operator_review_scenario([], current_inventory=0, required_inventory=1, approval_rate=50) == {"approvalRate": 50}
    assert factory._operator_review_minimum_path([], current_inventory=0, required_inventory=1) == {"minimumAssetsReviewedToPass25Gate": 1}
    assert factory._operator_review_highest_roi_batch_type([]) == "caption_only"
    assert factory._operator_review_lowest_risk_batch_type([]) == "caption_only"
    assert factory._operator_review_batch_order_labels([]) == ["caption_only"]
    assert factory._operator_review_candidate_eligible({"assetId": "asset_1"}) is True
    assert factory._operator_review_candidate_row({"assetId": "asset_1"}) == {"assetId": "asset_1"}
    assert factory._operator_review_actions(["operator_visual_review_required"]) == ["operator_visual_review"]

    assert calls == [
        ("operator_inventory_review_batch_plan", (), {
            "creator": "Test",
            "campaign_slug": None,
            "content_surface": "reel",
            "required_inventory": 225,
            "current_inventory": None,
            "target_unlock": None,
            "max_batch_size": None,
        }),
        ("operator_inventory_review_batch_summary", (), {"creator": "Test"}),
        ("operator_review_simulator", (), {
            "creator": "Test",
            "campaign_slug": None,
            "content_surface": "reel",
            "required_inventory": 225,
            "current_inventory": None,
            "approval_rates": None,
        }),
        ("operator_review_scenarios", (), {"creator": "Test"}),
        ("operator_review_efficiency_report", (), {"creator": "Test"}),
        ("operator_review_minimum_certification_path", (), {"creator": "Test"}),
        ("operator_review_master_report", (), {"creator": "Test"}),
        ("operator_review_execution_order", ([{"assetId": "asset_1"}],), {}),
        ("operator_review_batch_priority", (["discoverability_failure"],), {}),
        ("operator_review_batch_type", (["instagram_post_caption_quality_failed"],), {}),
        ("operator_review_scenario", ([],), {
            "current_inventory": 0,
            "required_inventory": 1,
            "approval_rate": 50,
        }),
        ("operator_review_minimum_path", ([],), {"current_inventory": 0, "required_inventory": 1}),
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
            return {"schema": "creator_os.operator_review_minimum_certification_path.v1"}

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

    assert services.operator_inventory_review_batch_plan(creator="Test")["schema"] == "creator_os.operator_inventory_review_batch_plan.v1"
    assert services.operator_inventory_review_batch_summary(creator="Test")["schema"] == "creator_os.operator_inventory_review_batch_summary.v1"
    assert services.operator_review_simulator(creator="Test")["schema"] == "creator_os.operator_review_simulator.v1"
    assert services.operator_review_scenarios(creator="Test")["schema"] == "creator_os.operator_review_scenarios.v1"
    assert services.operator_review_efficiency_report(creator="Test")["schema"] == "creator_os.operator_review_efficiency_report.v1"
    assert services.operator_review_minimum_certification_path(creator="Test")["schema"] == "creator_os.operator_review_minimum_certification_path.v1"
    assert services.operator_review_master_report(creator="Test")["schema"] == "creator_os.operator_review_master_report.v1"
    assert services.operator_review_execution_order([]) == []
    assert services.operator_review_batch_priority(["discoverability_failure"]) == 1
    assert services.operator_review_batch_type(["instagram_post_caption_quality_failed"]) == "caption_only"
    assert services.operator_review_scenario([], current_inventory=0, required_inventory=1, approval_rate=75) == {"approvalRate": 75}
    assert services.operator_review_minimum_path([], current_inventory=0, required_inventory=1) == {}
    assert services.operator_review_highest_roi_batch_type([]) == "caption_only"
    assert services.operator_review_lowest_risk_batch_type([]) == "caption_only"
    assert services.operator_review_batch_order_labels([]) == ["caption_only"]
    assert services.operator_review_candidate_eligible({"assetId": "asset_1"}) is True
    assert services.operator_review_candidate_row({"assetId": "asset_1"}) == {"assetId": "asset_1"}
    assert services.operator_review_actions(["operator_visual_review_required"]) == ["operator_visual_review"]

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
        ("operator_review_batch_type", (["instagram_post_caption_quality_failed"],), {}),
        ("operator_review_scenario", ([],), {
            "current_inventory": 0,
            "required_inventory": 1,
            "approval_rate": 75,
        }),
        ("operator_review_minimum_path", ([],), {"current_inventory": 0, "required_inventory": 1}),
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

    assert factory.story_inventory_report(creator="Stacey")["schema"] == "campaign_factory.story_inventory_report.v1"
    assert factory.story_intent_report(creator="Stacey")["schema"] == "campaign_factory.story_intent_report.v1"
    assert factory.story_mix_plan(creator="Stacey")["schema"] == "campaign_factory.story_mix_plan.v1"
    assert factory.story_calendar_plan(creator="Stacey")["schema"] == "campaign_factory.story_calendar_plan.v1"
    assert factory.story_intent_summary(creator="Stacey")["schema"] == "campaign_factory.story_intent_summary.v1"
    assert factory._story_metadata_payload({"id": "asset_1"}) == {"storyIntent": "reel_teaser"}
    assert factory._story_intent_value({"id": "asset_1"}) == "reel_teaser"
    assert factory._story_goal_value({"id": "asset_1"}) == "reel_support"
    assert factory._story_style_value({"id": "asset_1"}) == "raw_phone"
    assert factory._normalize_story_enum("Reel Teaser", {"reel_teaser"}) == "reel_teaser"
    assert factory.story_quality_gate_v1("asset_1")["schema"] == "campaign_factory.story_quality_gate_v1"
    assert factory.story_quality_report(creator="Stacey")["schema"] == "campaign_factory.story_quality_report.v1"
    assert factory._story_quality_gate_for_asset({"id": "asset_1"}) == {"storyQualityGatePassed": True}
    assert factory._story_quality_metadata({"id": "asset_1"}) == {"storySafeZoneScore": 100}
    assert factory._bounded_score("95", default=100) == 95
    assert factory._story_black_bar_check(Path("/tmp/story.png"), media_type="image") == {"blackBarsDetected": False}
    assert factory._story_no_text_check(Path("/tmp/story.png"), media_type="image", quality={}) == {"required": False, "passed": True}
    assert factory._story_ocr_frame_paths(Path("/tmp/story.mp4"), media_type="video") == [Path("/tmp/frame.png")]
    assert factory._story_ocr_detect_text(Path("/tmp/frame.png"), frame_index=0) == []
    assert factory._pixel_region_black([], x0=0, x1=1, y0=0, y1=1) is False
    assert factory.story_gap_report(creator="Stacey", date="2026-06-06")["schema"] == "campaign_factory.story_gap_report.v1"
    assert factory.account_story_status(account_id="acct_1", creator="Stacey", date="2026-06-06")["schema"] == "campaign_factory.account_story_status.v1"
    assert factory.creator_story_summary(creator="Stacey", date="2026-06-06")["schema"] == "campaign_factory.creator_story_summary.v1"
    assert factory.story_certification_proof(rendered_asset_id="asset_1")["schema"] == "creator_os.story_certification_proof.v1"
    assert factory.story_production_readiness()["schema"] == "creator_os.story_production_readiness.v1"
    assert factory.story_proof_gap_analysis()["schema"] == "creator_os.story_proof_gap_analysis.v1"
    assert factory._story_source_blockers([{"path": "/campaign_factory/02_rendered/story.png"}]) == ["story_source_must_be_raw_not_rendered_reel_asset"]
    assert factory._story_existing_asset_source_blockers({"id": "asset_1"}) == ["story_source_must_be_raw_not_approved_reel_asset"]

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
        ("story_no_text_check", (Path("/tmp/story.png"),), {"media_type": "image", "quality": {}}),
        ("story_ocr_frame_paths", (Path("/tmp/story.mp4"),), {"media_type": "video"}),
        ("story_ocr_detect_text", (Path("/tmp/frame.png"),), {"frame_index": 0}),
        ("pixel_region_black", ([],), {"x0": 0, "x1": 1, "y0": 0, "y1": 1}),
        ("story_gap_report", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("account_story_status", (), {"account_id": "acct_1", "creator": "Stacey", "date": "2026-06-06"}),
        ("creator_story_summary", (), {"creator": "Stacey", "date": "2026-06-06"}),
        ("story_certification_proof", (), {"rendered_asset_id": "asset_1"}),
        ("story_production_readiness", (), {}),
        ("story_proof_gap_analysis", (), {}),
        ("story_source_blockers", ([{"path": "/campaign_factory/02_rendered/story.png"}],), {}),
        ("story_existing_asset_source_blockers", ({"id": "asset_1"},), {}),
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
            return {"warming": 1, "normal": 0, "growth": 0, "winner": 0, "resting": 0, "blocked": 0}

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

    assert factory.creator_os_account_tiers(creator="Stacey")["schema"] == "creator_os.account_tiers.v1"
    assert factory.creator_os_account_health_report(creator="Stacey")["schema"] == "creator_os.account_health_report.v1"
    assert factory.creator_os_restricted_account_report(creator="Stacey")["schema"] == "creator_os.restricted_account_report.v1"
    assert factory.creator_os_manual_review_queue(creator="Stacey")["schema"] == "creator_os.manual_review_queue.v1"
    assert factory.creator_os_account_warmup_report(creator="Stacey")["schema"] == "creator_os.account_warmup_report.v1"
    assert factory._creator_os_execution_account_health_blockers({"accounts": []}) == ["account_link_sharing_restricted"]
    assert factory._creator_os_execution_account_health_warnings({"accounts": []}) == ["recommendation_eligibility_unknown_conservative_cadence"]
    assert factory._creator_os_account_tier_summary([{"accountTier": "warming"}])["warming"] == 1
    assert factory._creator_os_account_health_decision({"accountId": "ig_1"}, missed=[]) == {"accountId": "ig_1", "safeToSchedule": False}
    assert factory._creator_os_account_health_summary([{"safeToSchedule": False}]) == {"accounts": 1}
    assert factory._creator_os_recommendation_eligibility({"recommendationEligible": True}) == "eligible"
    assert factory._creator_os_restriction_status({}) == {"active": False}
    assert factory._creator_os_maturity_score({"accountAgeDays": 30}) == 60
    assert factory._creator_os_warming_stage({}, maturity_score=60) == "mature"
    assert factory._creator_os_creative_risk({}) == {"creativeRiskScore": 0}
    assert factory._creator_os_similarity_budget({}) == {"blocked": False}
    assert factory._creator_os_account_tier_from_health({}, trust_state="normal", maturity_score=60) == "normal"
    assert factory._creator_os_cadence_overrides({}, warming_stage="mature", maturity_score=60) == {"maxPostsPerDay": 1}
    assert factory._creator_os_account_over_cadence({}, {"maxPostsPerDay": 1}) is False
    assert factory._creator_os_account_tier({}, state="safe", blocked_reason="") == "normal"
    assert factory._creator_os_numeric("3") == 3.0
    assert factory._creator_os_tier_posting_guidance("normal") == {"recommendedPostCount": 1}

    assert calls == [
        ("creator_os_account_tiers", (), {"creator": "Stacey", "threadsdash_report": None, "generated_at": None}),
        ("creator_os_account_health_report", (), {"creator": "Stacey", "threadsdash_report": None, "generated_at": None}),
        ("creator_os_restricted_account_report", (), {"creator": "Stacey", "threadsdash_report": None, "generated_at": None}),
        ("creator_os_manual_review_queue", (), {"creator": "Stacey", "threadsdash_report": None, "generated_at": None}),
        ("creator_os_account_warmup_report", (), {"creator": "Stacey", "threadsdash_report": None, "generated_at": None}),
        ("creator_os_execution_account_health_blockers", ({"accounts": []},), {}),
        ("creator_os_execution_account_health_warnings", ({"accounts": []},), {}),
        ("creator_os_account_tier_summary", ([{"accountTier": "warming"}],), {"key": "accountTier"}),
        ("creator_os_account_health_decision", ({"accountId": "ig_1"},), {"missed": []}),
        ("creator_os_account_health_summary", ([{"safeToSchedule": False}],), {}),
        ("creator_os_recommendation_eligibility", ({"recommendationEligible": True},), {}),
        ("creator_os_restriction_status", ({},), {}),
        ("creator_os_maturity_score", ({"accountAgeDays": 30},), {}),
        ("creator_os_warming_stage", ({},), {"maturity_score": 60}),
        ("creator_os_creative_risk", ({},), {}),
        ("creator_os_similarity_budget", ({},), {}),
        ("creator_os_account_tier_from_health", ({},), {"trust_state": "normal", "maturity_score": 60}),
        ("creator_os_cadence_overrides", ({},), {"warming_stage": "mature", "maturity_score": 60}),
        ("creator_os_account_over_cadence", ({}, {"maxPostsPerDay": 1}), {}),
        ("creator_os_account_tier", ({},), {"state": "safe", "blocked_reason": ""}),
        ("creator_os_numeric", ("3",), {}),
        ("creator_os_tier_posting_guidance", ("normal",), {}),
    ]
