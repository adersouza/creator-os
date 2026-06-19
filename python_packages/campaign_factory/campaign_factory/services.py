from __future__ import annotations

import sqlite3
from typing import Any, Callable

from .acceptance_suite import AcceptanceSuiteRepository
from .account_health import AccountHealthRepository
from .account_memory import AccountMemoryRepository
from .asset_import import AssetImportRepository
from .autonomy import AutonomyPolicyRepository
from .caption import CaptionFamilyRepository
from .carousel_integrity import CarouselIntegrityRepository
from .campaign_overview import CampaignOverviewRepository
from .certification import CertificationRepository
from .config import Settings
from .core_complexity import CoreComplexityRepository
from .creative_knowledge import CreativeKnowledgeRepository
from .creative_planning import CreativePlanningRepository
from .decision_ledger import DecisionLedgerRepository
from .discoverability import DiscoverabilityRepository
from .distribution import DistributionRepository
from .daily_plan import DailyPlanRepository
from .draft_inventory_gap import DraftInventoryGapRepository
from .events import EventRepository
from .execution_readiness import ExecutionReadinessRepository
from .exceptions import ExceptionRepository
from .graph import GraphRepository
from .live_acceptance import LiveAcceptanceRepository
from .live_scale import LiveScaleRepository
from .models import ModelRepository
from .operational_proofs import OperationalProofRepository
from .operator_review import OperatorReviewRepository
from .reference import ReferenceRepository
from .recommendation_accuracy import RecommendationAccuracyRepository
from .readiness_report import ReadinessReportRepository
from .story_management import StoryManagementRepository
from .surface_handoff import SurfaceHandoffRepository
from .surface_inventory import SurfaceInventoryRepository
from .surface_requirements import SurfaceRequirementsRepository
from .surface_registration import SurfaceRegistrationRepository
from .surface_summary import SurfaceSummaryRepository
from .tribev2 import TribeV2Repository
from .winner_expansion import WinnerExpansionRepository


