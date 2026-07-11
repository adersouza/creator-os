from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from ..caption_outcome import (
    build_caption_outcome_context,
    column_values,
    load_context_json,
)
from ..contracts import (
    ContractValidationError,
    validate_performance_sync,
    validate_post_metric_history_read,
    validate_threadsdash_draft_payload_strict,
)
from ..core import (
    CampaignFactory,
    _normalize_distribution_surface,
    _normalize_schedule_mode,
    new_id,
    normalize_content_surface,
    utc_now,
)
from ..learning_readiness import closed_loop_learning_status
from ..learning_score import (
    learning_ineligibility_reasons,
    learning_loop_cutover_iso,
)
from ..lineage_v2 import (
    finalize_lineage_v2,
    lineage_v2_is_learning_traceable,
    lineage_v2_is_valid,
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
CAMPAIGN_FACTORY_INGEST_SIGNATURE_VERSION = "v1"
_STDLIB_URLOPEN = urlopen


class _RejectDashboardIngestRedirects(HTTPRedirectHandler):
    """Never forward authenticated ingest requests to a redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_threadsdash_ingest_request(request: Request, *, timeout: float):
    # Preserve the existing injected transport seam used by deterministic E2E
    # fakes. Runtime traffic keeps the no-redirect opener below.
    if urlopen is not _STDLIB_URLOPEN:
        return urlopen(request, timeout=timeout)
    return build_opener(_RejectDashboardIngestRedirects()).open(
        request, timeout=timeout
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
    schedule_mode: str = "draft",
    enable_variation: bool = False,
    publish_mode: str | None = None,
) -> dict[str, Any]:
    manifest = factory.export_manifest(campaign_slug=campaign_slug)
    normalized_publish_mode = _normalize_publish_mode(publish_mode)
    normalized_schedule_mode = _normalize_schedule_mode(schedule_mode)
    variation_index: dict[str, dict[str, Any]] = {}
    if enable_variation:
        from ..variation_stage import load_variant_assignment_index

        variation_index = load_variant_assignment_index(
            factory, campaign_slug=campaign_slug
        )
    distribution_plans_by_asset: dict[str, list[dict[str, Any]]] = {}
    require_distribution_plan = False
    if normalized_schedule_mode in {"preview", "live"}:
        distribution_plans = factory.distribution_plans_for_campaign(campaign_slug)
        require_distribution_plan = bool(distribution_plans)
        for plan in distribution_plans:
            distribution_plans_by_asset.setdefault(plan["renderedAssetId"], []).append(
                plan
            )
    selected_ids = set(rendered_asset_ids or [])
    drafts = []
    for asset in manifest["assets"]:
        if selected_ids and asset["renderedAssetId"] not in selected_ids:
            continue
        file_path = Path(asset["filePath"])
        caption = asset.get("caption") or ""
        caption_context = _caption_context_for_export(
            asset, caption=caption, file_path=file_path
        )
        caption_hash = caption_context.get("caption_hash") or _text_hash(caption)
        destinations = _draft_destinations_for_asset(
            factory,
            asset,
            plans=distribution_plans_by_asset.get(asset["renderedAssetId"]),
            require_distribution_plan=require_distribution_plan,
        )
        for destination in destinations:
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
            distribution_surface = _normalize_distribution_surface(
                destination.get("distributionSurface")
            )
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
            generated_asset_lineage = finalize_lineage_v2(
                asset.get("generatedAssetLineage") or {},
                audio_intent=audio_intent,
                variant_assignment=variation_assignment,
            )
            learning_cohort = _learning_cohort_metadata(asset)
            publishability = factory.explain_publishability(
                asset["renderedAssetId"],
                distribution_plan_id=destination.get("distributionPlanId"),
            )
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
            if not (
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
                (variation_assignment or {}).get("variant_path")
                or asset.get("contentHash")
                or "",
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
                "contentHash": asset.get("contentHash"),
                "sourceContentHash": asset.get("sourceContentHash"),
                "captionHash": caption_hash,
                "captionOutcomeContext": caption_context,
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
                "instagramTrialReels": bool(destination.get("instagramTrialReels")),
                "trialGraduationStrategy": destination.get("trialGraduationStrategy"),
                "trialGroupId": destination.get("trialGroupId"),
                "pairedRenderedAssetId": destination.get("pairedRenderedAssetId"),
                "distributionReasonCode": destination.get("reasonCode"),
                "smartLink": destination.get("smartLink"),
                "ctaText": destination.get("ctaText"),
                "accountProfile": factory.model_account_profile(
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
            draft["metadata"] = _draft_metadata(draft)
            drafts.append(draft)
    return {
        "schema": "campaign_factory.threadsdash_drafts.v2",
        "campaign": campaign_slug,
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


def _campaign_factory_manifest_blockers(
    payload: dict[str, Any],
    *,
    require_remote_media_urls: bool = False,
) -> list[str]:
    blockers: list[str] = []
    for idx, draft in enumerate(payload.get("drafts") or []):
        meta = (
            ((draft.get("metadata") or {}).get("campaign_factory") or {})
            if isinstance(draft.get("metadata"), dict)
            else {}
        )
        rendered_asset_id = (
            meta.get("rendered_asset_id")
            or draft.get("renderedAssetId")
            or f"draft_{idx}"
        )
        asset_state = str(meta.get("asset_state") or "").strip().lower()
        if asset_state not in {"publishable_candidate", "exportable"}:
            blockers.append(
                f"{rendered_asset_id}:asset_state:{asset_state or 'missing'}"
            )
        failures = meta.get("publishability_failure_reasons") or []
        if failures and not _draft_notify_audio_deferred(draft):
            blockers.extend(
                f"{rendered_asset_id}:publishability:{reason}" for reason in failures
            )
        manifest = meta.get("handoff_manifest")
        if not isinstance(manifest, dict):
            blockers.append(f"{rendered_asset_id}:handoff_manifest_missing")
            continue
        manifest_version = manifest.get("manifest_version")
        content_surface = (
            manifest.get("contentSurface")
            or manifest.get("content_surface")
            or meta.get("content_surface")
            or draft.get("contentSurface")
        )
        if manifest_version == 2:
            required = (
                "manifest_version",
                "asset_id",
                "content_fingerprint",
                "mediaItems",
                "contentSurface",
                "igMediaType",
                "exported_by_system",
                "exported_at",
            )
        else:
            required = (
                "manifest_version",
                "asset_id",
                "render_file_id",
                "content_fingerprint",
                "caption_hash",
                "captionOutcomeContext",
                "instagram_post_caption",
                "instagram_post_caption_hash",
                "visual_verification_id",
                "caption_verification_id",
                "audio_id",
                "distribution_plan_id",
                "exported_by_system",
                "exported_at",
            )
        for key in required:
            value = manifest.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                blockers.append(f"{rendered_asset_id}:handoff_manifest.{key}_missing")
        if manifest_version not in {1, 2}:
            blockers.append(f"{rendered_asset_id}:handoff_manifest.version_invalid")
        if manifest_version == 2:
            ig_media_type = manifest.get("igMediaType") or manifest.get("ig_media_type")
            if not content_surface:
                blockers.append(
                    f"{rendered_asset_id}:handoff_manifest.contentSurface_missing"
                )
            if not ig_media_type:
                blockers.append(
                    f"{rendered_asset_id}:handoff_manifest.igMediaType_missing"
                )
            if content_surface == "feed_single" and ig_media_type != "IMAGE":
                blockers.append(
                    f"{rendered_asset_id}:handoff_manifest.feed_single_ig_media_type_invalid"
                )
            media_items = manifest.get("mediaItems")
            if content_surface == "feed_single" and (
                not isinstance(media_items, list) or len(media_items) != 1
            ):
                blockers.append(
                    f"{rendered_asset_id}:handoff_manifest.mediaItems_invalid"
                )
            if content_surface == "story" and (
                not isinstance(media_items, list) or len(media_items) != 1
            ):
                blockers.append(
                    f"{rendered_asset_id}:handoff_manifest.mediaItems_invalid"
                )
        if manifest.get("exported_by_system") != "campaign_factory":
            blockers.append(
                f"{rendered_asset_id}:handoff_manifest.exported_by_system_invalid"
            )
        if manifest.get("asset_id") != rendered_asset_id:
            blockers.append(f"{rendered_asset_id}:handoff_manifest.asset_id_mismatch")
        content_hash = (
            meta.get("content_fingerprint")
            or meta.get("content_hash")
            or draft.get("contentHash")
        )
        if content_hash and manifest.get("content_fingerprint") != content_hash:
            blockers.append(
                f"{rendered_asset_id}:handoff_manifest.content_fingerprint_mismatch"
            )
        caption_hash = meta.get("caption_hash") or draft.get("captionHash")
        if (
            content_surface != "story"
            and caption_hash
            and manifest.get("caption_hash") != caption_hash
        ):
            blockers.append(
                f"{rendered_asset_id}:handoff_manifest.caption_hash_mismatch"
            )
        post_caption = meta.get("instagram_post_caption") or draft.get(
            "instagramPostCaption"
        )
        post_caption_hash = meta.get("instagram_post_caption_hash") or draft.get(
            "instagramPostCaptionHash"
        )
        if content_surface != "story" and (
            not isinstance(post_caption, str) or not post_caption.strip()
        ):
            blockers.append(f"{rendered_asset_id}:instagram_post_caption_missing")
        if (
            post_caption_hash
            and manifest.get("instagram_post_caption_hash") != post_caption_hash
        ):
            blockers.append(
                f"{rendered_asset_id}:handoff_manifest.instagram_post_caption_hash_mismatch"
            )
        if meta.get("quarantined"):
            blockers.append(f"{rendered_asset_id}:quarantined_asset")
        if require_remote_media_urls:
            blockers.extend(
                _remote_media_url_blockers(draft, rendered_asset_id=rendered_asset_id)
            )
    return sorted(set(blockers))


def _draft_payload_contract_blockers(payload: dict[str, Any]) -> list[str]:
    try:
        validate_threadsdash_draft_payload_strict(payload)
    except ContractValidationError as exc:
        detail = str(exc).splitlines()[0].strip()
        return [f"draft_payload_contract_invalid:{detail or 'validation_failed'}"]
    return []


def _is_remote_media_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _media_item_url(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if not isinstance(item, dict):
        return None
    for key in ("url", "publicUrl", "public_url", "file_url", "storage_url"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _remote_media_url_blockers(
    draft: dict[str, Any], *, rendered_asset_id: str
) -> list[str]:
    metadata = draft.get("metadata") if isinstance(draft.get("metadata"), dict) else {}
    meta = (
        metadata.get("campaign_factory")
        if isinstance(metadata.get("campaign_factory"), dict)
        else {}
    )
    manifest = (
        meta.get("handoff_manifest")
        if isinstance(meta.get("handoff_manifest"), dict)
        else {}
    )
    draft_media = draft.get("media") if isinstance(draft.get("media"), list) else []
    draft_media_items = (
        draft.get("mediaItems") if isinstance(draft.get("mediaItems"), list) else []
    )
    draft_media_urls = (
        draft.get("media_urls") if isinstance(draft.get("media_urls"), list) else []
    )
    manifest_media_items = (
        manifest.get("mediaItems")
        if isinstance(manifest.get("mediaItems"), list)
        else []
    )
    manifest_media_items = manifest_media_items or (
        manifest.get("media_items")
        if isinstance(manifest.get("media_items"), list)
        else []
    )
    groups = [draft_media, draft_media_items, draft_media_urls, manifest_media_items]
    expected_count = max((len(group) for group in groups), default=0)
    if expected_count == 0:
        return [f"{rendered_asset_id}:media_remote_url_missing"]

    blockers: list[str] = []
    for index in range(expected_count):
        candidates = [
            _media_item_url(group[index]) for group in groups if index < len(group)
        ]
        if not any(_is_remote_media_url(url) for url in candidates if url):
            blockers.append(
                f"{rendered_asset_id}:media_item_{index}_remote_url_missing"
            )
        for url in candidates:
            if url and not _is_remote_media_url(url):
                blockers.append(
                    f"{rendered_asset_id}:media_item_{index}_url_not_remote"
                )
    return blockers


def _draft_destinations_for_asset(
    factory: CampaignFactory,
    asset: dict[str, Any],
    *,
    plans: list[dict[str, Any]] | None = None,
    require_distribution_plan: bool = False,
) -> list[dict[str, Any]]:
    plans = (
        plans
        if plans is not None
        else factory.distribution_plans_for_asset(asset["renderedAssetId"])
    )
    asset_content_surface = normalize_content_surface(
        asset.get("contentSurface") or asset.get("content_surface")
    )
    default_distribution_surface = (
        "regular_reel" if asset_content_surface == "reel" else asset_content_surface
    )
    if plans:
        return [
            {
                "accountId": plan.get("accountId"),
                "instagramAccountId": plan.get("instagramAccountId"),
                "plannedWindowStart": plan.get("plannedWindowStart"),
                "plannedWindowEnd": plan.get("plannedWindowEnd"),
                "notes": plan.get("reasonCode"),
                "distributionPlanId": plan.get("id"),
                "distributionSurface": plan.get("surface"),
                "contentSurface": plan.get("contentSurface")
                or plan.get("content_surface"),
                "instagramTrialReels": plan.get("instagramTrialReels"),
                "trialGraduationStrategy": plan.get("trialGraduationStrategy"),
                "trialGroupId": plan.get("trialGroupId"),
                "pairedRenderedAssetId": plan.get("pairedRenderedAssetId"),
                "reasonCode": plan.get("reasonCode"),
                "smartLink": plan.get("smartLink"),
                "ctaText": plan.get("ctaText"),
            }
            for plan in plans
        ]
    if require_distribution_plan:
        return []
    assignments = factory.assignments_for_asset(asset["renderedAssetId"])
    if assignments:
        return [
            {
                "accountId": assignment.get("account_id"),
                "instagramAccountId": assignment.get("instagram_account_id"),
                "plannedWindowStart": assignment.get("planned_window_start"),
                "plannedWindowEnd": assignment.get("planned_window_end"),
                "notes": assignment.get("notes"),
                "distributionSurface": default_distribution_surface,
                "contentSurface": asset_content_surface,
            }
            for assignment in assignments
        ]
    destinations = []
    for account_id in asset.get("accountIds") or ["unassigned"]:
        destinations.append(
            {
                "accountId": account_id,
                "instagramAccountId": _resolve_instagram_account_id(
                    factory, account_id
                ),
                "plannedWindowStart": None,
                "plannedWindowEnd": None,
                "notes": None,
                "distributionSurface": default_distribution_surface,
                "contentSurface": asset_content_surface,
            }
        )
    return destinations


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
    recommendations = factory.recommend_audio(
        platform="instagram",
        content_tags=[str(tag) for tag in content_tags if tag],
        account_tags=[str(account)],
        account=str(account),
        limit=5,
    )
    if recommendations.get("recommendations"):
        return recommendations
    return fallback


def export_threadsdash(
    factory: CampaignFactory,
    *,
    campaign_slug: str,
    user_id: str,
    dry_run: bool = True,
    supabase_url: str | None = None,
    supabase_service_role_key: str | None = None,
    supabase_storage_bucket: str = "media",
    allow_warnings: bool = False,
    content_pillar: str | None = None,
    cta_type: str | None = None,
    language: str | None = None,
    max_drafts: int | None = None,
    rendered_asset_ids: list[str] | None = None,
    schedule_mode: str = "draft",
    threadsdash_ingest_url: str | None = None,
    threadsdash_ingest_secret: str | None = None,
    enable_variation: bool = False,
    variation_preset: str = "ig_subtle",
    publish_mode: str | None = None,
) -> dict[str, Any]:
    campaign = factory.campaign_by_slug(campaign_slug)
    normalized_schedule_mode = _normalize_schedule_mode(schedule_mode)
    normalized_publish_mode = _normalize_publish_mode(publish_mode)
    pipeline_job = factory.create_pipeline_job(
        "threadsdash_export",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "userId": user_id,
            "dryRun": dry_run,
            "hasSupabaseUrl": bool(supabase_url),
            "hasSupabaseServiceRoleKey": bool(supabase_service_role_key),
            "supabaseStorageBucket": supabase_storage_bucket,
            "allowWarnings": allow_warnings,
            "contentPillar": content_pillar,
            "ctaType": cta_type,
            "language": language,
            "maxDrafts": max_drafts,
            "renderedAssetIds": rendered_asset_ids or [],
            "scheduleMode": normalized_schedule_mode,
            "publishMode": normalized_publish_mode,
            "hasThreadsdashIngestUrl": bool(
                threadsdash_ingest_url
                or os.environ.get("THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL")
                or os.environ.get("CAMPAIGN_FACTORY_DRAFT_INGEST_URL")
            ),
            "enableVariation": enable_variation,
            "variationPreset": variation_preset,
        },
    )
    factory.start_pipeline_job(pipeline_job["id"])
    model_slug = factory._model_slug_for_campaign(campaign["id"])
    dirs = factory.campaign_dirs(model_slug, campaign["slug"])
    try:
        export_id = new_id("tdexp")
        variation_result = None
        if enable_variation:
            from ..variation_stage import run_variation_stage

            variation_result = run_variation_stage(
                factory,
                campaign_slug=campaign_slug,
                preset_name=variation_preset,
                rendered_asset_ids=rendered_asset_ids,
                dry_run=dry_run,
            )
        payload = build_draft_payloads(
            factory,
            campaign_slug=campaign_slug,
            user_id=user_id,
            export_id=export_id,
            content_pillar=content_pillar,
            cta_type=cta_type,
            language=language,
            rendered_asset_ids=rendered_asset_ids,
            schedule_mode=normalized_schedule_mode,
            enable_variation=enable_variation,
            publish_mode=normalized_publish_mode,
        )
        if max_drafts is not None:
            payload["drafts"] = payload["drafts"][: max(0, max_drafts)]
        readiness = evaluate_export_readiness(
            factory,
            campaign_slug=campaign_slug,
            user_id=user_id,
            supabase_url=supabase_url,
            supabase_service_role_key=supabase_service_role_key,
            content_pillar=content_pillar,
            cta_type=cta_type,
            language=language,
            rendered_asset_ids=rendered_asset_ids,
            schedule_mode=normalized_schedule_mode,
            publish_mode=normalized_publish_mode,
        )
        writes_non_draft_rows = normalized_schedule_mode in {"preview", "live"}
        publishability_blockers = [
            reason
            for reason in readiness.get("blockingReasons") or []
            if str(reason).startswith("publishability:")
            or "threadsdash_draft_media_invalid_missing_burned_captions" in str(reason)
        ]
        if not dry_run and publishability_blockers:
            raise ValueError(
                f"export blocked by publishability: {', '.join(publishability_blockers)}"
            )
        uses_dashboard_ingest = (
            not dry_run
            and not _legacy_supabase_writes_enabled()
            and normalized_schedule_mode == "draft"
        )
        dashboard_ingest_media: list[dict[str, Any]] = []
        if uses_dashboard_ingest:
            dashboard_ingest_media = _upload_media_for_dashboard_ingest(
                factory,
                payload,
                user_id=user_id,
                supabase_url=supabase_url,
                service_role_key=supabase_service_role_key,
                bucket=supabase_storage_bucket,
            )
        manifest_blockers = _campaign_factory_manifest_blockers(
            payload,
            require_remote_media_urls=uses_dashboard_ingest,
        )
        if not dry_run and manifest_blockers:
            raise ValueError(
                f"export blocked by handoff manifest: {', '.join(manifest_blockers)}"
            )
        if not dry_run and writes_non_draft_rows and not readiness["liveExportAllowed"]:
            raise ValueError(
                f"live export blocked: {', '.join(readiness['blockingReasons'])}"
            )
        if (
            not dry_run
            and writes_non_draft_rows
            and readiness["warnings"]
            and not allow_warnings
        ):
            raise ValueError(
                f"live export has warnings; pass explicit confirmation to continue: {', '.join(readiness['warnings'])}"
            )
        validate_threadsdash_draft_payload_strict(payload)
        out_path = (
            dirs["exports"] / f"supabase_drafts_{campaign['slug']}_{export_id}.json"
        )
        result: dict[str, Any] = {
            "schema": "campaign_factory.supabase_export.v1",
            "campaign": campaign["slug"],
            "userId": user_id,
            "variation": variation_result,
            "dryRun": dry_run,
            "createdAt": utc_now(),
            "draftCount": len(payload["drafts"]),
            "scheduleMode": normalized_schedule_mode,
            "schedulingOwner": "threadsdashboard_campaign_schedule_api",
            "scheduleHandoffRequired": normalized_schedule_mode in {"preview", "live"},
            "payload": payload,
            "readiness": readiness,
            "supabase": {"attempted": False, "media": [], "posts": []},
            "dashboardIngest": {
                "attempted": False,
                "dryRun": dry_run,
                "postIds": [],
                "media": dashboard_ingest_media,
            },
            "path": str(out_path),
            "pipelineJobId": pipeline_job["id"],
        }
        if not dry_run:
            if _legacy_supabase_writes_enabled():
                if normalized_schedule_mode == "preview":
                    preview_cleanup_client = SupabaseRestClient(
                        supabase_url.rstrip("/"), supabase_service_role_key
                    )
                    result["previewCleanup"] = _delete_existing_preview_schedule_rows(
                        preview_cleanup_client,
                        user_id=user_id,
                        campaign_slug=campaign["slug"],
                    )
                result["supabase"] = _write_supabase(
                    factory,
                    payload["drafts"],
                    user_id=user_id,
                    supabase_url=supabase_url,
                    service_role_key=supabase_service_role_key,
                    bucket=supabase_storage_bucket,
                )
            else:
                if normalized_schedule_mode != "draft":
                    raise ValueError(
                        "Campaign Factory preview/live exports must go through ThreadsDashboard scheduling APIs; "
                        "raw Supabase writes require CAMPAIGN_FACTORY_ENABLE_LEGACY_SUPABASE_WRITES=1"
                    )
                result["dashboardIngest"] = _post_threadsdash_draft_ingest(
                    payload,
                    ingest_url=threadsdash_ingest_url,
                    ingest_secret=threadsdash_ingest_secret,
                )
                reconciled_post_ids = _reconcile_dashboard_ingest_post_ids(
                    payload=payload,
                    ingest_result=result["dashboardIngest"],
                    user_id=user_id,
                    supabase_url=supabase_url,
                    supabase_service_role_key=supabase_service_role_key,
                )
                result["dashboardIngest"] = {
                    **result["dashboardIngest"],
                    "postIds": reconciled_post_ids,
                    "reconciled": True,
                    "postKeys": _threadsdash_ingest_post_keys(payload),
                    "media": dashboard_ingest_media,
                }
                result["supabase"] = {
                    "attempted": False,
                    "disabled": True,
                    "reason": "dashboard_ingest_boundary_required",
                    "media": [],
                    "posts": [],
                }
        out_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        factory.conn.execute(
            "INSERT INTO threadsdash_exports (id, campaign_id, manifest_path, user_id, dry_run, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                export_id,
                campaign["id"],
                str(out_path),
                user_id,
                1 if dry_run else 0,
                "dry_run" if dry_run else "exported",
                utc_now(),
            ),
        )
        export_label = (
            "Dry-run"
            if dry_run
            else (
                "Draft"
                if normalized_schedule_mode == "draft"
                else (
                    "Preview schedule"
                    if normalized_schedule_mode == "preview"
                    else "Live"
                )
            )
        )
        media_ids = [
            item.get("id") for item in (result.get("supabase") or {}).get("media", [])
        ]
        supabase_post_ids = [
            item.get("id") for item in (result.get("supabase") or {}).get("posts", [])
        ]
        dashboard_post_ids = list(
            (result.get("dashboardIngest") or {}).get("postIds") or []
        )
        post_ids = supabase_post_ids or dashboard_post_ids
        factory.record_event(
            "threadsdash_export_created",
            campaign_id=campaign["id"],
            threadsdash_export_id=export_id,
            pipeline_job_id=pipeline_job["id"],
            status="success" if not readiness.get("warnings") else "warning",
            message=f"{export_label} ThreadsDash draft export created: {len(payload['drafts'])} drafts",
            metadata={
                "manifestPath": str(out_path),
                "draftCount": len(payload["drafts"]),
                "dryRun": dry_run,
                "schedulingOwner": "threadsdashboard_campaign_schedule_api",
                "scheduleHandoffRequired": normalized_schedule_mode
                in {"preview", "live"},
                "mediaIds": media_ids,
                "postIds": post_ids,
                "blockingReasons": readiness.get("blockingReasons") or [],
                "warnings": readiness.get("warnings") or [],
                "scheduleMode": normalized_schedule_mode,
                "previewCleanup": result.get("previewCleanup") or {},
            },
            commit=False,
        )
        factory.conn.commit()
        factory.finish_pipeline_job(
            pipeline_job["id"],
            {
                "manifestPath": str(out_path),
                "draftCount": len(payload["drafts"]),
                "dryRun": dry_run,
                "mediaIds": media_ids,
                "postIds": post_ids,
                "scheduleMode": normalized_schedule_mode,
                "previewCleanup": result.get("previewCleanup") or {},
            },
        )
        return result
    except Exception as exc:
        failed_path = (
            dirs["exports"]
            / f"supabase_drafts_{campaign['slug']}_{locals().get('export_id', pipeline_job['id'])}_failed.json"
        )
        failed_payload = {
            "schema": "campaign_factory.supabase_export_failure.v1",
            "campaign": campaign["slug"],
            "userId": user_id,
            "dryRun": dry_run,
            "createdAt": utc_now(),
            "scheduleMode": normalized_schedule_mode,
            "pipelineJobId": pipeline_job["id"],
            "error": str(exc),
        }
        failed_path.parent.mkdir(parents=True, exist_ok=True)
        failed_path.write_text(
            json.dumps(failed_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        factory.conn.execute(
            "INSERT OR REPLACE INTO threadsdash_exports (id, campaign_id, manifest_path, user_id, dry_run, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(locals().get("export_id", pipeline_job["id"])),
                campaign["id"],
                str(failed_path),
                user_id,
                1 if dry_run else 0,
                "failed",
                utc_now(),
            ),
        )
        factory.record_event(
            "threadsdash_export_created",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"ThreadsDash export failed: {exc}",
            metadata={"error": str(exc), "dryRun": dry_run},
        )
        factory.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def preflight_supabase(
    *,
    supabase_url: str | None,
    supabase_service_role_key: str | None,
    supabase_storage_bucket: str = "media",
) -> dict[str, Any]:
    if not supabase_url or not supabase_service_role_key:
        raise ValueError(
            "supabase_url and supabase_service_role_key are required for Supabase preflight"
        )
    client = SupabaseRestClient(supabase_url.rstrip("/"), supabase_service_role_key)
    checks = []
    checks.append(
        _preflight_check(
            "auth_posts_read",
            lambda: client.select("posts", {"select": "id", "limit": "1"}),
        )
    )
    checks.append(
        _preflight_check(
            "media_bucket_exists",
            lambda: client.get_storage_bucket(supabase_storage_bucket),
        )
    )
    checks.append(
        _preflight_check(
            "media_schema",
            lambda: client.select(
                "media",
                {
                    "select": "id,user_id,file_name,file_url,file_type,file_size,mime_type,storage_url,storage_path,tags",
                    "limit": "1",
                },
            ),
        )
    )
    checks.append(
        _preflight_check(
            "posts_schema",
            lambda: client.select(
                "posts",
                {
                    "select": "id,user_id,platform,status,media_type,ig_media_type,instagram_account_id,media_urls,metadata,scheduled_for",
                    "limit": "1",
                },
            ),
        )
    )
    passed = all(check["ok"] for check in checks)
    return {
        "schema": "campaign_factory.supabase_preflight.v1",
        "checkedAt": utc_now(),
        "bucket": supabase_storage_bucket,
        "ok": passed,
        "checks": checks,
        "blockingReasons": [check["name"] for check in checks if not check["ok"]],
    }


def verify_threadsdash_export(
    *,
    export_result_or_path: dict[str, Any] | str | Path,
    supabase_url: str | None,
    supabase_service_role_key: str | None,
) -> dict[str, Any]:
    if not supabase_url or not supabase_service_role_key:
        raise ValueError(
            "supabase_url and supabase_service_role_key are required for export verification"
        )
    payload = _load_export_result(export_result_or_path)
    client = SupabaseRestClient(supabase_url.rstrip("/"), supabase_service_role_key)
    media_checks = [
        _verify_media_row(client, media)
        for media in (payload.get("supabase") or {}).get("media", [])
    ]
    post_checks = [
        _verify_post_row(client, post)
        for post in (payload.get("supabase") or {}).get("posts", [])
    ]
    checks = media_checks + post_checks
    ok = bool(checks) and all(check["ok"] for check in checks)
    return {
        "schema": "campaign_factory.threadsdash_export_verification.v1",
        "checkedAt": utc_now(),
        "campaign": payload.get("campaign"),
        "exportPath": str(export_result_or_path)
        if isinstance(export_result_or_path, (str, Path))
        else payload.get("path"),
        "ok": ok,
        "media": media_checks,
        "posts": post_checks,
        "blockingReasons": [
            f"{check['type']}:{check.get('id') or 'missing'}:{reason}"
            for check in checks
            for reason in check.get("blockingReasons", [])
        ],
    }


def safe_live_smoke_export(
    factory: CampaignFactory,
    *,
    campaign_slug: str,
    user_id: str,
    supabase_url: str | None,
    supabase_service_role_key: str | None,
    supabase_storage_bucket: str = "media",
    allow_warnings: bool = False,
) -> dict[str, Any]:
    campaign = factory.campaign_by_slug(campaign_slug)
    pipeline_job = factory.create_pipeline_job(
        "threadsdash_export",
        campaign["id"],
        {
            "mode": "safe_live_smoke",
            "campaign": campaign_slug,
            "userId": user_id,
            "hasSupabaseUrl": bool(supabase_url),
            "hasSupabaseServiceRoleKey": bool(supabase_service_role_key),
            "supabaseStorageBucket": supabase_storage_bucket,
            "allowWarnings": allow_warnings,
        },
    )
    factory.start_pipeline_job(pipeline_job["id"])
    try:
        preflight = preflight_supabase(
            supabase_url=supabase_url,
            supabase_service_role_key=supabase_service_role_key,
            supabase_storage_bucket=supabase_storage_bucket,
        )
        factory.record_event(
            "supabase_preflight_checked",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="success" if preflight["ok"] else "failure",
            message=f"Supabase preflight {'passed' if preflight['ok'] else 'failed'}",
            metadata={
                "ok": preflight["ok"],
                "blockingReasons": preflight.get("blockingReasons") or [],
            },
            commit=False,
        )
        if not preflight["ok"]:
            result = {
                "schema": "campaign_factory.safe_live_smoke.v1",
                "ok": False,
                "stage": "preflight",
                "preflight": preflight,
                "blockingReasons": preflight["blockingReasons"],
                "pipelineJobId": pipeline_job["id"],
            }
            factory.conn.commit()
            factory.fail_pipeline_job(
                pipeline_job["id"], "Supabase preflight failed", result
            )
            return result
        candidate = _best_live_smoke_candidate(factory, campaign_slug=campaign_slug)
        if not candidate:
            result = {
                "schema": "campaign_factory.safe_live_smoke.v1",
                "ok": False,
                "stage": "candidate",
                "preflight": preflight,
                "blockingReasons": ["no_locally_eligible_approved_asset"],
                "pipelineJobId": pipeline_job["id"],
            }
            factory.fail_pipeline_job(
                pipeline_job["id"], "No locally eligible approved asset", result
            )
            return result
        export = export_threadsdash(
            factory,
            campaign_slug=campaign_slug,
            user_id=user_id,
            dry_run=False,
            supabase_url=supabase_url,
            supabase_service_role_key=supabase_service_role_key,
            supabase_storage_bucket=supabase_storage_bucket,
            allow_warnings=allow_warnings,
            max_drafts=1,
            rendered_asset_ids=[candidate["id"]],
        )
        verification = verify_threadsdash_export(
            export_result_or_path=export,
            supabase_url=supabase_url,
            supabase_service_role_key=supabase_service_role_key,
        )
        factory.record_event(
            "threadsdash_export_verified",
            campaign_id=campaign["id"],
            rendered_asset_id=candidate["id"],
            pipeline_job_id=pipeline_job["id"],
            status="success" if verification["ok"] else "failure",
            message=f"Safe live smoke {'verified' if verification['ok'] else 'verification failed'}",
            metadata={
                "ok": verification["ok"],
                "blockingReasons": verification.get("blockingReasons") or [],
                "exportPath": export.get("path"),
            },
        )
        result = {
            "schema": "campaign_factory.safe_live_smoke.v1",
            "ok": verification["ok"],
            "stage": "complete" if verification["ok"] else "verify",
            "preflight": preflight,
            "export": {
                "path": export.get("path"),
                "draftCount": export.get("draftCount"),
                "renderedAssetId": candidate["id"],
                "posts": (export.get("supabase") or {}).get("posts", []),
                "media": (export.get("supabase") or {}).get("media", []),
            },
            "verification": verification,
            "blockingReasons": verification["blockingReasons"],
            "pipelineJobId": pipeline_job["id"],
        }
        if verification["ok"]:
            factory.finish_pipeline_job(pipeline_job["id"], result)
        else:
            factory.fail_pipeline_job(
                pipeline_job["id"], "Safe live smoke verification failed", result
            )
        return result
    except Exception as exc:
        factory.record_event(
            "threadsdash_export_verified",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"Safe live smoke failed: {exc}",
            metadata={"error": str(exc)},
        )
        factory.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def _best_live_smoke_candidate(
    factory: CampaignFactory, *, campaign_slug: str
) -> dict[str, Any] | None:
    dashboard = factory.dashboard(campaign_slug)
    candidates = []
    for asset in dashboard.get("rendered") or []:
        readiness = asset.get("export_readiness") or {}
        if asset.get("review_state") != "approved":
            continue
        if readiness.get("blockingReasons"):
            continue
        candidates.append(asset)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda asset: (
            (asset.get("export_readiness") or {}).get("operatorScore") or 0
        ),
        reverse=True,
    )[0]


def evaluate_export_readiness(
    factory: CampaignFactory,
    *,
    campaign_slug: str,
    user_id: str,
    supabase_url: str | None = None,
    supabase_service_role_key: str | None = None,
    limit: int = 1000,
    content_pillar: str | None = None,
    cta_type: str | None = None,
    language: str | None = None,
    rendered_asset_ids: list[str] | None = None,
    schedule_mode: str = "draft",
    publish_mode: str | None = None,
) -> dict[str, Any]:
    campaign = factory.campaign_by_slug(campaign_slug)
    normalized_schedule_mode = _normalize_schedule_mode(schedule_mode)
    normalized_publish_mode = _normalize_publish_mode(publish_mode)
    pipeline_job = factory.create_pipeline_job(
        "export_readiness",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "userId": user_id,
            "hasSupabaseUrl": bool(supabase_url),
            "hasSupabaseServiceRoleKey": bool(supabase_service_role_key),
            "limit": limit,
            "contentPillar": content_pillar,
            "ctaType": cta_type,
            "language": language,
            "renderedAssetIds": rendered_asset_ids or [],
            "scheduleMode": normalized_schedule_mode,
        },
    )
    factory.start_pipeline_job(pipeline_job["id"])
    try:
        dashboard = factory.dashboard(campaign_slug)
        payload = build_draft_payloads(
            factory,
            campaign_slug=campaign_slug,
            user_id=user_id,
            content_pillar=content_pillar,
            cta_type=cta_type,
            language=language,
            rendered_asset_ids=rendered_asset_ids,
            schedule_mode=normalized_schedule_mode,
            publish_mode=normalized_publish_mode,
        )
        draft_asset_ids = {draft["renderedAssetId"] for draft in payload["drafts"]}
        drafts_by_asset: dict[str, list[dict[str, Any]]] = {}
        for draft in payload["drafts"]:
            drafts_by_asset.setdefault(draft["renderedAssetId"], []).append(draft)
        contract_blockers = _draft_payload_contract_blockers(payload)
        batch_findings = _batch_guardrail_findings(payload["drafts"])
        usage: dict[str, Any] | None = None
        usage_error: str | None = None
        if supabase_url and supabase_service_role_key:
            try:
                usage = summarize_threadsdash_usage(
                    factory,
                    campaign_slug=campaign_slug,
                    user_id=user_id,
                    supabase_url=supabase_url,
                    supabase_service_role_key=supabase_service_role_key,
                    limit=limit,
                )
            except Exception as exc:
                usage_error = str(exc)
        else:
            usage_error = "supabase_url and supabase_service_role_key are required for live usage checks"

        usage_by_asset = {
            item["renderedAssetId"]: item for item in (usage or {}).get("assets", [])
        }
        source_usage = (usage or {}).get("sourceUsage") or {}
        caption_hash_usage = (usage or {}).get("captionHashUsage") or {}
        rows = []
        for asset in dashboard["rendered"]:
            local = asset.get("export_readiness") or {}
            blocking = list(local.get("blockingReasons") or [])
            warnings = list(local.get("warnings") or [])
            asset_usage = (
                usage_by_asset.get(asset["id"], {}).get("usage") or _empty_usage()
            )
            source_id = asset["source_asset_id"]
            source_counts = source_usage.get(source_id) or _empty_usage()
            asset_drafts = drafts_by_asset.get(asset["id"], [])
            audio_deferred_to_notify = bool(asset_drafts) and all(
                _draft_notify_audio_deferred(draft) for draft in asset_drafts
            )
            if audio_deferred_to_notify:
                blocking = [
                    reason
                    for reason in blocking
                    if not _is_deferred_notify_audio_blocker(reason)
                ]
                warnings.append("native_audio_deferred_to_notify_handoff")
            caption_hashes = {
                draft.get("captionHash")
                for draft in asset_drafts
                if draft.get("captionHash")
            }
            if asset_usage.get("published", 0) > 0:
                blocking.append("exact_render_published")
            if asset_usage.get("draft", 0) > 0 or asset_usage.get("scheduled", 0) > 0:
                warnings.append("exact_render_already_queued")
            if source_counts.get("total", 0) > 1:
                warnings.append("source_family_reuse")
            for caption_hash in caption_hashes:
                caption_usage = caption_hash_usage.get(caption_hash) or _empty_usage()
                if caption_usage.get("total", 0) > 0:
                    warnings.append("caption_reuse")
                if (
                    len(
                        {
                            post.get("instagramAccountId") or post.get("accountId")
                            for post in caption_usage.get("posts", [])
                        }
                    )
                    >= 3
                ):
                    warnings.append("caption_reuse_multi_account")
            for draft in asset_drafts:
                blocking.extend(contract_blockers)
                findings = batch_findings.get(_draft_key(draft), {})
                warnings.extend(findings.get("warnings") or [])
                blocking.extend(findings.get("blocking") or [])
                audio_intent = draft.get("audioIntent") or (
                    (draft.get("metadata") or {}).get("campaign_factory") or {}
                ).get("audio_intent")
                if not _audio_intent_allows_live(
                    audio_intent
                ) and not _draft_notify_audio_deferred(draft):
                    blocking.append(
                        "campaign_audio_unresolved: select audio before ThreadsDashboard export"
                    )
                compatible, mismatch_reason, _profile = (
                    factory.account_compatible_with_model(
                        asset.get("model_slug")
                        or asset.get("modelId")
                        or draft.get("modelId")
                        or "",
                        instagram_account_id=draft.get("instagramAccountId"),
                    )
                )
                if not compatible and mismatch_reason:
                    blocking.append(mismatch_reason)
            if asset["id"] in draft_asset_ids and usage_error:
                blocking.append("usage_check_unavailable")
            state = "blocked" if blocking else ("warning" if warnings else "ready")
            operator_score = _operator_score(
                state=state,
                warnings=warnings,
                blocking=blocking,
                upload_ready=(
                    (asset.get("latest_audit") or {}).get("readinessSummary") or {}
                ).get("uploadReady"),
                asset_usage=asset_usage,
                performance_score=asset.get("performanceScore"),
            )
            rows.append(
                {
                    "renderedAssetId": asset["id"],
                    "sourceAssetId": asset["source_asset_id"],
                    "filename": asset["filename"],
                    "reviewState": asset["review_state"],
                    "auditStatus": asset["audit_status"],
                    "overallVerdict": (asset.get("latest_audit") or {}).get(
                        "overallVerdict"
                    ),
                    "uploadReady": (
                        (asset.get("latest_audit") or {}).get("readinessSummary") or {}
                    ).get("uploadReady"),
                    "publishability": local.get("publishability") or {},
                    "usage": asset_usage,
                    "performanceScore": asset.get("performanceScore"),
                    "latestPerformance": asset.get("latestPerformance"),
                    "sourcePerformance": asset.get("sourcePerformance"),
                    "captionPerformance": asset.get("captionPerformance"),
                    "recipePerformance": asset.get("recipePerformance"),
                    "draftDestinations": [
                        {
                            "accountId": draft.get("accountId"),
                            "instagramAccountId": draft.get("instagramAccountId"),
                            "captionHash": draft.get("captionHash"),
                            "contentPillar": draft.get("contentPillar"),
                            "ctaType": draft.get("ctaType"),
                            "language": draft.get("language"),
                            "distributionSurface": draft.get("distributionSurface"),
                            "smartLink": draft.get("smartLink"),
                            "audioIntentStatus": (draft.get("audioIntent") or {}).get(
                                "status"
                            ),
                        }
                        for draft in asset_drafts
                    ],
                    "operatorScore": operator_score,
                    "state": state,
                    "willExport": asset["id"] in draft_asset_ids,
                    "blockingReasons": sorted(set(blocking)),
                    "warnings": sorted(set(warnings)),
                }
            )

        export_rows = [row for row in rows if row["willExport"]]
        global_blocking = []
        if not export_rows:
            global_blocking.append("no_approved_assets")
        if usage_error:
            global_blocking.append(usage_error)
        for row in export_rows:
            global_blocking.extend(
                [
                    f"{row['renderedAssetId']}:{reason}"
                    for reason in row["blockingReasons"]
                ]
            )
        live_allowed = not global_blocking
        result = {
            "schema": "campaign_factory.export_readiness.v1",
            "campaign": campaign_slug,
            "userId": user_id,
            "checkedAt": utc_now(),
            "expectedDraftCount": len(payload["drafts"]),
            "scheduleMode": normalized_schedule_mode,
            "schedulingOwner": "threadsdashboard_campaign_schedule_api",
            "scheduleHandoffRequired": normalized_schedule_mode in {"preview", "live"},
            "liveExportAllowed": live_allowed,
            "blockingReasons": sorted(set(global_blocking)),
            "warnings": sorted(
                set(
                    f"{row['renderedAssetId']}:{warning}"
                    for row in export_rows
                    for warning in row["warnings"]
                )
            ),
            "usageChecked": usage is not None,
            "usageError": usage_error,
            "assets": sorted(rows, key=lambda row: row["operatorScore"], reverse=True),
            "pipelineJobId": pipeline_job["id"],
        }
        factory.record_event(
            "export_readiness_checked",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="success" if result["liveExportAllowed"] else "warning",
            message=f"Export readiness checked: {result['expectedDraftCount']} expected drafts",
            metadata={
                "expectedDraftCount": result["expectedDraftCount"],
                "liveExportAllowed": result["liveExportAllowed"],
                "blockingReasonCount": len(result["blockingReasons"]),
                "warningCount": len(result["warnings"]),
                "usageChecked": result["usageChecked"],
            },
        )
        factory.finish_pipeline_job(
            pipeline_job["id"],
            {
                "expectedDraftCount": result["expectedDraftCount"],
                "liveExportAllowed": result["liveExportAllowed"],
                "blockingReasonCount": len(result["blockingReasons"]),
                "warningCount": len(result["warnings"]),
                "usageChecked": result["usageChecked"],
            },
        )
        return result
    except Exception as exc:
        factory.record_event(
            "export_readiness_checked",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"Export readiness failed: {exc}",
            metadata={"error": str(exc)},
        )
        factory.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def _upload_media_for_dashboard_ingest(
    factory: CampaignFactory,
    payload: dict[str, Any],
    *,
    user_id: str,
    supabase_url: str | None,
    service_role_key: str | None,
    bucket: str,
) -> list[dict[str, Any]]:
    if not supabase_url or not service_role_key:
        raise ValueError(
            "supabase_url and supabase_service_role_key are required for dashboard ingest media upload"
        )
    client = SupabaseRestClient(supabase_url.rstrip("/"), service_role_key)
    uploaded_by_path: dict[str, dict[str, Any]] = {}
    media_results: list[dict[str, Any]] = []
    for draft in payload.get("drafts") or []:
        if not isinstance(draft, dict):
            continue
        rendered_asset_id = str(draft.get("renderedAssetId") or "draft")
        if not _remote_media_url_blockers(draft, rendered_asset_id=rendered_asset_id):
            continue
        local_value = draft.get("_localFilePath")
        if not isinstance(local_value, str) or not local_value.strip():
            continue
        local_path = Path(local_value)
        media_cache_key = str(draft.get("campaignFactoryMediaKey") or local_path)
        if media_cache_key not in uploaded_by_path:
            try:
                media_ref = _upload_media(
                    client,
                    bucket=bucket,
                    user_id=user_id,
                    local_path=local_path,
                    tags=list(draft.get("_tags") or []),
                    media_key=draft.get("campaignFactoryMediaKey"),
                )
            except Exception as exc:
                blockers = _remote_media_url_blockers(
                    draft, rendered_asset_id=rendered_asset_id
                )
                raise ValueError(
                    f"export blocked by handoff manifest: {', '.join(blockers)}; media upload failed: {exc}"
                ) from exc
            uploaded_by_path[media_cache_key] = media_ref
            media_results.append(media_ref)
        media_ref = uploaded_by_path[media_cache_key]
        media_items = draft.get("media")
        if isinstance(media_items, list) and media_items:
            first = media_items[0]
            if isinstance(first, dict):
                first["id"] = media_ref["id"]
                first["url"] = media_ref["publicUrl"]
        _hydrate_surface_media_items_for_uploaded_media(draft, media_ref)
        draft["metadata"] = _draft_metadata(draft)
    return media_results


def _write_supabase(
    factory: CampaignFactory,
    drafts: list[dict[str, Any]],
    *,
    user_id: str,
    supabase_url: str | None,
    service_role_key: str | None,
    bucket: str,
) -> dict[str, Any]:
    _require_legacy_supabase_writes()
    if not supabase_url or not service_role_key:
        raise ValueError(
            "supabase_url and supabase_service_role_key are required when dry_run is false"
        )
    client = SupabaseRestClient(supabase_url.rstrip("/"), service_role_key)
    media_results = []
    post_results = []
    uploaded_by_path: dict[str, dict[str, Any]] = {}
    mirror_results = []
    for draft in drafts:
        local_path = Path(draft.pop("_localFilePath"))
        tags = draft.pop("_tags", [])
        campaign_ref = draft.get("campaignId")
        try:
            campaign_internal_id = (
                factory.campaign_by_slug(str(campaign_ref))["id"]
                if campaign_ref
                else None
            )
        except ValueError:
            campaign_internal_id = campaign_ref
        existing_post = _select_existing_campaign_factory_post(
            client, user_id=user_id, post_key=draft.get("campaignFactoryPostKey")
        )
        if existing_post:
            media_ref = _media_ref_from_existing_post(existing_post)
            _hydrate_surface_media_items_for_uploaded_media(draft, media_ref)
            refreshed = _update_existing_draft_post(
                client,
                draft=draft,
                media_ref=media_ref,
                post_id=str(existing_post.get("id")),
            )
            post_row = {
                "id": existing_post.get("id"),
                "status": refreshed.get("status")
                or existing_post.get("status", draft.get("status") or "draft"),
                "platform": existing_post.get("platform", "instagram"),
                "metadata": refreshed.get("metadata")
                or draft.get("metadata")
                or _draft_metadata(draft),
                "reused": True,
            }
        else:
            media_cache_key = draft.get("campaignFactoryMediaKey") or str(local_path)
            if media_cache_key not in uploaded_by_path:
                media_ref = _upload_media(
                    client,
                    bucket=bucket,
                    user_id=user_id,
                    local_path=local_path,
                    tags=tags,
                    media_key=draft.get("campaignFactoryMediaKey"),
                )
                uploaded_by_path[media_cache_key] = media_ref
                media_results.append(media_ref)
            media_ref = uploaded_by_path[media_cache_key]
            draft["media"][0]["id"] = media_ref["id"]
            draft["media"][0]["url"] = media_ref["publicUrl"]
            _hydrate_surface_media_items_for_uploaded_media(draft, media_ref)
            post_row = _insert_draft_post(client, draft=draft, media_ref=media_ref)
        post_graph_id = factory.ensure_graph_node(
            "threadsdash_post",
            external_system="threadsdash.posts",
            external_id=str(post_row.get("id")),
            payload={
                "postId": post_row.get("id"),
                "status": post_row.get("status"),
                "renderedAssetId": draft.get("renderedAssetId"),
                "renderedAssetGraphId": draft.get("renderedAssetGraphId")
                or draft.get("graphId"),
            },
        )
        factory.ensure_graph_edge_strict(
            draft.get("renderedAssetGraphId") or draft.get("graphId"),
            post_graph_id,
            "rendered_asset_to_threadsdash_post",
            evidence={
                "exportId": draft.get("campaignFactoryExportId"),
                "status": post_row.get("status"),
            },
            campaign_id=campaign_internal_id,
            source_operation="threadsdash_export",
        )
        mirror = _upsert_threadsdash_graph_mirror(
            client,
            draft=draft,
            post_row=post_row,
            media_ref=media_ref,
            post_graph_id=post_graph_id,
        )
        mirror_results.append(mirror)
        if mirror.get("errors"):
            factory.create_exception(
                reason_code="threadsdash_mirror_sync_failed",
                severity="high",
                campaign_id=campaign_internal_id,
                entity_graph_id=post_graph_id,
                payload={
                    "postId": post_row.get("id"),
                    "postGraphId": post_graph_id,
                    "exportRunId": draft.get("campaignFactoryExportId"),
                    "draftKey": draft.get("campaignFactoryDraftKey"),
                    "mediaKey": draft.get("campaignFactoryMediaKey"),
                    "postKey": draft.get("campaignFactoryPostKey"),
                    "errors": mirror.get("errors"),
                },
                commit=False,
            )
        post_results.append(post_row)
    factory.conn.commit()
    return {
        "attempted": True,
        "media": media_results,
        "posts": post_results,
        "mirror": mirror_results,
        "mirrorErrors": [
            error for item in mirror_results for error in item.get("errors", [])
        ],
    }


def _legacy_supabase_writes_enabled() -> bool:
    return os.environ.get("CAMPAIGN_FACTORY_ENABLE_LEGACY_SUPABASE_WRITES") == "1"


def _require_legacy_supabase_writes() -> None:
    if not _legacy_supabase_writes_enabled():
        raise ValueError(
            "raw ThreadsDashboard Supabase post writes are disabled; use Dashboard draft ingest "
            "or set CAMPAIGN_FACTORY_ENABLE_LEGACY_SUPABASE_WRITES=1 for explicit migration/backfill work"
        )


def _threadsdash_draft_post_key(draft: dict[str, Any]) -> str | None:
    metadata = draft.get("metadata") if isinstance(draft.get("metadata"), dict) else {}
    campaign_factory = (
        metadata.get("campaign_factory")
        if isinstance(metadata.get("campaign_factory"), dict)
        else {}
    )
    manifest = (
        campaign_factory.get("handoff_manifest")
        if isinstance(campaign_factory.get("handoff_manifest"), dict)
        else {}
    )
    for value in (
        draft.get("campaignFactoryPostKey"),
        draft.get("campaign_factory_post_key"),
        campaign_factory.get("post_key"),
        campaign_factory.get("draft_key"),
        campaign_factory.get("rendered_asset_id"),
        campaign_factory.get("asset_id"),
        manifest.get("asset_id"),
        manifest.get("rendered_asset_id"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _threadsdash_ingest_idempotency_key(payload: dict[str, Any]) -> str:
    drafts = payload.get("drafts") if isinstance(payload.get("drafts"), list) else []
    post_keys = [
        key
        for key in (
            _threadsdash_draft_post_key(draft)
            for draft in drafts
            if isinstance(draft, dict)
        )
        if key
    ]
    if len(post_keys) == 1:
        return post_keys[0]
    fingerprint_source = post_keys or [
        json.dumps(payload, sort_keys=True, ensure_ascii=False)
    ]
    digest = hashlib.sha256(
        json.dumps(fingerprint_source, sort_keys=True).encode("utf-8")
    ).hexdigest()[:32]
    return f"campaign-factory-draft-ingest:{digest}"


def _threadsdash_ingest_post_keys(payload: dict[str, Any]) -> list[str]:
    drafts = payload.get("drafts") if isinstance(payload.get("drafts"), list) else []
    keys: list[str] = []
    for draft in drafts:
        if not isinstance(draft, dict):
            continue
        key = _threadsdash_draft_post_key(draft)
        if key and key not in keys:
            keys.append(key)
    return keys


def _dashboard_ingest_backoff_seconds(attempt: int) -> float:
    index = max(0, min(attempt - 1, len(DASHBOARD_INGEST_BACKOFF_SECONDS) - 1))
    return DASHBOARD_INGEST_BACKOFF_SECONDS[index]


def _is_retryable_dashboard_ingest_http_status(status: int) -> bool:
    return status in {408, 409, 425, 429} or status >= 500


def _threadsdash_allowed_ingest_hosts() -> set[str]:
    configured = {
        host.strip().lower().rstrip(".")
        for host in os.environ.get("THREADSDASH_ALLOWED_INGEST_HOSTS", "").split(",")
        if host.strip()
    }
    return set(DEFAULT_THREADSDASH_INGEST_HOSTS) | configured


def _is_local_dashboard_ingest_host(host: str) -> bool:
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback


def _is_blocked_dashboard_ingest_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_threadsdash_ingest_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if not parsed.scheme or not host:
        raise ValueError(
            "ThreadsDashboard ingest URL must include an https scheme and hostname"
        )
    allow_local = (
        os.environ.get("CAMPAIGN_FACTORY_ALLOW_LOCAL_THREADSDASH_INGEST") == "1"
    )
    if parsed.username or parsed.password:
        raise ValueError("ThreadsDashboard ingest URL must not include credentials")
    if parsed.fragment:
        raise ValueError("ThreadsDashboard ingest URL must not include a fragment")
    if parsed.query:
        raise ValueError(
            "ThreadsDashboard ingest URL must not include query parameters"
        )
    if parsed.path.rstrip("/") != THREADSDASH_INGEST_PATH:
        raise ValueError(
            f"ThreadsDashboard ingest URL path must be {THREADSDASH_INGEST_PATH}"
        )
    if parsed.scheme != "https":
        if not (
            allow_local
            and parsed.scheme == "http"
            and _is_local_dashboard_ingest_host(host)
        ):
            raise ValueError("ThreadsDashboard ingest URL must use https")
    if _is_local_dashboard_ingest_host(host):
        if not allow_local:
            raise ValueError(
                "ThreadsDashboard ingest URL cannot target localhost unless local ingest is explicitly enabled"
            )
    elif _is_blocked_dashboard_ingest_ip(host):
        raise ValueError(
            "ThreadsDashboard ingest URL cannot target private or reserved IP addresses"
        )
    elif host not in _threadsdash_allowed_ingest_hosts():
        raise ValueError("ThreadsDashboard ingest URL host is not allowed")
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, THREADSDASH_INGEST_PATH, "", "", ""))


def _threadsdash_ingest_signature(
    body: bytes, *, secret: str, timestamp: str, nonce: str
) -> str:
    signing_input = (
        timestamp.encode("ascii") + b"." + nonce.encode("ascii") + b"." + body
    )
    digest = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).hexdigest()
    return f"{CAMPAIGN_FACTORY_INGEST_SIGNATURE_VERSION}={digest}"


def _post_threadsdash_draft_ingest(
    payload: dict[str, Any],
    *,
    ingest_url: str | None,
    ingest_secret: str | None,
) -> dict[str, Any]:
    url = (
        ingest_url
        or os.environ.get("THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL")
        or os.environ.get("CAMPAIGN_FACTORY_DRAFT_INGEST_URL")
    )
    secret = ingest_secret or os.environ.get("CAMPAIGN_FACTORY_INGEST_SECRET")
    if not url:
        raise ValueError(
            "threadsdash_ingest_url or THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL is required when dry_run is false"
        )
    if not secret:
        raise ValueError(
            "threadsdash_ingest_secret or CAMPAIGN_FACTORY_INGEST_SECRET is required when dry_run is false"
        )
    safe_url = _validate_threadsdash_ingest_url(url)
    body = dict(payload)
    body["dryRun"] = False
    idempotency_key = _threadsdash_ingest_idempotency_key(body)
    body_bytes = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    last_error: str | None = None
    last_empty_response: dict[str, Any] | None = None
    for attempt in range(1, DASHBOARD_INGEST_MAX_ATTEMPTS + 1):
        signature_timestamp = str(int(time.time()))
        signature_nonce = uuid.uuid4().hex
        signature = _threadsdash_ingest_signature(
            body_bytes,
            secret=secret,
            timestamp=signature_timestamp,
            nonce=signature_nonce,
        )
        request = Request(
            safe_url,
            data=body_bytes,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Campaign-Factory-Signature": signature,
                "X-Campaign-Factory-Timestamp": signature_timestamp,
                "X-Campaign-Factory-Nonce": signature_nonce,
                "X-Idempotency-Key": idempotency_key,
            },
        )
        try:
            with _open_threadsdash_ingest_request(request, timeout=30) as response:
                response_body = response.read().decode("utf-8")
                parsed = json.loads(response_body) if response_body else {}
                result = {
                    "attempted": True,
                    "dryRun": False,
                    "statusCode": getattr(response, "status", 200),
                    "postIds": parsed.get("postIds") or [],
                    "response": parsed,
                    "attempts": attempt,
                }
                if result["postIds"]:
                    return result
                last_empty_response = {
                    **result,
                    "emptyPostIds": True,
                    "retryableFailure": "dashboard_ingest_empty_post_ids",
                }
                last_error = "Dashboard draft ingest returned empty postIds"
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if not _is_retryable_dashboard_ingest_http_status(exc.code):
                raise ValueError(
                    f"Dashboard draft ingest rejected export ({exc.code}): {detail}"
                ) from exc
            last_error = f"Dashboard draft ingest retryable HTTP {exc.code}: {detail}"
        except (TimeoutError, URLError) as exc:
            last_error = f"Dashboard draft ingest transport error: {exc}"
        if attempt < DASHBOARD_INGEST_MAX_ATTEMPTS:
            time.sleep(_dashboard_ingest_backoff_seconds(attempt))
    if last_empty_response is not None:
        return last_empty_response
    raise ValueError(
        f"Dashboard draft ingest failed after {DASHBOARD_INGEST_MAX_ATTEMPTS} attempts: {last_error}"
    )


def _select_threadsdash_posts_by_post_keys(
    client: SupabaseRestClient,
    *,
    user_id: str,
    post_keys: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for post_key in post_keys:
        selected = client.select(
            "posts",
            {
                "select": "id,user_id,status,campaign_factory_post_key,metadata",
                "user_id": f"eq.{user_id}",
                "campaign_factory_post_key": f"eq.{post_key}",
                "limit": "1",
            },
        )
        for row in selected:
            row_id = str(row.get("id") or "")
            if row_id and row_id not in seen_ids:
                seen_ids.add(row_id)
                rows.append(row)
    return rows


def _reconcile_dashboard_ingest_post_ids(
    *,
    payload: dict[str, Any],
    ingest_result: dict[str, Any],
    user_id: str,
    supabase_url: str | None,
    supabase_service_role_key: str | None,
) -> list[str]:
    post_ids = [
        str(post_id) for post_id in ingest_result.get("postIds") or [] if str(post_id)
    ]
    post_keys = _threadsdash_ingest_post_keys(payload)
    if not post_keys:
        if post_ids:
            return post_ids
        raise ValueError(
            "Dashboard draft ingest did not return postIds and no Campaign Factory post keys were available"
        )
    if not supabase_url or not supabase_service_role_key:
        raise ValueError(
            "supabase_url and supabase_service_role_key are required to reconcile Dashboard draft ingest"
        )
    client = SupabaseRestClient(supabase_url.rstrip("/"), supabase_service_role_key)
    rows = _select_threadsdash_posts_by_post_keys(
        client, user_id=user_id, post_keys=post_keys
    )
    found_by_key = {str(row.get("campaign_factory_post_key")): row for row in rows}
    missing = [post_key for post_key in post_keys if post_key not in found_by_key]
    if missing:
        raise ValueError(
            f"Dashboard draft ingest reconciliation failed; missing post keys: {', '.join(missing)}"
        )
    reconciled = [
        str(found_by_key[post_key].get("id"))
        for post_key in post_keys
        if found_by_key[post_key].get("id")
    ]
    if not reconciled:
        raise ValueError("Dashboard draft ingest reconciliation found no post ids")
    return reconciled


def _hydrate_surface_media_items_for_uploaded_media(
    draft: dict[str, Any], media_ref: dict[str, Any]
) -> None:
    content_surface = normalize_content_surface(
        draft.get("contentSurface") or draft.get("content_surface")
    )
    media_url = media_ref.get("publicUrl")
    if not isinstance(media_url, str) or not media_url.strip():
        return
    media_kind = (
        "image"
        if content_surface in {"feed_single", "feed_carousel", "story"}
        and _draft_media_types(draft)[0] == "image"
        else _draft_media_types(draft)[0]
    )
    publishability = (
        draft.get("publishability")
        if isinstance(draft.get("publishability"), dict)
        else {}
    )
    manifest = (
        draft.get("handoffManifest")
        if isinstance(draft.get("handoffManifest"), dict)
        else publishability.get("handoff_manifest")
    )
    if not isinstance(manifest, dict):
        return
    items = manifest.get("mediaItems")
    if not isinstance(items, list) or not items:
        items = [{"componentIndex": 0}]
    hydrated = []
    for index, item in enumerate(items):
        next_item = dict(item) if isinstance(item, dict) else {"componentIndex": index}
        if index == 0:
            next_item["url"] = media_url
            next_item["type"] = media_kind
        hydrated.append(next_item)
    manifest["mediaItems"] = hydrated
    draft["mediaItems"] = hydrated
    draft["handoffManifest"] = manifest
    if isinstance(draft.get("publishability"), dict):
        draft["publishability"]["handoff_manifest"] = manifest
    draft["metadata"] = _draft_metadata(draft)


def _upload_media(
    client: SupabaseRestClient,
    *,
    bucket: str,
    user_id: str,
    local_path: Path,
    tags: list[str],
    media_key: str | None = None,
) -> dict[str, Any]:
    if not local_path.exists():
        raise FileNotFoundError(local_path)
    content_type = mimetypes.guess_type(local_path.name)[0] or "video/mp4"
    file_type = "image" if content_type.startswith("image/") else "video"
    safe_name = "".join(
        ch if ch.isalnum() or ch in "._-" else "-" for ch in local_path.name
    )[:120]
    stable_key = media_key or _stable_export_key(
        "media", user_id, local_path.name, local_path.stat().st_size
    )
    storage_path = f"campaign_factory/{user_id}/{stable_key}-{safe_name}"
    try:
        existing_rows = client.select(
            "media",
            {
                "select": "id,file_name,file_url,storage_url,storage_path,url,tags",
                "storage_path": f"eq.{storage_path}",
                "limit": "1",
            },
        )
    except RuntimeError:
        existing_rows = []
    if existing_rows:
        row = existing_rows[0]
        public_url = (
            row.get("storage_url")
            or row.get("file_url")
            or row.get("url")
            or f"{client.url}/storage/v1/object/public/{quote(bucket)}/{quote(storage_path)}"
        )
        return {
            "id": row.get("id"),
            "publicUrl": public_url,
            "storagePath": storage_path,
            "fileName": row.get("file_name") or local_path.name,
            "reused": True,
        }
    try:
        client.upload_storage_object(
            bucket, storage_path, local_path, content_type, upsert=True
        )
    except TypeError:
        client.upload_storage_object(bucket, storage_path, local_path, content_type)
    public_url = (
        f"{client.url}/storage/v1/object/public/{quote(bucket)}/{quote(storage_path)}"
    )
    base_row = {
        "user_id": user_id,
        "file_name": local_path.name,
        "file_url": public_url,
        "file_type": file_type,
        "file_size": local_path.stat().st_size,
        "mime_type": content_type,
        "folder_id": None,
        "group_id": None,
        "storage_url": public_url,
        "storage_path": storage_path,
        "url": public_url,
        "tags": tags,
    }
    try:
        upserted = client.upsert("media", base_row, on_conflict="storage_path")
        row = upserted[0] if isinstance(upserted, list) and upserted else upserted
    except (AttributeError, RuntimeError):
        row = client.insert_with_fallback("media", base_row, fallback_remove=["url"])
    return {
        "id": row.get("id"),
        "publicUrl": public_url,
        "storagePath": storage_path,
        "fileName": local_path.name,
    }


def _insert_draft_post(
    client: SupabaseRestClient, *, draft: dict[str, Any], media_ref: dict[str, Any]
) -> dict[str, Any]:
    _require_legacy_supabase_writes()
    metadata = draft.get("metadata") or _draft_metadata(draft)
    campaign_meta = (
        metadata.get("campaign_factory")
        if isinstance(metadata.get("campaign_factory"), dict)
        else {}
    )
    media_type, ig_media_type = _draft_media_types(draft)
    row = {
        "user_id": draft["userId"],
        "account_id": None,
        "instagram_account_id": draft["instagramAccountId"],
        "platform": "instagram",
        "content": draft["content"],
        "media_urls": [media_ref["publicUrl"]],
        "media_type": media_type,
        "ig_media_type": ig_media_type,
        "content_surface": draft.get("contentSurface")
        or campaign_meta.get("content_surface")
        or campaign_meta.get("contentSurface")
        or "reel",
        "status": draft.get("status") or "draft",
        "hashtags": draft.get("topics") or [],
        "source": "manual",
        "metadata": metadata,
        "scheduled_for": draft.get("scheduledFor")
        if draft.get("status") == "scheduled"
        else None,
        "campaign_factory_asset_id": draft.get("renderedAssetId"),
        "campaign_factory_distribution_plan_id": draft.get("distributionPlanId"),
        "campaign_factory_post_key": draft.get("campaignFactoryPostKey"),
        "campaign_factory_content_fingerprint": campaign_meta.get("content_fingerprint")
        or draft.get("contentHash"),
        "campaign_factory_caption_hash": draft.get("captionHash"),
        "campaign_factory_concept_id": campaign_meta.get("concept_id"),
        "campaign_factory_parent_asset_id": campaign_meta.get("parent_asset_id"),
        "campaign_factory_variant_family_id": campaign_meta.get("variant_family_id"),
        "campaign_factory_variant_id": campaign_meta.get("variant_id"),
        "platform_draft_validated": True,
    }
    inserted = client.insert_with_fallback(
        "posts",
        row,
        fallback_remove=[],
    )
    return {
        "id": inserted.get("id"),
        "status": inserted.get("status", "draft"),
        "platform": "instagram",
        "metadata": metadata,
    }


def _update_existing_draft_post(
    client: SupabaseRestClient,
    *,
    draft: dict[str, Any],
    media_ref: dict[str, Any],
    post_id: str,
) -> dict[str, Any]:
    _require_legacy_supabase_writes()
    metadata = draft.get("metadata") or _draft_metadata(draft)
    campaign_meta = (
        metadata.get("campaign_factory")
        if isinstance(metadata.get("campaign_factory"), dict)
        else {}
    )
    media_type, ig_media_type = _draft_media_types(draft)
    values = {
        "content": draft["content"],
        "media_urls": [media_ref["publicUrl"]] if media_ref.get("publicUrl") else [],
        "media_type": media_type,
        "ig_media_type": ig_media_type,
        "content_surface": draft.get("contentSurface")
        or campaign_meta.get("content_surface")
        or campaign_meta.get("contentSurface")
        or "reel",
        "hashtags": draft.get("topics") or [],
        "metadata": metadata,
        "campaign_factory_asset_id": draft.get("renderedAssetId"),
        "campaign_factory_distribution_plan_id": draft.get("distributionPlanId"),
        "campaign_factory_post_key": draft.get("campaignFactoryPostKey"),
        "campaign_factory_content_fingerprint": campaign_meta.get("content_fingerprint")
        or draft.get("contentHash"),
        "campaign_factory_caption_hash": draft.get("captionHash"),
        "campaign_factory_concept_id": campaign_meta.get("concept_id"),
        "campaign_factory_parent_asset_id": campaign_meta.get("parent_asset_id"),
        "campaign_factory_variant_family_id": campaign_meta.get("variant_family_id"),
        "campaign_factory_variant_id": campaign_meta.get("variant_id"),
        "platform_draft_validated": True,
    }
    updated = client.update("posts", values, {"id": f"eq.{post_id}"})
    row = updated[0] if isinstance(updated, list) and updated else {}
    return {
        "id": row.get("id", post_id),
        "status": row.get("status", draft.get("status") or "draft"),
        "platform": row.get("platform", "instagram"),
        "metadata": row.get("metadata") or metadata,
    }


def _select_existing_campaign_factory_post(
    client: SupabaseRestClient,
    *,
    user_id: str,
    post_key: str | None,
) -> dict[str, Any] | None:
    if not post_key:
        return None
    try:
        links = client.select(
            "campaign_factory_post_links",
            {
                "select": "post_id,status,media_id,metadata",
                "user_id": f"eq.{user_id}",
                "post_key": f"eq.{post_key}",
                "limit": "1",
            },
        )
    except RuntimeError as exc:
        # A transient failure here must NOT read as "post does not exist":
        # the caller would insert a duplicate post, defeating the post_key
        # dedup that makes export reruns safe (audit A6 companion). Only a
        # schema mismatch (table/column missing on older dashboards) may
        # fall through to the metadata lookup.
        if not _is_missing_column_error(exc):
            raise
        links = []
    if links:
        post_id = links[0].get("post_id")
        post = _select_post_by_id(client, post_id)
        if post:
            post["_campaign_factory_link"] = links[0]
            return post
        return {
            "id": post_id,
            "status": links[0].get("status"),
            "metadata": {"campaign_factory": links[0].get("metadata") or {}},
        }
    try:
        posts = client.select(
            "posts",
            {
                "select": "id,status,platform,media_urls,metadata",
                "user_id": f"eq.{user_id}",
                "metadata->campaign_factory->>post_key": f"eq.{post_key}",
                "limit": "1",
            },
        )
    except RuntimeError as exc:
        # Same dedup-safety rule as above: transient failures must propagate,
        # otherwise a rerun inserts a duplicate post.
        if not _is_missing_column_error(exc):
            raise
        posts = []
    return posts[0] if posts else None


def _select_post_by_id(
    client: SupabaseRestClient, post_id: Any
) -> dict[str, Any] | None:
    if not post_id:
        return None
    try:
        rows = client.select(
            "posts",
            {
                "select": "id,status,platform,media_urls,metadata",
                "id": f"eq.{post_id}",
                "limit": "1",
            },
        )
    except RuntimeError as exc:
        # Transient failure must not read as "post missing" — the caller
        # treats a miss as permission to create a new post (dedup safety).
        if not _is_missing_column_error(exc):
            raise
        rows = []
    return rows[0] if rows else None


def _media_ref_from_existing_post(post: dict[str, Any]) -> dict[str, Any]:
    media_urls = (
        post.get("media_urls") if isinstance(post.get("media_urls"), list) else []
    )
    public_url = media_urls[0] if media_urls else ""
    return {
        "id": (post.get("_campaign_factory_link") or {}).get("media_id")
        if isinstance(post.get("_campaign_factory_link"), dict)
        else None,
        "publicUrl": public_url,
        "storagePath": None,
        "fileName": None,
        "reused": True,
    }


def _upsert_threadsdash_graph_mirror(
    client: SupabaseRestClient,
    *,
    draft: dict[str, Any],
    post_row: dict[str, Any],
    media_ref: dict[str, Any],
    post_graph_id: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True, "errors": []}
    if not hasattr(client, "upsert"):
        return result
    metadata = draft.get("metadata") or {}
    campaign_factory = (
        metadata.get("campaign_factory") if isinstance(metadata, dict) else {}
    )
    if not isinstance(campaign_factory, dict):
        campaign_factory = {}
    now = utc_now()
    entities = [
        (
            "campaign",
            draft.get("campaignGraphId"),
            "campaigns",
            draft.get("campaignId"),
        ),
        (
            "source_asset",
            draft.get("sourceAssetGraphId"),
            "source_assets",
            draft.get("sourceAssetId"),
        ),
        (
            "rendered_asset",
            draft.get("renderedAssetGraphId") or draft.get("graphId"),
            "rendered_assets",
            draft.get("renderedAssetId"),
        ),
        (
            "audit_report",
            draft.get("auditGraphId"),
            "audit_reports",
            campaign_factory.get("contentforge_report_id"),
        ),
        ("threadsdash_post", post_graph_id, "posts", post_row.get("id")),
    ]
    for entity_type, graph_id, local_table, local_id in entities:
        if not graph_id:
            continue
        try:
            client.upsert(
                "campaign_factory_entities",
                {
                    "global_id": graph_id,
                    "entity_type": entity_type,
                    "campaign_id": draft.get("campaignId"),
                    "local_table": local_table,
                    "local_id": local_id,
                    "payload": campaign_factory
                    if entity_type == "threadsdash_post"
                    else {},
                    "updated_at": now,
                },
                on_conflict="global_id",
            )
        except Exception as exc:
            result["ok"] = False
            result["errors"].append(
                {
                    "table": "campaign_factory_entities",
                    "globalId": graph_id,
                    "error": str(exc),
                }
            )
    rendered_graph_id = draft.get("renderedAssetGraphId") or draft.get("graphId")
    if rendered_graph_id:
        try:
            client.upsert(
                "campaign_factory_post_links",
                {
                    "post_id": post_row.get("id"),
                    "user_id": draft.get("userId"),
                    "post_graph_id": post_graph_id,
                    "campaign_id": draft.get("campaignId"),
                    "campaign_graph_id": draft.get("campaignGraphId"),
                    "source_asset_id": draft.get("sourceAssetId"),
                    "source_asset_graph_id": draft.get("sourceAssetGraphId"),
                    "rendered_asset_id": draft.get("renderedAssetId"),
                    "rendered_asset_graph_id": rendered_graph_id,
                    "audit_graph_id": draft.get("auditGraphId"),
                    "media_id": media_ref.get("id"),
                    "status": post_row.get("status"),
                    "draft_key": draft.get("campaignFactoryDraftKey"),
                    "media_key": draft.get("campaignFactoryMediaKey"),
                    "post_key": draft.get("campaignFactoryPostKey"),
                    "export_run_id": draft.get("campaignFactoryExportId"),
                    "metadata": campaign_factory,
                    "updated_at": now,
                },
                on_conflict="user_id,post_key",
            )
            client.upsert(
                "campaign_factory_edges",
                {
                    "from_global_id": rendered_graph_id,
                    "to_global_id": post_graph_id,
                    "relation_type": "rendered_asset_to_threadsdash_post",
                    "campaign_id": draft.get("campaignId"),
                    "evidence": {
                        "postId": post_row.get("id"),
                        "mediaId": media_ref.get("id"),
                    },
                    "created_at": now,
                },
                on_conflict="from_global_id,to_global_id,relation_type",
            )
        except Exception as exc:
            result["ok"] = False
            result["errors"].append(
                {
                    "table": "campaign_factory_edges_or_post_links",
                    "postId": post_row.get("id"),
                    "error": str(exc),
                }
            )
    return result


def _delete_existing_preview_schedule_rows(
    client: SupabaseRestClient,
    *,
    user_id: str,
    campaign_slug: str,
    limit: int = 1000,
) -> dict[str, Any]:
    rows = client.select(
        "posts",
        {
            "select": "id,metadata,status",
            "user_id": f"eq.{user_id}",
            "status": "eq.scheduled",
            "limit": str(limit),
        },
    )
    deleted_ids = []
    for row in rows:
        metadata = row.get("metadata") if isinstance(row, dict) else {}
        campaign_factory = (
            metadata.get("campaign_factory")
            if isinstance(metadata, dict)
            and isinstance(metadata.get("campaign_factory"), dict)
            else {}
        )
        if (
            campaign_factory.get("campaign_id") == campaign_slug
            and campaign_factory.get("preview_schedule_only") is True
        ):
            client.delete("posts", {"id": f"eq.{row.get('id')}"})
            deleted_ids.append(row.get("id"))
    return {"deletedCount": len(deleted_ids), "deletedPostIds": deleted_ids}


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


def _learning_cohort_metadata(asset: dict[str, Any]) -> dict[str, Any] | None:
    candidates = (
        asset.get("learningCohort"),
        asset.get("learning_cohort"),
        (asset.get("sourcePrompt") or {}).get("learning_cohort")
        if isinstance(asset.get("sourcePrompt"), dict)
        else None,
        (asset.get("generatedAssetLineage") or {}).get("learning_cohort")
        if isinstance(asset.get("generatedAssetLineage"), dict)
        else None,
    )
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("cohort_id"):
            return dict(candidate)
    return None


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


def _draft_notify_audio_deferred(draft: dict[str, Any]) -> bool:
    publishability = (
        draft.get("publishability")
        if isinstance(draft.get("publishability"), dict)
        else {}
    )
    return _allows_draft_notify_audio_deferral(
        schedule_mode=str(draft.get("scheduleMode") or "").strip().lower(),
        publish_mode=str(draft.get("publishMode") or "").strip().lower(),
        audio_intent=draft.get("audioIntent"),
        publishability=publishability,
    )


def _is_deferred_notify_audio_blocker(reason: Any) -> bool:
    normalized = str(reason).split(":")[-1].strip()
    return normalized in DEFERRED_NOTIFY_AUDIO_FAILURES or normalized.startswith(
        "campaign_audio_unresolved"
    )


def _draft_metadata(draft: dict[str, Any]) -> dict[str, Any]:
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
        metadata["trialReels"] = True
        metadata["trialGraduationStrategy"] = (
            draft.get("trialGraduationStrategy") or "MANUAL"
        )
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


def _preflight_check(name: str, fn) -> dict[str, Any]:
    try:
        result = fn()
        detail: Any = result
        if isinstance(result, list):
            detail = {"rowCount": len(result)}
        elif isinstance(result, dict):
            detail = {
                key: result.get(key)
                for key in ("id", "name", "public")
                if key in result
            }
        return {"name": name, "ok": True, "detail": detail}
    except Exception as exc:
        return {"name": name, "ok": False, "error": str(exc)}


def _load_export_result(value: dict[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    path = Path(value)
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_media_row(
    client: SupabaseRestClient, media_ref: dict[str, Any]
) -> dict[str, Any]:
    media_id = media_ref.get("id")
    blocking: list[str] = []
    row = None
    if not media_id:
        blocking.append("missing_media_id")
    else:
        rows = client.select(
            "media",
            {
                "select": "id,user_id,file_name,file_url,file_type,file_size,mime_type,storage_url,storage_path,tags",
                "id": f"eq.{media_id}",
                "limit": "1",
            },
        )
        row = rows[0] if rows else None
        if not row:
            blocking.append("media_row_missing")
    if row:
        if row.get("file_type") not in {"video", "image"}:
            blocking.append(f"media_type_invalid:{row.get('file_type')}")
        if not row.get("file_url") and not row.get("storage_url"):
            blocking.append("media_missing_url")
        if not row.get("storage_path"):
            blocking.append("media_missing_storage_path")
    return {
        "type": "media",
        "id": media_id,
        "ok": not blocking,
        "row": row,
        "blockingReasons": blocking,
    }


def _verify_post_row(
    client: SupabaseRestClient, post_ref: dict[str, Any]
) -> dict[str, Any]:
    post_id = post_ref.get("id")
    blocking: list[str] = []
    row = None
    if not post_id:
        blocking.append("missing_post_id")
    else:
        row = _select_post_for_verification(client, post_id)
        if not row:
            blocking.append("post_row_missing")
    if row:
        metadata = row.get("metadata") or {}
        campaign_meta = (
            metadata.get("campaign_factory") if isinstance(metadata, dict) else None
        )
        preview_schedule_only = (
            isinstance(campaign_meta, dict)
            and campaign_meta.get("preview_schedule_only") is True
        )
        if row.get("status") != "draft" and not (
            row.get("status") == "scheduled" and preview_schedule_only
        ):
            blocking.append(f"post_status:{row.get('status')}")
        if row.get("platform") != "instagram":
            blocking.append(f"post_platform:{row.get('platform')}")
        if row.get("scheduled_for") is not None and not preview_schedule_only:
            blocking.append("scheduled_for_not_null")
        if row.get("published_at") is not None:
            blocking.append("published_at_not_null")
        if row.get("ig_container_id") is not None:
            blocking.append("ig_container_id_not_null")
        if not isinstance(campaign_meta, dict):
            blocking.append("missing_campaign_factory_metadata")
        if row.get("media_type") not in {None, "reel", "story"}:
            blocking.append(f"media_type:{row.get('media_type')}")
        if row.get("ig_media_type") not in {None, "REELS", "STORIES"}:
            blocking.append(f"ig_media_type:{row.get('ig_media_type')}")
    return {
        "type": "post",
        "id": post_id,
        "ok": not blocking,
        "row": row,
        "blockingReasons": blocking,
    }


def _select_post_for_verification(
    client: SupabaseRestClient, post_id: str
) -> dict[str, Any] | None:
    try:
        rows = client.select(
            "posts",
            {
                "select": (
                    "id,user_id,platform,status,media_type,ig_media_type,instagram_account_id,"
                    "media_urls,metadata,scheduled_for,published_at,ig_container_id"
                ),
                "id": f"eq.{post_id}",
                "limit": "1",
            },
        )
    except RuntimeError:
        rows = client.select(
            "posts",
            {
                "select": "id,user_id,platform,status,media_type,ig_media_type,instagram_account_id,media_urls,metadata,scheduled_for",
                "id": f"eq.{post_id}",
                "limit": "1",
            },
        )
    return rows[0] if rows else None


def promote_preview_schedule(
    factory: CampaignFactory,
    *,
    campaign_slug: str,
    user_id: str,
    supabase_url: str | None,
    supabase_service_role_key: str | None,
    limit: int = 1000,
) -> dict[str, Any]:
    if not supabase_url or not supabase_service_role_key:
        raise ValueError(
            "supabase_url and supabase_service_role_key are required for preview promotion"
        )
    campaign = factory.campaign_by_slug(campaign_slug)
    pipeline_job = factory.create_pipeline_job(
        "promote_preview_schedule",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "userId": user_id,
            "hasSupabaseUrl": bool(supabase_url),
            "hasSupabaseServiceRoleKey": bool(supabase_service_role_key),
            "limit": limit,
        },
    )
    factory.start_pipeline_job(pipeline_job["id"])
    try:
        client = SupabaseRestClient(supabase_url.rstrip("/"), supabase_service_role_key)
        rows = _select_threadsdash_posts(client, user_id=user_id, limit=limit)
        promoted = []
        skipped = []
        for row in rows:
            metadata = row.get("metadata") or {}
            meta = (
                metadata.get("campaign_factory") if isinstance(metadata, dict) else None
            )
            if not isinstance(meta, dict) or meta.get("campaign_id") != campaign_slug:
                continue
            if meta.get("preview_schedule_only") is not True:
                skipped.append({"id": row.get("id"), "reason": "not_preview_schedule"})
                continue
            if row.get("status") != "scheduled" or not row.get("scheduled_for"):
                skipped.append({"id": row.get("id"), "reason": "not_scheduled"})
                continue
            compatible, mismatch_reason, _profile = (
                factory.account_compatible_with_model(
                    meta.get("model_slug") or meta.get("model_id") or "",
                    instagram_account_id=row.get("instagram_account_id"),
                )
            )
            if not compatible:
                skipped.append(
                    {
                        "id": row.get("id"),
                        "reason": mismatch_reason or "model_account_mismatch",
                    }
                )
                continue
            next_metadata = dict(metadata)
            next_meta = dict(meta)
            next_meta["preview_schedule_only"] = False
            next_meta["schedule_mode"] = "live"
            next_metadata["campaign_factory"] = next_meta
            next_metadata.pop("previewScheduleOnly", None)
            updated = client.update(
                "posts",
                {"metadata": next_metadata},
                {"id": f"eq.{row['id']}", "user_id": f"eq.{user_id}"},
            )
            promoted.append(
                {
                    "id": row.get("id"),
                    "scheduledFor": row.get("scheduled_for"),
                    "updated": bool(updated),
                }
            )
        result = {
            "schema": "campaign_factory.preview_schedule_promotion.v1",
            "campaign": campaign_slug,
            "userId": user_id,
            "promotedCount": len(promoted),
            "skippedCount": len(skipped),
            "promoted": promoted,
            "skipped": skipped,
            "pipelineJobId": pipeline_job["id"],
        }
        factory.record_event(
            "preview_schedule_promoted",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="success" if promoted else "warning",
            message=f"Promoted {len(promoted)} preview scheduled posts",
            metadata={"promotedCount": len(promoted), "skippedCount": len(skipped)},
        )
        factory.finish_pipeline_job(pipeline_job["id"], result)
        return result
    except Exception as exc:
        factory.record_event(
            "preview_schedule_promoted",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"Preview schedule promotion failed: {exc}",
            metadata={"error": str(exc)},
        )
        factory.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def clear_preview_schedule(
    factory: CampaignFactory,
    *,
    campaign_slug: str,
    user_id: str,
    supabase_url: str | None,
    supabase_service_role_key: str | None,
    limit: int = 1000,
    reason: str = "audio_workflow_not_ready",
) -> dict[str, Any]:
    if not supabase_url or not supabase_service_role_key:
        raise ValueError(
            "supabase_url and supabase_service_role_key are required for schedule clearing"
        )
    campaign = factory.campaign_by_slug(campaign_slug)
    pipeline_job = factory.create_pipeline_job(
        "clear_preview_schedule",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "userId": user_id,
            "hasSupabaseUrl": bool(supabase_url),
            "hasSupabaseServiceRoleKey": bool(supabase_service_role_key),
            "limit": limit,
            "reason": reason,
        },
    )
    factory.start_pipeline_job(pipeline_job["id"])
    try:
        client = SupabaseRestClient(supabase_url.rstrip("/"), supabase_service_role_key)
        rows = _select_threadsdash_posts(client, user_id=user_id, limit=limit)
        cleared = []
        skipped = []
        now = utc_now()
        for row in rows:
            metadata = row.get("metadata") or {}
            meta = (
                metadata.get("campaign_factory") if isinstance(metadata, dict) else None
            )
            if not isinstance(meta, dict) or meta.get("campaign_id") != campaign_slug:
                continue
            if row.get("status") != "scheduled":
                skipped.append(
                    {
                        "id": row.get("id"),
                        "reason": f"not_scheduled:{row.get('status')}",
                    }
                )
                continue
            previous_scheduled_for = row.get("scheduled_for")
            next_metadata = dict(metadata)
            next_meta = dict(meta)
            if previous_scheduled_for:
                next_meta["previous_scheduled_for"] = previous_scheduled_for
            next_meta["unscheduled_at"] = now
            next_meta["unscheduled_reason"] = reason
            next_meta["scheduled_for"] = None
            next_meta["schedule_mode"] = "draft"
            if (
                meta.get("preview_schedule_only") is True
                or metadata.get("previewScheduleOnly") is True
            ):
                next_meta["preview_schedule_only"] = True
                next_metadata["previewScheduleOnly"] = True
            next_metadata["campaign_factory"] = next_meta
            updated = client.update(
                "posts",
                {
                    "status": "draft",
                    "scheduled_for": None,
                    "metadata": next_metadata,
                },
                {
                    "id": f"eq.{row['id']}",
                    "user_id": f"eq.{user_id}",
                    "status": "eq.scheduled",
                },
            )
            if updated:
                cleared.append(
                    {
                        "id": row.get("id"),
                        "previousScheduledFor": previous_scheduled_for,
                        "mediaUrlCount": len(row.get("media_urls") or []),
                    }
                )
            else:
                skipped.append(
                    {"id": row.get("id"), "reason": "update_returned_no_rows"}
                )
        remaining_rows = _select_threadsdash_posts(client, user_id=user_id, limit=limit)
        remaining_scheduled = [
            row
            for row in remaining_rows
            if row.get("status") == "scheduled"
            and isinstance((row.get("metadata") or {}).get("campaign_factory"), dict)
            and (row.get("metadata") or {})
            .get("campaign_factory", {})
            .get("campaign_id")
            == campaign_slug
        ]
        result = {
            "schema": "campaign_factory.preview_schedule_clear.v1",
            "campaign": campaign_slug,
            "userId": user_id,
            "clearedCount": len(cleared),
            "skippedCount": len(skipped),
            "remainingScheduledCount": len(remaining_scheduled),
            "cleared": cleared,
            "skipped": skipped,
            "pipelineJobId": pipeline_job["id"],
        }
        factory.record_event(
            "preview_schedule_cleared",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="success" if not remaining_scheduled else "warning",
            message=f"Cleared {len(cleared)} Campaign Factory scheduled posts",
            metadata={
                "clearedCount": len(cleared),
                "skippedCount": len(skipped),
                "remainingScheduledCount": len(remaining_scheduled),
                "reason": reason,
            },
        )
        factory.finish_pipeline_job(pipeline_job["id"], result)
        return result
    except Exception as exc:
        factory.record_event(
            "preview_schedule_cleared",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"Schedule clear failed: {exc}",
            metadata={"error": str(exc)},
        )
        factory.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def summarize_threadsdash_usage(
    factory: CampaignFactory,
    *,
    campaign_slug: str,
    user_id: str,
    supabase_url: str | None,
    supabase_service_role_key: str | None,
    limit: int = 1000,
) -> dict[str, Any]:
    if not supabase_url or not supabase_service_role_key:
        raise ValueError(
            "supabase_url and supabase_service_role_key are required for usage tracking"
        )
    payload = build_draft_payloads(
        factory, campaign_slug=campaign_slug, user_id=user_id
    )
    client = SupabaseRestClient(supabase_url.rstrip("/"), supabase_service_role_key)
    rows = _select_threadsdash_posts(client, user_id=user_id, limit=limit)
    tracked_rows = [
        row
        for row in rows
        if isinstance((row.get("metadata") or {}).get("campaign_factory"), dict)
    ]

    draft_by_rendered = {draft["renderedAssetId"]: draft for draft in payload["drafts"]}
    source_ids = {draft["sourceAssetId"] for draft in payload["drafts"]}
    campaign_ids = {draft["campaignId"] for draft in payload["drafts"]}
    content_hashes = {
        draft.get("contentHash")
        for draft in payload["drafts"]
        if draft.get("contentHash")
    }
    source_hashes = {
        draft.get("sourceContentHash")
        for draft in payload["drafts"]
        if draft.get("sourceContentHash")
    }
    caption_hashes = {
        draft.get("captionHash")
        for draft in payload["drafts"]
        if draft.get("captionHash")
    }

    asset_usage = {asset_id: _empty_usage() for asset_id in draft_by_rendered}
    source_usage = {source_id: _empty_usage() for source_id in source_ids}
    campaign_usage = {campaign_id: _empty_usage() for campaign_id in campaign_ids}
    content_hash_usage = {
        content_hash: _empty_usage() for content_hash in content_hashes
    }
    source_hash_usage = {source_hash: _empty_usage() for source_hash in source_hashes}
    caption_hash_usage = {
        caption_hash: _empty_usage() for caption_hash in caption_hashes
    }
    account_usage: dict[str, dict[str, Any]] = {}
    surface_usage: dict[str, dict[str, Any]] = {}

    for row in tracked_rows:
        meta = (row.get("metadata") or {}).get("campaign_factory") or {}
        status = str(row.get("status") or "unknown")
        rendered_id = meta.get("rendered_asset_id")
        source_id = meta.get("source_asset_id")
        campaign_id = meta.get("campaign_id")
        content_hash = meta.get("content_hash")
        source_hash = meta.get("source_content_hash")
        caption_hash = meta.get("caption_hash") or _text_hash(row.get("content") or "")
        if _usage_row_matches_campaign(
            meta=meta,
            rendered_id=rendered_id,
            source_id=source_id,
            campaign_id=campaign_id,
            content_hash=content_hash,
            source_hash=source_hash,
            caption_hash=caption_hash,
            draft_by_rendered=draft_by_rendered,
            source_ids=source_ids,
            campaign_ids=campaign_ids,
            content_hashes=content_hashes,
            source_hashes=source_hashes,
            caption_hashes=caption_hashes,
        ):
            account_key = (
                row.get("instagram_account_id") or row.get("account_id") or "unassigned"
            )
            _add_usage(
                account_usage.setdefault(account_key, _empty_usage()),
                row=row,
                status=status,
            )
            surface = _post_surface(row, meta)
            _add_usage(
                surface_usage.setdefault(surface, _empty_usage()),
                row=row,
                status=status,
            )
        for bucket, key in (
            (asset_usage, rendered_id),
            (source_usage, source_id),
            (campaign_usage, campaign_id),
            (content_hash_usage, content_hash),
            (source_hash_usage, source_hash),
            (caption_hash_usage, caption_hash),
        ):
            if key in bucket:
                _add_usage(bucket[key], row=row, status=status)

    warnings = []
    for asset_id, usage in asset_usage.items():
        if usage["published"] > 0:
            warnings.append(
                {
                    "level": "block",
                    "type": "exact_render_published",
                    "renderedAssetId": asset_id,
                    "count": usage["published"],
                }
            )
        elif usage["scheduled"] > 0 or usage["draft"] > 0:
            warnings.append(
                {
                    "level": "warn",
                    "type": "exact_render_already_queued",
                    "renderedAssetId": asset_id,
                    "count": usage["scheduled"] + usage["draft"],
                }
            )
    for source_id, usage in source_usage.items():
        if usage["published"] + usage["scheduled"] + usage["draft"] > 1:
            warnings.append(
                {
                    "level": "warn",
                    "type": "source_family_reuse",
                    "sourceAssetId": source_id,
                    "count": usage["total"],
                }
            )
    for caption_hash, usage in caption_hash_usage.items():
        if usage["published"] + usage["scheduled"] + usage["draft"] > 0:
            warnings.append(
                {
                    "level": "warn",
                    "type": "caption_reuse",
                    "captionHash": caption_hash,
                    "count": usage["total"],
                }
            )
        accounts = {
            post.get("instagramAccountId") or post.get("accountId")
            for post in usage["posts"]
        }
        if len(accounts) >= 3:
            warnings.append(
                {
                    "level": "warn",
                    "type": "caption_reuse_multi_account",
                    "captionHash": caption_hash,
                    "accountCount": len(accounts),
                }
            )
    for account, usage in account_usage.items():
        queued = usage["draft"] + usage["scheduled"]
        if account != "unassigned" and queued > 3:
            warnings.append(
                {
                    "level": "warn",
                    "type": "account_has_multiple_queued_posts",
                    "account": account,
                    "count": queued,
                }
            )

    return {
        "schema": "campaign_factory.threadsdash_usage.v1",
        "campaign": campaign_slug,
        "userId": user_id,
        "checkedAt": utc_now(),
        "postsScanned": len(rows),
        "campaignFactoryPostsScanned": len(tracked_rows),
        "assets": [
            {
                "renderedAssetId": asset_id,
                "sourceAssetId": draft["sourceAssetId"],
                "contentHash": draft.get("contentHash"),
                "sourceContentHash": draft.get("sourceContentHash"),
                "captionHash": draft.get("captionHash"),
                "recipe": draft.get("recipe"),
                "accountId": draft.get("accountId"),
                "instagramAccountId": draft.get("instagramAccountId"),
                "usage": asset_usage[asset_id],
                "captionUsage": caption_hash_usage.get(draft.get("captionHash"))
                or _empty_usage(),
            }
            for asset_id, draft in draft_by_rendered.items()
        ],
        "sourceUsage": source_usage,
        "contentHashUsage": content_hash_usage,
        "sourceContentHashUsage": source_hash_usage,
        "captionHashUsage": caption_hash_usage,
        "campaignUsage": campaign_usage,
        "accountUsage": account_usage,
        "surfaceUsage": surface_usage,
        "warnings": warnings,
    }


def sync_threadsdash_account_assignments(
    factory: CampaignFactory,
    *,
    campaign_slug: str,
    user_id: str,
    supabase_url: str | None,
    supabase_service_role_key: str | None,
    limit: int = 1000,
) -> dict[str, Any]:
    if not supabase_url or not supabase_service_role_key:
        raise ValueError(
            "supabase_url and supabase_service_role_key are required for assignment sync"
        )
    campaign = factory.campaign_by_slug(campaign_slug)
    pipeline_job = factory.create_pipeline_job(
        "sync_threadsdash_assignments",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "userId": user_id,
            "hasSupabaseUrl": bool(supabase_url),
            "hasSupabaseServiceRoleKey": True,
            "limit": limit,
        },
    )
    factory.start_pipeline_job(pipeline_job["id"])
    try:
        client = SupabaseRestClient(supabase_url.rstrip("/"), supabase_service_role_key)
        rows = _select_threadsdash_posts(client, user_id=user_id, limit=limit)
        inserted = 0
        skipped = 0
        matched = 0
        for row in rows:
            meta = (row.get("metadata") or {}).get("campaign_factory") or {}
            if not isinstance(meta, dict):
                skipped += 1
                continue
            if meta.get("campaign_id") and meta.get("campaign_id") not in {
                campaign["id"],
                campaign_slug,
            }:
                skipped += 1
                continue
            rendered_asset_id = meta.get("rendered_asset_id")
            if not rendered_asset_id:
                skipped += 1
                continue
            try:
                asset = factory.rendered_asset(rendered_asset_id)
            except Exception:
                skipped += 1
                continue
            if asset["campaign_id"] != campaign["id"]:
                skipped += 1
                continue
            account_id = row.get("account_id") or meta.get("account_id")
            instagram_account_id = row.get("instagram_account_id") or meta.get(
                "instagram_account_id"
            )
            if not account_id and not instagram_account_id:
                skipped += 1
                continue
            matched += 1
            local_account_id = (
                account_id if _local_account_exists(factory, account_id) else None
            )
            if _assignment_exists(
                factory, rendered_asset_id, local_account_id, instagram_account_id
            ):
                skipped += 1
                continue
            factory.assign_asset_account(
                rendered_asset_id,
                account_id=local_account_id,
                instagram_account_id=instagram_account_id,
                planned_window_start=row.get("scheduled_for")
                or meta.get("planned_window_start"),
                planned_window_end=meta.get("planned_window_end"),
                notes=f"Synced from ThreadsDash post {row.get('id')}",
            )
            inserted += 1
        result = {
            "schema": "campaign_factory.threadsdash_assignment_sync.v1",
            "campaign": campaign_slug,
            "userId": user_id,
            "checkedAt": utc_now(),
            "postsScanned": len(rows),
            "matched": matched,
            "inserted": inserted,
            "skipped": skipped,
            "pipelineJobId": pipeline_job["id"],
        }
        factory.record_event(
            "threadsdash_assignments_synced",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="success",
            message=f"ThreadsDash assignments synced: {inserted} inserted, {skipped} skipped",
            metadata={
                "postsScanned": len(rows),
                "matched": matched,
                "inserted": inserted,
                "skipped": skipped,
            },
        )
        factory.finish_pipeline_job(pipeline_job["id"], result)
        return result
    except Exception as exc:
        factory.record_event(
            "threadsdash_assignments_synced",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"ThreadsDash assignment sync failed: {exc}",
            metadata={"error": str(exc)},
        )
        factory.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def sync_threadsdash_instagram_accounts(
    factory: CampaignFactory,
    *,
    creator: str,
    supabase_url: str | None,
    supabase_service_role_key: str | None,
    user_id: str | None = None,
    match: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    if not supabase_url or not supabase_service_role_key:
        raise ValueError(
            "supabase_url and supabase_service_role_key are required for account sync"
        )
    creator_slug = _sync_slug(creator)
    model = factory.upsert_model(creator_slug, creator)
    matcher = (match or creator or "").strip().lower()
    client = SupabaseRestClient(supabase_url.rstrip("/"), supabase_service_role_key)
    params = {
        "select": "id,username,display_name,is_active,status,needs_reauth,group_id,user_id,login_type,sync_cohort",
        "limit": str(max(1, int(limit or 1))),
    }
    if user_id:
        params["user_id"] = f"eq.{user_id}"
    rows = client.select("instagram_accounts", params)
    matched_rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    imported: list[dict[str, Any]] = []
    for row in rows:
        username = str(row.get("username") or "").strip().lstrip("@")
        display_name = str(row.get("display_name") or "").strip()
        haystack = f"{username} {display_name}".lower()
        if matcher and matcher not in haystack:
            skipped.append(
                {
                    "id": row.get("id"),
                    "username": username,
                    "reason": "creator_match_failed",
                }
            )
            continue
        matched_rows.append(row)
        if not username:
            skipped.append(
                {
                    "id": row.get("id"),
                    "username": username,
                    "reason": "missing_username",
                }
            )
            continue
        status = str(row.get("status") or "").lower()
        if (
            row.get("is_active") is False
            or row.get("needs_reauth") is True
            or any(
                token in status
                for token in ("blocked", "restricted", "disabled", "reauth")
            )
        ):
            skipped.append(
                {"id": row.get("id"), "username": username, "reason": "not_eligible"}
            )
            continue
        before = factory.conn.execute(
            "SELECT id FROM accounts WHERE handle = ? AND platform = 'instagram'",
            (username,),
        ).fetchone()
        account = factory.upsert_account(
            username,
            platform="instagram",
            external_id=str(row.get("id") or ""),
            model_id=model["id"],
        )
        imported.append(
            {
                "accountId": account["id"],
                "instagramAccountId": row.get("id"),
                "username": username,
                "displayName": display_name,
                "syncCohort": row.get("sync_cohort"),
                "created": before is None,
            }
        )
    return {
        "schema": "campaign_factory.threadsdash_instagram_account_sync.v1",
        "creator": creator,
        "match": matcher,
        "rowsScanned": len(rows),
        "matched": len(matched_rows),
        "imported": len(imported),
        "created": sum(1 for row in imported if row["created"]),
        "updated": sum(1 for row in imported if not row["created"]),
        "skipped": len(skipped),
        "accounts": imported,
        "skipReasons": _sync_reason_counts(skipped),
        "wouldWrite": True,
    }


def sync_performance_snapshots(
    factory: CampaignFactory,
    *,
    campaign_slug: str,
    user_id: str,
    supabase_url: str | None,
    supabase_service_role_key: str | None,
    limit: int = 1000,
) -> dict[str, Any]:
    if not supabase_url or not supabase_service_role_key:
        raise ValueError(
            "supabase_url and supabase_service_role_key are required for performance sync"
        )
    campaign = factory.campaign_by_slug(campaign_slug)
    pipeline_job = factory.create_pipeline_job(
        "sync_performance",
        campaign["id"],
        {
            "campaign": campaign_slug,
            "userId": user_id,
            "hasSupabaseUrl": bool(supabase_url),
            "hasSupabaseServiceRoleKey": True,
            "limit": limit,
        },
    )
    factory.start_pipeline_job(pipeline_job["id"])
    try:
        client = SupabaseRestClient(supabase_url.rstrip("/"), supabase_service_role_key)
        rows, posts_truncated = _select_threadsdash_posts_paged(
            client, user_id=user_id, campaign_id=campaign["id"], limit=limit
        )
        tracked_rows = []
        tracked_snapshot_count = 0
        inserted = 0
        updated = 0
        backfilled_edges = 0
        skipped = 0
        skipped_rows: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if posts_truncated:
            raise RuntimeError(
                f"campaign-filtered posts read exceeded limit {limit}; refusing truncated sync"
            )
        metric_history_error: str | None = None
        history_source_counts: dict[str, int] = {}
        learning_ineligible_reasons: dict[str, int] = {}
        learning_ineligible_snapshot_count = 0
        learning_ineligible_post_ids: set[str] = set()
        metric_history_post_ids: list[str] = []
        for row in rows:
            row_metadata = (
                row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            )
            campaign_metadata = (
                row_metadata.get("campaign_factory")
                if isinstance(row_metadata, dict)
                else None
            )
            if not isinstance(campaign_metadata, dict) or not campaign_metadata:
                continue
            metadata_campaign = campaign_metadata.get("campaign_id")
            if metadata_campaign not in {campaign["id"], campaign_slug}:
                continue
            if row.get("id"):
                metric_history_post_ids.append(str(row["id"]))
        try:
            metric_history_rows, metric_history_truncated = (
                _select_threadsdash_post_metric_history(
                    client,
                    post_ids=metric_history_post_ids,
                    limit=limit,
                )
            )
            if metric_history_truncated:
                raise RuntimeError(
                    "campaign metric history read was truncated; refusing partial sync"
                )
        except RuntimeError as exc:
            metric_history_rows = []
            metric_history_error = str(exc)
            warnings.append(
                {
                    "reason": "metric_history_unavailable",
                    "message": str(exc),
                }
            )
        _validate_threadsdash_post_metric_history_read(metric_history_rows)
        metric_history_by_post = _group_metric_history_by_post(metric_history_rows)
        for row in rows:
            row_metadata = (
                row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            )
            meta = (
                row_metadata.get("campaign_factory")
                if isinstance(row_metadata, dict)
                else None
            ) or {}
            if not isinstance(meta, dict) or not meta:
                skipped += 1
                post_id = str(row.get("id") or "unknown")
                learning_ineligible_post_ids.add(post_id)
                learning_ineligible_reasons["manual_no_lineage"] = (
                    learning_ineligible_reasons.get("manual_no_lineage", 0) + 1
                )
                warning = _performance_sync_skip_warning(
                    row,
                    reason="missing_campaign_factory_metadata",
                    learningIneligibleReason="manual_no_lineage",
                )
                skipped_rows.append(warning)
                warnings.append(warning)
                _dead_letter_performance_sync_row(
                    factory,
                    campaign_id=campaign["id"],
                    row=row,
                    reason="missing_campaign_factory_metadata",
                    reason_code="threadsdash_performance_missing_campaign_metadata",
                    severity="medium",
                )
                continue
            if meta.get("campaign_id") and meta.get("campaign_id") != campaign_slug:
                skipped += 1
                skipped_rows.append(
                    _performance_sync_skip_warning(
                        row,
                        reason="campaign_mismatch",
                        campaignId=meta.get("campaign_id"),
                    )
                )
                continue
            row, meta, lineage_repair = _repair_learning_lineage_from_local_asset(
                factory, row=row, meta=meta
            )
            if lineage_repair["repairedFields"] or lineage_repair["blockingReasons"]:
                warning = {
                    "postId": row.get("id"),
                    "renderedAssetId": meta.get("rendered_asset_id"),
                    "reason": "learning_lineage_repair",
                    **lineage_repair,
                }
                warnings.append(warning)
            meta = _with_local_caption_outcome_context(factory, meta)
            eligibility = _metrics_eligibility_for_threadsdash_row(
                factory, row=row, meta=meta
            )
            if not eligibility["eligible"]:
                skipped += 1
                post_id = str(row.get("id") or "unknown")
                learning_ineligible_post_ids.add(post_id)
                learning_ineligible_reasons["metrics_not_eligible"] = (
                    learning_ineligible_reasons.get("metrics_not_eligible", 0) + 1
                )
                warning = {
                    "postId": row.get("id"),
                    "renderedAssetId": meta.get("rendered_asset_id"),
                    "reason": "metrics_not_eligible",
                    "blockingReasons": eligibility["blockingReasons"],
                }
                skipped_rows.append(warning)
                warnings.append(warning)
                continue
            tracked_rows.append(row)
            for sync_row in _threadsdash_performance_rows(
                row, metric_history_by_post.get(str(row.get("id")) or "", [])
            ):
                tracked_snapshot_count += 1
                snapshot = _performance_snapshot_from_row(
                    campaign_id=campaign["id"],
                    row=sync_row,
                    meta={**meta, "metrics_eligible": True},
                )
                history_source = str(
                    snapshot.get("history_source") or "post_row_fallback"
                )
                history_source_counts[history_source] = (
                    history_source_counts.get(history_source, 0) + 1
                )
                ineligible_reasons = learning_ineligibility_reasons(snapshot)
                for reason in ineligible_reasons:
                    learning_ineligible_reasons[reason] = (
                        learning_ineligible_reasons.get(reason, 0) + 1
                    )
                if ineligible_reasons:
                    learning_ineligible_snapshot_count += 1
                    learning_ineligible_post_ids.add(str(snapshot["post_id"]))
                existing = factory.conn.execute(
                    "SELECT id FROM performance_snapshots WHERE post_id = ? AND snapshot_at = ?",
                    (snapshot["post_id"], snapshot["snapshot_at"]),
                ).fetchone()
                factory.conn.execute(
                    """
                    INSERT INTO performance_snapshots
                    (id, campaign_id, rendered_asset_id, source_asset_id, content_hash, source_content_hash,
                     concept_id, parent_reel_id, variant_family_id, variant_id, variant_index,
                     variant_operations_json, audio_id, caption_family_id, caption_version_id,
                     caption_hash, caption_text, caption_bank, caption_banks_json, creator_mix, creator_model,
                     frame_type, length_class, format_class, caption_fit_version, suitability_decision,
                     suitability_reason, source_clip, caption_outcome_context_json, recipe,
                     post_id, platform, content_surface, status, account_id, instagram_account_id,
                     permalink, published_at, snapshot_at, views, likes, comments, shares, saves, impressions,
                     reach, watch_time_seconds, metrics_eligible, history_source, lineage_v2_valid, raw_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(post_id, snapshot_at) DO UPDATE SET
                      campaign_id = excluded.campaign_id,
                      rendered_asset_id = excluded.rendered_asset_id,
                      source_asset_id = excluded.source_asset_id,
                      content_hash = excluded.content_hash,
                      source_content_hash = excluded.source_content_hash,
                      concept_id = excluded.concept_id,
                      parent_reel_id = excluded.parent_reel_id,
                      variant_family_id = excluded.variant_family_id,
                      variant_id = excluded.variant_id,
                      variant_index = excluded.variant_index,
                      variant_operations_json = excluded.variant_operations_json,
                      audio_id = excluded.audio_id,
                      caption_family_id = excluded.caption_family_id,
                      caption_version_id = excluded.caption_version_id,
                      caption_hash = excluded.caption_hash,
                      caption_text = excluded.caption_text,
                      caption_bank = excluded.caption_bank,
                      caption_banks_json = excluded.caption_banks_json,
                      creator_mix = excluded.creator_mix,
                      creator_model = excluded.creator_model,
                      frame_type = excluded.frame_type,
                      length_class = excluded.length_class,
                      format_class = excluded.format_class,
                      caption_fit_version = excluded.caption_fit_version,
                      suitability_decision = excluded.suitability_decision,
                      suitability_reason = excluded.suitability_reason,
                      source_clip = excluded.source_clip,
                      caption_outcome_context_json = excluded.caption_outcome_context_json,
                      recipe = excluded.recipe,
                      platform = excluded.platform,
                      content_surface = excluded.content_surface,
                      status = excluded.status,
                      account_id = excluded.account_id,
                      instagram_account_id = excluded.instagram_account_id,
                      permalink = excluded.permalink,
                      published_at = excluded.published_at,
                      views = excluded.views,
                      likes = excluded.likes,
                      comments = excluded.comments,
                      shares = excluded.shares,
                      saves = excluded.saves,
                      impressions = excluded.impressions,
                      reach = excluded.reach,
                      watch_time_seconds = excluded.watch_time_seconds,
                      metrics_eligible = excluded.metrics_eligible,
                      history_source = excluded.history_source,
                      lineage_v2_valid = excluded.lineage_v2_valid,
                      raw_json = excluded.raw_json
                    """,
                    (
                        snapshot["id"],
                        snapshot["campaign_id"],
                        snapshot["rendered_asset_id"],
                        snapshot["source_asset_id"],
                        snapshot["content_hash"],
                        snapshot["source_content_hash"],
                        snapshot["concept_id"],
                        snapshot["parent_reel_id"],
                        snapshot["variant_family_id"],
                        snapshot["variant_id"],
                        snapshot["variant_index"],
                        snapshot["variant_operations_json"],
                        snapshot["audio_id"],
                        snapshot["caption_family_id"],
                        snapshot["caption_version_id"],
                        snapshot["caption_hash"],
                        snapshot["caption_text"],
                        snapshot["caption_bank"],
                        snapshot["caption_banks_json"],
                        snapshot["creator_mix"],
                        snapshot["creator_model"],
                        snapshot["frame_type"],
                        snapshot["length_class"],
                        snapshot["format_class"],
                        snapshot["caption_fit_version"],
                        snapshot["suitability_decision"],
                        snapshot["suitability_reason"],
                        snapshot["source_clip"],
                        snapshot["caption_outcome_context_json"],
                        snapshot["recipe"],
                        snapshot["post_id"],
                        snapshot["platform"],
                        snapshot["content_surface"],
                        snapshot["status"],
                        snapshot["account_id"],
                        snapshot["instagram_account_id"],
                        snapshot["permalink"],
                        snapshot["published_at"],
                        snapshot["snapshot_at"],
                        snapshot["views"],
                        snapshot["likes"],
                        snapshot["comments"],
                        snapshot["shares"],
                        snapshot["saves"],
                        snapshot["impressions"],
                        snapshot["reach"],
                        snapshot["watch_time_seconds"],
                        snapshot["metrics_eligible"],
                        snapshot["history_source"],
                        snapshot["lineage_v2_valid"],
                        snapshot["raw_json"],
                        snapshot["created_at"],
                    ),
                )
                if existing:
                    updated += 1
                    snapshot["id"] = existing["id"]
                else:
                    inserted += 1
                post_graph_id = factory.ensure_graph_node(
                    "threadsdash_post",
                    external_system="threadsdash.posts",
                    external_id=snapshot["post_id"],
                    payload={
                        "postId": snapshot["post_id"],
                        "status": snapshot["status"],
                        "campaignId": meta.get("campaign_id"),
                        "renderedAssetId": snapshot["rendered_asset_id"],
                    },
                )
                rendered_graph_id = meta.get("rendered_asset_graph_id") or meta.get(
                    "graph_id"
                )
                required_missing = [
                    key
                    for key in (
                        "graph_id",
                        "campaign_graph_id",
                        "source_asset_graph_id",
                        "rendered_asset_graph_id",
                    )
                    if not meta.get(key)
                ]
                if required_missing:
                    warning = {
                        "postId": snapshot["post_id"],
                        "missingGraphIds": required_missing,
                    }
                    warnings.append(warning)
                    factory.create_exception(
                        reason_code="performance_sync_missing_graph_ids",
                        severity="medium",
                        campaign_id=campaign["id"],
                        entity_graph_id=post_graph_id,
                        payload=warning,
                        commit=False,
                    )
                if not rendered_graph_id and snapshot["rendered_asset_id"]:
                    rendered_graph_id = factory.graph_id_for(
                        "rendered_assets",
                        snapshot["rendered_asset_id"],
                        entity_type="rendered_asset",
                    )
                before_edges = factory.conn.total_changes
                factory.ensure_graph_edge_strict(
                    rendered_graph_id,
                    post_graph_id,
                    "rendered_asset_to_threadsdash_post",
                    evidence={"postId": snapshot["post_id"], "performanceSync": True},
                    campaign_id=campaign["id"],
                    source_operation="threadsdash_performance_sync",
                )
                performance_graph_id = factory.ensure_graph_node(
                    "performance_snapshot",
                    local_table="performance_snapshots",
                    local_id=snapshot["id"],
                    payload={
                        "postId": snapshot["post_id"],
                        "snapshotAt": snapshot["snapshot_at"],
                        "views": snapshot["views"],
                        "likes": snapshot["likes"],
                        "comments": snapshot["comments"],
                        "shares": snapshot["shares"],
                        "saves": snapshot["saves"],
                    },
                )
                factory.ensure_graph_edge_strict(
                    post_graph_id,
                    performance_graph_id,
                    "threadsdash_post_to_performance_snapshot",
                    evidence={"snapshotAt": snapshot["snapshot_at"]},
                    campaign_id=campaign["id"],
                    source_operation="threadsdash_performance_sync",
                )
                recommendation_graph_id = factory.ensure_graph_node(
                    "recommendation_input",
                    external_system="campaign_factory.recommendation_input",
                    external_id=snapshot["id"],
                    payload={
                        "performanceSnapshotId": snapshot["id"],
                        "campaignId": campaign["id"],
                    },
                )
                factory.ensure_graph_edge_strict(
                    performance_graph_id,
                    recommendation_graph_id,
                    "performance_snapshot_to_recommendation_input",
                    evidence={"source": "threadsdash_performance_sync"},
                    campaign_id=campaign["id"],
                    source_operation="threadsdash_performance_sync",
                )
                audio_rollup = factory.record_audio_performance_snapshot(
                    snapshot, commit=False
                )
                if audio_rollup:
                    performance_payload = (
                        json.loads(snapshot["raw_json"])
                        if isinstance(snapshot.get("raw_json"), str)
                        else {}
                    )
                    campaign_meta = (
                        (
                            (performance_payload.get("metadata") or {}).get(
                                "campaign_factory"
                            )
                            or {}
                        )
                        if isinstance(performance_payload, dict)
                        else {}
                    )
                    selection = (
                        (
                            (campaign_meta.get("audio_intent") or {}).get(
                                "operator_selection"
                            )
                            or {}
                        )
                        if isinstance(campaign_meta.get("audio_intent"), dict)
                        else {}
                    )
                    if isinstance(selection, dict) and selection:
                        audio_selection_graph_id = factory.ensure_graph_node(
                            "audio_selection",
                            external_system="threadsdash.audio_selection",
                            external_id=f"{snapshot['post_id']}:{audio_rollup['audioKey']}",
                            payload={"postId": snapshot["post_id"], "audio": selection},
                        )
                        factory.ensure_graph_edge(
                            audio_selection_graph_id,
                            post_graph_id,
                            "audio_selection_to_threadsdash_post",
                        )
                        factory.ensure_graph_edge(
                            audio_selection_graph_id,
                            performance_graph_id,
                            "audio_selection_to_performance_snapshot",
                        )
                if existing and factory.conn.total_changes > before_edges:
                    backfilled_edges += 1
        factory.set_graph_sync_state(
            "threadsdash.performance",
            {
                "campaign": campaign_slug,
                "userId": user_id,
                "postsScanned": len(rows),
                "postsImported": len(tracked_rows),
                "campaignFactoryPostsScanned": len(tracked_rows),
                "metricHistoryRowsScanned": len(metric_history_rows),
                "metricHistoryError": metric_history_error,
                "historySources": history_source_counts,
                "learningIneligiblePosts": len(learning_ineligible_post_ids),
                "learningIneligibleSnapshots": learning_ineligible_snapshot_count,
                "learningIneligibleReasons": learning_ineligible_reasons,
                "campaignFactorySnapshotsScanned": tracked_snapshot_count,
                "inserted": inserted,
                "updated": updated,
                "backfilledEdges": backfilled_edges,
                "warnings": warnings,
                "skipReasons": _sync_reason_counts(skipped_rows),
            },
        )
        factory.conn.commit()
        summary = factory.performance_summary(campaign_slug)
        learning_readiness = closed_loop_learning_status(
            factory.conn, campaign_slug=campaign_slug
        )
        result = {
            "schema": "campaign_factory.performance_sync.v1",
            "campaign": campaign_slug,
            "userId": user_id,
            "checkedAt": utc_now(),
            "postsScanned": len(rows),
            "postsImported": len(tracked_rows),
            "campaignFactoryPostsScanned": len(tracked_rows),
            "metricHistoryRowsScanned": len(metric_history_rows),
            "metricHistoryError": metric_history_error,
            "historySources": history_source_counts,
            "fallbackRows": history_source_counts.get("post_row_fallback", 0),
            "learningIneligiblePosts": len(learning_ineligible_post_ids),
            "learningIneligibleSnapshots": learning_ineligible_snapshot_count,
            "learningIneligibleReasons": learning_ineligible_reasons,
            "learningLoopCutover": learning_loop_cutover_iso(),
            "learningReadiness": learning_readiness,
            "campaignFactorySnapshotsScanned": tracked_snapshot_count,
            "inserted": inserted,
            "updated": updated,
            "backfilledEdges": backfilled_edges,
            "skipped": skipped,
            "skipReasons": _sync_reason_counts(skipped_rows),
            "warnings": warnings,
            "summary": summary,
            "pipelineJobId": pipeline_job["id"],
            "pipelineTraceId": f"trace_performance_sync_{pipeline_job['id']}",
        }
        validate_performance_sync(result)
        factory.record_event(
            "performance_synced",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="success",
            message=f"Performance synced: {inserted} inserted, {updated} updated, {skipped} skipped",
            metadata={
                "postsScanned": len(rows),
                "postsImported": len(tracked_rows),
                "campaignFactoryPostsScanned": len(tracked_rows),
                "metricHistoryRowsScanned": len(metric_history_rows),
                "metricHistoryError": metric_history_error,
                "historySources": history_source_counts,
                "learningIneligiblePosts": len(learning_ineligible_post_ids),
                "learningIneligibleSnapshots": learning_ineligible_snapshot_count,
                "learningIneligibleReasons": learning_ineligible_reasons,
                "campaignFactorySnapshotsScanned": tracked_snapshot_count,
                "inserted": inserted,
                "updated": updated,
                "backfilledEdges": backfilled_edges,
                "skipped": skipped,
                "skipReasons": _sync_reason_counts(skipped_rows),
                "warnings": warnings,
            },
        )
        factory.finish_pipeline_job(
            pipeline_job["id"],
            {
                "postsScanned": len(rows),
                "postsImported": len(tracked_rows),
                "campaignFactoryPostsScanned": len(tracked_rows),
                "metricHistoryRowsScanned": len(metric_history_rows),
                "metricHistoryError": metric_history_error,
                "historySources": history_source_counts,
                "learningIneligiblePosts": len(learning_ineligible_post_ids),
                "learningIneligibleSnapshots": learning_ineligible_snapshot_count,
                "learningIneligibleReasons": learning_ineligible_reasons,
                "campaignFactorySnapshotsScanned": tracked_snapshot_count,
                "inserted": inserted,
                "updated": updated,
                "backfilledEdges": backfilled_edges,
                "skipped": skipped,
                "skipReasons": _sync_reason_counts(skipped_rows),
            },
        )
        return result
    except Exception as exc:
        factory.record_event(
            "performance_synced",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"Performance sync failed: {exc}",
            metadata={"error": str(exc)},
        )
        factory.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


THREADSDASH_POSTS_PAGE_SIZE = 500


def _select_paged(
    client: SupabaseRestClient,
    table: str,
    params: dict[str, str],
    *,
    limit: int,
    page_size: int,
    probe_select: str = "id",
) -> tuple[list[dict[str, Any]], bool]:
    """Fetch up to ``limit`` rows in pages of ``page_size``.

    Returns ``(rows, truncated)`` where ``truncated`` is True when at least
    one additional row exists beyond ``limit``.
    """
    rows: list[dict[str, Any]] = []
    offset = 0
    while len(rows) < limit:
        page_limit = min(page_size, limit - len(rows))
        page = client.select(
            table,
            {**params, "limit": str(page_limit), "offset": str(offset)},
        )
        rows.extend(page)
        if not page:
            # Empty page: definitive end of data.
            return rows, False
        # A short-but-non-empty page is NOT proof of end-of-data: PostgREST
        # `max-rows` (or any server-side cap) can silently clamp a page below
        # the requested limit. Keep paging from the real offset until an empty
        # page or `limit` is reached, so a server cap can never silently
        # truncate a sync (audit: partial-sync failure injection).
        offset += len(page)
    probe = client.select(
        table,
        {**params, "select": probe_select, "limit": "1", "offset": str(offset)},
    )
    return rows, bool(probe)


def _select_threadsdash_posts_paged(
    client: SupabaseRestClient,
    *,
    user_id: str,
    campaign_id: str | None = None,
    limit: int,
    page_size: int = THREADSDASH_POSTS_PAGE_SIZE,
) -> tuple[list[dict[str, Any]], bool]:
    base_params = {
        "user_id": f"eq.{user_id}",
        "order": "created_at.desc",
    }
    if campaign_id:
        base_params["metadata->campaign_factory->>campaign_id"] = f"eq.{campaign_id}"
    rich_select = (
        "id,status,platform,media_type,ig_media_type,content_surface,account_id,instagram_account_id,created_at,updated_at,scheduled_for,"
        "published_at,permalink,instagram_post_id,content,metadata,views_count,ig_views,"
        "likes_count,replies_count,ig_comment_count,"
        "shares_count,ig_shares,ig_saved,"
        "ig_reach,ig_impressions,"
        "ig_reels_avg_watch_time,ig_reels_video_view_total_time"
    )
    try:
        return _select_paged(
            client,
            "posts",
            {"select": rich_select, **base_params},
            limit=limit,
            page_size=page_size,
        )
    except RuntimeError as exc:
        # Only fall back to the narrow column set when the error is a
        # missing-column/schema mismatch. Transient failures (5xx, network)
        # must propagate: silently retrying them with a narrower select would
        # sync rows without published_at/metric columns and quietly make every
        # post learning-ineligible (audit: partial-sync failure injection).
        if not _is_missing_column_error(exc):
            raise
        return _select_paged(
            client,
            "posts",
            {
                "select": "id,status,platform,media_type,ig_media_type,content_surface,account_id,instagram_account_id,created_at,scheduled_for,content,metadata",
                **base_params,
            },
            limit=limit,
            page_size=page_size,
        )


def _is_missing_column_error(exc: Exception) -> bool:
    """True when a Supabase/PostgREST error indicates a schema/column mismatch
    (safe to retry with a narrower select), as opposed to a transient failure."""
    message = str(exc)
    return (
        "does not exist" in message
        or "42703" in message
        or "Could not find" in message
        or "schema cache" in message
    )


def _select_threadsdash_posts(
    client: SupabaseRestClient, *, user_id: str, limit: int
) -> list[dict[str, Any]]:
    rows, _truncated = _select_threadsdash_posts_paged(
        client, user_id=user_id, limit=limit
    )
    return rows


def _select_threadsdash_post_metric_history(
    client: SupabaseRestClient,
    *,
    post_ids: list[str],
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Returns ``(rows, truncated)``; ``truncated`` means at least one batch
    had more history rows than its per-batch limit allowed."""
    ids = sorted({post_id for post_id in post_ids if post_id})
    if not ids:
        return [], False
    select_columns = (
        "id,post_id,account_id,platform,snapshot_at,hours_since_publish,"
        "views_count,likes_count,replies_count,reposts_count,quotes_count,shares_count,"
        "saves_count,reach,engagement_rate"
    )
    rows: list[dict[str, Any]] = []
    truncated = False
    for offset in range(0, len(ids), POST_METRIC_HISTORY_POST_ID_BATCH_SIZE):
        batch = ids[offset : offset + POST_METRIC_HISTORY_POST_ID_BATCH_SIZE]
        batch_limit = max(limit, len(batch) * 24)
        batch_rows, batch_truncated = _select_paged(
            client,
            "post_metric_history",
            {
                "select": select_columns,
                "post_id": f"in.({','.join(batch)})",
                "order": "snapshot_at.asc",
            },
            limit=batch_limit,
            page_size=batch_limit,
        )
        truncated = truncated or batch_truncated
        rows.extend(batch_rows)
    return rows, truncated


def _validate_threadsdash_post_metric_history_read(rows: list[dict[str, Any]]) -> None:
    try:
        validate_post_metric_history_read(
            {
                "schema": "threadsdashboard.post_metric_history.read.v1",
                "rows": rows,
            }
        )
    except ContractValidationError as exc:
        raise RuntimeError(
            f"post_metric_history.read.v1 validation failed: {exc}"
        ) from exc


def _group_metric_history_by_post(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        post_id = str(row.get("post_id") or "")
        if not post_id:
            continue
        grouped.setdefault(post_id, []).append(row)
    for post_rows in grouped.values():
        post_rows.sort(key=lambda item: str(item.get("snapshot_at") or ""))
    return grouped


def _threadsdash_performance_rows(
    post_row: dict[str, Any], metric_history_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not metric_history_rows:
        return [{**post_row, "history_source": "post_row_fallback"}]
    return [
        _threadsdash_post_with_metric_history(post_row, history_row)
        for history_row in metric_history_rows
    ]


def _threadsdash_post_with_metric_history(
    post_row: dict[str, Any], history_row: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(post_row)
    merged["history_source"] = "metric_history"
    merged["metrics_updated_at"] = history_row["snapshot_at"]
    merged["views"] = history_row.get("views_count")
    merged["views_count"] = history_row.get("views_count")
    merged["likes"] = history_row.get("likes_count")
    merged["likes_count"] = history_row.get("likes_count")
    merged["comments"] = history_row.get("replies_count")
    merged["replies_count"] = history_row.get("replies_count")
    merged["reposts_count"] = history_row.get("reposts_count")
    merged["quotes_count"] = history_row.get("quotes_count")
    merged["shares"] = history_row.get("shares_count")
    merged["shares_count"] = history_row.get("shares_count")
    merged["saves"] = history_row.get("saves_count")
    merged["saves_count"] = history_row.get("saves_count")
    merged["reach"] = history_row.get("reach")
    merged["engagement_rate"] = history_row.get("engagement_rate")
    merged["account_id"] = post_row.get("account_id") or history_row.get("account_id")
    merged["platform"] = post_row.get("platform") or history_row.get("platform")
    metadata = dict(
        post_row.get("metadata") if isinstance(post_row.get("metadata"), dict) else {}
    )
    metadata["threadsdash_metric_history"] = {
        "id": history_row.get("id"),
        "postId": history_row.get("post_id"),
        "snapshotAt": history_row.get("snapshot_at"),
        "hoursSincePublish": history_row.get("hours_since_publish"),
    }
    merged["metadata"] = metadata
    return merged


def _performance_sync_skip_warning(
    row: dict[str, Any], *, reason: str, **extra: Any
) -> dict[str, Any]:
    warning = {
        "postId": row.get("id"),
        "platform": row.get("platform"),
        "status": row.get("status"),
        "reason": reason,
    }
    warning.update({key: value for key, value in extra.items() if value is not None})
    return warning


def _dead_letter_performance_sync_row(
    factory: CampaignFactory,
    *,
    campaign_id: str,
    row: dict[str, Any],
    reason: str,
    reason_code: str,
    severity: str,
) -> None:
    post_id = str(row.get("id") or new_id("threadsdash_post"))
    post_graph_id = factory.ensure_graph_node(
        "threadsdash_post",
        external_system="threadsdash.posts",
        external_id=post_id,
        payload={
            "postId": post_id,
            "platform": row.get("platform"),
            "status": row.get("status"),
            "missingCampaignFactoryMetadata": reason
            == "missing_campaign_factory_metadata",
        },
    )
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    factory.create_exception(
        reason_code=reason_code,
        severity=severity,
        campaign_id=campaign_id,
        entity_graph_id=post_graph_id,
        payload={
            "postId": post_id,
            "reason": reason,
            "platform": row.get("platform"),
            "status": row.get("status"),
            "metadataKeys": sorted(str(key) for key in metadata.keys()),
        },
        commit=False,
    )


def _performance_snapshot_from_row(
    *, campaign_id: str, row: dict[str, Any], meta: dict[str, Any]
) -> dict[str, Any]:
    metrics_meta = _merged_metric_metadata(row.get("metadata"))
    if row.get("history_source") == "metric_history":
        snapshot_at = row.get("metrics_updated_at")
        if not snapshot_at:
            raise RuntimeError(
                "metric_history row missing validated snapshot_at; refusing post timestamp fallback"
            )
    else:
        snapshot_at = (
            row.get("metrics_updated_at")
            or row.get("insights_updated_at")
            or row.get("updated_at")
            or row.get("published_at")
            or row.get("publishedAt")
            or row.get("created_at")
            or utc_now()
        )
    post_id = str(row.get("id") or new_id("post"))
    caption_hash = meta.get("caption_hash") or _text_hash(row.get("content") or "")
    caption_lineage = (
        meta.get("captionOutcomeContext")
        if isinstance(meta.get("captionOutcomeContext"), dict)
        else (
            meta.get("caption_outcome_context")
            if isinstance(meta.get("caption_outcome_context"), dict)
            else meta
        )
    )
    creator_model_fallback = None
    if not (
        isinstance(caption_lineage, dict)
        and caption_lineage.get("schema")
        == "campaign_factory.caption_outcome_context.v1"
    ):
        creator_model_fallback = meta.get("model_slug") or meta.get("model_id")
    caption_context = build_caption_outcome_context(
        caption_text=row.get("content"),
        caption_hash=caption_hash,
        creator_model=creator_model_fallback,
        lineage=caption_lineage,
    )
    caption_columns = column_values(caption_context)
    caption_hash = caption_context.get("caption_hash") or caption_hash
    content_surface = normalize_content_surface(
        meta.get("content_surface")
        or meta.get("contentSurface")
        or _post_surface(row, meta)
    )
    metric_contract = _metric_contract_metadata(
        row=row, meta=meta, metrics_meta=metrics_meta, content_surface=content_surface
    )
    raw_row = dict(row)
    raw_row["metric_contract"] = metric_contract
    return {
        "id": new_id("perf"),
        "campaign_id": campaign_id,
        "rendered_asset_id": meta.get("rendered_asset_id"),
        "source_asset_id": meta.get("source_asset_id"),
        "content_hash": meta.get("content_hash"),
        "source_content_hash": meta.get("source_content_hash"),
        "concept_id": meta.get("concept_id") or meta.get("conceptId"),
        "parent_reel_id": meta.get("parent_reel_id") or meta.get("parentReelId"),
        "variant_family_id": meta.get("variant_family_id")
        or meta.get("variantFamilyId"),
        "variant_id": meta.get("variant_id") or meta.get("variantId"),
        "variant_index": meta.get("variant_index") or meta.get("variantIndex"),
        "variant_operations_json": json.dumps(
            meta.get("variant_operations") or meta.get("variantOperations") or [],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "audio_id": meta.get("audio_id")
        or meta.get("audioId")
        or (
            (meta.get("handoff_manifest") or {}).get("audio_id")
            if isinstance(meta.get("handoff_manifest"), dict)
            else None
        ),
        "caption_family_id": (
            meta.get("caption_family_id")
            or meta.get("captionFamilyId")
            or caption_context.get("caption_family_id")
            or caption_context.get("captionFamilyId")
            or (
                (meta.get("handoff_manifest") or {}).get("caption_family_id")
                if isinstance(meta.get("handoff_manifest"), dict)
                else None
            )
        ),
        "caption_version_id": (
            meta.get("caption_version_id")
            or meta.get("captionVersionId")
            or caption_context.get("caption_version_id")
            or caption_context.get("captionVersionId")
            or (
                (meta.get("handoff_manifest") or {}).get("caption_version_id")
                if isinstance(meta.get("handoff_manifest"), dict)
                else None
            )
        ),
        "caption_hash": caption_hash,
        "caption_text": caption_columns["caption_text"],
        "caption_bank": caption_columns["caption_bank"],
        "caption_banks_json": caption_columns["caption_banks_json"],
        "creator_mix": caption_columns["creator_mix"],
        "creator_model": caption_columns["creator_model"],
        "frame_type": caption_columns["frame_type"],
        "length_class": caption_columns["length_class"],
        "format_class": caption_columns["format_class"],
        "caption_fit_version": caption_columns["caption_fit_version"],
        "suitability_decision": caption_columns["suitability_decision"],
        "suitability_reason": caption_columns["suitability_reason"],
        "source_clip": caption_columns["source_clip"],
        "caption_outcome_context_json": caption_columns["caption_outcome_context_json"],
        "recipe": meta.get("recipe") or caption_context.get("render_recipe"),
        "post_id": post_id,
        "platform": row.get("platform"),
        "content_surface": content_surface,
        "status": row.get("status"),
        "account_id": row.get("account_id"),
        "instagram_account_id": row.get("instagram_account_id"),
        "permalink": row.get("permalink") or row.get("url") or meta.get("permalink"),
        "published_at": row.get("published_at")
        or row.get("publishedAt")
        or meta.get("published_at"),
        "snapshot_at": str(snapshot_at),
        "views": _int_metric(
            row, metrics_meta, "views", "view_count", "views_count", "ig_views"
        ),
        "likes": _int_metric(row, metrics_meta, "likes", "like_count", "likes_count"),
        "comments": _int_metric(
            row,
            metrics_meta,
            "comments",
            "comment_count",
            "comments_count",
            "replies_count",
            "ig_comment_count",
        ),
        "shares": _int_metric(
            row, metrics_meta, "shares", "share_count", "shares_count", "ig_shares"
        ),
        "saves": _int_metric(
            row, metrics_meta, "saves", "save_count", "saves_count", "ig_saved"
        ),
        "impressions": _int_metric(
            row,
            metrics_meta,
            "impressions",
            "impression_count",
            "impressions_count",
            "ig_impressions",
        ),
        "reach": _int_metric(row, metrics_meta, "reach", "ig_reach"),
        "watch_time_seconds": _float_metric(
            row,
            metrics_meta,
            "watch_time_seconds",
            "watchTimeSeconds",
            "watch_time",
            "ig_reels_avg_watch_time",
            "ig_reels_video_view_total_time",
        ),
        "metrics_eligible": 1 if meta.get("metrics_eligible") else 0,
        "history_source": row.get("history_source") or "post_row_fallback",
        "lineage_v2_valid": 1
        if not meta.get("learning_lineage_blocking_reasons")
        and lineage_v2_is_learning_traceable(
            meta.get("generated_asset_lineage"),
            campaign_id=meta.get("campaign_id"),
            recipe_id=meta.get("recipe"),
            caption_hash=meta.get("caption_hash"),
            rendered_asset_id=meta.get("rendered_asset_id"),
            variant_id=meta.get("variant_asset_id"),
        )
        else 0,
        "learning_lineage_blocking_reasons": meta.get(
            "learning_lineage_blocking_reasons"
        )
        or [],
        "raw_json": json.dumps(raw_row, ensure_ascii=False, sort_keys=True),
        "created_at": utc_now(),
    }


def _repair_learning_lineage_from_local_asset(
    factory: CampaignFactory, *, row: dict[str, Any], meta: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[str]]]:
    """Fill missing cohort identities from one canonical local rendered asset.

    Conflicts are never overwritten. They remain visible in the stored raw row
    and force the snapshot out of learning until an operator resolves them.
    """
    repaired_fields: list[str] = []
    blockers: list[str] = []
    rendered_asset_id = str(meta.get("rendered_asset_id") or "").strip()
    if not rendered_asset_id:
        return (
            row,
            meta,
            {
                "repairedFields": repaired_fields,
                "blockingReasons": ["missing_rendered_asset_id"],
            },
        )
    local = factory.conn.execute(
        """
        SELECT r.id, r.campaign_id, r.source_asset_id, r.recipe, r.caption_hash,
               r.content_hash, r.caption_generation_json, s.source_prompt,
               c.slug AS campaign_slug
        FROM rendered_assets r
        JOIN source_assets s ON s.id = r.source_asset_id
        JOIN campaigns c ON c.id = r.campaign_id
        WHERE r.id = ?
        """,
        (rendered_asset_id,),
    ).fetchone()
    if not local:
        return (
            row,
            meta,
            {
                "repairedFields": repaired_fields,
                "blockingReasons": ["rendered_asset_not_found"],
            },
        )

    incoming_campaign = str(meta.get("campaign_id") or "").strip()
    if incoming_campaign and incoming_campaign not in {
        str(local["campaign_id"]),
        str(local["campaign_slug"]),
    }:
        blockers.append("campaign_identity_conflict")

    next_meta = dict(meta)
    incoming_lineage = (
        dict(meta.get("generated_asset_lineage"))
        if isinstance(meta.get("generated_asset_lineage"), dict)
        else {}
    )
    generation_payload = _json_mapping(local["caption_generation_json"])
    stored_lineage = generation_payload.get("generatedAssetLineage")
    if not isinstance(stored_lineage, dict):
        stored_lineage = {}
    lineage = {**stored_lineage, **incoming_lineage}
    if stored_lineage and not incoming_lineage:
        repaired_fields.append("generated_asset_lineage")
    source_prompt = _json_mapping(local["source_prompt"])
    stored_source = (
        stored_lineage.get("source")
        if isinstance(stored_lineage.get("source"), dict)
        else {}
    )
    incoming_source = (
        dict(lineage.get("source")) if isinstance(lineage.get("source"), dict) else {}
    )

    identity_sources = {
        "promptId": _unique_identity(
            stored_source.get("promptId"),
            source_prompt.get("promptId"),
            source_prompt.get("prompt_id"),
        ),
        "referenceId": _unique_identity(
            stored_source.get("referenceId"),
            source_prompt.get("referenceId"),
            source_prompt.get("reference_id"),
        ),
    }
    for field, candidates in identity_sources.items():
        incoming = str(incoming_source.get(field) or "").strip()
        if len(candidates) > 1:
            blockers.append(f"ambiguous_local_{field}")
        elif incoming and candidates and incoming not in candidates:
            blockers.append(f"{field}_conflict")
        elif not incoming and len(candidates) == 1:
            incoming_source[field] = next(iter(candidates))
            repaired_fields.append(f"source.{field}")
    for field in ("promptId", "referenceId"):
        if not str(incoming_source.get(field) or "").strip():
            blockers.append(f"missing_{field}")

    lineage_fields = {
        "campaignId": str(local["campaign_slug"] or "").strip(),
        "recipeId": str(local["recipe"] or meta.get("recipe") or "").strip(),
        "captionHash": str(
            local["caption_hash"] or meta.get("caption_hash") or ""
        ).strip(),
        "renderedAssetId": rendered_asset_id,
        "contentFingerprint": str(local["content_hash"] or "").strip(),
    }
    for field, canonical in lineage_fields.items():
        incoming = str(lineage.get(field) or "").strip()
        if incoming and canonical and incoming != canonical:
            blockers.append(f"{field}_conflict")
        elif not incoming and canonical:
            lineage[field] = canonical
            repaired_fields.append(field)
    if incoming_source:
        lineage["source"] = incoming_source
    next_meta["generated_asset_lineage"] = lineage
    next_meta["learning_lineage_blocking_reasons"] = sorted(set(blockers))

    next_row = dict(row)
    metadata = (
        dict(row.get("metadata")) if isinstance(row.get("metadata"), dict) else {}
    )
    metadata["campaign_factory"] = next_meta
    next_row["metadata"] = metadata
    return (
        next_row,
        next_meta,
        {
            "repairedFields": sorted(set(repaired_fields)),
            "blockingReasons": sorted(set(blockers)),
        },
    )


def _json_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _unique_identity(*values: Any) -> set[str]:
    return {text for value in values if (text := str(value or "").strip())}


def _metrics_eligibility_for_threadsdash_row(
    factory: CampaignFactory, *, row: dict[str, Any], meta: dict[str, Any]
) -> dict[str, Any]:
    blockers: list[str] = []
    post_id = row.get("id")
    status = str(row.get("status") or "").strip().lower()
    if status != "published":
        blockers.append("post_not_published")
    rendered_asset_id = meta.get("rendered_asset_id")
    if not rendered_asset_id:
        blockers.append("missing_rendered_asset_id")
    else:
        try:
            asset = factory.rendered_asset(str(rendered_asset_id))
        except ValueError:
            asset = None
            blockers.append("rendered_asset_not_found")
        if factory._active_quarantine_for_asset(str(rendered_asset_id)):
            blockers.append("quarantined_asset")
        if asset:
            local_content_hash = asset.get("content_hash")
            if (
                local_content_hash
                and meta.get("content_hash")
                and local_content_hash != meta.get("content_hash")
            ):
                blockers.append("content_fingerprint_mismatch")
            local_caption_hash = asset.get("caption_hash") or (
                load_context_json(asset.get("caption_outcome_context_json")).get(
                    "caption_hash"
                )
            )
            if (
                local_caption_hash
                and meta.get("caption_hash")
                and local_caption_hash != meta.get("caption_hash")
            ):
                blockers.append("caption_hash_mismatch")
    manifest = meta.get("handoff_manifest")
    if not isinstance(manifest, dict):
        blockers.append("handoff_manifest_missing")
    else:
        if manifest.get("manifest_version") not in {1, 2}:
            blockers.append("handoff_manifest_version_invalid")
        if manifest.get("exported_by_system") != "campaign_factory":
            blockers.append("handoff_manifest_exported_by_system_invalid")
        if rendered_asset_id and manifest.get("asset_id") != rendered_asset_id:
            blockers.append("handoff_manifest_asset_id_mismatch")
        if meta.get("content_hash") and manifest.get("content_fingerprint") != meta.get(
            "content_hash"
        ):
            blockers.append("handoff_manifest_content_fingerprint_mismatch")
        if (
            meta.get("caption_hash")
            and manifest.get("caption_hash") != meta.get("caption_hash")
            and not _story_blank_caption_hash_equivalent(
                row=row, meta=meta, manifest=manifest
            )
        ):
            blockers.append("handoff_manifest_caption_hash_mismatch")
    state = str(meta.get("asset_state") or "").strip().lower()
    platform_state = str(meta.get("platform_state") or "").strip().lower()
    if (
        state not in {"publishable_candidate", "exportable"}
        and platform_state != "platform_draft_validated"
    ):
        blockers.append("asset_not_publishable_or_exportable")
    if meta.get("quarantined"):
        blockers.append("metadata_quarantined")
    if meta.get("publishability_failure_reasons"):
        blockers.append("publishability_failure_reasons_present")
    if post_id and blockers:
        return {"eligible": False, "blockingReasons": sorted(set(blockers))}
    return {"eligible": not blockers, "blockingReasons": sorted(set(blockers))}


def _story_blank_caption_hash_equivalent(
    *, row: dict[str, Any], meta: dict[str, Any], manifest: dict[str, Any]
) -> bool:
    empty_sha256 = hashlib.sha256(b"").hexdigest()
    surface = normalize_content_surface(
        str(
            meta.get("content_surface")
            or manifest.get("contentSurface")
            or manifest.get("content_surface")
            or row.get("content_surface")
            or ""
        )
    )
    ig_media_type = (
        str(
            meta.get("ig_media_type")
            or meta.get("igMediaType")
            or manifest.get("igMediaType")
            or manifest.get("ig_media_type")
            or row.get("ig_media_type")
            or ""
        )
        .strip()
        .upper()
    )
    return (
        surface == "story"
        and ig_media_type in {"STORY", "STORIES"}
        and str(meta.get("caption_hash") or "") == empty_sha256
        and not manifest.get("caption_hash")
    )


def _with_local_caption_outcome_context(
    factory: CampaignFactory, meta: dict[str, Any]
) -> dict[str, Any]:
    rendered_asset_id = meta.get("rendered_asset_id")
    if not rendered_asset_id:
        return meta
    row = factory.conn.execute(
        "SELECT caption_outcome_context_json FROM rendered_assets WHERE id = ?",
        (rendered_asset_id,),
    ).fetchone()
    if not row:
        return meta
    local_context = load_context_json(row["caption_outcome_context_json"])
    if not local_context:
        return meta
    merged = dict(meta)
    merged["captionOutcomeContext"] = local_context
    return merged


def _merged_metric_metadata(metadata: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if not isinstance(metadata, dict):
        return merged
    for key in ("metrics", "insights", "performance"):
        value = metadata.get(key)
        if isinstance(value, dict):
            merged.update(value)
    return merged


def _metric_contract_metadata(
    *,
    row: dict[str, Any],
    meta: dict[str, Any],
    metrics_meta: dict[str, Any],
    content_surface: str,
) -> dict[str, Any]:
    contract = (
        metrics_meta.get("metricContract")
        if isinstance(metrics_meta.get("metricContract"), dict)
        else {}
    )
    surface = (
        contract.get("surface")
        or metrics_meta.get("metricSurface")
        or metrics_meta.get("metric_surface")
        or content_surface
        or _post_surface(row, meta)
    )
    normalized_surface = normalize_content_surface(str(surface)) if surface else "reel"
    metric_names = (
        contract.get("metricNames")
        or contract.get("metric_names")
        or metrics_meta.get("metricNames")
        or metrics_meta.get("metric_names")
        or []
    )
    if not isinstance(metric_names, list):
        metric_names = [str(metric_names)]
    normalized_names = [str(item) for item in metric_names if str(item or "").strip()]
    return {
        "version": contract.get("version")
        or metrics_meta.get("metricContractVersion")
        or metrics_meta.get("metric_contract_version")
        or METRIC_CONTRACT_VERSION,
        "surface": normalized_surface,
        "fallbackUsed": bool(
            contract.get("fallbackUsed")
            or contract.get("fallback_used")
            or metrics_meta.get("metricFallbackUsed")
            or metrics_meta.get("metric_fallback_used")
        ),
        "metricNames": normalized_names
        or _default_metric_names_for_surface(normalized_surface),
    }


def _default_metric_names_for_surface(surface: str) -> list[str]:
    if surface == "story":
        return [
            "views",
            "reach",
            "replies",
            "navigation",
            "follows",
            "shares",
            "total_interactions",
        ]
    if surface == "reel":
        return [
            "views",
            "reach",
            "likes",
            "comments",
            "shares",
            "saved",
            "ig_reels_avg_watch_time",
            "reels_skip_rate",
            "ig_reels_video_view_total_time",
        ]
    return ["views", "reach", "likes", "comments", "shares", "saved"]


def _nested_dict(value: Any, key: str) -> dict[str, Any] | None:
    if isinstance(value, dict) and isinstance(value.get(key), dict):
        return value[key]
    return None


def _int_metric(row: dict[str, Any], meta: dict[str, Any], *keys: str) -> int | None:
    value = _metric_value(row, meta, *keys)
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_metric(
    row: dict[str, Any], meta: dict[str, Any], *keys: str
) -> float | None:
    value = _metric_value(row, meta, *keys)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_value(row: dict[str, Any], meta: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) is not None:
            return row.get(key)
    for key in keys:
        if meta.get(key) is not None:
            return meta.get(key)
    return None


def _text_hash(value: str) -> str:
    normalized = " ".join((value or "").strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _stable_export_key(prefix: str, *parts: Any) -> str:
    joined = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}_{hashlib.sha256(joined.encode('utf-8')).hexdigest()[:20]}"


def _draft_key(draft: dict[str, Any]) -> tuple[str, str]:
    return (
        draft.get("renderedAssetId") or "",
        draft.get("accountId") or draft.get("instagramAccountId") or "unassigned",
    )


def _account_key(draft: dict[str, Any]) -> str:
    return draft.get("instagramAccountId") or draft.get("accountId") or "unassigned"


def _batch_guardrail_warnings(
    drafts: list[dict[str, Any]],
) -> dict[tuple[str, str], list[str]]:
    return {
        key: list(findings.get("warnings") or [])
        for key, findings in _batch_guardrail_findings(drafts).items()
    }


def _batch_guardrail_findings(
    drafts: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, list[str]]]:
    account_counts: dict[str, int] = {}
    account_render_counts: dict[tuple[str, str], int] = {}
    account_caption_counts: dict[tuple[str, str], int] = {}
    account_source_counts: dict[tuple[str, str], int] = {}
    for draft in drafts:
        account = _account_key(draft)
        account_counts[account] = account_counts.get(account, 0) + 1
        render_key = (account, draft.get("renderedAssetId") or "")
        account_render_counts[render_key] = account_render_counts.get(render_key, 0) + 1
        if draft.get("captionHash"):
            key = (account, draft["captionHash"])
            account_caption_counts[key] = account_caption_counts.get(key, 0) + 1
        source_key = (account, draft["sourceAssetId"])
        account_source_counts[source_key] = account_source_counts.get(source_key, 0) + 1

    findings: dict[tuple[str, str], dict[str, list[str]]] = {}
    for draft in drafts:
        account = _account_key(draft)
        draft_findings = findings.setdefault(
            _draft_key(draft), {"warnings": [], "blocking": []}
        )
        draft_warnings = draft_findings["warnings"]
        draft_blocking = draft_findings["blocking"]
        if account_counts.get(account, 0) > 2:
            draft_warnings.append("account_batch_volume_review")
        if (
            account_render_counts.get((account, draft.get("renderedAssetId") or ""), 0)
            > 1
        ):
            draft_blocking.append("same_rendered_asset_in_account_batch")
        if (
            draft.get("captionHash")
            and account_caption_counts.get((account, draft["captionHash"]), 0) > 1
        ):
            draft_warnings.append("same_caption_in_batch")
        if account_source_counts.get((account, draft["sourceAssetId"]), 0) > 2:
            draft_warnings.append("source_family_batch_volume_review")
    return findings


def _operator_score(
    *,
    state: str,
    warnings: list[str],
    blocking: list[str],
    upload_ready: Any,
    asset_usage: dict[str, Any],
    performance_score: int | None = None,
) -> int:
    score = 100
    if state == "blocked":
        score -= 70
    elif state == "warning":
        score -= 10
    if upload_ready is False:
        score -= 20
    score -= min(30, len(set(warnings)) * 5)
    score -= min(40, len(set(blocking)) * 10)
    if asset_usage.get("published", 0) > 0:
        score -= 60
    elif asset_usage.get("draft", 0) > 0 or asset_usage.get("scheduled", 0) > 0:
        score -= 10
    if performance_score is not None:
        score += int(round((performance_score - 50) * 0.3))
    return max(0, min(100, score))


def _empty_usage() -> dict[str, Any]:
    return {
        "total": 0,
        "draft": 0,
        "scheduled": 0,
        "published": 0,
        "other": 0,
        "surfaces": {},
        "posts": [],
    }


def _add_usage(usage: dict[str, Any], *, row: dict[str, Any], status: str) -> None:
    usage["total"] += 1
    if status in {"draft", "scheduled", "published"}:
        usage[status] += 1
    else:
        usage["other"] += 1
    meta = (row.get("metadata") or {}).get("campaign_factory") or {}
    surface = _post_surface(row, meta if isinstance(meta, dict) else {})
    surface_counts = usage.setdefault("surfaces", {}).setdefault(
        surface, {"total": 0, "draft": 0, "scheduled": 0, "published": 0, "other": 0}
    )
    surface_counts["total"] += 1
    if status in {"draft", "scheduled", "published"}:
        surface_counts[status] += 1
    else:
        surface_counts["other"] += 1
    usage["posts"].append(
        {
            "id": row.get("id"),
            "status": status,
            "platform": row.get("platform"),
            "surface": surface,
            "mediaType": row.get("media_type"),
            "igMediaType": row.get("ig_media_type"),
            "accountId": row.get("account_id"),
            "instagramAccountId": row.get("instagram_account_id"),
            "createdAt": row.get("created_at"),
            "scheduledFor": row.get("scheduled_for"),
            "previewScheduleOnly": bool(meta.get("preview_schedule_only"))
            if isinstance(meta, dict)
            else False,
        }
    )


def _usage_row_matches_campaign(
    *,
    meta: dict[str, Any],
    rendered_id: str | None,
    source_id: str | None,
    campaign_id: str | None,
    content_hash: str | None,
    source_hash: str | None,
    caption_hash: str | None,
    draft_by_rendered: dict[str, dict[str, Any]],
    source_ids: set[str],
    campaign_ids: set[str],
    content_hashes: set[str],
    source_hashes: set[str],
    caption_hashes: set[str],
) -> bool:
    return bool(
        rendered_id in draft_by_rendered
        or source_id in source_ids
        or campaign_id in campaign_ids
        or content_hash in content_hashes
        or source_hash in source_hashes
        or caption_hash in caption_hashes
        or meta.get("campaign_id") in campaign_ids
    )


def _post_surface(row: dict[str, Any], meta: dict[str, Any]) -> str:
    for key in ("distribution_surface", "content_surface", "surface"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    if meta.get("trial_reel") or meta.get("is_trial_reel"):
        return "trial_reel"
    media_type = str(row.get("media_type") or "").lower()
    ig_media_type = str(row.get("ig_media_type") or "").upper()
    if ig_media_type in {"STORY", "STORIES"} or media_type in {"story", "stories"}:
        return "story"
    if ig_media_type == "REELS" or media_type == "reel":
        return "reel"
    if media_type in {"carousel", "slideshow"}:
        return media_type
    return str(row.get("platform") or "unknown").lower()


def _local_account_exists(factory: CampaignFactory, account_id: str | None) -> bool:
    if not account_id:
        return False
    return bool(
        factory.conn.execute(
            "SELECT 1 FROM accounts WHERE id = ? LIMIT 1", (account_id,)
        ).fetchone()
    )


def _assignment_exists(
    factory: CampaignFactory,
    rendered_asset_id: str,
    account_id: str | None,
    instagram_account_id: str | None,
) -> bool:
    row = factory.conn.execute(
        """
        SELECT 1
        FROM asset_account_assignments
        WHERE rendered_asset_id = ?
          AND COALESCE(account_id, '') = COALESCE(?, '')
          AND COALESCE(instagram_account_id, '') = COALESCE(?, '')
        LIMIT 1
        """,
        (rendered_asset_id, account_id, instagram_account_id),
    ).fetchone()
    return bool(row)


UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _resolve_instagram_account_id(
    factory: CampaignFactory, account_id: str
) -> str | None:
    if not account_id or account_id == "unassigned":
        return None
    row = factory.conn.execute(
        "SELECT * FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if row and row["external_id"]:
        return row["external_id"]
    if UUID_RE.match(account_id):
        return account_id
    return None


def _sync_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return slug or "default"


def _sync_reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


class SupabaseRestClient:
    def __init__(self, url: str, service_role_key: str):
        self.url = url
        self.service_role_key = service_role_key

    def headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
        }
        if extra:
            headers.update(extra)
        return headers

    def upload_storage_object(
        self,
        bucket: str,
        storage_path: str,
        file_path: Path,
        content_type: str,
        *,
        upsert: bool = False,
    ) -> None:
        endpoint = f"{self.url}/storage/v1/object/{quote(bucket)}/{quote(storage_path)}"
        data = file_path.read_bytes()
        request = Request(
            endpoint,
            data=data,
            method="POST",
            headers=self.headers(
                {
                    "Content-Type": content_type,
                    "x-upsert": "true" if upsert else "false",
                }
            ),
        )
        self._open_json_or_empty(request)

    def get_storage_bucket(self, bucket: str) -> dict[str, Any]:
        endpoint = f"{self.url}/storage/v1/bucket/{quote(bucket)}"
        request = Request(endpoint, method="GET", headers=self.headers())
        result = self._open_json_or_empty(request)
        return result if isinstance(result, dict) else {}

    def insert_with_fallback(
        self, table: str, row: dict[str, Any], fallback_remove: list[str]
    ) -> dict[str, Any]:
        current = dict(row)
        while True:
            try:
                inserted = self.insert(table, current)
                return (
                    inserted[0] if isinstance(inserted, list) and inserted else inserted
                )
            except RuntimeError as exc:
                message = str(exc)
                removed = False
                for key in list(fallback_remove):
                    if key in current and (
                        key in message
                        or "Could not find" in message
                        or "schema cache" in message
                    ):
                        current.pop(key, None)
                        fallback_remove.remove(key)
                        removed = True
                        break
                if not removed:
                    raise

    def select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        query = "&".join(
            f"{quote(str(key), safe='')}={quote(str(value), safe='(),.*:>')}"
            for key, value in params.items()
        )
        endpoint = f"{self.url}/rest/v1/{quote(table)}?{query}"
        request = Request(endpoint, method="GET", headers=self.headers())
        result = self._open_json_or_empty(request)
        return result if isinstance(result, list) else []

    def insert(self, table: str, row: dict[str, Any]) -> Any:
        endpoint = f"{self.url}/rest/v1/{quote(table)}"
        request = Request(
            endpoint,
            data=json.dumps(row).encode("utf-8"),
            method="POST",
            headers=self.headers(
                {
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                }
            ),
        )
        # Plain POST inserts are not idempotent: a retry after an ambiguous
        # failure (timeout, or a 5xx sent after the row committed) can create
        # duplicate rows (audit A6). Only retry statuses that guarantee the
        # request was never processed; never retry network-level ambiguity.
        return self._open_json_or_empty(request, retry_ambiguous=False)

    def upsert(self, table: str, row: dict[str, Any], *, on_conflict: str) -> Any:
        endpoint = f"{self.url}/rest/v1/{quote(table)}?on_conflict={quote(on_conflict, safe=',')}"
        request = Request(
            endpoint,
            data=json.dumps(row).encode("utf-8"),
            method="POST",
            headers=self.headers(
                {
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates,return=representation",
                }
            ),
        )
        return self._open_json_or_empty(request)

    def update(
        self, table: str, values: dict[str, Any], filters: dict[str, str]
    ) -> Any:
        query = "&".join(
            f"{quote(str(key), safe='')}={quote(str(value), safe='(),.*:>')}"
            for key, value in filters.items()
        )
        endpoint = f"{self.url}/rest/v1/{quote(table)}?{query}"
        request = Request(
            endpoint,
            data=json.dumps(values).encode("utf-8"),
            method="PATCH",
            headers=self.headers(
                {
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                }
            ),
        )
        return self._open_json_or_empty(request)

    def delete(self, table: str, filters: dict[str, str]) -> Any:
        query = "&".join(
            f"{quote(str(key), safe='')}={quote(str(value), safe='(),.*:>')}"
            for key, value in filters.items()
        )
        endpoint = f"{self.url}/rest/v1/{quote(table)}?{query}"
        request = Request(
            endpoint,
            method="DELETE",
            headers=self.headers({"Prefer": "return=representation"}),
        )
        return self._open_json_or_empty(request)

    def _open_json_or_empty(
        self, request: Request, *, retry_ambiguous: bool = True
    ) -> Any:
        # Statuses where the server definitely did not process the request,
        # so retrying is always safe (even for non-idempotent POST inserts).
        safe_statuses = {408, 425, 429}
        # Statuses where the request *may* have been processed before the
        # error/timeout surfaced; only retried for idempotent requests.
        ambiguous_statuses = {409, 500, 502, 503, 504}
        transient_statuses = (
            safe_statuses | ambiguous_statuses if retry_ambiguous else safe_statuses
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urlopen(request, timeout=60) as response:
                    raw = response.read()
                break
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = RuntimeError(f"Supabase request failed {exc.code}: {body}")
                if exc.code not in transient_statuses or attempt == 2:
                    raise last_error from exc
            except URLError as exc:
                # Network-level failure (incl. timeouts): ambiguous whether
                # the request reached the server. Never retried for
                # non-idempotent requests.
                last_error = RuntimeError(f"Supabase request failed: {exc}")
                if not retry_ambiguous or attempt == 2:
                    raise last_error from exc
            time.sleep(0.25 * (2**attempt))
        else:  # pragma: no cover - loop either breaks or raises
            raise last_error or RuntimeError("Supabase request failed")
        if not raw:
            return {}
        text = raw.decode("utf-8")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}
