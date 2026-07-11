from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from creator_os_core.local_api_auth import (
    install_local_api_auth_middleware,
    require_local_api_auth,
)
from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .adapters.contentforge import audit_campaign
from .adapters.threadsdash import (
    clear_preview_schedule,
    evaluate_export_readiness,
    export_threadsdash,
    preflight_supabase,
    promote_preview_schedule,
    safe_live_smoke_export,
    summarize_threadsdash_usage,
    sync_performance_snapshots,
    sync_threadsdash_account_assignments,
    verify_threadsdash_export,
)
from .config import get_settings
from .core import CampaignFactory

settings = get_settings()
app = FastAPI(title="campaign_factory", dependencies=[Depends(require_local_api_auth)])
install_local_api_auth_middleware(app)
app.mount(
    "/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static"
)


def factory() -> CampaignFactory:
    return CampaignFactory(settings)


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.api_route("/favicon.ico", methods=["GET", "HEAD"])
def favicon():
    return FileResponse(Path(__file__).parent / "static" / "favicon.ico")


@app.get("/api/dashboard")
def dashboard(campaign: str | None = None):
    cf = factory()
    try:
        return cf.dashboard(campaign)
    finally:
        cf.close()


@app.get("/api/campaign-health")
def campaign_health(campaign: str):
    cf = factory()
    try:
        return cf.campaign_health(campaign)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/asset-detail/{rendered_asset_id}")
