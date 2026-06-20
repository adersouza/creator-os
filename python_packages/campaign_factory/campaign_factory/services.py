from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any, Callable

from .acceptance_suite import AcceptanceSuiteRepository
from .account_health import AccountHealthRepository
from .account_memory import AccountMemoryRepository
from .account_planning import AccountPlanningRepository
from .archive_quality import ArchiveQualityRepository
from .asset_import import AssetImportRepository
from .audio_operations import AudioOperationsRepository
from .audio_recommendations import AudioRecommendationRepository
from .autonomy import AutonomyPolicyRepository
from .caption import CaptionFamilyRepository
from .carousel_integrity import CarouselIntegrityRepository
from .campaign_overview import CampaignOverviewRepository
from .certification import CertificationRepository
from .config import Settings
from .contentforge_visual_qc import ContentForgeVisualQCRepository
from .core_complexity import CoreComplexityRepository
from .cost_tracker import ensure_cost_table, record_ai_cost
from .creative_knowledge import CreativeKnowledgeRepository
from .creator_os_drafts import CreatorOSDraftRepository
from .creator_os_recommendations import CreatorOSRecommendationRepository
from .creative_planning import CreativePlanningRepository
from .decision_ledger import DecisionLedgerRepository
from .discoverability import DiscoverabilityRepository
from .distribution import DistributionRepository
from .daily_plan import DailyPlanRepository
from .draft_inventory_gap import DraftInventoryGapRepository
from .events import EventRepository
from .export_summary import ExportSummaryRepository
from .execution_readiness import ExecutionReadinessRepository
from .exceptions import ExceptionRepository
from .finished_video import FinishedVideoRepository
from .fresh_reel_production import FreshReelProductionRepository
from .graph import GraphRepository
from .inventory_planning import InventoryPlanningRepository
from .inventory_perceptual import InventoryPerceptualRepository
from .inventory_recovery import InventoryRecoveryRepository
from .inventory_reservations import InventoryReservationRepository
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
from .reference import ReferenceRepository
from .recommendation_accuracy import RecommendationAccuracyRepository
from .recommendations import RecommendationRepository
from .recommended_inventory_request import RecommendedInventoryRequestRepository
from .readiness_report import ReadinessReportRepository
from .reel_factory_reports import ReelFactoryReportRepository
from .reel_execution import ReelExecutionRepository
from .schedule_safe_production import ScheduleSafeProductionRepository
from .story_management import StoryManagementRepository
from .surface_handoff import SurfaceHandoffRepository
from .surface_inventory import SurfaceInventoryRepository
from .surface_requirements import SurfaceRequirementsRepository
from .surface_registration import SurfaceRegistrationRepository
from .surface_summary import SurfaceSummaryRepository
from .tribev2 import TribeV2Repository
from .variant_lineage import VariantLineageRepository
from .winner_expansion import WinnerExpansionRepository


