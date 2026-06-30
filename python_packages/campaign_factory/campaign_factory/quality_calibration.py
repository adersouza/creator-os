from __future__ import annotations

import sqlite3
from typing import Any


def track_q_calibration_status(
    conn: sqlite3.Connection,
    *,
    campaign_slug: str | None = None,
    min_reviewed_reels: int = 30,
    min_low_score_or_rejected_samples: int = 10,
    low_score_threshold: int = 70,
) -> dict[str, Any]:
    params: list[Any] = []
    where = "r.media_type = 'video' AND r.content_surface = 'reel'"
    if campaign_slug:
        where += " AND c.slug = ?"
        params.append(campaign_slug)
    rows = conn.execute(
        f"""
        SELECT
          r.id AS rendered_asset_id,
          r.review_state,
          c.slug AS campaign_slug,
          ad.decision AS latest_decision,
          ad.created_at AS reviewed_at,
          ar.score AS latest_score
        FROM rendered_assets r
        JOIN campaigns c ON c.id = r.campaign_id
        JOIN approval_decisions ad ON ad.id = (
          SELECT id FROM approval_decisions
          WHERE rendered_asset_id = r.id
          ORDER BY created_at DESC, id DESC
          LIMIT 1
        )
        LEFT JOIN audit_reports ar ON ar.id = (
          SELECT id FROM audit_reports
          WHERE rendered_asset_id = r.id
          ORDER BY created_at DESC, id DESC
          LIMIT 1
        )
        WHERE {where}
        ORDER BY ad.created_at DESC, r.id
        """,
        params,
    ).fetchall()
    reviewed = len(rows)
    rejected_ids = {
        str(row["rendered_asset_id"])
        for row in rows
        if str(row["latest_decision"] or row["review_state"] or "").lower()
        == "rejected"
    }
    low_score_ids = {
        str(row["rendered_asset_id"])
        for row in rows
        if row["latest_score"] is not None
        and int(row["latest_score"]) < low_score_threshold
    }
    low_or_rejected = rejected_ids | low_score_ids
    reviewed_remaining = max(0, min_reviewed_reels - reviewed)
    low_remaining = max(0, min_low_score_or_rejected_samples - len(low_or_rejected))
    ready = reviewed_remaining == 0 and low_remaining == 0
    return {
        "schema": "campaign_factory.track_q_calibration_status.v1",
        "campaign": campaign_slug,
        "status": "ready_for_calibration" if ready else "collecting_evidence",
        "calibrationReady": ready,
        "targets": {
            "reviewedReels": min_reviewed_reels,
            "lowScoreOrRejectedSamples": min_low_score_or_rejected_samples,
            "lowScoreThreshold": low_score_threshold,
        },
        "counts": {
            "reviewedReels": reviewed,
            "rejectedReels": len(rejected_ids),
            "lowScoreReviewedReels": len(low_score_ids),
            "lowScoreOrRejectedSamples": len(low_or_rejected),
        },
        "remaining": {
            "reviewedReels": reviewed_remaining,
            "lowScoreOrRejectedSamples": low_remaining,
        },
        "wouldWrite": False,
    }
