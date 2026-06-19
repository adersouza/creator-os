from __future__ import annotations

import sqlite3
from typing import Any, Callable


class InventoryRecoveryRepository:
    INVENTORY_RECOVERY_CLASSES: tuple[str, ...] = (
        "caption_only",
        "caption_placement_qc",
        "missing_burned_captions",
        "operator_visual_review_required",
        "quarantined_asset",
        "wrong_visual",
        "audio_failure",
        "manifest_failure",
        "metadata_failure",
        "discoverability_failure",
        "other",
    )
    INVENTORY_RECOVERY_MINUTES = {
        "caption_only": 2,
        "caption_placement_qc": 6,
        "missing_burned_captions": 8,
        "operator_visual_review_required": 3,
        "quarantined_asset": 5,
        "wrong_visual": 10,
        "audio_failure": 12,
        "manifest_failure": 5,
        "metadata_failure": 4,
        "discoverability_failure": 3,
        "other": 10,
    }
    INVENTORY_RECOVERY_DIFFICULTY = {
        "caption_only": "low",
        "caption_placement_qc": "medium",
        "missing_burned_captions": "medium",
        "operator_visual_review_required": "low",
        "quarantined_asset": "medium",
        "wrong_visual": "high",
        "audio_failure": "medium",
        "manifest_failure": "low",
        "metadata_failure": "low",
        "discoverability_failure": "low",
        "other": "high",
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

    def inventory_recovery_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = None,
        required_inventory: int | None = None,
        account_target: int = 25,
        posts_per_account_per_day: int = 3,
        buffer_days: int = 3,
    ) -> dict[str, Any]:
        assets = self._surface_report_assets(creator=creator, campaign_slug=campaign_slug)
        surface = self._normalize_content_surface(content_surface) if content_surface else None
        if surface:
            assets = [
                asset for asset in assets
                if self._normalize_content_surface(asset.get("content_surface") or asset.get("source_content_surface")) == surface
            ]
        readiness = self._build_surface_readiness(assets)
        ready_assets = [item for item in readiness if item.get("canHandoff")]
        blocked_assets = [item for item in readiness if not item.get("canHandoff")]
        required = int(required_inventory) if required_inventory is not None else max(1, int(account_target or 25)) * max(0, int(posts_per_account_per_day or 3)) * max(1, int(buffer_days or 3))
        blocked_rows = [self.inventory_recovery_blocked_asset(item) for item in blocked_assets]
        class_rows = self.inventory_recovery_class_rows(blocked_rows)
        priorities = self.inventory_recovery_priorities(class_rows)
        top = priorities[0] if priorities else {}
        top3_classes = [item["repairClass"] for item in priorities[:3]]
        top_recovered = self.inventory_recovery_assets_unlocked(blocked_rows, [str(top.get("repairClass") or "")])
        top3_recovered = self.inventory_recovery_assets_unlocked(blocked_rows, top3_classes)
        current_inventory = len(ready_assets)
        return {
            "schema": "creator_os.inventory_recovery_report.v1",
            "creator": creator,
            "campaign": campaign_slug,
            "contentSurface": surface or "all",
            "currentScheduleSafeAssets": current_inventory,
            "requiredFor25Accounts": required,
            "requiredInventory": required,
            "shortfall": max(0, required - current_inventory),
            "blockedAssetCount": len(blocked_rows),
            "blockedAssets": blocked_rows,
            "repairClasses": class_rows,
            "priorityRanking": priorities,
            "highestROIRepairClass": top.get("repairClass") or "",
            "highestROI": {
                "highestROIRepairClass": top.get("repairClass") or "",
                "recoverableAssets": top.get("scheduleSafeAssetsRecoverable", 0),
                "estimatedInventoryGain": top.get("estimatedInventoryGain", 0),
                "estimatedOperatorMinutes": top.get("estimatedOperatorMinutes", 0),
            },
            "inventoryGateImpact": {
                "currentScheduleSafeAssets": current_inventory,
                "requiredFor25Accounts": required,
                "shortfall": max(0, required - current_inventory),
                "inventoryAfterTopRepair": current_inventory + top_recovered,
                "inventoryAfterTop3Repairs": current_inventory + top3_recovered,
                "wouldPass25AccountGate": current_inventory + top3_recovered >= required,
            },
            "successCriteria": {
                "whyAssetsAreBlocked": True,
                "whichRepairClassUnlocksMostInventory": bool(priorities),
                "howManyAssetsEachRepairWouldRecover": True,
                "whatGetsUsTo25AccountsFastest": True,
            },
            "wouldWrite": False,
        }

    def inventory_recovery_priority_report(self, **kwargs: Any) -> dict[str, Any]:
        report = self.inventory_recovery_report(**kwargs)
        return {
            "schema": "creator_os.inventory_recovery_priority_report.v1",
            "creator": report.get("creator"),
            "contentSurface": report.get("contentSurface"),
            "highestROI": report.get("highestROI"),
            "priorityRanking": report.get("priorityRanking"),
            "inventoryGateImpact": report.get("inventoryGateImpact"),
            "wouldWrite": False,
        }

    def inventory_recovery_by_blocker(self, **kwargs: Any) -> dict[str, Any]:
        report = self.inventory_recovery_report(**kwargs)
        return {
            "schema": "creator_os.inventory_recovery_by_blocker.v1",
            "creator": report.get("creator"),
            "contentSurface": report.get("contentSurface"),
            "repairClasses": report.get("repairClasses"),
            "blockedAssetCount": report.get("blockedAssetCount"),
            "wouldWrite": False,
        }

    def inventory_recovery_master_report(self, **kwargs: Any) -> dict[str, Any]:
        report = self.inventory_recovery_report(**kwargs)
        return {
            "schema": "creator_os.inventory_recovery_master_report.v1",
            **report,
            "wouldWrite": False,
        }

    def inventory_recovery_blocked_asset(self, readiness: dict[str, Any]) -> dict[str, Any]:
        blockers = sorted({str(reason).replace("publishability:", "") for reason in readiness.get("blockingReasons") or []})
        if len(blockers) > 1 and "handoff_manifest_missing" in blockers:
            blockers = [reason for reason in blockers if reason != "handoff_manifest_missing"]
        classes = sorted({self.inventory_recovery_class_for_blocker(reason) for reason in blockers})
        return {
            "assetId": readiness.get("assetId") or "",
            "contentSurface": readiness.get("contentSurface") or "",
            "blockingReasons": blockers,
            "repairClasses": classes or ["other"],
            "wouldWrite": False,
        }

    def inventory_recovery_class_for_blocker(self, reason: str) -> str:
        lowered = reason.lower()
        if any(token in lowered for token in ("instagram_post_caption_quality_failed", "missing_instagram_post_caption", "instagram_post_caption_missing")):
            return "caption_only"
        if "caption_placement" in lowered:
            return "caption_placement_qc"
        if "missing_burned" in lowered or "missing_burned_captions" in lowered:
            return "missing_burned_captions"
        if "operator_visual_review_required" in lowered:
            return "operator_visual_review_required"
        if "quarantined" in lowered:
            return "quarantined_asset"
        if "wrong_visual" in lowered or "visual_quality" in lowered or "story_quality" in lowered or "head_cutoff" in lowered:
            return "wrong_visual"
        if "audio" in lowered or "embedded_audio" in lowered or "missing_audio" in lowered:
            return "audio_failure"
        if "manifest" in lowered or "handoff" in lowered:
            return "manifest_failure"
        if "metadata" in lowered or "fingerprint" in lowered or "content_hash" in lowered or "caption_hash" in lowered or "caption_outcome_context" in lowered:
            return "metadata_failure"
        if "discoverability" in lowered or "dm" in lowered or "link" in lowered:
            return "discoverability_failure"
        return "other"

    def inventory_recovery_class_rows(self, blocked_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        total = len(blocked_assets)
        rows: list[dict[str, Any]] = []
        for repair_class in self.INVENTORY_RECOVERY_CLASSES:
            assets_with_class = [asset for asset in blocked_assets if repair_class in set(asset.get("repairClasses") or [])]
            unlocked = self.inventory_recovery_assets_unlocked(blocked_assets, [repair_class])
            minutes_per_asset = self.INVENTORY_RECOVERY_MINUTES[repair_class]
            rows.append({
                "repairClass": repair_class,
                "blockedAssets": len(assets_with_class),
                "repairableAssets": len(assets_with_class),
                "scheduleSafeAssetsRecoverable": unlocked,
                "percentOfTotalBlockedInventory": round((len(assets_with_class) / total) * 100, 1) if total else 0,
                "estimatedOperatorMinutes": len(assets_with_class) * minutes_per_asset,
                "estimatedMinutesPerAsset": minutes_per_asset,
                "repairDifficulty": self.INVENTORY_RECOVERY_DIFFICULTY[repair_class],
                "wouldWrite": False,
            })
        return rows

    def inventory_recovery_assets_unlocked(self, blocked_assets: list[dict[str, Any]], repaired_classes: list[str]) -> int:
        repaired = {item for item in repaired_classes if item}
        if not repaired:
            return 0
        return sum(
            1 for asset in blocked_assets
            if set(asset.get("repairClasses") or []) and set(asset.get("repairClasses") or []).issubset(repaired)
        )

    def inventory_recovery_priorities(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        difficulty_weight = {"low": 1, "medium": 2, "high": 3}
        ranked = []
        for row in rows:
            minutes = max(1, int(row.get("estimatedOperatorMinutes") or 0))
            gain = int(row.get("scheduleSafeAssetsRecoverable") or 0)
            blocked = int(row.get("blockedAssets") or 0)
            difficulty = str(row.get("repairDifficulty") or "high")
            score = round(((gain * 100) + blocked) / (minutes * difficulty_weight.get(difficulty, 3)), 4)
            ranked.append({
                **row,
                "estimatedInventoryGain": gain,
                "roiScore": score,
            })
        return sorted(
            ranked,
            key=lambda item: (
                -int(item.get("estimatedInventoryGain") or 0),
                -float(item.get("roiScore") or 0),
                int(item.get("estimatedOperatorMinutes") or 0),
                str(item.get("repairClass") or ""),
            ),
        )
