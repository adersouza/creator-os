from __future__ import annotations

from pathlib import Path

from .adapters.contentforge import audit_review_batch_manifest
from .adapters.threadsdash import (
    sync_threadsdash_instagram_accounts,
)
from .cli_support import (
    _threadsdash_supabase_args,
    load_json_object,
    print_json,
)


def dispatch_scale_commands(args, cf, settings) -> int | None:
    if args.cmd == "daily-plan":
        print_json(
            cf.domains.daily_plan.creator_os_daily_plan(
                creators=args.creator,
                threadsdash_report=load_json_object(args.threadsdash_report_json),
                schedule_plan=load_json_object(args.schedule_plan_json),
                time_plan=load_json_object(args.time_plan_json),
                winner_expansion_report=load_json_object(
                    args.winner_expansion_report_json
                ),
                winner_expansion_plan=load_json_object(args.winner_expansion_plan_json),
                variant_metrics_rollup=load_json_object(
                    args.variant_metrics_rollup_json
                ),
                date=args.date,
            )
        )
        return 0
    if args.cmd == "200-account-acceptance-suite":
        print_json(
            cf.domains.acceptance_suite.creator_os_200_account_acceptance_suite(
                accounts=args.accounts,
                creators=args.creators,
                daily_obligations=args.daily_obligations,
                draft_inventory=args.draft_inventory,
                warming_accounts=args.warming_accounts,
                restricted_accounts=args.restricted_accounts,
                manual_review_accounts=args.manual_review_accounts,
                mixed_surfaces=not args.single_surface,
            )
        )
        return 0
    if args.cmd == "review-batch-contentforge-audit":
        print_json(
            audit_review_batch_manifest(
                contentforge_root=cf.settings.contentforge_root,
                manifest_path=Path(args.manifest),
                source_path=Path(args.source),
                contentforge_base_url=args.contentforge_base_url
                or cf.settings.contentforge_base_url,
                report_path=Path(args.report_path) if args.report_path else None,
                layers=args.layers,
                animation_mode=args.animation_mode,
                allow_static_opening=args.allow_static_opening,
                per_file=args.per_file,
                update_manifest=not args.no_update_manifest,
            )
        )
        return 0
    if args.cmd == "inventory-slo-report":
        print_json(
            cf.domains.inventory_planning.inventory_slo_report(
                accounts=args.accounts,
                posts_per_account_per_day=args.posts_per_account_per_day,
                creators=args.creators,
                minimum_inventory_days=args.minimum_inventory_days,
                current_validated_drafts=args.current_validated_drafts,
            )
        )
        return 0
    if args.cmd == "inventory-buffer-report":
        print_json(
            cf.domains.inventory_planning.inventory_buffer_report(
                accounts=args.accounts,
                posts_per_account_per_day=args.posts_per_account_per_day,
                creators=args.creators,
                minimum_inventory_days=args.minimum_inventory_days,
                current_validated_drafts=args.current_validated_drafts,
            )
        )
        return 0
    if args.cmd == "inventory-factory-audit":
        print_json(
            cf.domains.inventory_planning.inventory_factory_audit(
                creator=args.creator,
                campaign_slug=args.campaign,
                accounts=args.accounts,
                posts_per_account_per_day=args.posts_per_account_per_day,
            )
        )
        return 0
    if args.cmd == "inventory-yield-analysis":
        print_json(
            cf.domains.inventory_planning.inventory_yield_analysis(
                creator=args.creator, campaign_slug=args.campaign
            )
        )
        return 0
    if args.cmd == "inventory-buffer-policy-plan":
        print_json(
            cf.domains.inventory_planning.inventory_buffer_policy_plan(
                creator=args.creator,
                surface=args.surface,
                daily_demand=args.daily_demand,
                buffer_target_days=args.buffer_target_days,
                available_inventory=args.available_inventory,
            )
        )
        return 0
    if args.cmd == "inventory-slo-enforcement-audit":
        print_json(
            cf.domains.inventory_planning.inventory_slo_enforcement_audit(
                creators=args.creator,
                accounts=args.accounts,
                posts_per_account_per_day=args.posts_per_account_per_day,
                minimum_inventory_days=args.minimum_inventory_days,
            )
        )
        return 0
    if args.cmd == "inventory-consumption-simulation":
        print_json(
            cf.domains.inventory_planning.inventory_consumption_simulation(
                available_inventory=args.available_inventory,
                posts_per_account_per_day=args.posts_per_account_per_day,
            )
        )
        return 0
    if args.cmd == "inventory-production-requirements":
        print_json(
            cf.domains.inventory_planning.inventory_production_requirements(
                accounts=args.accounts,
                posts_per_account_per_day=args.posts_per_account_per_day,
            )
        )
        return 0
    if args.cmd == "inventory-exception-audit":
        print_json(
            cf.domains.inventory_planning.inventory_exception_audit(
                execution_readiness=load_json_object(args.execution_readiness_json)
            )
        )
        return 0
    if args.cmd == "inventory-factory-readiness-report":
        print_json(
            cf.domains.inventory_planning.inventory_factory_readiness_report(
                accounts=args.accounts,
                posts_per_account_per_day=args.posts_per_account_per_day,
                available_inventory=args.available_inventory,
                execution_readiness=load_json_object(args.execution_readiness_json),
            )
        )
        return 0
    if args.cmd == "inventory-factory-master-report":
        print_json(
            cf.domains.inventory_planning.inventory_factory_master_report(
                accounts=args.accounts,
                posts_per_account_per_day=args.posts_per_account_per_day,
                available_inventory=args.available_inventory,
                execution_readiness=load_json_object(args.execution_readiness_json),
            )
        )
        return 0
    if args.cmd == "inventory-autopilot-plan":
        print_json(
            cf.domains.inventory_planning.inventory_autopilot_plan(
                accounts=args.accounts,
                posts_per_account_per_day=args.posts_per_account_per_day,
                available_inventory=args.available_inventory,
                buffer_target_days=args.buffer_target_days,
                surface=args.surface,
            )
        )
        return 0
    if args.cmd == "inventory-shortage-repair-plan":
        print_json(
            cf.domains.inventory_planning.inventory_shortage_repair_plan(
                accounts=args.accounts,
                posts_per_account_per_day=args.posts_per_account_per_day,
                available_inventory=args.available_inventory,
                buffer_target_days=args.buffer_target_days,
                surface=args.surface,
            )
        )
        return 0
    if args.cmd == "inventory-buffer-protection-report":
        print_json(
            cf.domains.inventory_planning.inventory_buffer_protection_report(
                accounts=args.accounts,
                posts_per_account_per_day=args.posts_per_account_per_day,
                available_inventory=args.available_inventory,
                buffer_target_days=args.buffer_target_days,
                surface=args.surface,
            )
        )
        return 0
    if args.cmd == "road-to-200-accounts":
        print_json(cf.domains.inventory_planning.road_to_200_accounts())
        return 0
    if args.cmd == "reel-factory-parent-throughput-proof":
        print_json(
            cf.domains.reel_factory_reports.reel_factory_parent_throughput_proof(
                required_parents_per_day=args.required_parents_per_day,
                lookback_days=args.lookback_days,
            )
        )
        return 0
    if args.cmd == "reel-factory-yield-analysis":
        print_json(cf.domains.reel_factory_reports.reel_factory_yield_analysis())
        return 0
    if args.cmd == "reel-factory-failure-analysis":
        print_json(cf.domains.reel_factory_reports.reel_factory_failure_analysis())
        return 0
    if args.cmd == "reel-factory-capacity-model":
        print_json(
            cf.domains.reel_factory_reports.reel_factory_capacity_model(
                required_parents_per_day=args.required_parents_per_day
            )
        )
        return 0
    if args.cmd == "reel-factory-200-account-readiness":
        print_json(cf.domains.reel_factory_reports.reel_factory_200_account_readiness())
        return 0
    if args.cmd == "reel-factory-master-report":
        print_json(cf.domains.reel_factory_reports.reel_factory_master_report())
        return 0
    if args.cmd == "parent-factory-yield-waterfall":
        print_json(
            cf.domains.parent_factory_reports.parent_factory_yield_waterfall(
                required_parents_per_day=args.required_parents_per_day
            )
        )
        return 0
    if args.cmd == "parent-factory-loss-analysis":
        print_json(
            cf.domains.parent_factory_reports.parent_factory_loss_analysis(
                required_parents_per_day=args.required_parents_per_day
            )
        )
        return 0
    if args.cmd == "parent-factory-rejection-report":
        print_json(cf.domains.parent_factory_reports.parent_factory_rejection_report())
        return 0
    if args.cmd == "parent-factory-discoverability-loss-analysis":
        print_json(
            cf.domains.discoverability.parent_factory_discoverability_loss_analysis()
        )
        return 0
    if args.cmd == "discoverability-intake-gate":
        print_json(
            cf.domains.discoverability.discoverability_intake_gate(
                load_json_object(args.payload_json) or {}
            )
        )
        return 0
    if args.cmd == "discoverability-generation-gate":
        print_json(
            cf.domains.discoverability.discoverability_generation_gate(
                load_json_object(args.payload_json) or {}
            )
        )
        return 0
    if args.cmd == "discoverability-pre-render-gate":
        print_json(
            cf.domains.discoverability.discoverability_pre_render_gate(
                load_json_object(args.payload_json) or {}
            )
        )
        return 0
    if args.cmd == "discoverability-violation-origin-map":
        print_json(cf.domains.discoverability.discoverability_violation_origin_map())
        return 0
    if args.cmd == "parent-factory-recoverable-yield":
        print_json(cf.domains.parent_factory_reports.parent_factory_recoverable_yield())
        return 0
    if args.cmd == "parent-factory-throughput-recovery-plan":
        print_json(
            cf.domains.parent_factory_reports.parent_factory_throughput_recovery_plan()
        )
        return 0
    if args.cmd == "parent-factory-53-parent-feasibility":
        print_json(
            cf.domains.parent_factory_reports.parent_factory_53_parent_feasibility()
        )
        return 0
    if args.cmd == "parent-factory-secondary-loss-analysis":
        print_json(
            cf.domains.parent_factory_reports.parent_factory_secondary_loss_analysis()
        )
        return 0
    if args.cmd == "parent-factory-waterfall-after-discoverability":
        print_json(
            cf.domains.discoverability.parent_factory_waterfall_after_discoverability()
        )
        return 0
    if args.cmd == "parent-factory-true-yield-model":
        print_json(cf.domains.parent_factory_reports.parent_factory_true_yield_model())
        return 0
    if args.cmd == "parent-factory-realistic-53-parent-plan":
        print_json(
            cf.domains.parent_factory_reports.parent_factory_realistic_53_parent_plan()
        )
        return 0
    if args.cmd == "capture-publishability-rejection-evidence":
        print_json(
            cf.domains.publishability.capture_publishability_rejection_evidence(
                args.asset_id
            )
        )
        return 0
    if args.cmd == "parent-factory-quality-gate-analysis":
        print_json(
            cf.domains.parent_factory_reports.parent_factory_quality_gate_analysis()
        )
        return 0
    if args.cmd == "parent-factory-optimization-plan":
        print_json(
            cf.domains.parent_factory_reports.parent_factory_optimization_plan(
                required_parents_per_day=args.required_parents_per_day
            )
        )
        return 0
    if args.cmd == "parent-factory-master-optimization-report":
        print_json(
            cf.domains.parent_factory_reports.parent_factory_master_optimization_report(
                required_parents_per_day=args.required_parents_per_day
            )
        )
        return 0
    if args.cmd == "parent-factory-autopilot-plan":
        print_json(
            cf.domains.parent_factory_planning.parent_factory_autopilot_plan(
                accounts=args.accounts,
                posts_per_account_per_day=args.posts_per_account_per_day,
            )
        )
        return 0
    if args.cmd == "parent-factory-shortfall-report":
        print_json(
            cf.domains.parent_factory_planning.parent_factory_shortfall_report(
                accounts=args.accounts,
                posts_per_account_per_day=args.posts_per_account_per_day,
            )
        )
        return 0
    if args.cmd == "parent-factory-production-targets":
        print_json(
            cf.domains.parent_factory_planning.parent_factory_production_targets(
                accounts=args.accounts,
                posts_per_account_per_day=args.posts_per_account_per_day,
            )
        )
        return 0
    if args.cmd == "exception-queue-report":
        print_json(
            cf.domains.exceptions.exception_queue_report(
                daily_plan=load_json_object(args.daily_plan_json),
                execution_readiness=load_json_object(args.execution_readiness_json),
            )
        )
        return 0
    if args.cmd == "exception-queue-summary":
        print_json(
            cf.domains.exceptions.exception_queue_summary(
                daily_plan=load_json_object(args.daily_plan_json),
                execution_readiness=load_json_object(args.execution_readiness_json),
            )
        )
        return 0
    if args.cmd == "exception-queue-priority-report":
        print_json(
            cf.domains.exceptions.exception_queue_priority_report(
                daily_plan=load_json_object(args.daily_plan_json),
                execution_readiness=load_json_object(args.execution_readiness_json),
            )
        )
        return 0
    if args.cmd == "exception-queue-owner-report":
        print_json(
            cf.domains.exceptions.exception_queue_owner_report(
                daily_plan=load_json_object(args.daily_plan_json),
                execution_readiness=load_json_object(args.execution_readiness_json),
            )
        )
        return 0
    if args.cmd == "failure-injection-suite":
        print_json(cf.domains.operational_proofs.failure_injection_suite())
        return 0
    if args.cmd == "idempotency-proof":
        print_json(cf.domains.operational_proofs.idempotency_proof())
        return 0
    if args.cmd == "surface-maturity-audit":
        print_json(cf.domains.operational_proofs.surface_maturity_audit())
        return 0
    if args.cmd == "surface-readiness-scorecard":
        print_json(cf.domains.readiness_report.surface_readiness_scorecard())
        return 0
    if args.cmd == "operator-load-audit":
        print_json(cf.domains.operational_proofs.operator_load_audit())
        return 0
    if args.cmd == "single-source-of-truth-audit":
        print_json(cf.domains.core_complexity.single_source_of_truth_audit())
        return 0
    if args.cmd == "core-complexity-reduction-plan":
        print_json(cf.domains.core_complexity.core_complexity_reduction_plan())
        return 0
    if args.cmd == "creator-os-100-account-proof":
        print_json(cf.domains.readiness_report.creator_os_100_account_proof())
        return 0
    if args.cmd == "creator-os-volume-acceptance-suite":
        print_json(cf.domains.readiness_report.creator_os_volume_acceptance_suite())
        return 0
    if args.cmd == "creator-os-9.5-readiness-report":
        print_json(cf.domains.readiness_report.creator_os_9_5_readiness_report())
        return 0
    if args.cmd == "creator-os-10.0-readiness-report":
        print_json(cf.domains.readiness_report.creator_os_10_0_readiness_report())
        return 0
    if args.cmd == "creator-os-live-100-account-readiness":
        print_json(cf.domains.live_scale.creator_os_live_100_account_readiness())
        return 0
    if args.cmd == "creator-os-live-account-acceptance":
        print_json(
            cf.domains.live_acceptance.creator_os_live_account_acceptance(
                account_target=args.account_target, content_surface=args.content_surface
            )
        )
        return 0
    if args.cmd == "creator-os-staged-live-acceptance":
        print_json(
            cf.domains.live_acceptance.creator_os_staged_live_acceptance(
                content_surface=args.content_surface
            )
        )
        return 0
    if args.cmd == "sync-threadsdash-instagram-accounts":
        supabase_url, service_key = _threadsdash_supabase_args(args)
        print_json(
            sync_threadsdash_instagram_accounts(
                cf,
                creator=args.creator,
                match=args.match,
                user_id=args.user_id,
                limit=args.limit,
                supabase_url=supabase_url,
                supabase_service_role_key=service_key,
            )
        )
        return 0
    if args.cmd == "creator-os-live-scale-runbook":
        print_json(cf.domains.live_scale.creator_os_live_scale_runbook())
        return 0
    if args.cmd == "creator-os-live-scale-scorecard":
        print_json(cf.domains.live_scale.creator_os_live_scale_scorecard())
        return 0
    if args.cmd == "parent-factory-production-trial":
        print_json(cf.domains.parent_factory_trials.parent_factory_production_trial())
        return 0
    if args.cmd == "parent-factory-production-scorecard":
        print_json(
            cf.domains.parent_factory_trials.parent_factory_production_scorecard()
        )
        return 0
    if args.cmd == "parent-factory-real-yield-report":
        print_json(cf.domains.parent_factory_trials.parent_factory_real_yield_report())
        return 0
    if args.cmd == "parent-factory-53-parent-trial":
        print_json(cf.domains.parent_factory_trials.parent_factory_53_parent_trial())
        return 0
    if args.cmd == "parent-factory-trial-results":
        print_json(cf.domains.parent_factory_trials.parent_factory_trial_results())
        return 0
    if args.cmd == "parent-factory-trial-analysis":
        print_json(cf.domains.parent_factory_trials.parent_factory_trial_analysis())
        return 0
    if args.cmd == "parent-factory-post-gate-fresh-batch-proof":
        print_json(
            cf.domains.parent_factory_trials.parent_factory_post_gate_fresh_batch_proof()
        )
        return 0
    if args.cmd == "discoverability-prevention-audit":
        print_json(cf.domains.discoverability.discoverability_prevention_audit())
        return 0
    if args.cmd == "discoverability-prevention-scorecard":
        print_json(cf.domains.discoverability.discoverability_prevention_scorecard())
        return 0
    if args.cmd == "story-certification-proof":
        print_json(
            cf.domains.story_management.story_certification_proof(
                rendered_asset_id=args.rendered_asset_id
            )
        )
        return 0
    if args.cmd == "story-production-readiness":
        print_json(cf.domains.story_management.story_production_readiness())
        return 0
    if args.cmd == "story-proof-gap-analysis":
        print_json(cf.domains.story_management.story_proof_gap_analysis())
        return 0
    if args.cmd == "carousel-certification-proof":
        print_json(
            cf.domains.carousel_integrity.carousel_certification_proof(
                rendered_asset_id=args.rendered_asset_id
            )
        )
        return 0
    if args.cmd == "carousel-production-readiness":
        print_json(cf.domains.carousel_integrity.carousel_production_readiness())
        return 0
    if args.cmd == "carousel-proof-gap-analysis":
        print_json(cf.domains.carousel_integrity.carousel_proof_gap_analysis())
        return 0
    if args.cmd == "creator-os-certification-report":
        print_json(cf.domains.certification.creator_os_certification_report())
        return 0
    if args.cmd == "draft-inventory-gap":
        print_json(
            cf.domains.draft_inventory_gap.creator_os_draft_inventory_gap(
                creator=args.creator,
                threadsdash_report=load_json_object(args.threadsdash_report_json),
                schedule_plan=load_json_object(args.schedule_plan_json),
                time_plan=load_json_object(args.time_plan_json),
            )
        )
        return 0
    if args.cmd == "execution-readiness":
        print_json(
            cf.domains.execution_readiness.creator_os_execution_readiness(
                creator=args.creator,
                requested_count=args.requested_count,
                threadsdash_report=load_json_object(args.threadsdash_report_json),
                schedule_plan=load_json_object(args.schedule_plan_json),
                time_plan=load_json_object(args.time_plan_json),
            )
        )
        return 0
    if args.cmd == "account-tiers":
        print_json(
            cf.domains.account_health.creator_os_account_tiers(
                creator=args.creator,
                threadsdash_report=load_json_object(args.threadsdash_report_json),
            )
        )
        return 0
    if args.cmd == "account-health-report":
        print_json(
            cf.domains.account_health.creator_os_account_health_report(
                creator=args.creator,
                threadsdash_report=load_json_object(args.threadsdash_report_json),
            )
        )
        return 0
    if args.cmd == "restricted-account-report":
        print_json(
            cf.domains.account_health.creator_os_restricted_account_report(
                creator=args.creator,
                threadsdash_report=load_json_object(args.threadsdash_report_json),
            )
        )
        return 0
    if args.cmd == "manual-review-queue":
        print_json(
            cf.domains.account_health.creator_os_manual_review_queue(
                creator=args.creator,
                threadsdash_report=load_json_object(args.threadsdash_report_json),
            )
        )
        return 0
    if args.cmd == "account-warmup-report":
        print_json(
            cf.domains.account_health.creator_os_account_warmup_report(
                creator=args.creator,
                threadsdash_report=load_json_object(args.threadsdash_report_json),
            )
        )
        return 0
    if args.cmd == "lifecycle-dashboard":
        posts_payload = load_json_object(args.threadsdash_posts_json)
        posts = None
        if isinstance(posts_payload, dict):
            raw_posts = (
                posts_payload.get("posts")
                or posts_payload.get("rows")
                or posts_payload.get("items")
            )
            if isinstance(raw_posts, list):
                posts = [item for item in raw_posts if isinstance(item, dict)]
        print_json(
            cf.domains.lifecycle_reporting.creator_os_lifecycle_dashboard(
                campaign=args.campaign,
                user_id=args.user_id,
                threadsdash_posts=posts,
                include_threadsdash=args.include_threadsdash,
            )
        )
        return 0
    if args.cmd == "creator-surface-summary":
        print_json(
            cf.domains.surface_summary.creator_surface_summary(
                creator=args.creator, date=args.date
            )
        )
        return 0
    if args.cmd == "account-surface-summary":
        print_json(
            cf.domains.surface_summary.account_surface_summary(
                creator=args.creator, date=args.date, account_id=args.account_id
            )
        )
        return 0
    if args.cmd == "creator-surface-gap-report":
        print_json(
            cf.domains.surface_summary.creator_surface_gap_report(
                creator=args.creator, date=args.date
            )
        )
        return 0
    return None
