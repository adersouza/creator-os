from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from pipeline_contracts import evaluate_overlay_semantic_completeness

from ..caption_outcome import (
    build_caption_outcome_context,
)
from ..core import (
    CampaignFactory,
    _normalize_distribution_surface,
    _normalize_schedule_mode,
    normalize_content_surface,
    utc_now,
)
from ..lineage_v2 import (
    finalize_lineage_v2,
    lineage_v2_is_valid,
)
from .threadsdash_draft_integrity import (
    asset_caption_is_burned,
    exported_content_hash,
    learning_cohort_metadata,
    verify_rendered_media_asset,
    with_content_fingerprint,
)
from .threadsdash_draft_integrity import (
    caption_timing_qc as resolve_caption_timing_qc,
)

VALID_PUBLISH_MODES = {"auto", "notify"}
SAFE_NATIVE_AUDIO_STATUSES = {"attached", "verified", "skipped", "not_required"}
UNRESOLVED_NATIVE_AUDIO_STATUSES = {
    "recommended",
    "needs_operator_selection",
    "selected",
    "blocked",
}
DEFERRED_NOTIFY_AUDIO_FAILURES = {"missing_audio", "embedded_audio_missing"}
METRIC_CONTRACT_VERSION = "instagram_metrics_contract_v1"
DASHBOARD_INGEST_MAX_ATTEMPTS = 3
DASHBOARD_INGEST_BACKOFF_SECONDS = (1.0, 3.0)
THREADSDASH_INGEST_PATH = "/api/campaign-factory/drafts/ingest"
DEFAULT_THREADSDASH_INGEST_HOSTS = frozenset({"juno33.com", "www.juno33.com"})
POST_METRIC_HISTORY_POST_ID_BATCH_SIZE = 5
_STDLIB_URLOPEN = urlopen

from .threadsdash_client import (
    _text_hash,
)
from .threadsdash_draft_destinations import (
    draft_destinations_for_asset as _draft_destinations_for_asset,
)


