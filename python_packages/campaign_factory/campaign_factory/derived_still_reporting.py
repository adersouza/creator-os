"""Read-only reporting for derived still inventory."""

from __future__ import annotations

import json
from typing import Any

from reel_factory.worker_api import DERIVED_STILL_SCHEMA


def derived_still_report(factory: Any, *, campaign_slug: str) -> dict[str, Any]:
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    rows = factory.conn.execute(
        """
        SELECT ra.*, sa.source_prompt
        FROM rendered_assets ra
        JOIN source_assets sa ON sa.id = ra.source_asset_id
        WHERE ra.campaign_id = ?
        ORDER BY ra.created_at, ra.id
        """,
        (campaign["id"],),
    ).fetchall()
    groups: dict[str, dict[str, Any]] = {}
    request_costs: dict[str, dict[str, float]] = {}
    total = approved = static_reels = 0
    for raw in rows:
        row = dict(raw)
        metadata = _json_object(row.get("metadata_json"))
        receipt = metadata.get("derivedStillSource")
        if not isinstance(receipt, dict):
            receipt = _json_object(row.get("source_prompt")).get("derivedStillSource")
        if (
            not isinstance(receipt, dict)
            or receipt.get("schema") != DERIVED_STILL_SCHEMA
        ):
            continue
        is_candidate = row["media_type"] == "image"
        total += int(is_candidate)
        approved += int(is_candidate and row["review_state"] == "approved")
        static_reels += int(row.get("recipe") == "static_mp4")
        evidence = receipt.get("evidence") or {}
        key_values = (
            receipt.get("sourceTier"),
            receipt.get("provider") or "local",
            evidence.get("batchingFormat") or "none",
            receipt.get("operation"),
        )
        key = "|".join(str(value) for value in key_values)
        group = groups.setdefault(
            key,
            {
                "sourceTier": key_values[0],
                "provider": key_values[1],
                "format": key_values[2],
                "operation": key_values[3],
                "candidates": 0,
                "approved": 0,
                "staticReels": 0,
                "reach72h": 0,
                "watchTimeSeconds72h": 0.0,
                "saves72h": 0,
            },
        )
        group["candidates"] += int(is_candidate)
        group["approved"] += int(is_candidate and row["review_state"] == "approved")
        group["staticReels"] += int(row.get("recipe") == "static_mp4")
        request_fingerprint = evidence.get("requestFingerprint")
        quote = evidence.get("quote")
        if (
            isinstance(request_fingerprint, str)
            and isinstance(quote, dict)
            and quote.get("unit") == "USD"
            and isinstance(quote.get("amount"), (int, float))
        ):
            request_costs.setdefault(key, {})[request_fingerprint] = float(
                quote["amount"]
            )
        snapshot = factory.conn.execute(
            """
            SELECT reach, watch_time_seconds, saves
            FROM performance_snapshots
            WHERE rendered_asset_id = ?
              AND julianday(snapshot_at) - julianday(published_at) >= 3
            ORDER BY snapshot_at DESC LIMIT 1
            """,
            (row["id"],),
        ).fetchone()
        if snapshot:
            group["reach72h"] += int(snapshot["reach"] or 0)
            group["watchTimeSeconds72h"] += float(snapshot["watch_time_seconds"] or 0)
            group["saves72h"] += int(snapshot["saves"] or 0)
    rejection_reasons: dict[str, int] = {}
    events = factory.conn.execute(
        """
        SELECT event_type, metadata_json FROM activity_events
        WHERE campaign_id = ? AND event_type IN (
          'derived_still_edit_completed', 'derived_still_harvest_completed'
        )
        """,
        (campaign["id"],),
    ).fetchall()
    for event in events:
        payload = _json_object(event["metadata_json"])
        reasons: list[str] = []
        if event["event_type"] == "derived_still_edit_completed":
            reasons.extend(
                str(item.get("reason"))
                for item in payload.get("rejectedPanels") or []
                if isinstance(item, dict) and item.get("reason")
            )
        else:
            reasons.extend(
                str(reason)
                for reason in _object(payload.get("harvest")).get("exhaustionReasons")
                or []
            )
        for reason in reasons:
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
    for key, group in groups.items():
        cost = round(sum(request_costs.get(key, {}).values()), 4)
        group["approvalYield"] = (
            group["approved"] / group["candidates"] if group["candidates"] else None
        )
        group["staticReelProductionYield"] = (
            group["staticReels"] / group["approved"] if group["approved"] else None
        )
        group["costUsd"] = cost
        group["costPerExactShaApprovedPanelUsd"] = (
            round(cost / group["approved"], 4) if group["approved"] and cost else None
        )
    return {
        "schema": "campaign_factory.derived_still_inventory_report.v1",
        "campaign": campaign_slug,
        "candidateCount": total,
        "approvedCount": approved,
        "approvalYield": approved / total if total else None,
        "staticReelCount": static_reels,
        "rejectionReasons": rejection_reasons,
        "groups": list(groups.values()),
    }


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
