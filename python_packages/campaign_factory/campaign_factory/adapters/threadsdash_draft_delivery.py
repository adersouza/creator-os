from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from creator_os_core.runtime_guards import require_global_write_allowed

from ..contracts import (
    validate_threadsdash_draft_payload_strict,
)
from ..core import (
    CampaignFactory,
    _normalize_schedule_mode,
    new_id,
    normalize_content_surface,
    utc_now,
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

from . import threadsdash_client as _threadsdash_client
from . import threadsdash_draft_payload as _draft_payload
from .threadsdash_client import (
    _threadsdash_ingest_signature,
    _validate_threadsdash_ingest_url,
)
from .threadsdash_draft_payload import (
    _draft_media_types,
    _draft_metadata,
    _normalize_publish_mode,
    _stable_export_key,
)
from .threadsdash_draft_readiness import (
    _batch_guardrail_findings,
    _draft_notify_audio_deferred,
    evaluate_export_readiness,
)


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
        review_only = (
            str(meta.get("handoffMode") or "").strip().lower() == "review_only"
        )
        allowed_states = (
            {"review_ready"} if review_only else {"publishable_candidate", "exportable"}
        )
        if asset_state not in allowed_states:
            blockers.append(
                f"{rendered_asset_id}:asset_state:{asset_state or 'missing'}"
            )
        failures = meta.get("publishability_failure_reasons") or []
        if failures and not review_only and not _draft_notify_audio_deferred(draft):
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
        overlay_semantic_qc = meta.get("overlay_semantic_qc")
        if (
            isinstance(overlay_semantic_qc, dict)
            and overlay_semantic_qc.get("passed") is False
        ):
            reasons = overlay_semantic_qc.get("failure_reasons") or [
                "overlay_semantic_qc_failed"
            ]
            blockers.extend(
                f"{rendered_asset_id}:overlay_semantic_qc:{reason}"
                for reason in reasons
            )
        if require_remote_media_urls:
            blockers.extend(
                _remote_media_url_blockers(draft, rendered_asset_id=rendered_asset_id)
            )
    return sorted(set(blockers))


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
    surface: str | None = "regular_reel",
    schedule_mode: str = "draft",
    threadsdash_ingest_url: str | None = None,
    threadsdash_ingest_secret: str | None = None,
    enable_variation: bool = False,
    variation_preset: str = "ig_subtle",
    publish_mode: str | None = None,
    review_only: bool = False,
) -> dict[str, Any]:
    if max_drafts is not None and max_drafts < 0:
        raise ValueError("max_drafts must be non-negative")
    if review_only and _normalize_schedule_mode(schedule_mode) != "draft":
        raise ValueError("review-only handoff requires schedule_mode='draft'")
    if not dry_run:
        require_global_write_allowed("ThreadsDashboard draft export")
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    normalized_schedule_mode = _normalize_schedule_mode(schedule_mode)
    normalized_publish_mode = _normalize_publish_mode(publish_mode)
    if not dry_run and normalized_schedule_mode != "draft":
        raise ValueError(
            "Campaign Factory exports are draft-only; scheduling and publishing belong to ThreadsDashboard"
        )
    if dry_run and enable_variation:
        raise ValueError(
            "read-only draft preview cannot generate variation artifacts; "
            "run the variation preview separately"
        )
    pipeline_job: dict[str, Any] | None = None
    if not dry_run:
        pipeline_job = factory.domains.events.create_pipeline_job(
            "threadsdash_export",
            campaign["id"],
            {
                "campaign": campaign_slug,
                "userId": user_id,
                "dryRun": False,
                "hasSupabaseUrl": bool(supabase_url),
                "hasSupabaseServiceRoleKey": bool(supabase_service_role_key),
                "supabaseStorageBucket": supabase_storage_bucket,
                "allowWarnings": allow_warnings,
                "contentPillar": content_pillar,
                "ctaType": cta_type,
                "language": language,
                "maxDrafts": max_drafts,
                "renderedAssetIds": rendered_asset_ids or [],
                "surface": surface,
                "scheduleMode": normalized_schedule_mode,
                "publishMode": normalized_publish_mode,
                "hasThreadsdashIngestUrl": bool(
                    threadsdash_ingest_url
                    or os.environ.get("THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL")
                    or os.environ.get("CAMPAIGN_FACTORY_DRAFT_INGEST_URL")
                ),
                "enableVariation": enable_variation,
                "variationPreset": variation_preset,
                "reviewOnly": review_only,
            },
        )
        factory.domains.events.start_pipeline_job(pipeline_job["id"])
    model_slug = factory.domains.reel_execution.model_slug_for_campaign(campaign["id"])
    if dry_run:
        exports_dir = (
            factory.settings.campaigns_dir
            / model_slug
            / campaign["slug"]
            / "05_threadsdash_exports"
        )
    else:
        exports_dir = factory.domains.campaign_dirs(model_slug, campaign["slug"])[
            "exports"
        ]
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
        payload = _draft_payload.build_draft_payloads(
            factory,
            campaign_slug=campaign_slug,
            user_id=user_id,
            export_id=export_id,
            content_pillar=content_pillar,
            cta_type=cta_type,
            language=language,
            rendered_asset_ids=rendered_asset_ids,
            surface=surface,
            schedule_mode=normalized_schedule_mode,
            enable_variation=enable_variation,
            publish_mode=normalized_publish_mode,
            review_only=review_only,
        )
        payload = _freeze_exact_draft_batch(payload, max_drafts=max_drafts)
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
            surface=surface,
            schedule_mode=normalized_schedule_mode,
            publish_mode=normalized_publish_mode,
            review_only=review_only,
            record_evidence=not dry_run,
            draft_payload=payload,
        )
        if not dry_run and readiness.get("liveExportAllowed") is not True:
            readiness_blockers = [
                str(reason)
                for reason in readiness.get("blockingReasons") or []
                if str(reason).strip()
            ] or ["export_readiness_not_proven"]
            raise ValueError(
                "export blocked by readiness before external writes: "
                + ", ".join(readiness_blockers)
            )
        if not dry_run and readiness.get("warnings") and not allow_warnings:
            warning_codes = [
                str(item.get("code") or item.get("type") or item)
                if isinstance(item, dict)
                else str(item)
                for item in readiness.get("warnings") or []
            ]
            raise ValueError(
                "export has readiness warnings; review them or explicitly pass "
                "allow_warnings: " + ", ".join(warning_codes)
            )
        uses_dashboard_ingest = not dry_run and normalized_schedule_mode == "draft"
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
        if not dry_run and normalized_schedule_mode != "draft":
            raise ValueError(
                "Campaign Factory exports are draft-only; scheduling and publishing belong to ThreadsDashboard"
            )
        validate_threadsdash_draft_payload_strict(payload)
        out_path = exports_dir / f"supabase_drafts_{campaign['slug']}_{export_id}.json"
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
            "path": None if dry_run else str(out_path),
            "wouldWritePath": str(out_path) if dry_run else None,
            "pipelineJobId": None if pipeline_job is None else pipeline_job["id"],
        }
        if dry_run:
            return result

        assert pipeline_job is not None
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
        factory.domains.events.record_event(
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
        factory.domains.events.finish_pipeline_job(
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
        if dry_run:
            raise
        assert pipeline_job is not None
        failed_path = (
            exports_dir
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
        factory.domains.events.record_event(
            "threadsdash_export_created",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"ThreadsDash export failed: {exc}",
            metadata={"error": str(exc), "dryRun": dry_run},
        )
        factory.domains.events.fail_pipeline_job(pipeline_job["id"], str(exc))
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
    client = _threadsdash_client.SupabaseRestClient(
        supabase_url.rstrip("/"), service_role_key
    )
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
                    expected_sha256=str(draft.get("contentHash") or ""),
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
            with _threadsdash_client._open_threadsdash_ingest_request(
                request, timeout=30
            ) as response:
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
    client: _threadsdash_client.SupabaseRestClient,
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
    client = _threadsdash_client.SupabaseRestClient(
        supabase_url.rstrip("/"), supabase_service_role_key
    )
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
    client: _threadsdash_client.SupabaseRestClient,
    *,
    bucket: str,
    user_id: str,
    local_path: Path,
    tags: list[str],
    media_key: str | None = None,
    expected_sha256: str,
) -> dict[str, Any]:
    if not local_path.exists():
        raise FileNotFoundError(local_path)
    expected_sha256 = expected_sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("media upload requires a canonical SHA-256 fingerprint")
    actual_sha256 = _sha256_file(local_path)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            "media changed after draft approval: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )
    content_type = mimetypes.guess_type(local_path.name)[0] or "video/mp4"
    file_type = "image" if content_type.startswith("image/") else "video"
    safe_name = "".join(
        ch if ch.isalnum() or ch in "._-" else "-" for ch in local_path.name
    )[:120]
    stable_key = media_key or _stable_export_key(
        "media", user_id, local_path.name, local_path.stat().st_size
    )
    storage_path = f"campaign_factory/{user_id}/{stable_key}-{safe_name}"

    def select_existing() -> list[dict[str, Any]]:
        return client.select(
            "media",
            {
                "select": "id,file_name,file_url,storage_url,storage_path,url,tags",
                "storage_path": f"eq.{storage_path}",
                "limit": "1",
            },
        )

    # A failed read is not evidence that the row is absent. Fail before the
    # storage upload so a degraded database cannot turn a read outage into
    # additional object and row writes.
    existing_rows = select_existing()
    if existing_rows:
        remote_bytes = client.download_storage_object(bucket, storage_path)
        remote_sha256 = hashlib.sha256(remote_bytes).hexdigest()
        if remote_sha256 != expected_sha256:
            raise ValueError(
                "existing remote media fingerprint mismatch: "
                f"expected {expected_sha256}, got {remote_sha256}"
            )
        confirmed_rows = select_existing()
        if not confirmed_rows:
            raise RuntimeError(
                "verified remote media row disappeared before reuse; refusing stale media id"
            )
        existing_rows = confirmed_rows
    else:
        with tempfile.TemporaryDirectory(
            prefix="creator-os-approved-media-"
        ) as temp_dir:
            approved_copy = Path(temp_dir) / local_path.name
            shutil.copyfile(local_path, approved_copy)
            copied_sha256 = _sha256_file(approved_copy)
            if copied_sha256 != expected_sha256:
                raise ValueError(
                    "media changed while creating immutable upload copy: "
                    f"expected {expected_sha256}, got {copied_sha256}"
                )
            try:
                client.upload_storage_object(
                    bucket, storage_path, approved_copy, content_type, upsert=False
                )
            except TypeError:
                client.upload_storage_object(
                    bucket, storage_path, approved_copy, content_type
                )
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
    reused = bool(existing_rows)
    if existing_rows:
        row = existing_rows[0]
    else:
        try:
            row = client.insert_with_fallback(
                "media", base_row, fallback_remove=["url"]
            )
        except RuntimeError as insert_error:
            # Production's storage_path uniqueness is enforced by a partial index,
            # which PostgREST cannot target with on_conflict=storage_path. Recover
            # a concurrent or ambiguously committed plain insert with one exact
            # read instead of issuing a second write.
            try:
                recovered_rows = select_existing()
            except RuntimeError as recovery_error:
                raise RuntimeError(
                    "media insert failed and its exact recovery read also failed"
                ) from recovery_error
            if not recovered_rows:
                raise insert_error
            row = recovered_rows[0]
            reused = True
    result = {
        "id": row.get("id"),
        "publicUrl": public_url,
        "storagePath": storage_path,
        "fileName": local_path.name,
        "sha256": expected_sha256,
    }
    if reused:
        result["reused"] = True
    return result


def _batch_guardrail_warnings(
    drafts: list[dict[str, Any]],
) -> dict[tuple[str, str], list[str]]:
    return {
        key: list(findings.get("warnings") or [])
        for key, findings in _batch_guardrail_findings(drafts).items()
    }


def _freeze_exact_draft_batch(
    payload: dict[str, Any], *, max_drafts: int | None
) -> dict[str, Any]:
    """Freeze one deterministic draft-row batch before any readiness or write.

    A rendered asset may expand to multiple account destinations, so an asset-id
    scope alone cannot represent ``max_drafts`` exactly. The stable draft keys
    are the integrity boundary shared by readiness, usage, upload, and ingest.
    """
    if max_drafts is None:
        return payload
    drafts = list(payload.get("drafts") or [])
    selected = drafts[:max_drafts]
    draft_keys = [
        str(draft.get("campaignFactoryDraftKey") or "").strip()
        for draft in selected
        if isinstance(draft, dict)
    ]
    if len(draft_keys) != len(selected) or any(not key for key in draft_keys):
        raise ValueError("exact draft batch contains a missing stable draft key")
    if len(set(draft_keys)) != len(draft_keys):
        raise ValueError("exact draft batch contains duplicate stable draft keys")
    selected_asset_ids = {
        str(draft.get("renderedAssetId") or "")
        for draft in selected
        if isinstance(draft, dict)
    }
    manifest = dict(payload.get("manifest") or {})
    manifest["assets"] = [
        asset
        for asset in manifest.get("assets") or []
        if str(asset.get("renderedAssetId") or "") in selected_asset_ids
    ]
    return {
        **payload,
        "manifest": manifest,
        "drafts": selected,
        "batchSelection": {
            "mode": "payload_order_prefix_frozen_by_stable_draft_key",
            "requestedMaxDrafts": max_drafts,
            "selectedDraftCount": len(selected),
            "draftKeys": draft_keys,
        },
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