def build_draft_payloads(
    factory: CampaignFactory,
    *,
    campaign_slug: str,
    user_id: str,
    export_id: str | None = None,
    content_pillar: str | None = None,
    cta_type: str | None = None,
    language: str | None = None,
    rendered_asset_ids: list[str] | None = None,
    surface: str | None = None,
    schedule_mode: str = "draft",
    enable_variation: bool = False,
    publish_mode: str | None = None,
    review_only: bool = False,
) -> dict[str, Any]:
    if review_only and _normalize_schedule_mode(schedule_mode) != "draft":
        raise ValueError("review-only handoff requires schedule_mode='draft'")
    manifest = factory.domains.export_summary.export_manifest(
        campaign_slug=campaign_slug, review_only=review_only
    )
    normalized_publish_mode = _normalize_publish_mode(publish_mode)
    normalized_schedule_mode = _normalize_schedule_mode(schedule_mode)
    normalized_surface = (
        _normalize_distribution_surface(surface) if surface is not None else None
    )
    variation_index: dict[str, dict[str, Any]] = {}
    if enable_variation:
        from ..variation_stage import load_variant_assignment_index

        variation_index = load_variant_assignment_index(
            factory, campaign_slug=campaign_slug
        )
    distribution_plans_by_asset: dict[str, list[dict[str, Any]]] = {}
    require_distribution_plan = False
    if normalized_schedule_mode in {"preview", "live"}:
        distribution_plans = (
            factory.domains.distribution.distribution_plans_for_campaign(campaign_slug)
        )
        require_distribution_plan = bool(distribution_plans)
        for plan in distribution_plans:
            distribution_plans_by_asset.setdefault(plan["renderedAssetId"], []).append(
                plan
            )
    selected_ids = set(rendered_asset_ids or [])
    if selected_ids:
        manifest_assets = list(manifest.get("assets") or [])
        available_ids = {
            str(asset.get("renderedAssetId") or "") for asset in manifest_assets
        }
        missing_ids = sorted(selected_ids - available_ids)
        if missing_ids:
            raise ValueError(
                "selected rendered assets are not exportable in this campaign: "
                + ", ".join(missing_ids)
            )
        # The signed dashboard request must describe only the selected batch.
        # Keeping the campaign-wide manifest here can exceed the production
        # request limit and also misrepresents the exact export boundary.
        manifest = {
            **manifest,
            "assets": [
                asset
                for asset in manifest_assets
                if asset.get("renderedAssetId") in selected_ids
            ],
        }
    drafts = []
    for asset in manifest["assets"]:
        if selected_ids and asset["renderedAssetId"] not in selected_ids:
            continue
        file_path = Path(asset["filePath"])
        actual_asset_hash = verify_rendered_media_asset(asset, file_path)
        expected_asset_hash = actual_asset_hash
        caption = asset.get("caption") or ""
        caption_context = _caption_context_for_export(
            asset, caption=caption, file_path=file_path
        )
        caption_is_burned = asset_caption_is_burned(asset)
        overlay_semantic_qc = evaluate_overlay_semantic_completeness(
            (caption_context.get("caption_text") or caption)
            if caption_is_burned
            else None,
            require_overlay=caption_is_burned,
        )
        if overlay_semantic_qc.get("passed") is not True:
            failure_reasons = overlay_semantic_qc.get("failure_reasons") or [
                "overlay_semantic_qc_failed"
            ]
            raise ValueError(
                "burned_overlay_semantic_incomplete:"
                + ",".join(str(reason) for reason in failure_reasons)
                + f":{asset['renderedAssetId']}"
            )
        caption_timing_qc = resolve_caption_timing_qc(asset, caption_context)
        if (
            caption_is_burned
            and overlay_semantic_qc.get("timed_sequence") is True
            and (
                not isinstance(caption_timing_qc, dict)
                or caption_timing_qc.get("passed") is not True
            )
        ):
            reasons = (
                caption_timing_qc.get("failure_reasons")
                if isinstance(caption_timing_qc, dict)
                else None
            ) or ["missing_resolved_overlay_timing_proof"]
            raise ValueError(
                "burned_overlay_timing_unverified:"
                + ",".join(str(reason) for reason in reasons)
                + f":{asset['renderedAssetId']}"
            )
        caption_hash = caption_context.get("caption_hash") or _text_hash(caption)
        destinations = _draft_destinations_for_asset(
            factory,
            asset,
            plans=distribution_plans_by_asset.get(asset["renderedAssetId"]),
            require_distribution_plan=require_distribution_plan,
        )
        for destination in destinations:
            distribution_surface = _normalize_distribution_surface(
                destination.get("distributionSurface")
            )
            if normalized_surface and distribution_surface != normalized_surface:
                continue
            factory.domains.distribution.validate_instagram_trial_reel_intent(
                content_surface=normalize_content_surface(
                    destination.get("contentSurface")
                    or destination.get("content_surface")
                    or asset.get("contentSurface")
                    or asset.get("content_surface")
                ),
                distribution_surface=distribution_surface,
                media_type=asset.get("mediaType") or asset.get("media_type") or "video",
                instagram_trial_reels=bool(destination.get("instagramTrialReels")),
                trial_graduation_strategy=destination.get("trialGraduationStrategy"),
            )
            account_eligibility = destination.get("accountEligibility") or {}
            if not account_eligibility.get("allowed", False):
                reason = account_eligibility.get("decisionReason") or "unavailable"
                raise ValueError(f"account eligibility blocked: {reason}")
            account_id = destination.get("accountId")
            instagram_account_id = destination.get("instagramAccountId")
            variation_assignment = _variant_assignment_for_destination(
                variation_index,
                rendered_asset_id=asset["renderedAssetId"],
                account_id=account_id,
                instagram_account_id=instagram_account_id,
                required=enable_variation,
            )
            destination_file_path = (
                Path(variation_assignment["variant_path"])
                if variation_assignment
                else file_path
            )
            destination_content_hash = exported_content_hash(
                destination_file_path,
                approved_hash=actual_asset_hash,
                is_derivative=bool(variation_assignment),
            )
            media_id = f"media_{uuid.uuid4().hex[:12]}"
            media_item = {
                "id": media_id,
                "type": "video",
                "url": None,
                "thumbnailUrl": None,
                "fileName": destination_file_path.name,
                "size": destination_file_path.stat().st_size
                if destination_file_path.exists()
                else 0,
                "uploadedAt": utc_now(),
            }
            post_caption = _instagram_post_caption_for_export(
                asset,
                caption=caption,
                caption_context=caption_context,
                destination=destination,
            )
            audio_recommendations = _audio_recommendations_for_destination(
                factory, asset, destination
            )
            audio_intent = _build_audio_intent(
                asset.get("audioIntent")
                or (asset.get("captionGeneration") or {}).get("audioIntent")
                or (asset.get("referencePattern") or {}).get("audioIntent"),
                audio_recommendations=audio_recommendations,
                platform="instagram",
                distribution_surface=distribution_surface,
            )
            source_lineage = asset.get("generatedAssetLineage") or {}
            generated_asset_lineage = (
                dict(source_lineage)
                if review_only
                and source_lineage.get("schema")
                == "campaign_factory.owned_library_lineage.v1"
                else finalize_lineage_v2(
                    source_lineage,
                    audio_intent=audio_intent,
                    variant_assignment=variation_assignment,
                )
            )
            learning_cohort = learning_cohort_metadata(asset)
            publishability = factory.domains.publishability.explain_publishability(
                asset["renderedAssetId"],
                distribution_plan_id=destination.get("distributionPlanId"),
            )
            if variation_assignment:
                publishability = with_content_fingerprint(
                    publishability, destination_content_hash
                )
            if review_only:
                publishability = {
                    **publishability,
                    "asset_state": "review_ready",
                    "assetState": "review_ready",
                    "approved": False,
                    "scheduleSafe": False,
                    "allowPublish": False,
                    "approvalRequired": True,
                    "handoffMode": "review_only",
                }
            resolved_publish_mode = _resolve_publish_mode(
                normalized_publish_mode,
                normalize_content_surface(
                    destination.get("contentSurface")
                    or publishability.get("contentSurface")
                    or distribution_surface
                ),
            )
            audio_deferred_to_notify = _allows_draft_notify_audio_deferral(
                schedule_mode=normalized_schedule_mode,
                publish_mode=resolved_publish_mode,
                audio_intent=audio_intent,
                publishability=publishability,
            )
            if review_only:
                publishability = dict(publishability)
            elif not (
                (publishability.get("publishableCandidate") or audio_deferred_to_notify)
                and publishability.get("handoff_manifest")
            ):
                publishability = dict(publishability)
            else:
                publishability = {
                    **publishability,
                    "asset_state": "exportable",
                    "assetState": "exportable",
                    "audioDeferredToHandoff": audio_deferred_to_notify,
                }
            content_surface = normalize_content_surface(
                destination.get("contentSurface")
                or publishability.get("contentSurface")
                or distribution_surface
            )
            cover_frame = (
                publishability.get("cover_frame")
                if isinstance(publishability.get("cover_frame"), dict)
                else {}
            )
            destination_media_item = dict(media_item)
            if (
                isinstance(cover_frame.get("image_url"), str)
                and cover_frame.get("image_url").strip()
            ):
                destination_media_item["thumbnailUrl"] = cover_frame.get(
                    "image_url"
                ).strip()
            draft_content = post_caption["instagram_post_caption"]
            draft_key = _stable_export_key(
                "draft",
                campaign_slug,
                asset["renderedAssetId"],
                instagram_account_id or account_id or "unassigned",
                distribution_surface,
                destination.get("plannedWindowStart") or "",
                caption_hash,
            )
            media_key = _stable_export_key(
                "media",
                campaign_slug,
                (variation_assignment or {}).get("variant_asset_id")
                or asset.get("renderedAssetGraphId")
                or asset.get("graphId")
                or asset["renderedAssetId"],
                destination_content_hash,
            )
            post_key = _stable_export_key("post", draft_key)
            draft = {
                "userId": user_id,
                "workspaceId": os.environ.get("THREADSDASH_WORKSPACE_ID"),
                # ThreadsDashboard accounts.id owns Threads identities. Instagram
                # drafts are scoped by instagram_account_id; never leak Campaign
                # Factory's internal account key into that foreign-key column.
                "accountId": account_id if not instagram_account_id else None,
                "instagramAccountId": instagram_account_id,
                "modelId": asset.get("modelId"),
                "platform": "instagram",
                "content": draft_content,
                "media": [destination_media_item],
                "status": _draft_status_for_schedule_mode(
                    normalized_schedule_mode, destination.get("plannedWindowStart")
                ),
                "topics": post_caption["hashtags"],
                "hashtags": post_caption["hashtags"],
                "settings": {
                    "allowReplies": True,
                    "whoCanReply": "everyone",
                    "topics": post_caption["hashtags"],
                },
                "campaignId": manifest["campaignId"],
                "graphId": asset.get("graphId") or asset.get("renderedAssetGraphId"),
                "campaignGraphId": asset.get("campaignGraphId")
                or manifest.get("campaignGraphId"),
                "sourceAssetGraphId": asset.get("sourceAssetGraphId"),
                "renderedAssetGraphId": asset.get("renderedAssetGraphId")
                or asset.get("graphId"),
                "auditGraphId": asset.get("auditGraphId"),
                "sourceAssetId": asset["sourceAssetId"],
                "renderedAssetId": asset["renderedAssetId"],
                "contentHash": destination_content_hash,
                "parentContentHash": expected_asset_hash
                if variation_assignment
                else None,
                "sourceContentHash": asset.get("sourceContentHash"),
                "captionHash": caption_hash,
                "captionOutcomeContext": caption_context,
                "overlaySemanticQc": overlay_semantic_qc,
                "captionTimingQc": caption_timing_qc,
                "instagramPostCaption": post_caption["instagram_post_caption"],
                "instagramPostCaptionHash": post_caption["instagram_post_caption_hash"],
                "captionCta": post_caption["caption_cta"],
                "postCaptionStyle": post_caption["post_caption_style"],
                "burnedCaptionText": post_caption["burned_caption_text"],
                "burnedCaptionHash": post_caption["burned_caption_hash"],
                "captionGeneration": asset.get("captionGeneration") or {},
                "contentPillar": content_pillar,
                "ctaType": cta_type,
                "language": language,
                "distributionPlanId": destination.get("distributionPlanId"),
                "distributionSurface": distribution_surface,
                "contentSurface": content_surface,
                "publishMode": resolved_publish_mode,
                "handoffMode": "review_only" if review_only else "publishable_draft",
                "instagramTrialReels": bool(destination.get("instagramTrialReels")),
                "trialGraduationStrategy": destination.get("trialGraduationStrategy"),
                "shareToFeed": not bool(destination.get("instagramTrialReels")),
                "collaborators": [],
                "trialGroupId": destination.get("trialGroupId"),
                "pairedRenderedAssetId": destination.get("pairedRenderedAssetId"),
                "distributionReasonCode": destination.get("reasonCode"),
                "smartLink": destination.get("smartLink"),
                "ctaText": destination.get("ctaText"),
                "accountProfile": factory.domains.models.model_account_profile(
                    asset.get("modelId") or ""
                ),
                "recipe": asset.get("recipe"),
                "referencePattern": asset.get("referencePattern") or {},
                "sourcePrompt": asset.get("sourcePrompt") or {},
                "generatedAssetLineage": generated_asset_lineage,
                "learningCohort": learning_cohort,
                "audioRecommendations": audio_recommendations,
                "audioIntent": audio_intent,
                "auditSummary": asset.get("auditSummary") or {},
                "plannedWindowStart": destination.get("plannedWindowStart"),
                "plannedWindowEnd": destination.get("plannedWindowEnd"),
                "scheduledFor": destination.get("plannedWindowStart")
                if normalized_schedule_mode in {"preview", "live"}
                else None,
                "previewScheduleOnly": normalized_schedule_mode == "preview"
                and bool(destination.get("plannedWindowStart")),
                "scheduleMode": normalized_schedule_mode,
                "assignmentNotes": destination.get("notes"),
                "campaignFactoryExportId": export_id,
                "campaignFactoryDraftKey": draft_key,
                "campaignFactoryMediaKey": media_key,
                "campaignFactoryPostKey": post_key,
                "auditStatus": asset.get("auditStatus"),
                "publishability": publishability,
                "handoffManifest": publishability.get("handoff_manifest"),
                "variantAssignment": variation_assignment,
                "createdAt": utc_now(),
                "updatedAt": utc_now(),
                "_localFilePath": str(destination_file_path),
                "_tags": asset.get("tags") or [],
            }
            if normalized_schedule_mode == "draft":
                draft.pop("scheduledFor", None)
                draft.pop("previewScheduleOnly", None)
            if review_only:
                review_manifest = _review_only_handoff_manifest(draft)
                draft["handoffManifest"] = review_manifest
                draft["publishability"]["handoff_manifest"] = review_manifest
            draft["metadata"] = _draft_metadata(
                draft,
                account_eligibility=destination.get("accountEligibility"),
            )
            drafts.append(draft)
    return {
        "schema": "campaign_factory.threadsdash_drafts.v2",
        "campaign": campaign_slug,
        "handoffMode": "review_only" if review_only else "publishable_draft",
        "manifest": manifest,
        "drafts": drafts,
    }


