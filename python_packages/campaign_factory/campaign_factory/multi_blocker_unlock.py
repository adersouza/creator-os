from __future__ import annotations

import sqlite3
from itertools import combinations
from typing import Any, Callable


class MultiBlockerUnlockRepository:
    MULTI_BLOCKER_REPAIR_CLASSES = (
        "operator_visual_review_required",
        "instagram_post_caption_quality_failed",
        "caption_placement_qc_failed",
        "discoverability_failure",
        "manifest_failure",
        "metadata_failure",
        "quarantined_asset",
        "wrong_visual",
        "missing_burned_captions",
        "audio_failure",
    )
    MULTI_BLOCKER_REPAIR_MINUTES = {
        "operator_visual_review_required": 3,
        "instagram_post_caption_quality_failed": 2,
        "caption_placement_qc_failed": 6,
        "discoverability_failure": 3,
        "manifest_failure": 5,
        "metadata_failure": 4,
        "quarantined_asset": 5,
        "wrong_visual": 10,
        "missing_burned_captions": 8,
        "audio_failure": 12,
    }
    MULTI_BLOCKER_REPAIR_DIFFICULTY = {
        "operator_visual_review_required": "low",
        "instagram_post_caption_quality_failed": "low",
        "caption_placement_qc_failed": "medium",
        "discoverability_failure": "low",
        "manifest_failure": "low",
        "metadata_failure": "low",
        "quarantined_asset": "medium",
        "wrong_visual": "high",
        "missing_burned_captions": "medium",
        "audio_failure": "medium",
    }

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        normalize_content_surface: Callable[[str | None], str],
        surface_report_assets: Callable[..., list[dict[str, Any]]],
        build_surface_readiness: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    ) -> None:
        self.conn = conn
        self._normalize_content_surface = normalize_content_surface
        self._surface_report_assets = surface_report_assets
        self._build_surface_readiness = build_surface_readiness

    def multi_blocker_inventory_unlock_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = "reel",
        required_inventory: int = 225,
        current_inventory: int | None = None,
    ) -> dict[str, Any]:
        surface = self._normalize_content_surface(content_surface or "reel")
        assets = self._surface_report_assets(creator=creator, campaign_slug=campaign_slug)
        assets = [
            asset for asset in assets
            if self._normalize_content_surface(asset.get("content_surface") or asset.get("source_content_surface")) == surface
        ]
        readiness = self._build_surface_readiness(assets)
        current = int(current_inventory) if current_inventory is not None else sum(1 for item in readiness if item.get("canHandoff"))
        blocked = [self.multi_blocker_asset_row(item) for item in readiness if not item.get("canHandoff")]
        combo_rows = self.multi_blocker_combo_rows(blocked, current_inventory=current, required_inventory=required_inventory)
        best_single = self.multi_blocker_best_combo(combo_rows, 1)
        best_two = self.multi_blocker_best_combo(combo_rows, 2)
        best_three = self.multi_blocker_best_combo(combo_rows, 3)
        minimal = self.multi_blocker_minimal_fix_set(combo_rows, current_inventory=current, required_inventory=required_inventory)
        all_repairable_gain = self.multi_blocker_assets_unlocked(blocked, list(self.MULTI_BLOCKER_REPAIR_CLASSES))
        still_needs = current + int(minimal.get("assetsUnlocked") or 0) < int(required_inventory)
        new_required = max(0, int(required_inventory) - current - all_repairable_gain)
        return {
            "schema": "creator_os.multi_blocker_inventory_unlock_report.v1",
            "creator": creator,
            "campaign": campaign_slug,
            "contentSurface": surface,
            "currentScheduleSafeAssets": current,
            "requiredFor25Accounts": int(required_inventory),
            "shortfall": max(0, int(required_inventory) - current),
            "blockedAssetCount": len(blocked),
            "blockedAssets": blocked,
            "repairCombinations": combo_rows,
            "bestSingleRepair": {
                "repairClass": (best_single.get("repairClasses") or [""])[0] if best_single else "",
                "assetsUnlocked": int(best_single.get("assetsUnlocked") or 0) if best_single else 0,
            },
            "bestTwoRepairCombo": {
                "repairClasses": best_two.get("repairClasses") or [],
                "assetsUnlocked": int(best_two.get("assetsUnlocked") or 0) if best_two else 0,
            },
            "bestThreeRepairCombo": {
                "repairClasses": best_three.get("repairClasses") or [],
                "assetsUnlocked": int(best_three.get("assetsUnlocked") or 0) if best_three else 0,
            },
            "minimalFixSetFor25Accounts": minimal,
            "stillNeedsNewProduction": still_needs,
            "newProductionAssetsRequired": new_required,
            "successCriteria": {
                "canDetermineCombinedRepairViability": True,
                "canIdentifyMinimalFixSet": True,
                "canDecideRepairVsNewProduction": True,
            },
            "wouldWrite": False,
        }

    def multi_blocker_inventory_unlock_plan(self, **kwargs: Any) -> dict[str, Any]:
        report = self.multi_blocker_inventory_unlock_report(**kwargs)
        return {
            "schema": "creator_os.multi_blocker_inventory_unlock_plan.v1",
            "creator": report.get("creator"),
            "contentSurface": report.get("contentSurface"),
            "bestSingleRepair": report.get("bestSingleRepair"),
            "bestTwoRepairCombo": report.get("bestTwoRepairCombo"),
            "bestThreeRepairCombo": report.get("bestThreeRepairCombo"),
            "minimalFixSetFor25Accounts": report.get("minimalFixSetFor25Accounts"),
            "stillNeedsNewProduction": report.get("stillNeedsNewProduction"),
            "newProductionAssetsRequired": report.get("newProductionAssetsRequired"),
            "wouldWrite": False,
        }

    def inventory_unlock_minimal_fix_set(self, **kwargs: Any) -> dict[str, Any]:
        report = self.multi_blocker_inventory_unlock_report(**kwargs)
        return {
            "schema": "creator_os.inventory_unlock_minimal_fix_set.v1",
            "creator": report.get("creator"),
            "contentSurface": report.get("contentSurface"),
            "currentScheduleSafeAssets": report.get("currentScheduleSafeAssets"),
            "requiredFor25Accounts": report.get("requiredFor25Accounts"),
            "minimalFixSetFor25Accounts": report.get("minimalFixSetFor25Accounts"),
            "stillNeedsNewProduction": report.get("stillNeedsNewProduction"),
            "newProductionAssetsRequired": report.get("newProductionAssetsRequired"),
            "wouldWrite": False,
        }

    def inventory_unlock_master_report(self, **kwargs: Any) -> dict[str, Any]:
        report = self.multi_blocker_inventory_unlock_report(**kwargs)
        return {
            **report,
            "schema": "creator_os.inventory_unlock_master_report.v1",
            "wouldWrite": False,
        }

    def multi_blocker_asset_row(self, readiness: dict[str, Any]) -> dict[str, Any]:
        blockers = sorted({str(reason).replace("publishability:", "") for reason in readiness.get("blockingReasons") or []})
        if len(blockers) > 1 and "handoff_manifest_missing" in blockers:
            blockers = [reason for reason in blockers if reason != "handoff_manifest_missing"]
        repair_classes = sorted({
            repair_class for repair_class in (self.multi_blocker_repair_class(reason) for reason in blockers)
            if repair_class
        })
        unrepairable = [reason for reason in blockers if not self.multi_blocker_repair_class(reason)]
        return {
            "assetId": readiness.get("assetId") or "",
            "blockers": blockers,
            "repairClasses": repair_classes,
            "unrepairableBlockers": unrepairable,
            "wouldBecomeScheduleSafeIfFixed": repair_classes if repair_classes and not unrepairable else [],
            "wouldWrite": False,
        }

    def multi_blocker_repair_class(self, reason: str) -> str:
        lowered = reason.lower()
        if "operator_visual_review_required" in lowered:
            return "operator_visual_review_required"
        if "instagram_post_caption_quality_failed" in lowered or "missing_instagram_post_caption" in lowered or "instagram_post_caption_missing" in lowered:
            return "instagram_post_caption_quality_failed"
        if "caption_placement" in lowered:
            return "caption_placement_qc_failed"
        if "discoverability" in lowered or "unsafe_reel_caption" in lowered or "dm" in lowered or "link" in lowered:
            return "discoverability_failure"
        if "manifest" in lowered or "handoff" in lowered:
            return "manifest_failure"
        if "metadata" in lowered or "fingerprint" in lowered or "content_hash" in lowered or "caption_hash" in lowered or "caption_outcome_context" in lowered:
            return "metadata_failure"
        if "quarantined" in lowered:
            return "quarantined_asset"
        if "wrong_visual" in lowered or "visual_quality" in lowered or "story_quality" in lowered or "head_cutoff" in lowered:
            return "wrong_visual"
        if "missing_burned" in lowered:
            return "missing_burned_captions"
        if "audio" in lowered or "embedded_audio" in lowered or "missing_audio" in lowered:
            return "audio_failure"
        return ""

    def multi_blocker_combo_rows(
        self,
        blocked_assets: list[dict[str, Any]],
        *,
        current_inventory: int,
        required_inventory: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        classes = list(self.MULTI_BLOCKER_REPAIR_CLASSES)
        for size in range(1, len(classes) + 1):
            for combo in combinations(classes, size):
                combo_list = list(combo)
                assets_unlocked = self.multi_blocker_assets_unlocked(blocked_assets, combo_list)
                minutes = self.multi_blocker_estimated_minutes(blocked_assets, combo_list)
                rows.append({
                    "repairCombo": combo_list,
                    "repairClasses": combo_list,
                    "assetsUnlocked": assets_unlocked,
                    "estimatedOperatorMinutes": minutes,
                    "repairDifficulty": self.multi_blocker_combo_difficulty(combo_list),
                    "remainingShortfall": max(0, int(required_inventory) - int(current_inventory) - assets_unlocked),
                    "wouldPass25Gate": int(current_inventory) + assets_unlocked >= int(required_inventory),
                    "wouldWrite": False,
                })
        return sorted(
            rows,
            key=lambda row: (
                len(row["repairClasses"]),
                -int(row["assetsUnlocked"]),
                int(row["estimatedOperatorMinutes"]),
                row["repairClasses"],
            ),
        )

    def multi_blocker_assets_unlocked(self, blocked_assets: list[dict[str, Any]], repair_classes: list[str]) -> int:
        selected = {item for item in repair_classes if item}
        if not selected:
            return 0
        return sum(
            1 for asset in blocked_assets
            if asset.get("wouldBecomeScheduleSafeIfFixed")
            and set(asset.get("repairClasses") or []).issubset(selected)
        )

    def multi_blocker_estimated_minutes(self, blocked_assets: list[dict[str, Any]], repair_classes: list[str]) -> int:
        total = 0
        for repair_class in repair_classes:
            impacted = sum(1 for asset in blocked_assets if repair_class in set(asset.get("repairClasses") or []))
            total += impacted * int(self.MULTI_BLOCKER_REPAIR_MINUTES.get(repair_class, 10))
        return total

    def multi_blocker_combo_difficulty(self, repair_classes: list[str]) -> str:
        weights = {"low": 1, "medium": 2, "high": 3}
        worst = max((weights.get(self.MULTI_BLOCKER_REPAIR_DIFFICULTY.get(item, "high"), 3) for item in repair_classes), default=1)
        return {1: "low", 2: "medium", 3: "high"}.get(worst, "high")

    def multi_blocker_best_combo(self, combo_rows: list[dict[str, Any]], size: int) -> dict[str, Any]:
        candidates = [row for row in combo_rows if len(row.get("repairClasses") or []) == size]
        if not candidates:
            return {}
        return sorted(
            candidates,
            key=lambda row: (-int(row.get("assetsUnlocked") or 0), int(row.get("estimatedOperatorMinutes") or 0), row.get("repairClasses") or []),
        )[0]

    def multi_blocker_minimal_fix_set(
        self,
        combo_rows: list[dict[str, Any]],
        *,
        current_inventory: int,
        required_inventory: int,
    ) -> dict[str, Any]:
        passing = [row for row in combo_rows if row.get("wouldPass25Gate")]
        if passing:
            selected = sorted(
                passing,
                key=lambda row: (len(row.get("repairClasses") or []), int(row.get("estimatedOperatorMinutes") or 0), -int(row.get("assetsUnlocked") or 0)),
            )[0]
        else:
            selected = sorted(
                combo_rows,
                key=lambda row: (-int(row.get("assetsUnlocked") or 0), len(row.get("repairClasses") or []), int(row.get("estimatedOperatorMinutes") or 0)),
            )[0] if combo_rows else {}
        return {
            "repairClasses": selected.get("repairClasses") or [],
            "assetsUnlocked": int(selected.get("assetsUnlocked") or 0),
            "estimatedOperatorMinutes": int(selected.get("estimatedOperatorMinutes") or 0),
            "remainingShortfall": max(0, int(required_inventory) - int(current_inventory) - int(selected.get("assetsUnlocked") or 0)),
            "wouldPass25Gate": bool(selected.get("wouldPass25Gate")),
            "wouldWrite": False,
        }
