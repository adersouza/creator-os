from __future__ import annotations

import json
from typing import Any

from .core import CampaignFactory, new_id, utc_now


def graduate_trial_reel(
    factory: CampaignFactory,
    *,
    trial_post_id: str,
    distribution_plan_id: str,
    approved_by: str,
) -> dict[str, Any]:
    if not str(approved_by or "").strip():
        raise ValueError("manual approval is required for trial graduation")
    existing = factory.conn.execute(
        "SELECT * FROM promotions WHERE trial_post_id = ?", (trial_post_id,)
    ).fetchone()
    if existing:
        plan = factory.conn.execute(
            "SELECT * FROM distribution_plans WHERE reason_code = ?",
            (f"trial_graduation:{trial_post_id}",),
        ).fetchone()
        return {
            "schema": "campaign_factory.trial_reel_graduation.v1",
            "idempotent": True,
            "trialPostId": trial_post_id,
            "promotionId": existing["id"],
            "distributionPlanId": plan["id"] if plan else None,
            "autoQueued": False,
        }
    trial_row = factory.conn.execute(
        "SELECT * FROM distribution_plans WHERE id = ?", (distribution_plan_id,)
    ).fetchone()
    if not trial_row:
        raise ValueError(f"distribution plan not found: {distribution_plan_id}")
    trial = dict(trial_row)
    if trial.get("surface") != "trial_reel" or not trial.get("instagram_trial_reels"):
        raise ValueError("graduation requires an Instagram trial_reel plan")
    if str(trial.get("trial_graduation_strategy") or "").upper() != "MANUAL":
        raise ValueError("only MANUAL trial graduation is supported")
    account_id = str(trial.get("account_id") or "")
    instagram_account_id = str(trial.get("instagram_account_id") or "")
    if not (account_id or instagram_account_id):
        raise ValueError("trial plan is missing its origin account")
    regular_row = factory.conn.execute(
        "SELECT id FROM distribution_plans WHERE reason_code = ?",
        (f"trial_graduation:{trial_post_id}",),
    ).fetchone()
    regular = (
        factory.distribution_plan(regular_row["id"])
        if regular_row
        else factory.create_distribution_plan(
            trial["rendered_asset_id"],
            surface="regular_reel",
            account_id=account_id or None,
            instagram_account_id=instagram_account_id or None,
            planned_window_start=None,
            reason_code=f"trial_graduation:{trial_post_id}",
            instagram_trial_reels=False,
            trial_group_id=trial.get("trial_group_id"),
        )
    )
    asset = factory.conn.execute(
        "SELECT content_hash FROM rendered_assets WHERE id = ?",
        (trial["rendered_asset_id"],),
    ).fetchone()
    canonical_account = account_id or instagram_account_id
    prior = factory.conn.execute(
        """
        SELECT * FROM promotions
        WHERE content_fingerprint = ? AND account_id = ?
        """,
        (asset["content_hash"], canonical_account),
    ).fetchone()
    now = utc_now()
    if prior:
        if prior["trial_post_id"] and prior["trial_post_id"] != trial_post_id:
            raise ValueError("content/account promotion already has another trial post")
        promotion_id = str(prior["id"])
        factory.conn.execute(
            "UPDATE promotions SET trial_post_id = ?, updated_at = ? WHERE id = ?",
            (trial_post_id, now, promotion_id),
        )
        event_action = "updated"
    else:
        promotion_id = new_id("promotion")
        factory.conn.execute(
            """
            INSERT INTO promotions
            (id, promotion_type, campaign_id, rendered_asset_id, account_id,
             posting_slot_id, content_fingerprint, trial_post_id, source_system,
             created_at, updated_at)
            VALUES (?, 'trial_graduation', ?, ?, ?, ?, ?, ?, 'instagram_trial_reels', ?, ?)
            """,
            (
                promotion_id,
                trial["campaign_id"],
                trial["rendered_asset_id"],
                canonical_account,
                f"trial_graduation:{trial_post_id}",
                asset["content_hash"],
                trial_post_id,
                now,
                now,
            ),
        )
        event_action = "created"
    event_payload = {
        "trialPostId": trial_post_id,
        "trialDistributionPlanId": distribution_plan_id,
        "regularDistributionPlanId": regular["id"],
        "approvedBy": approved_by,
        "sameAccount": True,
        "autoQueued": False,
    }
    factory.conn.execute(
        """
        INSERT INTO promotion_events
        (id, promotion_id, action, actor, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            new_id("promotion_event"),
            promotion_id,
            event_action,
            approved_by,
            json.dumps(event_payload, ensure_ascii=False, sort_keys=True),
            now,
        ),
    )
    factory.conn.commit()
    return {
        "schema": "campaign_factory.trial_reel_graduation.v1",
        "idempotent": False,
        "trialPostId": trial_post_id,
        "promotionId": promotion_id,
        "distributionPlanId": regular["id"],
        "sameAccount": True,
        "autoQueued": False,
    }


def record_trial_observation(
    factory: CampaignFactory,
    *,
    trial_post_id: str,
    distribution_plan_id: str,
    account_id: str,
    observed_hours: int,
    views: int,
    engagement: int,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if observed_hours not in {1, 24}:
        raise ValueError("observed_hours must be 1 or 24")
    now = utc_now()
    observation_id = "trial_observation_" + trial_post_id + f"_{observed_hours}h"
    factory.conn.execute(
        """
        INSERT INTO trial_reel_observations
        (id, trial_post_id, distribution_plan_id, account_id, observed_hours,
         views, engagement, metrics_json, observed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trial_post_id, observed_hours) DO UPDATE SET
          views = excluded.views,
          engagement = excluded.engagement,
          metrics_json = excluded.metrics_json,
          observed_at = excluded.observed_at
        """,
        (
            observation_id,
            trial_post_id,
            distribution_plan_id,
            account_id,
            observed_hours,
            max(0, int(views)),
            max(0, int(engagement)),
            json.dumps(metrics or {}, ensure_ascii=False, sort_keys=True),
            now,
        ),
    )
    factory.conn.commit()
    return {
        "schema": "campaign_factory.trial_reel_observation.v1",
        "trialPostId": trial_post_id,
        "observedHours": observed_hours,
        "views": max(0, int(views)),
        "engagement": max(0, int(engagement)),
    }


def trial_reel_ranking_report(factory: CampaignFactory) -> dict[str, Any]:
    rows = factory.conn.execute(
        """
        SELECT o.*, d.trial_group_id, d.rendered_asset_id
        FROM trial_reel_observations o
        LEFT JOIN distribution_plans d ON d.id = o.distribution_plan_id
        ORDER BY o.trial_post_id, o.observed_hours
        """
    ).fetchall()
    by_post: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        item = by_post.setdefault(
            row["trial_post_id"],
            {
                "trialPostId": row["trial_post_id"],
                "trialGroupId": row.get("trial_group_id"),
                "renderedAssetId": row.get("rendered_asset_id"),
                "accountId": row["account_id"],
                "oneHour": None,
                "twentyFourHour": None,
            },
        )
        bucket = "oneHour" if row["observed_hours"] == 1 else "twentyFourHour"
        item[bucket] = {
            "views": row["views"],
            "engagement": row["engagement"],
            "score": int(row["views"]) + 10 * int(row["engagement"]),
        }
    ranked = sorted(
        by_post.values(),
        key=lambda item: (
            -int((item["twentyFourHour"] or item["oneHour"] or {}).get("score", 0)),
            item["trialPostId"],
        ),
    )
    return {
        "schema": "campaign_factory.trial_reel_ranking_report.v1",
        "cadence": "nightly",
        "windowsHours": [1, 24],
        "count": len(ranked),
        "items": ranked,
        "autoPromotion": False,
    }
