from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .caption_outcome import load_context_json


class LifecycleReportingRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        campaign_by_slug: Callable[[str], dict[str, Any]],
        dashboard: Callable[[str | None], dict[str, Any]],
        jobs_for_campaign: Callable[..., list[dict[str, Any]]],
        distribution_plans_for_campaign: Callable[[str], list[dict[str, Any]]],
        assignments_for_campaign: Callable[[str], list[dict[str, Any]]],
        performance_snapshot_payload: Callable[[dict[str, Any]], dict[str, Any]],
        active_quarantine_for_asset: Callable[[str], dict[str, Any] | None],
        utc_now: Callable[[], str],
    ) -> None:
        self.conn = conn
        self._campaign_by_slug = campaign_by_slug
        self._dashboard = dashboard
        self._jobs_for_campaign = jobs_for_campaign
        self._distribution_plans_for_campaign = distribution_plans_for_campaign
        self._assignments_for_campaign = assignments_for_campaign
        self._performance_snapshot_payload = performance_snapshot_payload
        self._active_quarantine_for_asset = active_quarantine_for_asset
        self._utc_now = utc_now

    def campaign_readiness(
        self, campaign_slug: str, *, user_id: str | None = None
    ) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        dashboard = self._dashboard(campaign_slug)
        jobs = self._jobs_for_campaign(campaign_slug, limit=100)
        blocking = []
        warnings = []
        for source in dashboard["sources"]:
            has_render_job = self.conn.execute(
                "SELECT 1 FROM render_jobs WHERE source_asset_id = ? LIMIT 1",
                (source["id"],),
            ).fetchone()
            if not has_render_job:
                warnings.append(f"source_missing_render_job:{source['id']}")
        for asset in dashboard["rendered"]:
            if asset["review_state"] == "rejected":
                blocking.append(f"asset_rejected:{asset['id']}")
            if not asset.get("latest_audit"):
                warnings.append(f"missing_audit:{asset['id']}")
            readiness = asset.get("export_readiness") or {}
            for reason in readiness.get("blockingReasons") or []:
                blocking.append(f"{asset['id']}:{reason}")
        failed_jobs = [job for job in jobs if job["status"] == "failed"]
        for job in failed_jobs[:20]:
            warnings.append(f"failed_job:{job['id']}:{job['jobType']}")
        latest_perf = self.conn.execute(
            "SELECT MAX(snapshot_at) AS snapshot_at FROM performance_snapshots WHERE campaign_id = ?",
            (campaign["id"],),
        ).fetchone()
        if not latest_perf or not latest_perf["snapshot_at"]:
            warnings.append("performance_not_synced")
        return {
            "schema": "campaign_factory.campaign_readiness.v1",
            "campaign": campaign["slug"],
            "userId": user_id,
            "checkedAt": self._utc_now(),
            "ready": not blocking,
            "blockingReasons": sorted(set(blocking)),
            "warnings": sorted(set(warnings)),
            "health": dashboard["health"],
            "ranking": dashboard["ranking"][:20],
        }

    def lifecycle_report(
        self,
        campaign_slug: str,
        *,
        user_id: str | None = None,
        threadsdash_posts: list[dict[str, Any]] | None = None,
        include_threadsdash: str = "auto",
        state: str | None = None,
        blocking_reason: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        dashboard = self._dashboard(campaign_slug)
        plans_by_asset: dict[str, list[dict[str, Any]]] = {}
        for plan in self._distribution_plans_for_campaign(campaign_slug):
            plans_by_asset.setdefault(plan["renderedAssetId"], []).append(plan)
        assignments_by_asset: dict[str, list[dict[str, Any]]] = {}
        for assignment in self._assignments_for_campaign(campaign_slug):
            assignments_by_asset.setdefault(assignment["rendered_asset_id"], []).append(
                assignment
            )
        snapshots_by_asset = self.lifecycle_snapshots_by_asset(campaign["id"])
        posts_by_plan, posts_by_asset, td_evidence = self.lifecycle_threadsdash_indexes(
            campaign_slug=campaign_slug,
            user_id=user_id,
            include_threadsdash=include_threadsdash,
            threadsdash_posts=threadsdash_posts,
        )
        rows: list[dict[str, Any]] = []
        for asset in dashboard["rendered"]:
            if rendered_asset_id and asset["id"] != rendered_asset_id:
                continue
            plans = plans_by_asset.get(asset["id"]) or [None]
            for plan in plans:
                row = self.lifecycle_row(
                    campaign=campaign,
                    asset=asset,
                    plan=plan,
                    assignments=assignments_by_asset.get(asset["id"]) or [],
                    snapshots=snapshots_by_asset.get(asset["id"]) or [],
                    threadsdash_posts=(
                        posts_by_plan.get(plan["id"], []) if plan else []
                    )
                    or posts_by_asset.get(asset["id"], []),
                )
                if state and row["currentState"] != state:
                    continue
                if blocking_reason and row["blockingReason"] != blocking_reason:
                    continue
                rows.append(row)
        state_counts: dict[str, int] = {}
        stuck: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            state_counts[row["currentState"]] = (
                state_counts.get(row["currentState"], 0) + 1
            )
            reason = row.get("blockingReason")
            if reason:
                stuck.setdefault(reason, []).append(
                    {
                        "renderedAssetId": row["renderedAssetId"],
                        "distributionPlanId": row.get("distributionPlanId"),
                        "threadsDashboardPostId": row.get("threadsDashboardPostId"),
                        "currentState": row["currentState"],
                        "nextOperatorAction": row["nextOperatorAction"],
                    }
                )
        return {
            "schema": "campaign_factory.lifecycle_report.v1",
            "campaign": campaign["slug"],
            "campaignId": campaign["id"],
            "userId": user_id,
            "generatedAt": self._utc_now(),
            "includeThreadsDashboard": include_threadsdash,
            "threadsdash": td_evidence,
            "summary": {
                "totalRows": len(rows),
                "stateCounts": dict(sorted(state_counts.items())),
                "stuckCounts": {
                    key: len(value) for key, value in sorted(stuck.items())
                },
            },
            "stuck": {key: value for key, value in sorted(stuck.items())},
            "rows": rows,
        }

    def creator_os_lifecycle_dashboard(
        self,
        *,
        campaign: str,
        user_id: str | None = None,
        threadsdash_posts: list[dict[str, Any]] | None = None,
        include_threadsdash: str = "auto",
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        report = self.lifecycle_report(
            campaign,
            user_id=user_id,
            threadsdash_posts=threadsdash_posts,
            include_threadsdash=include_threadsdash,
        )
        buckets = {
            "approved": 0,
            "publishable": 0,
            "exported": 0,
            "scheduled": 0,
            "published": 0,
            "metricsImported": 0,
            "quarantined": 0,
            "failed": 0,
        }
        rows = []
        for row in report.get("rows") or []:
            bucket = self.creator_os_lifecycle_bucket(row)
            buckets[bucket] += 1
            rows.append(
                {
                    "renderedAssetId": row.get("renderedAssetId"),
                    "distributionPlanId": row.get("distributionPlanId"),
                    "threadsDashboardPostId": row.get("threadsDashboardPostId"),
                    "currentState": row.get("currentState"),
                    "bucket": bucket,
                    "blockingReason": row.get("blockingReason"),
                    "nextOperatorAction": row.get("nextOperatorAction"),
                    "lastStateChange": row.get("lastStateChange"),
                    "wouldWrite": False,
                }
            )
        return {
            "schema": "creator_os.lifecycle_dashboard.v1",
            "generatedAt": generated_at or self._utc_now(),
            "campaign": report.get("campaign"),
            "campaignId": report.get("campaignId"),
            "userId": user_id,
            "counts": buckets,
            "commandCenter": dict(buckets),
            "stuckCounts": (report.get("summary") or {}).get("stuckCounts") or {},
            "rows": rows,
            "wouldWrite": False,
            "inputs": {
                "lifecycleReportSchema": report.get("schema"),
                "includeThreadsDashboard": include_threadsdash,
                "threadsdashAvailable": (report.get("threadsdash") or {}).get(
                    "available"
                ),
            },
        }

    def creator_os_lifecycle_bucket(self, row: dict[str, Any]) -> str:
        state = str(row.get("currentState") or "").strip()
        reason = str(row.get("blockingReason") or "").strip()
        if state == "metrics_imported":
            return "metricsImported"
        if state == "published":
            return "published"
        if state in {"scheduled", "past_due_schedule"}:
            return "scheduled"
        if state in {"platform_draft_validated", "exported"}:
            return "exported"
        if state in {"publishable_candidate", "exportable", "ready_for_export"}:
            return "publishable"
        if state in {
            "creative_approved",
            "approved",
            "assigned",
            "distribution_planned",
            "rendered",
        }:
            return "approved"
        if state == "failed" and reason in {
            "quarantined_asset",
            "asset_quarantined",
            "operator_quarantine",
        }:
            return "quarantined"
        if state == "failed" and "quarantine" in reason:
            return "quarantined"
        if state == "failed":
            return "failed"
        return "approved"

    def lifecycle_snapshots_by_asset(
        self, campaign_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        rows = self.conn.execute(
            "SELECT * FROM performance_snapshots WHERE campaign_id = ? ORDER BY snapshot_at DESC, created_at DESC",
            (campaign_id,),
        ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            payload = self._performance_snapshot_payload(dict(row))
            asset_id = payload.get("renderedAssetId")
            if asset_id:
                grouped.setdefault(asset_id, []).append(payload)
        return grouped

    def lifecycle_threadsdash_indexes(
        self,
        *,
        campaign_slug: str,
        user_id: str | None,
        include_threadsdash: str,
        threadsdash_posts: list[dict[str, Any]] | None,
    ) -> tuple[
        dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, Any]
    ]:
        mode = (include_threadsdash or "auto").strip().lower()
        if mode not in {"auto", "live", "off"}:
            raise ValueError("include_threadsdash must be one of: auto, live, off")
        posts = threadsdash_posts
        evidence = {
            "mode": mode,
            "available": posts is not None,
            "rowCount": len(posts or []),
            "source": "provided" if posts is not None else "not_requested",
        }
        if posts is None and mode != "off":
            supabase_url = os.environ.get("SUPABASE_URL")
            service_key = (
                os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
                or os.environ.get("SUPABASE_SERVICE_KEY")
                or os.environ.get("SUPABASE_SECRET_KEY")
            )
            if supabase_url and service_key and user_id:
                try:
                    from .adapters.threadsdash_client import SupabaseRestClient

                    client = SupabaseRestClient(supabase_url.rstrip("/"), service_key)
                    posts = client.select(
                        "posts",
                        {
                            "select": "id,status,scheduled_for,published_at,created_at,updated_at,platform,instagram_account_id,account_id,user_id,metadata",
                            "user_id": f"eq.{user_id}",
                            "order": "created_at.desc",
                            "limit": "1000",
                        },
                    )
                    evidence.update(
                        {
                            "available": True,
                            "rowCount": len(posts),
                            "source": "supabase",
                        }
                    )
                except Exception as exc:
                    if mode == "live":
                        raise
                    evidence.update(
                        {
                            "available": False,
                            "source": "supabase_error",
                            "error": str(exc),
                        }
                    )
                    posts = []
            else:
                evidence.update(
                    {"available": False, "source": "missing_credentials_or_user"}
                )
                posts = []
        posts = posts or []
        by_plan: dict[str, list[dict[str, Any]]] = {}
        by_asset: dict[str, list[dict[str, Any]]] = {}
        for post in posts:
            metadata = (
                post.get("metadata") if isinstance(post.get("metadata"), dict) else {}
            )
            meta = (
                metadata.get("campaign_factory") if isinstance(metadata, dict) else None
            )
            if not isinstance(meta, dict) or meta.get("campaign_id") != campaign_slug:
                continue
            plan_id = meta.get("distribution_plan_id") or meta.get("distributionPlanId")
            asset_id = meta.get("rendered_asset_id") or meta.get("renderedAssetId")
            if plan_id:
                by_plan.setdefault(str(plan_id), []).append(post)
            if asset_id:
                by_asset.setdefault(str(asset_id), []).append(post)
        return by_plan, by_asset, evidence

    def lifecycle_row(
        self,
        *,
        campaign: dict[str, Any],
        asset: dict[str, Any],
        plan: dict[str, Any] | None,
        assignments: list[dict[str, Any]],
        snapshots: list[dict[str, Any]],
        threadsdash_posts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        latest_post = self.latest_lifecycle_post(threadsdash_posts)
        latest_snapshot = snapshots[0] if snapshots else None
        readiness = asset.get("export_readiness") or {}
        context = (
            asset.get("captionOutcomeContext")
            or load_context_json(asset.get("caption_outcome_context_json"))
            or {}
        )
        context_fingerprint = self.lifecycle_fingerprint(context) if context else None
        media_issue = self.lifecycle_media_validation_issue(
            asset=asset, post=latest_post
        )
        mismatch = self.lifecycle_mismatch(
            asset=asset,
            plan=plan,
            post=latest_post,
            snapshot=latest_snapshot,
            context_fingerprint=context_fingerprint,
        )
        current_state, blocking_reason, next_action = self.derive_lifecycle_state(
            asset=asset,
            plan=plan,
            assignments=assignments,
            readiness=readiness,
            post=latest_post,
            snapshot=latest_snapshot,
            mismatch=mismatch,
            media_issue=media_issue,
        )
        last_state_change = self.lifecycle_last_state_change(
            asset=asset, plan=plan, post=latest_post, snapshot=latest_snapshot
        )
        return {
            "campaignId": campaign["id"],
            "campaign": campaign["slug"],
            "renderedAssetId": asset["id"],
            "distributionPlanId": plan.get("id") if plan else None,
            "threadsDashboardPostId": latest_post.get("id")
            if latest_post
            else (latest_snapshot or {}).get("postId"),
            "performanceSnapshotId": (latest_snapshot or {}).get("id"),
            "instagramAccountId": (plan or {}).get("instagramAccountId")
            or (latest_post or {}).get("instagram_account_id")
            or (latest_snapshot or {}).get("instagramAccountId"),
            "accountId": (plan or {}).get("accountId")
            or (latest_post or {}).get("account_id")
            or (latest_snapshot or {}).get("accountId"),
            "contentFingerprint": asset.get("content_hash") or asset.get("contentHash"),
            "captionHash": asset.get("caption_hash") or asset.get("captionHash"),
            "captionOutcomeContextFingerprint": context_fingerprint,
            "currentState": current_state,
            "blockingReason": blocking_reason,
            "nextOperatorAction": next_action,
            "lastStateChange": last_state_change,
            "evidence": {
                "reviewState": asset.get("review_state"),
                "exportReadiness": readiness,
                "assignmentCount": len(assignments),
                "threadsdashPost": self.compact_lifecycle_post(latest_post),
                "performanceSnapshot": self.compact_lifecycle_snapshot(latest_snapshot),
                "lineageMismatch": mismatch,
                "mediaValidation": media_issue,
                "pastDueScheduleResolved": self.lifecycle_past_due_resolved(
                    latest_post
                ),
            },
        }

    def derive_lifecycle_state(
        self,
        *,
        asset: dict[str, Any],
        plan: dict[str, Any] | None,
        assignments: list[dict[str, Any]],
        readiness: dict[str, Any],
        post: dict[str, Any] | None,
        snapshot: dict[str, Any] | None,
        mismatch: dict[str, Any],
        media_issue: dict[str, Any] | None,
    ) -> tuple[str, str | None, str]:
        quarantine = (
            self._active_quarantine_for_asset(asset["id"]) if asset.get("id") else None
        )
        if quarantine:
            return (
                "failed",
                str(
                    quarantine.get("blocking_reason")
                    or quarantine.get("reason")
                    or "quarantined_asset"
                ),
                "replace_draft_with_verified_captioned_asset",
            )
        if media_issue:
            return (
                "failed",
                str(media_issue.get("reason") or "invalid_export_payload"),
                "replace_draft_with_verified_captioned_asset",
            )
        if mismatch:
            reason = next(iter(mismatch))
            return "failed", reason, "inspect_lineage_mismatch"
        if snapshot and self.lifecycle_snapshot_has_metrics(snapshot):
            return "metrics_imported", None, "run_performance_and_caption_reports"
        if post:
            status = str(post.get("status") or "").lower()
            if status == "published" or (
                snapshot and str(snapshot.get("status") or "").lower() == "published"
            ):
                return (
                    "published",
                    "awaiting_metrics",
                    "sync_performance_after_metrics_available",
                )
            if status == "scheduled":
                if self.lifecycle_is_past_due(post.get("scheduled_for")):
                    return (
                        "past_due_schedule",
                        "past_due_schedule",
                        "reschedule_or_manual_publish",
                    )
                return (
                    "scheduled",
                    "awaiting_publish",
                    "wait_for_publish_or_verify_scheduler",
                )
            meta = self.lifecycle_post_meta(post)
            if (
                str(meta.get("platform_state") or "").lower()
                == "platform_draft_validated"
                or str(meta.get("asset_state") or "").lower()
                in {"publishable_candidate", "exportable"}
                and isinstance(meta.get("handoff_manifest"), dict)
            ):
                return (
                    "platform_draft_validated",
                    None,
                    "schedule_or_publish_from_threadsdashboard",
                )
            return "exported", None, "schedule_or_publish_from_threadsdashboard"
        if snapshot and str(snapshot.get("status") or "").lower() == "published":
            return (
                "published",
                "awaiting_metrics",
                "sync_performance_after_metrics_available",
            )
        if snapshot and snapshot.get("postId"):
            return "exported", None, "verify_threadsdashboard_post_status"
        review_state = str(asset.get("review_state") or "").lower()
        if review_state in {"failed", "rejected"}:
            return (
                "failed",
                f"review_state:{review_state}",
                "replace_or_re_review_asset",
            )
        if plan:
            blocking = readiness.get("blockingReasons") or []
            if blocking:
                return (
                    "distribution_planned",
                    self.lifecycle_blocking_reason(blocking),
                    "clear_export_readiness_blockers",
                )
            publishability = (
                readiness.get("publishability")
                if isinstance(readiness.get("publishability"), dict)
                else {}
            )
            if readiness.get("state") == "ready" and publishability.get(
                "publishableCandidate"
            ):
                return "exportable", None, "run_live_export_after_operator_approval"
            if publishability and not publishability.get("publishableCandidate"):
                return (
                    "creative_approved",
                    publishability.get("blockingReason") or "publishability_blocked",
                    "resolve_publishability_failures",
                )
            return (
                "distribution_planned",
                "export_readiness_blocked",
                "run_export_readiness",
            )
        if assignments:
            return "assigned", "missing_distribution_plan", "create_distribution_plan"
        if review_state == "approved":
            return (
                "creative_approved",
                "missing_distribution_plan",
                "assign_account_and_plan_distribution",
            )
        if asset.get("id"):
            return "rendered", "needs_approval", "review_and_approve_or_reject"
        return "promoted", None, "inspect_asset_state"

    def lifecycle_blocking_reason(self, blocking: list[Any]) -> str:
        reasons = [str(item) for item in blocking if item]
        if any("campaign_audio_unresolved" in reason for reason in reasons):
            return "campaign_audio_unresolved"
        if any("missing_audit" in reason for reason in reasons):
            return "missing_audit"
        return "export_readiness_blocked"

    def lifecycle_media_validation_issue(
        self, *, asset: dict[str, Any], post: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        meta = self.lifecycle_post_meta(post) if post else {}
        if meta.get("invalid_export_payload"):
            return {
                "reason": str(meta.get("invalid_reason") or "invalid_export_payload"),
                "source": "threadsdash_metadata",
                "invalidatedAt": meta.get("invalidated_at"),
                "details": meta.get("invalid_details")
                if isinstance(meta.get("invalid_details"), dict)
                else {},
            }
        if not post:
            return None
        recipe = str(asset.get("recipe") or "").strip().lower()
        filename = (
            str(asset.get("filename") or asset.get("filePath") or "").strip().lower()
        )
        caption = str(asset.get("caption") or "").strip()
        if caption and ("passthrough" in recipe or "passthrough" in filename):
            return {
                "reason": "threadsdash_draft_media_invalid_missing_burned_captions",
                "source": "campaign_factory_asset_recipe",
                "details": {
                    "recipe": asset.get("recipe"),
                    "filename": asset.get("filename") or asset.get("filePath"),
                    "captionPresent": True,
                    "note": "Caption metadata exists but selected media is a pass-through variant, which is not safe for caption-burned reel proof.",
                },
            }
        return None

    def latest_lifecycle_post(
        self, posts: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        if not posts:
            return None
        return sorted(
            posts,
            key=lambda row: str(
                row.get("updated_at")
                or row.get("created_at")
                or row.get("scheduled_for")
                or ""
            ),
            reverse=True,
        )[0]

    def lifecycle_snapshot_has_metrics(self, snapshot: dict[str, Any]) -> bool:
        metrics = (
            snapshot.get("metrics") if isinstance(snapshot.get("metrics"), dict) else {}
        )
        return any(
            metrics.get(key) is not None
            for key in (
                "views",
                "likes",
                "comments",
                "shares",
                "saves",
                "impressions",
                "reach",
                "watchTimeSeconds",
            )
        )

    def lifecycle_is_past_due(self, scheduled_for: Any) -> bool:
        if not isinstance(scheduled_for, str) or not scheduled_for.strip():
            return False
        parsed = self.parse_lifecycle_time(scheduled_for)
        return bool(parsed and parsed < datetime.now(UTC))

    def lifecycle_past_due_resolved(self, post: dict[str, Any] | None) -> bool:
        if not post:
            return False
        metadata = (
            post.get("metadata") if isinstance(post.get("metadata"), dict) else {}
        )
        meta = metadata.get("campaign_factory") if isinstance(metadata, dict) else {}
        return bool(
            isinstance(meta, dict)
            and meta.get("past_due_schedule")
            and str(post.get("status") or "").lower() != "scheduled"
        )

    def lifecycle_last_state_change(
        self,
        *,
        asset: dict[str, Any],
        plan: dict[str, Any] | None,
        post: dict[str, Any] | None,
        snapshot: dict[str, Any] | None,
    ) -> str | None:
        candidates = [
            (snapshot or {}).get("snapshotAt"),
            (snapshot or {}).get("publishedAt"),
            (post or {}).get("updated_at"),
            (post or {}).get("published_at"),
            (post or {}).get("scheduled_for"),
            (plan or {}).get("updatedAt"),
            (plan or {}).get("createdAt"),
            asset.get("updated_at") or asset.get("updatedAt"),
            asset.get("created_at") or asset.get("createdAt"),
        ]
        parsed = [
            (self.parse_lifecycle_time(value), value) for value in candidates if value
        ]
        parsed = [(dt, value) for dt, value in parsed if dt]
        if not parsed:
            return None
        return str(max(parsed, key=lambda item: item[0])[1])

    def parse_lifecycle_time(self, value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def lifecycle_mismatch(
        self,
        *,
        asset: dict[str, Any],
        plan: dict[str, Any] | None,
        post: dict[str, Any] | None,
        snapshot: dict[str, Any] | None,
        context_fingerprint: str | None,
    ) -> dict[str, Any]:
        mismatches: dict[str, Any] = {}
        expected_asset_id = asset.get("id")
        expected_content_hash = asset.get("content_hash") or asset.get("contentHash")
        expected_caption_hash = asset.get("caption_hash") or asset.get("captionHash")
        for label, payload in (("threadsdash", post), ("performance", snapshot)):
            if not payload:
                continue
            meta = self.lifecycle_post_meta(payload) if label == "threadsdash" else {}
            asset_id = (
                meta.get("rendered_asset_id")
                or meta.get("renderedAssetId")
                or payload.get("renderedAssetId")
            )
            content_hash = (
                meta.get("content_hash")
                or meta.get("contentHash")
                or payload.get("contentHash")
            )
            caption_hash = (
                meta.get("caption_hash")
                or meta.get("captionHash")
                or payload.get("captionHash")
            )
            if asset_id and expected_asset_id and asset_id != expected_asset_id:
                mismatches["rendered_asset_id_mismatch"] = {
                    "stage": label,
                    "expected": expected_asset_id,
                    "actual": asset_id,
                }
            if (
                content_hash
                and expected_content_hash
                and content_hash != expected_content_hash
            ):
                mismatches["content_fingerprint_mismatch"] = {
                    "stage": label,
                    "expected": expected_content_hash,
                    "actual": content_hash,
                }
            if (
                caption_hash
                and expected_caption_hash
                and caption_hash != expected_caption_hash
            ):
                mismatches["caption_hash_mismatch"] = {
                    "stage": label,
                    "expected": expected_caption_hash,
                    "actual": caption_hash,
                }
            context = (
                meta.get("captionOutcomeContext")
                if label == "threadsdash"
                else payload.get("captionOutcomeContext")
            )
            if context_fingerprint and isinstance(context, dict) and context:
                actual_fingerprint = self.lifecycle_fingerprint(context)
                if actual_fingerprint != context_fingerprint:
                    mismatches["caption_outcome_context_fingerprint_mismatch"] = {
                        "stage": label,
                        "expected": context_fingerprint,
                        "actual": actual_fingerprint,
                    }
        if plan:
            plan_caption_hash = (plan.get("captionOutcomeContext") or {}).get(
                "caption_hash"
            )
            if (
                plan_caption_hash
                and expected_caption_hash
                and plan_caption_hash != expected_caption_hash
            ):
                mismatches["caption_hash_mismatch"] = {
                    "stage": "distribution_plan",
                    "expected": expected_caption_hash,
                    "actual": plan_caption_hash,
                }
        return mismatches

    def lifecycle_post_meta(self, post: dict[str, Any]) -> dict[str, Any]:
        metadata = (
            post.get("metadata") if isinstance(post.get("metadata"), dict) else {}
        )
        meta = metadata.get("campaign_factory") if isinstance(metadata, dict) else {}
        return meta if isinstance(meta, dict) else {}

    def lifecycle_fingerprint(self, value: Any) -> str:
        payload = self.canonical_lifecycle_context(value)
        return hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()

    def canonical_lifecycle_context(self, value: Any) -> Any:
        if isinstance(value, dict):
            normalized: dict[str, Any] = {}
            for key, item in value.items():
                if key == "render_recipe":
                    continue
                canonical = self.canonical_lifecycle_context(item)
                if canonical is None:
                    continue
                normalized[key] = canonical
            return normalized
        if isinstance(value, list):
            return [self.canonical_lifecycle_context(item) for item in value]
        return value

    def compact_lifecycle_post(
        self, post: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not post:
            return None
        return {
            "id": post.get("id"),
            "status": post.get("status"),
            "scheduledFor": post.get("scheduled_for"),
            "publishedAt": post.get("published_at") or post.get("publishedAt"),
            "createdAt": post.get("created_at"),
            "updatedAt": post.get("updated_at"),
            "instagramAccountId": post.get("instagram_account_id"),
        }

    def compact_lifecycle_snapshot(
        self, snapshot: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not snapshot:
            return None
        return {
            "id": snapshot.get("id"),
            "postId": snapshot.get("postId"),
            "status": snapshot.get("status"),
            "publishedAt": snapshot.get("publishedAt"),
            "snapshotAt": snapshot.get("snapshotAt"),
            "metrics": snapshot.get("metrics") or {},
        }
