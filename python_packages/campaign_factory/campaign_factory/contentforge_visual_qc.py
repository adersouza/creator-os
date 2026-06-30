from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any


class ContentForgeVisualQCRepository:
    CONTENTFORGE_VISUAL_QC_CATEGORIES = (
        "actual_visual_quality_failure",
        "visual_metadata_missing",
        "operator_visual_review_required",
        "wrong_visual_lineage",
        "caption_placement_failure",
        "safe_zone_failure",
        "readability_failure",
        "aspect_ratio_failure",
        "duplicate_visual_failure",
        "proof_asset_only",
        "trial_asset_only",
        "unknown",
    )
    CONTENTFORGE_VISUAL_QC_MINUTES = {
        "actual_visual_quality_failure": 10,
        "visual_metadata_missing": 4,
        "operator_visual_review_required": 3,
        "wrong_visual_lineage": 10,
        "caption_placement_failure": 6,
        "safe_zone_failure": 8,
        "readability_failure": 6,
        "aspect_ratio_failure": 8,
        "duplicate_visual_failure": 5,
        "proof_asset_only": 2,
        "trial_asset_only": 2,
        "unknown": 10,
    }
    CONTENTFORGE_VISUAL_QC_REPAIRABLE = {
        "actual_visual_quality_failure": False,
        "visual_metadata_missing": True,
        "operator_visual_review_required": True,
        "wrong_visual_lineage": False,
        "caption_placement_failure": True,
        "safe_zone_failure": True,
        "readability_failure": True,
        "aspect_ratio_failure": False,
        "duplicate_visual_failure": False,
        "proof_asset_only": True,
        "trial_asset_only": True,
        "unknown": False,
    }

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        normalize_content_surface: Callable[[str | None], str],
        schedule_safe_production_assets: Callable[..., list[dict[str, Any]]],
        schedule_safe_is_variant_asset: Callable[[dict[str, Any]], bool],
        surface_report_assets: Callable[..., list[dict[str, Any]]],
        build_surface_readiness: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        surface_handoff_readiness_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        explain_publishability: Callable[[str], dict[str, Any]],
    ) -> None:
        self.conn = conn
        self._normalize_content_surface = normalize_content_surface
        self._schedule_safe_production_assets = schedule_safe_production_assets
        self._schedule_safe_is_variant_asset = schedule_safe_is_variant_asset
        self._surface_report_assets = surface_report_assets
        self._build_surface_readiness = build_surface_readiness
        self._surface_handoff_readiness_for_asset = surface_handoff_readiness_for_asset
        self._explain_publishability = explain_publishability

    def contentforge_visual_qc_failure_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = "reel",
        lookback_days: int = 1,
        current_inventory: int | None = None,
        required_inventory: int = 225,
    ) -> dict[str, Any]:
        surface = self._normalize_content_surface(content_surface or "reel")
        assets = self._schedule_safe_production_assets(
            creator=creator,
            campaign_slug=campaign_slug,
            content_surface=surface,
            lookback_days=lookback_days,
        )
        variants = [
            asset for asset in assets if self._schedule_safe_is_variant_asset(asset)
        ]
        failures = [
            self.contentforge_visual_qc_failure_for_asset(asset, surface)
            for asset in variants
        ]
        visual_failures = [
            failure for failure in failures if not failure["visualQcPassed"]
        ]
        categories = self.contentforge_visual_qc_category_rows(visual_failures)
        ranked = sorted(
            categories,
            key=lambda row: (
                -int(row.get("estimatedInventoryGain") or 0),
                -int(row.get("count") or 0),
                int(row.get("estimatedOperatorMinutes") or 0),
                str(row.get("failureCategory") or ""),
            ),
        )
        top = (
            ranked[0]
            if ranked
            else {
                "failureCategory": "",
                "count": 0,
                "repairable": False,
                "estimatedInventoryGain": 0,
            }
        )
        top3 = [row["failureCategory"] for row in ranked[:3]]
        all_surface_assets = self._surface_report_assets(
            creator=creator, campaign_slug=campaign_slug
        )
        all_surface_assets = [
            asset
            for asset in all_surface_assets
            if self._normalize_content_surface(
                asset.get("content_surface") or asset.get("source_content_surface")
            )
            == surface
        ]
        current = (
            int(current_inventory)
            if current_inventory is not None
            else sum(
                1
                for item in self._build_surface_readiness(all_surface_assets)
                if item.get("canHandoff")
            )
        )
        top_gain = self.contentforge_visual_qc_recovered_inventory(
            visual_failures, [str(top.get("failureCategory") or "")]
        )
        top3_gain = self.contentforge_visual_qc_recovered_inventory(
            visual_failures, top3
        )
        return {
            "schema": "creator_os.contentforge_visual_qc_failure_report.v1",
            "creator": creator,
            "campaign": campaign_slug,
            "contentSurface": surface,
            "lookbackDays": max(1, int(lookback_days or 1)),
            "freshProductionOnly": True,
            "variantsAnalyzed": len(variants),
            "visualQcPassed": len(variants) - len(visual_failures),
            "visualQcFailed": len(visual_failures),
            "failedVariants": visual_failures,
            "failureCategories": categories,
            "largestVisualQCLoss": {
                "largestFailureCategory": top.get("failureCategory") or "",
                "count": int(top.get("count") or 0),
                "repairable": bool(top.get("repairable")),
                "estimatedInventoryGain": int(top.get("estimatedInventoryGain") or 0),
            },
            "recoveryProjection": {
                "currentScheduleSafeAssets": current,
                "inventoryRecoveredIfTopVisualIssueFixed": top_gain,
                "inventoryRecoveredIfTop3VisualIssuesFixed": top3_gain,
                "requiredFor25Accounts": int(required_inventory),
                "remainingGap": max(0, int(required_inventory) - (current + top_gain)),
            },
            "mostImportantAnswer": self.contentforge_visual_qc_answer(
                top, len(visual_failures)
            ),
            "wouldWrite": False,
        }

    def contentforge_visual_qc_waterfall(self, **kwargs: Any) -> dict[str, Any]:
        report = self.contentforge_visual_qc_failure_report(**kwargs)
        failed = list(report.get("failedVariants") or [])
        waterfall = {
            "variantsCreated": int(report.get("variantsAnalyzed") or 0),
            "visualQcPassed": int(report.get("visualQcPassed") or 0),
            "visualQcFailed": int(report.get("visualQcFailed") or 0),
            "operatorReviewRequired": sum(
                1
                for item in failed
                if item.get("failureCategory") == "operator_visual_review_required"
            ),
            "metadataFailures": sum(
                1
                for item in failed
                if item.get("failureCategory") == "visual_metadata_missing"
            ),
            "trueVisualFailures": sum(
                1
                for item in failed
                if item.get("failureCategory") == "actual_visual_quality_failure"
            ),
            "lineageFailures": sum(
                1
                for item in failed
                if item.get("failureCategory") == "wrong_visual_lineage"
            ),
            "captionPlacementFailures": sum(
                1
                for item in failed
                if item.get("failureCategory") == "caption_placement_failure"
            ),
        }
        return {
            "schema": "creator_os.contentforge_visual_qc_waterfall.v1",
            "creator": report.get("creator"),
            "contentSurface": report.get("contentSurface"),
            "lookbackDays": report.get("lookbackDays"),
            "waterfall": waterfall,
            "wouldWrite": False,
        }

    def contentforge_visual_qc_loss_analysis(self, **kwargs: Any) -> dict[str, Any]:
        report = self.contentforge_visual_qc_failure_report(**kwargs)
        ranked = sorted(
            report.get("failureCategories") or [],
            key=lambda row: (
                -int(row.get("count") or 0),
                -int(row.get("estimatedInventoryGain") or 0),
                str(row.get("failureCategory") or ""),
            ),
        )
        return {
            "schema": "creator_os.contentforge_visual_qc_loss_analysis.v1",
            "creator": report.get("creator"),
            "contentSurface": report.get("contentSurface"),
            "largestVisualQCLoss": report.get("largestVisualQCLoss"),
            "rankedFailureCategories": ranked,
            "mostImportantAnswer": report.get("mostImportantAnswer"),
            "wouldWrite": False,
        }

    def contentforge_visual_qc_repair_plan(self, **kwargs: Any) -> dict[str, Any]:
        report = self.contentforge_visual_qc_failure_report(**kwargs)
        repairable = [
            row
            for row in report.get("failureCategories") or []
            if row.get("repairable") and int(row.get("count") or 0) > 0
        ]
        return {
            "schema": "creator_os.contentforge_visual_qc_repair_plan.v1",
            "creator": report.get("creator"),
            "contentSurface": report.get("contentSurface"),
            "repairActions": sorted(
                repairable,
                key=lambda row: (
                    -int(row.get("estimatedInventoryGain") or 0),
                    int(row.get("estimatedOperatorMinutes") or 0),
                    str(row.get("failureCategory") or ""),
                ),
            ),
            "recoveryProjection": report.get("recoveryProjection"),
            "wouldWrite": False,
        }

    def contentforge_visual_qc_master_report(self, **kwargs: Any) -> dict[str, Any]:
        report = self.contentforge_visual_qc_failure_report(**kwargs)
        waterfall = self.contentforge_visual_qc_waterfall(**kwargs)
        loss = self.contentforge_visual_qc_loss_analysis(**kwargs)
        repair = self.contentforge_visual_qc_repair_plan(**kwargs)
        return {
            **report,
            "schema": "creator_os.contentforge_visual_qc_master_report.v1",
            "visualQcWaterfall": waterfall.get("waterfall"),
            "lossAnalysis": loss.get("rankedFailureCategories"),
            "repairPlan": repair.get("repairActions"),
            "wouldWrite": False,
        }

    def contentforge_visual_qc_failure_for_asset(
        self, asset: dict[str, Any], surface: str
    ) -> dict[str, Any]:
        readiness = self._surface_handoff_readiness_for_asset(asset)
        publishability = (
            self._explain_publishability(str(asset["id"])) if surface == "reel" else {}
        )
        checks = (
            publishability.get("checks")
            if isinstance(publishability.get("checks"), dict)
            else {}
        )
        blockers = sorted(
            {
                str(reason).replace("publishability:", "")
                for reason in list(readiness.get("blockingReasons") or [])
                + list(publishability.get("publishability_failure_reasons") or [])
            }
        )
        visual_passed = bool(
            checks.get(
                "operator_visual_review_passed",
                "operator_visual_review_required" not in blockers,
            )
        )
        category = (
            ""
            if visual_passed
            else self.contentforge_visual_qc_failure_category(
                asset, blockers, readiness, publishability
            )
        )
        non_visual_blockers = [
            blocker
            for blocker in blockers
            if self.contentforge_visual_qc_failure_category(
                asset, [blocker], readiness, publishability
            )
            != category
        ]
        inventory_gain = (
            1
            if category
            and self.CONTENTFORGE_VISUAL_QC_REPAIRABLE.get(category, False)
            and self.contentforge_non_visual_gates_pass(
                checks, readiness, publishability, non_visual_blockers
            )
            else 0
        )
        return {
            "assetId": asset["id"],
            "variantId": asset.get("variant_id") or "",
            "parentAssetId": asset.get("parent_asset_id") or "",
            "visualQcPassed": visual_passed,
            "failureCategory": category,
            "blockingReasons": blockers,
            "nonVisualBlockers": non_visual_blockers,
            "repairable": bool(
                self.CONTENTFORGE_VISUAL_QC_REPAIRABLE.get(category, False)
            ),
            "estimatedInventoryGain": inventory_gain,
            "wouldWrite": False,
        }

    def contentforge_visual_qc_failure_category(
        self,
        asset: dict[str, Any],
        blockers: list[str],
        readiness: dict[str, Any],
        publishability: dict[str, Any],
    ) -> str:
        text = " ".join(
            blockers
            + [
                str(asset.get("filename") or ""),
                str(asset.get("campaign_slug") or ""),
                str(asset.get("recipe") or ""),
                str(asset.get("output_path") or ""),
            ]
        ).lower()
        if "operator_visual_review_required" in text:
            return "operator_visual_review_required"
        if any(token in text for token in ("caption_placement", "caption placement")):
            return "caption_placement_failure"
        if any(token in text for token in ("safe_zone", "safe zone", "focal")):
            return "safe_zone_failure"
        if any(token in text for token in ("readability", "caption_readability")):
            return "readability_failure"
        if "aspect_ratio" in text or "ratio" in text:
            return "aspect_ratio_failure"
        if "duplicate" in text or "cooldown" in text:
            return "duplicate_visual_failure"
        if any(
            token in text
            for token in ("wrong_visual", "passthrough", "wrong_approved_asset")
        ):
            return "wrong_visual_lineage"
        if any(
            token in text
            for token in ("proof", "preview", "audio_preview", "surface_proof")
        ):
            return "proof_asset_only"
        if "trial" in text:
            return "trial_asset_only"
        if any(
            token in text
            for token in (
                "metadata",
                "content_hash",
                "fingerprint",
                "caption_outcome_context",
                "caption_hash",
            )
        ):
            return "visual_metadata_missing"
        if any(
            token in text
            for token in (
                "visual_quality",
                "head_cutoff",
                "face_cutoff",
                "black_bars",
                "letterbox",
                "pillarbox",
            )
        ):
            return "actual_visual_quality_failure"
        if (
            not blockers
            and not publishability.get("publishableCandidate")
            and not readiness.get("canHandoff")
        ):
            return "visual_metadata_missing"
        return "unknown"

    def contentforge_non_visual_gates_pass(
        self,
        checks: dict[str, Any],
        readiness: dict[str, Any],
        publishability: dict[str, Any],
        non_visual_blockers: list[str],
    ) -> bool:
        ignored = {"operator_visual_review_required"}
        remaining = [
            blocker
            for blocker in non_visual_blockers
            if blocker not in ignored and blocker != "handoff_manifest_missing"
        ]
        return bool(
            not remaining
            and checks.get("caption_placement_qc_passed", True)
            and checks.get(
                "discoverability_safe", readiness.get("discoverabilitySafe", True)
            )
            and checks.get("instagram_post_caption_quality_passed", True)
        )

    def contentforge_visual_qc_category_rows(
        self, failures: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        total = len(failures)
        rows = []
        for category in self.CONTENTFORGE_VISUAL_QC_CATEGORIES:
            matching = [
                item for item in failures if item.get("failureCategory") == category
            ]
            rows.append(
                {
                    "failureCategory": category,
                    "count": len(matching),
                    "percentOfVisualFailures": round((len(matching) / total) * 100, 1)
                    if total
                    else 0,
                    "repairable": bool(
                        self.CONTENTFORGE_VISUAL_QC_REPAIRABLE.get(category, False)
                    ),
                    "estimatedInventoryGain": sum(
                        int(item.get("estimatedInventoryGain") or 0)
                        for item in matching
                    ),
                    "estimatedOperatorMinutes": len(matching)
                    * int(self.CONTENTFORGE_VISUAL_QC_MINUTES.get(category, 10)),
                    "wouldWrite": False,
                }
            )
        return rows

    def contentforge_visual_qc_recovered_inventory(
        self, failures: list[dict[str, Any]], categories: list[str]
    ) -> int:
        selected = {category for category in categories if category}
        return sum(
            int(item.get("estimatedInventoryGain") or 0)
            for item in failures
            if item.get("failureCategory") in selected
        )

    def contentforge_visual_qc_answer(
        self, top: dict[str, Any], total_failures: int
    ) -> str:
        category = str(top.get("failureCategory") or "")
        count = int(top.get("count") or 0)
        if not category:
            return "No ContentForge visual QC failures were observed in the selected fresh production window."
        return (
            f"{count} of {total_failures} ContentForge visual QC failures are classified as "
            f"{category}; estimated schedule-safe inventory gain from fixing that category is "
            f"{int(top.get('estimatedInventoryGain') or 0)}."
        )
