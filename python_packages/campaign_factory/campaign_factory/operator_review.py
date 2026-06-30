from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable
from typing import Any


class OperatorReviewRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        normalize_content_surface: Callable[[str | None], str],
        multi_blocker_inventory_unlock_report: Callable[..., dict[str, Any]],
        repair_minutes: dict[str, int],
    ) -> None:
        self.conn = conn
        self._normalize_content_surface = normalize_content_surface
        self._multi_blocker_inventory_unlock_report = (
            multi_blocker_inventory_unlock_report
        )
        self._repair_minutes = repair_minutes

    def operator_inventory_review_batch_plan(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = "reel",
        required_inventory: int = 225,
        current_inventory: int | None = None,
        target_unlock: int | None = None,
        max_batch_size: int | None = None,
    ) -> dict[str, Any]:
        unlock = self._multi_blocker_inventory_unlock_report(
            creator=creator,
            campaign_slug=campaign_slug,
            content_surface=content_surface,
            required_inventory=required_inventory,
            current_inventory=current_inventory,
        )
        shortfall = max(
            0,
            int(required_inventory) - int(unlock.get("currentScheduleSafeAssets") or 0),
        )
        target = int(target_unlock) if target_unlock is not None else shortfall
        candidates = [
            self.operator_review_candidate_row(asset)
            for asset in unlock.get("blockedAssets") or []
            if self.operator_review_candidate_eligible(asset)
        ]
        candidates = sorted(
            candidates,
            key=lambda row: (
                -int(row.get("estimatedInventoryGain") or 0),
                int(row.get("estimatedOperatorMinutes") or 0),
                int(row.get("repairClassCount") or 0),
                str(row.get("assetId") or ""),
            ),
        )
        selected: list[dict[str, Any]] = []
        unlocked = 0
        for row in candidates:
            if max_batch_size is not None and len(selected) >= max(
                0, int(max_batch_size)
            ):
                break
            if unlocked >= target:
                break
            selected.append(row)
            unlocked += int(row.get("estimatedInventoryGain") or 0)
        minutes = sum(int(row.get("estimatedOperatorMinutes") or 0) for row in selected)
        return {
            "schema": "creator_os.operator_inventory_review_batch_plan.v1",
            "creator": creator,
            "campaign": campaign_slug,
            "contentSurface": self._normalize_content_surface(
                content_surface or "reel"
            ),
            "targetUnlock": target,
            "currentScheduleSafeAssets": int(
                unlock.get("currentScheduleSafeAssets") or 0
            ),
            "requiredFor25Accounts": int(required_inventory),
            "shortfall": shortfall,
            "reviewCandidates": len(candidates),
            "recommendedReviewBatchSize": len(selected),
            "estimatedInventoryGain": unlocked,
            "estimatedOperatorMinutes": minutes,
            "wouldPass25GateAfterBatch": int(
                unlock.get("currentScheduleSafeAssets") or 0
            )
            + unlocked
            >= int(required_inventory),
            "remainingGapAfterBatch": max(
                0,
                int(required_inventory)
                - int(unlock.get("currentScheduleSafeAssets") or 0)
                - unlocked,
            ),
            "excludedRiskClasses": [
                "wrong_visual",
                "actual_visual_quality_failure",
                "wrong_visual_lineage",
                "aspect_ratio_failure",
                "duplicate_visual_failure",
                "audio_failure",
                "missing_burned_captions",
            ],
            "safeRepairsOnly": True,
            "reviewBatch": selected,
            "wouldWrite": False,
        }

    def operator_inventory_review_batch_summary(self, **kwargs: Any) -> dict[str, Any]:
        plan = self.operator_inventory_review_batch_plan(**kwargs)
        return {
            "schema": "creator_os.operator_inventory_review_batch_summary.v1",
            "creator": plan.get("creator"),
            "contentSurface": plan.get("contentSurface"),
            "targetUnlock": plan.get("targetUnlock"),
            "reviewCandidates": plan.get("reviewCandidates"),
            "recommendedReviewBatchSize": plan.get("recommendedReviewBatchSize"),
            "estimatedInventoryGain": plan.get("estimatedInventoryGain"),
            "estimatedOperatorMinutes": plan.get("estimatedOperatorMinutes"),
            "wouldPass25GateAfterBatch": plan.get("wouldPass25GateAfterBatch"),
            "remainingGapAfterBatch": plan.get("remainingGapAfterBatch"),
            "safeRepairsOnly": True,
            "wouldWrite": False,
        }

    def operator_review_simulator(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = "reel",
        required_inventory: int = 225,
        current_inventory: int | None = None,
        approval_rates: list[int] | None = None,
    ) -> dict[str, Any]:
        plan = self.operator_inventory_review_batch_plan(
            creator=creator,
            campaign_slug=campaign_slug,
            content_surface=content_surface,
            required_inventory=required_inventory,
            current_inventory=current_inventory,
        )
        ordered = self.operator_review_execution_order(plan.get("reviewBatch") or [])
        rates = approval_rates or [25, 50, 75, 90, 100]
        scenarios = [
            self.operator_review_scenario(
                ordered,
                current_inventory=int(plan.get("currentScheduleSafeAssets") or 0),
                required_inventory=int(required_inventory),
                approval_rate=int(rate),
            )
            for rate in rates
        ]
        minimum = self.operator_review_minimum_path(
            ordered,
            current_inventory=int(plan.get("currentScheduleSafeAssets") or 0),
            required_inventory=int(required_inventory),
        )
        return {
            "schema": "creator_os.operator_review_simulator.v1",
            "creator": creator,
            "campaign": campaign_slug,
            "contentSurface": self._normalize_content_surface(
                content_surface or "reel"
            ),
            "currentScheduleSafeAssets": int(
                plan.get("currentScheduleSafeAssets") or 0
            ),
            "requiredFor25Accounts": int(required_inventory),
            "shortfall": max(
                0,
                int(required_inventory)
                - int(plan.get("currentScheduleSafeAssets") or 0),
            ),
            "reviewCandidates": int(plan.get("reviewCandidates") or 0),
            "scenarios": scenarios,
            "minimumCertificationPath": minimum,
            "minimumAssetsReviewedToPass25Gate": int(
                minimum.get("minimumAssetsReviewedToPass25Gate") or 0
            ),
            "minimumOperatorMinutesToPass25Gate": int(
                minimum.get("minimumOperatorMinutesToPass25Gate") or 0
            ),
            "highestROIBatchType": self.operator_review_highest_roi_batch_type(ordered),
            "lowestRiskBatchType": self.operator_review_lowest_risk_batch_type(ordered),
            "recommendedExecutionOrder": self.operator_review_batch_order_labels(
                ordered
            ),
            "wouldWrite": False,
        }

    def operator_review_scenarios(self, **kwargs: Any) -> dict[str, Any]:
        report = self.operator_review_simulator(**kwargs)
        return {
            "schema": "creator_os.operator_review_scenarios.v1",
            "creator": report.get("creator"),
            "contentSurface": report.get("contentSurface"),
            "scenarios": report.get("scenarios"),
            "wouldWrite": False,
        }

    def operator_review_efficiency_report(self, **kwargs: Any) -> dict[str, Any]:
        report = self.operator_review_simulator(**kwargs)
        return {
            "schema": "creator_os.operator_review_efficiency_report.v1",
            "creator": report.get("creator"),
            "contentSurface": report.get("contentSurface"),
            "highestROIBatchType": report.get("highestROIBatchType"),
            "lowestRiskBatchType": report.get("lowestRiskBatchType"),
            "recommendedExecutionOrder": report.get("recommendedExecutionOrder"),
            "minimumCertificationPath": report.get("minimumCertificationPath"),
            "wouldWrite": False,
        }

    def operator_review_minimum_certification_path(
        self, **kwargs: Any
    ) -> dict[str, Any]:
        report = self.operator_review_simulator(**kwargs)
        return {
            "schema": "creator_os.operator_review_minimum_certification_path.v1",
            "creator": report.get("creator"),
            "contentSurface": report.get("contentSurface"),
            "minimumCertificationPath": report.get("minimumCertificationPath"),
            "minimumAssetsReviewedToPass25Gate": report.get(
                "minimumAssetsReviewedToPass25Gate"
            ),
            "minimumOperatorMinutesToPass25Gate": report.get(
                "minimumOperatorMinutesToPass25Gate"
            ),
            "wouldWrite": False,
        }

    def operator_review_master_report(self, **kwargs: Any) -> dict[str, Any]:
        report = self.operator_review_simulator(**kwargs)
        return {
            **report,
            "schema": "creator_os.operator_review_master_report.v1",
            "wouldWrite": False,
        }

    def operator_review_execution_order(
        self, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return sorted(
            rows,
            key=lambda row: (
                self.operator_review_batch_priority(row.get("repairClasses") or []),
                int(row.get("estimatedOperatorMinutes") or 0),
                str(row.get("assetId") or ""),
            ),
        )

    def operator_review_batch_priority(self, repair_classes: list[str]) -> int:
        classes = set(repair_classes)
        if classes == {"instagram_post_caption_quality_failed"}:
            return 0
        if classes <= {
            "instagram_post_caption_quality_failed",
            "discoverability_failure",
        }:
            return 1
        if classes <= {
            "instagram_post_caption_quality_failed",
            "operator_visual_review_required",
        }:
            return 2
        if "quarantined_asset" in classes:
            return 3
        return 4

    def operator_review_batch_type(self, repair_classes: list[str]) -> str:
        classes = set(repair_classes)
        if classes == {"instagram_post_caption_quality_failed"}:
            return "caption_only"
        if classes <= {
            "instagram_post_caption_quality_failed",
            "discoverability_failure",
        }:
            return "caption_discoverability"
        if classes <= {
            "instagram_post_caption_quality_failed",
            "operator_visual_review_required",
        }:
            return "caption_visual_review"
        if "quarantined_asset" in classes:
            return "quarantine_review"
        return "mixed_review"

    def operator_review_scenario(
        self,
        ordered_rows: list[dict[str, Any]],
        *,
        current_inventory: int,
        required_inventory: int,
        approval_rate: int,
    ) -> dict[str, Any]:
        reviewed = len(ordered_rows)
        recovered = min(
            reviewed, int(math.floor(reviewed * max(0, min(100, approval_rate)) / 100))
        )
        minutes = sum(
            int(row.get("estimatedOperatorMinutes") or 0) for row in ordered_rows
        )
        inventory = current_inventory + recovered
        return {
            "approvalRate": approval_rate,
            "assetsReviewed": reviewed,
            "assetsRecovered": recovered,
            "scheduleSafeInventory": inventory,
            "passes25AccountGate": inventory >= required_inventory,
            "operatorMinutes": minutes,
            "wouldWrite": False,
        }

    def operator_review_minimum_path(
        self,
        ordered_rows: list[dict[str, Any]],
        *,
        current_inventory: int,
        required_inventory: int,
    ) -> dict[str, Any]:
        needed = max(0, required_inventory - current_inventory)
        selected = ordered_rows[:needed]
        minutes = sum(int(row.get("estimatedOperatorMinutes") or 0) for row in selected)
        reviewed_by_type: dict[str, int] = {}
        for row in selected:
            batch_type = self.operator_review_batch_type(row.get("repairClasses") or [])
            reviewed_by_type[batch_type] = reviewed_by_type.get(batch_type, 0) + 1
        return {
            "minimumAssetsReviewedToPass25Gate": len(selected),
            "minimumOperatorMinutesToPass25Gate": minutes,
            "passes25Gate": current_inventory + len(selected) >= required_inventory,
            "assumedApprovalRate": 100,
            "reviewedByBatchType": reviewed_by_type,
            "wouldWrite": False,
        }

    def operator_review_highest_roi_batch_type(self, rows: list[dict[str, Any]]) -> str:
        by_type: dict[str, dict[str, int]] = {}
        for row in rows:
            batch_type = self.operator_review_batch_type(row.get("repairClasses") or [])
            bucket = by_type.setdefault(batch_type, {"gain": 0, "minutes": 0})
            bucket["gain"] += int(row.get("estimatedInventoryGain") or 0)
            bucket["minutes"] += int(row.get("estimatedOperatorMinutes") or 0)
        if not by_type:
            return ""
        return sorted(
            by_type,
            key=lambda key: (
                -(by_type[key]["gain"] / max(1, by_type[key]["minutes"])),
                key,
            ),
        )[0]

    def operator_review_lowest_risk_batch_type(self, rows: list[dict[str, Any]]) -> str:
        order = [
            "caption_only",
            "caption_discoverability",
            "caption_visual_review",
            "quarantine_review",
            "mixed_review",
        ]
        present = {
            self.operator_review_batch_type(row.get("repairClasses") or [])
            for row in rows
        }
        return next((item for item in order if item in present), "")

    def operator_review_batch_order_labels(
        self, rows: list[dict[str, Any]]
    ) -> list[str]:
        order = []
        for row in rows:
            label = self.operator_review_batch_type(row.get("repairClasses") or [])
            if label not in order:
                order.append(label)
        return order

    def operator_review_candidate_eligible(self, asset: dict[str, Any]) -> bool:
        classes = set(asset.get("repairClasses") or [])
        if not classes:
            return False
        excluded = {
            "wrong_visual",
            "audio_failure",
            "missing_burned_captions",
            "manifest_failure",
            "metadata_failure",
        }
        if classes & excluded:
            return False
        if asset.get("unrepairableBlockers"):
            return False
        return classes.issubset(
            {
                "operator_visual_review_required",
                "instagram_post_caption_quality_failed",
                "discoverability_failure",
                "caption_placement_qc_failed",
                "quarantined_asset",
            }
        )

    def operator_review_candidate_row(self, asset: dict[str, Any]) -> dict[str, Any]:
        classes = list(asset.get("repairClasses") or [])
        minutes = sum(int(self._repair_minutes.get(item, 10)) for item in classes)
        return {
            "assetId": asset.get("assetId") or "",
            "blockers": asset.get("blockers") or [],
            "repairClasses": classes,
            "repairClassCount": len(classes),
            "recommendedActions": self.operator_review_actions(classes),
            "estimatedInventoryGain": 1,
            "estimatedOperatorMinutes": minutes,
            "safeRepairsOnly": True,
            "wouldWrite": False,
        }

    def operator_review_actions(self, repair_classes: list[str]) -> list[str]:
        actions = []
        if "operator_visual_review_required" in repair_classes:
            actions.append("operator_visual_review")
        if "quarantined_asset" in repair_classes:
            actions.append("review_quarantine_reason_do_not_clear_if_visual_risk")
        if "instagram_post_caption_quality_failed" in repair_classes:
            actions.append("replace_with_simple_safe_instagram_post_caption")
        if "discoverability_failure" in repair_classes:
            actions.append("remove_dm_link_or_platform_risk_language")
        if "caption_placement_qc_failed" in repair_classes:
            actions.append("rerun_caption_placement_qc_or_reject_if_text_overlaps")
        return actions
