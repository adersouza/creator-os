from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .acceptance_suite import AcceptanceSuiteRepository
from .account_health import AccountHealthRepository
from .account_memory import AccountMemoryRepository
from .account_planning import AccountPlanningRepository
from .archive_quality import ArchiveQualityRepository
from .asset_import import AssetImportRepository
from .audio_operations import AudioOperationsRepository
from .audio_recommendations import AudioRecommendationRepository
from .autonomy import AutonomyPolicyRepository
from .campaign_overview import CampaignOverviewRepository
from .caption import CaptionFamilyRepository
from .carousel_integrity import CarouselIntegrityRepository
from .certification import CertificationRepository
from .config import Settings
from .contentforge_visual_qc import ContentForgeVisualQCRepository
from .core_complexity import CoreComplexityRepository
from .cost_tracker import ensure_cost_table, record_ai_cost
from .creative_knowledge import CreativeKnowledgeRepository
from .creative_planning import CreativePlanningRepository
from .creator_os_drafts import CreatorOSDraftRepository
from .creator_os_recommendations import CreatorOSRecommendationRepository
from .daily_plan import DailyPlanRepository
from .decision_ledger import DecisionLedgerRepository
from .discoverability import DiscoverabilityRepository
from .distribution import DistributionRepository
from .draft_inventory_gap import DraftInventoryGapRepository
from .events import EventRepository
from .exceptions import ExceptionRepository
from .execution_readiness import ExecutionReadinessRepository
from .export_summary import ExportSummaryRepository
from .finished_video import FinishedVideoRepository
from .fresh_reel_production import FreshReelProductionRepository
from .graph import GraphRepository
from .inventory_perceptual import InventoryPerceptualRepository
from .inventory_planning import InventoryPlanningRepository
from .inventory_recovery import InventoryRecoveryRepository
from .inventory_reservations import InventoryReservationRepository
from .learning_score import account_reward_baselines as _account_reward_baselines
from .lifecycle_reporting import LifecycleReportingRepository
from .live_acceptance import LiveAcceptanceRepository
from .live_scale import LiveScaleRepository
from .make_batch import MakeBatchRepository
from .models import ModelRepository
from .multi_blocker_unlock import MultiBlockerUnlockRepository
from .operational_proofs import OperationalProofRepository
from .operator_review import OperatorReviewRepository
from .parent_factory_planning import ParentFactoryPlanningRepository
from .parent_factory_reports import ParentFactoryReportRepository
from .parent_factory_trials import ParentFactoryTrialRepository
from .performance_summary import PerformanceSummaryRepository
from .publishability import PublishabilityRepository
from .readiness_report import ReadinessReportRepository
from .recommendation_accuracy import RecommendationAccuracyRepository
from .recommendations import RecommendationRepository
from .recommended_inventory_request import RecommendedInventoryRequestRepository
from .reel_execution import ReelExecutionRepository
from .reel_factory_reports import ReelFactoryReportRepository
from .reference import ReferenceRepository
from .schedule_safe_production import ScheduleSafeProductionRepository
from .story_management import StoryManagementRepository
from .surface_handoff import SurfaceHandoffRepository
from .surface_inventory import SurfaceInventoryRepository
from .surface_registration import SurfaceRegistrationRepository
from .surface_requirements import SurfaceRequirementsRepository
from .surface_summary import SurfaceSummaryRepository
from .tribev2 import TribeV2Repository
from .variant_lineage import VariantLineageRepository
from .winner_expansion import WinnerExpansionRepository


@dataclass(frozen=True)
class CampaignContext:
    conn: sqlite3.Connection
    settings: Settings


