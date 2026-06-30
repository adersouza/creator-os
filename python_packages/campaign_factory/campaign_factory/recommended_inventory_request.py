from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RecommendedInventoryRequestRepository:
    def __init__(
        self,
        *,
        creator_label: Callable[[Any], str],
        creator_os_daily_plan: Callable[..., dict[str, Any]],
        normalize_content_surface: Callable[[str | None], str],
        recommendation_explainability: Callable[..., dict[str, Any]],
        utc_now: Callable[[], str],
    ) -> None:
        self._creator_label = creator_label
        self._creator_os_daily_plan = creator_os_daily_plan
        self._normalize_content_surface = normalize_content_surface
        self._recommendation_explainability = recommendation_explainability
        self._utc_now = utc_now

    def recommended_inventory_request_plan(
        self,
        *,
        creator: str,
        target_count: int | None = None,
        daily_plan: dict[str, Any] | None = None,
        variant_inventory_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        source_plan = (
            daily_plan
            if isinstance(daily_plan, dict)
            else self._creator_os_daily_plan(creators=[creator_label])
        )
        creator_row = self.recommended_inventory_creator_row(source_plan, creator_label)
        recommendations = (
            [
                item
                for item in (creator_row.get("recommendedInventory") or [])
                if isinstance(item, dict)
            ]
            if creator_row
            else []
        )
        target = max(
            0,
            int(
                target_count
                if target_count is not None
                else (creator_row or {}).get("inventoryShortfall")
                or len(recommendations)
                or 0
            ),
        )
        existing_by_parent = self.recommended_inventory_existing_by_parent(
            variant_inventory_plan
        )
        recommended_parent_ids = {
            str(item.get("parentAssetId") or "")
            for item in recommendations
            if isinstance(item, dict) and str(item.get("parentAssetId") or "")
        }
        matched_existing_total = sum(
            existing_by_parent.get(parent_id, 0) for parent_id in recommended_parent_ids
        )
        existing_total = (
            min(target, matched_existing_total) if target else matched_existing_total
        )
        remaining = target
        batches: list[dict[str, Any]] = []
        if recommendations:
            for recommendation in recommendations:
                if remaining <= 0:
                    break
                surface = self._normalize_content_surface(
                    recommendation.get("surface") or "reel"
                )
                parent_asset_id = str(recommendation.get("parentAssetId") or "")
                existing_available = (
                    min(remaining, existing_by_parent.get(parent_asset_id, 0))
                    if parent_asset_id
                    else 0
                )
                target_for_batch = (
                    existing_available if existing_available > 0 else remaining
                )
                if target_for_batch <= 0:
                    continue
                batch = {
                    "sourceSystem": recommendation.get("sourceSystem")
                    or "campaign_factory.creative_performance_analysis",
                    "surface": surface,
                    "recommendedAction": self.recommended_inventory_action(
                        surface=surface, story_intent=recommendation.get("storyIntent")
                    ),
                    "parentAssetId": parent_asset_id,
                    "conceptId": str(recommendation.get("conceptId") or ""),
                    "captionAngle": str(recommendation.get("captionAngle") or ""),
                    "postingWindow": str(recommendation.get("postingWindow") or ""),
                    "audioId": str(recommendation.get("audioId") or ""),
                    "storyIntent": str(recommendation.get("storyIntent") or ""),
                    "targetCount": target_for_batch,
                    "existingInventoryAvailable": existing_available,
                    "requiresNewInventory": target_for_batch > existing_available,
                    "reason": str(
                        recommendation.get("reason")
                        or "recommended_inventory_outperformed_baseline"
                    ),
                    "confidence": str(recommendation.get("confidence") or "low"),
                    "sampleSize": int(
                        recommendation.get("sampleSize")
                        or (
                            (recommendation.get("explainability") or {}).get(
                                "sampleSize"
                            )
                            if isinstance(recommendation.get("explainability"), dict)
                            else 0
                        )
                        or 0
                    ),
                    "baselineMetric": str(
                        recommendation.get("baselineMetric")
                        or (
                            (recommendation.get("explainability") or {}).get(
                                "baselineMetric"
                            )
                            if isinstance(recommendation.get("explainability"), dict)
                            else ""
                        )
                        or "score"
                    ),
                    "observedMetric": str(
                        recommendation.get("observedMetric")
                        or (
                            (recommendation.get("explainability") or {}).get(
                                "observedMetric"
                            )
                            if isinstance(recommendation.get("explainability"), dict)
                            else ""
                        )
                        or "score"
                    ),
                    "scoreLiftPct": recommendation.get("scoreLiftPct") or 0,
                    "wouldWrite": False,
                }
                batch["explainability"] = self._recommendation_explainability(
                    batch,
                    item=recommendation.get("explainability")
                    if isinstance(recommendation.get("explainability"), dict)
                    else recommendation,
                    confidence=batch.get("confidence"),
                )
                if parent_asset_id and variant_inventory_plan:
                    batch["variantInventoryBatch"] = (
                        self.recommended_inventory_variant_batch(
                            parent_asset_id, variant_inventory_plan
                        )
                    )
                batches.append(batch)
                remaining -= target_for_batch
        blocking_reason = "" if batches else "no_recommended_inventory_available"
        return {
            "schema": "creator_os.recommended_inventory_request_plan.v1",
            "creator": creator_label,
            "generatedAt": self._utc_now(),
            "targetCount": target,
            "existingInventoryCanSatisfy": existing_total,
            "remainingRequestCount": max(0, target - existing_total),
            "canSatisfyFromExistingInventory": bool(
                target > 0 and existing_total >= target
            ),
            "requestBatches": batches,
            "blockingReason": blocking_reason,
            "nextSafeAction": "review_and_approve_inventory_requests"
            if batches
            else "wait_for_more_metrics_or_create_operator_selected_inventory",
            "inputs": {
                "dailyPlanSchema": source_plan.get("schema")
                if isinstance(source_plan, dict)
                else None,
                "variantInventoryPlanSchema": variant_inventory_plan.get("schema")
                if isinstance(variant_inventory_plan, dict)
                else None,
            },
            "wouldWrite": False,
        }

    def recommended_inventory_creator_row(
        self, daily_plan: dict[str, Any], creator: str
    ) -> dict[str, Any]:
        for row in daily_plan.get("creators") or []:
            if (
                isinstance(row, dict)
                and self._creator_label(row.get("creator")) == creator
            ):
                return row
        return {}

    def recommended_inventory_existing_by_parent(
        self, variant_inventory_plan: dict[str, Any] | None
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        if not isinstance(variant_inventory_plan, dict):
            return counts
        for batch in variant_inventory_plan.get("executionBatches") or []:
            if not isinstance(batch, dict):
                continue
            parent = str(batch.get("parentAssetId") or "")
            if not parent:
                continue
            counts[parent] = counts.get(parent, 0) + max(
                0, int(batch.get("requestedVariants") or 0)
            )
        return counts

    def recommended_inventory_variant_batch(
        self,
        parent_asset_id: str,
        variant_inventory_plan: dict[str, Any],
    ) -> dict[str, Any]:
        for batch in variant_inventory_plan.get("executionBatches") or []:
            if (
                isinstance(batch, dict)
                and str(batch.get("parentAssetId") or "") == parent_asset_id
            ):
                return {**batch, "wouldWrite": False}
        return {}

    def recommended_inventory_action(
        self, *, surface: str, story_intent: Any = None
    ) -> str:
        if surface == "reel":
            return "create_more_reels"
        if surface == "story" and str(story_intent or "") == "snapchat_promo":
            return "create_more_snapchat_promo_stories"
        if surface == "story":
            return "create_more_stories"
        if surface == "feed_carousel":
            return "create_more_carousels"
        if surface == "feed_single":
            return "create_more_feed_singles"
        return "create_more_inventory"
