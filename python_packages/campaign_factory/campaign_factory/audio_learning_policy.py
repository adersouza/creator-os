from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from .learning_score import (
    account_reward_baselines,
    learning_eligible,
    learning_loop_cutover,
    learning_summary,
    snapshot_normalized_reward,
)
from .persistence import json_load


def _snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "postId": row.get("post_id"),
        "instagramAccountId": row.get("instagram_account_id") or row.get("account_id"),
        "snapshotAt": row.get("snapshot_at"),
        "metrics": {
            key: row.get(column)
            for key, column in (
                ("views", "views"),
                ("likes", "likes"),
                ("comments", "comments"),
                ("shares", "shares"),
                ("saves", "saves"),
                ("impressions", "impressions"),
                ("reach", "reach"),
                ("watchTimeSeconds", "watch_time_seconds"),
            )
        },
    }


def measured_audio_performance(
    conn: Any,
    *,
    catalog_ids: set[str],
    creator: str,
    creator_identity_profile: str,
    account: str | None,
    intent: str,
    now: datetime,
    observation_bucket: Callable[[object, object], str | None],
    production_buckets: Sequence[str],
    minimum_examples: int,
    objective: str,
    policy_version: str,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    cutover = learning_loop_cutover()
    if not catalog_ids or cutover is None:
        return {}, []
    placeholders = ",".join("?" for _ in catalog_ids)
    rows = conn.execute(
        f"""
        SELECT s.audio_catalog_id, h.linkage_json, h.segment_start_seconds,
               p.post_id, p.account_id, p.instagram_account_id,
               p.published_at, p.snapshot_at, p.metrics_eligible,
               p.history_source, p.lineage_v2_valid, p.raw_json,
               p.views, p.likes, p.comments, p.shares, p.saves,
               p.impressions, p.reach, p.watch_time_seconds
        FROM audio_publication_history h
        JOIN audio_selections s ON s.id = h.audio_selection_id
        JOIN performance_snapshots p ON p.post_id = h.post_id
        WHERE s.audio_catalog_id IN ({placeholders})
        ORDER BY p.snapshot_at DESC, p.id DESC
        """,
        tuple(sorted(catalog_ids)),
    ).fetchall()
    eligible: list[dict[str, Any]] = []
    for stored in rows:
        row = dict(stored)
        if not learning_eligible(row, cutover=cutover):
            continue
        bucket = observation_bucket(row.get("published_at"), row.get("snapshot_at"))
        if bucket not in production_buckets:
            continue
        linkage = json_load(row.get("linkage_json"), {})
        if (
            str(linkage.get("creator") or "") != creator
            or str(linkage.get("intent") or "") != intent
        ):
            continue
        row["observation_bucket"] = bucket
        row["creator_identity_profile"] = str(
            linkage.get("creatorIdentityProfile") or ""
        )
        row["publication_account"] = str(linkage.get("account") or "")
        eligible.append(row)

    baseline_rows = conn.execute(
        """
        SELECT post_id, account_id, instagram_account_id, published_at, snapshot_at,
               metrics_eligible, history_source, lineage_v2_valid, raw_json,
               views, likes, comments, shares, saves, impressions, reach,
               watch_time_seconds
        FROM performance_snapshots
        ORDER BY snapshot_at DESC, id DESC
        """
    ).fetchall()
    adjustments: dict[str, float] = {}
    evidence: list[dict[str, Any]] = []
    for catalog_id in sorted(catalog_ids):
        candidate_rows = [
            row for row in eligible if str(row["audio_catalog_id"]) == catalog_id
        ]
        scopes = (
            (
                "creator_identity_account_intent",
                [
                    row
                    for row in candidate_rows
                    if row["creator_identity_profile"] == creator_identity_profile
                    and row["publication_account"] == str(account or "")
                ],
            ),
            ("creator_intent", candidate_rows),
        )
        selected_scope = ""
        selected_bucket = ""
        selected_rows: list[dict[str, Any]] = []
        for scope, scoped_rows in scopes:
            for bucket in production_buckets:
                latest_by_post: dict[str, dict[str, Any]] = {}
                for row in scoped_rows:
                    if row["observation_bucket"] != bucket:
                        continue
                    post_id = str(row.get("post_id") or "")
                    if post_id and post_id not in latest_by_post:
                        latest_by_post[post_id] = row
                if len(latest_by_post) >= minimum_examples:
                    selected_scope = scope
                    selected_bucket = bucket
                    selected_rows = list(latest_by_post.values())
                    break
            if selected_rows:
                break
        if not selected_rows:
            continue
        accounts = {
            str(row.get("instagram_account_id") or row.get("account_id") or "")
            for row in selected_rows
        }
        baseline_snapshots = [
            _snapshot(row)
            for stored in baseline_rows
            if learning_eligible((row := dict(stored)), cutover=cutover)
            and observation_bucket(row.get("published_at"), row.get("snapshot_at"))
            == selected_bucket
            and str(row.get("instagram_account_id") or row.get("account_id") or "")
            in accounts
        ]
        snapshots = [_snapshot(row) for row in selected_rows]
        baselines = account_reward_baselines(
            snapshots=baseline_snapshots, objective=objective
        )
        summary = learning_summary(
            snapshots,
            account_baselines=baselines,
            reference_now=now,
            objective=objective,
        )
        score = summary.get("score")
        if not isinstance(score, (int, float)):
            continue
        adjustment = round(max(-8.0, min(10.0, (float(score) - 50.0) * 0.2)), 4)
        adjustments[catalog_id] = adjustment
        post_ids = sorted(str(row["post_id"]) for row in selected_rows)
        best_row = max(
            selected_rows,
            key=lambda row: snapshot_normalized_reward(
                _snapshot(row), baselines, objective=objective
            ),
        )
        evidence.append(
            {
                "schema": "campaign_factory.audio_learning_evidence.v1",
                "policyVersion": policy_version,
                "audioCatalogId": catalog_id,
                "contextScope": selected_scope,
                "observationBucket": selected_bucket,
                "sampleCount": len(post_ids),
                "score": score,
                "scoreAdjustment": adjustment,
                "bestSegmentOffsetSeconds": best_row.get("segment_start_seconds"),
                "scoringVersion": summary.get("scoringVersion"),
                "effectiveSampleSize": summary.get("effectiveSampleSize"),
                "explorationPriority": (
                    summary.get("posteriorRanking") or summary.get("bandit") or {}
                ).get("explorationPriority"),
                "postIdsFingerprint": hashlib.sha256(
                    "\n".join(post_ids).encode("utf-8")
                ).hexdigest(),
            }
        )
    return adjustments, evidence