def _normalize_publish_mode(publish_mode: str | None) -> str | None:
    if publish_mode is None or not str(publish_mode).strip():
        return None
    normalized = str(publish_mode).strip().lower()
    if normalized not in VALID_PUBLISH_MODES:
        raise ValueError(
            f"invalid publish_mode {publish_mode!r}; expected one of {sorted(VALID_PUBLISH_MODES)}"
        )
    return normalized


def _resolve_publish_mode(
    normalized_publish_mode: str | None, content_surface: str | None
) -> str:
    if normalized_publish_mode is not None:
        return normalized_publish_mode
    # Reels default to notify/handoff publishing: IG's trending-audio picker is
    # app-only, so a human attaches real audio at post time. API publish would
    # ship silent/muxed audio.
    return "notify" if content_surface == "reel" else "auto"


def _draft_status_for_schedule_mode(
    schedule_mode: str, planned_window_start: str | None
) -> str:
    # Campaign Factory may export scheduling intent, but ThreadsDashboard owns
    # schedule row transitions and QStash dispatch. Never create scheduled rows
    # directly from Campaign Factory.
    return "draft"


def _variant_assignment_for_destination(
    assignment_index: dict[str, dict[str, Any]],
    *,
    rendered_asset_id: str,
    account_id: str | None,
    instagram_account_id: str | None,
    required: bool,
) -> dict[str, Any] | None:
    if not required:
        return None
    from ..variation_stage import variant_for_destination

    assignment = variant_for_destination(
        assignment_index,
        rendered_asset_id=rendered_asset_id,
        account_id=account_id,
        instagram_account_id=instagram_account_id,
    )
    if assignment is None:
        raise ValueError(
            "variation assignment missing for "
            f"rendered_asset_id={rendered_asset_id} account_id={account_id or ''} "
            f"instagram_account_id={instagram_account_id or ''}"
        )
    return assignment