class CampaignDomainServices:
    def __init__(
        self,
        context: CampaignContext,
        *,
        factory_context: Any,
        new_id: Callable[[str], str],
        new_graph_id: Callable[[str], str],
        slugify: Callable[[str], str],
        sanitize_for_storage: Callable[[Any], Any],
        utc_now: Callable[[], str],
        media_type_for_path: Callable[[Any], str],
        sha256_file: Callable[[Any], str],
        probe_image_shape: Callable[[Any], dict[str, Any]],
        probe_video_shape: Callable[[Any], dict[str, Any]],
        probe_video_metadata: Callable[[Any], dict[str, Any]],
        read_png_rgb_pixels: Callable[[Any], dict[str, Any]],
        ratio_label_from_shape: Callable[[int | None, int | None], str | None],
        dashboard_rendered_asset: Callable[[dict[str, Any]], dict[str, Any]],
        audio_recommendations_for_asset: Callable[..., dict[str, Any]],
        generated_asset_lineage: Callable[
            [dict[str, Any], dict[str, Any] | None], dict[str, Any]
        ],
        prepare_reel_inputs: Callable[..., dict[str, Any]],
        reel_factory_python: Callable[[Any], str],
        make_batch: Callable[..., dict[str, Any]],
        load_source_lineage: Callable[[Any | None], dict[str, Any]],
        discoverability_generation_gate: Callable[[dict[str, Any]], dict[str, Any]],
        discoverability_pre_render_gate: Callable[[dict[str, Any]], dict[str, Any]],
        discoverability_safe_content_contract: Callable[..., dict[str, Any]],
        capture_discoverability_gate_rejection_evidence: Callable[..., dict[str, Any]],
        reference_hook_fallbacks: tuple[str, ...],
        normalize_content_surface: Callable[[str | None], str],
        urlopen: Callable[..., Any],
        concept_for_parent_asset: Callable[[str], dict[str, Any] | None],
        explain_publishability: Callable[[str], dict[str, Any]],
        capture_publishability_rejection_evidence_from_result: Callable[
            ..., dict[str, Any]
        ],
        distribution_plan_payload: Callable[[dict[str, Any]], dict[str, Any]],
        verification_id: Callable[..., str],
        caption_lineage_sidecar: Callable[[str], dict[str, Any]],
        active_quarantine_for_asset: Callable[[str], dict[str, Any] | None],
        audio_segment_for_asset: Callable[[dict[str, Any]], dict[str, Any] | None],
        cover_frame_for_asset: Callable[
            [dict[str, Any], dict[str, Any] | None], dict[str, Any] | None
        ],
        audio_intent_claims_embedded_media: Callable[[dict[str, Any]], bool],
        embedded_audio_verified: Callable[[str], bool | None],
        discoverability_evidence_for_fields: Callable[
            [list[tuple[str, str]]], list[dict[str, Any]]
        ],
        reference_hook_is_schedule_safe: Callable[[str], bool],
        audio_intent_is_attached: Callable[[dict[str, Any], str | None], bool],
        requires_operator_visual_review_for_handoff: Callable[[dict[str, Any]], bool],
        ig_media_type_for_surface: Callable[[str, str], str],
        surface_handoff_readiness_report: Callable[..., dict[str, Any]],
        recommend_audio: Callable[..., dict[str, Any]],
        select_audio_for_recommendation: Callable[..., dict[str, Any]],
        surface_handoff_readiness_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        audio_selection_for_asset: Callable[
            [dict[str, Any]], tuple[dict[str, Any], str | None]
        ],
        surface_report_assets: Callable[..., list[dict[str, Any]]],
        build_surface_readiness: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        asset_matches_creator: Callable[[dict[str, Any], str], bool],
        latest_audit_for_asset: Callable[[str], dict[str, Any] | None],
        content_trust_status_blockers: Callable[..., tuple[list[str], dict[str, str]]],
        compute_pdq_fingerprint: Callable[..., dict[str, Any]],
        pdq_hamming_distance: Callable[[str, str], int | None],
        surface_draft_proof: Callable[..., dict[str, Any]],
        asset_components: Callable[[str], list[dict[str, Any]]],
        instagram_post_caption_for_asset: Callable[..., dict[str, Any]],
        register_variant_asset: Callable[..., dict[str, Any]],
        suggest_simple_instagram_post_caption: Callable[..., str],
        text_hash: Callable[[str], str],
        variant_lineage_for_asset: Callable[[str], dict[str, Any]],
        story_quality_gate_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        story_style_value: Callable[[dict[str, Any]], str | None],
        story_intent_value: Callable[[dict[str, Any]], str | None],
        ranking: Callable[[str], dict[str, Any]],
        dashboard: Callable[[str], dict[str, Any]],
        creator_os_account_health_report: Callable[..., dict[str, Any]],
        creator_os_account_health_decision: Callable[..., dict[str, Any]],
        creator_os_tier_posting_guidance: Callable[[str], dict[str, Any]],
        creator_os_account_tier_summary: Callable[
            [list[dict[str, Any]]], dict[str, Any]
        ],
        creator_os_account_health_summary: Callable[
            [list[dict[str, Any]]], dict[str, Any]
        ],
        creator_os_winner_recommendations: Callable[..., list[dict[str, Any]]],
        creator_os_recommended_inventory: Callable[..., list[dict[str, Any]]],
        recommendation_explainability: Callable[..., dict[str, Any]],
        build_creative_performance_analysis: Callable[..., dict[str, Any]],
        build_creative_knowledge_base: Callable[..., dict[str, Any]],
        creative_knowledge_rows: Callable[..., list[dict[str, Any]]],
        creative_knowledge_result: Callable[[dict[str, Any]], dict[str, Any]],
        creative_knowledge_score_weights: Callable[[], dict[str, float]],
        creative_result_group: Callable[..., list[dict[str, Any]]],
        creative_knowledge_results_for_report: Callable[..., list[dict[str, Any]]],
        creative_dimension_label: Callable[[str], str],
        learning_confidence_classification: Callable[
            [list[dict[str, Any]]], dict[str, Any]
        ],
        creative_fatigue_signals: Callable[..., list[dict[str, Any]]],
        creative_surface_rows: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        recommendation_quality_bucket: Callable[[dict[str, Any]], str],
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
        surface_readiness_scorecard: Callable[[], dict[str, Any]],
        certification_asset_for_surface: Callable[..., dict[str, Any] | None],
        latest_proof_run_for_asset: Callable[[str], dict[str, Any] | None],
        latest_surface_metric_for_asset: Callable[[str, str], dict[str, Any] | None],
        empty_surface_certification_audit: Callable[[str], dict[str, Any]],
        surface_certification_audit: Callable[..., dict[str, Any]],
        audio_selection_payload: Callable[[str], dict[str, Any]],
        audio_workflow_summary: Callable[[list[dict[str, Any]]], dict[str, Any]],
        events_for_asset: Callable[..., list[dict[str, Any]]],
        story_mix_plan: Callable[..., dict[str, Any]],
        story_calendar_plan: Callable[..., dict[str, Any]],
        json_load: Callable[[Any, Any], Any],
        parent_factory_yield_waterfall: Callable[..., dict[str, Any]],
        exception_next_action: Callable[[str], str],
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
        conn = context.conn
        settings = context.settings
        self.context = context
        self.conn = conn
        self.settings = settings
        self.factory_context = factory_context
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
        self.performance_summary_repo = PerformanceSummaryRepository(
            conn,
            campaign_by_slug=self.campaign_by_slug,
            slugify=slugify,
        )
        self.export_summary = ExportSummaryRepository(factory_context)
        self.reel_execution = ReelExecutionRepository(
            conn,
            settings,
            new_id=new_id,
            utc_now=utc_now,
            sha256_file=sha256_file,
            sanitize_for_storage=sanitize_for_storage,
            text_hash=text_hash,
            campaign_by_slug=self.campaign_by_slug,
            assets_for_campaign=self.asset_import.assets_for_campaign,
            campaign_dirs=self.campaign_dirs,
            reel_factory_python=reel_factory_python,
            create_pipeline_job=self.events.create_pipeline_job,
            start_pipeline_job=self.events.start_pipeline_job,
            finish_pipeline_job=self.events.finish_pipeline_job,
            fail_pipeline_job=self.events.fail_pipeline_job,
            record_event=self.events.record_event,
            ensure_graph_node=self.graph.ensure_graph_node,
            ensure_graph_edge=self.graph.ensure_graph_edge,
            graph_id_for=self.graph.graph_id_for,
            discoverability_generation_gate=discoverability_generation_gate,
            capture_discoverability_gate_rejection_evidence=capture_discoverability_gate_rejection_evidence,
            suggest_simple_instagram_post_caption=suggest_simple_instagram_post_caption,
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
            rendered_for_campaign=self.rendered_for_campaign,
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
        self.make_batch_repo = MakeBatchRepository(
            conn,
            settings,
            factory_context=factory_context,
            new_id=new_id,
            utc_now=utc_now,
            sha256_file=sha256_file,
            media_type_for_path=media_type_for_path,
            reel_factory_python=reel_factory_python,
            subprocess_run=lambda *args, **kwargs: __import__("subprocess").run(
                *args, **kwargs
            ),
            create_pipeline_job=self.events.create_pipeline_job,
            start_pipeline_job=self.events.start_pipeline_job,
            set_pipeline_job_campaign=self.events.set_pipeline_job_campaign,
            finish_pipeline_job=self.events.finish_pipeline_job,
            fail_pipeline_job=self.events.fail_pipeline_job,
            record_event=self.events.record_event,
            import_folder=self.asset_import.import_folder,
            reference_patterns=self.reference.reference_patterns,
            import_reference_bank=self.reference.import_reference_bank,
            select_reference_pattern=self.reference.select_reference_pattern,
            prepare_reel_from_reference=self.reference.prepare_reel_from_reference,
            finished_video_hooks=lambda *args, **kwargs: (
                self.finished_video.finished_video_hooks(*args, **kwargs)
            ),
            finished_video_caption_band=lambda *args, **kwargs: (
                self.finished_video.finished_video_caption_band(*args, **kwargs)
            ),
            finished_video_caption_font=lambda *args, **kwargs: (
                self.finished_video.finished_video_caption_font(*args, **kwargs)
            ),
            prepare_reel_inputs=prepare_reel_inputs,
            run_reel_factory=lambda *args, **kwargs: (
                self.reel_execution.run_reel_factory(*args, **kwargs)
            ),
            sync_reel_outputs=lambda *args, **kwargs: (
                self.reel_execution.sync_reel_outputs(*args, **kwargs)
            ),
            dashboard=dashboard,
            campaign_health=lambda campaign_slug: (
                self.campaign_overview.campaign_health(campaign_slug)
            ),
            ranking=ranking,
            campaign_by_slug=self.campaign_by_slug,
            model_slug_for_campaign=self.reel_execution.model_slug_for_campaign,
            campaign_dirs=self.campaign_dirs,
            assets_for_campaign=self.asset_import.assets_for_campaign,
        )
        self.finished_video = FinishedVideoRepository(
            conn,
            settings,
            slugify=slugify,
            new_id=new_id,
            media_type_for_path=media_type_for_path,
            sha256_file=sha256_file,
            probe_video_shape=probe_video_shape,
            text_hash=text_hash,
            json_load=json_load,
            utc_now=utc_now,
            upsert_model=self.models.upsert_model,
            upsert_campaign=self.models.upsert_campaign,
            campaign_dirs=self.campaign_dirs,
            make_batch=make_batch,
            creative_plan=self.creative_planning.creative_plan,
            load_source_lineage=load_source_lineage,
            discoverability_pre_render_gate=discoverability_pre_render_gate,
            capture_discoverability_gate_rejection_evidence=capture_discoverability_gate_rejection_evidence,
            explain_publishability=explain_publishability,
            capture_publishability_rejection_evidence_from_result=capture_publishability_rejection_evidence_from_result,
            record_creative_plan_event=self.creative_planning.record_creative_plan_event,
            record_event=self.events.record_event,
            ensure_graph_node=self.graph.ensure_graph_node,
            ensure_graph_edge=self.graph.ensure_graph_edge,
            graph_id_for=self.graph.graph_id_for,
            ensure_cost_table=ensure_cost_table,
            record_ai_cost=record_ai_cost,
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
        self.variant_lineage = VariantLineageRepository(
            conn,
            settings,
            utc_now=utc_now,
            sha256_file=sha256_file,
            sanitize_for_storage=sanitize_for_storage,
            normalize_content_surface=normalize_content_surface,
            urlopen=urlopen,
            campaign_by_slug=self.campaign_by_slug,
            rendered_asset=self.rendered_asset,
            explain_publishability=explain_publishability,
            capture_publishability_rejection_evidence_from_result=capture_publishability_rejection_evidence_from_result,
            surface_handoff_readiness_for_asset=surface_handoff_readiness_for_asset,
            audio_selection_for_asset=audio_selection_for_asset,
            record_event=self.events.record_event,
            caption_version_by_id=self.caption_family.caption_version_by_id,
            model_slug_for_campaign=self.reel_execution.model_slug_for_campaign,
            campaign_dirs=self.campaign_dirs,
            latest_audit_for_asset=latest_audit_for_asset,
            content_trust_status_blockers=content_trust_status_blockers,
            instagram_post_caption_for_asset=instagram_post_caption_for_asset,
            performance_snapshot_payload=self.performance_summary_repo.performance_snapshot_payload,
            aggregate_performance=self.performance_summary_repo.aggregate_performance,
            register_variant_asset=register_variant_asset,
        )
        self.publishability = PublishabilityRepository(
            conn,
            utc_now=utc_now,
            sanitize_for_storage=sanitize_for_storage,
            normalize_content_surface=normalize_content_surface,
            rendered_asset=self.rendered_asset,
            record_event=self.events.record_event,
            distribution_plan_payload=distribution_plan_payload,
            audit_report_payload=self.audit_report_payload,
            latest_audit_for_asset=latest_audit_for_asset,
            verification_id=verification_id,
            text_hash=text_hash,
            caption_lineage_sidecar=caption_lineage_sidecar,
            variant_lineage_for_asset=self.variant_lineage.variant_lineage_for_asset,
            active_quarantine_for_asset=active_quarantine_for_asset,
            audio_selection_for_asset=audio_selection_for_asset,
            audio_segment_for_asset=audio_segment_for_asset,
            cover_frame_for_asset=cover_frame_for_asset,
            instagram_post_caption_for_asset=instagram_post_caption_for_asset,
            content_trust_status_blockers=content_trust_status_blockers,
            audio_intent_claims_embedded_media=audio_intent_claims_embedded_media,
            embedded_audio_verified=embedded_audio_verified,
            discoverability_safe_content_contract=discoverability_safe_content_contract,
            discoverability_evidence_for_fields=discoverability_evidence_for_fields,
            reference_hook_is_schedule_safe=reference_hook_is_schedule_safe,
            audio_intent_is_attached=audio_intent_is_attached,
            requires_operator_visual_review_for_handoff=requires_operator_visual_review_for_handoff,
            surface_report_assets=surface_report_assets,
            ig_media_type_for_surface=ig_media_type_for_surface,
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
            rendered_for_campaign=self.rendered_for_campaign,
            dashboard_rendered_asset=dashboard_rendered_asset,
            ig_media_type_for_surface=ig_media_type_for_surface,
            variant_lineage_for_asset=variant_lineage_for_asset,
            ranking=ranking,
            dashboard=dashboard,
            model_account_profile=self.models.model_account_profile,
            account_compatible_with_model=self.models.account_compatible_with_model,
        )
        self.surface_inventory = SurfaceInventoryRepository(
            conn,
            slugify=slugify,
            creator_label=self.creator_label,
            normalize_content_surface=normalize_content_surface,
            surface_report_assets=surface_report_assets,
            build_surface_readiness=build_surface_readiness,
            build_surface_inventory_for_audit=build_surface_inventory,
            content_surfaces=content_surfaces,
        )
        self.surface_requirements = SurfaceRequirementsRepository(
            conn,
            creator_label=self.creator_label,
            normalize_content_surface=normalize_content_surface,
            multi_surface_inventory_audit=self.surface_inventory.multi_surface_inventory_audit,
            build_surface_inventory=build_surface_inventory,
            content_surfaces=content_surfaces,
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
            performance_snapshot_payload=self.performance_summary_repo.performance_snapshot_payload,
            account_reward_baselines=self.account_reward_baselines,
            aggregate_performance=self.performance_summary_repo.aggregate_performance,
            performance_quality_score=self.performance_summary_repo.performance_quality_score,
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
            list_campaigns=self.list_campaigns,
            campaign_by_slug=self.campaign_by_slug,
            assets_for_campaign=self.asset_import.assets_for_campaign,
            rendered_for_campaign=self.rendered_for_campaign,
            dashboard_rendered_asset=dashboard_rendered_asset,
            jobs_for_campaign=self.events.jobs_for_campaign,
            audio_workflow_summary=audio_workflow_summary,
            daily_production_counters=self.export_summary.daily_production_counters,
            creative_plan_for_campaign=self.creative_planning.creative_plan_for_campaign,
            events_for_campaign=self.events.events_for_campaign,
            distribution_summary=self.distribution.distribution_summary,
            trust_summary=lambda campaign_slug: self.exceptions.trust_summary(
                campaign_slug
            ),
            rendered_asset=self.rendered_asset,
            record_event=self.events.record_event,
            events_for_asset=events_for_asset,
            performance_for_asset=self.performance_summary_repo.performance_for_asset,
            ranking=ranking,
            audit_report_payload=self.audit_report_payload,
        )
        self.account_planning = AccountPlanningRepository(
            conn,
            utc_now=utc_now,
            campaign_by_slug=self.campaign_by_slug,
            assignments_for_campaign=self.campaign_overview.assignments_for_campaign,
            assignments_for_asset=self.campaign_overview.assignments_for_asset,
            distribution_plans_for_campaign=self.distribution.distribution_plans_for_campaign,
            account_compatible_with_model=self.models.account_compatible_with_model,
            dashboard=dashboard,
            ranking=ranking,
            rendered_for_campaign=self.rendered_for_campaign,
            dashboard_rendered_asset=dashboard_rendered_asset,
            active_reference_pattern_for_campaign=self.reference.active_reference_pattern_for_campaign,
            audio_recommendations_for_asset=audio_recommendations_for_asset,
            generated_asset_lineage=generated_asset_lineage,
            audit_report_payload=self.audit_report_payload,
            performance_for_asset=self.performance_summary_repo.performance_for_asset,
            local_export_readiness=self.publishability.local_export_readiness,
            recommend_audio=recommend_audio,
            performance_quality_score=self.performance_summary_repo.performance_quality_score,
        )
        self.inventory_perceptual = InventoryPerceptualRepository(
            conn,
            rendered_asset=self.rendered_asset,
            compute_pdq_fingerprint=compute_pdq_fingerprint,
            pdq_hamming_distance=pdq_hamming_distance,
            sanitize_for_storage=sanitize_for_storage,
        )
        self.inventory_reservations = InventoryReservationRepository(
            conn,
            new_id=new_id,
            utc_now=utc_now,
            normalize_content_surface=normalize_content_surface,
            rendered_asset=self.rendered_asset,
            ensure_rendered_asset_perceptual_metadata=self.inventory_perceptual.ensure_rendered_asset_perceptual_metadata,
            asset_uniqueness_values=self.inventory_perceptual.asset_uniqueness_values,
            default_reservation_ttl_days=7,
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
            normalize_content_surface=normalize_content_surface,
        )
        self.recommendations = RecommendationRepository(
            conn,
            slugify=slugify,
            sanitize_for_storage=sanitize_for_storage,
            utc_now=utc_now,
            campaign_by_slug=self.campaign_by_slug,
            graph_id_for=self.graph.graph_id_for,
            ensure_graph_node=self.graph.ensure_graph_node,
            ensure_graph_edge=self.graph.ensure_graph_edge,
            ensure_graph_edge_strict=self.ensure_graph_edge_strict,
            record_event=self.events.record_event,
            performance_summary=self.performance_summary_repo.performance_summary,
            ranking=ranking,
            active_reference_pattern_for_campaign=self.reference.active_reference_pattern_for_campaign,
            reference_pattern_payload=self.reference.reference_pattern_payload,
            performance_snapshot_payload=self.performance_summary_repo.performance_snapshot_payload,
            account_reward_baselines=self.account_reward_baselines,
            aggregate_performance=self.performance_summary_repo.aggregate_performance,
            performance_quality_score=self.performance_summary_repo.performance_quality_score,
            performance_planning_score=self.performance_summary_repo.performance_planning_score,
            rendered_asset=self.rendered_asset,
            dashboard_rendered_asset=dashboard_rendered_asset,
            assignments_for_asset=self.campaign_overview.assignments_for_asset,
            account_memory_for=self.account_memory.account_memory_for,
            recommend_audio=recommend_audio,
            autonomy_level=self.autonomy.autonomy_level,
            create_exception=self.exceptions.create_exception,
            exception_payload=self.exceptions.exception_payload,
            create_pipeline_job=self.events.create_pipeline_job,
            start_pipeline_job=self.events.start_pipeline_job,
            finish_pipeline_job=self.events.finish_pipeline_job,
            fail_pipeline_job=self.events.fail_pipeline_job,
            prepare_reel_from_reference=self.reference.prepare_reel_from_reference,
            run_reel_factory=self.reel_execution.run_reel_factory,
            sync_reel_outputs=self.reel_execution.sync_reel_outputs,
        )
        self.audio_recommendations = AudioRecommendationRepository(
            conn,
            settings,
            new_id=new_id,
            slugify=slugify,
            campaign_by_slug=self.campaign_by_slug,
            ensure_graph_node=self.graph.ensure_graph_node,
            ensure_graph_edge=self.graph.ensure_graph_edge,
            graph_id_for=self.graph.graph_id_for,
            record_event=self.events.record_event,
            recommendation_item_row=self.recommendations.recommendation_item_row,
            reference_pattern_payload=self.reference.reference_pattern_payload,
            select_audio_for_recommendation=lambda *args, **kwargs: (
                self.audio_operations.select_audio_for_recommendation(*args, **kwargs)
            ),
        )
        self.audio_operations = AudioOperationsRepository(
            conn,
            slugify=slugify,
            sanitize_for_storage=sanitize_for_storage,
            utc_now=utc_now,
            video_exts={".mp4", ".mov", ".m4v", ".webm"},
            probe_video_metadata=probe_video_metadata,
            rendered_asset=self.rendered_asset,
            record_event=self.events.record_event,
            recommendation_item_row=self.recommendations.recommendation_item_row,
            recommendation_item_campaign=self.recommendations.recommendation_item_campaign,
            recommendation_item=self.recommendations.recommendation_item,
            audio_catalog_payload=self.audio_recommendations.audio_catalog_payload,
            audio_catalog_recommendation=self.audio_recommendations.audio_catalog_recommendation,
            graph_id_for=self.graph.graph_id_for,
            ensure_graph_node=self.graph.ensure_graph_node,
            ensure_graph_edge=self.graph.ensure_graph_edge,
            ensure_graph_edge_strict=self.ensure_graph_edge_strict,
            resolve_exception=self.exceptions.resolve_exception,
            performance_snapshot_payload=self.performance_summary_repo.performance_snapshot_payload,
        )
        self.archive_quality = ArchiveQualityRepository(
            conn,
            slugify=slugify,
            utc_now=utc_now,
            sha256_file=sha256_file,
            probe_video_metadata=probe_video_metadata,
            upsert_model=self.models.upsert_model,
            upsert_campaign=self.models.upsert_campaign,
            campaign_dirs=self.campaign_dirs,
            record_event=self.events.record_event,
        )
        self.inventory_planning = InventoryPlanningRepository(
            conn,
            creator_label=self.creator_label,
            normalize_content_surface=normalize_content_surface,
            surface_report_assets=surface_report_assets,
            build_surface_readiness=build_surface_readiness,
            build_surface_inventory=build_surface_inventory,
            ratio=self.ratio,
            score_fraction=self.score_fraction,
            road_to_accounts_payload=self.road_to_accounts_payload,
            exception_next_action=exception_next_action,
            content_surfaces=content_surfaces,
        )
        self.inventory_recovery = InventoryRecoveryRepository(
            conn,
            normalize_content_surface=normalize_content_surface,
            surface_report_assets=surface_report_assets,
            build_surface_readiness=build_surface_readiness,
        )
        self.schedule_safe_production = ScheduleSafeProductionRepository(
            conn,
            normalize_content_surface=normalize_content_surface,
            surface_report_assets=surface_report_assets,
            build_surface_readiness=build_surface_readiness,
            surface_handoff_readiness_for_asset=surface_handoff_readiness_for_asset,
            explain_publishability=explain_publishability,
            ratio=self.ratio,
        )
        self.fresh_reel_production = FreshReelProductionRepository(
            conn,
            normalize_content_surface=normalize_content_surface,
            surface_report_assets=surface_report_assets,
            build_surface_readiness=build_surface_readiness,
        )
        self.reel_factory_reports = ReelFactoryReportRepository(
            conn,
            build_surface_readiness=build_surface_readiness,
            inventory_count_related=lambda table, column, asset_ids: (
                self.inventory_planning.inventory_count_related(
                    table, column, asset_ids
                )
            ),
            inventory_production_requirements=inventory_production_requirements,
            ratio=self.ratio,
        )
        self.contentforge_visual_qc = ContentForgeVisualQCRepository(
            conn,
            normalize_content_surface=normalize_content_surface,
            schedule_safe_production_assets=self.schedule_safe_production.schedule_safe_production_assets,
            schedule_safe_is_variant_asset=self.schedule_safe_production.schedule_safe_is_variant_asset,
            surface_report_assets=surface_report_assets,
            build_surface_readiness=build_surface_readiness,
            surface_handoff_readiness_for_asset=surface_handoff_readiness_for_asset,
            explain_publishability=explain_publishability,
        )
        self.multi_blocker_unlock = MultiBlockerUnlockRepository(
            conn,
            normalize_content_surface=normalize_content_surface,
            surface_report_assets=surface_report_assets,
            build_surface_readiness=build_surface_readiness,
        )
        self.discoverability = DiscoverabilityRepository(
            conn,
            json_load=json_load,
            parent_factory_yield_waterfall=parent_factory_yield_waterfall,
            ratio=self.ratio,
            score_fraction=self.score_fraction,
            wilson_lower_bound=self.wilson_lower_bound,
        )
        self.parent_factory_reports = ParentFactoryReportRepository(
            conn,
            reel_factory_parent_metrics=self.reel_factory_reports.reel_factory_parent_metrics,
            parent_factory_discoverability_loss_analysis=self.discoverability.parent_factory_discoverability_loss_analysis,
            parent_factory_waterfall_after_discoverability=self.discoverability.parent_factory_waterfall_after_discoverability,
            post_discoverability_downstream_confidence=self.discoverability.post_discoverability_downstream_confidence,
            exception_next_action=exception_next_action,
            ratio=self.ratio,
        )
        self.parent_factory_trials = ParentFactoryTrialRepository(
            conn,
            settings=settings,
            factory_constructor=lambda sandbox_settings: factory_context.__class__(
                sandbox_settings
            ),
            reel_factory_parent_metrics=self.reel_factory_reports.reel_factory_parent_metrics,
            operator_review_minutes_per_parent=self.reel_factory_reports.operator_review_minutes_per_parent,
            parent_factory_yield_waterfall=self.parent_factory_reports.parent_factory_yield_waterfall,
            parent_factory_loss_analysis=self.parent_factory_reports.parent_factory_loss_analysis,
            parent_factory_trial_loss_buckets=self.parent_factory_reports.parent_factory_trial_loss_buckets,
            parent_factory_trial_stage_repairable=self.parent_factory_reports.parent_factory_trial_stage_repairable,
            explain_publishability=explain_publishability,
            ratio=self.ratio,
            score_fraction=self.score_fraction,
        )
        self.parent_factory_planning = ParentFactoryPlanningRepository(
            inventory_production_requirements=self.inventory_planning.inventory_production_requirements,
            reel_factory_parent_metrics=self.reel_factory_reports.reel_factory_parent_metrics,
            parent_factory_yield_waterfall=self.parent_factory_reports.parent_factory_yield_waterfall,
            parent_factory_loss_analysis=self.parent_factory_reports.parent_factory_loss_analysis,
        )
        self.surface_handoff = SurfaceHandoffRepository(
            conn,
            slugify=slugify,
            creator_label=self.creator_label,
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
            truthy=self.truthy,
            story_native_proof_styles=story_native_proof_styles,
            ig_media_type_by_surface=ig_media_type_by_surface,
        )
        self.story_management = StoryManagementRepository(
            conn,
            creator_label=self.creator_label,
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
            truthy=self.truthy,
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
        self.creator_os_drafts = CreatorOSDraftRepository(
            sanitize_for_storage=sanitize_for_storage,
            normalize_content_surface=normalize_content_surface,
            creator_label=self.creator_label,
            truthy=self.truthy,
            creator_os_numeric=lambda value: self.account_health.creator_os_numeric(
                value
            ),
            surface_report_assets=surface_report_assets,
            surface_handoff_readiness_for_asset=surface_handoff_readiness_for_asset,
            multi_surface_inventory_audit=self.surface_inventory.multi_surface_inventory_audit,
            creator_content_needs=self.surface_requirements.creator_content_needs,
            story_intent_report=self.story_management.story_intent_report,
            utc_now=utc_now,
            content_surfaces=content_surfaces,
            creative_risk_block_threshold=creative_risk_block_threshold,
            default_story_calendar=default_story_calendar,
        )
        self.decision_ledger = DecisionLedgerRepository(
            conn,
            sanitize_for_storage=sanitize_for_storage,
            utc_now=utc_now,
            creator_label=self.creator_label,
            creator_os_target_date=self.creator_os_drafts.creator_os_target_date,
            creator_os_daily_plan=creator_os_daily_plan,
            creator_content_needs=self.surface_requirements.creator_content_needs,
            recommended_story_intent_for_date=self.creator_os_drafts.recommended_story_intent_for_date,
            recommended_story_style_for_intent=self.creator_os_drafts.recommended_story_style_for_intent,
            story_mix_plan=story_mix_plan,
            story_calendar_plan=story_calendar_plan,
            normalize_content_surface=normalize_content_surface,
        )
        self.surface_summary = SurfaceSummaryRepository(
            conn,
            creator_label=self.creator_label,
            creator_os_target_date=self.creator_os_drafts.creator_os_target_date,
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
            creator_label=self.creator_label,
            creator_os_draft_items=self.creator_os_drafts.creator_os_draft_items,
            creator_os_local_schedule_safe_assets=self.creator_os_drafts.creator_os_local_schedule_safe_assets,
            creator_os_schedule_safe_drafts=self.creator_os_drafts.creator_os_schedule_safe_drafts,
            creator_os_draft_exclusion_reason=self.creator_os_drafts.creator_os_draft_exclusion_reason,
            creator_os_execution_draft_blockers=self.creator_os_drafts.creator_os_execution_draft_blockers,
            creator_os_gap_blocking_reason=self.creator_os_drafts.creator_os_gap_blocking_reason,
            utc_now=utc_now,
        )
        self.creator_os_recommendations = CreatorOSRecommendationRepository(
            creator_label=self.creator_label,
            build_creative_performance_analysis=build_creative_performance_analysis,
            first_lineage_value=self.first_lineage_value,
            surface_from_pattern=self.surface_from_pattern,
            recommendation_explainability=recommendation_explainability,
        )
        self.daily_plan = DailyPlanRepository(
            conn,
            creator_label=self.creator_label,
            creator_os_target_date=self.creator_os_drafts.creator_os_target_date,
            creator_os_draft_items=self.creator_os_drafts.creator_os_draft_items,
            creator_os_account_health_report=creator_os_account_health_report,
            creator_os_account_health_decision=creator_os_account_health_decision,
            creator_os_tier_posting_guidance=creator_os_tier_posting_guidance,
            creator_os_account_surface_status=self.creator_os_drafts.creator_os_account_surface_status,
            creator_os_draft_exclusion_reason=self.creator_os_drafts.creator_os_draft_exclusion_reason,
            creator_os_draft_has_instagram_post_caption=self.creator_os_drafts.creator_os_draft_has_instagram_post_caption,
            creator_os_post_time=self.creator_os_drafts.creator_os_post_time,
            creator_os_recommended_post_count=self.creator_os_drafts.creator_os_recommended_post_count,
            creator_os_account_tier_summary=creator_os_account_tier_summary,
            creator_os_account_health_summary=creator_os_account_health_summary,
            creator_os_surface_summary_for_creator=self.creator_os_drafts.creator_os_surface_summary_for_creator,
            creator_os_inventory_for_creator=self.creator_os_drafts.creator_os_inventory_for_creator,
            creator_os_draft_exclusion_counts=self.creator_os_drafts.creator_os_draft_exclusion_counts,
            creator_os_winner_recommendations=self.creator_os_recommendations.creator_os_winner_recommendations,
            creator_os_manager_decision=self.creator_os_drafts.creator_os_manager_decision,
            creator_os_blocked_account_breakdown=self.creator_os_drafts.creator_os_blocked_account_breakdown,
            recommended_story_intent_for_date=self.creator_os_drafts.recommended_story_intent_for_date,
            creator_os_recommended_inventory=self.creator_os_recommendations.creator_os_recommended_inventory,
            recommended_story_style_for_intent=self.creator_os_drafts.recommended_story_style_for_intent,
            creator_os_draft_inventory_gap=self.draft_inventory_gap.creator_os_draft_inventory_gap,
            utc_now=utc_now,
        )
        self.recommended_inventory_request = RecommendedInventoryRequestRepository(
            creator_label=self.creator_label,
            creator_os_daily_plan=lambda *args, **kwargs: (
                self.daily_plan.creator_os_daily_plan(*args, **kwargs)
            ),
            normalize_content_surface=normalize_content_surface,
            recommendation_explainability=recommendation_explainability,
            utc_now=utc_now,
        )
        self.surface_registration = SurfaceRegistrationRepository(
            conn,
            slugify=slugify,
            utc_now=utc_now,
            creator_label=self.creator_label,
            normalize_content_surface=normalize_content_surface,
            upsert_model=self.models.upsert_model,
            upsert_campaign=self.models.upsert_campaign,
            campaign_dirs=self.campaign_dirs,
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
            creator_label=self.creator_label,
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
            creator_label=self.creator_label,
            concept_payload=lambda row: self.variant_lineage.concept_payload(row),
        )
        self.creative_knowledge = CreativeKnowledgeRepository(
            conn,
            slugify=slugify,
            creator_label=self.creator_label,
            campaign_by_slug=self.campaign_by_slug,
            normalize_content_surface=normalize_content_surface,
            first_lineage_value=self.first_lineage_value,
            surface_from_pattern=self.surface_from_pattern,
            ig_media_type_for_surface=ig_media_type_for_surface,
            performance_metric_contract=self.performance_summary_repo.performance_metric_contract,
            build_creative_knowledge_base=build_creative_knowledge_base,
            build_creative_performance_analysis=build_creative_performance_analysis,
            creative_knowledge_score_weights=creative_knowledge_score_weights,
            creative_result_group=creative_result_group,
            creative_knowledge_results_for_report=creative_knowledge_results_for_report,
            creative_dimension_label=creative_dimension_label,
            learning_confidence_classification=learning_confidence_classification,
            creative_fatigue_signals=creative_fatigue_signals,
            creative_surface_rows=creative_surface_rows,
            recommendation_explainability=recommendation_explainability,
            recommendation_quality_bucket=recommendation_quality_bucket,
        )
        self.tribev2 = TribeV2Repository(
            conn,
            settings,
            slugify=slugify,
            creator_label=self.creator_label,
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
            creator_label=self.creator_label,
            truthy=self.truthy,
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
            creator_label=self.creator_label,
            creator_os_daily_plan=creator_os_daily_plan,
            creator_os_draft_items=self.creator_os_drafts.creator_os_draft_items,
            creator_os_schedule_safe_drafts=self.creator_os_drafts.creator_os_schedule_safe_drafts,
            creator_os_account_health_report=creator_os_account_health_report,
            creator_os_execution_draft_blockers=self.creator_os_drafts.creator_os_execution_draft_blockers,
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
            parent_factory_autopilot_plan=self.parent_factory_planning.parent_factory_autopilot_plan,
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
            score_fraction=self.score_fraction,
        )
        self.live_acceptance = LiveAcceptanceRepository(
            conn,
            normalize_content_surface=normalize_content_surface,
            actual_account_operational_counts=self.live_scale.actual_account_operational_counts,
            surface_report_assets=surface_report_assets,
            build_surface_readiness=build_surface_readiness,
            reservation_adjusted_inventory=self.inventory_reservations.reservation_adjusted_inventory,
            exception_queue_report=exception_queue_report,
        )
        self.lifecycle_reporting = LifecycleReportingRepository(
            conn,
            campaign_by_slug=self.campaign_by_slug,
            dashboard=dashboard,
            jobs_for_campaign=self.events.jobs_for_campaign,
            distribution_plans_for_campaign=self.distribution.distribution_plans_for_campaign,
            assignments_for_campaign=self.campaign_overview.assignments_for_campaign,
            performance_snapshot_payload=self.performance_summary_repo.performance_snapshot_payload,
            active_quarantine_for_asset=active_quarantine_for_asset,
            utc_now=utc_now,
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

    def ensure_graph_edge_strict(
        self,
        from_global_id: str | None,
        to_global_id: str | None,
        relation_type: str,
        *,
        evidence: dict[str, Any] | None = None,
        campaign_id: str | None = None,
        account_id: str | None = None,
        recommendation_item_id: str | None = None,
        source_operation: str = "content_graph",
        commit: bool = False,
    ) -> str | None:
        if from_global_id and to_global_id:
            return self.graph.ensure_graph_edge(
                from_global_id,
                to_global_id,
                relation_type,
                evidence=evidence,
                commit=commit,
            )
        missing = []
        if not from_global_id:
            missing.append("from_global_id")
        if not to_global_id:
            missing.append("to_global_id")
        reason_code = "graph_edge_missing_endpoint"
        self.exceptions.create_exception(
            reason_code=f"{reason_code}:{self._slugify(source_operation)}:{self._slugify(relation_type)}:{'_'.join(missing)}",
            severity="high",
            campaign_id=campaign_id,
            account_id=account_id,
            entity_graph_id=from_global_id or to_global_id,
            recommendation_item_id=recommendation_item_id,
            payload={
                "relationType": relation_type,
                "sourceOperation": source_operation,
                "missing": missing,
                "fromGlobalId": from_global_id,
                "toGlobalId": to_global_id,
                "evidence": self._sanitize_for_storage(evidence or {}),
            },
            commit=commit,
        )
        return None

    def events_for_campaign(
        self, campaign_slug: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        return self.events.events_for_campaign(campaign_slug, limit=limit)

    def events_for_asset(
        self, rendered_asset_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self.events.events_for_asset(rendered_asset_id, limit=limit)

    def jobs_for_campaign(
        self,
        campaign_slug: str | None = None,
        limit: int = 100,
        statuses: list[str] | None = None,
        stuck_hours: float | None = None,
    ) -> list[dict[str, Any]]:
        return self.events.jobs_for_campaign(
            campaign_slug, limit=limit, statuses=statuses, stuck_hours=stuck_hours
        )

    def account_reward_baselines(
        self, snapshots: list[dict[str, Any]]
    ) -> dict[str, float]:
        return _account_reward_baselines(snapshots)

    def audio_catalog(
        self, platform: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        return self.audio_recommendations.audio_catalog(platform=platform, limit=limit)

    def audio_memory(
        self, platform: str | None = None, account: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        return self.audio_recommendations.audio_memory(
            platform=platform, account=account, limit=limit
        )

    def cover_frame_for_asset(
        self, asset: dict[str, Any], caption_context: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        return self.audio_operations.cover_frame_for_asset(
            asset, caption_context=caption_context
        )

    def upsert_model(
        self, slug: str, name: str | None = None, notes: str | None = None
    ) -> dict[str, Any]:
        return self.models.upsert_model(slug, name=name, notes=notes)

    def upsert_campaign(
        self,
        slug: str,
        model_slug: str,
        name: str | None = None,
        platform: str = "instagram",
    ) -> dict[str, Any]:
        return self.models.upsert_campaign(
            slug, model_slug, name=name, platform=platform
        )

    def upsert_account(
        self,
        handle: str,
        platform: str = "instagram",
        external_id: str | None = None,
        model_id: str | None = None,
        account_group_id: str | None = None,
    ) -> dict[str, Any]:
        kwargs = {
            "platform": platform,
            "external_id": external_id,
            "model_id": model_id,
        }
        if account_group_id is not None:
            kwargs["account_group_id"] = account_group_id
        return self.models.upsert_account(handle, **kwargs)

    def account_memory_report(
        self, campaign_slug: str, account: str | None = None
    ) -> dict[str, Any]:
        return self.account_memory.account_memory(campaign_slug, account=account)

    def reference_patterns(self, limit: int = 50) -> dict[str, Any]:
        return self.reference.reference_patterns(limit=limit)

    def reference_hooks(
        self, pattern: dict[str, Any], count: int = 5
    ) -> list[dict[str, Any]]:
        return self.reference.reference_hooks(pattern, count=count)

    def finished_video_hooks(
        self, format_type: str, pattern: dict[str, Any], count: int = 5
    ) -> list[dict[str, Any]]:
        return self.finished_video.finished_video_hooks(
            format_type, pattern, count=count
        )

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
        trial_group_id: str | None = None,
    ) -> dict[str, Any]:
        kwargs = {
            "surface": surface,
            "account_id": account_id,
            "instagram_account_id": instagram_account_id,
            "planned_window_start": planned_window_start,
            "planned_window_end": planned_window_end,
            "paired_rendered_asset_id": paired_rendered_asset_id,
            "reason_code": reason_code,
            "smart_link": smart_link,
            "cta_text": cta_text,
            "instagram_trial_reels": instagram_trial_reels,
            "trial_graduation_strategy": trial_graduation_strategy,
        }
        if trial_group_id is not None:
            kwargs["trial_group_id"] = trial_group_id
        return self.distribution.create_distribution_plan(rendered_asset_id, **kwargs)

    def campaign_by_slug(self, slug: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM campaigns WHERE slug = ?", (self._slugify(slug),)
        ).fetchone()
        if not row:
            raise ValueError(f"campaign not found: {slug}")
        return dict(row)

    def list_campaigns(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM campaigns ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def campaign_dirs(self, model_slug: str, campaign_slug: str) -> dict[str, Path]:
        root = self.settings.campaigns_dir / model_slug / campaign_slug
        dirs = {
            "root": root,
            "sources": root / "00_sources",
            "reel_inputs": root / "01_reel_inputs",
            "rendered": root / "02_rendered",
            "audits": root / "03_contentforge_audits",
            "approved": root / "04_approved",
            "exports": root / "05_threadsdash_exports",
        }
        for path in dirs.values():
            path.mkdir(parents=True, exist_ok=True)
        return dirs

    def rendered_for_campaign(self, campaign_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM rendered_assets WHERE campaign_id = ? ORDER BY created_at DESC",
            (campaign_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def rendered_asset(self, rendered_asset_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM rendered_assets WHERE id = ?", (rendered_asset_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"rendered asset not found: {rendered_asset_id}")
        return dict(row)

    def ratio(self, numerator: Any, denominator: Any) -> float:
        denom = float(denominator or 0)
        if denom <= 0:
            return 0
        return round(float(numerator or 0) / denom, 3)

    def score_fraction(self, numerator: Any, denominator: Any) -> float:
        denom = float(denominator or 0)
        if denom <= 0:
            return 0.0
        return round(10 * min(1.0, max(0.0, float(numerator or 0) / denom)), 1)

    def road_to_accounts_payload(
        self, *, accounts: int, production: dict[str, Any]
    ) -> dict[str, Any]:
        posts = int(production.get("postsPerDay") or 0)
        return {
            "schema": f"creator_os.road_to_{accounts}_accounts.v1",
            "accounts": accounts,
            "requiredInventoryBuffer": f"{posts * 3} schedule-safe drafts",
            "requiredDailyProduction": f"{posts} schedule-safe drafts/day",
            "requiredValidatedDrafts": f"{production.get('requiredValidatedDraftsPerDay')} validated drafts/day",
            "requiredParentAssetsPerDay": int(
                production.get("requiredParentsPerDay") or 0
            ),
            "requiredCaptionFamiliesPerDay": int(
                production.get("requiredCaptionFamiliesPerDay") or 0
            ),
            "requiredVariantsPerDay": int(
                production.get("requiredVariantsPerDay") or 0
            ),
            "requiredExceptionRate": "<=2.0% inventory-blocking exceptions",
            "requiredOperatorLoad": "<=25 inventory exceptions/day per operator queue",
            "wouldWrite": False,
        }

    def wilson_lower_bound(
        self, *, successes: int, trials: int, z: float = 1.96
    ) -> float:
        if trials <= 0:
            return 0.0
        phat = successes / trials
        denominator = 1 + (z * z / trials)
        centre = phat + (z * z / (2 * trials))
        margin = z * math.sqrt((phat * (1 - phat) + (z * z / (4 * trials))) / trials)
        return max(0.0, (centre - margin) / denominator)

    def creator_label(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return "unknown"
        return text[:1].upper() + text[1:]

    def truthy(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def surface_from_pattern(
        self, item: dict[str, Any], lineage: dict[str, Any]
    ) -> str:
        if item.get("dimension") == "contentSurface":
            return str(item.get("key") or "reel")
        surfaces = (
            lineage.get("contentSurfaces")
            if isinstance(lineage.get("contentSurfaces"), list)
            else []
        )
        if surfaces:
            return str(surfaces[0] or "reel")
        if item.get("dimension") in {"storyIntent", "storyStyle"}:
            return "story"
        return "reel"

    def first_lineage_value(
        self, lineage: dict[str, Any], key: str, *, fallback: str = ""
    ) -> str:
        values = lineage.get(key) if isinstance(lineage.get(key), list) else []
        return str(values[0]) if values else fallback

    def audit_report(self, audit_report_id: str) -> dict[str, Any]:
        from . import audit_payload as _audit_payload

        return _audit_payload.audit_report(self.factory_context, audit_report_id)

    def audit_report_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        from . import audit_payload as _audit_payload

        return _audit_payload._audit_report_payload(self.factory_context, row)