class CoreServices:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        new_id: Callable[[str], str],
        new_graph_id: Callable[[str], str],
        slugify: Callable[[str], str],
        sanitize_for_storage: Callable[[Any], Any],
        utc_now: Callable[[], str],
        media_type_for_path: Callable[[Any], str],
        sha256_file: Callable[[Any], str],
        probe_image_shape: Callable[[Any], dict[str, Any]],
        probe_video_shape: Callable[[Any], dict[str, Any]],
        read_png_rgb_pixels: Callable[[Any], dict[str, Any]],
        ratio_label_from_shape: Callable[[int | None, int | None], str | None],
        rendered_for_campaign: Callable[[str], list[dict[str, Any]]],
        dashboard_rendered_asset: Callable[[dict[str, Any]], dict[str, Any]],
        prepare_reel_inputs: Callable[..., dict[str, Any]],
        discoverability_safe_content_contract: Callable[..., dict[str, Any]],
        reference_hook_fallbacks: tuple[str, ...],
        normalize_content_surface: Callable[[str | None], str],
        campaign_dirs: Callable[[str, str], dict[str, Any]],
        concept_for_parent_asset: Callable[[str], dict[str, Any] | None],
        explain_publishability: Callable[[str], dict[str, Any]],
        surface_handoff_readiness_report: Callable[..., dict[str, Any]],
        surface_handoff_readiness_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        surface_report_assets: Callable[..., list[dict[str, Any]]],
        build_surface_readiness: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        asset_matches_creator: Callable[[dict[str, Any], str], bool],
        latest_audit_for_asset: Callable[[str], dict[str, Any] | None],
        reservation_adjusted_inventory: Callable[..., dict[str, int]],
        surface_draft_proof: Callable[..., dict[str, Any]],
        asset_components: Callable[[str], list[dict[str, Any]]],
        instagram_post_caption_for_asset: Callable[..., dict[str, Any]],
        text_hash: Callable[[str], str],
        validate_instagram_trial_reel_intent: Callable[..., str | None],
        variant_lineage_for_asset: Callable[[str], dict[str, Any]],
        story_quality_gate_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        story_style_value: Callable[[dict[str, Any]], str | None],
        story_intent_value: Callable[[dict[str, Any]], str | None],
        ranking: Callable[[str], dict[str, Any]],
        dashboard: Callable[[str], dict[str, Any]],
        creator_label: Callable[[Any], str],
        creator_os_draft_items: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        creator_os_local_schedule_safe_assets: Callable[[str], list[dict[str, Any]]],
        creator_os_schedule_safe_drafts: Callable[[str, list[dict[str, Any]]], list[dict[str, Any]]],
        creator_os_draft_exclusion_reason: Callable[[dict[str, Any]], str | None],
        creator_os_execution_draft_blockers: Callable[[str, list[dict[str, Any]]], list[str]],
        creator_os_gap_blocking_reason: Callable[[str | None, list[str], dict[str, Any]], str],
        creator_os_account_health_report: Callable[..., dict[str, Any]],
        creator_os_account_health_decision: Callable[..., dict[str, Any]],
        creator_os_tier_posting_guidance: Callable[[str], dict[str, Any]],
        creator_os_account_surface_status: Callable[..., dict[str, Any]],
        creator_os_draft_has_instagram_post_caption: Callable[[dict[str, Any]], bool],
        creator_os_post_time: Callable[[Any], str | None],
        creator_os_recommended_post_count: Callable[[str, bool], int],
        creator_os_account_tier_summary: Callable[[list[dict[str, Any]]], dict[str, Any]],
        creator_os_account_health_summary: Callable[[list[dict[str, Any]]], dict[str, Any]],
        creator_os_surface_summary_for_creator: Callable[..., dict[str, Any]],
        creator_os_inventory_for_creator: Callable[..., dict[str, Any]],
        creator_os_draft_exclusion_counts: Callable[[str, list[dict[str, Any]]], dict[str, int]],
        creator_os_winner_recommendations: Callable[..., list[dict[str, Any]]],
        creator_os_manager_decision: Callable[..., dict[str, Any]],
        creator_os_blocked_account_breakdown: Callable[[list[dict[str, Any]]], dict[str, int]],
        creator_os_recommended_inventory: Callable[..., list[dict[str, Any]]],
        build_creative_knowledge_base: Callable[..., dict[str, Any]],
        creative_knowledge_rows: Callable[..., list[dict[str, Any]]],
        creative_knowledge_result: Callable[[dict[str, Any]], dict[str, Any]],
        creator_os_target_date: Callable[..., str],
        creator_os_daily_plan: Callable[..., dict[str, Any]],
        creator_os_execution_readiness: Callable[..., dict[str, Any]],
        inventory_slo_report: Callable[..., dict[str, Any]],
        exception_queue_priority_report: Callable[[], dict[str, Any]],
        parent_factory_autopilot_plan: Callable[..., dict[str, Any]],
        inventory_autopilot_plan: Callable[..., dict[str, Any]],
        inventory_stage_counts: Callable[[], dict[str, int]],
        inventory_production_requirements: Callable[..., dict[str, Any]],
        exception_queue_report: Callable[[], dict[str, Any]],
        reel_factory_parent_metrics: Callable[[], dict[str, Any]],
        parent_factory_production_scorecard: Callable[[], dict[str, Any]],
        build_surface_inventory: Callable[..., dict[str, Any]],
        truthy: Callable[[Any], bool],
        surface_readiness_scorecard: Callable[[], dict[str, Any]],
        certification_asset_for_surface: Callable[..., dict[str, Any] | None],
        latest_proof_run_for_asset: Callable[[str], dict[str, Any] | None],
        latest_surface_metric_for_asset: Callable[[str, str], dict[str, Any] | None],
        empty_surface_certification_audit: Callable[[str], dict[str, Any]],
        surface_certification_audit: Callable[..., dict[str, Any]],
        performance_snapshot_payload: Callable[[dict[str, Any]], dict[str, Any]],
        account_reward_baselines: Callable[[list[dict[str, Any]]], dict[str, float]],
        aggregate_performance: Callable[..., dict[str, Any]],
        performance_quality_score: Callable[[dict[str, Any]], int | None],
        audio_selection_payload: Callable[[str], dict[str, Any]],
        audio_workflow_summary: Callable[[list[dict[str, Any]]], dict[str, Any]],
        events_for_asset: Callable[..., list[dict[str, Any]]],
        performance_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        audit_report_payload: Callable[[dict[str, Any]], dict[str, Any]],
        recommended_story_intent_for_date: Callable[..., str],
        recommended_story_style_for_intent: Callable[[str], str],
        story_mix_plan: Callable[..., dict[str, Any]],
        story_calendar_plan: Callable[..., dict[str, Any]],
        json_load: Callable[[Any, Any], Any],
        parent_factory_yield_waterfall: Callable[..., dict[str, Any]],
        ratio: Callable[[Any, Any], float],
        score_fraction: Callable[[Any, Any], float],
        wilson_lower_bound: Callable[..., float],
        story_source_blockers: Callable[[list[dict[str, Any]]], list[str]],
        normalize_story_enum: Callable[[Any, set[str]], str | None],
        story_intents: set[str],
        story_goals: set[str],
        story_styles: set[str],
        story_native_proof_styles: set[str],
        default_story_mix: dict[str, int],
        default_story_calendar: dict[str, str],
        ig_media_type_by_surface: dict[str, str],
        image_exts: set[str],
        video_exts: set[str],
        autonomy_levels: set[str],
        default_autonomy_level: str,
        recommendation_proof_summary: Callable[[str], dict[str, Any]],
        multi_blocker_inventory_unlock_report: Callable[..., dict[str, Any]],
        multi_blocker_repair_minutes: dict[str, int],
        account_trust_states: set[str],
        recommendation_eligibility_states: set[str],
        warming_stages: set[str],
        content_surfaces: tuple[str, ...],
        creative_risk_block_threshold: int,
        creative_risk_caution_threshold: int,
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._new_id = new_id
        self._new_graph_id = new_graph_id
        self._slugify = slugify
        self._sanitize_for_storage = sanitize_for_storage
        self._utc_now = utc_now
        self.graph = GraphRepository(
            conn,
            new_id=new_id,
            new_graph_id=new_graph_id,
            slugify=slugify,
            sanitize_for_storage=sanitize_for_storage,
            utc_now=utc_now,
        )
        self.events = EventRepository(
            conn,
            new_id=new_id,
            slugify=slugify,
            sanitize_for_storage=sanitize_for_storage,
            utc_now=utc_now,
        )
        self.models = ModelRepository(
            conn,
            settings,
            new_id=new_id,
            slugify=slugify,
            utc_now=utc_now,
            ensure_graph_node=self.graph.ensure_graph_node,
            record_event=self.events.record_event,
        )
        self.asset_import = AssetImportRepository(
            conn,
            settings,
            new_id=new_id,
            slugify=slugify,
            utc_now=utc_now,
            media_type_for_path=media_type_for_path,
            sha256_file=sha256_file,
            upsert_model=self.models.upsert_model,
            upsert_campaign=self.models.upsert_campaign,
            upsert_account=self.models.upsert_account,
            create_pipeline_job=self.events.create_pipeline_job,
            start_pipeline_job=self.events.start_pipeline_job,
            finish_pipeline_job=self.events.finish_pipeline_job,
            fail_pipeline_job=self.events.fail_pipeline_job,
            record_event=self.events.record_event,
            ensure_graph_node=self.graph.ensure_graph_node,
            ensure_graph_edge=self.graph.ensure_graph_edge,
            graph_id_for=self.graph.graph_id_for,
        )
        self.creative_planning = CreativePlanningRepository(
            conn,
            new_id=new_id,
            slugify=slugify,
            sanitize_for_storage=sanitize_for_storage,
            utc_now=utc_now,
            ensure_graph_node=self.graph.ensure_graph_node,
            ensure_graph_edge=self.graph.ensure_graph_edge,
            graph_id_for=self.graph.graph_id_for,
            campaign_by_slug=self.campaign_by_slug,
            assets_for_campaign=self.asset_import.assets_for_campaign,
            rendered_for_campaign=rendered_for_campaign,
            dashboard_rendered_asset=dashboard_rendered_asset,
        )
        self.reference = ReferenceRepository(
            conn,
            settings,
            new_id=new_id,
            utc_now=utc_now,
            record_event=self.events.record_event,
            campaign_by_slug=self.campaign_by_slug,
            prepare_reel_inputs=prepare_reel_inputs,
            discoverability_safe_content_contract=discoverability_safe_content_contract,
            reference_hook_fallbacks=reference_hook_fallbacks,
        )
        self.caption_family = CaptionFamilyRepository(
            conn,
            utc_now=utc_now,
            normalize_content_surface=normalize_content_surface,
            rendered_asset=self.rendered_asset,
            concept_for_parent_asset=concept_for_parent_asset,
            explain_publishability=explain_publishability,
            surface_handoff_readiness_for_asset=surface_handoff_readiness_for_asset,
            instagram_post_caption_for_asset=instagram_post_caption_for_asset,
            text_hash=text_hash,
        )
        self.distribution = DistributionRepository(
            conn,
            new_id=new_id,
            sanitize_for_storage=sanitize_for_storage,
            utc_now=utc_now,
            normalize_content_surface=normalize_content_surface,
            rendered_asset=self.rendered_asset,
            campaign_by_slug=self.campaign_by_slug,
            record_event=self.events.record_event,
            create_pipeline_job=self.events.create_pipeline_job,
            start_pipeline_job=self.events.start_pipeline_job,
            finish_pipeline_job=self.events.finish_pipeline_job,
            fail_pipeline_job=self.events.fail_pipeline_job,
            rendered_for_campaign=rendered_for_campaign,
            dashboard_rendered_asset=dashboard_rendered_asset,
            validate_instagram_trial_reel_intent=validate_instagram_trial_reel_intent,
            variant_lineage_for_asset=variant_lineage_for_asset,
            ranking=ranking,
            dashboard=dashboard,
            model_account_profile=self.models.model_account_profile,
            account_compatible_with_model=self.models.account_compatible_with_model,
        )
        self.surface_inventory = SurfaceInventoryRepository(
            conn,
            slugify=slugify,
            creator_label=creator_label,
            normalize_content_surface=normalize_content_surface,
            surface_report_assets=surface_report_assets,
            build_surface_readiness=build_surface_readiness,
            build_surface_inventory_for_audit=build_surface_inventory,
            content_surfaces=content_surfaces,
        )
        self.surface_requirements = SurfaceRequirementsRepository(
            conn,
            creator_label=creator_label,
            normalize_content_surface=normalize_content_surface,
            multi_surface_inventory_audit=self.surface_inventory.multi_surface_inventory_audit,
            build_surface_inventory=build_surface_inventory,
            content_surfaces=content_surfaces,
        )
        self.decision_ledger = DecisionLedgerRepository(
            conn,
            sanitize_for_storage=sanitize_for_storage,
            utc_now=utc_now,
            creator_label=creator_label,
            creator_os_target_date=creator_os_target_date,
            creator_os_daily_plan=creator_os_daily_plan,
            creator_content_needs=self.surface_requirements.creator_content_needs,
            recommended_story_intent_for_date=recommended_story_intent_for_date,
            recommended_story_style_for_intent=recommended_story_style_for_intent,
            story_mix_plan=story_mix_plan,
            story_calendar_plan=story_calendar_plan,
            normalize_content_surface=normalize_content_surface,
        )
        self.autonomy = AutonomyPolicyRepository(
            conn,
            autonomy_levels=autonomy_levels,
            default_autonomy_level=default_autonomy_level,
            json_load=json_load,
            utc_now=utc_now,
        )
        self.account_memory = AccountMemoryRepository(
            conn,
            utc_now=utc_now,
            json_load=json_load,
            sanitize_for_storage=sanitize_for_storage,
            campaign_by_slug=self.campaign_by_slug,
            graph_id_for=self.graph.graph_id_for,
            ensure_graph_node=self.graph.ensure_graph_node,
            ensure_graph_edge=self.graph.ensure_graph_edge,
            performance_snapshot_payload=performance_snapshot_payload,
            account_reward_baselines=account_reward_baselines,
            aggregate_performance=aggregate_performance,
            performance_quality_score=performance_quality_score,
        )
        self.recommendation_accuracy_repo = RecommendationAccuracyRepository(
            conn,
            utc_now=utc_now,
            json_load=json_load,
            sanitize_for_storage=sanitize_for_storage,
            campaign_by_slug=self.campaign_by_slug,
            graph_id_for=self.graph.graph_id_for,
            ensure_graph_node=self.graph.ensure_graph_node,
            ensure_graph_edge=self.graph.ensure_graph_edge,
            audio_selection_payload=audio_selection_payload,
        )
        self.campaign_overview = CampaignOverviewRepository(
            conn,
            new_id=new_id,
            utc_now=utc_now,
            campaign_by_slug=self.campaign_by_slug,
            assets_for_campaign=self.asset_import.assets_for_campaign,
            rendered_for_campaign=rendered_for_campaign,
            dashboard_rendered_asset=dashboard_rendered_asset,
            jobs_for_campaign=self.events.jobs_for_campaign,
            audio_workflow_summary=audio_workflow_summary,
            rendered_asset=self.rendered_asset,
            record_event=self.events.record_event,
            events_for_asset=events_for_asset,
            performance_for_asset=performance_for_asset,
            ranking=ranking,
            audit_report_payload=audit_report_payload,
        )
        self.exceptions = ExceptionRepository(
            conn,
            sanitize_for_storage=sanitize_for_storage,
            json_load=json_load,
            utc_now=utc_now,
            campaign_by_slug=self.campaign_by_slug,
            ensure_graph_node=self.graph.ensure_graph_node,
            ensure_graph_edge=self.graph.ensure_graph_edge,
            graph_id_for=self.graph.graph_id_for,
            autonomy_level=self.autonomy.autonomy_level,
            recommendation_proof_summary=recommendation_proof_summary,
        )
        self.discoverability = DiscoverabilityRepository(
            conn,
            json_load=json_load,
            parent_factory_yield_waterfall=parent_factory_yield_waterfall,
            ratio=ratio,
            score_fraction=score_fraction,
            wilson_lower_bound=wilson_lower_bound,
        )
        self.surface_handoff = SurfaceHandoffRepository(
            conn,
            slugify=slugify,
            creator_label=creator_label,
            media_type_for_path=media_type_for_path,
            normalize_content_surface=normalize_content_surface,
            discoverability_safe_content_contract=discoverability_safe_content_contract,
            explain_publishability=explain_publishability,
            latest_distribution_plan_for_asset=self.distribution.latest_distribution_plan_for_asset,
            latest_audit_for_asset=latest_audit_for_asset,
            instagram_post_caption_for_asset=instagram_post_caption_for_asset,
            variant_lineage_for_asset=variant_lineage_for_asset,
            story_quality_gate_for_asset=story_quality_gate_for_asset,
            story_style_value=story_style_value,
            story_intent_value=story_intent_value,
            truthy=truthy,
            story_native_proof_styles=story_native_proof_styles,
            ig_media_type_by_surface=ig_media_type_by_surface,
        )
        self.story_management = StoryManagementRepository(
            conn,
            creator_label=creator_label,
            slugify=slugify,
            json_load=json_load,
            normalize_content_surface=normalize_content_surface,
            media_type_for_path=media_type_for_path,
            probe_image_shape=probe_image_shape,
            probe_video_shape=probe_video_shape,
            read_png_rgb_pixels=read_png_rgb_pixels,
            rendered_asset=self.rendered_asset,
            build_surface_inventory=build_surface_inventory,
            surface_handoff_readiness_for_asset=surface_handoff_readiness_for_asset,
            account_content_needs=self.surface_requirements.account_content_needs,
            creator_content_needs=self.surface_requirements.creator_content_needs,
            last_surface_posted_at=self.surface_requirements.last_surface_posted_at,
            truthy=truthy,
            surface_readiness_scorecard=surface_readiness_scorecard,
            certification_asset_for_surface=certification_asset_for_surface,
            surface_draft_proof=surface_draft_proof,
            latest_proof_run_for_asset=latest_proof_run_for_asset,
            latest_surface_metric_for_asset=latest_surface_metric_for_asset,
            empty_surface_certification_audit=empty_surface_certification_audit,
            surface_certification_audit=surface_certification_audit,
            default_story_mix=default_story_mix,
            default_story_calendar=default_story_calendar,
            story_intents=story_intents,
            story_goals=story_goals,
            story_styles=story_styles,
        )
        self.surface_summary = SurfaceSummaryRepository(
            conn,
            creator_label=creator_label,
            creator_os_target_date=creator_os_target_date,
            creator_content_needs=self.surface_requirements.creator_content_needs,
            account_content_needs=self.surface_requirements.account_content_needs,
            account_surface_obligations_plan=self.surface_requirements.account_surface_obligations_plan,
            multi_surface_inventory_audit=self.surface_inventory.multi_surface_inventory_audit,
            surface_gap_report=self.surface_requirements.surface_gap_report,
            empty_surface_totals=self.surface_requirements.empty_surface_totals,
            content_surfaces=content_surfaces,
        )
        self.draft_inventory_gap = DraftInventoryGapRepository(
            conn,
            creator_label=creator_label,
            creator_os_draft_items=creator_os_draft_items,
            creator_os_local_schedule_safe_assets=creator_os_local_schedule_safe_assets,
            creator_os_schedule_safe_drafts=creator_os_schedule_safe_drafts,
            creator_os_draft_exclusion_reason=creator_os_draft_exclusion_reason,
            creator_os_execution_draft_blockers=creator_os_execution_draft_blockers,
            creator_os_gap_blocking_reason=creator_os_gap_blocking_reason,
            utc_now=utc_now,
        )
        self.daily_plan = DailyPlanRepository(
            conn,
            creator_label=creator_label,
            creator_os_target_date=creator_os_target_date,
            creator_os_draft_items=creator_os_draft_items,
            creator_os_account_health_report=creator_os_account_health_report,
            creator_os_account_health_decision=creator_os_account_health_decision,
            creator_os_tier_posting_guidance=creator_os_tier_posting_guidance,
            creator_os_account_surface_status=creator_os_account_surface_status,
            creator_os_draft_exclusion_reason=creator_os_draft_exclusion_reason,
            creator_os_draft_has_instagram_post_caption=creator_os_draft_has_instagram_post_caption,
            creator_os_post_time=creator_os_post_time,
            creator_os_recommended_post_count=creator_os_recommended_post_count,
            creator_os_account_tier_summary=creator_os_account_tier_summary,
            creator_os_account_health_summary=creator_os_account_health_summary,
            creator_os_surface_summary_for_creator=creator_os_surface_summary_for_creator,
            creator_os_inventory_for_creator=creator_os_inventory_for_creator,
            creator_os_draft_exclusion_counts=creator_os_draft_exclusion_counts,
            creator_os_winner_recommendations=creator_os_winner_recommendations,
            creator_os_manager_decision=creator_os_manager_decision,
            creator_os_blocked_account_breakdown=creator_os_blocked_account_breakdown,
            recommended_story_intent_for_date=recommended_story_intent_for_date,
            creator_os_recommended_inventory=creator_os_recommended_inventory,
            recommended_story_style_for_intent=recommended_story_style_for_intent,
            creator_os_draft_inventory_gap=self.draft_inventory_gap.creator_os_draft_inventory_gap,
            utc_now=utc_now,
        )
        self.surface_registration = SurfaceRegistrationRepository(
            conn,
            slugify=slugify,
            utc_now=utc_now,
            creator_label=creator_label,
            normalize_content_surface=normalize_content_surface,
            upsert_model=self.models.upsert_model,
            upsert_campaign=self.models.upsert_campaign,
            campaign_dirs=campaign_dirs,
            surface_handoff_readiness_report=surface_handoff_readiness_report,
            record_event=self.events.record_event,
            media_type_for_path=media_type_for_path,
            sha256_file=sha256_file,
            probe_image_shape=probe_image_shape,
            probe_video_shape=probe_video_shape,
            ratio_label_from_shape=ratio_label_from_shape,
            story_source_blockers=self.story_management.story_source_blockers,
            normalize_story_enum=normalize_story_enum,
            story_intents=story_intents,
            story_goals=story_goals,
            story_styles=story_styles,
            ig_media_type_by_surface=ig_media_type_by_surface,
        )
        self.carousel_integrity = CarouselIntegrityRepository(
            conn,
            slugify=slugify,
            creator_label=creator_label,
            normalize_content_surface=normalize_content_surface,
            surface_report_assets=surface_report_assets,
            surface_handoff_readiness_for_asset=surface_handoff_readiness_for_asset,
            surface_draft_proof=surface_draft_proof,
            surface_readiness_scorecard=surface_readiness_scorecard,
            asset_components=asset_components,
        )
        self.winner_expansion = WinnerExpansionRepository(
            conn,
            campaign_by_slug=self.campaign_by_slug,
            rendered_asset=self.rendered_asset,
            concept_for_parent_asset=concept_for_parent_asset,
            explain_publishability=explain_publishability,
        )
        self.creative_knowledge = CreativeKnowledgeRepository(
            conn,
            slugify=slugify,
            creator_label=creator_label,
            build_creative_knowledge_base=build_creative_knowledge_base,
        )
        self.tribev2 = TribeV2Repository(
            conn,
            settings,
            slugify=slugify,
            creator_label=creator_label,
            normalize_content_surface=normalize_content_surface,
            creative_knowledge_rows=creative_knowledge_rows,
            creative_knowledge_result=creative_knowledge_result,
            image_exts=image_exts,
            video_exts=video_exts,
        )
        self.operator_review = OperatorReviewRepository(
            conn,
            normalize_content_surface=normalize_content_surface,
            multi_blocker_inventory_unlock_report=multi_blocker_inventory_unlock_report,
            repair_minutes=multi_blocker_repair_minutes,
        )
        self.account_health = AccountHealthRepository(
            conn,
            utc_now=utc_now,
            creator_label=creator_label,
            truthy=truthy,
            normalize_content_surface=normalize_content_surface,
            account_trust_states=account_trust_states,
            recommendation_eligibility_states=recommendation_eligibility_states,
            warming_stages=warming_stages,
            content_surfaces=content_surfaces,
            creative_risk_block_threshold=creative_risk_block_threshold,
            creative_risk_caution_threshold=creative_risk_caution_threshold,
        )
        self.execution_readiness = ExecutionReadinessRepository(
            conn,
            settings,
            creator_label=creator_label,
            creator_os_daily_plan=creator_os_daily_plan,
            creator_os_draft_items=creator_os_draft_items,
            creator_os_schedule_safe_drafts=creator_os_schedule_safe_drafts,
            creator_os_account_health_report=creator_os_account_health_report,
            creator_os_execution_draft_blockers=creator_os_execution_draft_blockers,
            creator_os_execution_account_health_blockers=self.account_health.creator_os_execution_account_health_blockers,
            creator_os_execution_account_health_warnings=self.account_health.creator_os_execution_account_health_warnings,
            utc_now=utc_now,
        )
        self.acceptance_suite = AcceptanceSuiteRepository(
            conn,
            creator_os_daily_plan=creator_os_daily_plan,
            creator_os_execution_readiness=creator_os_execution_readiness,
            creator_os_account_health_report=creator_os_account_health_report,
            content_surfaces=content_surfaces,
        )
        self.operational_proofs = OperationalProofRepository(conn)
        self.readiness_report = ReadinessReportRepository(
            conn,
            creator_os_200_account_acceptance_suite=self.acceptance_suite.creator_os_200_account_acceptance_suite,
            inventory_slo_report=inventory_slo_report,
            surface_maturity_audit=self.operational_proofs.surface_maturity_audit,
            exception_queue_priority_report=exception_queue_priority_report,
            parent_factory_autopilot_plan=parent_factory_autopilot_plan,
            inventory_autopilot_plan=inventory_autopilot_plan,
            operator_load_audit=self.operational_proofs.operator_load_audit,
            failure_injection_suite=self.operational_proofs.failure_injection_suite,
            idempotency_proof=self.operational_proofs.idempotency_proof,
        )
        self.live_scale = LiveScaleRepository(
            conn,
            inventory_stage_counts=inventory_stage_counts,
            inventory_production_requirements=inventory_production_requirements,
            operator_load_audit=self.operational_proofs.operator_load_audit,
            exception_queue_report=exception_queue_report,
            reel_factory_parent_metrics=reel_factory_parent_metrics,
            score_fraction=score_fraction,
        )
        self.live_acceptance = LiveAcceptanceRepository(
            conn,
            normalize_content_surface=normalize_content_surface,
            actual_account_operational_counts=self.live_scale.actual_account_operational_counts,
            surface_report_assets=surface_report_assets,
            build_surface_readiness=build_surface_readiness,
            reservation_adjusted_inventory=reservation_adjusted_inventory,
            exception_queue_report=exception_queue_report,
        )
        self.certification = CertificationRepository(
            conn,
            creator_os_live_100_account_readiness=self.live_scale.creator_os_live_100_account_readiness,
            parent_factory_production_scorecard=parent_factory_production_scorecard,
            discoverability_prevention_scorecard=self.discoverability.discoverability_prevention_scorecard,
            story_certification_proof=self.story_management.story_certification_proof,
            carousel_certification_proof=self.carousel_integrity.carousel_certification_proof,
        )
        self.core_complexity = CoreComplexityRepository(conn, settings)

    def ensure_graph_node(
        self,
        entity_type: str,
        *,
        local_table: str | None = None,
        local_id: str | None = None,
        external_system: str | None = None,
        external_id: str | None = None,
        payload: dict[str, Any] | None = None,
        commit: bool = False,
    ) -> str:
        return self.graph.ensure_graph_node(
            entity_type,
            local_table=local_table,
            local_id=local_id,
            external_system=external_system,
            external_id=external_id,
            payload=payload,
            commit=commit,
        )

    def graph_id_for(
        self,
        local_table: str,
        local_id: str | None,
        *,
        entity_type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str | None:
        return self.graph.graph_id_for(local_table, local_id, entity_type=entity_type, payload=payload)

    def ensure_graph_edge(
        self,
        from_global_id: str | None,
        to_global_id: str | None,
        relation_type: str,
        *,
        evidence: dict[str, Any] | None = None,
        commit: bool = False,
    ) -> str | None:
        return self.graph.ensure_graph_edge(
            from_global_id,
            to_global_id,
            relation_type,
            evidence=evidence,
            commit=commit,
        )

    def set_graph_sync_state(self, system: str, cursor: dict[str, Any]) -> None:
        self.graph.set_sync_state(system, cursor)

    def record_event(
        self,
        event_type: str,
        *,
        campaign_id: str | None = None,
        source_asset_id: str | None = None,
        rendered_asset_id: str | None = None,
        render_job_id: str | None = None,
        audit_report_id: str | None = None,
        threadsdash_export_id: str | None = None,
        pipeline_job_id: str | None = None,
        status: str = "info",
        message: str = "",
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        return self.events.record_event(
            event_type,
            campaign_id=campaign_id,
            source_asset_id=source_asset_id,
            rendered_asset_id=rendered_asset_id,
            render_job_id=render_job_id,
            audit_report_id=audit_report_id,
            threadsdash_export_id=threadsdash_export_id,
            pipeline_job_id=pipeline_job_id,
            status=status,
            message=message,
            metadata=metadata,
            commit=commit,
        )

    def event_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.events.event_payload(row)

    def events_for_campaign(self, campaign_slug: str, limit: int = 200) -> list[dict[str, Any]]:
        return self.events.events_for_campaign(campaign_slug, limit=limit)

    def events_for_asset(self, rendered_asset_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.events.events_for_asset(rendered_asset_id, limit=limit)

    def jobs_for_campaign(self, campaign_slug: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.events.jobs_for_campaign(campaign_slug, limit=limit)

    def creator_os_draft_inventory_gap(
        self,
        *,
        creator: str,
        threadsdash_report: dict[str, Any] | None = None,
        schedule_plan: dict[str, Any] | None = None,
        time_plan: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.draft_inventory_gap.creator_os_draft_inventory_gap(
            creator=creator,
            threadsdash_report=threadsdash_report,
            schedule_plan=schedule_plan,
            time_plan=time_plan,
            generated_at=generated_at,
        )

    def creator_os_daily_plan(
        self,
        *,
        creators: list[str] | None = None,
        threadsdash_report: dict[str, Any] | None = None,
        schedule_plan: dict[str, Any] | None = None,
        time_plan: dict[str, Any] | None = None,
        winner_expansion_report: dict[str, Any] | None = None,
        winner_expansion_plan: dict[str, Any] | None = None,
        variant_metrics_rollup: dict[str, Any] | None = None,
        date: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.daily_plan.creator_os_daily_plan(
            creators=creators,
            threadsdash_report=threadsdash_report,
            schedule_plan=schedule_plan,
            time_plan=time_plan,
            winner_expansion_report=winner_expansion_report,
            winner_expansion_plan=winner_expansion_plan,
            variant_metrics_rollup=variant_metrics_rollup,
            date=date,
            generated_at=generated_at,
        )

    def creator_os_execution_readiness(
        self,
        *,
        creator: str,
        requested_count: int,
        threadsdash_report: dict[str, Any] | None = None,
        schedule_plan: dict[str, Any] | None = None,
        time_plan: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.execution_readiness.creator_os_execution_readiness(
            creator=creator,
            requested_count=requested_count,
            threadsdash_report=threadsdash_report,
            schedule_plan=schedule_plan,
            time_plan=time_plan,
            generated_at=generated_at,
        )

    def creator_os_200_account_acceptance_suite(
        self,
        *,
        accounts: int = 200,
        creators: int = 3,
        daily_obligations: int = 600,
        draft_inventory: int = 1800,
        warming_accounts: int = 30,
        restricted_accounts: int = 15,
        manual_review_accounts: int = 10,
        mixed_surfaces: bool = True,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.acceptance_suite.creator_os_200_account_acceptance_suite(
            accounts=accounts,
            creators=creators,
            daily_obligations=daily_obligations,
            draft_inventory=draft_inventory,
            warming_accounts=warming_accounts,
            restricted_accounts=restricted_accounts,
            manual_review_accounts=manual_review_accounts,
            mixed_surfaces=mixed_surfaces,
            generated_at=generated_at,
        )

    def creator_os_100_account_proof(self) -> dict[str, Any]:
        return self.readiness_report.creator_os_100_account_proof()

    def creator_os_volume_acceptance_suite(self) -> dict[str, Any]:
        return self.readiness_report.creator_os_volume_acceptance_suite()

    def surface_readiness_scorecard(self) -> dict[str, Any]:
        return self.readiness_report.surface_readiness_scorecard()

    def creator_os_10_0_readiness_report(self) -> dict[str, Any]:
        return self.readiness_report.creator_os_10_0_readiness_report()

    def creator_os_9_5_readiness_report(self) -> dict[str, Any]:
        return self.readiness_report.creator_os_9_5_readiness_report()

    def creator_os_live_100_account_readiness(self) -> dict[str, Any]:
        return self.live_scale.creator_os_live_100_account_readiness()

    def creator_os_live_scale_runbook(self) -> dict[str, Any]:
        return self.live_scale.creator_os_live_scale_runbook()

    def creator_os_live_scale_scorecard(self) -> dict[str, Any]:
        return self.live_scale.creator_os_live_scale_scorecard()

    def actual_account_operational_counts(self) -> dict[str, int]:
        return self.live_scale.actual_account_operational_counts()

    def live_100_exact_shortfall(
        self,
        *,
        accounts: dict[str, int],
        available_inventory: int,
        required_inventory: int,
        available_parents: int,
        required_parents: int,
    ) -> str:
        return self.live_scale.live_100_exact_shortfall(
            accounts=accounts,
            available_inventory=available_inventory,
            required_inventory=required_inventory,
            available_parents=available_parents,
            required_parents=required_parents,
        )

    def creator_os_live_account_acceptance(
        self,
        *,
        account_target: int,
        posts_per_account_per_day: int = 3,
        buffer_days: int = 3,
        content_surface: str | None = None,
        threadsdash_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.live_acceptance.creator_os_live_account_acceptance(
            account_target=account_target,
            posts_per_account_per_day=posts_per_account_per_day,
            buffer_days=buffer_days,
            content_surface=content_surface,
            threadsdash_report=threadsdash_report,
        )

    def creator_os_staged_live_acceptance(
        self,
        *,
        stages: list[int] | None = None,
        content_surface: str | None = None,
        threadsdash_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.live_acceptance.creator_os_staged_live_acceptance(
            stages=stages,
            content_surface=content_surface,
            threadsdash_report=threadsdash_report,
        )

    def live_acceptance_actuals(
        self,
        *,
        account_target: int,
        threadsdash_report: dict[str, Any],
        required_inventory: int,
        available_inventory: int,
        exception_count: int,
    ) -> dict[str, Any]:
        return self.live_acceptance.live_acceptance_actuals(
            account_target=account_target,
            threadsdash_report=threadsdash_report,
            required_inventory=required_inventory,
            available_inventory=available_inventory,
            exception_count=exception_count,
        )

    def live_acceptance_missed_dispatches(self, report: dict[str, Any]) -> int:
        return self.live_acceptance.live_acceptance_missed_dispatches(report)

    def live_acceptance_duplicate_publishes(self, report: dict[str, Any]) -> int:
        return self.live_acceptance.live_acceptance_duplicate_publishes(report)

    def live_acceptance_restricted_scheduled(self, report: dict[str, Any]) -> int:
        return self.live_acceptance.live_acceptance_restricted_scheduled(report)

    def live_acceptance_surface_contract_violations(self, report: dict[str, Any]) -> int:
        return self.live_acceptance.live_acceptance_surface_contract_violations(report)

    def live_acceptance_metrics_imported(self) -> bool:
        return self.live_acceptance.live_acceptance_metrics_imported()

    def live_acceptance_blocker_for(self, key: str) -> str:
        return self.live_acceptance.live_acceptance_blocker_for(key)

    def creator_os_certification_report(self) -> dict[str, Any]:
        return self.certification.creator_os_certification_report()

    def failure_injection_suite(self) -> dict[str, Any]:
        return self.operational_proofs.failure_injection_suite()

    def idempotency_proof(self) -> dict[str, Any]:
        return self.operational_proofs.idempotency_proof()

    def surface_maturity_audit(self) -> dict[str, Any]:
        return self.operational_proofs.surface_maturity_audit()

    def operator_load_audit(self) -> dict[str, Any]:
        return self.operational_proofs.operator_load_audit()

    def idempotency_evidence_for_path(self, name: str) -> str:
        return self.operational_proofs.idempotency_evidence_for_path(name)

    def single_source_of_truth_audit(self) -> dict[str, Any]:
        return self.core_complexity.single_source_of_truth_audit()

    def core_complexity_reduction_plan(self) -> dict[str, Any]:
        return self.core_complexity.core_complexity_reduction_plan()

    def largest_project_files(self) -> list[dict[str, Any]]:
        return self.core_complexity.largest_project_files()

    def create_pipeline_job(
        self,
        job_type: str,
        campaign_id: str | None,
        input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.events.create_pipeline_job(job_type, campaign_id, input_payload)

    def start_pipeline_job(self, job_id: str) -> dict[str, Any]:
        return self.events.start_pipeline_job(job_id)

    def finish_pipeline_job(self, job_id: str, result_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.events.finish_pipeline_job(job_id, result_payload)

    def fail_pipeline_job(self, job_id: str, error: str, result_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.events.fail_pipeline_job(job_id, error, result_payload)

    def set_pipeline_job_campaign(self, job_id: str, campaign_id: str) -> dict[str, Any]:
        return self.events.set_pipeline_job_campaign(job_id, campaign_id)

    def pipeline_job(self, job_id: str) -> dict[str, Any]:
        return self.events.pipeline_job(job_id)

    def pipeline_job_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.events.pipeline_job_payload(row)

    def upsert_model(self, slug: str, name: str | None = None, notes: str | None = None) -> dict[str, Any]:
        return self.models.upsert_model(slug, name=name, notes=notes)

    def upsert_campaign(self, slug: str, model_slug: str, name: str | None = None, platform: str = "instagram") -> dict[str, Any]:
        return self.models.upsert_campaign(slug, model_slug, name=name, platform=platform)

    def upsert_account(
        self,
        handle: str,
        platform: str = "instagram",
        external_id: str | None = None,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        return self.models.upsert_account(handle, platform=platform, external_id=external_id, model_id=model_id)

    def upsert_model_account_profile(
        self,
        model_slug: str,
        *,
        label: str | None = None,
        allowed_instagram_account_ids: list[str] | None = None,
        allowed_account_group_names: list[str] | None = None,
        allowed_handle_patterns: list[str] | None = None,
        default_smart_link: str | None = None,
        story_cta_text: str | None = None,
    ) -> dict[str, Any]:
        return self.models.upsert_model_account_profile(
            model_slug,
            label=label,
            allowed_instagram_account_ids=allowed_instagram_account_ids,
            allowed_account_group_names=allowed_account_group_names,
            allowed_handle_patterns=allowed_handle_patterns,
            default_smart_link=default_smart_link,
            story_cta_text=story_cta_text,
        )

    def model_account_profile(self, model_slug: str) -> dict[str, Any] | None:
        return self.models.model_account_profile(model_slug)

    def account_compatible_with_model(
        self,
        model_slug: str,
        *,
        instagram_account_id: str | None = None,
        account_handle: str | None = None,
        account_group_name: str | None = None,
    ) -> tuple[bool, str | None, dict[str, Any] | None]:
        return self.models.account_compatible_with_model(
            model_slug,
            instagram_account_id=instagram_account_id,
            account_handle=account_handle,
            account_group_name=account_group_name,
        )

    def import_folder(
        self,
        folder: Any,
        *,
        campaign_slug: str,
        model_slug: str,
        model_name: str | None = None,
        platform: str = "instagram",
        account_handles: list[str] | None = None,
        source_prompt: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return self.asset_import.import_folder(
            folder,
            campaign_slug=campaign_slug,
            model_slug=model_slug,
            model_name=model_name,
            platform=platform,
            account_handles=account_handles,
            source_prompt=source_prompt,
            notes=notes,
        )

    def assets_for_campaign(self, campaign_id: str) -> list[dict[str, Any]]:
        return self.asset_import.assets_for_campaign(campaign_id)

    def autonomy_level(self) -> str:
        return self.autonomy.autonomy_level()

    def set_autonomy_level(self, level: str) -> dict[str, Any]:
        return self.autonomy.set_autonomy_level(level)

    def autonomy_policy(self) -> dict[str, Any]:
        return self.autonomy.autonomy_policy()

    def rebuild_account_memory(self, campaign_slug: str) -> dict[str, Any]:
        return self.account_memory.rebuild_account_memory(campaign_slug)

    def account_memory_report(self, campaign_slug: str, account: str | None = None) -> dict[str, Any]:
        return self.account_memory.account_memory(campaign_slug, account=account)

    def account_memory_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.account_memory.account_memory_payload(row)

    def account_memory_for(self, campaign_id: str, account_id: str | None) -> dict[str, Any] | None:
        return self.account_memory.account_memory_for(campaign_id, account_id)

    def account_pattern_stats_from_snapshots(
        self,
        campaign_id: str,
        account_id: str,
        snapshots: list[dict[str, Any]],
        updated_at: str,
        *,
        account_baselines: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        return self.account_memory.account_pattern_stats_from_snapshots(
            campaign_id,
            account_id,
            snapshots,
            updated_at,
            account_baselines=account_baselines,
        )

    def account_posting_windows_from_snapshots(
        self,
        campaign_id: str,
        account_id: str,
        snapshots: list[dict[str, Any]],
        updated_at: str,
        *,
        account_baselines: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        return self.account_memory.account_posting_windows_from_snapshots(
            campaign_id,
            account_id,
            snapshots,
            updated_at,
            account_baselines=account_baselines,
        )

    def account_fatigue_from_pattern_stats(self, pattern_stats: list[dict[str, Any]]) -> dict[str, Any]:
        return self.account_memory.account_fatigue_from_pattern_stats(pattern_stats)

    def account_recommendation_outcomes(self, campaign_id: str, account_id: str, updated_at: str) -> dict[str, Any]:
        return self.account_memory.account_recommendation_outcomes(campaign_id, account_id, updated_at)

    def account_memory_confidence(self, sample_size: int, outcomes: dict[str, Any]) -> str:
        return self.account_memory.account_memory_confidence(sample_size, outcomes)

    def recommendation_accuracy(
        self,
        campaign_slug: str,
        *,
        account: str | None = None,
        window_days: int = 30,
        persist: bool = True,
    ) -> dict[str, Any]:
        return self.recommendation_accuracy_repo.recommendation_accuracy(
            campaign_slug,
            account=account,
            window_days=window_days,
            persist=persist,
        )

    def rebuild_recommendation_accuracy(
        self,
        campaign_slug: str,
        *,
        account: str | None = None,
        window_days: int = 30,
    ) -> dict[str, Any]:
        return self.recommendation_accuracy_repo.rebuild_recommendation_accuracy(
            campaign_slug,
            account=account,
            window_days=window_days,
        )

    def recommendation_proof_summary(self, campaign_id: str) -> dict[str, Any]:
        return self.recommendation_accuracy_repo.recommendation_proof_summary(campaign_id)

    def rebuild_recommendation_accuracy_observations(
        self,
        campaign_id: str,
        *,
        account: str | None = None,
        commit: bool = True,
    ) -> list[dict[str, Any]]:
        return self.recommendation_accuracy_repo.rebuild_recommendation_accuracy_observations(
            campaign_id,
            account=account,
            commit=commit,
        )

    def upsert_recommendation_accuracy_observation(self, row: dict[str, Any], *, commit: bool = False) -> dict[str, Any]:
        return self.recommendation_accuracy_repo.upsert_recommendation_accuracy_observation(row, commit=commit)

    def recommendation_accuracy_observations(
        self,
        campaign_id: str,
        *,
        account: str | None = None,
        window_days: int | None = None,
        before_window_days: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.recommendation_accuracy_repo.recommendation_accuracy_observations(
            campaign_id,
            account=account,
            window_days=window_days,
            before_window_days=before_window_days,
        )

    def recommendation_accuracy_report_payload(
        self,
        campaign: dict[str, Any],
        observations: list[dict[str, Any]],
        prior_observations: list[dict[str, Any]],
        *,
        account: str | None,
        window_days: int,
    ) -> dict[str, Any]:
        return self.recommendation_accuracy_repo.recommendation_accuracy_report_payload(
            campaign,
            observations,
            prior_observations,
            account=account,
            window_days=window_days,
        )

    def persist_recommendation_accuracy_report(
        self,
        report: dict[str, Any],
        campaign_id: str,
        *,
        account: str | None,
        window_days: int,
    ) -> str:
        return self.recommendation_accuracy_repo.persist_recommendation_accuracy_report(
            report,
            campaign_id,
            account=account,
            window_days=window_days,
        )

    def accuracy_segment(self, observations: list[dict[str, Any]]) -> dict[str, Any]:
        return self.recommendation_accuracy_repo.accuracy_segment(observations)

    def accuracy_grouped(self, observations: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        return self.recommendation_accuracy_repo.accuracy_grouped(observations, key)

    def recommendation_accuracy_drift(
        self,
        recent: list[dict[str, Any]],
        prior: list[dict[str, Any]],
        *,
        min_sample: int = 5,
        drop_threshold: float = 0.15,
    ) -> list[dict[str, Any]]:
        return self.recommendation_accuracy_repo.recommendation_accuracy_drift(
            recent,
            prior,
            min_sample=min_sample,
            drop_threshold=drop_threshold,
        )

    def recommendation_trust_score(self, observations: list[dict[str, Any]], drift: list[dict[str, Any]]) -> int:
        return self.recommendation_accuracy_repo.recommendation_trust_score(observations, drift)

    def recommendation_trust_confidence(self, measured_count: int) -> str:
        return self.recommendation_accuracy_repo.recommendation_trust_confidence(measured_count)

    def recommendation_confidence_bucket(self, confidence: str, data_quality_level: str) -> str:
        return self.recommendation_accuracy_repo.recommendation_confidence_bucket(confidence, data_quality_level)

    def recommendation_audio_selection(self, recommendation_item_id: str) -> dict[str, Any]:
        return self.recommendation_accuracy_repo.recommendation_audio_selection(recommendation_item_id)

    def recommendation_audio_match_status(self, output: dict[str, Any], selection: dict[str, Any]) -> str:
        return self.recommendation_accuracy_repo.recommendation_audio_match_status(output, selection)

    def recommendation_outcome_snapshot_ids(self, outcome: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
        return self.recommendation_accuracy_repo.recommendation_outcome_snapshot_ids(outcome, evidence)

    def parse_datetime(self, value: Any):
        return self.recommendation_accuracy_repo.parse_datetime(value)

    def campaign_health(self, campaign_slug: str) -> dict[str, Any]:
        return self.campaign_overview.campaign_health(campaign_slug)

    def asset_detail(self, rendered_asset_id: str) -> dict[str, Any]:
        return self.campaign_overview.asset_detail(rendered_asset_id)

    def assign_asset_account(
        self,
        rendered_asset_id: str,
        *,
        account_id: str | None = None,
        instagram_account_id: str | None = None,
        planned_window_start: str | None = None,
        planned_window_end: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return self.campaign_overview.assign_asset_account(
            rendered_asset_id,
            account_id=account_id,
            instagram_account_id=instagram_account_id,
            planned_window_start=planned_window_start,
            planned_window_end=planned_window_end,
            notes=notes,
        )

    def assignments_for_asset(self, rendered_asset_id: str) -> list[dict[str, Any]]:
        return self.campaign_overview.assignments_for_asset(rendered_asset_id)

    def assignments_for_campaign(self, campaign_slug: str) -> list[dict[str, Any]]:
        return self.campaign_overview.assignments_for_campaign(campaign_slug)

    def create_creative_plan(
        self,
        *,
        name: str,
        platform: str = "instagram",
        target_account: str,
        daily_base_video_target: int = 10,
        style_lanes: list[str] | None = None,
        model_profile: str = "",
        source_accounts: list[str] | None = None,
        goal: str = "views_reach",
        linked_campaign: str | None = None,
    ) -> dict[str, Any]:
        return self.creative_planning.create_creative_plan(
            name=name,
            platform=platform,
            target_account=target_account,
            daily_base_video_target=daily_base_video_target,
            style_lanes=style_lanes,
            model_profile=model_profile,
            source_accounts=source_accounts,
            goal=goal,
            linked_campaign=linked_campaign,
        )

    def creative_plan(self, name: str) -> dict[str, Any]:
        return self.creative_planning.creative_plan(name)

    def update_creative_plan_status(self, *, name: str, status: str) -> dict[str, Any]:
        return self.creative_planning.update_creative_plan_status(name=name, status=status)

    def sync_creative_plan_progress(self, *, name: str, prompt_export_path: Any) -> dict[str, Any]:
        return self.creative_planning.sync_creative_plan_progress(name=name, prompt_export_path=prompt_export_path)

    def creative_plan_for_campaign(self, campaign_slug: str, *, dashboard: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self.creative_planning.creative_plan_for_campaign(campaign_slug, dashboard=dashboard)

    def record_creative_plan_event(
        self,
        plan_id: str,
        event_type: str,
        *,
        status: str = "info",
        message: str = "",
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> None:
        self.creative_planning.record_creative_plan_event(
            plan_id,
            event_type,
            status=status,
            message=message,
            metadata=metadata,
            commit=commit,
        )

    def creative_plan_payload(self, row: dict[str, Any], *, dashboard: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.creative_planning.creative_plan_payload(row, dashboard=dashboard)

    def source_prompt_creative_plan_id(self, source: dict[str, Any]) -> str | None:
        return self.creative_planning.source_prompt_creative_plan_id(source)

    def asset_creative_plan_id(self, asset: dict[str, Any]) -> str | None:
        return self.creative_planning.asset_creative_plan_id(asset)

    def import_reference_bank(self, bank_path: Any, prompt_pack_path: Any | None = None) -> dict[str, Any]:
        return self.reference.import_reference_bank(bank_path, prompt_pack_path)

    def reference_prompt_pack_by_cluster(self, prompt_pack_path: Any | None) -> dict[str, dict[str, Any]]:
        return self.reference.reference_prompt_pack_by_cluster(prompt_pack_path)

    def reference_patterns(self, limit: int = 50) -> dict[str, Any]:
        return self.reference.reference_patterns(limit=limit)

    def reference_pattern_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.reference.reference_pattern_payload(row)

    def select_reference_pattern(
        self,
        campaign_slug: str,
        *,
        cluster_key: str | None = None,
        reference_pattern_id: str | None = None,
        variant_count: int = 5,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return self.reference.select_reference_pattern(
            campaign_slug,
            cluster_key=cluster_key,
            reference_pattern_id=reference_pattern_id,
            variant_count=variant_count,
            notes=notes,
        )

    def campaign_reference_plan(self, campaign_slug: str) -> dict[str, Any]:
        return self.reference.campaign_reference_plan(campaign_slug)

    def prepare_reel_from_reference(
        self,
        *,
        campaign_slug: str,
        cluster_key: str | None = None,
        reference_pattern_id: str | None = None,
        variant_count: int = 5,
        recipes: list[str] | None = None,
        caption_color: str | None = "auto",
        notes: str | None = None,
        force_new: bool = True,
    ) -> dict[str, Any]:
        return self.reference.prepare_reel_from_reference(
            campaign_slug=campaign_slug,
            cluster_key=cluster_key,
            reference_pattern_id=reference_pattern_id,
            variant_count=variant_count,
            recipes=recipes,
            caption_color=caption_color,
            notes=notes,
            force_new=force_new,
        )

    def active_reference_pattern_for_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        return self.reference.active_reference_pattern_for_campaign(campaign_id)

    def reference_hooks(self, pattern: dict[str, Any], count: int = 5) -> list[dict[str, Any]]:
        return self.reference.reference_hooks(pattern, count=count)

    def reference_hook_is_schedule_safe(self, text: str) -> bool:
        return self.reference.reference_hook_is_schedule_safe(text)

    def caption_family_plan(
        self,
        *,
        creator: str | None,
        parent_asset_id: str,
        requested_caption_versions: int = 5,
        style: str = "ig_short",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        return self.caption_family.caption_family_plan(
            creator=creator,
            parent_asset_id=parent_asset_id,
            requested_caption_versions=requested_caption_versions,
            style=style,
            dry_run=dry_run,
        )

    def caption_family_create(
        self,
        *,
        creator: str | None,
        parent_asset_id: str,
        requested_caption_versions: int = 5,
        style: str = "ig_short",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.caption_family.caption_family_create(
            creator=creator,
            parent_asset_id=parent_asset_id,
            requested_caption_versions=requested_caption_versions,
            style=style,
            dry_run=dry_run,
        )

    def planned_caption_version(
        self,
        *,
        caption_family_id: str,
        parent: dict[str, Any],
        concept: dict[str, Any] | None,
        index: int,
        angle: str,
        base_burned: str,
        base_hashtags: list[str],
        style: str,
        caption_source: str,
    ) -> dict[str, Any]:
        return self.caption_family.planned_caption_version(
            caption_family_id=caption_family_id,
            parent=parent,
            concept=concept,
            index=index,
            angle=angle,
            base_burned=base_burned,
            base_hashtags=base_hashtags,
            style=style,
            caption_source=caption_source,
        )

    def caption_family_hashtags(self, raw_tags: Any) -> list[str]:
        return self.caption_family.caption_family_hashtags(raw_tags)

    def caption_version_by_id(self, caption_version_id: str | None) -> dict[str, Any] | None:
        return self.caption_family.caption_version_by_id(caption_version_id)

    def caption_version_payload(self, row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
        return self.caption_family.caption_version_payload(row)

    def create_distribution_plan(
        self,
        rendered_asset_id: str,
        *,
        surface: str = "regular_reel",
        account_id: str | None = None,
        instagram_account_id: str | None = None,
        planned_window_start: str | None = None,
        planned_window_end: str | None = None,
        paired_rendered_asset_id: str | None = None,
        reason_code: str | None = None,
        smart_link: str | None = None,
        cta_text: str | None = None,
        instagram_trial_reels: bool = False,
        trial_graduation_strategy: str | None = None,
    ) -> dict[str, Any]:
        return self.distribution.create_distribution_plan(
            rendered_asset_id,
            surface=surface,
            account_id=account_id,
            instagram_account_id=instagram_account_id,
            planned_window_start=planned_window_start,
            planned_window_end=planned_window_end,
            paired_rendered_asset_id=paired_rendered_asset_id,
            reason_code=reason_code,
            smart_link=smart_link,
            cta_text=cta_text,
            instagram_trial_reels=instagram_trial_reels,
            trial_graduation_strategy=trial_graduation_strategy,
        )

    def distribution_plan(self, plan_id: str) -> dict[str, Any] | None:
        return self.distribution.distribution_plan(plan_id)

    def distribution_plans_for_asset(self, rendered_asset_id: str) -> list[dict[str, Any]]:
        return self.distribution.distribution_plans_for_asset(rendered_asset_id)

    def distribution_plans_for_campaign(self, campaign_slug: str) -> list[dict[str, Any]]:
        return self.distribution.distribution_plans_for_campaign(campaign_slug)

    def clear_distribution_plans_for_campaign(self, campaign_slug: str) -> int:
        return self.distribution.clear_distribution_plans_for_campaign(campaign_slug)

    def distribution_plan_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.distribution.distribution_plan_payload(row)

    def plan_distribution(
        self,
        campaign_slug: str,
        *,
        user_id: str,
        mode: str = "preview",
        strategy: str = "trial-heavy",
        replace: bool = True,
        fallback_hours: list[int] | None = None,
    ) -> dict[str, Any]:
        return self.distribution.plan_distribution(
            campaign_slug,
            user_id=user_id,
            mode=mode,
            strategy=strategy,
            replace=replace,
            fallback_hours=fallback_hours,
        )

    def next_distribution_account(
        self,
        profile: dict[str, Any] | None,
        model_slug: str,
        cursors: dict[str, int],
    ) -> str | None:
        return self.distribution.next_distribution_account(profile, model_slug, cursors)

    def distribution_slots(self, hours: list[int], count: int) -> list[Any]:
        return self.distribution.distribution_slots(hours, count)

    def next_valid_distribution_slot(
        self,
        slots: list[Any],
        start_index: int,
        account_id: str,
        asset: dict[str, Any],
        account_day_counts: dict[tuple[str, str], int],
        account_last_time: dict[str, Any],
        caption_day_counts: dict[tuple[str, str], int],
        source_week_counts: dict[tuple[str, str], int],
        warnings: list[dict[str, Any]],
    ) -> tuple[Any | None, int]:
        return self.distribution.next_valid_distribution_slot(
            slots,
            start_index,
            account_id,
            asset,
            account_day_counts,
            account_last_time,
            caption_day_counts,
            source_week_counts,
            warnings,
        )

    def distribution_summary(self, campaign_slug: str) -> dict[str, Any]:
        return self.distribution.distribution_summary(campaign_slug)

    def latest_distribution_plan_for_asset(self, rendered_asset_id: str) -> dict[str, Any] | None:
        return self.distribution.latest_distribution_plan_for_asset(rendered_asset_id)

    def decision_ledger_preview(
        self,
        *,
        creator: str,
        date: str | None = None,
        threadsdash_report: dict[str, Any] | None = None,
        schedule_plan: dict[str, Any] | None = None,
        time_plan: dict[str, Any] | None = None,
        winner_expansion_report: dict[str, Any] | None = None,
        winner_expansion_plan: dict[str, Any] | None = None,
        variant_inventory_plan: dict[str, Any] | None = None,
        variant_metrics_rollup: dict[str, Any] | None = None,
        account_tiers: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.decision_ledger.decision_ledger_preview(
            creator=creator,
            date=date,
            threadsdash_report=threadsdash_report,
            schedule_plan=schedule_plan,
            time_plan=time_plan,
            winner_expansion_report=winner_expansion_report,
            winner_expansion_plan=winner_expansion_plan,
            variant_inventory_plan=variant_inventory_plan,
            variant_metrics_rollup=variant_metrics_rollup,
            account_tiers=account_tiers,
            generated_at=generated_at,
        )

    def decision_ledger_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.decision_ledger.decision_ledger_report(**kwargs)

    def decision_ledger_summary(self, **kwargs: Any) -> dict[str, Any]:
        return self.decision_ledger.decision_ledger_summary(**kwargs)

    def decision_ledger_by_creator(self, *, creator: str, **kwargs: Any) -> dict[str, Any]:
        return self.decision_ledger.decision_ledger_by_creator(creator=creator, **kwargs)

    def decision_ledger_by_account(self, *, account_id: str, creator: str, **kwargs: Any) -> dict[str, Any]:
        return self.decision_ledger.decision_ledger_by_account(account_id=account_id, creator=creator, **kwargs)

    def decision_ledger_by_surface(self, *, surface: str, creator: str, **kwargs: Any) -> dict[str, Any]:
        return self.decision_ledger.decision_ledger_by_surface(surface=surface, creator=creator, **kwargs)

    def decision_ledger_by_decision_type(self, *, decision_type: str, creator: str, **kwargs: Any) -> dict[str, Any]:
        return self.decision_ledger.decision_ledger_by_decision_type(
            decision_type=decision_type,
            creator=creator,
            **kwargs,
        )

    def query_decision_ledger(self, **kwargs: Any) -> dict[str, Any]:
        return self.decision_ledger.query_decision_ledger(**kwargs)

    def create_exception(
        self,
        *,
        reason_code: str,
        severity: str = "medium",
        campaign_id: str | None = None,
        account_id: str | None = None,
        entity_graph_id: str | None = None,
        recommendation_item_id: str | None = None,
        payload: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        return self.exceptions.create_exception(
            reason_code=reason_code,
            severity=severity,
            campaign_id=campaign_id,
            account_id=account_id,
            entity_graph_id=entity_graph_id,
            recommendation_item_id=recommendation_item_id,
            payload=payload,
            commit=commit,
        )

    def exception(self, exception_id: str) -> dict[str, Any]:
        return self.exceptions.exception(exception_id)

    def exceptions_report(self, campaign_slug: str | None = None, *, status: str = "open") -> dict[str, Any]:
        return self.exceptions.exceptions(campaign_slug, status=status)

    def trust_summary(self, campaign_slug: str) -> dict[str, Any]:
        return self.exceptions.trust_summary(campaign_slug)

    def resolve_exception(
        self,
        exception_id: str,
        *,
        resolution: str | None = None,
        operator: str | None = None,
    ) -> dict[str, Any]:
        return self.exceptions.resolve_exception(exception_id, resolution=resolution, operator=operator)

    def snooze_exception(
        self,
        exception_id: str,
        *,
        until: str | None = None,
        reason: str | None = None,
        operator: str | None = None,
    ) -> dict[str, Any]:
        return self.exceptions.snooze_exception(exception_id, until=until, reason=reason, operator=operator)

    def reopen_exception(
        self,
        exception_id: str,
        *,
        reason: str | None = None,
        operator: str | None = None,
    ) -> dict[str, Any]:
        return self.exceptions.reopen_exception(exception_id, reason=reason, operator=operator)

    def update_exception_status(
        self,
        exception_id: str,
        status: str,
        *,
        resolution: dict[str, Any] | None = None,
        snoozed_until: str | None = None,
    ) -> dict[str, Any]:
        return self.exceptions.update_exception_status(
            exception_id,
            status,
            resolution=resolution,
            snoozed_until=snoozed_until,
        )

    def exception_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.exceptions.exception_payload(row)

    def discoverability_safe_content_contract(self, *values: Any) -> dict[str, Any]:
        return self.discoverability.discoverability_safe_content_contract(*values)

    def discoverability_intake_gate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.discoverability.discoverability_intake_gate(payload)

    def discoverability_generation_gate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.discoverability.discoverability_generation_gate(payload)

    def discoverability_pre_render_gate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.discoverability.discoverability_pre_render_gate(payload)

    def discoverability_violation_origin_map(self) -> dict[str, Any]:
        return self.discoverability.discoverability_violation_origin_map()

    def parent_factory_discoverability_loss_analysis(self, *, waterfall: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.discoverability.parent_factory_discoverability_loss_analysis(waterfall=waterfall)

    def parent_factory_waterfall_after_discoverability(self) -> dict[str, Any]:
        return self.discoverability.parent_factory_waterfall_after_discoverability()

    def discoverability_prevention_audit(self) -> dict[str, Any]:
        return self.discoverability.discoverability_prevention_audit()

    def discoverability_prevention_scorecard(self) -> dict[str, Any]:
        return self.discoverability.discoverability_prevention_scorecard()

    def story_inventory_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.story_management.story_inventory_report(**kwargs)

    def story_intent_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.story_management.story_intent_report(**kwargs)

    def story_mix_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.story_management.story_mix_plan(**kwargs)

    def story_calendar_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.story_management.story_calendar_plan(**kwargs)

    def story_intent_summary(self, **kwargs: Any) -> dict[str, Any]:
        return self.story_management.story_intent_summary(**kwargs)

    def story_metadata_payload(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.story_management.story_metadata_payload(asset)

    def story_intent_value(self, asset: dict[str, Any]) -> str | None:
        return self.story_management.story_intent_value(asset)

    def story_goal_value(self, asset: dict[str, Any]) -> str | None:
        return self.story_management.story_goal_value(asset)

    def story_style_value(self, asset: dict[str, Any]) -> str | None:
        return self.story_management.story_style_value(asset)

    def normalize_story_enum(self, value: Any, allowed: set[str]) -> str | None:
        return self.story_management.normalize_story_enum(value, allowed)

    def story_quality_gate_v1(self, rendered_asset_id: str) -> dict[str, Any]:
        return self.story_management.story_quality_gate_v1(rendered_asset_id)

    def story_quality_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.story_management.story_quality_report(**kwargs)

    def story_quality_gate_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.story_management.story_quality_gate_for_asset(asset)

    def story_quality_metadata(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.story_management.story_quality_metadata(asset)

    def bounded_score(self, value: Any, *, default: int) -> int:
        return self.story_management.bounded_score(value, default=default)

    def story_black_bar_check(self, media_path: Any, *, media_type: str) -> dict[str, Any]:
        return self.story_management.story_black_bar_check(media_path, media_type=media_type)

    def story_no_text_check(self, media_path: Any, *, media_type: str, quality: dict[str, Any]) -> dict[str, Any]:
        return self.story_management.story_no_text_check(media_path, media_type=media_type, quality=quality)

    def story_ocr_frame_paths(self, media_path: Any, *, media_type: str) -> list[Any]:
        return self.story_management.story_ocr_frame_paths(media_path, media_type=media_type)

    def story_ocr_detect_text(self, image_path: Any, *, frame_index: int) -> list[dict[str, Any]]:
        return self.story_management.story_ocr_detect_text(image_path, frame_index=frame_index)

    def pixel_region_black(self, rows: list[list[tuple[int, int, int]]], *, x0: int, x1: int, y0: int, y1: int) -> bool:
        return self.story_management.pixel_region_black(rows, x0=x0, x1=x1, y0=y0, y1=y1)

    def story_gap_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.story_management.story_gap_report(**kwargs)

    def account_story_status(self, **kwargs: Any) -> dict[str, Any]:
        return self.story_management.account_story_status(**kwargs)

    def creator_story_summary(self, **kwargs: Any) -> dict[str, Any]:
        return self.story_management.creator_story_summary(**kwargs)

    def multi_surface_inventory_audit(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
    ) -> dict[str, Any]:
        return self.surface_inventory.multi_surface_inventory_audit(creator=creator, campaign_slug=campaign_slug)

    def build_surface_inventory(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
    ) -> dict[str, Any]:
        return self.surface_inventory.build_surface_inventory(creator=creator, campaign_slug=campaign_slug)

    def account_surface_obligations_plan(self, *, creator: str, date: str) -> dict[str, Any]:
        return self.surface_requirements.account_surface_obligations_plan(creator=creator, date=date)

    def account_content_needs(
        self,
        *,
        account_id: str,
        creator: str | None = None,
        date: str,
    ) -> dict[str, Any]:
        return self.surface_requirements.account_content_needs(account_id=account_id, creator=creator, date=date)

    def account_surface_status(
        self,
        *,
        account_id: str,
        creator: str | None = None,
        date: str,
    ) -> dict[str, Any]:
        return self.surface_requirements.account_surface_status(account_id=account_id, creator=creator, date=date)

    def creator_content_needs(self, *, creator: str, date: str) -> dict[str, Any]:
        return self.surface_requirements.creator_content_needs(creator=creator, date=date)

    def surface_gap_report(self, *, creator: str, date: str) -> dict[str, Any]:
        return self.surface_requirements.surface_gap_report(creator=creator, date=date)

    def build_surface_status(self, *, creator: str, date: str) -> dict[str, Any]:
        return self.surface_requirements.build_surface_status(creator=creator, date=date)

    def account_content_requirement_rows(
        self,
        *,
        creator: str | None = None,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.surface_requirements.account_content_requirement_rows(creator=creator, account_id=account_id)

    def account_row_for_requirement_account(self, account_id: str) -> dict[str, Any] | None:
        return self.surface_requirements.account_row_for_requirement_account(account_id)

    def content_obligation_for_requirement(self, requirement: dict[str, Any], target_date: Any) -> dict[str, Any]:
        return self.surface_requirements.content_obligation_for_requirement(requirement, target_date)

    def required_content_count(self, requirement: dict[str, Any], target_date: Any) -> int:
        return self.surface_requirements.required_content_count(requirement, target_date)

    def empty_surface_totals(self) -> dict[str, dict[str, int]]:
        return self.surface_requirements.empty_surface_totals()

    def add_obligation_to_totals(self, totals: dict[str, dict[str, int]], obligation: dict[str, Any]) -> None:
        self.surface_requirements.add_obligation_to_totals(totals, obligation)

    def requirement_active_on_date(self, requirement: dict[str, Any], target_date: Any) -> bool:
        return self.surface_requirements.requirement_active_on_date(requirement, target_date)

    def surface_scheduled_count(self, account_id: str, instagram_account_id: str | None, surface: str, target_date: Any) -> int:
        return self.surface_requirements.surface_scheduled_count(account_id, instagram_account_id, surface, target_date)

    def surface_completed_count(self, account_id: str, instagram_account_id: str | None, surface: str, target_date: Any) -> int:
        return self.surface_requirements.surface_completed_count(account_id, instagram_account_id, surface, target_date)

    def last_surface_posted_at(
        self,
        *,
        account_id: str,
        instagram_account_id: str | None,
        surface: str,
        before_date: Any,
    ) -> str | None:
        return self.surface_requirements.last_surface_posted_at(
            account_id=account_id,
            instagram_account_id=instagram_account_id,
            surface=surface,
            before_date=before_date,
        )

    def surface_scheduled_for_account(self, account_id: str, instagram_account_id: str | None, surface: str, target_date: Any) -> bool:
        return self.surface_requirements.surface_scheduled_for_account(account_id, instagram_account_id, surface, target_date)

    def surface_completed_for_account(self, account_id: str, instagram_account_id: str | None, surface: str, target_date: Any) -> bool:
        return self.surface_requirements.surface_completed_for_account(account_id, instagram_account_id, surface, target_date)

    def creator_surface_summary(
        self,
        *,
        creator: str,
        date: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.surface_summary.creator_surface_summary(creator=creator, date=date, generated_at=generated_at)

    def account_surface_summary(
        self,
        *,
        creator: str,
        date: str | None = None,
        account_id: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.surface_summary.account_surface_summary(
            creator=creator,
            date=date,
            account_id=account_id,
            generated_at=generated_at,
        )

    def creator_surface_gap_report(
        self,
        *,
        creator: str,
        date: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        return self.surface_summary.creator_surface_gap_report(creator=creator, date=date, generated_at=generated_at)

    def story_certification_proof(self, **kwargs: Any) -> dict[str, Any]:
        return self.story_management.story_certification_proof(**kwargs)

    def story_production_readiness(self) -> dict[str, Any]:
        return self.story_management.story_production_readiness()

    def story_proof_gap_analysis(self) -> dict[str, Any]:
        return self.story_management.story_proof_gap_analysis()

    def story_source_blockers(self, components: list[dict[str, Any]]) -> list[str]:
        return self.story_management.story_source_blockers(components)

    def story_existing_asset_source_blockers(self, asset: dict[str, Any]) -> list[str]:
        return self.story_management.story_existing_asset_source_blockers(asset)

    def creator_os_account_tiers(self, **kwargs: Any) -> dict[str, Any]:
        return self.account_health.creator_os_account_tiers(**kwargs)

    def creator_os_account_health_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.account_health.creator_os_account_health_report(**kwargs)

    def creator_os_restricted_account_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.account_health.creator_os_restricted_account_report(**kwargs)

    def creator_os_manual_review_queue(self, **kwargs: Any) -> dict[str, Any]:
        return self.account_health.creator_os_manual_review_queue(**kwargs)

    def creator_os_account_warmup_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.account_health.creator_os_account_warmup_report(**kwargs)

    def creator_os_execution_account_health_blockers(self, account_health: dict[str, Any]) -> list[str]:
        return self.account_health.creator_os_execution_account_health_blockers(account_health)

    def creator_os_execution_account_health_warnings(self, account_health: dict[str, Any]) -> list[str]:
        return self.account_health.creator_os_execution_account_health_warnings(account_health)

    def creator_os_account_tier_summary(self, accounts: list[dict[str, Any]], *, key: str = "accountTier") -> dict[str, int]:
        return self.account_health.creator_os_account_tier_summary(accounts, key=key)

    def creator_os_account_health_decision(self, account: dict[str, Any], *, missed: list[dict[str, Any]]) -> dict[str, Any]:
        return self.account_health.creator_os_account_health_decision(account, missed=missed)

    def creator_os_account_health_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return self.account_health.creator_os_account_health_summary(rows)

    def creator_os_account_trust_state(self, account: dict[str, Any]) -> str:
        return self.account_health.creator_os_account_trust_state(account)

    def creator_os_recommendation_eligibility(self, account: dict[str, Any]) -> str:
        return self.account_health.creator_os_recommendation_eligibility(account)

    def creator_os_restriction_status(self, account: dict[str, Any]) -> dict[str, Any]:
        return self.account_health.creator_os_restriction_status(account)

    def creator_os_maturity_score(self, account: dict[str, Any]) -> int:
        return self.account_health.creator_os_maturity_score(account)

    def creator_os_warming_stage(self, account: dict[str, Any], *, maturity_score: int) -> str:
        return self.account_health.creator_os_warming_stage(account, maturity_score=maturity_score)

    def creator_os_creative_risk(self, account: dict[str, Any]) -> dict[str, Any]:
        return self.account_health.creator_os_creative_risk(account)

    def creator_os_similarity_budget(self, account: dict[str, Any]) -> dict[str, Any]:
        return self.account_health.creator_os_similarity_budget(account)

    def creator_os_account_tier_from_health(self, account: dict[str, Any], *, trust_state: str, maturity_score: int) -> str:
        return self.account_health.creator_os_account_tier_from_health(account, trust_state=trust_state, maturity_score=maturity_score)

    def creator_os_cadence_overrides(self, account: dict[str, Any], *, warming_stage: str, maturity_score: int) -> dict[str, Any]:
        return self.account_health.creator_os_cadence_overrides(account, warming_stage=warming_stage, maturity_score=maturity_score)

    def creator_os_account_over_cadence(self, account: dict[str, Any], guidance: dict[str, Any]) -> bool:
        return self.account_health.creator_os_account_over_cadence(account, guidance)

    def creator_os_account_tier(self, account: dict[str, Any], *, state: str, blocked_reason: str) -> str:
        return self.account_health.creator_os_account_tier(account, state=state, blocked_reason=blocked_reason)

    def creator_os_numeric(self, value: Any) -> float:
        return self.account_health.creator_os_numeric(value)

    def creator_os_tier_posting_guidance(self, tier: str) -> dict[str, Any]:
        return self.account_health.creator_os_tier_posting_guidance(tier)

    def creator_os_blocked_reason(self, account: dict[str, Any], missed: list[dict[str, Any]]) -> str:
        return self.account_health.creator_os_blocked_reason(account, missed)

    def parent_factory_observed_discoverability_terms(self) -> list[dict[str, str]]:
        return self.discoverability.parent_factory_observed_discoverability_terms()

    def parent_factory_captured_discoverability_evidence(self) -> list[dict[str, str]]:
        return self.discoverability.parent_factory_captured_discoverability_evidence()

    def discoverability_text_values(self, payload: dict[str, Any]) -> list[str]:
        return self.discoverability.discoverability_text_values(payload)

    def discoverability_loss_category(self, reason: str, matched_text: str) -> str:
        return self.discoverability.discoverability_loss_category(reason, matched_text)

    def discoverability_prevention_stage(self, category: str) -> str:
        return self.discoverability.discoverability_prevention_stage(category)

    def discoverability_gate_fields(self, payload: dict[str, Any], allowed_fields: set[str]) -> list[tuple[str, str]]:
        return self.discoverability.discoverability_gate_fields(payload, allowed_fields)

    def discoverability_gate_result(self, gate: str, fields: list[tuple[str, str]]) -> dict[str, Any]:
        return self.discoverability.discoverability_gate_result(gate, fields)

    def discoverability_origin_stage(self, source_field: str, reason: str) -> str:
        return self.discoverability.discoverability_origin_stage(source_field, reason)

    def post_discoverability_downstream_confidence(self) -> dict[str, Any]:
        return self.discoverability.post_discoverability_downstream_confidence()

    def discoverability_evidence_for_fields(self, fields: list[tuple[str, str]]) -> list[dict[str, Any]]:
        return self.discoverability.discoverability_evidence_for_fields(fields)

    def register_surface_asset(
        self,
        *,
        input_path: Any,
        surface: str,
        creator: str,
        campaign_slug: str,
        instagram_post_caption: str | None = None,
        target_ratio: str | None = None,
        model_slug: str | None = None,
        operator: str | None = None,
        alt_text: list[str] | None = None,
        story_asset_class: str | None = None,
        story_cta_type: str | None = None,
        story_cta_text: str | None = None,
        story_cta_target_url: str | None = None,
        story_intent: str | None = None,
        story_goal: str | None = None,
        story_style: str | None = None,
        snapchat_username: str | None = None,
        snapchat_display_name: str | None = None,
        snapchat_cta_text: str | None = None,
    ) -> dict[str, Any]:
        return self.surface_registration.register_surface_asset(
            input_path=input_path,
            surface=surface,
            creator=creator,
            campaign_slug=campaign_slug,
            instagram_post_caption=instagram_post_caption,
            target_ratio=target_ratio,
            model_slug=model_slug,
            operator=operator,
            alt_text=alt_text,
            story_asset_class=story_asset_class,
            story_cta_type=story_cta_type,
            story_cta_text=story_cta_text,
            story_cta_target_url=story_cta_target_url,
            story_intent=story_intent,
            story_goal=story_goal,
            story_style=story_style,
            snapchat_username=snapchat_username,
            snapchat_display_name=snapchat_display_name,
            snapchat_cta_text=snapchat_cta_text,
        )

    def surface_registration_components(
        self,
        *,
        input_path: Any,
        surface: str,
        target_ratio: str | None,
    ) -> list[dict[str, Any]]:
        return self.surface_registration.surface_registration_components(
            input_path=input_path,
            surface=surface,
            target_ratio=target_ratio,
        )

    def surface_registration_component(self, path: Any, *, surface: str, target_ratio: str | None) -> dict[str, Any]:
        return self.surface_registration.surface_registration_component(path, surface=surface, target_ratio=target_ratio)

    def stage_surface_registration_file(
        self,
        path: Any,
        rendered_dir: Any,
        *,
        content_surface: str,
        content_hash: str,
        component_index: int,
    ) -> Any:
        return self.surface_registration.stage_surface_registration_file(
            path,
            rendered_dir,
            content_surface=content_surface,
            content_hash=content_hash,
            component_index=component_index,
        )

    def surface_registration_aspect_ratio_safe(self, ratio: Any, surface: str) -> bool:
        return self.surface_registration.aspect_ratio_safe(ratio, surface)

    def ig_media_type_for_surface(self, surface: str, media_type: str) -> str:
        return self.surface_registration.ig_media_type_for_surface(surface, media_type)

    def surface_handoff_readiness_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        return self.surface_handoff.surface_handoff_readiness_report(
            creator=creator,
            campaign_slug=campaign_slug,
            rendered_asset_id=rendered_asset_id,
        )

    def surface_draft_proof(
        self,
        *,
        creator: str | None = None,
        campaign: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        return self.surface_handoff.surface_draft_proof(
            creator=creator,
            campaign=campaign,
            rendered_asset_id=rendered_asset_id,
        )

    def surface_report_assets(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.surface_handoff.surface_report_assets(creator=creator, campaign_slug=campaign_slug)

    def build_surface_readiness(self, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.surface_handoff.build_surface_readiness(assets)

    def surface_draft_payload_for_readiness(self, readiness: dict[str, Any]) -> dict[str, Any]:
        return self.surface_handoff.surface_draft_payload_for_readiness(readiness)

    def surface_handoff_readiness_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.surface_handoff.surface_handoff_readiness_for_asset(asset)

    def requires_operator_visual_review_for_handoff(self, asset: dict[str, Any]) -> bool:
        return self.surface_handoff.requires_operator_visual_review_for_handoff(asset)

    def content_trust_status_blockers(
        self,
        asset: dict[str, Any],
        latest_audit: dict[str, Any] | None,
        caption_context: dict[str, Any] | None,
    ) -> tuple[list[str], dict[str, str]]:
        return self.surface_handoff.content_trust_status_blockers(asset, latest_audit, caption_context)

    def asset_matches_creator(self, asset: dict[str, Any], creator: str) -> bool:
        return self.surface_handoff.asset_matches_creator(asset, creator)

    def asset_components(self, rendered_asset_id: str) -> list[dict[str, Any]]:
        return self.surface_handoff.asset_components(rendered_asset_id)

    def surface_handoff_ig_media_type_for_surface(self, surface: str, media_type: str) -> str:
        return self.surface_handoff.ig_media_type_for_surface(surface, media_type)

    def surface_handoff_aspect_ratio_safe(self, ratio: Any, surface: str) -> bool:
        return self.surface_handoff.aspect_ratio_safe(ratio, surface)

    def allows_blank_instagram_post_caption(self, asset: dict[str, Any]) -> bool:
        return self.surface_handoff.allows_blank_instagram_post_caption(asset)

    def carousel_integrity_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        return self.carousel_integrity.carousel_integrity_report(
            creator=creator,
            campaign_slug=campaign_slug,
            rendered_asset_id=rendered_asset_id,
        )

    def carousel_child_metrics_plan(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        return self.carousel_integrity.carousel_child_metrics_plan(
            creator=creator,
            campaign_slug=campaign_slug,
            rendered_asset_id=rendered_asset_id,
        )

    def carousel_report_assets(
        self,
        *,
        creator: str | None,
        campaign_slug: str | None,
        rendered_asset_id: str | None,
    ) -> list[dict[str, Any]]:
        return self.carousel_integrity.carousel_report_assets(
            creator=creator,
            campaign_slug=campaign_slug,
            rendered_asset_id=rendered_asset_id,
        )

    def carousel_integrity_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.carousel_integrity.carousel_integrity_for_asset(asset)

    def carousel_component_signature(self, components: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.carousel_integrity.carousel_component_signature(components)

    def carousel_media_item_signature(self, media_items: Any) -> list[dict[str, Any]]:
        return self.carousel_integrity.carousel_media_item_signature(media_items)

    def carousel_signature_payload(
        self,
        signature: list[dict[str, Any]],
        *,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.carousel_integrity.carousel_signature_payload(signature, extra=extra)

    def carousel_boundary_result(
        self,
        boundary: str,
        before: list[dict[str, Any]],
        after: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self.carousel_integrity.carousel_boundary_result(boundary, before, after)

    def carousel_meta_child_payload_preview(
        self,
        *,
        asset: dict[str, Any],
        draft: dict[str, Any],
        components: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self.carousel_integrity.carousel_meta_child_payload_preview(asset=asset, draft=draft, components=components)

    def carousel_certification_proof(self, **kwargs: Any) -> dict[str, Any]:
        return self.carousel_integrity.carousel_certification_proof(**kwargs)

    def certification_asset_for_surface(self, surface: str, *, rendered_asset_id: str | None = None) -> dict[str, Any] | None:
        return self.carousel_integrity.certification_asset_for_surface(surface, rendered_asset_id=rendered_asset_id)

    def latest_proof_run_for_asset(self, rendered_asset_id: str) -> dict[str, Any] | None:
        return self.carousel_integrity.latest_proof_run_for_asset(rendered_asset_id)

    def latest_surface_metric_for_asset(self, rendered_asset_id: str, surface: str) -> dict[str, Any] | None:
        return self.carousel_integrity.latest_surface_metric_for_asset(rendered_asset_id, surface)

    def empty_surface_certification_audit(self, surface: str) -> dict[str, Any]:
        return self.carousel_integrity.empty_surface_certification_audit(surface)

    def surface_certification_audit(self, **kwargs: Any) -> dict[str, Any]:
        return self.carousel_integrity.surface_certification_audit(**kwargs)

    def carousel_production_readiness(self) -> dict[str, Any]:
        return self.carousel_integrity.carousel_production_readiness()

    def carousel_proof_gap_analysis(self) -> dict[str, Any]:
        return self.carousel_integrity.carousel_proof_gap_analysis()

    def winner_expansion_plan(
        self,
        *,
        creator: str | None = None,
        parent_asset_id: str,
        target_variants: int = 10,
        preset: str = "caption_safe_v2",
    ) -> dict[str, Any]:
        return self.winner_expansion.winner_expansion_plan(
            creator=creator,
            parent_asset_id=parent_asset_id,
            target_variants=target_variants,
            preset=preset,
        )

    def winner_expansion_report(
        self,
        campaign_slug: str,
        *,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        return self.winner_expansion.winner_expansion_report(
            campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )

    def winner_variant_candidate(self, variant_payload: dict[str, Any], rendered: dict[str, Any]) -> dict[str, Any]:
        return self.winner_expansion.winner_variant_candidate(variant_payload, rendered)

    def winner_variant_candidate_decision(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return self.winner_expansion.winner_variant_candidate_decision(candidate)

    def latest_variant_audit_result(self, variant_asset_id: str) -> dict[str, Any]:
        return self.winner_expansion.latest_variant_audit_result(variant_asset_id)

    def contentforge_result_from_operations(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        return self.winner_expansion.contentforge_result_from_operations(operations)

    def operation_family_from_operations(self, operations: list[dict[str, Any]]) -> str | None:
        return self.winner_expansion.operation_family_from_operations(operations)

    def score_value(self, value: Any) -> int:
        return self.winner_expansion.score_value(value)

    def variant_inventory_primary_blocking_reason(self, failures: list[str]) -> str:
        return self.winner_expansion.variant_inventory_primary_blocking_reason(failures)

    def variant_inventory_quality_risk(self, parent_asset_id: str) -> str:
        return self.winner_expansion.variant_inventory_quality_risk(parent_asset_id)

    def variant_inventory_winner_rank(
        self,
        *,
        campaign_id: str,
        parent_asset_id: str,
        parent_reel_id: str,
    ) -> dict[str, Any]:
        return self.winner_expansion.variant_inventory_winner_rank(
            campaign_id=campaign_id,
            parent_asset_id=parent_asset_id,
            parent_reel_id=parent_reel_id,
        )

    def variant_asset_payload(self, row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
        return self.winner_expansion.variant_asset_payload(row)

    def winner_registry(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        return self.creative_knowledge.winner_registry(
            creator=creator,
            campaign_slug=campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )

    def concept_registry(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        return self.creative_knowledge.concept_registry(
            creator=creator,
            campaign_slug=campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )

    def winner_patterns(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        return self.creative_knowledge.winner_patterns(
            creator=creator,
            campaign_slug=campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )

    def winner_knowledge_base(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        return self.creative_knowledge.winner_knowledge_base(
            creator=creator,
            campaign_slug=campaign_slug,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )

    def winner_memory_rows(self, *, creator: str, campaign_slug: str | None = None) -> list[dict[str, Any]]:
        return self.creative_knowledge.winner_memory_rows(creator=creator, campaign_slug=campaign_slug)

    def winner_memory_item(
        self,
        row: dict[str, Any],
        *,
        min_views: int,
        min_reach: int,
        min_followers: int,
    ) -> dict[str, Any] | None:
        return self.creative_knowledge.winner_memory_item(
            row,
            min_views=min_views,
            min_reach=min_reach,
            min_followers=min_followers,
        )

    def winner_concept_name(self, row: dict[str, Any]) -> str:
        return self.creative_knowledge.winner_concept_name(row)

    def posting_window_label(self, published_at: Any) -> str:
        return self.creative_knowledge.posting_window_label(published_at)

    def winner_pattern_group(
        self,
        items: list[dict[str, Any]],
        *,
        key_field: str,
        label_field: str | None,
        output_key: str,
        output_label: str | None,
    ) -> list[dict[str, Any]]:
        return self.creative_knowledge.winner_pattern_group(
            items,
            key_field=key_field,
            label_field=label_field,
            output_key=output_key,
            output_label=output_label,
        )

    def tribev2_reel_analysis(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        minimum_sample_size: int = 3,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self.tribev2.tribev2_reel_analysis(
            creator=creator,
            campaign_slug=campaign_slug,
            minimum_sample_size=minimum_sample_size,
            limit=limit,
        )

    def tribev2_reel_review(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        sort_by: str = "meanAbsActivation",
        bucket: str = "top",
        limit: int = 12,
        contact_sheet: bool = False,
        show_metrics: bool | None = None,
        show_tribe_score: bool = True,
        blind_mode: bool = False,
    ) -> dict[str, Any]:
        return self.tribev2.tribev2_reel_review(
            creator=creator,
            campaign_slug=campaign_slug,
            sort_by=sort_by,
            bucket=bucket,
            limit=limit,
            contact_sheet=contact_sheet,
            show_metrics=show_metrics,
            show_tribe_score=show_tribe_score,
            blind_mode=blind_mode,
        )

    def tribev2_holdout_pilot_review(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
        limit: int = 20,
        contact_sheet: bool = False,
    ) -> dict[str, Any]:
        return self.tribev2.tribev2_holdout_pilot_review(
            creator=creator,
            campaign_slug=campaign_slug,
            limit=limit,
            contact_sheet=contact_sheet,
        )

    def tribev2_review_both_bucket(self, ranked: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        return self.tribev2.tribev2_review_both_bucket(ranked, limit)

    def tribev2_review_item(
        self,
        row: dict[str, Any],
        *,
        rank: int,
        sort_field: str,
        show_metrics: bool = True,
        show_tribe_score: bool = True,
    ) -> dict[str, Any]:
        return self.tribev2.tribev2_review_item(
            row,
            rank=rank,
            sort_field=sort_field,
            show_metrics=show_metrics,
            show_tribe_score=show_tribe_score,
        )

    def tribev2_holdout_bucket_rows(self, ranked: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        return self.tribev2.tribev2_holdout_bucket_rows(ranked)

    def tribev2_holdout_bucket_summary(self, name: str, rows: list[dict[str, Any]], *, limit: int) -> dict[str, Any]:
        return self.tribev2.tribev2_holdout_bucket_summary(name, rows, limit=limit)

    def tribev2_average_metrics(self, rows: list[dict[str, Any]]) -> dict[str, float]:
        return self.tribev2.tribev2_average_metrics(rows)

    def tribev2_average_scores(self, rows: list[dict[str, Any]]) -> dict[str, float]:
        return self.tribev2.tribev2_average_scores(rows)

    def average_row_field(self, rows: list[dict[str, Any]], field: str) -> float:
        return self.tribev2.average_row_field(rows, field)

    def tribev2_preview_path(self, row: dict[str, Any]) -> str:
        return self.tribev2.tribev2_preview_path(row)

    def write_tribev2_review_contact_sheet(
        self,
        items: list[dict[str, Any]],
        *,
        creator: str,
        title: str = "TRIBE v2 Review",
        blind_mode: bool = False,
        show_metrics: bool = True,
        show_tribe_score: bool = True,
    ) -> str:
        return self.tribev2.write_tribev2_review_contact_sheet(
            items,
            creator=creator,
            title=title,
            blind_mode=blind_mode,
            show_metrics=show_metrics,
            show_tribe_score=show_tribe_score,
        )

    def write_tribev2_holdout_contact_sheet(self, buckets: dict[str, Any], *, creator: str) -> str:
        return self.tribev2.write_tribev2_holdout_contact_sheet(buckets, creator=creator)

    def tribev2_contact_sheet_cards(
        self,
        items: list[dict[str, Any]],
        root: Any,
        *,
        show_metrics: bool,
        show_tribe_score: bool,
    ) -> list[str]:
        return self.tribev2.tribev2_contact_sheet_cards(
            items,
            root,
            show_metrics=show_metrics,
            show_tribe_score=show_tribe_score,
        )

    def tribev2_contact_sheet_html(self, *, title: str, body: str) -> str:
        return self.tribev2.tribev2_contact_sheet_html(title=title, body=body)

    def tribev2_extract_thumbnail(self, preview_path: str, output_dir: Any, item: dict[str, Any]) -> str:
        return self.tribev2.tribev2_extract_thumbnail(preview_path, output_dir, item)

    def tribev2_reel_analysis_rows(self, *, creator: str, campaign_slug: str | None = None) -> list[dict[str, Any]]:
        return self.tribev2.tribev2_reel_analysis_rows(creator=creator, campaign_slug=campaign_slug)

    def tribev2_score_for_snapshot(self, row: dict[str, Any]) -> dict[str, Any] | None:
        return self.tribev2.tribev2_score_for_snapshot(row)

    def pearson_correlation(self, xs: list[float], ys: list[float]) -> float | None:
        return self.tribev2.pearson_correlation(xs, ys)

    def tribev2_bucket_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return self.tribev2.tribev2_bucket_summary(rows)

    def tribev2_bucket_lift(self, top: dict[str, Any], bottom: dict[str, Any]) -> dict[str, Any]:
        return self.tribev2.tribev2_bucket_lift(top, bottom)

    def tribev2_metric_quality(self, rows: list[dict[str, Any]], metric_fields: list[str]) -> dict[str, Any]:
        return self.tribev2.tribev2_metric_quality(rows, metric_fields)

    def tribev2_signal_summary(
        self,
        correlations: dict[str, dict[str, float | None]],
        *,
        sample_size: int,
        metric_quality: dict[str, Any],
    ) -> dict[str, Any]:
        return self.tribev2.tribev2_signal_summary(
            correlations,
            sample_size=sample_size,
            metric_quality=metric_quality,
        )

    def tribev2_confidence_level(self, sample_size: int, statistically_interesting: bool) -> str:
        return self.tribev2.tribev2_confidence_level(sample_size, statistically_interesting)

    def operator_inventory_review_batch_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.operator_review.operator_inventory_review_batch_plan(**kwargs)

    def operator_inventory_review_batch_summary(self, **kwargs: Any) -> dict[str, Any]:
        return self.operator_review.operator_inventory_review_batch_summary(**kwargs)

    def operator_review_simulator(self, **kwargs: Any) -> dict[str, Any]:
        return self.operator_review.operator_review_simulator(**kwargs)

    def operator_review_scenarios(self, **kwargs: Any) -> dict[str, Any]:
        return self.operator_review.operator_review_scenarios(**kwargs)

    def operator_review_efficiency_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.operator_review.operator_review_efficiency_report(**kwargs)

    def operator_review_minimum_certification_path(self, **kwargs: Any) -> dict[str, Any]:
        return self.operator_review.operator_review_minimum_certification_path(**kwargs)

    def operator_review_master_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.operator_review.operator_review_master_report(**kwargs)

    def operator_review_execution_order(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.operator_review.operator_review_execution_order(rows)

    def operator_review_batch_priority(self, repair_classes: list[str]) -> int:
        return self.operator_review.operator_review_batch_priority(repair_classes)

    def operator_review_batch_type(self, repair_classes: list[str]) -> str:
        return self.operator_review.operator_review_batch_type(repair_classes)

    def operator_review_scenario(
        self,
        ordered_rows: list[dict[str, Any]],
        *,
        current_inventory: int,
        required_inventory: int,
        approval_rate: int,
    ) -> dict[str, Any]:
        return self.operator_review.operator_review_scenario(
            ordered_rows,
            current_inventory=current_inventory,
            required_inventory=required_inventory,
            approval_rate=approval_rate,
        )

    def operator_review_minimum_path(
        self,
        ordered_rows: list[dict[str, Any]],
        *,
        current_inventory: int,
        required_inventory: int,
    ) -> dict[str, Any]:
        return self.operator_review.operator_review_minimum_path(
            ordered_rows,
            current_inventory=current_inventory,
            required_inventory=required_inventory,
        )

    def operator_review_highest_roi_batch_type(self, rows: list[dict[str, Any]]) -> str:
        return self.operator_review.operator_review_highest_roi_batch_type(rows)

    def operator_review_lowest_risk_batch_type(self, rows: list[dict[str, Any]]) -> str:
        return self.operator_review.operator_review_lowest_risk_batch_type(rows)

    def operator_review_batch_order_labels(self, rows: list[dict[str, Any]]) -> list[str]:
        return self.operator_review.operator_review_batch_order_labels(rows)

    def operator_review_candidate_eligible(self, asset: dict[str, Any]) -> bool:
        return self.operator_review.operator_review_candidate_eligible(asset)

    def operator_review_candidate_row(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.operator_review.operator_review_candidate_row(asset)

    def operator_review_actions(self, repair_classes: list[str]) -> list[str]:
        return self.operator_review.operator_review_actions(repair_classes)

    def campaign_by_slug(self, slug: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM campaigns WHERE slug = ?", (self._slugify(slug),)).fetchone()
        if not row:
            raise ValueError(f"campaign not found: {slug}")
        return dict(row)

    def rendered_asset(self, rendered_asset_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM rendered_assets WHERE id = ?", (rendered_asset_id,)).fetchone()
        if not row:
            raise ValueError(f"rendered asset not found: {rendered_asset_id}")
        return dict(row)
