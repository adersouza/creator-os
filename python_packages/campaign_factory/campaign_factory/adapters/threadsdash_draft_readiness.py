from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from ..contracts import (
    ContractValidationError,
    validate_threadsdash_draft_payload_strict,
)
from ..core import (
    CampaignFactory,
    _normalize_schedule_mode,
    utc_now,
)
from ..readiness_finding import (
    make_readiness_finding,
    readiness_finding_payloads,
    readiness_findings_from_codes,
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
    _empty_usage,
)
from .threadsdash_draft_payload import (
    _allows_draft_notify_audio_deferral,
    _audio_intent_allows_live,
    _normalize_publish_mode,
)


def _draft_payload_contract_blockers(payload: dict[str, Any]) -> list[str]:
    try:
        validate_threadsdash_draft_payload_strict(payload)
    except ContractValidationError as exc:
        detail = str(exc).splitlines()[0].strip()
        return [f"draft_payload_contract_invalid:{detail or 'validation_failed'}"]
    return []


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
    client = _threadsdash_client.SupabaseRestClient(
        supabase_url.rstrip("/"), supabase_service_role_key
    )
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
    blocking_reasons = [check["name"] for check in checks if not check["ok"]]
    return {
        "schema": "campaign_factory.supabase_preflight.v1",
        "checkedAt": utc_now(),
        "bucket": supabase_storage_bucket,
        "ok": passed,
        "checks": checks,
        "blockingReasons": blocking_reasons,
        "findings": readiness_finding_payloads(
            readiness_findings_from_codes(
                blocking_reasons,
                severity="blocker",
                owner="threadsdash",
                operator_action="repair_supabase_preflight",
                evidence={"source": "supabase_preflight"},
            )
        ),
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
    client = _threadsdash_client.SupabaseRestClient(
        supabase_url.rstrip("/"), supabase_service_role_key
    )
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
    blocking_reasons = [
        f"{check['type']}:{check.get('id') or 'missing'}:{reason}"
        for check in checks
        for reason in check.get("blockingReasons", [])
    ]
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
        "blockingReasons": blocking_reasons,
        "findings": readiness_finding_payloads(
            readiness_findings_from_codes(
                blocking_reasons,
                severity="blocker",
                owner="threadsdash",
                operator_action="repair_threadsdash_export_verification",
                evidence={"source": "threadsdash_export_verification"},
            )
        ),
    }


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
    review_only: bool = False,
    record_evidence: bool = True,
) -> dict[str, Any]:
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    normalized_schedule_mode = _normalize_schedule_mode(schedule_mode)
    normalized_publish_mode = _normalize_publish_mode(publish_mode)
    pipeline_job: dict[str, Any] | None = None
    if record_evidence:
        pipeline_job = factory.domains.events.create_pipeline_job(
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
                "reviewOnly": review_only,
            },
        )
        factory.domains.events.start_pipeline_job(pipeline_job["id"])
    try:
        dashboard = factory.domains.campaign_overview.dashboard(campaign_slug)
        payload = _draft_payload.build_draft_payloads(
            factory,
            campaign_slug=campaign_slug,
            user_id=user_id,
            content_pillar=content_pillar,
            cta_type=cta_type,
            language=language,
            rendered_asset_ids=rendered_asset_ids,
            schedule_mode=normalized_schedule_mode,
            publish_mode=normalized_publish_mode,
            review_only=review_only,
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
                from .threadsdash_account_projection import (
                    summarize_threadsdash_usage,
                )

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
                    factory.domains.models.account_compatible_with_model(
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
            asset_findings = readiness_finding_payloads(
                [
                    *readiness_findings_from_codes(
                        blocking,
                        severity="blocker",
                        evidence={
                            "source": "threadsdash_export_readiness",
                            "renderedAssetId": asset.get("id"),
                        },
                    ),
                    *readiness_findings_from_codes(
                        warnings,
                        severity="warning",
                        evidence={
                            "source": "threadsdash_export_readiness",
                            "renderedAssetId": asset.get("id"),
                        },
                    ),
                ]
            )
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
                    "findings": asset_findings,
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
        global_findings: list[dict[str, Any]] = [
            finding
            for row in export_rows
            for finding in row.get("findings") or []
            if isinstance(finding, dict)
        ]
        if not export_rows:
            global_findings.extend(
                dict(finding)
                for finding in readiness_finding_payloads(
                    [
                        make_readiness_finding(
                            "no_approved_assets",
                            severity="blocker",
                            evidence={
                                "source": "threadsdash_export_readiness",
                                "campaign": campaign_slug,
                            },
                        )
                    ]
                )
            )
        if usage_error:
            global_findings.extend(
                dict(finding)
                for finding in readiness_finding_payloads(
                    [
                        make_readiness_finding(
                            "usage_check_unavailable",
                            severity="blocker",
                            evidence={
                                "source": "threadsdash_export_readiness",
                                "error": usage_error,
                            },
                        )
                    ]
                )
            )
        result: dict[str, Any] = {
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
            "findings": global_findings,
            "usageChecked": usage is not None,
            "usageError": usage_error,
            "assets": sorted(rows, key=lambda row: row["operatorScore"], reverse=True),
            "pipelineJobId": None if pipeline_job is None else pipeline_job["id"],
        }
        if pipeline_job is not None:
            factory.domains.events.record_event(
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
            factory.domains.events.finish_pipeline_job(
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
        if pipeline_job is None:
            raise
        factory.domains.events.record_event(
            "export_readiness_checked",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"Export readiness failed: {exc}",
            metadata={"error": str(exc)},
        )
        factory.domains.events.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


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
    client: _threadsdash_client.SupabaseRestClient, media_ref: dict[str, Any]
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
        "findings": readiness_finding_payloads(
            readiness_findings_from_codes(
                blocking,
                severity="blocker",
                owner="threadsdash",
                operator_action="repair_threadsdash_media_row",
                evidence={
                    "source": "threadsdash_export_verification",
                    "type": "media",
                    "id": media_id,
                },
            )
        ),
    }


def _verify_post_row(
    client: _threadsdash_client.SupabaseRestClient, post_ref: dict[str, Any]
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
        "findings": readiness_finding_payloads(
            readiness_findings_from_codes(
                blocking,
                severity="blocker",
                owner="threadsdash",
                operator_action="repair_threadsdash_post_row",
                evidence={
                    "source": "threadsdash_export_verification",
                    "type": "post",
                    "id": post_id,
                },
            )
        ),
    }


def _select_post_for_verification(
    client: _threadsdash_client.SupabaseRestClient, post_id: str
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


def _draft_key(draft: dict[str, Any]) -> tuple[str, str]:
    return (
        draft.get("renderedAssetId") or "",
        draft.get("accountId") or draft.get("instagramAccountId") or "unassigned",
    )


def _account_key(draft: dict[str, Any]) -> str:
    return draft.get("instagramAccountId") or draft.get("accountId") or "unassigned"


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