def asset_detail(rendered_asset_id: str):
    cf = factory()
    try:
        return cf.asset_detail(rendered_asset_id)
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/campaign-readiness")
def campaign_readiness(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.campaign_readiness(body["campaign"], user_id=body.get("userId"))
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/asset-account-assignment")
def asset_account_assignment(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.assign_asset_account(
            body["renderedAssetId"],
            account_id=body.get("accountId"),
            instagram_account_id=body.get("instagramAccountId"),
            planned_window_start=body.get("plannedWindowStart"),
            planned_window_end=body.get("plannedWindowEnd"),
            notes=body.get("notes"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/account-plan")
def account_plan(campaign: str, userId: str):
    cf = factory()
    try:
        usage = None
        supabase_url = os.environ.get("SUPABASE_URL")
        service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if supabase_url and service_key:
            usage = summarize_threadsdash_usage(
                cf,
                campaign_slug=campaign,
                user_id=userId,
                supabase_url=supabase_url,
                supabase_service_role_key=service_key,
            )
        return cf.account_plan(campaign, user_id=userId, usage=usage)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/model-account-profile")
def model_account_profile(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.upsert_model_account_profile(
            body["model"],
            label=body.get("label"),
            allowed_instagram_account_ids=body.get("allowedInstagramAccountIds") or [],
            allowed_account_group_names=body.get("allowedAccountGroupNames") or [],
            allowed_handle_patterns=body.get("allowedHandlePatterns") or [],
            default_smart_link=body.get("defaultSmartLink"),
            story_cta_text=body.get("storyCtaText"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/distribution-plan")
def distribution_plan(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.create_distribution_plan(
            body["renderedAssetId"],
            surface=body.get("surface") or "regular_reel",
            account_id=body.get("accountId"),
            instagram_account_id=body.get("instagramAccountId"),
            planned_window_start=body.get("plannedWindowStart"),
            planned_window_end=body.get("plannedWindowEnd"),
            paired_rendered_asset_id=body.get("pairedRenderedAssetId"),
            reason_code=body.get("reasonCode"),
            smart_link=body.get("smartLink"),
            cta_text=body.get("ctaText"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/plan-distribution")
def plan_distribution(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.plan_distribution(
            body["campaign"],
            user_id=body["userId"],
            mode=body.get("mode") or "preview",
            strategy=body.get("strategy") or "trial-heavy",
            replace=body.get("replace", True) is not False,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/promote-preview-schedule")
def promote_preview(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return promote_preview_schedule(
            cf,
            campaign_slug=body["campaign"],
            user_id=body["userId"],
            supabase_url=body.get("supabaseUrl") or os.environ.get("SUPABASE_URL"),
            supabase_service_role_key=body.get("supabaseServiceRoleKey")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
            limit=int(body.get("limit") or 1000),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/clear-preview-schedule")
def clear_preview(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return clear_preview_schedule(
            cf,
            campaign_slug=body["campaign"],
            user_id=body["userId"],
            supabase_url=body.get("supabaseUrl") or os.environ.get("SUPABASE_URL"),
            supabase_service_role_key=body.get("supabaseServiceRoleKey")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
            limit=int(body.get("limit") or 1000),
            reason=body.get("reason") or "audio_workflow_not_ready",
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/ranking")
def ranking(campaign: str):
    cf = factory()
    try:
        return cf.ranking(campaign)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/autonomy-policy")
def autonomy_policy():
    cf = factory()
    try:
        return cf.autonomy_policy()
    finally:
        cf.close()


@app.post("/api/autonomy-policy")
def set_autonomy_policy(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.set_autonomy_level(body["level"])
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/trust-summary")
def trust_summary(campaign: str):
    cf = factory()
    try:
        return cf.trust_summary(campaign)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/recommendations/run")
def run_recommendations(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.recommend_next_batch(
            body["campaign"],
            count=int(body.get("count") or 20),
            account=body.get("account"),
            persist=bool(body.get("persist", True)),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/recommendations")
def recommendations(campaign: str, limit: int = 10):
    cf = factory()
    try:
        return cf.recommendation_runs(campaign, limit=limit)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/recommendations/accuracy")
def recommendation_accuracy(
    campaign: str, account: str | None = None, windowDays: int = 30
):
    cf = factory()
    try:
        return cf.recommendation_accuracy(
            campaign, account=account, window_days=windowDays, persist=True
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/recommendations/accuracy/rebuild")
def rebuild_recommendation_accuracy(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.rebuild_recommendation_accuracy(
            body["campaign"],
            account=body.get("account"),
            window_days=int(body.get("windowDays") or body.get("window_days") or 30),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/recommendations/{recommendation_item_id}/accept")
def accept_recommendation(
    recommendation_item_id: str, body: dict[str, Any] = Body(default={})
):
    cf = factory()
    try:
        return cf.accept_recommendation_item(
            recommendation_item_id,
            operator=body.get("operator"),
            notes=body.get("notes"),
            admin_override=bool(body.get("adminOverride")),
            override_reason=body.get("overrideReason"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/recommendations/{recommendation_item_id}/reject")
def reject_recommendation(
    recommendation_item_id: str, body: dict[str, Any] = Body(default={})
):
    cf = factory()
    try:
        return cf.reject_recommendation_item(
            recommendation_item_id,
            reason=body.get("reason"),
            operator=body.get("operator"),
            notes=body.get("notes"),
            admin_override=bool(body.get("adminOverride")),
            override_reason=body.get("overrideReason"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/recommendations/{recommendation_item_id}/link")
def link_recommendation(recommendation_item_id: str, body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.link_recommendation_item(
            recommendation_item_id,
            source_asset_id=body.get("sourceAssetId"),
            render_job_id=body.get("renderJobId"),
            rendered_asset_id=body.get("renderedAssetId"),
            post_id=body.get("postId"),
            performance_snapshot_id=body.get("performanceSnapshotId"),
            evidence=body.get("evidence")
            if isinstance(body.get("evidence"), dict)
            else None,
            admin_override=bool(body.get("adminOverride")),
            override_reason=body.get("overrideReason"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/recommendations/{recommendation_item_id}/measure")
def measure_recommendation(
    recommendation_item_id: str, body: dict[str, Any] = Body(default={})
):
    cf = factory()
    try:
        return cf.measure_recommendation_item(
            recommendation_item_id,
            performance_snapshot_id=body.get("performanceSnapshotId"),
            admin_override=bool(body.get("adminOverride")),
            override_reason=body.get("overrideReason"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/recommendations/{recommendation_item_id}/execute")
def execute_recommendation(
    recommendation_item_id: str, body: dict[str, Any] = Body(default={})
):
    cf = factory()
    try:
        return cf.execute_accepted_recommendation(
            recommendation_item_id,
            mode=body.get("mode") or "level_2",
            force=bool(body.get("force", False)),
            dry_run_render=bool(body.get("dryRunRender")),
            run_audit=bool(body.get("runAudit", True)),
            contentforge_base_url=body.get("contentforgeBaseUrl"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/account-memory")
def account_memory(campaign: str, account: str | None = None):
    cf = factory()
    try:
        return cf.account_memory(campaign, account=account)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/account-memory/rebuild")
def rebuild_account_memory(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.rebuild_account_memory(body["campaign"])
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/exceptions")
def exceptions(campaign: str | None = None, status: str = "open"):
    cf = factory()
    try:
        return cf.exceptions(campaign, status=status)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/exceptions/{exception_id}/resolve")
def resolve_exception(exception_id: str, body: dict[str, Any] = Body(default={})):
    cf = factory()
    try:
        return cf.resolve_exception(
            exception_id,
            resolution=body.get("resolution"),
            operator=body.get("operator"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/exceptions/{exception_id}/snooze")
def snooze_exception(exception_id: str, body: dict[str, Any] = Body(default={})):
    cf = factory()
    try:
        return cf.snooze_exception(
            exception_id,
            until=body.get("until"),
            reason=body.get("reason"),
            operator=body.get("operator"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/exceptions/{exception_id}/reopen")
def reopen_exception(exception_id: str, body: dict[str, Any] = Body(default={})):
    cf = factory()
    try:
        return cf.reopen_exception(
            exception_id, reason=body.get("reason"), operator=body.get("operator")
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/import-reference-bank")
def import_reference_bank(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        default_bank = (
            settings.reference_reels_root / "learning" / "campaign_reference_bank.json"
        )
        return cf.import_reference_bank(
            Path(body.get("path") or default_bank),
            Path(body["promptPack"]) if body.get("promptPack") else None,
            dry_run=bool(body.get("dryRun", True)),
            campaign_slug=body.get("campaign"),
            require_local_paths=bool(body.get("requireLocalPaths", False)),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/import-audio-catalog")
def import_audio_catalog(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.import_audio_catalog(Path(body["path"]))
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/import-audio-memory")
def import_audio_memory(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.import_audio_memory(Path(body["path"]))
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/audio-catalog")
def audio_catalog(platform: str | None = None, limit: int = 100):
    cf = factory()
    try:
        return cf.audio_catalog(platform=platform, limit=limit)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/audio-memory")
def audio_memory(
    platform: str | None = None, account: str | None = None, limit: int = 100
):
    cf = factory()
    try:
        return cf.audio_memory(platform=platform, account=account, limit=limit)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/audio/recommend")
def recommend_audio(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.recommend_audio(
            platform=body.get("platform") or "instagram",
            campaign_slug=body.get("campaign"),
            recommendation_item_id=body.get("recommendationItemId"),
            account=body.get("account"),
            content_tags=body.get("contentTags") or [],
            account_tags=body.get("accountTags") or [],
            limit=int(body.get("count") or body.get("limit") or 5),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/audio/decide")
def decide_audio(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.decide_audio(
            platform=body.get("platform") or "instagram",
            campaign_slug=body.get("campaign"),
            recommendation_item_id=body.get("recommendationItemId"),
            account=body.get("account"),
            content_tags=body.get("contentTags") or [],
            account_tags=body.get("accountTags") or [],
            limit=int(body.get("count") or body.get("limit") or 5),
            select=bool(body.get("select")),
            operator=body.get("operator"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/audio/select")
def select_audio(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.select_audio_for_recommendation(
            body["recommendationItemId"],
            body["audioId"],
            operator=body.get("operator"),
            notes=body.get("notes"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/audio/verify")
def verify_audio(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.verify_audio_for_post(
            body["postId"],
            proof_url=body["proofUrl"],
            proof_note=body.get("proofNote"),
            operator=body.get("operator"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/reference-patterns")
def reference_patterns(limit: int = 50):
    cf = factory()
    try:
        return cf.reference_patterns(limit)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/select-reference-pattern")
def select_reference_pattern(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.select_reference_pattern(
            body["campaign"],
            cluster_key=body.get("clusterKey"),
            reference_pattern_id=body.get("referencePatternId"),
            variant_count=int(body.get("variantCount") or 5),
            notes=body.get("notes"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/reference-plan")
def reference_plan(campaign: str):
    cf = factory()
    try:
        return cf.campaign_reference_plan(campaign)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/prepare-from-reference")
def prepare_from_reference(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.prepare_reel_from_reference(
            campaign_slug=body["campaign"],
            cluster_key=body.get("clusterKey"),
            reference_pattern_id=body.get("referencePatternId"),
            variant_count=int(body.get("variantCount") or 5),
            recipes=body.get("recipes") or None,
            caption_color=body.get("captionColor") or "auto",
            notes=body.get("notes"),
            force_new=bool(body.get("forceNew", True)),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/make-batch")
def make_batch(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.make_batch(
            folder=Path(body["folder"]),
            campaign_slug=body["campaign"],
            model_slug=body["model"],
            output_format=body.get("format") or body.get("outputFormat") or "auto",
            variant_count=int(body.get("variantCount") or 20),
            reference_pattern=body.get("referencePattern") or "auto",
            contentforge_base_url=body.get("contentforgeBaseUrl")
            or settings.contentforge_base_url,
            user_id=body.get("userId"),
            dry_run_export=bool(body.get("dryRunExport", True)),
            workers=int(body.get("workers") or 3),
            recipes=body.get("recipes") or None,
            auto_approve_warning_only=bool(body.get("autoApproveWarningOnly", True)),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/intake-finished-video")
def intake_finished_video(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.intake_finished_video(
            input_path=Path(body["input"]),
            model_slug=body["model"],
            platform=body.get("platform") or "instagram",
            goal=body.get("goal") or "reach",
            reference_pattern=body.get("referencePattern") or "auto",
            campaign_slug=body.get("campaign"),
            contentforge_base_url=body.get("contentforgeBaseUrl")
            or settings.contentforge_base_url,
            user_id=body.get("userId"),
            dry_run_export=bool(body.get("dryRunExport", True)),
            variant_count=int(body.get("variantCount") or 10),
            workers=int(body.get("workers") or 3),
            recipes=body.get("recipes") or None,
            creative_plan=body.get("creativePlan") or body.get("creative_plan"),
            style_lane=body.get("styleLane") or body.get("style_lane"),
            source_lineage_path=Path(body["sourceLineage"])
            if body.get("sourceLineage")
            else None,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/batch-summary")
def batch_summary(campaign: str):
    cf = factory()
    try:
        return cf.batch_summary(campaign)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/create-creative-plan")
def create_creative_plan(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.create_creative_plan(
            name=body.get("name") or "daily_plan",
            platform=body.get("platform") or "instagram",
            target_account=body.get("targetAccount")
            or body.get("target_account")
            or "",
            daily_base_video_target=int(
                body.get("dailyBaseVideoTarget")
                or body.get("daily_base_video_target")
                or 10
            ),
            style_lanes=body.get("styleLanes") or body.get("style_lanes") or None,
            model_profile=body.get("modelProfile") or body.get("model_profile") or "",
            source_accounts=body.get("sourceAccounts")
            or body.get("source_accounts")
            or [],
            goal=body.get("goal") or "views_reach",
            linked_campaign=body.get("linkedCampaign") or body.get("linked_campaign"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/creative-plan")
def creative_plan(name: str):
    cf = factory()
    try:
        return cf.creative_plan(name)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/update-creative-plan-status")
def update_creative_plan_status(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.update_creative_plan_status(
            name=body.get("name") or "", status=body.get("status") or ""
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/sync-creative-plan-progress")
def sync_creative_plan_progress(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.sync_creative_plan_progress(
            name=body.get("name") or "",
            prompt_export_path=Path(
                body.get("promptExport") or body.get("prompt_export") or ""
            ),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/activity-log")
def activity_log(campaign: str, limit: int = 200):
    cf = factory()
    try:
        return {
            "schema": "campaign_factory.activity_log.v1",
            "campaign": campaign,
            "events": cf.events_for_campaign(campaign, limit=limit),
        }
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/jobs")
def jobs(campaign: str | None = None, limit: int = 100, stuck_hours: float = 24.0):
    cf = factory()
    try:
        rows = cf.jobs_for_campaign(campaign, limit=limit, stuck_hours=stuck_hours)
        return {
            "schema": "campaign_factory.jobs.v1",
            "campaign": campaign,
            "stuckHours": stuck_hours,
            "summary": {
                "failed": sum(1 for job in rows if job.get("status") == "failed"),
                "stuck": sum(1 for job in rows if job.get("stuck")),
            },
            "jobs": rows,
        }
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    cf = factory()
    try:
        return cf.pipeline_job(job_id)
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/rendered/{rendered_asset_id}/media")
def rendered_media(rendered_asset_id: str):
    cf = factory()
    try:
        asset = cf.rendered_asset(rendered_asset_id)
        path = Path(asset["campaign_path"])
        if not path.exists():
            raise HTTPException(404, f"rendered media not found: {rendered_asset_id}")
        return FileResponse(path)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/rendered/{rendered_asset_id}/poster.jpg")
def rendered_poster(rendered_asset_id: str):
    cf = factory()
    try:
        asset = cf.rendered_asset(rendered_asset_id)
        media_path = Path(asset["campaign_path"])
        if not media_path.exists():
            raise HTTPException(404, f"rendered media not found: {rendered_asset_id}")
        cache_dir = settings.root / ".cache" / "posters"
        cache_dir.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(
            ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in rendered_asset_id
        )
        poster_path = cache_dir / f"{safe_id}_{int(media_path.stat().st_mtime)}.jpg"
        if not poster_path.exists():
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    "1",
                    "-i",
                    str(media_path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=360:-1",
                    "-q:v",
                    "3",
                    "-y",
                    str(poster_path),
                ],
                check=True,
                timeout=20,
            )
        return FileResponse(poster_path, media_type="image/jpeg")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(404, f"poster unavailable: {exc}") from exc
    finally:
        cf.close()


@app.get("/api/audit-report/{audit_report_id}")
def audit_report(audit_report_id: str):
    cf = factory()
    try:
        return cf.audit_report(audit_report_id)
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/import-folder")
def import_folder(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.import_folder(
            Path(body["folder"]),
            campaign_slug=body["campaign"],
            model_slug=body["model"],
            model_name=body.get("modelName"),
            platform=body.get("platform", "instagram"),
            account_handles=body.get("accounts") or [],
            source_prompt=body.get("sourcePrompt"),
            notes=body.get("notes"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/prepare-reel")
def prepare_reel(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        hooks = body.get("hooks")
        if isinstance(hooks, str):
            hooks = [h.strip() for h in hooks.splitlines() if h.strip()]
        return cf.prepare_reel_inputs(
            campaign_slug=body["campaign"],
            hooks=hooks or [],
            recipes=body.get("recipes") or None,
            caption_color=body.get("captionColor"),
            notes=body.get("notes"),
            force_new=bool(body.get("forceNew", False)),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/run-reel")
def run_reel(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.run_reel_factory(
            campaign_slug=body["campaign"],
            workers=int(body.get("workers") or 3),
            dry_run=bool(body.get("dryRun")),
            caption_band=body.get("captionBand") or "center",
            caption_color=body.get("captionColor") or "light",
            caption_style=body.get("captionStyle") or "ig",
            caption_font=body.get("captionFont") or "Instagram Sans Condensed",
            phone_finalize=bool(body.get("phoneFinalize", True)),
            rerender_all=bool(body.get("rerenderAll", False)),
            max_outputs_per_clip=body.get("maxOutputsPerClip"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/sync-reel")
def sync_reel(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.sync_reel_outputs(campaign_slug=body["campaign"])
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/audit")
def audit(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return audit_campaign(
            cf,
            campaign_slug=body["campaign"],
            min_score=int(body.get("minScore") or 85),
            contentforge_base_url=body.get("contentforgeBaseUrl")
            or settings.contentforge_base_url,
            layers=body.get("layers") or None,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/approve")
def approve(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.approve_rendered_asset(
            body["renderedAssetId"],
            notes=body.get("notes"),
            require_safe_audit=not bool(body.get("forceUnsafeAudit")),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/review-decision")
def review_decision(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return cf.review_rendered_asset(
            body["renderedAssetId"],
            decision=body["decision"],
            notes=body.get("notes"),
            require_safe_audit=not bool(body.get("forceUnsafeAudit")),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/export-readiness")
def export_readiness(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return evaluate_export_readiness(
            cf,
            campaign_slug=body["campaign"],
            user_id=body["userId"],
            supabase_url=body.get("supabaseUrl") or os.environ.get("SUPABASE_URL"),
            supabase_service_role_key=body.get("supabaseServiceRoleKey")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
            limit=int(body.get("limit") or 1000),
            content_pillar=body.get("contentPillar"),
            cta_type=body.get("ctaType"),
            language=body.get("language"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/export-threadsdash")
def export_td(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return export_threadsdash(
            cf,
            campaign_slug=body["campaign"],
            user_id=body["userId"],
            dry_run=body.get("dryRun", True),
            supabase_url=body.get("supabaseUrl") or os.environ.get("SUPABASE_URL"),
            supabase_service_role_key=body.get("supabaseServiceRoleKey")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
            supabase_storage_bucket=body.get("supabaseStorageBucket")
            or os.environ.get("SUPABASE_STORAGE_BUCKET", "media"),
            allow_warnings=bool(body.get("allowWarnings")),
            content_pillar=body.get("contentPillar"),
            cta_type=body.get("ctaType"),
            language=body.get("language"),
            max_drafts=int(body["maxDrafts"])
            if body.get("maxDrafts") is not None
            else None,
            rendered_asset_ids=body.get("renderedAssetIds") or None,
            schedule_mode=body.get("scheduleMode") or "draft",
            threadsdash_ingest_url=body.get("threadsdashIngestUrl")
            or os.environ.get("THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL")
            or os.environ.get("CAMPAIGN_FACTORY_DRAFT_INGEST_URL"),
            threadsdash_ingest_secret=body.get("threadsdashIngestSecret")
            or os.environ.get("CAMPAIGN_FACTORY_INGEST_SECRET"),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/threadsdash-usage")
def threadsdash_usage(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return summarize_threadsdash_usage(
            cf,
            campaign_slug=body["campaign"],
            user_id=body["userId"],
            supabase_url=body.get("supabaseUrl") or os.environ.get("SUPABASE_URL"),
            supabase_service_role_key=body.get("supabaseServiceRoleKey")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
            limit=int(body.get("limit") or 1000),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/sync-threadsdash-assignments")
def sync_threadsdash_assignments(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return sync_threadsdash_account_assignments(
            cf,
            campaign_slug=body["campaign"],
            user_id=body["userId"],
            supabase_url=body.get("supabaseUrl") or os.environ.get("SUPABASE_URL"),
            supabase_service_role_key=body.get("supabaseServiceRoleKey")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
            limit=int(body.get("limit") or 1000),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/supabase-preflight")
def supabase_preflight(body: dict[str, Any] = Body(...)):
    cf = factory()
    pipeline_job = cf.create_pipeline_job(
        "supabase_preflight",
        None,
        {
            "hasSupabaseUrl": bool(
                body.get("supabaseUrl") or os.environ.get("SUPABASE_URL")
            ),
            "hasSupabaseServiceRoleKey": bool(
                body.get("supabaseServiceRoleKey")
                or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            ),
            "supabaseStorageBucket": body.get("supabaseStorageBucket")
            or os.environ.get("SUPABASE_STORAGE_BUCKET", "media"),
        },
    )
    cf.start_pipeline_job(pipeline_job["id"])
    try:
        result = preflight_supabase(
            supabase_url=body.get("supabaseUrl") or os.environ.get("SUPABASE_URL"),
            supabase_service_role_key=body.get("supabaseServiceRoleKey")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
            supabase_storage_bucket=body.get("supabaseStorageBucket")
            or os.environ.get("SUPABASE_STORAGE_BUCKET", "media"),
        )
        result["pipelineJobId"] = pipeline_job["id"]
        cf.record_event(
            "supabase_preflight_checked",
            pipeline_job_id=pipeline_job["id"],
            status="success" if result["ok"] else "failure",
            message=f"Supabase preflight {'passed' if result['ok'] else 'failed'}",
            metadata={
                "ok": result["ok"],
                "blockingReasons": result.get("blockingReasons") or [],
            },
        )
        if result["ok"]:
            cf.finish_pipeline_job(
                pipeline_job["id"],
                {
                    "ok": result["ok"],
                    "blockingReasons": result.get("blockingReasons") or [],
                },
            )
        else:
            cf.fail_pipeline_job(
                pipeline_job["id"],
                "Supabase preflight failed",
                {
                    "ok": result["ok"],
                    "blockingReasons": result.get("blockingReasons") or [],
                },
            )
        return result
    except Exception as exc:
        cf.record_event(
            "supabase_preflight_checked",
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"Supabase preflight failed: {exc}",
            metadata={"error": str(exc)},
        )
        cf.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/verify-threadsdash-export")
def verify_td_export(body: dict[str, Any] = Body(...)):
    cf = factory()
    pipeline_job = cf.create_pipeline_job(
        "verify_threadsdash_export",
        None,
        {
            "hasExportResult": bool(body.get("exportResult")),
            "exportPath": body.get("exportPath"),
        },
    )
    cf.start_pipeline_job(pipeline_job["id"])
    try:
        export_value = body.get("exportResult") or body.get("exportPath")
        if not export_value:
            raise ValueError("exportResult or exportPath is required")
        result = verify_threadsdash_export(
            export_result_or_path=export_value,
            supabase_url=body.get("supabaseUrl") or os.environ.get("SUPABASE_URL"),
            supabase_service_role_key=body.get("supabaseServiceRoleKey")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
        result["pipelineJobId"] = pipeline_job["id"]
        cf.record_event(
            "threadsdash_export_verified",
            pipeline_job_id=pipeline_job["id"],
            status="success" if result["ok"] else "failure",
            message=f"ThreadsDash export {'verified' if result['ok'] else 'verification failed'}",
            metadata={
                "ok": result["ok"],
                "campaign": result.get("campaign"),
                "exportPath": result.get("exportPath"),
                "blockingReasons": result.get("blockingReasons") or [],
            },
        )
        if result["ok"]:
            cf.finish_pipeline_job(
                pipeline_job["id"],
                {
                    "ok": result["ok"],
                    "campaign": result.get("campaign"),
                    "blockingReasons": result.get("blockingReasons") or [],
                },
            )
        else:
            cf.fail_pipeline_job(
                pipeline_job["id"],
                "ThreadsDash export verification failed",
                {
                    "ok": result["ok"],
                    "campaign": result.get("campaign"),
                    "blockingReasons": result.get("blockingReasons") or [],
                },
            )
        return result
    except Exception as exc:
        cf.record_event(
            "threadsdash_export_verified",
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"ThreadsDash export verification failed: {exc}",
            metadata={"error": str(exc)},
        )
        cf.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/safe-live-smoke")
def safe_live_smoke(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return safe_live_smoke_export(
            cf,
            campaign_slug=body["campaign"],
            user_id=body["userId"],
            supabase_url=body.get("supabaseUrl") or os.environ.get("SUPABASE_URL"),
            supabase_service_role_key=body.get("supabaseServiceRoleKey")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
            supabase_storage_bucket=body.get("supabaseStorageBucket")
            or os.environ.get("SUPABASE_STORAGE_BUCKET", "media"),
            allow_warnings=bool(body.get("allowWarnings")),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.post("/api/sync-performance")
def sync_performance(body: dict[str, Any] = Body(...)):
    cf = factory()
    try:
        return sync_performance_snapshots(
            cf,
            campaign_slug=body["campaign"],
            user_id=body["userId"],
            supabase_url=body.get("supabaseUrl") or os.environ.get("SUPABASE_URL"),
            supabase_service_role_key=body.get("supabaseServiceRoleKey")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
            limit=int(body.get("limit") or 1000),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()


@app.get("/api/performance-summary")
def performance_summary(campaign: str):
    cf = factory()
    try:
        return cf.performance_summary(campaign)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        cf.close()
