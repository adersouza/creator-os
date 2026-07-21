from __future__ import annotations

import hashlib
import json
from pathlib import Path

from campaign_asset_test_support import add_audit_report
from campaign_factory.adapters import threadsdash_client as threadsdash_client_adapter
from campaign_factory.core import CampaignFactory
from campaign_test_support import add_rendered_asset


def _slice_rows(rows, params):
    """Apply PostgREST-style limit/offset paging to a fake result set.

    Fakes that ignore ``offset`` return the same non-empty page forever, which
    the clamp-safe paginator (correctly) keeps reading until ``limit`` — so
    test fakes must honor paging params the way real PostgREST does.
    """
    offset = int(params.get("offset", "0"))
    limit = int(params.get("limit", str(len(rows))))
    return rows[offset : offset + limit]


def _approve_asset_for_lifecycle(cf: CampaignFactory, tmp_path: Path):
    source, _ = add_rendered_asset(cf, tmp_path)
    add_audit_report(cf)
    cf.domains.finished_video.review_rendered_asset("asset_1", decision="approved")
    return source


def _threadsdash_lifecycle_post(
    *,
    post_id: str = "post_1",
    status: str = "draft",
    scheduled_for: str | None = None,
    published_at: str | None = None,
    plan_id: str | None = None,
    rendered_asset_id: str = "asset_1",
    metadata_extra: dict | None = None,
) -> dict:
    rendered_hash = hashlib.sha256(b"rendered").hexdigest()
    campaign_factory = {
        "campaign_id": "may",
        "rendered_asset_id": rendered_asset_id,
        "asset_id": rendered_asset_id,
        "asset_state": "exportable",
        "platform_state": "platform_draft_validated",
        "content_hash": rendered_hash,
        "content_fingerprint": rendered_hash,
        "caption_hash": "caption_hash_1",
        "publishability_failure_reasons": [],
        "quarantined": False,
    }
    if plan_id:
        campaign_factory["distribution_plan_id"] = plan_id
        campaign_factory["handoff_manifest"] = {
            "manifest_version": 1,
            "asset_id": rendered_asset_id,
            "render_file_id": "render_file_lifecycle",
            "content_fingerprint": rendered_hash,
            "caption_hash": "caption_hash_1",
            "captionOutcomeContext": {
                "schema": "campaign_factory.caption_outcome_context.v1",
                "caption_hash": "caption_hash_1",
                "caption_text": "caption",
            },
            "visual_verification_id": "visual_verification_lifecycle",
            "caption_verification_id": "caption_verification_lifecycle",
            "audio_id": "audio_lifecycle",
            "distribution_plan_id": plan_id,
            "exported_by_system": "campaign_factory",
            "exported_at": "2026-01-01T00:00:00+00:00",
        }
    if metadata_extra:
        campaign_factory.update(metadata_extra)
    return {
        "id": post_id,
        "status": status,
        "scheduled_for": scheduled_for,
        "published_at": published_at,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "platform": "instagram",
        "instagram_account_id": "ig_1",
        "metadata": {"campaign_factory": campaign_factory},
    }


def _lifecycle_state(report: dict) -> str:
    assert len(report["rows"]) == 1
    return report["rows"][0]["currentState"]


def _manager_report_fixture(
    *, accounts: list[dict], missed: list[dict] | None = None
) -> dict:
    buckets = {
        "safe_to_schedule_today": [
            a for a in accounts if a.get("bucket") == "safe_to_schedule_today"
        ],
        "already_scheduled_today": [
            a for a in accounts if a.get("bucket") == "already_scheduled_today"
        ],
        "blocked_reauth": [a for a in accounts if a.get("bucket") == "blocked_reauth"],
        "blocked_token_expired": [
            a for a in accounts if a.get("bucket") == "blocked_token_expired"
        ],
        "blocked_disabled": [
            a for a in accounts if a.get("bucket") == "blocked_disabled"
        ],
        "blocked_recent_failure": [
            a for a in accounts if a.get("bucket") == "blocked_recent_failure"
        ],
        "blocked_unknown": [
            a for a in accounts if a.get("bucket") == "blocked_unknown"
        ],
    }
    return {
        "schema": "threadsdashboard.campaign_schedule_manager_report.v1",
        "accounts": accounts,
        "accountBuckets": buckets,
        "missedDispatches": missed or [],
        "summary": {
            "safeToScheduleCount": len(buckets["safe_to_schedule_today"]),
            "needsPostTodayCount": sum(1 for a in accounts if a.get("needsPostToday")),
            "blockedCount": sum(
                len(buckets[key]) for key in buckets if key.startswith("blocked_")
            ),
            "missedDispatchCount": len(missed or []),
        },
    }


