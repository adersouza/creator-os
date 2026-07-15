from __future__ import annotations

import json
from pathlib import Path

from .adapters.contentforge import audit_campaign
from .adapters.threadsdash_account_projection import summarize_threadsdash_usage
from .adapters.threadsdash_client import SupabaseRestClient
from .adapters.threadsdash_draft_delivery import export_threadsdash
from .adapters.threadsdash_draft_readiness import evaluate_export_readiness
from .assignment_eligibility import (
    evaluate_assignment_eligibility,
    write_assignment_eligibility_artifact,
)
from .cli_support import (
    load_hooks,
    load_json_object,
    print_json,
)
from .closed_loop_proof import (
    build_account_routing_audit,
    run_stacey_closed_loop_proof,
)
from .learning_readiness import closed_loop_learning_status
from .quality_calibration import track_q_calibration_status


def dispatch_operations_commands(args, cf, settings) -> int | None:
    if args.cmd == "caption-outcome-report":
        print_json(
            cf.domains.performance_summary_repo.caption_outcome_report(args.campaign)
        )
        return 0
    if args.cmd == "reference-outcome-report":
        print_json(
            cf.domains.performance_summary_repo.reference_outcome_report(args.campaign)
        )
        return 0
    if args.cmd == "track-q-calibration-status":
        print_json(
            track_q_calibration_status(
                cf.conn,
                campaign_slug=args.campaign,
                min_reviewed_reels=args.min_reviewed_reels,
                min_low_score_or_rejected_samples=args.min_low_score_or_rejected_samples,
                low_score_threshold=args.low_score_threshold,
            )
        )
        return 0
    if args.cmd == "lifecycle-report":
        print_json(
            cf.domains.lifecycle_reporting.lifecycle_report(
                args.campaign,
                user_id=args.user_id,
                include_threadsdash=args.include_threadsdash,
                state=args.state,
                blocking_reason=args.blocking_reason,
                rendered_asset_id=args.rendered_asset_id,
            )
        )
        return 0
    if args.cmd == "explain-publishability":
        print_json(
            cf.domains.publishability.explain_publishability(
                args.rendered_asset_id, distribution_plan_id=args.distribution_plan_id
            )
        )
        return 0
    if args.cmd == "register-parent-reel":
        metadata = json.loads(args.metadata_json) if args.metadata_json else None
        print_json(
            cf.domains.variant_lineage.register_parent_reel(
                args.rendered_asset_id,
                operator=args.operator,
                status=args.status,
                metadata=metadata,
            )
        )
        return 0
    if args.cmd == "parent-variant-inventory":
        print_json(cf.domains.variant_lineage.parent_variant_inventory(args.campaign))
        return 0
    if args.cmd == "variant-plan":
        print_json(
            cf.domains.variant_lineage.variant_plan(
                parent_asset_id=args.parent_asset_id,
                count=args.count,
                contentforge_preset=args.contentforge_preset,
                cooldown_days=args.cooldown_days,
            )
        )
        return 0
    if args.cmd == "generate-variants":
        if args.dry_run or not args.contentforge_base_url:
            plan = cf.domains.variant_lineage.variant_plan(
                parent_asset_id=args.parent_asset_id,
                caption_version_id=args.caption_version_id,
                count=args.count,
                contentforge_preset=args.contentforge_preset,
            )
            plan["schema"] = "campaign_factory.generate_variants.preview.v1"
            plan["status"] = "dry_run" if args.dry_run else "blocked"
            plan["blockingReason"] = (
                None if args.dry_run else "contentforge_cli_required"
            )
            print_json(plan)
        else:
            print_json(
                cf.domains.variant_lineage.generate_variants(
                    parent_asset_id=args.parent_asset_id,
                    caption_version_id=args.caption_version_id,
                    count=args.count,
                    contentforge_preset=args.contentforge_preset,
                    contentforge_base_url=args.contentforge_base_url,
                    source_media_path=args.source_media_path,
                )
            )
        return 0
    if args.cmd == "winner-expansion-plan":
        payload = {}
        if args.input_json:
            input_value = args.input_json.strip()
            if input_value.startswith("{"):
                payload = json.loads(input_value)
            else:
                payload = json.loads(Path(input_value).read_text(encoding="utf-8"))
        parent_asset_id = (
            args.parent_asset_id
            or payload.get("parentAssetId")
            or payload.get("parent_asset_id")
        )
        if not parent_asset_id:
            raise ValueError("parentAssetId is required")
        print_json(
            cf.domains.winner_expansion.winner_expansion_plan(
                creator=args.creator or payload.get("creator"),
                parent_asset_id=parent_asset_id,
                target_variants=args.target_variants
                or payload.get("targetVariants")
                or payload.get("target_variants")
                or 10,
                preset=args.preset or payload.get("preset") or "caption_safe_v2",
            )
        )
        return 0
    if args.cmd in {"caption-family-plan", "caption-family-create"}:
        payload = {}
        if args.input_json:
            input_value = args.input_json.strip()
            if input_value.startswith("{"):
                payload = json.loads(input_value)
            else:
                payload = json.loads(Path(input_value).read_text(encoding="utf-8"))
        parent_asset_id = (
            args.parent_asset_id
            or payload.get("parentAssetId")
            or payload.get("parent_asset_id")
        )
        if not parent_asset_id:
            raise ValueError("parentAssetId is required")
        common = {
            "creator": args.creator or payload.get("creator"),
            "parent_asset_id": parent_asset_id,
            "requested_caption_versions": args.requested_caption_versions
            if args.requested_caption_versions is not None
            else payload.get("requestedCaptionVersions")
            or payload.get("requested_caption_versions")
            or 5,
            "style": args.style or payload.get("style") or "ig_short",
        }
        if args.cmd == "caption-family-plan":
            print_json(
                cf.domains.caption_family.caption_family_plan(
                    **common,
                    dry_run=bool(args.dry_run or payload.get("dryRun") is not False),
                )
            )
        else:
            print_json(
                cf.domains.caption_family.caption_family_create(
                    **common,
                    dry_run=bool(args.dry_run or payload.get("dryRun") is True),
                )
            )
        return 0
    if args.cmd == "variant-inventory-plan":
        payload = {}
        if args.input_json:
            input_value = args.input_json.strip()
            if input_value.startswith("{"):
                payload = json.loads(input_value)
            else:
                payload = json.loads(Path(input_value).read_text(encoding="utf-8"))
        creator = args.creator or payload.get("creator")
        campaign = args.campaign or payload.get("campaign")
        if not creator:
            raise ValueError("creator is required")
        if not campaign:
            raise ValueError("campaign is required")
        print_json(
            cf.domains.winner_expansion.variant_inventory_plan(
                creator=creator,
                campaign=campaign,
                target_draft_shortfall=args.target_draft_shortfall
                if args.target_draft_shortfall is not None
                else payload.get("targetDraftShortfall")
                or payload.get("target_draft_shortfall")
                or 0,
                preset=args.preset or payload.get("preset") or "caption_safe_v2",
                max_variants_per_parent=args.max_variants_per_parent
                if args.max_variants_per_parent is not None
                else payload.get("maxVariantsPerParent")
                or payload.get("max_variants_per_parent")
                or 10,
                minimum_recommended_per_parent=args.minimum_recommended_per_parent
                if args.minimum_recommended_per_parent is not None
                else payload.get("minimumRecommendedPerParent")
                or payload.get("minimum_recommended_per_parent")
                or 3,
                dry_run=bool(args.dry_run or payload.get("dryRun") is not False),
            )
        )
        return 0
    if args.cmd == "winner-expansion-report":
        print_json(
            cf.domains.winner_expansion.winner_expansion_report(
                args.campaign,
                min_views=args.min_views,
                min_reach=args.min_reach,
                min_followers=args.min_followers,
            )
        )
        return 0
    if args.cmd == "concept-registry":
        print_json(
            cf.domains.creative_knowledge.concept_registry(
                creator=args.creator,
                campaign_slug=args.campaign,
                min_views=args.min_views,
                min_reach=args.min_reach,
                min_followers=args.min_followers,
            )
        )
        return 0
    if args.cmd == "winner-registry":
        print_json(
            cf.domains.creative_knowledge.winner_registry(
                creator=args.creator,
                campaign_slug=args.campaign,
                min_views=args.min_views,
                min_reach=args.min_reach,
                min_followers=args.min_followers,
            )
        )
        return 0
    if args.cmd == "winner-patterns":
        print_json(
            cf.domains.creative_knowledge.winner_patterns(
                creator=args.creator,
                campaign_slug=args.campaign,
                min_views=args.min_views,
                min_reach=args.min_reach,
                min_followers=args.min_followers,
            )
        )
        return 0
    if args.cmd == "winner-knowledge-base":
        print_json(
            cf.domains.creative_knowledge.winner_knowledge_base(
                creator=args.creator,
                campaign_slug=args.campaign,
                min_views=args.min_views,
                min_reach=args.min_reach,
                min_followers=args.min_followers,
            )
        )
        return 0
    if args.cmd == "creative-knowledge-base":
        print_json(
            cf.domains.creative_knowledge.creative_knowledge_base(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "creative-pattern-report":
        print_json(
            cf.domains.creative_knowledge.creative_pattern_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "creative-surface-report":
        print_json(
            cf.domains.creative_knowledge.creative_surface_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "creative-account-tier-report":
        print_json(
            cf.domains.creative_knowledge.creative_account_tier_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "creative-caption-report":
        print_json(
            cf.domains.creative_knowledge.creative_caption_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "creative-audio-report":
        print_json(
            cf.domains.creative_knowledge.creative_audio_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "creative-window-report":
        print_json(
            cf.domains.creative_knowledge.creative_window_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "creative-performance-analysis":
        print_json(
            cf.domains.creative_knowledge.creative_performance_analysis(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "creator-learning-summary":
        print_json(
            cf.domains.creative_knowledge.creator_learning_summary(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "next-content-recommendations":
        print_json(
            cf.domains.creative_knowledge.next_content_recommendations(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "creative-learning-confidence-model":
        print_json(
            cf.domains.creative_knowledge.creative_learning_confidence_model(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
            )
        )
        return 0
    if args.cmd == "creative-fatigue-report":
        print_json(
            cf.domains.creative_knowledge.creative_fatigue_report(
                creator=args.creator, campaign_slug=args.campaign, limit=args.limit
            )
        )
        return 0
    if args.cmd == "creative-surface-comparison-report":
        print_json(
            cf.domains.creative_knowledge.creative_surface_comparison_report(
                creator=args.creator, campaign_slug=args.campaign, limit=args.limit
            )
        )
        return 0
    if args.cmd == "recommendation-quality-audit":
        print_json(
            cf.domains.creative_knowledge.recommendation_quality_audit(
                creator=args.creator,
                campaign_slug=args.campaign,
                minimum_sample_size=args.minimum_sample_size,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "caption-quality-repair-plan":
        print_json(
            cf.domains.publishability.caption_quality_repair_plan(
                creator=args.creator,
                campaign_slug=args.campaign,
                content_surface=args.content_surface,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "recommended-inventory-request-plan":
        print_json(
            cf.domains.recommended_inventory_request.recommended_inventory_request_plan(
                creator=args.creator,
                target_count=args.target_count,
                daily_plan=load_json_object(args.daily_plan_json),
                variant_inventory_plan=load_json_object(
                    args.variant_inventory_plan_json
                ),
            )
        )
        return 0
    if args.cmd == "variant-metrics-rollup":
        print_json(cf.domains.variant_lineage.variant_metrics_rollup(args.campaign))
        return 0
    if args.cmd == "account-routing-audit":
        if not args.supabase_url or not args.supabase_service_role_key:
            print_json(
                {
                    "schema": "campaign_factory.account_routing_audit.v1",
                    "mode": "preview",
                    "mutatesSupabase": False,
                    "creator": args.creator,
                    "userId": args.user_id,
                    "status": "blocked",
                    "blockingReasons": ["missing_supabase_credentials"],
                    "hasSupabaseUrl": bool(args.supabase_url),
                    "hasSupabaseServiceRoleKey": bool(args.supabase_service_role_key),
                    "recommendations": [
                        "load ThreadsDashboard Supabase credentials before running the routing audit"
                    ],
                }
            )
            return 1
        client = SupabaseRestClient(
            args.supabase_url.rstrip("/"), args.supabase_service_role_key
        )
        print_json(
            build_account_routing_audit(
                client, user_id=args.user_id, creator=args.creator
            )
        )
        return 0
    if args.cmd == "closed-loop-proof":
        result = run_stacey_closed_loop_proof(
            campaign_slug=args.campaign,
            user_id=args.user_id,
            output_dir=args.output_dir,
            supabase_url=args.supabase_url,
            supabase_service_role_key=args.supabase_service_role_key,
            supabase_storage_bucket=args.supabase_storage_bucket,
            operator=args.operator,
            approval_reason=args.approval_reason,
            approved_rendered_asset_id=args.approved_rendered_asset_id,
            prompt_path=args.prompt_path,
            schedule_mode=args.schedule_mode,
            allow_warnings=args.allow_warnings,
            allow_live_export=args.allow_live_export,
            read_only_verification=args.read_only_verification,
            existing_threadsdash_post_id=args.existing_threadsdash_post_id,
            limit=args.limit,
        )
        print_json(result)
        if result.get("result") == "failed":
            return 1
        return 0
    if args.cmd == "closed-loop-learning-status":
        print_json(
            closed_loop_learning_status(
                cf.conn,
                campaign_slug=args.campaign,
                min_posts_with_1h_and_24h=args.min_posts_with_1h_and_24h,
            )
        )
        return 0
    if args.cmd == "campaign-health":
        print_json(cf.domains.campaign_overview.campaign_health(args.campaign))
        return 0
    if args.cmd == "asset-detail":
        print_json(cf.domains.campaign_overview.asset_detail(args.rendered_asset_id))
        return 0
    if args.cmd == "campaign-readiness":
        print_json(
            cf.domains.lifecycle_reporting.campaign_readiness(
                args.campaign, user_id=args.user_id
            )
        )
        return 0
    if args.cmd == "assign-account":
        print_json(
            cf.domains.campaign_overview.assign_asset_account(
                args.rendered_asset_id,
                account_id=args.account_id,
                instagram_account_id=args.instagram_account_id,
                planned_window_start=args.planned_window_start,
                planned_window_end=args.planned_window_end,
                notes=args.notes,
            )
        )
        return 0
    if args.cmd == "model-account-profile":
        print_json(
            cf.domains.models.upsert_model_account_profile(
                args.model,
                label=args.label,
                allowed_instagram_account_ids=args.instagram_account_id,
                allowed_account_group_names=args.account_group_name,
                allowed_handle_patterns=args.handle_pattern,
                default_smart_link=args.smart_link,
                story_cta_text=args.story_cta,
            )
        )
        return 0
    if args.cmd == "distribution-plan":
        print_json(
            cf.domains.distribution.create_distribution_plan(
                args.rendered_asset_id,
                surface=args.surface,
                account_id=args.account_id,
                instagram_account_id=args.instagram_account_id,
                planned_window_start=args.planned_window_start,
                planned_window_end=args.planned_window_end,
                paired_rendered_asset_id=args.paired_rendered_asset_id,
                reason_code=args.reason_code,
                smart_link=args.smart_link,
                cta_text=args.cta_text,
                instagram_trial_reels=args.instagram_trial_reels,
                trial_graduation_strategy=args.trial_graduation_strategy,
                trial_group_id=args.trial_group_id,
                trial_capability_authorization=args.trial_capability_authorization,
            )
        )
        return 0
    if args.cmd == "assignment-eligibility":
        decision = evaluate_assignment_eligibility(
            cf.conn,
            rendered_asset_id=args.rendered_asset_id,
            account_id=args.account_id,
            instagram_account_id=args.instagram_account_id,
            planned_at=args.planned_at,
            surface=args.surface,
            reuse_window_days=args.reuse_window_days,
        )
        if args.output:
            decision["artifactPath"] = str(
                write_assignment_eligibility_artifact(decision, Path(args.output))
            )
        print_json(decision)
        return 0
    if args.cmd == "plan-distribution":
        print_json(
            cf.domains.distribution.plan_distribution(
                args.campaign,
                user_id=args.user_id,
                mode=args.mode,
                strategy=args.strategy,
                replace=not args.no_replace,
            )
        )
        return 0
    if args.cmd == "account-plan":
        usage_result = None
        if args.supabase_url and args.supabase_service_role_key:
            usage_result = summarize_threadsdash_usage(
                cf,
                campaign_slug=args.campaign,
                user_id=args.user_id,
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
            )
        print_json(
            cf.domains.account_planning.account_plan(
                args.campaign, user_id=args.user_id, usage=usage_result
            )
        )
        return 0
    if args.cmd == "ranking":
        print_json(cf.domains.account_planning.ranking(args.campaign))
        return 0
    if args.cmd == "autonomy-policy":
        if args.set_level:
            print_json(cf.domains.autonomy.set_autonomy_level(args.set_level))
        else:
            print_json(cf.domains.autonomy.autonomy_policy())
        return 0
    if args.cmd == "trust-summary":
        print_json(cf.domains.exceptions.trust_summary(args.campaign))
        return 0
    if args.cmd == "recommendation-accuracy":
        print_json(
            cf.domains.recommendation_accuracy_repo.recommendation_accuracy(
                args.campaign, account=args.account, window_days=args.window_days
            )
        )
        return 0
    if args.cmd == "rebuild-recommendation-accuracy":
        print_json(
            cf.domains.recommendation_accuracy_repo.rebuild_recommendation_accuracy(
                args.campaign, account=args.account, window_days=args.window_days
            )
        )
        return 0
    if args.cmd == "recommend-next-batch":
        print_json(
            cf.domains.recommendations.recommend_next_batch(
                args.campaign,
                count=args.count,
                account=args.account,
                persist=args.persist,
            )
        )
        return 0
    if args.cmd == "accept-recommendation":
        print_json(
            cf.domains.recommendations.accept_recommendation_item(
                args.id,
                operator=args.operator,
                notes=args.notes,
                admin_override=args.admin_override,
                override_reason=args.override_reason,
            )
        )
        return 0
    if args.cmd == "reject-recommendation":
        print_json(
            cf.domains.recommendations.reject_recommendation_item(
                args.id,
                reason=args.reason,
                operator=args.operator,
                notes=args.notes,
                admin_override=args.admin_override,
                override_reason=args.override_reason,
            )
        )
        return 0
    if args.cmd == "link-recommendation":
        evidence = json.loads(args.evidence_json) if args.evidence_json else None
        print_json(
            cf.domains.recommendations.link_recommendation_item(
                args.id,
                source_asset_id=args.source_asset_id,
                render_job_id=args.render_job_id,
                rendered_asset_id=args.rendered_asset_id,
                post_id=args.post_id,
                performance_snapshot_id=args.performance_snapshot_id,
                evidence=evidence,
                admin_override=args.admin_override,
                override_reason=args.override_reason,
            )
        )
        return 0
    if args.cmd == "measure-recommendation":
        print_json(
            cf.domains.recommendations.measure_recommendation_item(
                args.id,
                performance_snapshot_id=args.performance_snapshot_id,
                admin_override=args.admin_override,
                override_reason=args.override_reason,
            )
        )
        return 0
    if args.cmd == "execute-recommendation":
        print_json(
            cf.domains.recommendations.execute_accepted_recommendation(
                args.id,
                mode=args.mode,
                force=args.force,
                dry_run_render=args.dry_run_render,
                run_audit=not args.no_audit,
                contentforge_base_url=args.contentforge_base_url,
            )
        )
        return 0
    if args.cmd == "account-memory":
        print_json(
            cf.domains.account_memory.account_memory(
                args.campaign, account=args.account
            )
        )
        return 0
    if args.cmd == "rebuild-account-memory":
        print_json(cf.domains.account_memory.rebuild_account_memory(args.campaign))
        return 0
    if args.cmd == "exceptions":
        print_json(cf.domains.exceptions.exceptions(args.campaign, status=args.status))
        return 0
    if args.cmd == "resolve-exception":
        print_json(
            cf.domains.exceptions.resolve_exception(
                args.id, resolution=args.resolution, operator=args.operator
            )
        )
        return 0
    if args.cmd == "snooze-exception":
        print_json(
            cf.domains.exceptions.snooze_exception(
                args.id, until=args.until, reason=args.reason, operator=args.operator
            )
        )
        return 0
    if args.cmd == "reopen-exception":
        print_json(
            cf.domains.exceptions.reopen_exception(
                args.id, reason=args.reason, operator=args.operator
            )
        )
        return 0
    if args.cmd == "import-reference-bank":
        bank_path = (
            Path(args.path)
            if args.path
            else settings.reference_reels_root
            / "learning"
            / "campaign_reference_bank.json"
        )
        prompt_pack = (
            Path(args.prompt_pack)
            if args.prompt_pack
            else settings.reference_reels_root
            / "learning"
            / "higgsfield_prompt_pack_top300.json"
        )
        print_json(
            cf.domains.reference.import_reference_bank(
                bank_path,
                prompt_pack if prompt_pack.exists() else None,
                dry_run=not args.apply,
                campaign_slug=args.campaign,
                require_local_paths=args.require_local_paths,
                replace_campaign_links=args.replace_campaign_links,
            )
        )
        return 0
    if args.cmd == "import-audio-catalog":
        print_json(
            cf.domains.audio_recommendations.import_audio_catalog(Path(args.path))
        )
        return 0
    if args.cmd == "import-audio-memory":
        print_json(
            cf.domains.audio_recommendations.import_audio_memory(Path(args.path))
        )
        return 0
    if args.cmd == "audio-catalog":
        print_json(
            cf.domains.audio_recommendations.audio_catalog(
                platform=args.platform, limit=args.limit
            )
        )
        return 0
    if args.cmd == "audio-memory":
        print_json(
            cf.domains.audio_recommendations.audio_memory(
                platform=args.platform, account=args.account, limit=args.limit
            )
        )
        return 0
    if args.cmd == "recommend-audio":
        visual_signal = {
            key: value
            for key, value in {
                "energy": args.visual_energy,
                "cutsPerSecond": args.cuts_per_second,
                "avgFrameDelta": args.avg_frame_delta,
            }.items()
            if value is not None
        }
        print_json(
            cf.domains.audio_recommendations.recommend_audio(
                platform=args.platform,
                campaign_slug=args.campaign,
                recommendation_item_id=args.recommendation_item,
                account=args.account,
                content_tags=[
                    tag.strip() for tag in args.content_tags.split(",") if tag.strip()
                ],
                account_tags=[
                    tag.strip() for tag in args.account_tags.split(",") if tag.strip()
                ],
                visual_signal=visual_signal or None,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "select-audio":
        print_json(
            cf.domains.audio_operations.select_audio_for_recommendation(
                args.recommendation_item,
                args.audio_id,
                operator=args.operator,
                notes=args.notes,
            )
        )
        return 0
    if args.cmd == "attach-audio":
        print_json(
            cf.domains.audio_operations.attach_audio_to_distribution_plan(
                args.distribution_plan_id,
                track_id=args.track_id,
                track_name=args.track_name,
                source=args.source,
                audio_url=args.audio_url,
                native_audio_id=args.native_audio_id,
                local_winner_audio_id=args.local_winner_audio_id,
                selected_reason=args.selected_reason,
                segment_start_seconds=args.segment_start_seconds,
                segment_duration_seconds=args.segment_duration_seconds,
                segment_label=args.segment_label,
                segment_reason=args.segment_reason,
                operator=args.operator,
                notes=args.notes,
            )
        )
        return 0
    if args.cmd == "attach-cover-frame":
        print_json(
            cf.domains.audio_operations.attach_cover_frame_to_rendered_asset(
                args.rendered_asset_id,
                seconds=args.seconds,
                cover_image_path=args.cover_image_path,
                cover_image_url=args.cover_image_url,
                cover_image_hash=args.cover_image_hash,
                reason=args.reason,
                operator=args.operator,
            )
        )
        return 0
    if args.cmd == "decide-audio":
        visual_signal = {
            key: value
            for key, value in {
                "energy": args.visual_energy,
                "cutsPerSecond": args.cuts_per_second,
                "avgFrameDelta": args.avg_frame_delta,
            }.items()
            if value is not None
        }
        print_json(
            cf.domains.audio_recommendations.decide_audio(
                platform=args.platform,
                campaign_slug=args.campaign,
                recommendation_item_id=args.recommendation_item,
                account=args.account,
                content_tags=[
                    tag.strip() for tag in args.content_tags.split(",") if tag.strip()
                ],
                account_tags=[
                    tag.strip() for tag in args.account_tags.split(",") if tag.strip()
                ],
                visual_signal=visual_signal or None,
                limit=args.limit,
                select=args.select,
                operator=args.operator,
            )
        )
        return 0
    if args.cmd == "verify-audio":
        print_json(
            cf.domains.audio_operations.verify_audio_for_post(
                args.post_id,
                proof_url=args.proof_url,
                proof_note=args.proof_note,
                operator=args.operator,
            )
        )
        return 0
    if args.cmd == "reference-patterns":
        print_json(cf.domains.reference.reference_patterns(args.limit))
        return 0
    if args.cmd == "select-reference-pattern":
        print_json(
            cf.domains.reference.select_reference_pattern(
                args.campaign,
                cluster_key=args.cluster_key,
                reference_pattern_id=args.reference_pattern_id,
                variant_count=args.variant_count,
                notes=args.notes,
            )
        )
        return 0
    if args.cmd == "reference-plan":
        print_json(cf.domains.reference.campaign_reference_plan(args.campaign))
        return 0
    if args.cmd == "prepare-from-reference":
        print_json(
            cf.domains.reference.prepare_reel_from_reference(
                campaign_slug=args.campaign,
                cluster_key=args.cluster_key,
                reference_pattern_id=args.reference_pattern_id,
                variant_count=args.variant_count,
                recipes=args.recipes,
                caption_color=args.caption_color,
                notes=args.notes,
                force_new=not args.reuse_existing,
            )
        )
        return 0
    if args.cmd == "make-batch":
        print_json(
            cf.domains.make_batch_repo.make_batch(
                folder=Path(args.folder),
                campaign_slug=args.campaign,
                model_slug=args.model,
                output_format=args.format,
                variant_count=args.variant_count,
                reference_pattern=args.reference_pattern,
                contentforge_base_url=args.contentforge_base_url,
                user_id=args.user_id,
                dry_run_export=args.dry_run_export or True,
                workers=args.workers,
                recipes=args.recipes,
                auto_approve_warning_only=not args.no_auto_approve,
            )
        )
        return 0
    if args.cmd == "intake-finished-video":
        print_json(
            cf.domains.finished_video.intake_finished_video(
                input_path=Path(args.input),
                model_slug=args.model,
                platform=args.platform,
                goal=args.goal,
                reference_pattern=args.reference_pattern,
                campaign_slug=args.campaign,
                contentforge_base_url=args.contentforge_base_url,
                user_id=args.user_id,
                dry_run_export=args.dry_run_export or True,
                variant_count=args.variant_count,
                workers=args.workers,
                recipes=args.recipes,
                creative_plan=args.creative_plan,
                style_lane=args.style_lane,
                source_lineage_path=Path(args.source_lineage).expanduser()
                if args.source_lineage
                else None,
            )
        )
        return 0
    if args.cmd == "register-finished-video":
        placement_decision = None
        if args.caption_placement_decision_json:
            placement_decision = json.loads(args.caption_placement_decision_json)
            if not isinstance(placement_decision, dict):
                raise SystemExit(
                    "--caption-placement-decision-json must be a JSON object"
                )
        print_json(
            cf.domains.finished_video.register_finished_video(
                input_path=Path(args.input),
                campaign_slug=args.campaign,
                model_slug=args.model,
                caption=args.caption,
                caption_hash=args.caption_hash,
                caption_bank=args.caption_bank,
                creator_mix=args.creator_mix,
                creator_model=args.creator_model,
                track_id=args.track_id,
                track_name=args.track_name,
                audio_source=args.audio_source,
                selected_reason=args.selected_reason,
                operator=args.operator,
                approval_reason=args.approval_reason,
                review_batch=args.review_batch,
                caption_placement_policy=args.caption_placement_policy,
                caption_placement_decision=placement_decision,
            )
        )
        return 0
    if args.cmd == "archive-inventory":
        print_json(
            cf.domains.archive_quality.archive_inventory_report(
                folder=Path(args.folder),
                campaign_slug=args.campaign,
                creator=args.creator,
                requested_count=args.requested_count,
                model_slug=args.model,
                recent_days=args.recent_days,
            )
        )
        return 0
    if args.cmd == "archive-candidate-quality":
        print_json(
            cf.domains.archive_quality.archive_candidate_quality_report(
                inventory_report_path=Path(args.inventory_report),
                requested_count=args.requested_count,
                exclude_indices=args.exclude_index,
            )
        )
        return 0
    if args.cmd == "create-creative-plan":
        print_json(
            cf.domains.creative_planning.create_creative_plan(
                name=args.name,
                platform=args.platform,
                target_account=args.target_account,
                daily_base_video_target=args.daily_base_video_target,
                style_lanes=[
                    lane.strip() for lane in args.style_lanes.split(",") if lane.strip()
                ],
                model_profile=args.model_profile,
                source_accounts=[
                    account.strip()
                    for account in args.source_accounts.split(",")
                    if account.strip()
                ],
                goal=args.goal,
                linked_campaign=args.linked_campaign,
            )
        )
        return 0
    if args.cmd == "creative-plan":
        print_json(cf.domains.creative_planning.creative_plan(args.name))
        return 0
    if args.cmd == "update-creative-plan-status":
        print_json(
            cf.domains.creative_planning.update_creative_plan_status(
                name=args.name, status=args.status
            )
        )
        return 0
    if args.cmd == "sync-creative-plan-progress":
        print_json(
            cf.domains.creative_planning.sync_creative_plan_progress(
                name=args.name, prompt_export_path=Path(args.prompt_export)
            )
        )
        return 0
    if args.cmd == "activity-log":
        print_json(
            {
                "schema": "campaign_factory.activity_log.v1",
                "campaign": args.campaign,
                "events": cf.domains.events.events_for_campaign(
                    args.campaign, limit=args.limit
                ),
            }
        )
        return 0
    if args.cmd == "jobs":
        statuses = (
            [status.strip() for status in args.status.split(",") if status.strip()]
            if args.status
            else None
        )
        jobs = cf.domains.events.jobs_for_campaign(
            args.campaign,
            limit=args.limit,
            statuses=statuses,
            stuck_hours=args.stuck_hours,
        )
        print_json(
            {
                "schema": "campaign_factory.jobs.v1",
                "campaign": args.campaign,
                "statuses": statuses,
                "stuckHours": args.stuck_hours,
                "summary": {
                    "failed": sum(1 for job in jobs if job.get("status") == "failed"),
                    "stuck": sum(1 for job in jobs if job.get("stuck")),
                },
                "jobs": jobs,
            }
        )
        return 0
    if args.cmd == "job":
        print_json(cf.domains.events.pipeline_job(args.id))
        return 0
    if args.cmd == "pipeline-smoke":
        pipeline_job = cf.domains.events.create_pipeline_job(
            "pipeline_smoke",
            None,
            {
                "folder": args.folder,
                "campaign": args.campaign,
                "model": args.model,
                "userId": args.user_id,
                "hookCount": len(args.hook or []),
                "hooksPath": args.hooks,
                "recipes": args.recipes or [],
                "accounts": args.account or [],
                "contentforgeBaseUrl": args.contentforge_base_url,
                "runReel": args.run_reel,
                "workers": args.workers,
                "minScore": args.min_score,
            },
        )
        cf.domains.events.start_pipeline_job(pipeline_job["id"])
        hooks = load_hooks(args.hooks, args.hook)
        if not hooks:
            cf.domains.events.fail_pipeline_job(
                pipeline_job["id"], "pipeline-smoke requires --hook or --hooks"
            )
            raise SystemExit("pipeline-smoke requires --hook or --hooks")
        try:
            result = {
                "schema": "campaign_factory.pipeline_smoke.v1",
                "campaign": args.campaign,
                "pipelineJobId": pipeline_job["id"],
                "import": cf.domains.asset_import.import_folder(
                    Path(args.folder),
                    campaign_slug=args.campaign,
                    model_slug=args.model,
                    account_handles=args.account,
                    platform="instagram",
                    notes="pipeline smoke import",
                ),
                "prepare": None,
                "run": None,
                "sync": None,
                "audit": None,
                "dryRunExport": None,
                "readiness": None,
            }
            cf.domains.events.set_pipeline_job_campaign(
                pipeline_job["id"], result["import"]["campaign"]["id"]
            )
            result["prepare"] = cf.domains.reel_execution.prepare_reel_inputs(
                campaign_slug=args.campaign,
                hooks=hooks,
                recipes=args.recipes,
                caption_color="auto",
                notes="pipeline smoke render",
            )
            if args.run_reel:
                result["run"] = cf.domains.reel_execution.run_reel_factory(
                    campaign_slug=args.campaign,
                    workers=args.workers,
                    dry_run=False,
                    caption_band="auto",
                    caption_color="light",
                    caption_style="ig",
                    caption_font="Instagram Sans Condensed",
                    phone_finalize=True,
                )
            result["sync"] = cf.domains.reel_execution.sync_reel_outputs(
                campaign_slug=args.campaign
            )
            result["audit"] = audit_campaign(
                cf,
                campaign_slug=args.campaign,
                min_score=args.min_score,
                contentforge_base_url=args.contentforge_base_url,
            )
            result["dryRunExport"] = export_threadsdash(
                cf, campaign_slug=args.campaign, user_id=args.user_id, dry_run=True
            )
            result["readiness"] = evaluate_export_readiness(
                cf, campaign_slug=args.campaign, user_id=args.user_id
            )
            cf.domains.events.finish_pipeline_job(
                pipeline_job["id"],
                {
                    "campaign": args.campaign,
                    "importedCount": len(
                        (result.get("import") or {}).get("imported") or []
                    ),
                    "syncedCount": len((result.get("sync") or {}).get("synced") or []),
                    "draftCount": (result.get("dryRunExport") or {}).get("draftCount"),
                },
            )
            print_json(result)
        except Exception as exc:
            cf.domains.events.record_event(
                "pipeline_smoke_failed",
                pipeline_job_id=pipeline_job["id"],
                status="failure",
                message=f"Pipeline smoke failed: {exc}",
                metadata={"error": str(exc)},
            )
            cf.domains.events.fail_pipeline_job(pipeline_job["id"], str(exc))
            raise
        return 0
    return None
