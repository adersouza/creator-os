from __future__ import annotations

import hashlib
import json
import os
from typing import Any
from urllib.parse import urlparse

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
from ..creative_approval import (
    CreativeApprovalError,
    asset_requires_creative_approval,
    validate_approval_for_draft,
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
THREADSDASH_INGEST_PATH = "/api/campaign-factory/drafts/ingest"
DEFAULT_THREADSDASH_INGEST_HOSTS = frozenset({"juno33.com", "www.juno33.com"})
POST_METRIC_HISTORY_POST_ID_BATCH_SIZE = 5

from . import threadsdash_draft_payload as _draft_payload
from .threadsdash_draft_payload import (
    DEFAULT_DRAFT_PAYLOAD_SCHEMA,
    _draft_media_types,
    _draft_metadata,
    _normalize_publish_mode,
)
from .threadsdash_draft_readiness import (
    _batch_guardrail_findings,
    _draft_notify_audio_deferred,
    evaluate_export_readiness,
)
from .threadsdash_export_saga import prepare_export, set_export_state
from .threadsdash_handoff_evidence import (
    attach_handoff_evidence,
    handoff_idempotency_key,
)
from .threadsdash_handshake import (
    HANDSHAKE_SCHEMA_V1,
    HANDSHAKE_SCHEMA_V2,
    configured_handshake_url,
    run_threadsdash_handshake,
)
from .threadsdash_owner_api import (
    reconcile_draft_handoff,
    submit_draft_handoff,
    upload_delivery_media,
)


def _bind_export_governance(
    factory: CampaignFactory,
    payload: dict[str, Any],
    *,
    campaign_id: str,
    creator: str,
    expected_fingerprints: dict[str, str] | None = None,
) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for index, draft in enumerate(payload.get("drafts") or []):
        metadata_root = draft.setdefault("metadata", {})
        if not isinstance(metadata_root, dict):
            raise PermissionError("export_metadata_invalid")
        metadata = metadata_root.setdefault("campaign_factory", {})
        if not isinstance(metadata, dict):
            raise PermissionError("export_campaign_metadata_invalid")
        source_asset_id = str(
            draft.get("sourceAssetId") or metadata.get("source_asset_id") or ""
        )
        if not source_asset_id:
            rendered_asset_id = str(draft.get("renderedAssetId") or "").strip()
            row = factory.conn.execute(
                """
                SELECT source_asset_id
                FROM rendered_assets
                WHERE id = ? AND campaign_id = ?
                """,
                (rendered_asset_id, campaign_id),
            ).fetchone()
            source_asset_id = str(row["source_asset_id"] if row else "")
        if not source_asset_id:
            raise PermissionError("export_source_asset_identity_missing")
        account_value = str(
            draft.get("accountId") or draft.get("instagramAccountId") or ""
        ).strip()
        account_id = (
            None if account_value.casefold() in {"", "unassigned"} else account_value
        )
        context = factory.domains.creator_governance.resolve_operation(
            creator=creator,
            campaign=campaign_id,
            operation="export",
            provider="internal",
            source_asset_id=source_asset_id,
            account_id=account_id,
        )
        draft_key = str(
            draft.get("campaignFactoryDraftKey") or draft.get("id") or f"draft:{index}"
        )
        fingerprint = str(context["governanceFingerprint"])
        if (
            expected_fingerprints is not None
            and expected_fingerprints.get(draft_key) != fingerprint
        ):
            raise PermissionError("export_governance_stale")
        fingerprints[draft_key] = fingerprint
        if expected_fingerprints is None:
            metadata["creator_governance"] = context
    return fingerprints


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
        required: tuple[str, ...]
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
    supabase_storage_bucket: str = "media",
    allow_warnings: bool = False,
    warning_override_reason: str | None = None,
    warning_override_by: str | None = None,
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
    draft_payload_schema: str = DEFAULT_DRAFT_PAYLOAD_SCHEMA,
) -> dict[str, Any]:
    if max_drafts is not None and max_drafts < 0:
        raise ValueError("max_drafts must be non-negative")
    normalized_draft_payload_schema = _draft_payload._normalize_draft_payload_schema(
        draft_payload_schema
    )
    if review_only and _normalize_schedule_mode(schedule_mode) != "draft":
        raise ValueError("review-only handoff requires schedule_mode='draft'")
    if not dry_run:
        require_global_write_allowed("ThreadsDashboard draft export")
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    model_slug = factory.domains.reel_execution.model_slug_for_campaign(campaign["id"])
    governance_context = None
    if not dry_run:
        governance_context = factory.domains.creator_governance.resolve_operation(
            creator=str(model_slug),
            campaign=str(campaign["id"]),
            operation="export",
            provider="internal",
        )
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
                "supabaseStorageBucket": supabase_storage_bucket,
                "allowWarnings": allow_warnings,
                "warningOverrideReason": warning_override_reason,
                "warningOverrideBy": warning_override_by or user_id,
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
                "draftPayloadSchema": normalized_draft_payload_schema,
                "creatorGovernanceFingerprint": governance_context[
                    "governanceFingerprint"
                ],
            },
        )
        factory.domains.events.start_pipeline_job(pipeline_job["id"])
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
    submission_started = False
    acceptance_recorded = False
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
            draft_payload_schema=normalized_draft_payload_schema,
        )
        governance_fingerprints: dict[str, str] = {}
        if not dry_run:
            governance_fingerprints = _bind_export_governance(
                factory,
                payload,
                campaign_id=str(campaign["id"]),
                creator=str(model_slug),
            )
        payload = _freeze_exact_draft_batch(payload, max_drafts=max_drafts)
        uses_dashboard_ingest = not dry_run and normalized_schedule_mode == "draft"
        readiness = evaluate_export_readiness(
            factory,
            campaign_slug=campaign_slug,
            user_id=user_id,
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
            owner_api_authoritative=uses_dashboard_ingest,
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
        operator_overridable_warnings = _operator_overridable_warnings(readiness)
        if not dry_run and operator_overridable_warnings and not allow_warnings:
            unreviewed_warning_codes = [
                str(item.get("code") or item.get("type") or item)
                if isinstance(item, dict)
                else str(item)
                for item in operator_overridable_warnings
            ]
            raise ValueError(
                "export has readiness warnings; review them or explicitly pass "
                "allow_warnings: " + ", ".join(unreviewed_warning_codes)
            )
        warning_codes: list[str] = []
        warning_override_reason_normalized = ""
        if not dry_run and operator_overridable_warnings and allow_warnings:
            warning_override_reason_normalized = str(
                warning_override_reason or ""
            ).strip()
            if not warning_override_reason_normalized:
                raise ValueError(
                    "warning override requires a non-empty warning_override_reason"
                )
            warning_codes = [
                str(item.get("code") or item.get("type") or item)
                if isinstance(item, dict)
                else str(item)
                for item in operator_overridable_warnings
            ]
        warning_override: dict[str, Any] | None = None
        # Validate the exact local payload before any handshake, storage upload,
        # nonce claim, or ingest write. The second validation below proves that
        # remote-media hydration did not invalidate the contract.
        validate_threadsdash_draft_payload_strict(payload)
        contract_negotiation: dict[str, Any] | None = None
        if uses_dashboard_ingest:
            _validate_exact_creative_approvals(
                factory, payload, campaign_slug=campaign_slug
            )
            contract_negotiation = _negotiate_threadsdash_draft_payload(
                payload_schema=str(payload.get("schema") or ""),
                ingest_url=threadsdash_ingest_url,
                ingest_secret=threadsdash_ingest_secret,
            )
        out_path = exports_dir / f"supabase_drafts_{campaign['slug']}_{export_id}.json"
        if uses_dashboard_ingest:
            out_path.write_text(
                json.dumps(
                    {
                        "schema": "campaign_factory.supabase_export.v1",
                        "status": "prepared",
                        "exportId": export_id,
                        "payload": payload,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            prepare_export(
                factory.conn,
                export_id=export_id,
                campaign_id=campaign["id"],
                user_id=user_id,
                manifest_path=str(out_path),
                payload=payload,
            )
        dashboard_ingest_media: list[dict[str, Any]] = []
        if uses_dashboard_ingest:
            _validate_exact_creative_approvals(
                factory, payload, campaign_slug=campaign_slug
            )
            _bind_export_governance(
                factory,
                payload,
                campaign_id=str(campaign["id"]),
                creator=str(model_slug),
                expected_fingerprints=governance_fingerprints,
            )
            dashboard_ingest_media = _upload_media_for_dashboard_ingest(
                factory,
                payload,
                ingest_url=threadsdash_ingest_url,
                ingest_secret=threadsdash_ingest_secret,
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
        if warning_codes:
            warning_override = {
                "schema": "campaign_factory.export_warning_override.v1",
                "warningCodes": sorted(set(warning_codes)),
                "operatorIdentity": str(warning_override_by or user_id),
                "overrideReason": warning_override_reason_normalized,
                "payloadFingerprint": hashlib.sha256(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "recordedAt": utc_now(),
            }
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
            "warningOverride": warning_override,
            "supabase": {"attempted": False, "media": [], "posts": []},
            "dashboardIngest": {
                "attempted": False,
                "dryRun": dry_run,
                "postIds": [],
                "media": dashboard_ingest_media,
            },
            "contractNegotiation": contract_negotiation,
            "path": None if dry_run else str(out_path),
            "wouldWritePath": str(out_path) if dry_run else None,
            "pipelineJobId": None if pipeline_job is None else pipeline_job["id"],
        }
        if dry_run:
            return result

        assert pipeline_job is not None
        _validate_exact_creative_approvals(
            factory, payload, campaign_slug=campaign_slug
        )
        _bind_export_governance(
            factory,
            payload,
            campaign_id=str(campaign["id"]),
            creator=str(model_slug),
            expected_fingerprints=governance_fingerprints,
        )
        set_export_state(factory.conn, export_id, "submitted")
        submission_started = True
        result["dashboardIngest"] = _post_threadsdash_draft_ingest(
            payload,
            ingest_url=threadsdash_ingest_url,
            ingest_secret=threadsdash_ingest_secret,
        )
        reconciled_post_ids = _reconcile_dashboard_ingest_post_ids(
            payload=payload,
            ingest_result=result["dashboardIngest"],
            user_id=user_id,
            ingest_url=threadsdash_ingest_url,
            ingest_secret=threadsdash_ingest_secret,
        )
        if not reconciled_post_ids:
            raise ValueError("ThreadsDashboard acknowledgment contains no post IDs")
        set_export_state(
            factory.conn,
            export_id,
            "accepted",
            acknowledgment=result["dashboardIngest"]["acknowledgment"],
        )
        acceptance_recorded = True
        _commit_payload_inventory_reservations(factory, payload)
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
                "warningOverride": warning_override,
                "scheduleMode": normalized_schedule_mode,
                "draftPayloadSchema": payload.get("schema"),
                "selectedDraftPayload": (contract_negotiation or {}).get(
                    "selectedDraftPayload"
                ),
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
                "draftPayloadSchema": payload.get("schema"),
                "selectedDraftPayload": (contract_negotiation or {}).get(
                    "selectedDraftPayload"
                ),
                "previewCleanup": result.get("previewCleanup") or {},
                "warningOverride": warning_override,
            },
        )
        return result
    except Exception as exc:
        if dry_run:
            raise
        acceptance_unknown = (
            submission_started
            and not acceptance_recorded
            and isinstance(exc, TimeoutError)
        )
        if "payload" in locals() and not acceptance_unknown and not acceptance_recorded:
            _release_payload_inventory_reservations(factory, payload)
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
            "draftPayloadSchema": normalized_draft_payload_schema,
            "error": str(exc),
            "status": (
                "accepted"
                if acceptance_recorded
                else ("acceptance_unknown" if acceptance_unknown else "rejected")
            ),
            "warningOverride": locals().get("warning_override"),
        }
        failed_path.parent.mkdir(parents=True, exist_ok=True)
        failed_path.write_text(
            json.dumps(failed_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        failed_export_id = str(locals().get("export_id", pipeline_job["id"]))
        export_row = factory.conn.execute(
            "SELECT id FROM threadsdash_exports WHERE id = ?", (failed_export_id,)
        ).fetchone()
        if export_row is not None:
            if acceptance_recorded:
                set_export_state(
                    factory.conn,
                    failed_export_id,
                    "accepted",
                    acknowledgment=result["dashboardIngest"]["acknowledgment"],
                    error=str(exc),
                )
            else:
                set_export_state(
                    factory.conn,
                    failed_export_id,
                    "acceptance_unknown" if acceptance_unknown else "rejected",
                    error=str(exc),
                )
        factory.domains.events.record_event(
            "threadsdash_export_created",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"ThreadsDash export failed: {exc}",
            metadata={
                "error": str(exc),
                "dryRun": dry_run,
                "exportStatus": failed_payload["status"],
                "reservationAction": (
                    "held_for_reconciliation"
                    if acceptance_unknown or acceptance_recorded
                    else "released"
                ),
            },
        )
        factory.domains.events.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


def _payload_inventory_reservation_ids(payload: dict[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            str(draft.get("inventoryReservationId"))
            for draft in payload.get("drafts") or []
            if isinstance(draft, dict) and draft.get("inventoryReservationId")
        )
    )


def _commit_payload_inventory_reservations(
    factory: CampaignFactory, payload: dict[str, Any]
) -> None:
    for reservation_id in _payload_inventory_reservation_ids(payload):
        factory.domains.inventory_reservations.commit_inventory_reservation(
            reservation_id
        )


def _release_payload_inventory_reservations(
    factory: CampaignFactory, payload: dict[str, Any]
) -> None:
    for reservation_id in _payload_inventory_reservation_ids(payload):
        factory.domains.inventory_reservations.release_inventory_reservation(
            reservation_id,
            status="released",
            pending_only=True,
        )


def _operator_overridable_warnings(readiness: dict[str, Any]) -> list[Any]:
    warnings = readiness.get("operatorOverridableWarnings")
    return list(warnings) if isinstance(warnings, list) else []


def _validate_exact_creative_approvals(
    factory: CampaignFactory,
    payload: dict[str, Any],
    *,
    campaign_slug: str,
) -> None:
    for draft in payload.get("drafts") or []:
        if not isinstance(draft, dict):
            raise ValueError("creative approval draft must be an object")
        rendered_asset_id = str(draft.get("renderedAssetId") or "")
        asset = factory.domains.publishability.rendered_asset(rendered_asset_id)
        if not asset_requires_creative_approval(asset):
            continue
        status = factory.domains.publishability.creative_approval_for_asset(
            rendered_asset_id
        )
        approval = status.get("approval")
        if not isinstance(approval, dict):
            raise ValueError(
                f"{rendered_asset_id}:"
                + str(status.get("blockingReason") or "creative_approval_missing")
            )
        try:
            validate_approval_for_draft(approval, draft, campaign_slug=campaign_slug)
        except CreativeApprovalError as exc:
            raise ValueError(f"{rendered_asset_id}:{exc}") from exc


def _negotiate_threadsdash_draft_payload(
    *,
    payload_schema: str,
    ingest_url: str | None,
    ingest_secret: str | None,
) -> dict[str, Any]:
    """Negotiate the exact draft contract before any product or media write."""
    resolved_ingest_url = (
        ingest_url
        or os.environ.get("THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL")
        or os.environ.get("CAMPAIGN_FACTORY_DRAFT_INGEST_URL")
    )
    secret = ingest_secret or os.environ.get("CAMPAIGN_FACTORY_INGEST_SECRET")
    if not resolved_ingest_url:
        raise ValueError(
            "threadsdash_ingest_url or THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL "
            "is required before live draft contract negotiation"
        )
    if not secret:
        raise ValueError(
            "threadsdash_ingest_secret or CAMPAIGN_FACTORY_INGEST_SECRET is "
            "required before live draft contract negotiation"
        )
    handshake_env = dict(os.environ)
    handshake_env["THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL"] = resolved_ingest_url
    handshake_url = configured_handshake_url(handshake_env)
    if not handshake_url:
        raise ValueError(
            "ThreadsDashboard handshake URL could not be derived from the ingest URL"
        )
    if payload_schema == _draft_payload.DRAFT_PAYLOAD_SCHEMA_V3:
        handshake_schema = HANDSHAKE_SCHEMA_V2
    elif payload_schema == _draft_payload.DRAFT_PAYLOAD_SCHEMA_V2:
        handshake_schema = HANDSHAKE_SCHEMA_V1
    else:
        raise ValueError(
            f"draft payload contract is not negotiable: {payload_schema or 'missing'}"
        )
    result = run_threadsdash_handshake(
        url=handshake_url,
        secret=secret,
        env=handshake_env,
        handshake_schema=handshake_schema,
    )
    selected = str(result.get("selectedDraftPayload") or "")
    if selected != payload_schema:
        raise ValueError(
            "ThreadsDashboard selected a different draft payload contract: "
            f"requested {payload_schema}, selected {selected or 'missing'}"
        )
    return result


def _upload_media_for_dashboard_ingest(
    factory: CampaignFactory,
    payload: dict[str, Any],
    *,
    ingest_url: str | None,
    ingest_secret: str | None,
    bucket: str,
) -> list[dict[str, Any]]:
    del factory
    media_results = upload_delivery_media(
        payload,
        ingest_url=ingest_url,
        ingest_secret=ingest_secret,
        bucket=bucket,
    )
    by_key = {
        str(item.get("sha256")): item
        for item in media_results
        if isinstance(item, dict)
    }
    for draft in payload.get("drafts") or []:
        if not isinstance(draft, dict):
            continue
        media_ref = by_key.get(str(draft.get("contentHash") or ""))
        if media_ref is None:
            continue
        _hydrate_surface_media_items_for_uploaded_media(draft, media_ref)
        draft["metadata"] = _draft_metadata(draft)
        attach_handoff_evidence(
            draft,
            schema=str(payload.get("schema") or ""),
            campaign_id=str(draft.get("campaignId") or ""),
            source_asset_id=str(draft.get("sourceAssetId") or ""),
        )
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
    export_id = str(payload.get("exportId") or "").strip()
    if export_id:
        return handoff_idempotency_key(export_id)
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


def _post_threadsdash_draft_ingest(
    payload: dict[str, Any],
    *,
    ingest_url: str | None,
    ingest_secret: str | None,
) -> dict[str, Any]:
    return submit_draft_handoff(
        payload, ingest_url=ingest_url, ingest_secret=ingest_secret
    )


def _reconcile_dashboard_ingest_post_ids(
    *,
    payload: dict[str, Any],
    ingest_result: dict[str, Any],
    user_id: str,
    ingest_url: str | None,
    ingest_secret: str | None,
) -> list[str]:
    post_ids = [
        str(post_id) for post_id in ingest_result.get("postIds") or [] if str(post_id)
    ]
    if post_ids:
        return post_ids
    export_id = str(payload.get("exportId") or "")
    reconciliation = reconcile_draft_handoff(
        export_id=export_id,
        user_id=user_id,
        ingest_url=ingest_url,
        ingest_secret=ingest_secret,
    )
    acknowledgment = reconciliation.get("acknowledgment")
    if not isinstance(acknowledgment, dict):
        raise TimeoutError("Dashboard draft ingest remains ambiguous")
    reconciled = [str(value) for value in acknowledgment.get("postIds") or []]
    if not reconciled:
        raise TimeoutError("Dashboard reconciliation found no accepted draft")
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