def _review_only_handoff_manifest(draft: dict[str, Any]) -> dict[str, Any]:
    """Build an integrity manifest that cannot authorize scheduling or publishing."""
    _, ig_media_type = _draft_media_types(draft)
    rendered_asset_id = str(draft.get("renderedAssetId") or "")
    content_fingerprint = str(draft.get("contentHash") or "")
    caption_hash = str(draft.get("captionHash") or _text_hash(""))
    content_surface = normalize_content_surface(
        draft.get("contentSurface") or draft.get("content_surface")
    )
    media_items = []
    for index, item in enumerate(draft.get("media") or []):
        media = item if isinstance(item, dict) else {}
        media_items.append(
            {
                "componentIndex": index,
                "type": media.get("type") or "video",
                "url": media.get("url"),
                "fileName": media.get("fileName"),
                "size": media.get("size"),
            }
        )
    return {
        "manifest_version": 2,
        "asset_id": rendered_asset_id,
        "rendered_asset_id": rendered_asset_id,
        "source_asset_id": draft.get("sourceAssetId"),
        "render_file_id": _stable_export_key(
            "render_file", rendered_asset_id, content_fingerprint
        ),
        "content_fingerprint": content_fingerprint,
        "content_hash": content_fingerprint,
        "caption_hash": caption_hash,
        "captionOutcomeContext": draft.get("captionOutcomeContext") or {},
        "visual_verification_id": _stable_export_key(
            "visual_verification", rendered_asset_id, content_fingerprint
        ),
        "caption_verification_id": _stable_export_key(
            "caption_verification", rendered_asset_id, caption_hash
        ),
        # Native audio is deliberately selected later in ThreadsDashboard.
        # The sentinel satisfies the shared integrity contract without claiming
        # that an audio choice or proof exists.
        "audio_id": "pending_native_audio_review",
        "instagram_post_caption": draft.get("instagramPostCaption") or "",
        "instagram_post_caption_hash": draft.get("instagramPostCaptionHash"),
        "burned_caption_text": draft.get("burnedCaptionText"),
        "burned_caption_hash": draft.get("burnedCaptionHash")
        or draft.get("captionHash"),
        "contentSurface": content_surface,
        "igMediaType": ig_media_type,
        "mediaItems": media_items,
        "distribution_plan_id": draft.get("distributionPlanId")
        or "review_only_unassigned",
        "instagram_trial_reels": bool(draft.get("instagramTrialReels")),
        "trial_graduation_strategy": draft.get("trialGraduationStrategy"),
        "share_to_feed": bool(draft.get("shareToFeed")),
        "trial_group_id": draft.get("trialGroupId"),
        "handoffMode": "review_only",
        "approvalRequired": True,
        "approved": False,
        "scheduleSafe": False,
        "allowPublish": False,
        "exported_by_system": "campaign_factory",
        "exported_at": utc_now(),
    }


def _audio_recommendations_for_destination(
    factory: CampaignFactory,
    asset: dict[str, Any],
    destination: dict[str, Any],
) -> dict[str, Any]:
    fallback = (
        asset.get("audioRecommendations")
        if isinstance(asset.get("audioRecommendations"), dict)
        else {}
    )
    account = destination.get("instagramAccountId") or destination.get("accountId")
    if not account:
        return fallback
    reference_pattern = (
        asset.get("referencePattern")
        if isinstance(asset.get("referencePattern"), dict)
        else {}
    )
    content_tags = [
        reference_pattern.get("visualFormat"),
        reference_pattern.get("hookType"),
        reference_pattern.get("captionArchetype"),
        asset.get("recipe"),
    ]
    recommendations = factory.domains.audio_recommendations.recommend_audio(
        platform="instagram",
        content_tags=[str(tag) for tag in content_tags if tag],
        account_tags=[str(account)],
        account=str(account),
        limit=5,
    )
    if recommendations.get("recommendations"):
        return recommendations
    return fallback


def _draft_media_types(draft: dict[str, Any]) -> tuple[str, str]:
    content_surface = normalize_content_surface(
        draft.get("contentSurface") or draft.get("content_surface")
    )
    if content_surface == "feed_single":
        return "image", "IMAGE"
    if content_surface == "feed_carousel":
        return "carousel", "CAROUSEL"
    if content_surface == "story":
        return "story", "STORIES"
    surface = _normalize_distribution_surface(draft.get("distributionSurface"))
    if surface == "story_cta":
        return "story", "STORIES"
    return "reel", "REELS"


def _clean_hashtags(raw_tags: Any) -> list[str]:
    tags: list[str] = []
    if not isinstance(raw_tags, list):
        return tags
    for raw in raw_tags:
        if not isinstance(raw, str):
            continue
        cleaned = re.sub(r"[^A-Za-z0-9_]", "", raw.strip().lstrip("#"))
        if not cleaned:
            continue
        tag = f"#{cleaned}"
        if tag.lower() not in {existing.lower() for existing in tags}:
            tags.append(tag)
        if len(tags) >= 5:
            break
    return tags


def _first_string_from_records(records: list[Any], *keys: str) -> str:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in keys:
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _explicit_string_from_records(records: list[Any], *keys: str) -> tuple[bool, str]:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in keys:
            if key in record and isinstance(record.get(key), str):
                return True, str(record.get(key) or "").strip()
    return False, ""


def _instagram_post_caption_for_export(
    asset: dict[str, Any],
    *,
    caption: str,
    caption_context: dict[str, Any],
    destination: dict[str, Any],
) -> dict[str, Any]:
    caption_generation = (
        asset.get("captionGeneration")
        if isinstance(asset.get("captionGeneration"), dict)
        else {}
    )
    nested_generation = [
        caption_generation.get("instagramPostCaption"),
        caption_generation.get("instagram_post_caption"),
    ]
    records = [
        destination,
        caption_generation,
        *(record for record in nested_generation if isinstance(record, dict)),
        caption_context,
        asset,
    ]
    burned_caption = (caption or caption_context.get("caption_text") or "").strip()
    explicit_platform_caption, platform_caption = _explicit_string_from_records(
        records,
        "instagram_post_caption",
        "instagramPostCaption",
        "post_caption",
        "postCaption",
    )
    if (
        _normalize_distribution_surface(destination.get("distributionSurface"))
        == "story_cta"
        and isinstance(destination.get("ctaText"), str)
        and destination.get("ctaText").strip()
    ):
        platform_caption = destination.get("ctaText").strip()
    if not explicit_platform_caption and not platform_caption:
        platform_caption = burned_caption
    caption_cta = _first_string_from_records(records, "caption_cta", "captionCta")
    hashtags: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        hashtags.extend(
            tag
            for tag in _clean_hashtags(
                record.get("hashtags")
                or record.get("instagram_hashtags")
                or record.get("instagramHashtags")
            )
            if tag.lower() not in {existing.lower() for existing in hashtags}
        )
        if len(hashtags) >= 5:
            hashtags = hashtags[:5]
            break
    post_caption_style = (
        _first_string_from_records(records, "post_caption_style", "postCaptionStyle")
        or "short_natural"
    )
    final_caption = platform_caption
    if caption_cta and caption_cta.lower() not in final_caption.lower():
        final_caption = f"{final_caption}\n{caption_cta}".strip()
    missing_tags = [tag for tag in hashtags if tag.lower() not in final_caption.lower()]
    if missing_tags:
        final_caption = f"{final_caption}\n{' '.join(missing_tags)}".strip()
    return {
        "instagram_post_caption": final_caption,
        "instagram_post_caption_hash": _text_hash(final_caption)
        if final_caption
        else None,
        "caption_cta": caption_cta or None,
        "hashtags": hashtags,
        "post_caption_style": post_caption_style,
        "burned_caption_text": burned_caption,
        "burned_caption_hash": _text_hash(burned_caption) if burned_caption else None,
    }


