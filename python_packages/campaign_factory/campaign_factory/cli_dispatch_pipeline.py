from __future__ import annotations

from pathlib import Path

from .adapters.contentforge import audit_campaign
from .adapters.threadsdash_account_projection import (
    summarize_threadsdash_usage,
    sync_threadsdash_account_assignments,
)
from .adapters.threadsdash_draft_delivery import export_threadsdash
from .adapters.threadsdash_draft_readiness import (
    evaluate_export_readiness,
    preflight_supabase,
    verify_threadsdash_export,
)
from .adapters.threadsdash_metrics_ingestion import sync_performance_snapshots
from .adapters.threadsdash_owner_api import fetch_reddit_library_snapshot
from .asset_inventory import explain_asset, inventory_report
from .cli_support import (
    decision_ledger_kwargs,
    load_hooks,
    load_json_object,
    print_json,
)
from .control import operator_control_check
from .creation_modes import run_creation_batch
from .creative_approval import build_and_record_creative_approval_v2
from .daily_library_production import run_daily_library_production
from .daily_orchestrator import orchestrate_daily
from .derived_still_reporting import derived_still_report
from .derived_stills import (
    edit_still,
    enroll_still,
    harvest_stills,
)
from .learning_cohort import (
    assign_learning_cohort_references,
    audit_learning_cohort,
    learning_cohort_status,
    prepare_learning_cohort,
    record_learning_cohort_approval,
    record_learning_cohort_draft,
    record_learning_cohort_generation,
    record_learning_cohort_publish,
    run_learning_cohort_day,
)
from .production_higgsfield_authorization import provider_control_reconciliation
from .qc_explain import explain_asset_qc
from .readiness_report import build_mass_production_readiness_report
from .reconciliation import (
    reconciliation_report,
    repair_reconciliation_case,
    summarize_reconciliation_report,
)
from .recreation_anchor_approval import approve_recreation_anchor
from .recreation_lifecycle import explain_recreation_job, record_recreation_review
from .recreation_prompting import build_openai_prompt_pack
from .reddit_handoff import (
    build_reddit_daily_schedule,
    build_reddit_handoff_review,
    build_reddit_manual_handoff,
    build_reddit_trend_brief,
    deliver_reddit_manual_handoff,
    record_reddit_reservation_receipt,
    set_reddit_proposed_assignment,
    write_reddit_manual_handoff,
    write_reddit_trend_brief,
)
from .reddit_library import archive_reddit_assets, build_reddit_library_report
from .reddit_weekly import (
    RedditResearchClient,
    prepare_reddit_weekly_plan,
    run_reddit_generation_request,
)
from .reference_url_workflow import run_reference_analysis
from .state_ownership import explain_state, reconcile_bridge
from .trial_reels import (
    graduate_trial_reel,
    record_trial_observation,
    trial_reel_ranking_report,
)
from .variation_stage import run_variation_stage