def _draft_item(
    post_id: str,
    account_id: str,
    *,
    variant_family_id: str | None = None,
    variant_id: str | None = None,
    cooldown: str = "clear",
    instagram_post_caption: str | None = "new post is up",
    handoff_manifest_ok: bool | None = True,
    platform_draft_validated: bool | None = True,
    publishability_state: str | None = "exportable",
    quarantined: bool = False,
    scheduled_for: str = "2026-06-06T16:00:00+00:00",
    content_surface: str = "reel",
) -> dict:
    return {
        "postId": post_id,
        "accountId": account_id,
        "username": f"user_{account_id}",
        "creator": "Stacey",
        "renderedAssetId": f"asset_{post_id}",
        "distributionPlanId": f"dist_{post_id}",
        "variantFamilyId": variant_family_id,
        "variantId": variant_id,
        "platformDraftValidated": platform_draft_validated,
        "handoffManifestOk": handoff_manifest_ok,
        "publishabilityState": publishability_state,
        "quarantined": quarantined,
        "duplicateCheck": "clear",
        "variantCooldownCheck": cooldown,
        "qstashEligible": cooldown == "clear",
        "instagramPostCaption": instagram_post_caption,
        "scheduledFor": scheduled_for,
        "contentSurface": content_surface,
        "wouldWrite": False,
    }


def add_account_requirement_fixture(
    cf: CampaignFactory,
    *,
    account_id: str,
    creator: str = "Stacey",
    surface: str,
    cadence: str = "daily",
    max_per_day: int = 1,
    allowed_days: list[int] | None = None,
):
    cf.conn.execute(
        """
        INSERT INTO account_content_requirements
        (id, account_id, creator, content_surface, cadence, max_per_day, min_gap_hours,
         allowed_days, active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, 1,
                '2026-06-06T00:00:00+00:00', '2026-06-06T00:00:00+00:00')
        """,
        (
            f"req_{account_id}_{surface}",
            account_id,
            creator,
            surface,
            cadence,
            max_per_day,
            json.dumps(allowed_days or []),
        ),
    )


def _insert_creative_kb_snapshot(
    cf: CampaignFactory,
    *,
    snapshot_id: str,
    campaign_id: str,
    post_id: str,
    creator: str = "Stacey",
    campaign_asset_id: str = "",
    source_asset_id: str = "",
    concept_id: str = "",
    parent_reel_id: str = "",
    variant_family_id: str = "",
    variant_id: str = "",
    caption_angle: str = "",
    caption_hash: str = "",
    caption_family_id: str = "",
    caption_version_id: str = "",
    instagram_post_caption_hash: str = "",
    audio_id: str = "",
    content_surface: str = "reel",
    ig_media_type: str = "REELS",
    account_id: str = "",
    instagram_account_id: str = "",
    account_username: str = "",
    account_tier: str = "",
    story_intent: str = "",
    story_style: str = "",
    story_goal: str = "",
    published_at: str = "2026-06-06T18:00:00+00:00",
    views: int = 0,
    reach: int = 0,
    saves: int = 0,
    shares: int = 0,
    followers: int = 0,
    profile_visits: int = 0,
) -> None:
    raw = {
        "followers": followers,
        "profile_visits": profile_visits,
        "instagram_post_caption_hash": instagram_post_caption_hash,
        "ig_media_type": ig_media_type,
        "account_username": account_username,
        "account_tier": account_tier,
        "story_intent": story_intent,
        "story_style": story_style,
        "story_goal": story_goal,
        "metric_contract": {
            "version": "instagram_metrics_contract_v1",
            "surface": content_surface,
            "metricNames": [
                "views",
                "reach",
                "likes",
                "comments",
                "shares",
                "saves",
                "followers",
                "profile_visits",
            ],
        },
    }
    context = {
        "caption_angle": caption_angle,
        "caption_family_id": caption_family_id,
        "caption_version_id": caption_version_id,
        "instagram_post_caption_hash": instagram_post_caption_hash,
        "storyIntent": story_intent,
        "storyStyle": story_style,
        "storyGoal": story_goal,
    }
    cf.conn.execute(
        """
        INSERT INTO performance_snapshots
        (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
         caption_hash, caption_text, creator_mix, caption_outcome_context_json, concept_id,
         parent_reel_id, variant_family_id, variant_id, audio_id, recipe, post_id, platform,
         content_surface, status, account_id, instagram_account_id, published_at, snapshot_at,
         views, likes, comments, shares, saves, impressions, reach, watch_time_seconds,
         metrics_eligible, raw_json, created_at, history_source, lineage_v2_valid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'recipe_1', ?, 'instagram',
         ?, 'published', ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, 0, 1, ?, ?, 'metric_history', 1)
        """,
        (
            snapshot_id,
            campaign_id,
            campaign_asset_id or f"asset_{snapshot_id}",
            source_asset_id or f"source_{snapshot_id}",
            f"hash_{snapshot_id}",
            f"source_hash_{snapshot_id}",
            caption_hash,
            "caption text",
            creator,
            json.dumps(context),
            concept_id,
            parent_reel_id,
            variant_family_id,
            variant_id,
            audio_id,
            post_id,
            content_surface,
            account_id,
            instagram_account_id,
            published_at,
            published_at,
            views,
            shares,
            saves,
            reach,
            reach,
            json.dumps(raw),
            published_at,
        ),
    )


