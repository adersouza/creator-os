from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from ..caption_outcome import (
    build_caption_outcome_context,
    column_values,
    load_context_json,
)
from ..contracts import (
    validate_performance_sync,
)
from ..core import (
    CampaignFactory,
    new_id,
    normalize_content_surface,
    utc_now,
)
from ..learning_cohort import (
    COHORT_ID,
    sync_learning_cohort_metrics,
    sync_learning_cohort_publish_state,
)
from ..learning_readiness import closed_loop_learning_status
from ..learning_score import (
    learning_ineligibility_reasons,
    learning_loop_cutover_iso,
)
from ..lineage_v2 import (
    lineage_v2_is_learning_traceable,
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
from .threadsdash_client import (
    _post_surface,
    _select_threadsdash_post_metric_history,
    _select_threadsdash_posts_paged,
    _sync_reason_counts,
    _text_hash,
    _validate_threadsdash_post_metric_history_read,
)


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
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    pipeline_job = factory.domains.events.create_pipeline_job(
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
    factory.domains.events.start_pipeline_job(pipeline_job["id"])
    try:
        client = _threadsdash_client.SupabaseRestClient(
            supabase_url.rstrip("/"), supabase_service_role_key
        )
        rows, posts_truncated = _select_threadsdash_posts_paged(
            client,
            user_id=user_id,
            campaign_ids=[campaign["id"], campaign_slug],
            limit=limit,
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
                post_graph_id = factory.domains.graph.ensure_graph_node(
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
                    factory.domains.exceptions.create_exception(
                        reason_code="performance_sync_missing_graph_ids",
                        severity="medium",
                        campaign_id=campaign["id"],
                        entity_graph_id=post_graph_id,
                        payload=warning,
                        commit=False,
                    )
                if not rendered_graph_id and snapshot["rendered_asset_id"]:
                    rendered_graph_id = factory.domains.graph.graph_id_for(
                        "rendered_assets",
                        snapshot["rendered_asset_id"],
                        entity_type="rendered_asset",
                    )
                before_edges = factory.conn.total_changes
                factory.domains.ensure_graph_edge_strict(
                    rendered_graph_id,
                    post_graph_id,
                    "rendered_asset_to_threadsdash_post",
                    evidence={"postId": snapshot["post_id"], "performanceSync": True},
                    campaign_id=campaign["id"],
                    source_operation="threadsdash_performance_sync",
                )
                performance_graph_id = factory.domains.graph.ensure_graph_node(
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
                factory.domains.ensure_graph_edge_strict(
                    post_graph_id,
                    performance_graph_id,
                    "threadsdash_post_to_performance_snapshot",
                    evidence={"snapshotAt": snapshot["snapshot_at"]},
                    campaign_id=campaign["id"],
                    source_operation="threadsdash_performance_sync",
                )
                recommendation_graph_id = factory.domains.graph.ensure_graph_node(
                    "recommendation_input",
                    external_system="campaign_factory.recommendation_input",
                    external_id=snapshot["id"],
                    payload={
                        "performanceSnapshotId": snapshot["id"],
                        "campaignId": campaign["id"],
                    },
                )
                factory.domains.ensure_graph_edge_strict(
                    performance_graph_id,
                    recommendation_graph_id,
                    "performance_snapshot_to_recommendation_input",
                    evidence={"source": "threadsdash_performance_sync"},
                    campaign_id=campaign["id"],
                    source_operation="threadsdash_performance_sync",
                )
                audio_rollup = (
                    factory.domains.audio_operations.record_audio_performance_snapshot(
                        snapshot, commit=False
                    )
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
                        audio_selection_graph_id = factory.domains.graph.ensure_graph_node(
                            "audio_selection",
                            external_system="threadsdash.audio_selection",
                            external_id=f"{snapshot['post_id']}:{audio_rollup['audioKey']}",
                            payload={"postId": snapshot["post_id"], "audio": selection},
                        )
                        factory.domains.graph.ensure_graph_edge(
                            audio_selection_graph_id,
                            post_graph_id,
                            "audio_selection_to_threadsdash_post",
                        )
                        factory.domains.graph.ensure_graph_edge(
                            audio_selection_graph_id,
                            performance_graph_id,
                            "audio_selection_to_performance_snapshot",
                        )
                if existing and factory.conn.total_changes > before_edges:
                    backfilled_edges += 1
        factory.domains.graph.set_sync_state(
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
        cohort_publish_writeback = (
            sync_learning_cohort_publish_state(factory.conn)
            if campaign_slug == COHORT_ID
            else None
        )
        cohort_metric_writeback = (
            sync_learning_cohort_metrics(factory.conn)
            if campaign_slug == COHORT_ID
            else None
        )
        summary = factory.domains.performance_summary_repo.performance_summary(
            campaign_slug
        )
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
            "learningCohortPublishWriteback": cohort_publish_writeback,
            "learningCohortMetricWriteback": cohort_metric_writeback,
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
        factory.domains.events.record_event(
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
                "learningCohortPublishWriteback": cohort_publish_writeback,
                "learningCohortMetricWriteback": cohort_metric_writeback,
                "campaignFactorySnapshotsScanned": tracked_snapshot_count,
                "inserted": inserted,
                "updated": updated,
                "backfilledEdges": backfilled_edges,
                "skipped": skipped,
                "skipReasons": _sync_reason_counts(skipped_rows),
                "warnings": warnings,
            },
        )
        factory.domains.events.finish_pipeline_job(
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
                "learningCohortMetricWriteback": cohort_metric_writeback,
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
        factory.domains.events.record_event(
            "performance_synced",
            campaign_id=campaign["id"],
            pipeline_job_id=pipeline_job["id"],
            status="failure",
            message=f"Performance sync failed: {exc}",
            metadata={"error": str(exc)},
        )
        factory.domains.events.fail_pipeline_job(pipeline_job["id"], str(exc))
        raise


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
    post_graph_id = factory.domains.graph.ensure_graph_node(
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
    factory.domains.exceptions.create_exception(
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
        "watch_time_seconds": _watch_time_seconds(row, metrics_meta),
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

    stored_lineage_path = str(stored_source.get("sourceLineagePath") or "").strip()
    incoming_lineage_path = str(incoming_source.get("sourceLineagePath") or "").strip()
    if stored_lineage_path and incoming_lineage_path != stored_lineage_path:
        if incoming_lineage_path:
            blockers.append("sourceLineagePath_conflict")
        else:
            incoming_source["sourceLineagePath"] = stored_lineage_path
            repaired_fields.append("source.sourceLineagePath")

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

    trusted_source = dict(incoming_source)
    if stored_lineage_path:
        trusted_source["sourceLineagePath"] = stored_lineage_path
    else:
        trusted_source.pop("sourceLineagePath", None)
    trusted_features = _features_from_source_lineage(
        trusted_source,
        prompt_id=str(incoming_source.get("promptId") or ""),
    )
    incoming_features = (
        lineage.get("features") if isinstance(lineage.get("features"), dict) else {}
    )
    if trusted_features:
        merged_features = dict(trusted_features)
        merged_features.update(
            {
                key: value
                for key, value in incoming_features.items()
                if value not in (None, "", "unknown")
            }
        )
        if merged_features != incoming_features:
            lineage["features"] = merged_features
            repaired_fields.append("features")
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


def _features_from_source_lineage(
    source: dict[str, Any], *, prompt_id: str
) -> dict[str, Any]:
    raw_path = str(source.get("sourceLineagePath") or "").strip()
    if not raw_path:
        return {}
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    generation = (
        payload.get("generation") if isinstance(payload.get("generation"), dict) else {}
    )
    captured = str(generation.get("capturedHiggsfieldPrompt") or "").strip()
    if captured and prompt_id.startswith("prompt_higgsfield_"):
        resolved = (
            "prompt_higgsfield_"
            + hashlib.sha256(captured.encode("utf-8")).hexdigest()[:16]
        )
        if resolved != prompt_id:
            return {}
    features = payload.get("features")
    if not isinstance(features, dict):
        return {}
    return {
        str(key): value for key, value in features.items() if value not in (None, "")
    }


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
            asset = factory.domains.rendered_asset(str(rendered_asset_id))
        except ValueError:
            asset = None
            blockers.append("rendered_asset_not_found")
        if factory.domains.publishability.active_quarantine_for_asset(
            str(rendered_asset_id)
        ):
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
    publishability_failures = {
        str(value).strip()
        for value in meta.get("publishability_failure_reasons") or []
        if str(value).strip()
    }
    notify_audio_resolved = (
        status == "published"
        and str(row.get("publish_mode") or "").lower() == "notify"
        and str(row.get("handoff_status") or "").lower() == "completed"
        and bool(row.get("manual_publish_confirmed_at"))
        and bool(row.get("instagram_post_id"))
        and bool(row.get("permalink"))
        and publishability_failures.issubset(
            {"embedded_audio_missing", "missing_audio"}
        )
    )
    if publishability_failures and not notify_audio_resolved:
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


def _watch_time_seconds(row: dict[str, Any], meta: dict[str, Any]) -> float | None:
    """Normalize ThreadsDashboard watch-time fields to total seconds.

    Creator OS stores total watch time in ``performance_snapshots``. Explicit
    normalized fields already use seconds. Meta's Reel insight fields are raw
    milliseconds: prefer total view time, or derive it from average watch time
    and views when the total is unavailable.
    """
    normalized = _float_metric(
        row, meta, "watch_time_seconds", "watchTimeSeconds", "watch_time"
    )
    if normalized is not None:
        return normalized

    total_ms = _float_metric(row, meta, "ig_reels_video_view_total_time")
    if total_ms is not None:
        return total_ms / 1000.0

    average_ms = _float_metric(row, meta, "ig_reels_avg_watch_time")
    if average_ms is None:
        return None
    views = _int_metric(row, meta, "views", "view_count", "views_count", "ig_views")
    if views is None:
        return None
    return average_ms * views / 1000.0


def _metric_value(row: dict[str, Any], meta: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) is not None:
            return row.get(key)
    for key in keys:
        if meta.get(key) is not None:
            return meta.get(key)
    return None