def dispatch_pipeline_commands(args, cf, settings) -> int | None:
    if args.cmd == "reconcile":
        if args.reconcile_cmd == "report":
            report = reconciliation_report(cf.conn, settings)
            print_json(
                summarize_reconciliation_report(
                    report, examples_per_class=args.examples_per_class
                )
                if args.summary
                else report
            )
        else:
            print_json(
                repair_reconciliation_case(
                    cf.conn,
                    settings,
                    case_id=args.case,
                    operator=args.operator,
                    reason=args.reason,
                    apply=args.apply,
                    expected_fingerprint=args.fingerprint,
                )
            )
        return 0
    if args.cmd == "state" and args.state_cmd == "explain":
        print_json(explain_state(args.record_or_id))
        return 0
    if args.cmd == "bridge" and args.bridge_cmd == "reconcile":
        print_json(
            reconcile_bridge(
                cf,
                export_id=args.export_id,
                ingest_url=args.threadsdash_ingest_url,
                ingest_secret=args.threadsdash_ingest_secret,
            )
        )
        return 0
    if args.cmd == "provider" and args.provider_cmd == "reconcile":
        print_json(provider_control_reconciliation(cf))
        return 0
    if args.cmd == "init":
        print_json(
            {
                "ok": True,
                "db": str(settings.db_path),
                "campaigns": str(settings.campaigns_dir),
            }
        )
        return 0
    if args.cmd == "control-check":
        print_json(operator_control_check(settings))
        return 0
    if args.cmd == "reddit-brief":
        spec = load_json_object(str(args.spec))
        brief = build_reddit_trend_brief(spec or {})
        path = (
            write_reddit_trend_brief(cf, campaign_slug=args.campaign, brief=brief)
            if args.apply
            else None
        )
        print_json({"brief": brief, "artifactPath": str(path) if path else None})
        return 0
    if args.cmd == "reddit-assign":
        print_json(
            set_reddit_proposed_assignment(
                cf,
                campaign_slug=args.campaign,
                rendered_asset_id=args.asset,
                account_username=args.account,
                operator=args.operator,
                reason=args.reason,
                apply=args.apply,
            )
        )
        return 0
    if args.cmd == "reddit-handoff":
        spec = load_json_object(str(args.spec)) or {}
        if not args.apply:
            print_json(
                build_reddit_handoff_review(cf, campaign_slug=args.campaign, spec=spec)
            )
            return 0
        payload = build_reddit_manual_handoff(
            cf, campaign_slug=args.campaign, spec=spec
        )
        path = write_reddit_manual_handoff(
            cf, campaign_slug=args.campaign, payload=payload
        )
        delivery = None
        if args.deliver:
            delivery = deliver_reddit_manual_handoff(
                payload,
                ingest_url=args.threadsdash_ingest_url,
                ingest_secret=args.threadsdash_ingest_secret,
            )
            record_reddit_reservation_receipt(
                cf,
                campaign_slug=args.campaign,
                payload=payload,
                delivery=delivery,
            )
        print_json(
            {
                "payload": payload,
                "artifactPath": str(path),
                "delivery": delivery,
            }
        )
        return 0
    if args.cmd == "reddit-schedule":
        print_json(
            build_reddit_daily_schedule(
                args.date,
                include_optional=args.include_optional,
            )
        )
        return 0
    if args.cmd == "reddit-library":
        print_json(
            build_reddit_library_report(
                cf,
                campaign_slug=args.campaign,
                state=load_json_object(str(args.state)) or {},
                as_of=args.as_of,
            )
        )
        return 0
    if args.cmd == "reddit-library-archive":
        print_json(
            archive_reddit_assets(
                cf,
                campaign_slug=args.campaign,
                state=load_json_object(str(args.state)) or {},
                asset_ids=args.asset,
                operator=args.operator,
                reason=args.reason,
                as_of=args.as_of,
                apply=args.apply,
            )
        )
        return 0
    if args.cmd == "reddit-weekly":
        state = (
            load_json_object(str(args.state))
            if args.state
            else fetch_reddit_library_snapshot(
                user_id=args.user_id,
                ingest_url=args.threadsdash_ingest_url,
                ingest_secret=args.threadsdash_ingest_secret,
            )
        )
        client = RedditResearchClient.from_env()
        print_json(
            prepare_reddit_weekly_plan(
                cf,
                campaign_slug=args.campaign,
                state=state or {},
                research_provider=lambda name: client.subreddit_snapshot(
                    name, limit=args.limit
                ),
                as_of=args.as_of,
                download_references=args.download_references,
            )
        )
        return 0
    if args.cmd == "reddit-weekly-generate":
        print_json(
            run_reddit_generation_request(
                cf,
                plan=load_json_object(str(args.plan)) or {},
                request_id=args.request_id,
                reviewed_by=args.reviewed_by,
                apply=args.apply,
                enable_paid_generation=args.enable_paid_generation,
                budget_cap_credits=args.budget_cap_credits,
                wait=args.wait,
                download=args.download,
            )
        )
        return 0
    if args.cmd == "recreation-anchor-approve":
        print_json(
            approve_recreation_anchor(
                factory=cf,
                creator=args.creator,
                anchor_file=args.anchor_file,
                anchor_generation_id=args.anchor_generation_id,
                prompt_pack_path=args.prompt_pack,
                selected_composition_frame_sha256=(
                    args.selected_composition_frame_sha256
                ),
                approved_by=args.approved_by,
                output_dir=(
                    args.output_dir
                    or settings.reference_reels_root / "anchor_approvals"
                ),
            )
        )
        return 0
    if args.cmd == "recreation":
        if args.recreation_cmd == "explain":
            print_json(explain_recreation_job(cf, args.job))
        else:
            print_json(
                record_recreation_review(
                    cf,
                    job_id=args.job,
                    stage=args.stage,
                    decision=args.decision,
                    reviewed_by=args.reviewed_by,
                    notes=args.notes,
                )
            )
        return 0
    if args.cmd == "asset":
        if args.asset_cmd == "explain":
            print_json(explain_asset(cf, args.sha))
        elif args.asset_cmd == "inventory":
            print_json(
                inventory_report(
                    cf,
                    campaign_slug=args.campaign,
                    content_surface=args.surface,
                )
            )
        elif args.reservation_cmd == "reconcile":
            print_json(
                cf.domains.inventory_reservations.reservation_reconciliation_report(
                    apply=args.apply
                )
            )
        else:
            print_json(
                cf.domains.inventory_reservations.release_inventory_reservation(
                    args.reservation,
                    status="cancelled",
                )
            )
        return 0
    if args.cmd == "create":
        if args.recreation_anchor_approval and getattr(args, "reference_url", None):
            raise ValueError(
                "approved-anchor recreate execution requires --reference-video"
            )
        if (
            args.mode == "recreate_reel"
            and (getattr(args, "reference_url", None) or args.reference_video)
            and not args.recreation_anchor_approval
        ):
            print_json(
                run_reference_analysis(
                    cf,
                    creator=args.creator,
                    reference_url=getattr(args, "reference_url", None),
                    reference_video_path=args.reference_video,
                    reference_platform=args.reference_platform,
                    reference_authorized=args.reference_authorized,
                    declared_talking=args.reference_talking,
                    declared_non_talking=args.reference_non_talking,
                    operator_classification=args.reference_classification,
                    operator_warnings=args.reference_warning,
                    recreate_mode=args.recreate_mode,
                    through=getattr(args, "through", None),
                    audio_policy=args.audio_preference,
                    max_credits=args.max_credits,
                    creator_image_path=args.creator_image,
                    recreation_attempt_id=args.recreation_attempt_id,
                    apply=args.apply,
                )
            )
            return 0
        print_json(
            run_creation_batch(
                cf,
                creator=args.creator,
                mode=args.mode,
                style=args.style,
                count=args.count,
                execution=args.execution,
                accounts=args.accounts,
                audio_preference=args.audio_preference,
                reference_video_path=args.reference_video,
                reference_platform=args.reference_platform,
                reference_authorized=args.reference_authorized,
                reference_talking=args.reference_talking,
                apply=args.apply,
                max_total_credits=args.max_credits,
                max_concurrency=args.concurrency,
                prompt_pack_provider=build_openai_prompt_pack,
                reuse_policy=args.reuse_policy,
                recreation_anchor_approval_path=args.recreation_anchor_approval,
                recreation_attempt_id=args.recreation_attempt_id,
                source_asset_ids=tuple(args.source_asset_id) or None,
            )
        )
        return 0
    if args.cmd == "stills":
        if args.stills_cmd == "enroll":
            result = enroll_still(
                cf,
                campaign_slug=args.campaign,
                source_asset_id=args.source_asset_id,
                tier=args.tier,
                apply=args.apply,
            )
        elif args.stills_cmd == "harvest":
            result = harvest_stills(
                cf,
                campaign_slug=args.campaign,
                rendered_asset_id=args.rendered_asset_id,
                count=args.count,
                apply=args.apply,
            )
        elif args.stills_cmd == "edit":
            result = edit_still(
                cf,
                campaign_slug=args.campaign,
                image_asset_id=args.image_asset_id,
                operation=args.operation,
                provider=args.provider,
                output_format=args.output_format,
                count=args.count,
                max_usd=args.max_usd,
                apply=args.apply,
            )
        else:
            result = derived_still_report(cf, campaign_slug=args.campaign)
        print_json(result)
        return 0
    if args.cmd == "creative-approval-build":
        print_json(
            build_and_record_creative_approval_v2(
                cf,
                campaign_slug=args.campaign,
                rendered_asset_id=args.rendered_asset_id,
                user_id=args.user_id,
                approved_by=args.approved_by,
                review_decision=load_json_object(args.review_decision),
                root=args.root or settings.creative_approvals_dir,
                surface=args.surface,
                publish_mode=args.publish_mode,
            )
        )
        return 0
    if args.cmd == "qc-explain":
        print_json(explain_asset_qc(cf, args.asset))
        return 0
    if args.cmd == "learning-cohort":
        if args.learning_cohort_cmd == "prepare":
            print_json(
                prepare_learning_cohort(
                    cf.conn, start_date=args.start_date, seed=args.seed
                )
            )
        elif args.learning_cohort_cmd == "run-day":
            print_json(run_learning_cohort_day(cf.conn, day_index=args.day))
        elif args.learning_cohort_cmd == "assign-references":
            print_json(
                assign_learning_cohort_references(
                    cf.conn,
                    identity_manifest_path=args.identity_manifest,
                    apply=args.apply,
                )
            )
        elif args.learning_cohort_cmd == "record-generation":
            print_json(
                record_learning_cohort_generation(
                    cf.conn,
                    assignment_id=args.assignment,
                    rendered_asset_id=args.rendered_asset_id,
                    lineage_path=args.lineage,
                    artifact_path=args.artifact,
                    provider_reservation_id=args.provider_reservation_id,
                )
            )
        elif args.learning_cohort_cmd == "record-draft":
            print_json(
                record_learning_cohort_draft(
                    cf.conn, assignment_id=args.assignment, draft_id=args.draft_id
                )
            )
        elif args.learning_cohort_cmd == "record-approval":
            print_json(
                record_learning_cohort_approval(
                    cf.conn, assignment_id=args.assignment, decision=args.decision
                )
            )
        elif args.learning_cohort_cmd == "record-publish":
            print_json(
                record_learning_cohort_publish(
                    cf.conn,
                    assignment_id=args.assignment,
                    post_id=args.post_id,
                    published_at=args.published_at,
                )
            )
        elif args.learning_cohort_cmd == "status":
            print_json(learning_cohort_status(cf.conn))
        elif args.learning_cohort_cmd == "audit":
            print_json(audit_learning_cohort(cf.conn))
        return 0
    if args.cmd == "import-folder":
        print_json(
            cf.domains.asset_import.import_folder(
                Path(args.folder),
                campaign_slug=args.campaign,
                model_slug=args.model,
                model_name=args.model_name,
                platform=args.platform,
                account_handles=args.account,
                source_prompt=args.source_prompt,
                notes=args.notes,
                storage_mode=args.storage_mode,
            )
        )
        return 0
    if args.cmd == "prepare-reel":
        print_json(
            cf.domains.reel_execution.prepare_reel_inputs(
                campaign_slug=args.campaign,
                hooks=load_hooks(args.hooks, args.hook),
                recipes=args.recipes,
                caption_color=args.caption_color,
                notes=args.notes,
                force_new=args.force_new,
                source_asset_ids=args.source_asset_id or None,
            )
        )
        return 0
    if args.cmd == "run-reel":
        print_json(
            cf.domains.reel_execution.run_reel_factory(
                campaign_slug=args.campaign,
                workers=args.workers,
                library_root=args.library_root,
                dry_run=not args.apply or args.dry_run,
                caption_band=args.band,
                caption_color=args.color,
                caption_style=args.style,
                caption_font=args.font,
                phone_finalize=not args.no_phone_finalize,
                rerender_all=args.rerender_all,
                max_outputs_per_clip=args.max_outputs_per_clip,
                render_job_ids=args.render_job_id or None,
                caption_mix=args.caption_mix,
                creator_style_preset=args.creator_style_preset,
            )
        )
        return 0
    if args.cmd == "sync-reel":
        print_json(
            cf.domains.reel_execution.sync_reel_outputs(
                campaign_slug=args.campaign, render_job_ids=args.render_job_id or None
            )
        )
        return 0
    if args.cmd == "daily-library":
        print_json(
            run_daily_library_production(
                cf,
                day_index=args.day,
                cohort_id=args.cohort,
                campaign_slug=args.campaign,
                workers=args.workers,
                contentforge_base_url=args.contentforge_base_url,
                apply=args.apply,
            )
        )
        return 0
    if args.cmd == "orchestrate-daily":
        print_json(
            orchestrate_daily(
                cf,
                run_key=args.run_key,
                max_items=args.max_items,
                per_creator_cap=args.per_creator_cap,
                per_campaign_cap=args.per_campaign_cap,
                provider_cap=args.provider_cap,
                max_attempts=args.max_attempts,
                apply=args.apply,
                execute=args.execute,
            )
        )
        return 0
    if args.cmd == "variation":
        if args.variation_cmd == "run":
            print_json(
                run_variation_stage(
                    cf,
                    campaign_slug=args.campaign,
                    preset_name=args.preset,
                    rendered_asset_ids=args.rendered_asset_id or None,
                    dry_run=not args.apply or args.dry_run,
                    contentforge_base_url=args.contentforge_base_url,
                )
            )
        return 0
    if args.cmd == "audit":
        print_json(
            audit_campaign(
                cf,
                campaign_slug=args.campaign,
                min_score=args.min_score,
                contentforge_base_url=args.contentforge_base_url,
                layers=args.layer or None,
                rendered_asset_ids=args.rendered_asset_id or None,
            )
        )
        return 0
    if args.cmd == "approve":
        print_json(
            cf.domains.finished_video.approve_rendered_asset(
                args.rendered_asset_id,
                notes=args.notes,
                require_safe_audit=not args.force_unsafe_audit,
            )
        )
        return 0
    if args.cmd == "review-decision":
        print_json(
            cf.domains.finished_video.review_rendered_asset(
                args.rendered_asset_id,
                decision=args.decision,
                notes=args.notes,
                require_safe_audit=not args.force_unsafe_audit,
            )
        )
        return 0
    if args.cmd == "attest-publishability":
        print_json(
            cf.domains.finished_video.attest_publishability_evidence(
                args.rendered_asset_id,
                instagram_post_caption=args.instagram_post_caption,
                visual_qc_status=args.visual_qc_status,
                identity_verification_status=args.identity_verification_status,
                operator=args.operator,
                notes=args.notes,
            )
        )
        return 0
    if args.cmd == "export-readiness":
        print_json(
            evaluate_export_readiness(
                cf,
                campaign_slug=args.campaign,
                user_id=args.user_id,
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                limit=args.limit,
                content_pillar=args.content_pillar,
                cta_type=args.cta_type,
                language=args.language,
                schedule_mode=args.schedule_mode,
            )
        )
        return 0
    if args.cmd == "readiness-report":
        campaign_row = cf.conn.execute(
            "SELECT slug FROM campaigns WHERE id = ? OR slug = ?",
            (args.campaign_id, args.campaign_id),
        ).fetchone()
        if not campaign_row:
            raise ValueError(f"campaign not found: {args.campaign_id}")
        campaign_slug = campaign_row["slug"]
        usage = None
        export_readiness = None
        if args.user_id and args.supabase_url and args.supabase_service_role_key:
            try:
                usage = summarize_threadsdash_usage(
                    cf,
                    campaign_slug=campaign_slug,
                    user_id=args.user_id,
                    supabase_url=args.supabase_url,
                    supabase_service_role_key=args.supabase_service_role_key,
                    limit=args.limit,
                )
            except Exception as exc:
                usage = {"checked": False, "error": str(exc), "assets": []}
            try:
                export_readiness = evaluate_export_readiness(
                    cf,
                    campaign_slug=campaign_slug,
                    user_id=args.user_id,
                    supabase_url=args.supabase_url,
                    supabase_service_role_key=args.supabase_service_role_key,
                    limit=args.limit,
                )
            except Exception as exc:
                export_readiness = {
                    "checked": False,
                    "liveExportAllowed": False,
                    "blockingReasons": ["threadsdash_readiness_check_failed"],
                    "warnings": [str(exc)],
                }
        report = build_mass_production_readiness_report(
            cf,
            campaign_id=args.campaign_id,
            days=args.days,
            user_id=args.user_id,
            threadsdash_usage=usage,
            threadsdash_readiness=export_readiness,
        )
        if args.format == "markdown":
            print(report["markdownSummary"])
        else:
            print_json(report)
        return 0
    if args.cmd == "graduate-trial-reel":
        print_json(
            graduate_trial_reel(
                cf,
                trial_post_id=args.trial_post_id,
                distribution_plan_id=args.distribution_plan_id,
                approved_by=args.approved_by,
            )
        )
        return 0
    if args.cmd == "record-trial-observation":
        print_json(
            record_trial_observation(
                cf,
                trial_post_id=args.trial_post_id,
                distribution_plan_id=args.distribution_plan_id,
                account_id=args.account_id,
                observed_hours=args.observed_hours,
                views=args.views,
                engagement=args.engagement,
                metrics=load_json_object(args.metrics_json),
            )
        )
        return 0
    if args.cmd == "trial-reel-ranking-report":
        print_json(trial_reel_ranking_report(cf))
        return 0
    if args.cmd == "export-threadsdash":
        if not args.dry_run and (
            not (args.threadsdash_ingest_url and args.threadsdash_ingest_secret)
        ):
            raise SystemExit(
                "live ThreadsDashboard export requested but ingest URL/secret are missing; pass --dry-run or provide owner-API credentials"
            )
        print_json(
            export_threadsdash(
                cf,
                campaign_slug=args.campaign,
                user_id=args.user_id,
                dry_run=args.dry_run,
                supabase_storage_bucket=args.supabase_storage_bucket,
                allow_warnings=args.allow_warnings,
                warning_override_reason=args.warning_override_reason,
                warning_override_by=args.warning_override_by,
                content_pillar=args.content_pillar,
                cta_type=args.cta_type,
                language=args.language,
                max_drafts=args.max_drafts,
                rendered_asset_ids=args.rendered_asset_id or None,
                surface=args.surface,
                schedule_mode=args.schedule_mode,
                enable_variation=args.enable_variation,
                variation_preset=args.variation_preset,
                publish_mode=args.publish_mode,
                review_only=args.review_only,
                draft_payload_schema=args.draft_payload_schema,
                threadsdash_ingest_url=args.threadsdash_ingest_url,
                threadsdash_ingest_secret=args.threadsdash_ingest_secret,
            )
        )
        return 0
    if args.cmd == "supabase-preflight":
        pipeline_job = cf.domains.events.create_pipeline_job(
            "supabase_preflight",
            None,
            {
                "hasSupabaseUrl": bool(args.supabase_url),
                "hasSupabaseServiceRoleKey": bool(args.supabase_service_role_key),
                "supabaseStorageBucket": args.supabase_storage_bucket,
            },
        )
        cf.domains.events.start_pipeline_job(pipeline_job["id"])
        try:
            result = preflight_supabase(
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                supabase_storage_bucket=args.supabase_storage_bucket,
            )
            result["pipelineJobId"] = pipeline_job["id"]
            cf.domains.events.record_event(
                "supabase_preflight_checked",
                pipeline_job_id=pipeline_job["id"],
                status="success" if result["ok"] else "failure",
                message=f"Supabase preflight {('passed' if result['ok'] else 'failed')}",
                metadata={
                    "ok": result["ok"],
                    "blockingReasons": result.get("blockingReasons") or [],
                },
            )
            if result["ok"]:
                cf.domains.events.finish_pipeline_job(
                    pipeline_job["id"],
                    {
                        "ok": result["ok"],
                        "blockingReasons": result.get("blockingReasons") or [],
                    },
                )
            else:
                cf.domains.events.fail_pipeline_job(
                    pipeline_job["id"],
                    "Supabase preflight failed",
                    {
                        "ok": result["ok"],
                        "blockingReasons": result.get("blockingReasons") or [],
                    },
                )
            print_json(result)
        except Exception as exc:
            result = {
                "schema": "campaign_factory.supabase_preflight.v1",
                "ok": False,
                "bucket": args.supabase_storage_bucket,
                "checks": [],
                "blockingReasons": [str(exc)],
                "pipelineJobId": pipeline_job["id"],
            }
            cf.domains.events.record_event(
                "supabase_preflight_checked",
                pipeline_job_id=pipeline_job["id"],
                status="failure",
                message=f"Supabase preflight failed: {exc}",
                metadata={"error": str(exc)},
            )
            cf.domains.events.fail_pipeline_job(pipeline_job["id"], str(exc))
            print_json(result)
            return 1
        return 0
    if args.cmd == "verify-threadsdash-export":
        pipeline_job = cf.domains.events.create_pipeline_job(
            "verify_threadsdash_export", None, {"exportManifest": args.export_manifest}
        )
        cf.domains.events.start_pipeline_job(pipeline_job["id"])
        try:
            result = verify_threadsdash_export(
                export_result_or_path=Path(args.export_manifest),
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                allowed_export_root=cf.settings.campaigns_dir,
            )
            result["pipelineJobId"] = pipeline_job["id"]
            cf.domains.events.record_event(
                "threadsdash_export_verified",
                pipeline_job_id=pipeline_job["id"],
                status="success" if result["ok"] else "failure",
                message=f"ThreadsDash export {('verified' if result['ok'] else 'verification failed')}",
                metadata={
                    "ok": result["ok"],
                    "campaign": result.get("campaign"),
                    "exportPath": result.get("exportPath"),
                    "blockingReasons": result.get("blockingReasons") or [],
                },
            )
            if result["ok"]:
                cf.domains.events.finish_pipeline_job(
                    pipeline_job["id"],
                    {
                        "ok": result["ok"],
                        "campaign": result.get("campaign"),
                        "blockingReasons": result.get("blockingReasons") or [],
                    },
                )
            else:
                cf.domains.events.fail_pipeline_job(
                    pipeline_job["id"],
                    "ThreadsDash export verification failed",
                    {
                        "ok": result["ok"],
                        "campaign": result.get("campaign"),
                        "blockingReasons": result.get("blockingReasons") or [],
                    },
                )
            print_json(result)
        except Exception as exc:
            cf.domains.events.record_event(
                "threadsdash_export_verified",
                pipeline_job_id=pipeline_job["id"],
                status="failure",
                message=f"ThreadsDash export verification failed: {exc}",
                metadata={"error": str(exc)},
            )
            cf.domains.events.fail_pipeline_job(pipeline_job["id"], str(exc))
            raise
        return 0
    if args.cmd == "threadsdash-usage":
        print_json(
            summarize_threadsdash_usage(
                cf,
                campaign_slug=args.campaign,
                user_id=args.user_id,
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "sync-threadsdash-assignments":
        print_json(
            sync_threadsdash_account_assignments(
                cf,
                campaign_slug=args.campaign,
                user_id=args.user_id,
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "sync-performance":
        print_json(
            sync_performance_snapshots(
                cf,
                campaign_slug=args.campaign,
                user_id=args.user_id,
                supabase_url=args.supabase_url,
                supabase_service_role_key=args.supabase_service_role_key,
                limit=args.limit,
            )
        )
        return 0
    if args.cmd == "performance-summary":
        print_json(
            cf.domains.performance_summary_repo.performance_summary(args.campaign)
        )
        return 0
    if args.cmd == "multi-surface-inventory-audit":
        print_json(
            cf.domains.surface_inventory.multi_surface_inventory_audit(
                creator=args.creator, campaign_slug=args.campaign
            )
        )
        return 0
    if args.cmd == "account-surface-obligations-plan":
        print_json(
            cf.domains.surface_requirements.account_surface_obligations_plan(
                creator=args.creator, date=args.date
            )
        )
        return 0
    if args.cmd == "account-content-needs":
        print_json(
            cf.domains.surface_requirements.account_content_needs(
                account_id=args.account_id, creator=args.creator, date=args.date
            )
        )
        return 0
    if args.cmd == "account-surface-status":
        print_json(
            cf.domains.surface_requirements.account_surface_status(
                account_id=args.account_id, creator=args.creator, date=args.date
            )
        )
        return 0
    if args.cmd == "creator-content-needs":
        print_json(
            cf.domains.surface_requirements.creator_content_needs(
                creator=args.creator, date=args.date
            )
        )
        return 0
    if args.cmd == "surface-gap-report":
        print_json(
            cf.domains.surface_requirements.surface_gap_report(
                creator=args.creator, date=args.date
            )
        )
        return 0
    if args.cmd in {
        "inventory-recovery-report",
        "inventory-recovery-priority-report",
        "inventory-recovery-by-blocker",
        "inventory-recovery-master-report",
    }:
        payload = {
            "creator": args.creator,
            "campaign_slug": args.campaign,
            "content_surface": args.content_surface,
            "required_inventory": args.required_inventory,
            "account_target": args.account_target,
            "posts_per_account_per_day": args.posts_per_account_per_day,
            "buffer_days": args.buffer_days,
        }
        if args.cmd == "inventory-recovery-report":
            print_json(
                cf.domains.inventory_recovery.inventory_recovery_report(**payload)
            )
        elif args.cmd == "inventory-recovery-priority-report":
            print_json(
                cf.domains.inventory_recovery.inventory_recovery_priority_report(
                    **payload
                )
            )
        elif args.cmd == "inventory-recovery-by-blocker":
            print_json(
                cf.domains.inventory_recovery.inventory_recovery_by_blocker(**payload)
            )
        else:
            print_json(
                cf.domains.inventory_recovery.inventory_recovery_master_report(
                    **payload
                )
            )
        return 0
    if args.cmd in {
        "schedule-safe-production-report",
        "schedule-safe-production-waterfall",
        "schedule-safe-production-loss-analysis",
        "schedule-safe-production-capacity-model",
        "schedule-safe-production-master-report",
    }:
        payload = {
            "creator": args.creator,
            "campaign_slug": args.campaign,
            "content_surface": args.content_surface,
            "lookback_days": args.lookback_days,
            "required_inventory": args.required_inventory,
            "current_inventory": args.current_inventory,
        }
        if args.cmd == "schedule-safe-production-report":
            print_json(
                cf.domains.schedule_safe_production.schedule_safe_production_report(
                    **payload
                )
            )
        elif args.cmd == "schedule-safe-production-waterfall":
            print_json(
                cf.domains.schedule_safe_production.schedule_safe_production_waterfall(
                    **payload
                )
            )
        elif args.cmd == "schedule-safe-production-loss-analysis":
            print_json(
                cf.domains.schedule_safe_production.schedule_safe_production_loss_analysis(
                    **payload
                )
            )
        elif args.cmd == "schedule-safe-production-capacity-model":
            print_json(
                cf.domains.schedule_safe_production.schedule_safe_production_capacity_model(
                    **payload
                )
            )
        else:
            print_json(
                cf.domains.schedule_safe_production.schedule_safe_production_master_report(
                    **payload
                )
            )
        return 0
    if args.cmd in {
        "contentforge-visual-qc-failure-report",
        "contentforge-visual-qc-loss-analysis",
        "contentforge-visual-qc-waterfall",
        "contentforge-visual-qc-repair-plan",
        "contentforge-visual-qc-master-report",
    }:
        payload = {
            "creator": args.creator,
            "campaign_slug": args.campaign,
            "content_surface": args.content_surface,
            "lookback_days": args.lookback_days,
            "required_inventory": args.required_inventory or 225,
            "current_inventory": args.current_inventory,
        }
        if args.cmd == "contentforge-visual-qc-failure-report":
            print_json(
                cf.domains.contentforge_visual_qc.contentforge_visual_qc_failure_report(
                    **payload
                )
            )
        elif args.cmd == "contentforge-visual-qc-loss-analysis":
            print_json(
                cf.domains.contentforge_visual_qc.contentforge_visual_qc_loss_analysis(
                    **payload
                )
            )
        elif args.cmd == "contentforge-visual-qc-waterfall":
            print_json(
                cf.domains.contentforge_visual_qc.contentforge_visual_qc_waterfall(
                    **payload
                )
            )
        elif args.cmd == "contentforge-visual-qc-repair-plan":
            print_json(
                cf.domains.contentforge_visual_qc.contentforge_visual_qc_repair_plan(
                    **payload
                )
            )
        else:
            print_json(
                cf.domains.contentforge_visual_qc.contentforge_visual_qc_master_report(
                    **payload
                )
            )
        return 0
    if args.cmd in {
        "multi-blocker-inventory-unlock-report",
        "multi-blocker-inventory-unlock-plan",
        "inventory-unlock-minimal-fix-set",
        "inventory-unlock-master-report",
    }:
        payload = {
            "creator": args.creator,
            "campaign_slug": args.campaign,
            "content_surface": args.content_surface,
            "required_inventory": args.required_inventory,
            "current_inventory": args.current_inventory,
        }
        if args.cmd == "multi-blocker-inventory-unlock-report":
            print_json(
                cf.domains.multi_blocker_unlock.multi_blocker_inventory_unlock_report(
                    **payload
                )
            )
        elif args.cmd == "multi-blocker-inventory-unlock-plan":
            print_json(
                cf.domains.multi_blocker_unlock.multi_blocker_inventory_unlock_plan(
                    **payload
                )
            )
        elif args.cmd == "inventory-unlock-minimal-fix-set":
            print_json(
                cf.domains.multi_blocker_unlock.inventory_unlock_minimal_fix_set(
                    **payload
                )
            )
        else:
            print_json(
                cf.domains.multi_blocker_unlock.inventory_unlock_master_report(
                    **payload
                )
            )
        return 0
    if args.cmd in {
        "operator-inventory-review-batch-plan",
        "operator-inventory-review-batch-summary",
    }:
        payload = {
            "creator": args.creator,
            "campaign_slug": args.campaign,
            "content_surface": args.content_surface,
            "required_inventory": args.required_inventory,
            "current_inventory": args.current_inventory,
            "target_unlock": args.target_unlock,
            "max_batch_size": args.max_batch_size,
        }
        if args.cmd == "operator-inventory-review-batch-plan":
            print_json(
                cf.domains.operator_review.operator_inventory_review_batch_plan(
                    **payload
                )
            )
        else:
            print_json(
                cf.domains.operator_review.operator_inventory_review_batch_summary(
                    **payload
                )
            )
        return 0
    if args.cmd in {
        "operator-review-simulator",
        "operator-review-scenarios",
        "operator-review-efficiency-report",
        "operator-review-minimum-certification-path",
        "operator-review-master-report",
    }:
        payload = {
            "creator": args.creator,
            "campaign_slug": args.campaign,
            "content_surface": args.content_surface,
            "required_inventory": args.required_inventory,
            "current_inventory": args.current_inventory,
        }
        if args.cmd == "operator-review-simulator":
            print_json(cf.domains.operator_review.operator_review_simulator(**payload))
        elif args.cmd == "operator-review-scenarios":
            print_json(cf.domains.operator_review.operator_review_scenarios(**payload))
        elif args.cmd == "operator-review-efficiency-report":
            print_json(
                cf.domains.operator_review.operator_review_efficiency_report(**payload)
            )
        elif args.cmd == "operator-review-minimum-certification-path":
            print_json(
                cf.domains.operator_review.operator_review_minimum_certification_path(
                    **payload
                )
            )
        else:
            print_json(
                cf.domains.operator_review.operator_review_master_report(**payload)
            )
        return 0
    if args.cmd in {
        "fresh-schedule-safe-production-plan",
        "fresh-reel-production-batch-plan",
        "fresh-reel-production-capacity-plan",
        "fresh-reel-production-master-report",
    }:
        payload = {
            "creator": args.creator,
            "campaign_slug": args.campaign,
            "target_schedule_safe_inventory": args.target_schedule_safe_inventory,
            "current_inventory": args.current_inventory,
            "caption_versions_per_parent": args.caption_versions_per_parent,
            "variants_per_caption": args.variants_per_caption,
            "batch_schedule_safe_target": args.batch_schedule_safe_target,
        }
        if args.cmd == "fresh-schedule-safe-production-plan":
            print_json(
                cf.domains.fresh_reel_production.fresh_schedule_safe_production_plan(
                    **payload
                )
            )
        elif args.cmd == "fresh-reel-production-batch-plan":
            print_json(
                cf.domains.fresh_reel_production.fresh_reel_production_batch_plan(
                    **payload
                )
            )
        elif args.cmd == "fresh-reel-production-capacity-plan":
            print_json(
                cf.domains.fresh_reel_production.fresh_reel_production_capacity_plan(
                    **payload
                )
            )
        else:
            print_json(
                cf.domains.fresh_reel_production.fresh_reel_production_master_report(
                    **payload
                )
            )
        return 0
    if args.cmd == "story-inventory-report":
        print_json(
            cf.domains.story_management.story_inventory_report(
                creator=args.creator, campaign_slug=args.campaign
            )
        )
        return 0
    if args.cmd == "story-gap-report":
        print_json(
            cf.domains.story_management.story_gap_report(
                creator=args.creator, date=args.date
            )
        )
        return 0
    if args.cmd == "story-quality-report":
        print_json(
            cf.domains.story_management.story_quality_report(
                creator=args.creator, campaign_slug=args.campaign
            )
        )
        return 0
    if args.cmd == "story-intent-report":
        print_json(
            cf.domains.story_management.story_intent_report(
                creator=args.creator, campaign_slug=args.campaign
            )
        )
        return 0
    if args.cmd == "story-mix-plan":
        print_json(cf.domains.story_management.story_mix_plan(creator=args.creator))
        return 0
    if args.cmd == "story-calendar-plan":
        print_json(
            cf.domains.story_management.story_calendar_plan(creator=args.creator)
        )
        return 0
    if args.cmd == "story-intent-summary":
        print_json(
            cf.domains.story_management.story_intent_summary(
                creator=args.creator, campaign_slug=args.campaign
            )
        )
        return 0
    if args.cmd == "decision-ledger-preview":
        print_json(
            cf.domains.decision_ledger.decision_ledger_preview(
                **decision_ledger_kwargs(args)
            )
        )
        return 0
    if args.cmd == "decision-ledger-report":
        print_json(
            cf.domains.decision_ledger.decision_ledger_report(
                **decision_ledger_kwargs(args)
            )
        )
        return 0
    if args.cmd == "decision-ledger-summary":
        print_json(
            cf.domains.decision_ledger.decision_ledger_summary(
                **decision_ledger_kwargs(args)
            )
        )
        return 0
    if args.cmd == "decision-ledger-by-creator":
        print_json(
            cf.domains.decision_ledger.decision_ledger_by_creator(
                **decision_ledger_kwargs(args)
            )
        )
        return 0
    if args.cmd == "decision-ledger-by-account":
        print_json(
            cf.domains.decision_ledger.decision_ledger_by_account(
                account_id=args.account_id, **decision_ledger_kwargs(args)
            )
        )
        return 0
    if args.cmd == "decision-ledger-by-surface":
        print_json(
            cf.domains.decision_ledger.decision_ledger_by_surface(
                surface=args.surface, **decision_ledger_kwargs(args)
            )
        )
        return 0
    if args.cmd == "decision-ledger-by-decision-type":
        print_json(
            cf.domains.decision_ledger.decision_ledger_by_decision_type(
                decision_type=args.decision_type, **decision_ledger_kwargs(args)
            )
        )
        return 0
    if args.cmd == "account-story-status":
        print_json(
            cf.domains.story_management.account_story_status(
                account_id=args.account_id, creator=args.creator, date=args.date
            )
        )
        return 0
    if args.cmd == "creator-story-summary":
        print_json(
            cf.domains.story_management.creator_story_summary(
                creator=args.creator, date=args.date
            )
        )
        return 0
    if args.cmd == "surface-handoff-readiness-report":
        print_json(
            cf.domains.surface_handoff.surface_handoff_readiness_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                rendered_asset_id=args.rendered_asset_id,
            )
        )
        return 0
    if args.cmd == "surface-draft-proof":
        print_json(
            cf.domains.surface_handoff.surface_draft_proof(
                creator=args.creator,
                campaign=args.campaign,
                rendered_asset_id=args.rendered_asset_id,
            )
        )
        return 0
    if args.cmd == "carousel-integrity-report":
        print_json(
            cf.domains.carousel_integrity.carousel_integrity_report(
                creator=args.creator,
                campaign_slug=args.campaign,
                rendered_asset_id=args.rendered_asset_id,
            )
        )
        return 0
    if args.cmd == "carousel-child-metrics-plan":
        print_json(
            cf.domains.carousel_integrity.carousel_child_metrics_plan(
                creator=args.creator,
                campaign_slug=args.campaign,
                rendered_asset_id=args.rendered_asset_id,
            )
        )
        return 0
    if args.cmd == "register-surface-asset":
        inputs = [Path(item) for item in args.input]
        print_json(
            cf.domains.surface_registration.register_surface_asset(
                input_path=inputs if args.surface == "feed_carousel" else inputs[0],
                surface=args.surface,
                creator=args.creator,
                campaign_slug=args.campaign,
                instagram_post_caption=args.instagram_post_caption,
                target_ratio=args.target_ratio,
                model_slug=args.model,
                operator=args.operator,
                story_asset_class=args.story_asset_class,
                story_cta_type=args.story_cta_type,
                story_cta_text=args.story_cta_text,
                story_cta_target_url=args.story_cta_target_url,
                story_intent=args.story_intent,
                story_goal=args.story_goal,
                story_style=args.story_style,
                snapchat_username=args.snapchat_username,
                snapchat_display_name=args.snapchat_display_name,
                snapchat_cta_text=args.snapchat_cta_text,
            )
        )
        return 0
    return None
