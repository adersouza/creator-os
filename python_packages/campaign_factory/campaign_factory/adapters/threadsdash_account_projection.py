from __future__ import annotations

import re
from typing import Any
from urllib.request import urlopen

from ..core import (
    CampaignFactory,
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
    _add_usage,
    _empty_usage,
    _post_surface,
    _select_threadsdash_posts,
    _sync_reason_counts,
    _text_hash,
)


def summarize_threadsdash_usage(
    factory: CampaignFactory,
    *,
    campaign_slug: str,
    user_id: str,
    supabase_url: str | None,
    supabase_service_role_key: str | None,
    limit: int = 1000,
    rendered_asset_ids: list[str] | None = None,
) -> dict[str, Any]:
    if not supabase_url or not supabase_service_role_key:
        raise ValueError(
            "supabase_url and supabase_service_role_key are required for usage tracking"
        )
    payload = _draft_payload.build_draft_payloads(
        factory,
        campaign_slug=campaign_slug,
        user_id=user_id,
        rendered_asset_ids=rendered_asset_ids,
    )
    client = _threadsdash_client.SupabaseRestClient(
        supabase_url.rstrip("/"), supabase_service_role_key
    )
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
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    pipeline_job = factory.domains.events.create_pipeline_job(
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
    factory.domains.events.start_pipeline_job(pipeline_job["id"])
    try:
        client = _threadsdash_client.SupabaseRestClient(
            supabase_url.rstrip("/"), supabase_service_role_key
        )
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
                asset = factory.domains.rendered_asset(rendered_asset_id)
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
            factory.domains.campaign_overview.assign_asset_account(
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
        factory.domains.events.record_event(
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
        factory.domains.events.finish_pipeline_job(pipeline_job["id"], result)
        return result
    except Exception as exc:
        factory.domains.events.record_event(
            "threadsdash_assignments_synced",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"ThreadsDash assignment sync failed: {exc}",
            metadata={"error": str(exc)},
        )
        factory.domains.events.fail_pipeline_job(pipeline_job["id"], str(exc))
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
    model = factory.domains.models.upsert_model(creator_slug, creator)
    matcher = (match or creator or "").strip().lower()
    client = _threadsdash_client.SupabaseRestClient(
        supabase_url.rstrip("/"), supabase_service_role_key
    )
    params = {
        "select": (
            "id,username,display_name,is_active,status,needs_reauth,group_id,"
            "user_id,login_type,sync_cohort,oauth_granted_scopes,"
            "oauth_scopes_verified_at,trial_reels_capability,"
            "trial_reels_capability_checked_at,trial_reels_capability_reason"
        ),
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
        before = factory.conn.execute(
            "SELECT id FROM accounts WHERE handle = ? AND platform = 'instagram'",
            (username,),
        ).fetchone()
        capability = str(row.get("trial_reels_capability") or "unknown").lower()
        if capability not in {"unknown", "eligible", "denied"}:
            raise ValueError(
                f"invalid ThreadsDashboard Trial Reel capability for @{username}: "
                f"{capability!r}"
            )
        oauth_scopes = row.get("oauth_granted_scopes")
        if oauth_scopes is not None and not isinstance(oauth_scopes, list):
            raise ValueError(
                f"invalid ThreadsDashboard OAuth scope evidence for @{username}"
            )
        projection_observed_at = utc_now()
        if (
            row.get("is_active") is False
            or row.get("needs_reauth") is True
            or any(
                token in status
                for token in ("blocked", "restricted", "disabled", "reauth")
            )
        ):
            if before:
                factory.domains.models.project_instagram_account_evidence(
                    before["id"],
                    capability=capability,
                    oauth_granted_scopes=oauth_scopes,
                    oauth_scopes_verified_at=row.get("oauth_scopes_verified_at"),
                    checked_at=row.get("trial_reels_capability_checked_at"),
                    reason=row.get("trial_reels_capability_reason"),
                    is_active=row.get("is_active"),
                    status=status,
                    needs_reauth=row.get("needs_reauth"),
                    sync_cohort=row.get("sync_cohort"),
                    projection_observed_at=projection_observed_at,
                )
            skipped.append(
                {"id": row.get("id"), "username": username, "reason": "not_eligible"}
            )
            continue
        account = factory.domains.models.upsert_account(
            username,
            platform="instagram",
            external_id=str(row.get("id") or ""),
            model_id=model["id"],
        )
        account = factory.domains.models.project_instagram_account_evidence(
            account["id"],
            capability=capability,
            oauth_granted_scopes=oauth_scopes,
            oauth_scopes_verified_at=row.get("oauth_scopes_verified_at"),
            checked_at=row.get("trial_reels_capability_checked_at"),
            reason=row.get("trial_reels_capability_reason"),
            is_active=row.get("is_active"),
            status=status,
            needs_reauth=row.get("needs_reauth"),
            sync_cohort=row.get("sync_cohort"),
            projection_observed_at=projection_observed_at,
        )
        imported.append(
            {
                "accountId": account["id"],
                "instagramAccountId": row.get("id"),
                "username": username,
                "displayName": display_name,
                "syncCohort": row.get("sync_cohort"),
                "accountState": {
                    "active": row.get("is_active"),
                    "status": status or "unknown",
                    "needsReauth": row.get("needs_reauth"),
                    "projectionObservedAt": projection_observed_at,
                },
                "trialCapability": {
                    "status": capability,
                    "checkedAt": row.get("trial_reels_capability_checked_at"),
                    "reason": row.get("trial_reels_capability_reason"),
                    "oauthGrantedScopes": oauth_scopes,
                    "oauthScopesVerifiedAt": row.get("oauth_scopes_verified_at"),
                },
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


def _sync_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return slug or "default"
