from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _history_hour(row: sqlite3.Row) -> int | None:
    raw = row["raw_json"]
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        history = data.get("metadata", {}).get("threadsdash_metric_history", {})
        hours = history.get("hoursSincePublish", history.get("hours_since_publish"))
        if hours is not None:
            return int(round(float(hours)))
    snapshot_at = _parse_iso(row["snapshot_at"])
    published_at = _parse_iso(row["published_at"])
    if not snapshot_at or not published_at:
        return None
    return int(round((snapshot_at - published_at).total_seconds() / 3600))


def closed_loop_learning_status(
    conn: sqlite3.Connection,
    *,
    campaign_slug: str | None = None,
    min_posts_with_1h_and_24h: int = 50,
) -> dict[str, Any]:
    params: list[Any] = []
    where = "p.metrics_eligible = 1 AND p.post_id IS NOT NULL"
    if campaign_slug:
        where += " AND c.slug = ?"
        params.append(campaign_slug)
    rows = conn.execute(
        f"""
        SELECT p.post_id, p.snapshot_at, p.published_at, p.raw_json
        FROM performance_snapshots p
        JOIN campaigns c ON c.id = p.campaign_id
        WHERE {where}
        """,
        params,
    ).fetchall()
    hours_by_post: dict[str, set[int]] = {}
    eligible_posts = {str(row["post_id"]) for row in rows}
    for row in rows:
        hour = _history_hour(row)
        if hour is not None:
            hours_by_post.setdefault(str(row["post_id"]), set()).add(hour)
    posts_with_1h = sum(1 for hours in hours_by_post.values() if 1 in hours)
    posts_with_24h = sum(1 for hours in hours_by_post.values() if 24 in hours)
    posts_with_both = sum(1 for hours in hours_by_post.values() if {1, 24}.issubset(hours))
    remaining = max(0, min_posts_with_1h_and_24h - posts_with_both)
    ready = remaining == 0
    return {
        "schema": "campaign_factory.closed_loop_learning_status.v1",
        "campaign": campaign_slug,
        "status": "ready_for_learning_audit" if ready else "collecting_metric_history",
        "learningAuditReady": ready,
        "targets": {"postsWith1hAnd24hHistory": min_posts_with_1h_and_24h},
        "counts": {
            "eligiblePosts": len(eligible_posts),
            "postsWith1hHistory": posts_with_1h,
            "postsWith24hHistory": posts_with_24h,
            "postsWith1hAnd24hHistory": posts_with_both,
        },
        "remaining": {"postsWith1hAnd24hHistory": remaining},
        "wouldWrite": False,
    }