class CoreServices:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
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
        generated_asset_lineage: Callable[[dict[str, Any], dict[str, Any] | None], dict[str, Any]],
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
        capture_publishability_rejection_evidence_from_result: Callable[..., dict[str, Any]],
        distribution_plan_payload: Callable[[dict[str, Any]], dict[str, Any]],
        verification_id: Callable[..., str],
        caption_lineage_sidecar: Callable[[str], dict[str, Any]],
        active_quarantine_for_asset: Callable[[str], dict[str, Any] | None],
        audio_segment_for_asset: Callable[[dict[str, Any]], dict[str, Any] | None],
        cover_frame_for_asset: Callable[[dict[str, Any], dict[str, Any] | None], dict[str, Any] | None],
        audio_intent_claims_embedded_media: Callable[[dict[str, Any]], bool],
        embedded_audio_verified: Callable[[str], bool | None],
        discoverability_evidence_for_fields: Callable[[list[tuple[str, str]]], list[dict[str, Any]]],
        reference_hook_is_schedule_safe: Callable[[str], bool],
        audio_intent_is_attached: Callable[[dict[str, Any], str | None], bool],
        requires_operator_visual_review_for_handoff: Callable[[dict[str, Any]], bool],
        ig_media_type_for_surface: Callable[[str, str], str],
        surface_handoff_readiness_report: Callable[..., dict[str, Any]],
        performance_summary: Callable[[str], dict[str, Any]],
        recommend_audio: Callable[..., dict[str, Any]],
        select_audio_for_recommendation: Callable[..., dict[str, Any]],
        surface_handoff_readiness_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        audio_selection_for_asset: Callable[[dict[str, Any]], tuple[dict[str, Any], str | None]],
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
        creator_os_account_tier_summary: Callable[[list[dict[str, Any]]], dict[str, Any]],
        creator_os_account_health_summary: Callable[[list[dict[str, Any]]], dict[str, Any]],
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
        learning_confidence_classification: Callable[[list[dict[str, Any]]], dict[str, Any]],
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
        performance_snapshot_payload: Callable[[dict[str, Any]], dict[str, Any]],
        account_reward_baselines: Callable[[list[dict[str, Any]]], dict[str, float]],
        aggregate_performance: Callable[..., dict[str, Any]],
        performance_quality_score: Callable[[dict[str, Any]], int | None],
        performance_planning_score: Callable[[dict[str, Any]], int | None],
        audio_selection_payload: Callable[[str], dict[str, Any]],
        audio_workflow_summary: Callable[[list[dict[str, Any]]], dict[str, Any]],
        events_for_asset: Callable[..., list[dict[str, Any]]],
        performance_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
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
            subprocess_run=lambda *args, **kwargs: __import__("subprocess").run(*args, **kwargs),
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
            finished_video_hooks=lambda *args, **kwargs: self.finished_video.finished_video_hooks(*args, **kwargs),
            finished_video_caption_band=lambda *args, **kwargs: self.finished_video.finished_video_caption_band(*args, **kwargs),
            finished_video_caption_font=lambda *args, **kwargs: self.finished_video.finished_video_caption_font(*args, **kwargs),
            prepare_reel_inputs=prepare_reel_inputs,
            run_reel_factory=lambda *args, **kwargs: self.reel_execution.run_reel_factory(*args, **kwargs),
            sync_reel_outputs=lambda *args, **kwargs: self.reel_execution.sync_reel_outputs(*args, **kwargs),
            dashboard=dashboard,
            campaign_health=self.campaign_health,
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
            performance_snapshot_payload=performance_snapshot_payload,
            aggregate_performance=aggregate_performance,
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
            trust_summary=self.trust_summary,
            rendered_asset=self.rendered_asset,
            record_event=self.events.record_event,
            events_for_asset=events_for_asset,
            performance_for_asset=performance_for_asset,
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
            performance_for_asset=performance_for_asset,
            local_export_readiness=self.publishability.local_export_readiness,
            recommend_audio=recommend_audio,
            performance_quality_score=performance_quality_score,
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
            performance_summary=performance_summary,
            ranking=ranking,
            active_reference_pattern_for_campaign=self.reference.active_reference_pattern_for_campaign,
            reference_pattern_payload=self.reference.reference_pattern_payload,
            performance_snapshot_payload=performance_snapshot_payload,
            account_reward_baselines=account_reward_baselines,
            aggregate_performance=aggregate_performance,
            performance_quality_score=performance_quality_score,
            performance_planning_score=performance_planning_score,
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
            select_audio_for_recommendation=lambda *args, **kwargs: self.audio_operations.select_audio_for_recommendation(*args, **kwargs),
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
            performance_snapshot_payload=performance_snapshot_payload,
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
            inventory_count_related=lambda table, column, asset_ids: self.inventory_planning.inventory_count_related(table, column, asset_ids),
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
            factory_constructor=lambda sandbox_settings: factory_context.__class__(sandbox_settings),
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
            creator_os_numeric=self.creator_os_numeric,
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
            creator_os_daily_plan=lambda *args, **kwargs: self.creator_os_daily_plan(*args, **kwargs),
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
            performance_metric_contract=self.performance_metric_contract,
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
            performance_snapshot_payload=performance_snapshot_payload,
            active_quarantine_for_asset=active_quarantine_for_asset,
            utc_now=utc_now,
        )
        self.performance_summary_repo = PerformanceSummaryRepository(
            conn,
            campaign_by_slug=self.campaign_by_slug,
            slugify=slugify,
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

    def campaign_readiness(self, campaign_slug: str, **kwargs: Any) -> dict[str, Any]:
        return self.lifecycle_reporting.campaign_readiness(campaign_slug, **kwargs)

    def lifecycle_report(self, campaign_slug: str, **kwargs: Any) -> dict[str, Any]:
        return self.lifecycle_reporting.lifecycle_report(campaign_slug, **kwargs)

    def creator_os_lifecycle_dashboard(self, **kwargs: Any) -> dict[str, Any]:
        return self.lifecycle_reporting.creator_os_lifecycle_dashboard(**kwargs)

    def creator_os_lifecycle_bucket(self, row: dict[str, Any]) -> str:
        return self.lifecycle_reporting.creator_os_lifecycle_bucket(row)

    def lifecycle_snapshots_by_asset(self, campaign_id: str) -> dict[str, list[dict[str, Any]]]:
        return self.lifecycle_reporting.lifecycle_snapshots_by_asset(campaign_id)

    def lifecycle_threadsdash_indexes(self, **kwargs: Any) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
        return self.lifecycle_reporting.lifecycle_threadsdash_indexes(**kwargs)

    def lifecycle_row(self, **kwargs: Any) -> dict[str, Any]:
        return self.lifecycle_reporting.lifecycle_row(**kwargs)

    def derive_lifecycle_state(self, **kwargs: Any) -> tuple[str, str | None, str]:
        return self.lifecycle_reporting.derive_lifecycle_state(**kwargs)

    def lifecycle_blocking_reason(self, blocking: list[Any]) -> str:
        return self.lifecycle_reporting.lifecycle_blocking_reason(blocking)

    def lifecycle_media_validation_issue(self, **kwargs: Any) -> dict[str, Any] | None:
        return self.lifecycle_reporting.lifecycle_media_validation_issue(**kwargs)

    def latest_lifecycle_post(self, posts: list[dict[str, Any]]) -> dict[str, Any] | None:
        return self.lifecycle_reporting.latest_lifecycle_post(posts)

    def lifecycle_snapshot_has_metrics(self, snapshot: dict[str, Any]) -> bool:
        return self.lifecycle_reporting.lifecycle_snapshot_has_metrics(snapshot)

    def lifecycle_is_past_due(self, scheduled_for: Any) -> bool:
        return self.lifecycle_reporting.lifecycle_is_past_due(scheduled_for)

    def lifecycle_past_due_resolved(self, post: dict[str, Any] | None) -> bool:
        return self.lifecycle_reporting.lifecycle_past_due_resolved(post)

    def lifecycle_last_state_change(self, **kwargs: Any) -> str | None:
        return self.lifecycle_reporting.lifecycle_last_state_change(**kwargs)

    def parse_lifecycle_time(self, value: Any) -> Any:
        return self.lifecycle_reporting.parse_lifecycle_time(value)

    def lifecycle_mismatch(self, **kwargs: Any) -> dict[str, Any]:
        return self.lifecycle_reporting.lifecycle_mismatch(**kwargs)

    def lifecycle_post_meta(self, post: dict[str, Any]) -> dict[str, Any]:
        return self.lifecycle_reporting.lifecycle_post_meta(post)

    def lifecycle_fingerprint(self, value: Any) -> str:
        return self.lifecycle_reporting.lifecycle_fingerprint(value)

    def canonical_lifecycle_context(self, value: Any) -> Any:
        return self.lifecycle_reporting.canonical_lifecycle_context(value)

    def compact_lifecycle_post(self, post: dict[str, Any] | None) -> dict[str, Any] | None:
        return self.lifecycle_reporting.compact_lifecycle_post(post)

    def compact_lifecycle_snapshot(self, snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
        return self.lifecycle_reporting.compact_lifecycle_snapshot(snapshot)

    def performance_summary(self, campaign_slug: str) -> dict[str, Any]:
        return self.performance_summary_repo.performance_summary(campaign_slug)

    def caption_outcome_report(self, campaign_slug: str) -> dict[str, Any]:
        return self.performance_summary_repo.caption_outcome_report(campaign_slug)

    def performance_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.performance_summary_repo.performance_for_asset(asset)

    def performance_snapshot_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.performance_summary_repo.performance_snapshot_payload(row)

    def group_performance(
        self,
        snapshots: list[dict[str, Any]],
        key: str,
        *,
        account_baselines: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        return self.performance_summary_repo.group_performance(
            snapshots,
            key,
            account_baselines=account_baselines,
        )

    def aggregate_performance(
        self,
        snapshots: list[dict[str, Any]],
        *,
        account_baselines: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        return self.performance_summary_repo.aggregate_performance(
            snapshots,
            account_baselines=account_baselines,
        )

    def performance_metric_contract(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.performance_summary_repo.performance_metric_contract(row)

    def default_performance_metric_names(self, surface: str) -> list[str]:
        return self.performance_summary_repo.default_performance_metric_names(surface)

    def performance_leaderboards(
        self,
        snapshots: list[dict[str, Any]],
        *,
        account_baselines: dict[str, float] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        return self.performance_summary_repo.performance_leaderboards(
            snapshots,
            account_baselines=account_baselines,
        )

    def caption_outcome_manual_review(self, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        return self.performance_summary_repo.caption_outcome_manual_review(snapshots)

    def has_caption_outcome_context(self, snapshot: dict[str, Any]) -> bool:
        return self.performance_summary_repo.has_caption_outcome_context(snapshot)

    def caption_outcome_snapshot_with_placement(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return self.performance_summary_repo.caption_outcome_snapshot_with_placement(snapshot)

    def caption_outcome_group(self, snapshots: list[dict[str, Any]], source_key: str, output_key: str) -> list[dict[str, Any]]:
        return self.performance_summary_repo.caption_outcome_group(snapshots, source_key, output_key)

    def caption_outcome_contexts_for_group(self, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.performance_summary_repo.caption_outcome_contexts_for_group(snapshots)

    def add_leaderboard_snapshot(
        self,
        items: dict[str, dict[str, Any]],
        key: str,
        snapshot: dict[str, Any],
        dimensions: dict[str, Any],
    ) -> None:
        return self.performance_summary_repo.add_leaderboard_snapshot(items, key, snapshot, dimensions)

    def rank_leaderboard_entries(
        self,
        items: dict[str, dict[str, Any]],
        *,
        limit: int = 20,
        account_baselines: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        return self.performance_summary_repo.rank_leaderboard_entries(
            items,
            limit=limit,
            account_baselines=account_baselines,
        )

    def performance_recommendation_label(self, summary: dict[str, Any]) -> str:
        return self.performance_summary_repo.performance_recommendation_label(summary)

    def performance_quality_score(self, summary: dict[str, Any]) -> int | None:
        return self.performance_summary_repo.performance_quality_score(summary)

    def performance_planning_score(self, summary: dict[str, Any]) -> int | None:
        return self.performance_summary_repo.performance_planning_score(summary)

    def performance_snapshot_dimensions(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.performance_summary_repo.performance_snapshot_dimensions(row)

    def performance_hook_dimension(self, campaign_meta: dict[str, Any]) -> dict[str, Any] | None:
        return self.performance_summary_repo.performance_hook_dimension(campaign_meta)

    def performance_audio_dimension(self, campaign_meta: dict[str, Any]) -> dict[str, Any] | None:
        return self.performance_summary_repo.performance_audio_dimension(campaign_meta)

    def performance_reference_format_dimension(self, campaign_meta: dict[str, Any]) -> dict[str, Any] | None:
        return self.performance_summary_repo.performance_reference_format_dimension(campaign_meta)

    def performance_prompt_pattern_dimension(self, campaign_meta: dict[str, Any]) -> dict[str, Any] | None:
        return self.performance_summary_repo.performance_prompt_pattern_dimension(campaign_meta)

    def performance_pattern_card_dimension(self, campaign_meta: dict[str, Any]) -> dict[str, Any] | None:
        return self.performance_summary_repo.performance_pattern_card_dimension(campaign_meta)

    def performance_model_account_dimension(self, campaign_meta: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
        return self.performance_summary_repo.performance_model_account_dimension(campaign_meta, row)

    def performance_caption_formula_dimension(self, campaign_meta: dict[str, Any]) -> dict[str, Any] | None:
        return self.performance_summary_repo.performance_caption_formula_dimension(campaign_meta)

    def performance_variation_preset_dimension(self, campaign_meta: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
        return self.performance_summary_repo.performance_variation_preset_dimension(campaign_meta, row)

    def performance_score(self, *, source: dict[str, Any], caption: dict[str, Any], recipe: dict[str, Any]) -> int | None:
        return self.performance_summary_repo.performance_score(source=source, caption=caption, recipe=recipe)

    def import_audio_catalog(self, catalog_path: Path) -> dict[str, Any]:
        return self.audio_recommendations.import_audio_catalog(catalog_path)

    def import_audio_memory(self, catalog_path: Path) -> dict[str, Any]:
        return self.audio_recommendations.import_audio_memory(catalog_path)

    def audio_catalog(self, platform: str | None = None, limit: int = 100) -> dict[str, Any]:
        return self.audio_recommendations.audio_catalog(platform=platform, limit=limit)

    def audio_memory(self, platform: str | None = None, account: str | None = None, limit: int = 100) -> dict[str, Any]:
        return self.audio_recommendations.audio_memory(platform=platform, account=account, limit=limit)

    def recommend_audio(
        self,
        *,
        platform: str = "instagram",
        content_tags: list[str] | None = None,
        account_tags: list[str] | None = None,
        campaign_slug: str | None = None,
        recommendation_item_id: str | None = None,
        account: str | None = None,
        visual_signal: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> dict[str, Any]:
        return self.audio_recommendations.recommend_audio(
            platform=platform,
            content_tags=content_tags,
            account_tags=account_tags,
            campaign_slug=campaign_slug,
            recommendation_item_id=recommendation_item_id,
            account=account,
            visual_signal=visual_signal,
            limit=limit,
        )

    def decide_audio(
        self,
        *,
        platform: str = "instagram",
        campaign_slug: str | None = None,
        recommendation_item_id: str | None = None,
        account: str | None = None,
        content_tags: list[str] | None = None,
        account_tags: list[str] | None = None,
        visual_signal: dict[str, Any] | None = None,
        limit: int = 5,
        select: bool = False,
        operator: str | None = None,
    ) -> dict[str, Any]:
        return self.audio_recommendations.decide_audio(
            platform=platform,
            campaign_slug=campaign_slug,
            recommendation_item_id=recommendation_item_id,
            account=account,
            content_tags=content_tags,
            account_tags=account_tags,
            visual_signal=visual_signal,
            limit=limit,
            select=select,
            operator=operator,
        )

    def decide_audio_from_recommendations(
        self,
        recommendations: list[dict[str, Any]],
        *,
        requested_platform: str = "instagram",
        content_tags: list[str] | None = None,
        account_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.audio_recommendations.decide_audio_from_recommendations(
            recommendations,
            requested_platform=requested_platform,
            content_tags=content_tags,
            account_tags=account_tags,
        )

    def audio_decision_score(self, item: dict[str, Any], *, requested_platform: str) -> tuple[float, list[str], list[str]]:
        return self.audio_recommendations.audio_decision_score(item, requested_platform=requested_platform)

    def audio_decision_confidence(self, primary: dict[str, Any] | None) -> str:
        return self.audio_recommendations.audio_decision_confidence(primary)

    def audio_when_to_use(self, item: dict[str, Any], risks: list[str]) -> str:
        return self.audio_recommendations.audio_when_to_use(item, risks)

    def audio_when_not_to_use(self, item: dict[str, Any], risks: list[str]) -> str:
        return self.audio_recommendations.audio_when_not_to_use(item, risks)

    def audio_operator_instruction(self, primary: dict[str, Any] | None) -> str:
        return self.audio_recommendations.audio_operator_instruction(primary)

    def is_generic_audio_title(self, title: str, platform: str | None = None) -> bool:
        return self.audio_recommendations.is_generic_audio_title(title, platform)

    def audio_catalog_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.audio_recommendations.audio_catalog_payload(row)

    def audio_performance_summary(
        self,
        item: dict[str, Any],
        *,
        campaign_id: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any]:
        return self.audio_recommendations.audio_performance_summary(item, campaign_id=campaign_id, account=account)

    def audio_fatigue_summary(
        self,
        item: dict[str, Any],
        *,
        campaign_id: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any]:
        return self.audio_recommendations.audio_fatigue_summary(item, campaign_id=campaign_id, account=account)

    def audio_key(self, item: dict[str, Any]) -> str:
        return self.audio_recommendations.audio_key(item)

    def score_audio_catalog_item(self, item: dict[str, Any], tags: set[str], accounts: set[str]) -> tuple[float, list[str]]:
        return self.audio_recommendations.score_audio_catalog_item(item, tags, accounts)

    def score_audio_catalog_item_v2(
        self,
        item: dict[str, Any],
        tags: set[str],
        accounts: set[str],
        *,
        account: str | None = None,
    ) -> tuple[float, list[str], dict[str, float], str]:
        return self.audio_recommendations.score_audio_catalog_item_v2(item, tags, accounts, account=account)

    def audio_trend_component(self, item: dict[str, Any]) -> float:
        return self.audio_recommendations.audio_trend_component(item)

    def audio_velocity_component(self, item: dict[str, Any]) -> float:
        return self.audio_recommendations.audio_velocity_component(item)

    def audio_performance_component(self, item: dict[str, Any]) -> float:
        return self.audio_recommendations.audio_performance_component(item)

    def audio_account_fit_component(self, item: dict[str, Any], accounts: set[str]) -> float:
        return self.audio_recommendations.audio_account_fit_component(item, accounts)

    def audio_creator_fit_component(self, item: dict[str, Any], tags: set[str]) -> float:
        return self.audio_recommendations.audio_creator_fit_component(item, tags)

    def audio_fatigue_safety_component(self, item: dict[str, Any]) -> float:
        return self.audio_recommendations.audio_fatigue_safety_component(item)

    def audio_recommendation_confidence(self, item: dict[str, Any], components: dict[str, float]) -> str:
        return self.audio_recommendations.audio_recommendation_confidence(item, components)

    def latest_audio_trend_snapshot_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        return self.audio_recommendations.latest_audio_trend_snapshot_payload(item)

    def audio_memory_trust_summary(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return self.audio_recommendations.audio_memory_trust_summary(items)

    def contentforge_audio_fit_for_item(self, item: dict[str, Any], tags: set[str], *, visual_signal: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self.audio_recommendations.contentforge_audio_fit_for_item(item, tags, visual_signal=visual_signal)

    def audio_catalog_recommendation(self, item: dict[str, Any]) -> dict[str, Any]:
        return self.audio_recommendations.audio_catalog_recommendation(item)

    def norm_tag(self, value: Any) -> str:
        return self.audio_recommendations.norm_tag(value)

    def attach_audio_to_distribution_plan(self, distribution_plan_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.audio_operations.attach_audio_to_distribution_plan(distribution_plan_id, **kwargs)

    def attach_cover_frame_to_rendered_asset(self, rendered_asset_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.audio_operations.attach_cover_frame_to_rendered_asset(rendered_asset_id, **kwargs)

    def select_audio_for_recommendation(self, recommendation_item_id: str, audio_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.audio_operations.select_audio_for_recommendation(recommendation_item_id, audio_id, **kwargs)

    def verify_audio_for_post(self, post_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.audio_operations.verify_audio_for_post(post_id, **kwargs)

    def audio_catalog_row(self, audio_id: str, *, allow_locator: bool = False) -> dict[str, Any]:
        return self.audio_operations.audio_catalog_row(audio_id, allow_locator=allow_locator)

    def audio_selection_payload(self, selection_id: str) -> dict[str, Any]:
        return self.audio_operations.audio_selection_payload(selection_id)

    def link_audio_selection_graph(self, **kwargs: Any) -> None:
        return self.audio_operations.link_audio_selection_graph(**kwargs)

    def resolve_audio_exception_for_recommendation(self, recommendation_item_id: str, **kwargs: Any) -> None:
        return self.audio_operations.resolve_audio_exception_for_recommendation(recommendation_item_id, **kwargs)

    def record_audio_performance_snapshot(self, snapshot: dict[str, Any], *, commit: bool = True) -> dict[str, Any] | None:
        return self.audio_operations.record_audio_performance_snapshot(snapshot, commit=commit)

    def performance_snapshot_score(self, snapshot: dict[str, Any]) -> float:
        return self.audio_operations.performance_snapshot_score(snapshot)

    def audio_workflow_summary(self, rendered: list[dict[str, Any]]) -> dict[str, Any]:
        return self.audio_operations.audio_workflow_summary(rendered)

    def dashboard_audio_intent_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.audio_operations.dashboard_audio_intent_for_asset(asset)

    def audio_task_for_dashboard_intent(self, intent: dict[str, Any]) -> dict[str, Any]:
        return self.audio_operations.audio_task_for_dashboard_intent(intent)

    def normalize_seconds(self, value: Any) -> float | None:
        return self.audio_operations.normalize_seconds(value)

    def first_metadata_value(self, payload: dict[str, Any], *keys: str) -> Any:
        return self.audio_operations.first_metadata_value(payload, *keys)

    def normalize_audio_segment(self, payload: Any) -> dict[str, Any] | None:
        return self.audio_operations.normalize_audio_segment(payload)

    def audio_segment_for_asset(self, audio_intent: dict[str, Any]) -> dict[str, Any] | None:
        return self.audio_operations.audio_segment_for_asset(audio_intent)

    def normalize_cover_frame(self, payload: Any) -> dict[str, Any] | None:
        return self.audio_operations.normalize_cover_frame(payload)

    def cover_frame_for_asset(self, asset: dict[str, Any], caption_context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self.audio_operations.cover_frame_for_asset(asset, caption_context=caption_context)

    def audio_selection_for_asset(self, asset: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        return self.audio_operations.audio_selection_for_asset(asset)

    def audio_intent_is_attached(self, audio_intent: dict[str, Any], audio_id: str | None) -> bool:
        return self.audio_operations.audio_intent_is_attached(audio_intent, audio_id)

    def audio_intent_claims_embedded_media(self, audio_intent: dict[str, Any]) -> bool:
        return self.audio_operations.audio_intent_claims_embedded_media(audio_intent)

    def embedded_audio_verified(self, output_path: str) -> bool | None:
        return self.audio_operations.embedded_audio_verified(output_path)

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

    def creator_os_winner_recommendations(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.creator_os_recommendations.creator_os_winner_recommendations(**kwargs)

    def creator_os_winner_action(self, value: Any) -> str:
        return self.creator_os_recommendations.creator_os_winner_action(value)

    def creator_os_best_rollup_family(self, variant_metrics_rollup: dict[str, Any]) -> dict[str, Any] | None:
        return self.creator_os_recommendations.creator_os_best_rollup_family(variant_metrics_rollup)

    def creator_os_recommended_inventory(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.creator_os_recommendations.creator_os_recommended_inventory(**kwargs)

    def creator_os_lineage_posting_window(self, pattern: dict[str, Any]) -> str:
        return self.creator_os_recommendations.creator_os_lineage_posting_window(pattern)

    def recommended_inventory_request_plan(
        self,
        *,
        creator: str,
        target_count: int | None = None,
        daily_plan: dict[str, Any] | None = None,
        variant_inventory_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.recommended_inventory_request.recommended_inventory_request_plan(
            creator=creator,
            target_count=target_count,
            daily_plan=daily_plan,
            variant_inventory_plan=variant_inventory_plan,
        )

    def recommended_inventory_creator_row(self, daily_plan: dict[str, Any], creator: str) -> dict[str, Any]:
        return self.recommended_inventory_request.recommended_inventory_creator_row(daily_plan, creator)

    def recommended_inventory_existing_by_parent(
        self,
        variant_inventory_plan: dict[str, Any] | None,
    ) -> dict[str, int]:
        return self.recommended_inventory_request.recommended_inventory_existing_by_parent(variant_inventory_plan)

    def recommended_inventory_variant_batch(
        self,
        parent_asset_id: str,
        variant_inventory_plan: dict[str, Any],
    ) -> dict[str, Any]:
        return self.recommended_inventory_request.recommended_inventory_variant_batch(
            parent_asset_id,
            variant_inventory_plan,
        )

    def recommended_inventory_action(self, *, surface: str, story_intent: Any = None) -> str:
        return self.recommended_inventory_request.recommended_inventory_action(
            surface=surface,
            story_intent=story_intent,
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


    def recommend_next_batch(
        self,
        campaign_slug: str,
        *,
        count: int = 20,
        account: str | None = None,
        persist: bool = False,
    ) -> dict[str, Any]:
        return self.recommendations.recommend_next_batch(
            campaign_slug,
            count=count,
            account=account,
            persist=persist,
        )

    def recommendation_runs(self, campaign_slug: str, *, limit: int = 10) -> dict[str, Any]:
        return self.recommendations.recommendation_runs(campaign_slug, limit=limit)

    def top_reference_pattern(self) -> dict[str, Any] | None:
        return self.recommendations.top_reference_pattern()

    def ranked_reference_patterns_for_campaign(self, campaign_id: str) -> list[dict[str, Any]]:
        return self.recommendations.ranked_reference_patterns_for_campaign(campaign_id)

    def ranked_variation_presets_for_campaign(self, campaign_id: str, *, account: str | None = None) -> list[dict[str, Any]]:
        return self.recommendations.ranked_variation_presets_for_campaign(campaign_id, account=account)

    def compact_recommendation_rankings(self, rankings: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
        return self.recommendations.compact_recommendation_rankings(rankings, limit=limit)

    def recommendation_reference_pattern_evidence(self, rankings: list[dict[str, Any]], selected_pattern: dict[str, Any] | None) -> dict[str, Any]:
        return self.recommendations.recommendation_reference_pattern_evidence(rankings, selected_pattern)

    def recommendation_variation_preset_evidence(self, rankings: list[dict[str, Any]], selected_preset: str | None) -> dict[str, Any]:
        return self.recommendations.recommendation_variation_preset_evidence(rankings, selected_preset)

    def latest_recommendation_trust_context(self, campaign_id: str, *, account: str | None) -> dict[str, Any]:
        return self.recommendations.latest_recommendation_trust_context(campaign_id, account=account)

    def apply_recommendation_trust(
        self,
        *,
        score: int | float,
        confidence: str,
        confidence_reason: str,
        recommendation_trust: dict[str, Any],
    ) -> tuple[int, str, str, list[str]]:
        return self.recommendations.apply_recommendation_trust(
            score=score,
            confidence=confidence,
            confidence_reason=confidence_reason,
            recommendation_trust=recommendation_trust,
        )

    def recommendation_item_payload(self, **kwargs: Any) -> dict[str, Any]:
        return self.recommendations.recommendation_item_payload(**kwargs)

    def reference_only_recommendation_item(self, **kwargs: Any) -> dict[str, Any] | None:
        return self.recommendations.reference_only_recommendation_item(**kwargs)

    def write_recommendation_graph_edges(self, **kwargs: Any) -> None:
        self.recommendations.write_recommendation_graph_edges(**kwargs)

    def write_audio_recommendation_graph_edges(self, **kwargs: Any) -> None:
        self.recommendations.write_audio_recommendation_graph_edges(**kwargs)

    def stored_recommendation_item_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.recommendations.stored_recommendation_item_payload(row)

    def exceptions_for_recommendation(self, recommendation_item_id: str) -> list[dict[str, Any]]:
        return self.recommendations.exceptions_for_recommendation(recommendation_item_id)

    def recommendation_item(self, recommendation_item_id: str) -> dict[str, Any]:
        return self.recommendations.recommendation_item(recommendation_item_id)

    def accept_recommendation_item(
        self,
        recommendation_item_id: str,
        *,
        operator: str | None = None,
        notes: str | None = None,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        return self.recommendations.accept_recommendation_item(
            recommendation_item_id,
            operator=operator,
            notes=notes,
            admin_override=admin_override,
            override_reason=override_reason,
        )

    def reject_recommendation_item(
        self,
        recommendation_item_id: str,
        *,
        reason: str | None = None,
        operator: str | None = None,
        notes: str | None = None,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        return self.recommendations.reject_recommendation_item(
            recommendation_item_id,
            reason=reason,
            operator=operator,
            notes=notes,
            admin_override=admin_override,
            override_reason=override_reason,
        )

    def link_recommendation_item(
        self,
        recommendation_item_id: str,
        *,
        source_asset_id: str | None = None,
        render_job_id: str | None = None,
        rendered_asset_id: str | None = None,
        post_id: str | None = None,
        performance_snapshot_id: str | None = None,
        evidence: dict[str, Any] | None = None,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        return self.recommendations.link_recommendation_item(
            recommendation_item_id,
            source_asset_id=source_asset_id,
            render_job_id=render_job_id,
            rendered_asset_id=rendered_asset_id,
            post_id=post_id,
            performance_snapshot_id=performance_snapshot_id,
            evidence=evidence,
            admin_override=admin_override,
            override_reason=override_reason,
        )

    def measure_recommendation_item(
        self,
        recommendation_item_id: str,
        *,
        performance_snapshot_id: str | None = None,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        return self.recommendations.measure_recommendation_item(
            recommendation_item_id,
            performance_snapshot_id=performance_snapshot_id,
            admin_override=admin_override,
            override_reason=override_reason,
        )

    def execute_accepted_recommendation(
        self,
        recommendation_item_id: str,
        *,
        mode: str = "level_2",
        force: bool = False,
        dry_run_render: bool = False,
        run_audit: bool = True,
        contentforge_base_url: str | None = None,
    ) -> dict[str, Any]:
        return self.recommendations.execute_accepted_recommendation(
            recommendation_item_id,
            mode=mode,
            force=force,
            dry_run_render=dry_run_render,
            run_audit=run_audit,
            contentforge_base_url=contentforge_base_url,
        )

    def compact_execution_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return self.recommendations.compact_execution_result(result)

    def create_trust_exceptions_for_recommendation(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.recommendations.create_trust_exceptions_for_recommendation(**kwargs)

    def asset_has_final_audio_proof(self, asset: dict[str, Any]) -> bool:
        return self.recommendations.asset_has_final_audio_proof(asset)

    def recommendation_item_row(self, recommendation_item_id: str) -> dict[str, Any]:
        return self.recommendations.recommendation_item_row(recommendation_item_id)

    def recommendation_item_campaign(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.recommendations.recommendation_item_campaign(row)

    def update_recommendation_lifecycle(self, recommendation_item_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.recommendations.update_recommendation_lifecycle(recommendation_item_id, **kwargs)

    def validate_recommendation_transition(
        self,
        current_status: str,
        next_status: str,
        *,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> None:
        return self.recommendations.validate_recommendation_transition(
            current_status,
            next_status,
            admin_override=admin_override,
            override_reason=override_reason,
        )

    def recommendation_baseline_payload(
        self,
        baseline_summary: dict[str, Any],
        *,
        baseline_score: int | None,
        threshold: int,
    ) -> dict[str, Any]:
        return self.recommendations.recommendation_baseline_payload(
            baseline_summary,
            baseline_score=baseline_score,
            threshold=threshold,
        )

    def recommendation_performance_rows(self, row: dict[str, Any]) -> list[sqlite3.Row]:
        return self.recommendations.recommendation_performance_rows(row)

    def best_asset_history_score(self, asset: dict[str, Any]) -> int | None:
        return self.recommendations.best_asset_history_score(asset)

    def reference_pattern_score(self, pattern: dict[str, Any] | None) -> int:
        return self.recommendations.reference_pattern_score(pattern)

    def recommendation_account_score(self, asset: dict[str, Any], account: str | None) -> int:
        return self.recommendations.recommendation_account_score(asset, account)

    def recommendation_account_fit_evidence(
        self,
        campaign_id: str,
        asset: dict[str, Any],
        account: str | None,
    ) -> dict[str, Any]:
        return self.recommendations.recommendation_account_fit_evidence(campaign_id, asset, account)

    def operational_recommendation_score(self, asset: dict[str, Any]) -> int:
        return self.recommendations.operational_recommendation_score(asset)

    def recommendation_confidence(self, asset: dict[str, Any], pattern: dict[str, Any] | None) -> tuple[str, str]:
        return self.recommendations.recommendation_confidence(asset, pattern)

    def recommendation_data_quality(self, asset: dict[str, Any], pattern: dict[str, Any] | None) -> dict[str, Any]:
        return self.recommendations.recommendation_data_quality(asset, pattern)

    def recommendation_reasons(self, **kwargs: Any) -> list[str]:
        return self.recommendations.recommendation_reasons(**kwargs)

    def asset_target_account(self, asset: dict[str, Any]) -> str | None:
        return self.recommendations.asset_target_account(asset)

    def recommendation_reference_summary(self, pattern: dict[str, Any] | None) -> dict[str, Any] | None:
        return self.recommendations.recommendation_reference_summary(pattern)

    def first_suggested_recipe(self, pattern: dict[str, Any] | None) -> str | None:
        return self.recommendations.first_suggested_recipe(pattern)

    def hook_guidance(self, pattern: dict[str, Any] | None, asset: dict[str, Any]) -> str:
        return self.recommendations.hook_guidance(pattern, asset)

    def caption_guidance(self, pattern: dict[str, Any] | None, asset: dict[str, Any]) -> str:
        return self.recommendations.caption_guidance(pattern, asset)

    def archive_inventory_report(
        self,
        *,
        folder: Path,
        campaign_slug: str,
        creator: str = "Stacey",
        requested_count: int = 25,
        model_slug: str | None = None,
        recent_days: int = 30,
    ) -> dict[str, Any]:
        return self.archive_quality.archive_inventory_report(
            folder=folder,
            campaign_slug=campaign_slug,
            creator=creator,
            requested_count=requested_count,
            model_slug=model_slug,
            recent_days=recent_days,
        )

    def archive_existing_content_duplicate(self, digest: str) -> dict[str, Any] | None:
        return self.archive_quality.archive_existing_content_duplicate(digest)

    def archive_recent_publish_duplicate(self, digest: str, recent_cutoff: Any) -> dict[str, Any] | None:
        return self.archive_quality.archive_recent_publish_duplicate(digest, recent_cutoff)

    def archive_candidate_quality_report(
        self,
        *,
        inventory_report_path: Path,
        requested_count: int = 25,
        exclude_indices: list[int] | None = None,
    ) -> dict[str, Any]:
        return self.archive_quality.archive_candidate_quality_report(
            inventory_report_path=inventory_report_path,
            requested_count=requested_count,
            exclude_indices=exclude_indices,
        )

    def archive_crop_severity(self, probe: dict[str, Any]) -> tuple[str, int, float | None]:
        return self.archive_quality.archive_crop_severity(probe)

    def archive_visual_quality_score(self, probe: dict[str, Any], warnings: list[Any], crop_score: int) -> int:
        return self.archive_quality.archive_visual_quality_score(probe, warnings, crop_score)

    def archive_duplicate_confidence(self, item: dict[str, Any]) -> str:
        return self.archive_quality.archive_duplicate_confidence(item)

    def inventory_slo_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_planning.inventory_slo_report(**kwargs)

    def inventory_buffer_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_planning.inventory_buffer_report(**kwargs)

    def inventory_factory_audit(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_planning.inventory_factory_audit(**kwargs)

    def inventory_yield_analysis(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_planning.inventory_yield_analysis(**kwargs)

    def inventory_buffer_policy_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_planning.inventory_buffer_policy_plan(**kwargs)

    def inventory_slo_enforcement_audit(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_planning.inventory_slo_enforcement_audit(**kwargs)

    def inventory_consumption_simulation(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_planning.inventory_consumption_simulation(**kwargs)

    def inventory_production_requirements(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_planning.inventory_production_requirements(**kwargs)

    def road_to_200_accounts(self) -> dict[str, Any]:
        return self.inventory_planning.road_to_200_accounts()

    def inventory_exception_audit(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_planning.inventory_exception_audit(**kwargs)

    def inventory_factory_readiness_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_planning.inventory_factory_readiness_report(**kwargs)

    def inventory_factory_master_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_planning.inventory_factory_master_report(**kwargs)

    def inventory_autopilot_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_planning.inventory_autopilot_plan(**kwargs)

    def inventory_shortage_repair_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_planning.inventory_shortage_repair_plan(**kwargs)

    def inventory_buffer_protection_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_planning.inventory_buffer_protection_report(**kwargs)

    def inventory_slo_surface_targets(self, minimum_buffer: int) -> dict[str, int]:
        return self.inventory_planning.inventory_slo_surface_targets(minimum_buffer)

    def inventory_health(self, *, current: int, minimum: int) -> str:
        return self.inventory_planning.inventory_health(current=current, minimum=minimum)

    def inventory_stage_counts(self, *, creator: str | None = None, campaign_slug: str | None = None) -> dict[str, int]:
        return self.inventory_planning.inventory_stage_counts(creator=creator, campaign_slug=campaign_slug)

    def inventory_count_related(self, table: str, column: str, asset_ids: set[str]) -> int:
        return self.inventory_planning.inventory_count_related(table, column, asset_ids)

    def inventory_limiting_stage(self, counts: dict[str, int]) -> str:
        return self.inventory_planning.inventory_limiting_stage(counts)

    def inventory_loss_by_stage(self, counts: dict[str, int]) -> dict[str, int]:
        return self.inventory_planning.inventory_loss_by_stage(counts)

    def inventory_repair_actions(self, policy: dict[str, Any]) -> list[dict[str, Any]]:
        return self.inventory_planning.inventory_repair_actions(policy)

    def inventory_recovery_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_recovery.inventory_recovery_report(**kwargs)

    def inventory_recovery_priority_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_recovery.inventory_recovery_priority_report(**kwargs)

    def inventory_recovery_by_blocker(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_recovery.inventory_recovery_by_blocker(**kwargs)

    def inventory_recovery_master_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_recovery.inventory_recovery_master_report(**kwargs)

    def inventory_recovery_blocked_asset(self, readiness: dict[str, Any]) -> dict[str, Any]:
        return self.inventory_recovery.inventory_recovery_blocked_asset(readiness)

    def inventory_recovery_class_for_blocker(self, reason: str) -> str:
        return self.inventory_recovery.inventory_recovery_class_for_blocker(reason)

    def inventory_recovery_class_rows(self, blocked_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.inventory_recovery.inventory_recovery_class_rows(blocked_assets)

    def inventory_recovery_assets_unlocked(self, blocked_assets: list[dict[str, Any]], repaired_classes: list[str]) -> int:
        return self.inventory_recovery.inventory_recovery_assets_unlocked(blocked_assets, repaired_classes)

    def inventory_recovery_priorities(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.inventory_recovery.inventory_recovery_priorities(rows)

    def schedule_safe_production_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.schedule_safe_production.schedule_safe_production_report(**kwargs)

    def schedule_safe_production_waterfall(self, **kwargs: Any) -> dict[str, Any]:
        return self.schedule_safe_production.schedule_safe_production_waterfall(**kwargs)

    def schedule_safe_production_loss_analysis(self, **kwargs: Any) -> dict[str, Any]:
        return self.schedule_safe_production.schedule_safe_production_loss_analysis(**kwargs)

    def schedule_safe_production_capacity_model(self, **kwargs: Any) -> dict[str, Any]:
        return self.schedule_safe_production.schedule_safe_production_capacity_model(**kwargs)

    def schedule_safe_production_master_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.schedule_safe_production.schedule_safe_production_master_report(**kwargs)

    def schedule_safe_production_assets(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.schedule_safe_production.schedule_safe_production_assets(**kwargs)

    def schedule_safe_asset_created_at(self, asset: dict[str, Any]) -> Any:
        return self.schedule_safe_production.schedule_safe_asset_created_at(asset)

    def schedule_safe_production_waterfall_rows(self, assets: list[dict[str, Any]], surface: str) -> list[dict[str, Any]]:
        return self.schedule_safe_production.schedule_safe_production_waterfall_rows(assets, surface)

    def schedule_safe_is_variant_asset(self, asset: dict[str, Any]) -> bool:
        return self.schedule_safe_production.schedule_safe_is_variant_asset(asset)

    def schedule_safe_related_count(self, table: str, column: str, asset_ids: set[str]) -> int:
        return self.schedule_safe_production.schedule_safe_related_count(table, column, asset_ids)

    def schedule_safe_production_variant_checks(self, asset: dict[str, Any], surface: str) -> dict[str, Any]:
        return self.schedule_safe_production.schedule_safe_production_variant_checks(asset, surface)

    def schedule_safe_production_largest_loss(self, waterfall: list[dict[str, Any]]) -> dict[str, Any]:
        return self.schedule_safe_production.schedule_safe_production_largest_loss(waterfall)

    def schedule_safe_production_capacity(self, **kwargs: Any) -> dict[str, Any]:
        return self.schedule_safe_production.schedule_safe_production_capacity(**kwargs)

    def schedule_safe_required_parents_per_day(self, produced_per_day: float, produced: int, parent_count: int) -> int:
        return self.schedule_safe_production.schedule_safe_required_parents_per_day(produced_per_day, produced, parent_count)

    def schedule_safe_required_variants_per_day(self, produced_per_day: float, produced: int, variant_count: int) -> int:
        return self.schedule_safe_production.schedule_safe_required_variants_per_day(produced_per_day, produced, variant_count)

    def schedule_safe_production_summary_key(self, stage: str) -> str:
        return self.schedule_safe_production.schedule_safe_production_summary_key(stage)

    def fresh_schedule_safe_production_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.fresh_reel_production.fresh_schedule_safe_production_plan(**kwargs)

    def fresh_reel_production_batch_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.fresh_reel_production.fresh_reel_production_batch_plan(**kwargs)

    def fresh_reel_production_capacity_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.fresh_reel_production.fresh_reel_production_capacity_plan(**kwargs)

    def fresh_reel_production_master_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.fresh_reel_production.fresh_reel_production_master_report(**kwargs)

    def fresh_reel_current_schedule_safe_inventory(self, **kwargs: Any) -> int:
        return self.fresh_reel_production.fresh_reel_current_schedule_safe_inventory(**kwargs)

    def fresh_reel_downstream_schedule_safe_yield_pct(self) -> float:
        return self.fresh_reel_production.fresh_reel_downstream_schedule_safe_yield_pct()

    def fresh_reel_expected_stage_rows(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.fresh_reel_production.fresh_reel_expected_stage_rows(**kwargs)

    def fresh_reel_stage_evidence(self, stage: str) -> str:
        return self.fresh_reel_production.fresh_reel_stage_evidence(stage)

    def fresh_reel_execution_batches(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.fresh_reel_production.fresh_reel_execution_batches(**kwargs)

    def reel_factory_parent_throughput_proof(self, **kwargs: Any) -> dict[str, Any]:
        return self.reel_factory_reports.reel_factory_parent_throughput_proof(**kwargs)

    def reel_factory_yield_analysis(self, **kwargs: Any) -> dict[str, Any]:
        return self.reel_factory_reports.reel_factory_yield_analysis(**kwargs)

    def reel_factory_failure_analysis(self) -> dict[str, Any]:
        return self.reel_factory_reports.reel_factory_failure_analysis()

    def reel_factory_capacity_model(self, **kwargs: Any) -> dict[str, Any]:
        return self.reel_factory_reports.reel_factory_capacity_model(**kwargs)

    def reel_factory_200_account_readiness(self) -> dict[str, Any]:
        return self.reel_factory_reports.reel_factory_200_account_readiness()

    def reel_factory_master_report(self) -> dict[str, Any]:
        return self.reel_factory_reports.reel_factory_master_report()

    def reel_factory_parent_metrics(self) -> dict[str, int]:
        return self.reel_factory_reports.reel_factory_parent_metrics()

    def reel_factory_parent_qc_pass(self, asset: dict[str, Any]) -> bool:
        return self.reel_factory_reports.reel_factory_parent_qc_pass(asset)

    def reel_factory_confidence(self, metrics: dict[str, int]) -> str:
        return self.reel_factory_reports.reel_factory_confidence(metrics)

    def operator_review_minutes_per_parent(self, metrics: dict[str, int]) -> float:
        return self.reel_factory_reports.operator_review_minutes_per_parent(metrics)

    def reel_factory_intake_metrics(self, metrics: dict[str, int]) -> dict[str, Any]:
        return self.reel_factory_reports.reel_factory_intake_metrics(metrics)

    def reel_factory_parent_creation_metrics(self, metrics: dict[str, int]) -> dict[str, Any]:
        return self.reel_factory_reports.reel_factory_parent_creation_metrics(metrics)

    def reel_factory_quality_gate_metrics(self, yield_report: dict[str, Any]) -> dict[str, Any]:
        return self.reel_factory_reports.reel_factory_quality_gate_metrics(yield_report)

    def reel_factory_operational_readiness_metrics(self, yield_report: dict[str, Any]) -> dict[str, Any]:
        return self.reel_factory_reports.reel_factory_operational_readiness_metrics(yield_report)

    def reel_factory_human_cost(self, metrics: dict[str, int]) -> dict[str, Any]:
        return self.reel_factory_reports.reel_factory_human_cost(metrics)

    def reel_factory_rating(self, proof: dict[str, Any]) -> float:
        return self.reel_factory_reports.reel_factory_rating(proof)

    def parent_factory_yield_waterfall(self, **kwargs: Any) -> dict[str, Any]:
        return self.parent_factory_reports.parent_factory_yield_waterfall(**kwargs)

    def parent_factory_loss_analysis(self, **kwargs: Any) -> dict[str, Any]:
        return self.parent_factory_reports.parent_factory_loss_analysis(**kwargs)

    def parent_factory_rejection_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.parent_factory_reports.parent_factory_rejection_report(**kwargs)

    def parent_factory_quality_gate_analysis(self) -> dict[str, Any]:
        return self.parent_factory_reports.parent_factory_quality_gate_analysis()

    def parent_factory_optimization_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.parent_factory_reports.parent_factory_optimization_plan(**kwargs)

    def parent_factory_master_optimization_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.parent_factory_reports.parent_factory_master_optimization_report(**kwargs)

    def parent_factory_recoverable_yield(self) -> dict[str, Any]:
        return self.parent_factory_reports.parent_factory_recoverable_yield()

    def parent_factory_throughput_recovery_plan(self) -> dict[str, Any]:
        return self.parent_factory_reports.parent_factory_throughput_recovery_plan()

    def parent_factory_53_parent_feasibility(self) -> dict[str, Any]:
        return self.parent_factory_reports.parent_factory_53_parent_feasibility()

    def parent_factory_secondary_loss_analysis(self) -> dict[str, Any]:
        return self.parent_factory_reports.parent_factory_secondary_loss_analysis()

    def parent_factory_true_yield_model(self) -> dict[str, Any]:
        return self.parent_factory_reports.parent_factory_true_yield_model()

    def parent_factory_realistic_53_parent_plan(self) -> dict[str, Any]:
        return self.parent_factory_reports.parent_factory_realistic_53_parent_plan()

    def parent_factory_stage_order(self) -> list[str]:
        return self.parent_factory_reports.parent_factory_stage_order()

    def parent_factory_detailed_stage_counts(self, metrics: dict[str, int]) -> dict[str, int]:
        return self.parent_factory_reports.parent_factory_detailed_stage_counts(metrics)

    def parent_factory_highest_roi(self, reasons: list[dict[str, Any]]) -> str:
        return self.parent_factory_reports.parent_factory_highest_roi(reasons)

    def parent_factory_top_fixes(self, reasons: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.parent_factory_reports.parent_factory_top_fixes(reasons)

    def parent_factory_human_bottleneck(self, **kwargs: Any) -> dict[str, Any]:
        return self.parent_factory_reports.parent_factory_human_bottleneck(**kwargs)

    def parent_factory_yield_explanation(self, waterfall: dict[str, Any], loss: dict[str, Any]) -> str:
        return self.parent_factory_reports.parent_factory_yield_explanation(waterfall, loss)

    def secondary_loss_reason(self, stage: str, loss_count: int) -> str:
        return self.parent_factory_reports.secondary_loss_reason(stage, loss_count)

    def parent_factory_trial_loss_buckets(self, waterfall: dict[str, Any]) -> dict[str, int]:
        return self.parent_factory_reports.parent_factory_trial_loss_buckets(waterfall)

    def parent_factory_trial_stage_repairable(self, stage: str) -> bool:
        return self.parent_factory_reports.parent_factory_trial_stage_repairable(stage)

    def parent_factory_production_trial(self) -> dict[str, Any]:
        return self.parent_factory_trials.parent_factory_production_trial()

    def latest_measured_53_parent_production_trial(self) -> dict[str, Any] | None:
        return self.parent_factory_trials.latest_measured_53_parent_production_trial()

    def parent_factory_53_parent_trial(self) -> dict[str, Any]:
        return self.parent_factory_trials.parent_factory_53_parent_trial()

    def parent_factory_trial_results(self) -> dict[str, Any]:
        return self.parent_factory_trials.parent_factory_trial_results()

    def parent_factory_trial_analysis(self) -> dict[str, Any]:
        return self.parent_factory_trials.parent_factory_trial_analysis()

    def parent_factory_post_gate_fresh_batch_proof(self) -> dict[str, Any]:
        return self.parent_factory_trials.parent_factory_post_gate_fresh_batch_proof()

    def parent_factory_production_scorecard(self) -> dict[str, Any]:
        return self.parent_factory_trials.parent_factory_production_scorecard()

    def parent_factory_real_yield_report(self) -> dict[str, Any]:
        return self.parent_factory_trials.parent_factory_real_yield_report()

    def post_gate_fresh_batch_candidates(self) -> list[dict[str, str]]:
        return self.parent_factory_trials.post_gate_fresh_batch_candidates()

    def post_gate_blocked_candidate_evidence(self, sandbox: Any, result: dict[str, Any]) -> dict[str, Any] | None:
        return self.parent_factory_trials.post_gate_blocked_candidate_evidence(sandbox, result)

    def parent_factory_autopilot_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.parent_factory_planning.parent_factory_autopilot_plan(**kwargs)

    def parent_factory_shortfall_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.parent_factory_planning.parent_factory_shortfall_report(**kwargs)

    def parent_factory_production_targets(self, **kwargs: Any) -> dict[str, Any]:
        return self.parent_factory_planning.parent_factory_production_targets(**kwargs)

    def contentforge_visual_qc_failure_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.contentforge_visual_qc.contentforge_visual_qc_failure_report(**kwargs)

    def contentforge_visual_qc_waterfall(self, **kwargs: Any) -> dict[str, Any]:
        return self.contentforge_visual_qc.contentforge_visual_qc_waterfall(**kwargs)

    def contentforge_visual_qc_loss_analysis(self, **kwargs: Any) -> dict[str, Any]:
        return self.contentforge_visual_qc.contentforge_visual_qc_loss_analysis(**kwargs)

    def contentforge_visual_qc_repair_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.contentforge_visual_qc.contentforge_visual_qc_repair_plan(**kwargs)

    def contentforge_visual_qc_master_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.contentforge_visual_qc.contentforge_visual_qc_master_report(**kwargs)

    def contentforge_visual_qc_failure_for_asset(self, asset: dict[str, Any], surface: str) -> dict[str, Any]:
        return self.contentforge_visual_qc.contentforge_visual_qc_failure_for_asset(asset, surface)

    def contentforge_visual_qc_failure_category(
        self,
        asset: dict[str, Any],
        blockers: list[str],
        readiness: dict[str, Any],
        publishability: dict[str, Any],
    ) -> str:
        return self.contentforge_visual_qc.contentforge_visual_qc_failure_category(asset, blockers, readiness, publishability)

    def contentforge_non_visual_gates_pass(
        self,
        checks: dict[str, Any],
        readiness: dict[str, Any],
        publishability: dict[str, Any],
        non_visual_blockers: list[str],
    ) -> bool:
        return self.contentforge_visual_qc.contentforge_non_visual_gates_pass(
            checks,
            readiness,
            publishability,
            non_visual_blockers,
        )

    def contentforge_visual_qc_category_rows(self, failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.contentforge_visual_qc.contentforge_visual_qc_category_rows(failures)

    def contentforge_visual_qc_recovered_inventory(self, failures: list[dict[str, Any]], categories: list[str]) -> int:
        return self.contentforge_visual_qc.contentforge_visual_qc_recovered_inventory(failures, categories)

    def contentforge_visual_qc_answer(self, top: dict[str, Any], total_failures: int) -> str:
        return self.contentforge_visual_qc.contentforge_visual_qc_answer(top, total_failures)

    def multi_blocker_inventory_unlock_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.multi_blocker_unlock.multi_blocker_inventory_unlock_report(**kwargs)

    def multi_blocker_inventory_unlock_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self.multi_blocker_unlock.multi_blocker_inventory_unlock_plan(**kwargs)

    def inventory_unlock_minimal_fix_set(self, **kwargs: Any) -> dict[str, Any]:
        return self.multi_blocker_unlock.inventory_unlock_minimal_fix_set(**kwargs)

    def inventory_unlock_master_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.multi_blocker_unlock.inventory_unlock_master_report(**kwargs)

    def multi_blocker_asset_row(self, readiness: dict[str, Any]) -> dict[str, Any]:
        return self.multi_blocker_unlock.multi_blocker_asset_row(readiness)

    def multi_blocker_repair_class(self, reason: str) -> str:
        return self.multi_blocker_unlock.multi_blocker_repair_class(reason)

    def multi_blocker_combo_rows(self, blocked_assets: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
        return self.multi_blocker_unlock.multi_blocker_combo_rows(blocked_assets, **kwargs)

    def multi_blocker_assets_unlocked(self, blocked_assets: list[dict[str, Any]], repair_classes: list[str]) -> int:
        return self.multi_blocker_unlock.multi_blocker_assets_unlocked(blocked_assets, repair_classes)

    def multi_blocker_estimated_minutes(self, blocked_assets: list[dict[str, Any]], repair_classes: list[str]) -> int:
        return self.multi_blocker_unlock.multi_blocker_estimated_minutes(blocked_assets, repair_classes)

    def multi_blocker_combo_difficulty(self, repair_classes: list[str]) -> str:
        return self.multi_blocker_unlock.multi_blocker_combo_difficulty(repair_classes)

    def multi_blocker_best_combo(self, combo_rows: list[dict[str, Any]], size: int) -> dict[str, Any]:
        return self.multi_blocker_unlock.multi_blocker_best_combo(combo_rows, size)

    def multi_blocker_minimal_fix_set(self, combo_rows: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        return self.multi_blocker_unlock.multi_blocker_minimal_fix_set(combo_rows, **kwargs)

    def asset_uniqueness_values(self, asset: dict[str, Any], **kwargs: Any) -> dict[str, str]:
        return self.inventory_perceptual.asset_uniqueness_values(asset, **kwargs)

    def ensure_rendered_asset_perceptual_metadata(self, rendered_asset_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_perceptual.ensure_rendered_asset_perceptual_metadata(rendered_asset_id, **kwargs)

    def pdq_cluster_id_for_fingerprint(self, **kwargs: Any) -> str:
        return self.inventory_perceptual.pdq_cluster_id_for_fingerprint(**kwargs)

    def reserve_inventory_asset(self, asset_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_reservations.reserve_inventory_asset(asset_id, **kwargs)

    def expire_inventory_reservations(self, **kwargs: Any) -> int:
        return self.inventory_reservations.expire_inventory_reservations(**kwargs)

    def release_inventory_reservation(self, reservation_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.inventory_reservations.release_inventory_reservation(reservation_id, **kwargs)

    def inventory_uniqueness_conflicts(self, asset: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
        return self.inventory_reservations.inventory_uniqueness_conflicts(asset, **kwargs)

    def reservation_adjusted_inventory(self, readiness_rows: list[dict[str, Any]], **kwargs: Any) -> dict[str, int]:
        return self.inventory_reservations.reservation_adjusted_inventory(readiness_rows, **kwargs)

    def dashboard(self, campaign_slug: str | None = None) -> dict[str, Any]:
        return self.campaign_overview.dashboard(campaign_slug)

    def default_dashboard_campaign(self, campaigns: list[dict[str, Any]]) -> dict[str, Any] | None:
        return self.campaign_overview.default_dashboard_campaign(campaigns)

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

    def account_plan(self, campaign_slug: str, *, user_id: str, usage: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.account_planning.account_plan(campaign_slug, user_id=user_id, usage=usage)

    def ranking(self, campaign_slug: str) -> dict[str, Any]:
        return self.account_planning.ranking(campaign_slug)

    def quality_score_for_ranking(self, asset: dict[str, Any]) -> int:
        return self.account_planning.quality_score_for_ranking(asset)

    def history_score(self, summary: dict[str, Any] | None) -> int:
        return self.account_planning.history_score(summary)

    def account_fit_score(self, asset: dict[str, Any]) -> int:
        return self.account_planning.account_fit_score(asset)

    def novelty_score(self, asset: dict[str, Any]) -> int:
        return self.account_planning.novelty_score(asset)

    def dashboard_rendered_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self.account_planning.dashboard_rendered_asset(asset)

    def generated_asset_lineage(
        self,
        source_prompt: dict[str, Any],
        reference_pattern: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return self.account_planning.generated_asset_lineage(source_prompt, reference_pattern)

    def audio_recommendations_for_asset(
        self,
        *,
        caption_generation: dict[str, Any],
        reference_pattern: dict[str, Any] | None,
        recipe: str | None,
        account_tags: list[str],
    ) -> dict[str, Any]:
        return self.account_planning.audio_recommendations_for_asset(
            caption_generation=caption_generation,
            reference_pattern=reference_pattern,
            recipe=recipe,
            account_tags=account_tags,
        )

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

    def prepare_reel_inputs(
        self,
        *,
        campaign_slug: str,
        hooks: list[str | dict[str, Any]],
        recipes: list[str] | None = None,
        caption_color: str | None = None,
        notes: str | None = None,
        force_new: bool = False,
    ) -> dict[str, Any]:
        return self.reel_execution.prepare_reel_inputs(
            campaign_slug=campaign_slug,
            hooks=hooks,
            recipes=recipes,
            caption_color=caption_color,
            notes=notes,
            force_new=force_new,
        )

    def rotate_hooks_for_source(self, hooks: list[str | dict[str, Any]], source_index: int) -> list[str | dict[str, Any]]:
        return self.reel_execution.rotate_hooks_for_source(hooks, source_index)

    def reel_sidecar_hooks(self, hooks: list[str | dict[str, Any]]) -> tuple[list[str | dict[str, Any]], list[dict[str, Any]]]:
        return self.reel_execution.reel_sidecar_hooks(hooks)

    def next_reel_clip_number(self, raw_dir: Any) -> int:
        return self.reel_execution.next_reel_clip_number(raw_dir)

    def run_reel_factory(
        self,
        *,
        campaign_slug: str,
        workers: int = 3,
        dry_run: bool = False,
        caption_band: str = "auto",
        caption_color: str = "light",
        caption_style: str = "ig",
        caption_font: str = "Instagram Sans Condensed",
        caption_placement_qc: bool = True,
        phone_finalize: bool = True,
        rerender_all: bool = False,
        max_outputs_per_clip: int | None = None,
    ) -> dict[str, Any]:
        return self.reel_execution.run_reel_factory(
            campaign_slug=campaign_slug,
            workers=workers,
            dry_run=dry_run,
            caption_band=caption_band,
            caption_color=caption_color,
            caption_style=caption_style,
            caption_font=caption_font,
            caption_placement_qc=caption_placement_qc,
            phone_finalize=phone_finalize,
            rerender_all=rerender_all,
            max_outputs_per_clip=max_outputs_per_clip,
        )

    def sync_reel_outputs(self, *, campaign_slug: str) -> dict[str, Any]:
        return self.reel_execution.sync_reel_outputs(campaign_slug=campaign_slug)

    def model_slug_for_campaign(self, campaign_id: str) -> str:
        return self.reel_execution.model_slug_for_campaign(campaign_id)

    def ratio_from_filename(self, filename: str) -> str:
        return self.reel_execution.ratio_from_filename(filename)

    def caption_generation_for_clip(self, clip_stem: str) -> dict[str, Any]:
        return self.reel_execution.caption_generation_for_clip(clip_stem)

    def caption_outcome_context_for_reel_output(
        self,
        *,
        clip_stem: str,
        caption_text: str,
        caption_hash: str | None,
        recipe: str,
        source_path: str,
        rendered_path: str,
        creator_model: str,
        lineage: dict[str, Any],
    ) -> dict[str, Any]:
        return self.reel_execution.caption_outcome_context_for_reel_output(
            clip_stem=clip_stem,
            caption_text=caption_text,
            caption_hash=caption_hash,
            recipe=recipe,
            source_path=source_path,
            rendered_path=rendered_path,
            creator_model=creator_model,
            lineage=lineage,
        )

    def lineage_first_present(self, lineage: dict[str, Any] | None, key: str) -> Any:
        return self.reel_execution.lineage_first_present(lineage, key)

    def lineage_placement_decision(self, lineage: dict[str, Any] | None) -> dict[str, Any] | None:
        return self.reel_execution.lineage_placement_decision(lineage)

    def caption_lane_from_render_recipe(self, recipe: str | None) -> str:
        return self.reel_execution.caption_lane_from_render_recipe(recipe)

    def audio_intent_from_reference_recommendations(self, payload: dict[str, Any], *, now: str) -> dict[str, Any]:
        return self.reel_execution.audio_intent_from_reference_recommendations(payload, now=now)

    def backfill_synced_reel_output_lineage(
        self,
        *,
        asset: dict[str, Any],
        clip_stem: str,
        caption_text: str,
        recipe: str,
        output_path: str,
        rendered_path: str,
        creator_model: str,
        lineage: dict[str, Any] | None = None,
    ) -> bool:
        return self.reel_execution.backfill_synced_reel_output_lineage(
            asset=asset,
            clip_stem=clip_stem,
            caption_text=caption_text,
            recipe=recipe,
            output_path=output_path,
            rendered_path=rendered_path,
            creator_model=creator_model,
            lineage=lineage,
        )

    def make_batch(
        self,
        *,
        folder: Any,
        campaign_slug: str,
        model_slug: str,
        output_format: str = "auto",
        variant_count: int = 20,
        reference_pattern: str | None = "auto",
        contentforge_base_url: str | None = None,
        user_id: str | None = None,
        dry_run_export: bool = True,
        workers: int = 3,
        recipes: list[str] | None = None,
        auto_approve_warning_only: bool = True,
        source_prompt: str | None = None,
        import_notes: str | None = None,
    ) -> dict[str, Any]:
        return self.make_batch_repo.make_batch(
            folder=folder,
            campaign_slug=campaign_slug,
            model_slug=model_slug,
            output_format=output_format,
            variant_count=variant_count,
            reference_pattern=reference_pattern,
            contentforge_base_url=contentforge_base_url,
            user_id=user_id,
            dry_run_export=dry_run_export,
            workers=workers,
            recipes=recipes,
            auto_approve_warning_only=auto_approve_warning_only,
            source_prompt=source_prompt,
            import_notes=import_notes,
        )

    def run_slideshow_pack(
        self,
        *,
        campaign_slug: str,
        variant_count: int,
        title: str,
        cluster_key: str | None = None,
        media_types: set[str] | None = None,
    ) -> dict[str, Any]:
        return self.make_batch_repo.run_slideshow_pack(
            campaign_slug=campaign_slug,
            variant_count=variant_count,
            title=title,
            cluster_key=cluster_key,
            media_types=media_types,
        )

    def campaign_source_media_summary(self, campaign_id: str) -> dict[str, int]:
        return self.make_batch_repo.campaign_source_media_summary(campaign_id)

    def formats_for_batch(self, selected_format: str, source_mix: dict[str, int]) -> list[str]:
        return self.make_batch_repo.formats_for_batch(selected_format, source_mix)

    def finished_video_hooks(self, format_type: str, pattern: dict[str, Any], count: int = 5) -> list[dict[str, Any]]:
        return self.finished_video.finished_video_hooks(format_type, pattern, count=count)

    def intake_finished_video(
        self,
        *,
        input_path: Any,
        model_slug: str,
        platform: str = "instagram",
        goal: str = "reach",
        reference_pattern: str | None = "auto",
        campaign_slug: str | None = None,
        contentforge_base_url: str | None = None,
        user_id: str | None = None,
        dry_run_export: bool = True,
        variant_count: int = 10,
        workers: int = 3,
        recipes: list[str] | None = None,
        creative_plan: str | None = None,
        style_lane: str | None = None,
        source_lineage_path: Any | None = None,
    ) -> dict[str, Any]:
        return self.finished_video.intake_finished_video(
            input_path=input_path,
            model_slug=model_slug,
            platform=platform,
            goal=goal,
            reference_pattern=reference_pattern,
            campaign_slug=campaign_slug,
            contentforge_base_url=contentforge_base_url,
            user_id=user_id,
            dry_run_export=dry_run_export,
            variant_count=variant_count,
            workers=workers,
            recipes=recipes,
            creative_plan=creative_plan,
            style_lane=style_lane,
            source_lineage_path=source_lineage_path,
        )

    def finished_video_preflight(self, probe: dict[str, Any]) -> list[dict[str, str]]:
        return self.finished_video.finished_video_preflight(probe)

    def finished_video_style_lane_format(self, style_lane: str | None) -> str | None:
        return self.finished_video.finished_video_style_lane_format(style_lane)

    def finished_video_caption_band(self, format_type: str) -> str:
        return self.finished_video.finished_video_caption_band(format_type)

    def finished_video_caption_font(self, format_type: str) -> str:
        return self.finished_video.finished_video_caption_font(format_type)

    def classify_finished_video_format(self, path: Any) -> str:
        return self.finished_video.classify_finished_video_format(path)

    def review_rendered_asset(
        self,
        rendered_asset_id: str,
        *,
        decision: str,
        notes: str | None = None,
        require_safe_audit: bool = False,
    ) -> dict[str, Any]:
        return self.finished_video.review_rendered_asset(
            rendered_asset_id,
            decision=decision,
            notes=notes,
            require_safe_audit=require_safe_audit,
        )

    def approve_rendered_asset(
        self,
        rendered_asset_id: str,
        *,
        notes: str | None = None,
        require_safe_audit: bool = False,
    ) -> dict[str, Any]:
        return self.finished_video.approve_rendered_asset(
            rendered_asset_id,
            notes=notes,
            require_safe_audit=require_safe_audit,
        )

    def register_finished_video(
        self,
        *,
        input_path: Any,
        campaign_slug: str,
        model_slug: str,
        caption: str,
        instagram_post_caption: str | None = None,
        caption_hash: str | None = None,
        caption_bank: str | None = None,
        creator_mix: str | None = None,
        creator_model: str | None = None,
        track_id: str | None = None,
        track_name: str | None = None,
        audio_source: str | None = None,
        selected_reason: str | None = None,
        operator: str | None = None,
        approval_reason: str | None = None,
        review_batch: str | None = None,
        caption_placement_policy: str | None = None,
        caption_placement_decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.finished_video.register_finished_video(
            input_path=input_path,
            campaign_slug=campaign_slug,
            model_slug=model_slug,
            caption=caption,
            instagram_post_caption=instagram_post_caption,
            caption_hash=caption_hash,
            caption_bank=caption_bank,
            creator_mix=creator_mix,
            creator_model=creator_model,
            track_id=track_id,
            track_name=track_name,
            audio_source=audio_source,
            selected_reason=selected_reason,
            operator=operator,
            approval_reason=approval_reason,
            review_batch=review_batch,
            caption_placement_policy=caption_placement_policy,
            caption_placement_decision=caption_placement_decision,
        )

    def record_lineage_costs(self, lineage: dict[str, Any]) -> None:
        self.finished_video.record_lineage_costs(lineage)

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

    def validate_instagram_trial_reel_intent(
        self,
        *,
        content_surface: str,
        distribution_surface: str,
        media_type: str,
        instagram_trial_reels: bool,
        trial_graduation_strategy: str | None,
    ) -> str | None:
        return self.distribution.validate_instagram_trial_reel_intent(
            content_surface=content_surface,
            distribution_surface=distribution_surface,
            media_type=media_type,
            instagram_trial_reels=instagram_trial_reels,
            trial_graduation_strategy=trial_graduation_strategy,
        )

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

    def exception_queue_report(
        self,
        *,
        daily_plan: dict[str, Any] | None = None,
        execution_readiness: dict[str, Any] | None = None,
        publishability_report: dict[str, Any] | None = None,
        surface_readiness_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.exceptions.exception_queue_report(
            daily_plan=daily_plan,
            execution_readiness=execution_readiness,
            publishability_report=publishability_report,
            surface_readiness_report=surface_readiness_report,
        )

    def exception_queue_summary(self, **kwargs: Any) -> dict[str, Any]:
        return self.exceptions.exception_queue_summary(**kwargs)

    def exception_queue_priority_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.exceptions.exception_queue_priority_report(**kwargs)

    def exception_queue_owner_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.exceptions.exception_queue_owner_report(**kwargs)

    def exception_queue_item(
        self,
        *,
        severity: str,
        system: str,
        account: Any,
        asset: Any,
        reason: str,
        next_action: str,
        count: int | None = None,
    ) -> dict[str, Any]:
        return self.exceptions.exception_queue_item(
            severity=severity,
            system=system,
            account=account,
            asset=asset,
            reason=reason,
            next_action=next_action,
            count=count,
        )

    def exception_severity_for_reason(self, reason: str) -> str:
        return self.exceptions.exception_severity_for_reason(reason)

    def exception_next_action(self, reason: str) -> str:
        return self.exceptions.exception_next_action(reason)

    def exception_category_for_reason(self, reason: str, system: str) -> str:
        return self.exceptions.exception_category_for_reason(reason, system)

    def exception_owner_for_category(self, category: str, system: str) -> str:
        return self.exceptions.exception_owner_for_category(category, system)

    def exception_repairable(self, reason: str) -> bool:
        return self.exceptions.exception_repairable(reason)

    def exception_resolution_minutes(self, reason: str, *, count: int | None = None) -> int:
        return self.exceptions.exception_resolution_minutes(reason, count=count)

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

    def creator_os_local_schedule_safe_assets(self, creator: str) -> list[dict[str, Any]]:
        return self.creator_os_drafts.creator_os_local_schedule_safe_assets(creator)

    def creator_os_target_date(self, *, date: str | None = None, generated_at: str | None = None) -> str:
        return self.creator_os_drafts.creator_os_target_date(date=date, generated_at=generated_at)

    def creator_os_account_surface_status(self, account: dict[str, Any], *, reel_needed: bool) -> dict[str, dict[str, Any]]:
        return self.creator_os_drafts.creator_os_account_surface_status(account, reel_needed=reel_needed)

    def creator_os_surface_summary_for_creator(self, **kwargs: Any) -> dict[str, Any]:
        return self.creator_os_drafts.creator_os_surface_summary_for_creator(**kwargs)

    def creator_os_gap_blocking_reason(self, reason: str, blockers: list[str], item: dict[str, Any]) -> str:
        return self.creator_os_drafts.creator_os_gap_blocking_reason(reason, blockers, item)

    def creator_os_draft_items(self, planner_inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.creator_os_drafts.creator_os_draft_items(planner_inputs)

    def creator_os_draft_has_instagram_post_caption(self, draft: dict[str, Any]) -> bool:
        return self.creator_os_drafts.creator_os_draft_has_instagram_post_caption(draft)

    def creator_os_draft_exclusion_reason(self, draft: dict[str, Any]) -> str:
        return self.creator_os_drafts.creator_os_draft_exclusion_reason(draft)

    def creator_os_draft_exclusion_counts(self, creator: str, draft_items: list[dict[str, Any]]) -> dict[str, int]:
        return self.creator_os_drafts.creator_os_draft_exclusion_counts(creator, draft_items)

    def creator_os_schedule_safe_drafts(self, creator: str, draft_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.creator_os_drafts.creator_os_schedule_safe_drafts(creator, draft_items)

    def creator_os_execution_draft_blockers(self, creator: str, draft_items: list[dict[str, Any]]) -> list[str]:
        return self.creator_os_drafts.creator_os_execution_draft_blockers(creator, draft_items)

    def creator_os_explicit_false(self, item: dict[str, Any], *keys: str) -> bool:
        return self.creator_os_drafts.creator_os_explicit_false(item, *keys)

    def creator_os_inventory_for_creator(
        self,
        creator: str,
        planner_inputs: list[dict[str, Any]],
        draft_items: list[dict[str, Any]],
    ) -> dict[str, int]:
        return self.creator_os_drafts.creator_os_inventory_for_creator(creator, planner_inputs, draft_items)

    def creator_os_blocked_account_breakdown(self, blocked_accounts: list[dict[str, Any]]) -> dict[str, int]:
        return self.creator_os_drafts.creator_os_blocked_account_breakdown(blocked_accounts)

    def creator_os_manager_decision(self, **kwargs: Any) -> dict[str, str]:
        return self.creator_os_drafts.creator_os_manager_decision(**kwargs)

    def creator_os_account_state(self, account: dict[str, Any], blocked_reason: str) -> str:
        return self.creator_os_drafts.creator_os_account_state(account, blocked_reason)

    def creator_os_post_time(self, value: Any) -> str:
        return self.creator_os_drafts.creator_os_post_time(value)

    def creator_os_recommended_post_count(self, state: str, needs_post_today: bool) -> int:
        return self.creator_os_drafts.creator_os_recommended_post_count(state, needs_post_today)

    def recommended_story_intent_for_date(self, target_date: str, *, creator: str | None = None) -> str:
        return self.creator_os_drafts.recommended_story_intent_for_date(target_date, creator=creator)

    def recommended_story_style_for_intent(self, intent: str) -> str:
        return self.creator_os_drafts.recommended_story_style_for_intent(intent)

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

    def variant_inventory_plan(
        self,
        *,
        creator: str,
        campaign: str,
        target_draft_shortfall: int,
        preset: str = "caption_safe_v2",
        max_variants_per_parent: int = 10,
        minimum_recommended_per_parent: int = 3,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        return self.winner_expansion.variant_inventory_plan(
            creator=creator,
            campaign=campaign,
            target_draft_shortfall=target_draft_shortfall,
            preset=preset,
            max_variants_per_parent=max_variants_per_parent,
            minimum_recommended_per_parent=minimum_recommended_per_parent,
            dry_run=dry_run,
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

    def creative_knowledge_base(self, **kwargs: Any) -> dict[str, Any]:
        return self.creative_knowledge.creative_knowledge_base(**kwargs)

    def creative_pattern_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.creative_knowledge.creative_pattern_report(**kwargs)

    def creative_caption_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.creative_knowledge.creative_caption_report(**kwargs)

    def creative_audio_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.creative_knowledge.creative_audio_report(**kwargs)

    def creative_surface_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.creative_knowledge.creative_surface_report(**kwargs)

    def creative_account_tier_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.creative_knowledge.creative_account_tier_report(**kwargs)

    def creative_window_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.creative_knowledge.creative_window_report(**kwargs)

    def creative_performance_analysis(self, **kwargs: Any) -> dict[str, Any]:
        return self.creative_knowledge.creative_performance_analysis(**kwargs)

    def creator_learning_summary(self, **kwargs: Any) -> dict[str, Any]:
        return self.creative_knowledge.creator_learning_summary(**kwargs)

    def next_content_recommendations(self, **kwargs: Any) -> dict[str, Any]:
        return self.creative_knowledge.next_content_recommendations(**kwargs)

    def creative_learning_confidence_model(self, **kwargs: Any) -> dict[str, Any]:
        return self.creative_knowledge.creative_learning_confidence_model(**kwargs)

    def creative_fatigue_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.creative_knowledge.creative_fatigue_report(**kwargs)

    def creative_surface_comparison_report(self, **kwargs: Any) -> dict[str, Any]:
        return self.creative_knowledge.creative_surface_comparison_report(**kwargs)

    def recommendation_quality_audit(self, **kwargs: Any) -> dict[str, Any]:
        return self.creative_knowledge.recommendation_quality_audit(**kwargs)

    def build_creative_knowledge_base(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.build_creative_knowledge_base(*args, **kwargs)

    def build_creative_performance_analysis(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.build_creative_performance_analysis(*args, **kwargs)

    def creative_performance_baseline(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_performance_baseline(*args, **kwargs)

    def creative_performance_assessment(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_performance_assessment(*args, **kwargs)

    def creative_more_recommendations(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_more_recommendations(*args, **kwargs)

    def creative_less_recommendations(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_less_recommendations(*args, **kwargs)

    def recommendation_explainability(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.recommendation_explainability(*args, **kwargs)

    def confidence_score(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.confidence_score(*args, **kwargs)

    def learning_confidence_classification(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.learning_confidence_classification(*args, **kwargs)

    def creative_fatigue_signals(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_fatigue_signals(*args, **kwargs)

    def metric_decline_pct(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.metric_decline_pct(*args, **kwargs)

    def engagement_decline_pct(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.engagement_decline_pct(*args, **kwargs)

    def avg_result_metric(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.avg_result_metric(*args, **kwargs)

    def creative_surface_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_surface_rows(*args, **kwargs)

    def recommendation_quality_bucket(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.recommendation_quality_bucket(*args, **kwargs)

    def creative_analysis_confidence(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_analysis_confidence(*args, **kwargs)

    def creative_dimension_label(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_dimension_label(*args, **kwargs)

    def creative_pattern_priority(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_pattern_priority(*args, **kwargs)

    def creative_knowledge_results_for_report(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_knowledge_results_for_report(*args, **kwargs)

    def creative_knowledge_rows(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_knowledge_rows(*args, **kwargs)

    def creative_knowledge_result(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_knowledge_result(*args, **kwargs)

    def creative_knowledge_score_weights(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_knowledge_score_weights(*args, **kwargs)

    def creative_knowledge_score(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_knowledge_score(*args, **kwargs)

    def creative_result_group(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_result_group(*args, **kwargs)

    def creative_result_lineage(self, *args: Any, **kwargs: Any) -> Any:
        return self.creative_knowledge.creative_result_lineage(*args, **kwargs)

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

    def batch_summary(self, campaign_slug: str) -> dict[str, Any]:
        return self.export_summary.batch_summary(campaign_slug)

    def daily_production_counters(
        self,
        campaign_slug: str,
        *,
        dashboard: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.export_summary.daily_production_counters(campaign_slug, dashboard=dashboard)

    def variant_pack_groups(self, rendered: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.export_summary.variant_pack_groups(rendered)

    def export_manifest(self, *, campaign_slug: str) -> dict[str, Any]:
        return self.export_summary.export_manifest(campaign_slug=campaign_slug)

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

    def list_campaigns(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM campaigns ORDER BY updated_at DESC").fetchall()
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
        rows = self.conn.execute("SELECT * FROM rendered_assets WHERE campaign_id = ? ORDER BY created_at DESC", (campaign_id,)).fetchall()
        return [dict(row) for row in rows]

    def rendered_asset(self, rendered_asset_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM rendered_assets WHERE id = ?", (rendered_asset_id,)).fetchone()
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

    def road_to_accounts_payload(self, *, accounts: int, production: dict[str, Any]) -> dict[str, Any]:
        posts = int(production.get("postsPerDay") or 0)
        return {
            "schema": f"creator_os.road_to_{accounts}_accounts.v1",
            "accounts": accounts,
            "requiredInventoryBuffer": f"{posts * 3} schedule-safe drafts",
            "requiredDailyProduction": f"{posts} schedule-safe drafts/day",
            "requiredValidatedDrafts": f"{production.get('requiredValidatedDraftsPerDay')} validated drafts/day",
            "requiredParentAssetsPerDay": int(production.get("requiredParentsPerDay") or 0),
            "requiredCaptionFamiliesPerDay": int(production.get("requiredCaptionFamiliesPerDay") or 0),
            "requiredVariantsPerDay": int(production.get("requiredVariantsPerDay") or 0),
            "requiredExceptionRate": "<=2.0% inventory-blocking exceptions",
            "requiredOperatorLoad": "<=25 inventory exceptions/day per operator queue",
            "wouldWrite": False,
        }

    def wilson_lower_bound(self, *, successes: int, trials: int, z: float = 1.96) -> float:
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

    def surface_from_pattern(self, item: dict[str, Any], lineage: dict[str, Any]) -> str:
        if item.get("dimension") == "contentSurface":
            return str(item.get("key") or "reel")
        surfaces = lineage.get("contentSurfaces") if isinstance(lineage.get("contentSurfaces"), list) else []
        if surfaces:
            return str(surfaces[0] or "reel")
        if item.get("dimension") in {"storyIntent", "storyStyle"}:
            return "story"
        return "reel"

    def first_lineage_value(self, lineage: dict[str, Any], key: str, *, fallback: str = "") -> str:
        values = lineage.get(key) if isinstance(lineage.get(key), list) else []
        return str(values[0]) if values else fallback

    def audit_report(self, audit_report_id: str) -> dict[str, Any]:
        from . import audit_payload as _audit_payload

        return _audit_payload.audit_report(self.factory_context, audit_report_id)

    def audit_report_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        from . import audit_payload as _audit_payload

        return _audit_payload._audit_report_payload(self.factory_context, row)

    def register_parent_reel(
        self,
        rendered_asset_id: str,
        *,
        operator: str | None = None,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.variant_lineage.register_parent_reel(
            rendered_asset_id,
            operator=operator,
            status=status,
            metadata=metadata,
        )

    def variant_plan(
        self,
        *,
        parent_asset_id: str,
        caption_version_id: str | None = None,
        count: int = 10,
        contentforge_preset: str = "caption_safe",
        cooldown_days: int = 14,
    ) -> dict[str, Any]:
        return self.variant_lineage.variant_plan(
            parent_asset_id=parent_asset_id,
            caption_version_id=caption_version_id,
            count=count,
            contentforge_preset=contentforge_preset,
            cooldown_days=cooldown_days,
        )

    def generate_variants(
        self,
        *,
        parent_asset_id: str,
        caption_version_id: str | None = None,
        count: int = 10,
        contentforge_preset: str = "caption_safe",
        contentforge_base_url: str | None = None,
        source_media_path: str | None = None,
        contentforge_timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        return self.variant_lineage.generate_variants(
            parent_asset_id=parent_asset_id,
            caption_version_id=caption_version_id,
            count=count,
            contentforge_preset=contentforge_preset,
            contentforge_base_url=contentforge_base_url,
            source_media_path=source_media_path,
            contentforge_timeout_seconds=contentforge_timeout_seconds,
        )

    def contentforge_variant_pack_blocked_result(
        self,
        *,
        plan: dict[str, Any],
        blocking_reason: str,
        endpoint: str,
        staged_source: str,
        timeout_seconds: int,
        error: BaseException,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.variant_lineage.contentforge_variant_pack_blocked_result(
            plan=plan,
            blocking_reason=blocking_reason,
            endpoint=endpoint,
            staged_source=staged_source,
            timeout_seconds=timeout_seconds,
            error=error,
            extra=extra,
        )

    def register_variant_asset(
        self,
        *,
        parent_asset_id: str,
        variant_asset_id: str,
        variant_family_id: str,
        variant_index: int,
        operations: list[dict[str, Any]],
        caption_family_id: str | None = None,
        caption_version_id: str | None = None,
        contentforge_run_id: str | None = None,
        contentforge_preset: str = "caption_safe",
        qc_status: str = "passed",
        cooldown_days: int = 14,
        commit: bool = True,
    ) -> dict[str, Any]:
        return self.variant_lineage.register_variant_asset(
            parent_asset_id=parent_asset_id,
            variant_asset_id=variant_asset_id,
            variant_family_id=variant_family_id,
            variant_index=variant_index,
            operations=operations,
            caption_family_id=caption_family_id,
            caption_version_id=caption_version_id,
            contentforge_run_id=contentforge_run_id,
            contentforge_preset=contentforge_preset,
            qc_status=qc_status,
            cooldown_days=cooldown_days,
            commit=commit,
        )

    def parent_variant_inventory(self, campaign_slug: str) -> dict[str, Any]:
        return self.variant_lineage.parent_variant_inventory(campaign_slug)

    def variant_metrics_rollup(self, campaign_slug: str) -> dict[str, Any]:
        return self.variant_lineage.variant_metrics_rollup(campaign_slug)

    def concept_for_parent_asset(self, parent_asset_id: str) -> dict[str, Any] | None:
        return self.variant_lineage.concept_for_parent_asset(parent_asset_id)

    def variant_lineage_for_asset(self, rendered_asset_id: str) -> dict[str, Any]:
        return self.variant_lineage.variant_lineage_for_asset(rendered_asset_id)

    def concept_payload(self, row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
        return self.variant_lineage.concept_payload(row)

    def variant_family_payload(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        return self.variant_lineage.variant_family_payload(row)

    def variant_lineage_asset_payload(self, row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
        return self.variant_lineage.variant_lineage_asset_payload(row)

    def variant_usage_payload(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        return self.variant_lineage.variant_usage_payload(row)

    def variant_rollup_group(self, snapshots: list[dict[str, Any]], key: str, output_key: str) -> list[dict[str, Any]]:
        return self.variant_lineage.variant_rollup_group(snapshots, key, output_key)

    def local_export_readiness(self, asset: dict[str, Any], latest_audit: dict[str, Any] | None) -> dict[str, Any]:
        return self.publishability.local_export_readiness(asset, latest_audit)

    def latest_audit_for_asset(self, rendered_asset_id: str) -> dict[str, Any] | None:
        return self.publishability.latest_audit_for_asset(rendered_asset_id)

    def active_quarantine_for_asset(self, rendered_asset_id: str) -> dict[str, Any] | None:
        return self.publishability.active_quarantine_for_asset(rendered_asset_id)

    def quarantine_asset(
        self,
        rendered_asset_id: str,
        *,
        reason: str,
        root_cause: str | None = None,
        blocking_reason: str | None = None,
        distribution_plan_id: str | None = None,
        threadsdash_post_id: str | None = None,
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        return self.publishability.quarantine_asset(
            rendered_asset_id,
            reason=reason,
            root_cause=root_cause,
            blocking_reason=blocking_reason,
            distribution_plan_id=distribution_plan_id,
            threadsdash_post_id=threadsdash_post_id,
            created_by=created_by,
            metadata=metadata,
            commit=commit,
        )

    def verification_id(self, prefix: str, *parts: Any) -> str:
        return self.publishability.verification_id(prefix, *parts)

    def text_hash(self, value: str) -> str:
        return self.publishability.text_hash(value)

    def instagram_post_caption_for_asset(
        self,
        asset: dict[str, Any],
        caption_context: dict[str, Any] | None,
        *,
        distribution_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.publishability.instagram_post_caption_for_asset(
            asset,
            caption_context,
            distribution_plan=distribution_plan,
        )

    def caption_lineage_sidecar(self, output_path: str) -> dict[str, Any]:
        return self.publishability.caption_lineage_sidecar(output_path)

    def explain_publishability(
        self,
        rendered_asset_id: str,
        *,
        distribution_plan_id: str | None = None,
    ) -> dict[str, Any]:
        return self.publishability.explain_publishability(
            rendered_asset_id,
            distribution_plan_id=distribution_plan_id,
        )

    def capture_publishability_rejection_evidence(self, rendered_asset_id: str) -> dict[str, Any]:
        return self.publishability.capture_publishability_rejection_evidence(rendered_asset_id)

    def capture_publishability_rejection_evidence_from_result(
        self,
        rendered_asset_id: str,
        result: dict[str, Any],
        *,
        commit: bool,
    ) -> dict[str, Any]:
        return self.publishability.capture_publishability_rejection_evidence_from_result(
            rendered_asset_id,
            result,
            commit=commit,
        )

    def capture_discoverability_gate_rejection_evidence(self, **kwargs: Any) -> dict[str, Any]:
        return self.publishability.capture_discoverability_gate_rejection_evidence(**kwargs)

    def record_proof_run(
        self,
        *,
        campaign_id: str | None,
        rendered_asset_id: str,
        distribution_plan_id: str | None = None,
        threadsdash_draft_id: str | None = None,
        threadsdash_post_id: str | None = None,
        status: str = "started",
        current_state: str = "creative_approved",
        blocking_reason: str | None = None,
        root_cause: str | None = None,
        metrics_eligible: bool = False,
        metadata: dict[str, Any] | None = None,
        proof_run_id: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        return self.publishability.record_proof_run(
            campaign_id=campaign_id,
            rendered_asset_id=rendered_asset_id,
            distribution_plan_id=distribution_plan_id,
            threadsdash_draft_id=threadsdash_draft_id,
            threadsdash_post_id=threadsdash_post_id,
            status=status,
            current_state=current_state,
            blocking_reason=blocking_reason,
            root_cause=root_cause,
            metrics_eligible=metrics_eligible,
            metadata=metadata,
            proof_run_id=proof_run_id,
            commit=commit,
        )

    def publishability_discoverability_fields(
        self,
        *,
        asset: dict[str, Any],
        caption_text: str,
        caption_context: dict[str, Any],
        post_caption: dict[str, Any],
    ) -> list[tuple[str, str]]:
        return self.publishability.publishability_discoverability_fields(
            asset=asset,
            caption_text=caption_text,
            caption_context=caption_context,
            post_caption=post_caption,
        )

    def instagram_post_caption_quality(self, post_caption: dict[str, Any]) -> dict[str, Any]:
        return self.publishability.instagram_post_caption_quality(post_caption)

    def caption_quality_repair_plan(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        return self.publishability.caption_quality_repair_plan(
            creator=creator,
            campaign_slug=campaign_slug,
            content_surface=content_surface,
            limit=limit,
        )

    def caption_quality_recovery_class(self, quality_reasons: list[str]) -> str:
        return self.publishability.caption_quality_recovery_class(quality_reasons)

    def suggest_simple_instagram_post_caption(self, *, asset_id: str, current_caption: str, burned_caption: str) -> str:
        return self.publishability.suggest_simple_instagram_post_caption(
            asset_id=asset_id,
            current_caption=current_caption,
            burned_caption=burned_caption,
        )

    def publishability_check(
        self,
        asset: dict[str, Any],
        latest_audit: dict[str, Any] | None = None,
        *,
        distribution_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.publishability.publishability_check(
            asset,
            latest_audit,
            distribution_plan=distribution_plan,
        )