def _caption_context_for_export(
    asset: dict[str, Any], *, caption: str, file_path: Path
) -> dict[str, Any]:
    existing = asset.get("captionOutcomeContext")
    if isinstance(existing, dict) and existing.get("caption_hash"):
        return dict(existing)
    return build_caption_outcome_context(
        caption_text=caption,
        caption_hash=asset.get("captionHash"),
        source_clip=existing.get("source_clip") if isinstance(existing, dict) else None,
        rendered_output=str(file_path),
        creator_model=asset.get("modelId"),
        lineage=existing
        or asset.get("generatedAssetLineage")
        or asset.get("captionGeneration")
        or {},
    )


def _build_audio_intent(
    existing: Any,
    *,
    audio_recommendations: Any,
    platform: str,
    distribution_surface: str,
) -> dict[str, Any]:
    if (
        isinstance(existing, dict)
        and existing.get("schema") == "pipeline.audio_intent.v1"
    ):
        intent = dict(existing)
        intent.setdefault(
            "recommendations", _audio_intent_recommendations(audio_recommendations)
        )
        if isinstance(audio_recommendations, dict) and audio_recommendations.get(
            "decision"
        ):
            intent.setdefault(
                "decision",
                _audio_intent_decision(audio_recommendations.get("decision")),
            )
    else:
        intent = {
            "schema": "pipeline.audio_intent.v1",
            "mode": "native_platform_audio",
            "required": _native_audio_required(distribution_surface),
            "status": None,
            "platform": platform,
            "surface": distribution_surface,
            "recommendations": _audio_intent_recommendations(audio_recommendations),
            "decision": _audio_intent_decision(audio_recommendations.get("decision"))
            if isinstance(audio_recommendations, dict)
            else None,
            "operator_selection": {
                "audio_title": None,
                "artist_name": None,
                "platform_audio_id": None,
                "platform_url": None,
                "selected_at": None,
                "selected_by": None,
                "notes": None,
            },
            "gates": {},
        }
    intent["required"] = bool(
        intent.get("required", _native_audio_required(distribution_surface))
    )
    recommendations = intent.get("recommendations")
    has_recommendations = (
        isinstance(recommendations, list) and bool(recommendations)
    ) or (
        isinstance(audio_recommendations, dict)
        and bool(
            audio_recommendations.get("primaryStrategy")
            or audio_recommendations.get("fallbackInstruction")
        )
    )
    status = str(intent.get("status") or "").strip().lower()
    if not intent["required"]:
        status = "not_required"
    elif status not in SAFE_NATIVE_AUDIO_STATUSES | UNRESOLVED_NATIVE_AUDIO_STATUSES:
        status = "recommended" if has_recommendations else "needs_operator_selection"
    intent["status"] = status
    intent["platform"] = str(intent.get("platform") or platform)
    intent["surface"] = str(intent.get("surface") or distribution_surface)
    intent.setdefault("mode", "native_platform_audio")
    intent.setdefault("operator_selection", {})
    safe = _audio_intent_allows_live(intent)
    intent["task"] = _audio_task_for_intent(intent)
    intent["gates"] = {
        **(intent.get("gates") if isinstance(intent.get("gates"), dict) else {}),
        "allow_draft_export": True,
        "allow_preview_schedule": safe,
        "allow_live_schedule": safe,
        "allow_publish": safe,
    }
    return intent


def _audio_task_for_intent(intent: dict[str, Any]) -> dict[str, Any]:
    existing = intent.get("task") if isinstance(intent.get("task"), dict) else {}
    status = str(intent.get("status") or "needs_operator_selection").strip().lower()
    task_status = {
        "not_required": "not_required",
        "recommended": "open",
        "needs_operator_selection": "open",
        "selected": "selected",
        "attached": "completed"
        if _audio_intent_allows_live(intent)
        else "proof_missing",
        "verified": "completed"
        if _audio_intent_allows_live(intent)
        else "proof_missing",
        "skipped": "completed",
        "blocked": "blocked",
        "needs_review": "needs_review",
        "burned": "blocked",
    }.get(status, "open")
    completed_at = existing.get("completed_at")
    if task_status == "completed" and not completed_at:
        selection = (
            intent.get("operator_selection")
            if isinstance(intent.get("operator_selection"), dict)
            else {}
        )
        completed_at = (
            selection.get("verified_at")
            or selection.get("attached_at")
            or selection.get("skipped_at")
        )
    return {
        **existing,
        "schema": existing.get("schema") or "pipeline.audio_task.v1",
        "status": task_status,
        "proof_required": bool(
            intent.get("required", False) and status in {"attached", "verified"}
        ),
        "assignee": existing.get("assignee"),
        "due_at": existing.get("due_at"),
        "created_at": existing.get("created_at"),
        "updated_at": existing.get("updated_at"),
        "completed_at": completed_at,
    }


def _native_audio_required(distribution_surface: str) -> bool:
    return _normalize_distribution_surface(distribution_surface) in {
        "regular_reel",
        "trial_reel",
        "reel",
    }


def _audio_intent_recommendations(audio_recommendations: Any) -> list[dict[str, Any]]:
    if not isinstance(audio_recommendations, dict):
        return []
    recommendations = audio_recommendations.get("recommendations")
    if not isinstance(recommendations, list):
        return []
    normalized = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "source": item.get("source")
                or audio_recommendations.get("source")
                or "reference_factory",
                "strategy": item.get("audioVibe")
                or item.get("usageType")
                or item.get("audioType")
                or audio_recommendations.get("primaryStrategy"),
                "audio_title": item.get("audioTitle") or item.get("title"),
                "artist_name": item.get("artistName") or item.get("artist"),
                "platform_audio_id": item.get("audioId") or item.get("platformAudioId"),
                "platform_url": item.get("platformUrl") or item.get("url"),
                "freshness": item.get("freshness") or "unknown",
                "trend_status": item.get("trendStatus")
                or item.get("freshness")
                or "unknown",
                "confidence": item.get("confidence"),
                "vibe_tags": item.get("vibeTags")
                or item.get("tags")
                or ([item.get("audioVibe")] if item.get("audioVibe") else []),
                "best_content_types": item.get("bestContentTypes") or [],
                "account_fit": item.get("accountFit") or [],
                "usage_count": item.get("usageCount"),
                "bpm": item.get("bpm"),
                "energy": item.get("energy"),
                "vocality": item.get("vocality"),
                "safe_usage_notes": item.get("safeUsageNotes")
                or item.get("safe_usage_notes"),
                "audioMemoryGraphId": item.get("audioMemoryGraphId"),
                "trendScore": item.get("trendScore"),
                "fatigueScore": item.get("fatigueScore"),
                "accountFitScore": item.get("accountFitScore"),
                "performanceLift": item.get("performanceLift"),
                "exampleReels": item.get("exampleReels") or [],
                "selectionRank": item.get("selectionRank"),
                "catalogAudioId": item.get("catalogAudioId")
                or item.get("catalog_audio_id"),
                "rationale": item.get("rationale"),
                "instruction": item.get("instruction")
                or audio_recommendations.get("fallbackInstruction"),
            }
        )
    return normalized