def threadsdash_campaign_factory_metadata(
    source: dict,
    *,
    rendered_asset_id: str = "asset_1",
    content_hash: str | None = None,
    caption_hash: str = "caption_hash_1",
    recipe: str = "v01_original",
    context: dict | None = None,
) -> dict:
    content_hash = content_hash or hashlib.sha256(b"rendered").hexdigest()
    context = context or {
        "schema": "campaign_factory.caption_outcome_context.v1",
        "caption_hash": caption_hash,
        "caption_text": "caption",
        "caption_bank": "test_bank",
        "caption_banks": ["test_bank"],
        "creator_mix": "Test",
        "render_recipe": recipe,
    }
    return {
        "campaign_id": "may",
        "source_asset_id": source["id"],
        "rendered_asset_id": rendered_asset_id,
        "asset_id": rendered_asset_id,
        "asset_state": "exportable",
        "platform_state": "platform_draft_validated",
        "content_hash": content_hash,
        "content_fingerprint": content_hash,
        "source_content_hash": source["content_hash"],
        "caption_hash": caption_hash,
        "recipe": recipe,
        "captionOutcomeContext": context,
        "caption_outcome_context": context,
        "generated_asset_lineage": {
            "schema": "reel_factory.generated_asset_lineage.v2",
            "pipelineTraceId": "trace_threadsdash_test_001",
            "campaignId": "may",
            "recipeId": recipe,
            "captionHash": caption_hash,
            "renderedAssetId": rendered_asset_id,
            "contentFingerprint": content_hash,
            "variationApplied": False,
            "variantId": None,
            "audioIntentFingerprint": threadsdash_client_adapter._text_hash(
                "audio_intent"
            ),
            "audioId": None,
            "source": {
                "promptId": "prompt_test_001",
                "referenceId": "reference_test_001",
            },
            "generation": {"tool": "manual_finished_video"},
            "review": {"humanReviewRequired": True, "status": "approved"},
        },
        "publishability_failure_reasons": [],
        "quarantined": False,
        "lineage_v2_valid": 1,
        "handoff_manifest": {
            "manifest_version": 1,
            "asset_id": rendered_asset_id,
            "render_file_id": "render_file_test",
            "content_fingerprint": content_hash,
            "caption_hash": caption_hash,
            "captionOutcomeContext": context,
            "visual_verification_id": "visual_verification_test",
            "caption_verification_id": "caption_verification_test",
            "audio_id": "audio_test",
            "distribution_plan_id": "dist_test",
            "exported_by_system": "campaign_factory",
            "exported_at": "2026-01-02T00:00:00+00:00",
        },
    }