def _audio_intent_decision(decision: Any) -> dict[str, Any] | None:
    if not isinstance(decision, dict):
        return None

    def normalize_audio(item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        return {
            "source": item.get("source"),
            "audio_title": item.get("audio_title")
            or item.get("audioTitle")
            or item.get("title"),
            "artist_name": item.get("artist_name")
            or item.get("artistName")
            or item.get("artist"),
            "platform": item.get("platform"),
            "platform_audio_id": item.get("platform_audio_id")
            or item.get("platformAudioId")
            or item.get("audioId"),
            "platform_url": item.get("platform_url")
            or item.get("platformUrl")
            or item.get("url"),
            "catalog_audio_id": item.get("catalog_audio_id")
            or item.get("catalogAudioId"),
            "audioMemoryGraphId": item.get("audioMemoryGraphId"),
            "selectionRank": item.get("selectionRank"),
            "decisionScore": item.get("decisionScore"),
            "decisionReasons": item.get("decisionReasons") or [],
            "riskFlags": item.get("riskFlags") or [],
            "whenToUse": item.get("whenToUse"),
            "whenNotToUse": item.get("whenNotToUse"),
            "instruction": item.get("instruction"),
        }

    primary = normalize_audio(decision.get("primaryAudio"))
    backups = [
        item
        for item in (
            normalize_audio(row) for row in (decision.get("backupAudios") or [])
        )
        if item
    ]
    do_not_use = [
        item
        for item in (
            normalize_audio(row) for row in (decision.get("doNotUseAudios") or [])
        )
        if item
    ]
    return {
        "schema": decision.get("schema") or "campaign_factory.audio_decision.v1",
        "primaryAudio": primary,
        "backupAudios": backups,
        "doNotUseAudios": do_not_use,
        "decisionConfidence": decision.get("decisionConfidence"),
        "decisionReasons": decision.get("decisionReasons") or [],
        "riskFlags": decision.get("riskFlags") or [],
        "whenToUse": decision.get("whenToUse"),
        "whenNotToUse": decision.get("whenNotToUse"),
        "operatorInstruction": decision.get("operatorInstruction"),
    }


def _audio_intent_allows_live(intent: Any) -> bool:
    if not isinstance(intent, dict):
        return True
    if not intent.get("required", False):
        return True
    status = str(intent.get("status") or "").strip().lower()
    if status in {"skipped", "not_required"}:
        return True
    if status not in {"attached", "verified"}:
        return False
    selection = intent.get("operator_selection")
    if not isinstance(selection, dict):
        return False
    has_native_locator = any(
        isinstance(selection.get(key), str) and selection.get(key).strip()
        for key in (
            "platform_audio_id",
            "platform_url",
            "native_audio_id",
            "native_audio_url",
            "audio_id",
        )
    )
    has_selected_at = isinstance(selection.get("selected_at"), str) and bool(
        selection.get("selected_at").strip()
    )
    final_key = "verified_at" if status == "verified" else "attached_at"
    has_final_timestamp = isinstance(selection.get(final_key), str) and bool(
        selection.get(final_key).strip()
    )
    return bool(has_native_locator and has_selected_at and has_final_timestamp)


def _allows_draft_notify_audio_deferral(
    *,
    schedule_mode: str,
    publish_mode: str,
    audio_intent: Any,
    publishability: dict[str, Any],
) -> bool:
    if schedule_mode != "draft" or publish_mode != "notify":
        return False
    if not isinstance(audio_intent, dict) or audio_intent.get("required") is not True:
        return False
    gates = (
        audio_intent.get("gates") if isinstance(audio_intent.get("gates"), dict) else {}
    )
    if (
        gates.get("allow_draft_export") is not True
        or gates.get("allow_publish") is not False
    ):
        return False
    failures = {
        str(reason)
        for reason in publishability.get("publishability_failure_reasons") or []
    }
    manifest = publishability.get("handoff_manifest")
    return bool(
        failures
        and failures.issubset(DEFERRED_NOTIFY_AUDIO_FAILURES)
        and isinstance(manifest, dict)
        and manifest.get("manifest_version") == 2
        and manifest.get("audioDeferredToHandoff") is True
    )


def _draft_metadata(
    draft: dict[str, Any], *, account_eligibility: dict[str, Any] | None = None
) -> dict[str, Any]:
    audit_summary = draft.get("auditSummary") or {}
    audio_recommendations = draft.get("audioRecommendations") or {}
    publishability = (
        draft.get("publishability")
        if isinstance(draft.get("publishability"), dict)
        else {}
    )
    handoff_manifest = (
        draft.get("handoffManifest")
        if isinstance(draft.get("handoffManifest"), dict)
        else publishability.get("handoff_manifest")
    )
    caption_context = (
        draft.get("captionOutcomeContext")
        if isinstance(draft.get("captionOutcomeContext"), dict)
        else {}
    )
    overlay_semantic_qc = (
        draft.get("overlaySemanticQc")
        if isinstance(draft.get("overlaySemanticQc"), dict)
        else caption_context.get("overlaySemanticQc")
        or caption_context.get("overlay_semantic_qc")
        or {}
    )
    caption_timing_qc = (
        draft.get("captionTimingQc")
        if isinstance(draft.get("captionTimingQc"), dict)
        else caption_context.get("captionTimingQc")
        or caption_context.get("caption_timing_qc")
        or {}
    )
    failure_reasons = list(
        publishability.get("publishability_failure_reasons")
        or publishability.get("failureReasons")
        or []
    )
    asset_state = str(
        publishability.get("asset_state")
        or publishability.get("assetState")
        or (
            "exportable"
            if handoff_manifest and not failure_reasons
            else "approved_but_not_publishable"
        )
    )
    instagram_trial_reels = bool(
        draft.get("instagramTrialReels")
        or draft.get("isInstagramTrialReel")
        or publishability.get("instagramTrialReels")
        or publishability.get("instagram_trial_reels")
    )
    audio_intent = draft.get("audioIntent") or _build_audio_intent(
        None,
        audio_recommendations=audio_recommendations,
        platform="instagram",
        distribution_surface=draft.get("distributionSurface") or "regular_reel",
    )
    audio_selection = (
        audio_intent.get("operator_selection")
        if isinstance(audio_intent.get("operator_selection"), dict)
        else {}
    )
    handoff_audio_id = (
        handoff_manifest.get("audio_id") if isinstance(handoff_manifest, dict) else None
    )
    audio_segment = publishability.get("audio_segment") or (
        handoff_manifest.get("audio_segment")
        if isinstance(handoff_manifest, dict)
        else None
    )
    cover_frame = publishability.get("cover_frame") or (
        handoff_manifest.get("cover_frame")
        if isinstance(handoff_manifest, dict)
        else None
    )
    audio_id = next(
        (
            value
            for value in (
                audio_selection.get("audio_id"),
                audio_selection.get("track_id"),
                audio_selection.get("platform_audio_id"),
                audio_selection.get("native_audio_id"),
                handoff_audio_id,
            )
            if isinstance(value, str) and value.strip()
        ),
        None,
    )
    visual_qc = (
        publishability.get("visualQc")
        or publishability.get("visual_qc")
        or (
            handoff_manifest.get("visualQc")
            if isinstance(handoff_manifest, dict)
            else None
        )
        or {}
    )
    identity_verification = (
        publishability.get("identityVerification")
        or publishability.get("identity_verification")
        or (
            handoff_manifest.get("identityVerification")
            if isinstance(handoff_manifest, dict)
            else None
        )
        or {}
    )
    visual_qc_status = (
        str(
            publishability.get("visualQcStatus")
            or publishability.get("visual_qc_status")
            or (
                handoff_manifest.get("visualQcStatus")
                if isinstance(handoff_manifest, dict)
                else None
            )
            or (
                visual_qc.get("visualQcStatus") if isinstance(visual_qc, dict) else None
            )
            or (visual_qc.get("status") if isinstance(visual_qc, dict) else None)
            or "unavailable"
        )
        .strip()
        .lower()
    )
    identity_verification_status = (
        str(
            publishability.get("identityVerificationStatus")
            or publishability.get("identity_verification_status")
            or (
                handoff_manifest.get("identityVerificationStatus")
                if isinstance(handoff_manifest, dict)
                else None
            )
            or (
                identity_verification.get("identityVerificationStatus")
                if isinstance(identity_verification, dict)
                else None
            )
            or (
                identity_verification.get("status")
                if isinstance(identity_verification, dict)
                else None
            )
            or "unavailable"
        )
        .strip()
        .lower()
    )
    if visual_qc_status not in {"passed", "failed", "unavailable"}:
        visual_qc_status = "unavailable"
    if identity_verification_status not in {"passed", "failed", "unavailable"}:
        identity_verification_status = "unavailable"
    metadata = {
        "campaign_factory": {
            "graph_id": draft.get("graphId") or draft.get("renderedAssetGraphId"),
            "campaign_graph_id": draft.get("campaignGraphId"),
            "source_asset_graph_id": draft.get("sourceAssetGraphId"),
            "rendered_asset_graph_id": draft.get("renderedAssetGraphId")
            or draft.get("graphId"),
            "audit_graph_id": draft.get("auditGraphId"),
            "campaign_id": draft["campaignId"],
            "asset_id": draft["renderedAssetId"],
            "source_asset_id": draft["sourceAssetId"],
            "rendered_asset_id": draft["renderedAssetId"],
            "content_hash": draft.get("contentHash"),
            "content_fingerprint": publishability.get("content_fingerprint")
            or publishability.get("contentFingerprint")
            or draft.get("contentHash"),
            "source_content_hash": draft.get("sourceContentHash"),
            "concept_id": publishability.get("concept_id")
            or publishability.get("conceptId"),
            "parent_reel_id": publishability.get("parent_reel_id")
            or publishability.get("parentReelId"),
            "parent_asset_id": publishability.get("parent_asset_id")
            or publishability.get("parentAssetId"),
            "variant_family_id": publishability.get("variant_family_id")
            or publishability.get("variantFamilyId"),
            "variant_id": publishability.get("variant_id")
            or publishability.get("variantId"),
            "variant_index": publishability.get("variant_index")
            or publishability.get("variantIndex"),
            "variant_operations": publishability.get("variant_operations")
            or publishability.get("variantOperations")
            or [],
            "variant_assignment": draft.get("variantAssignment"),
            "variant_asset_id": (draft.get("variantAssignment") or {}).get(
                "variant_asset_id"
            )
            if isinstance(draft.get("variantAssignment"), dict)
            else None,
            "variant_path": (draft.get("variantAssignment") or {}).get("variant_path")
            if isinstance(draft.get("variantAssignment"), dict)
            else None,
            "parent_master_asset_id": (draft.get("variantAssignment") or {}).get(
                "parent_master_asset_id"
            )
            if isinstance(draft.get("variantAssignment"), dict)
            else None,
            "variant_distinctness_scores": (draft.get("variantAssignment") or {}).get(
                "distinctness_scores"
            )
            if isinstance(draft.get("variantAssignment"), dict)
            else None,
            "caption_family_id": publishability.get("caption_family_id")
            or publishability.get("captionFamilyId")
            or caption_context.get("caption_family_id")
            or caption_context.get("captionFamilyId"),
            "caption_version_id": publishability.get("caption_version_id")
            or publishability.get("captionVersionId")
            or caption_context.get("caption_version_id")
            or caption_context.get("captionVersionId"),
            "caption_hash": draft.get("captionHash"),
            "instagram_post_caption": draft.get("instagramPostCaption") or "",
            "instagram_post_caption_hash": draft.get("instagramPostCaptionHash"),
            "caption_cta": draft.get("captionCta"),
            "hashtags": draft.get("hashtags") or draft.get("topics") or [],
            "post_caption_style": draft.get("postCaptionStyle") or "short_natural",
            "burned_caption_text": draft.get("burnedCaptionText"),
            "burned_caption_hash": draft.get("burnedCaptionHash")
            or draft.get("captionHash"),
            "captionOutcomeContext": caption_context,
            "caption_outcome_context": caption_context,
            "overlay_semantic_qc": overlay_semantic_qc,
            "caption_timing_qc": caption_timing_qc,
            "caption_generation": draft.get("captionGeneration") or {},
            "recipe": draft.get("recipe"),
            "reference_pattern": draft.get("referencePattern") or {},
            "source_prompt": draft.get("sourcePrompt") or {},
            "generated_asset_lineage": draft.get("generatedAssetLineage") or {},
            "learning_cohort": draft.get("learningCohort"),
            "lineage_v2_valid": lineage_v2_is_valid(draft.get("generatedAssetLineage")),
            "creative_plan": draft.get("creativePlan") or {},
            "audio_recommendations": audio_recommendations,
            "audio_intent": audio_intent,
            "audio_id": audio_id,
            "audio_segment": audio_segment if isinstance(audio_segment, dict) else None,
            "audio_strategy": _primary_audio_strategy(audio_recommendations),
            "native_audio_preferred": bool(
                audio_recommendations.get("nativeAudioPreferred", True)
            )
            if isinstance(audio_recommendations, dict)
            else True,
            "cover_frame": cover_frame if isinstance(cover_frame, dict) else None,
            "variation_score": audit_summary.get("variationScore"),
            "creative_score": audit_summary.get("creativeScore"),
            "audit_summary": audit_summary,
            "export_id": draft.get("campaignFactoryExportId"),
            "draft_key": draft.get("campaignFactoryDraftKey"),
            "media_key": draft.get("campaignFactoryMediaKey"),
            "post_key": draft.get("campaignFactoryPostKey"),
            "audit_status": draft.get("auditStatus"),
            "publish_mode": draft.get("publishMode"),
            "handoffMode": draft.get("handoffMode") or "publishable_draft",
            "scheduleSafe": False
            if draft.get("handoffMode") == "review_only"
            else bool(publishability.get("scheduleSafe")),
            "allowPublish": False
            if draft.get("handoffMode") == "review_only"
            else bool(publishability.get("allowPublish", True)),
            "approvalRequired": draft.get("handoffMode") == "review_only",
            "asset_state": asset_state,
            "lifecycle_state": publishability.get("lifecycle_state")
            or (
                "publishable_candidate"
                if asset_state in {"publishable_candidate", "exportable"}
                else "creative_approved"
            ),
            "approved": bool(publishability.get("approved")),
            "captioned_render_present": bool(
                publishability.get("captioned_render_present")
                or publishability.get("captionedRenderPresent")
            ),
            "visible_caption_verification": "pass"
            if publishability.get("visible_caption_verification")
            else "fail",
            "expected_visual_verification": "pass"
            if publishability.get("expected_visual_verification")
            else "fail",
            "visualQcStatus": visual_qc_status,
            "identityVerificationStatus": identity_verification_status,
            "visualQc": visual_qc if isinstance(visual_qc, dict) else {},
            "identityVerification": identity_verification
            if isinstance(identity_verification, dict)
            else {},
            "readiness_checks_pass": bool(
                publishability.get("readiness_checks_pass")
                or publishability.get("readinessChecksPass")
            ),
            "publishability_failure_reasons": failure_reasons,
            "blockingReason": publishability.get("blockingReason"),
            "rootCause": publishability.get("rootCause"),
            "nextOperatorAction": publishability.get("nextOperatorAction"),
            "handoff_manifest": handoff_manifest,
            "quarantined": bool(publishability.get("quarantine")),
            "metrics_eligible": False,
            "model_id": draft.get("modelId"),
            "model_slug": draft.get("modelId"),
            "account_profile": draft.get("accountProfile") or {},
            "account_eligibility": account_eligibility or {},
            "content_pillar": draft.get("contentPillar"),
            "cta_type": draft.get("ctaType"),
            "language": draft.get("language"),
            "content_surface": draft.get("contentSurface") or "reel",
            "distribution_surface": draft.get("distributionSurface") or "reel",
            "distribution_plan_id": draft.get("distributionPlanId"),
            "paired_rendered_asset_id": draft.get("pairedRenderedAssetId"),
            "distribution_reason_code": draft.get("distributionReasonCode"),
            "smart_link": draft.get("smartLink"),
            "cta_text": draft.get("ctaText"),
            "instagram_trial_reels": instagram_trial_reels,
            "share_to_feed": bool(draft.get("shareToFeed")),
            "trial_graduation_strategy": draft.get("trialGraduationStrategy")
            if instagram_trial_reels
            else None,
            "trial_reel": draft.get("distributionSurface") == "trial_reel",
            "trial_group_id": draft.get("trialGroupId"),
            "planned_window_start": draft.get("plannedWindowStart"),
            "planned_window_end": draft.get("plannedWindowEnd"),
            "preview_schedule_only": bool(draft.get("previewScheduleOnly")),
            "schedule_mode": draft.get("scheduleMode") or "draft",
            "scheduled_for": draft.get("scheduledFor"),
            "assignment_notes": draft.get("assignmentNotes"),
        }
    }
    if draft.get("previewScheduleOnly"):
        metadata["previewScheduleOnly"] = True
    if instagram_trial_reels:
        trial_graduation_strategy = (
            str(draft.get("trialGraduationStrategy") or "").strip().upper()
        )
        if trial_graduation_strategy not in {"MANUAL", "SS_PERFORMANCE"}:
            raise ValueError(
                "Trial Reel draft requires trialGraduationStrategy=MANUAL or SS_PERFORMANCE"
            )
        metadata["trialReels"] = True
        metadata["shareToFeed"] = False
        metadata["trialGraduationStrategy"] = trial_graduation_strategy
    else:
        metadata["shareToFeed"] = bool(draft.get("shareToFeed"))
    if draft.get("trialGroupId"):
        metadata["trialGroupId"] = draft.get("trialGroupId")
    if isinstance(cover_frame, dict):
        if (
            isinstance(cover_frame.get("image_url"), str)
            and cover_frame.get("image_url").strip()
        ):
            metadata["coverUrl"] = cover_frame.get("image_url").strip()
        if isinstance(cover_frame.get("seconds"), (int, float)):
            metadata["thumbOffset"] = cover_frame.get("seconds")
    if draft.get("smartLink"):
        metadata["campaign_factory_smart_link"] = draft.get("smartLink")
    if metadata["campaign_factory"].get("learning_cohort") is None:
        metadata["campaign_factory"].pop("learning_cohort", None)
    if draft.get("handoffMode") != "review_only":
        metadata["campaign_factory"].pop("scheduleSafe", None)
        metadata["campaign_factory"].pop("allowPublish", None)
        metadata["campaign_factory"].pop("approvalRequired", None)
    return metadata


def _primary_audio_strategy(audio_recommendations: Any) -> str | None:
    if not isinstance(audio_recommendations, dict):
        return None
    primary = audio_recommendations.get("primaryStrategy")
    if primary:
        return str(primary)
    recommendations = audio_recommendations.get("recommendations")
    if isinstance(recommendations, list):
        for recommendation in recommendations:
            if isinstance(recommendation, dict):
                for key in ("audioVibe", "usageType", "audioType", "sourceType"):
                    value = recommendation.get(key)
                    if value:
                        return str(value)
    return None


def _stable_export_key(prefix: str, *parts: Any) -> str:
    joined = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}_{hashlib.sha256(joined.encode('utf-8')).hexdigest()[:20]}"
