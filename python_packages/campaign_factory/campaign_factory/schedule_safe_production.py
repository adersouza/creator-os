from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any


class ScheduleSafeProductionRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        normalize_content_surface: Callable[[str | None], str],
        surface_report_assets: Callable[..., list[dict[str, Any]]],
        build_surface_readiness: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        surface_handoff_readiness_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        explain_publishability: Callable[[str], dict[str, Any]],
        ratio: Callable[[Any, Any], float],
    ) -> None:
        self.conn = conn
        self._normalize_content_surface = normalize_content_surface
        self._surface_report_assets = surface_report_assets
        self._build_surface_readiness = build_surface_readiness
        self._surface_handoff_readiness_for_asset = surface_handoff_readiness_for_asset
        self._explain_publishability = explain_publishability
        self._ratio = ratio

    def schedule_safe_production_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        content_surface: str | None = "reel",
        lookback_days: int = 1,
        required_inventory: int | None = None,
        current_inventory: int | None = None,
    ) -> dict[str, Any]:
        surface = self._normalize_content_surface(content_surface or "reel")
        assets = self.schedule_safe_production_assets(
            creator=creator,
            campaign_slug=campaign_slug,
            content_surface=surface,
            lookback_days=lookback_days,
        )
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
        waterfall = self.schedule_safe_production_waterfall_rows(assets, surface)
        largest_loss = self.schedule_safe_production_largest_loss(waterfall)
        raw = int(waterfall[0]["outputCount"]) if waterfall else 0
        schedule_safe = int(waterfall[-1]["outputCount"]) if waterfall else 0
        days = max(1, int(lookback_days or 1))
        produced_per_day = round(schedule_safe / days, 2)
        required = int(required_inventory) if required_inventory is not None else 225
        capacity = self.schedule_safe_production_capacity(
            current_inventory=current,
            daily_production=produced_per_day,
            required_for_25=required,
        )
        return {
            "schema": "creator_os.schedule_safe_production_report.v1",
            "creator": creator,
            "campaign": campaign_slug,
            "contentSurface": surface,
            "lookbackDays": days,
            "freshProductionOnly": True,
            "waterfall": waterfall,
            "waterfallSummary": {
                self.schedule_safe_production_summary_key(row["stage"]): int(
                    row["outputCount"]
                )
                for row in waterfall
            },
            "largestProductionLoss": largest_loss,
            "largestLossGate": largest_loss["largestLossGate"],
            "scheduleSafeAssetsProducedPerDay": produced_per_day,
            "scheduleSafeYieldPct": round(self._ratio(schedule_safe, raw) * 100, 1),
            "parentsRequiredPerDay": self.schedule_safe_required_parents_per_day(
                produced_per_day, schedule_safe, len(assets)
            ),
            "variantsRequiredPerDay": self.schedule_safe_required_variants_per_day(
                produced_per_day,
                schedule_safe,
                len(
                    [
                        asset
                        for asset in assets
                        if self.schedule_safe_is_variant_asset(asset)
                    ]
                ),
            ),
            "requiredFor25Accounts": required,
            "currentInventory": current,
            "capacityProjections": capacity["capacityProjections"],
            "daysToReach25AccountBuffer": capacity["daysToReach25AccountBuffer"],
            "daysToReach50AccountBuffer": capacity["daysToReach50AccountBuffer"],
            "daysToReach100AccountBuffer": capacity["daysToReach100AccountBuffer"],
            "successCriteria": {
                "canMeasureProductionThroughput": True,
                "canIdentifyLargestProductionBottleneck": True,
                "canEstimate25AccountBufferTimeline": produced_per_day > 0,
                "canEstimate50AccountBufferTimeline": produced_per_day > 0,
                "canEstimate100AccountBufferTimeline": produced_per_day > 0,
            },
            "wouldWrite": False,
        }

    def schedule_safe_production_waterfall(self, **kwargs: Any) -> dict[str, Any]:
        report = self.schedule_safe_production_report(**kwargs)
        return {
            "schema": "creator_os.schedule_safe_production_waterfall.v1",
            "creator": report.get("creator"),
            "campaign": report.get("campaign"),
            "contentSurface": report.get("contentSurface"),
            "lookbackDays": report.get("lookbackDays"),
            "waterfall": report.get("waterfall"),
            "waterfallSummary": report.get("waterfallSummary"),
            "wouldWrite": False,
        }

    def schedule_safe_production_loss_analysis(self, **kwargs: Any) -> dict[str, Any]:
        report = self.schedule_safe_production_report(**kwargs)
        losses = [
            {
                "gate": row["stage"],
                "lossCount": int(row.get("lossCount") or 0),
                "percentOfTotalLoss": round(
                    (
                        int(row.get("lossCount") or 0)
                        / max(
                            1,
                            sum(
                                int(item.get("lossCount") or 0)
                                for item in report.get("waterfall") or []
                            ),
                        )
                    )
                    * 100,
                    1,
                ),
            }
            for row in report.get("waterfall") or []
            if int(row.get("lossCount") or 0) > 0
        ]
        return {
            "schema": "creator_os.schedule_safe_production_loss_analysis.v1",
            "creator": report.get("creator"),
            "contentSurface": report.get("contentSurface"),
            "largestProductionLoss": report.get("largestProductionLoss"),
            "rankedLosses": sorted(
                losses, key=lambda row: (-row["lossCount"], row["gate"])
            ),
            "wouldWrite": False,
        }

    def schedule_safe_production_capacity_model(self, **kwargs: Any) -> dict[str, Any]:
        report = self.schedule_safe_production_report(**kwargs)
        return {
            "schema": "creator_os.schedule_safe_production_capacity_model.v1",
            "creator": report.get("creator"),
            "contentSurface": report.get("contentSurface"),
            "scheduleSafeAssetsProducedPerDay": report.get(
                "scheduleSafeAssetsProducedPerDay"
            ),
            "scheduleSafeYieldPct": report.get("scheduleSafeYieldPct"),
            "currentInventory": report.get("currentInventory"),
            "capacityProjections": report.get("capacityProjections"),
            "daysToReach25AccountBuffer": report.get("daysToReach25AccountBuffer"),
            "daysToReach50AccountBuffer": report.get("daysToReach50AccountBuffer"),
            "daysToReach100AccountBuffer": report.get("daysToReach100AccountBuffer"),
            "wouldWrite": False,
        }

    def schedule_safe_production_master_report(self, **kwargs: Any) -> dict[str, Any]:
        report = self.schedule_safe_production_report(**kwargs)
        return {
            **report,
            "schema": "creator_os.schedule_safe_production_master_report.v1",
            "wouldWrite": False,
        }

    def schedule_safe_production_assets(
        self,
        *,
        creator: str | None,
        campaign_slug: str | None,
        content_surface: str,
        lookback_days: int,
    ) -> list[dict[str, Any]]:
        cutoff = datetime.now(UTC) - timedelta(days=max(1, int(lookback_days or 1)))
        assets = self._surface_report_assets(
            creator=creator, campaign_slug=campaign_slug
        )
        return [
            asset
            for asset in assets
            if self._normalize_content_surface(
                asset.get("content_surface") or asset.get("source_content_surface")
            )
            == content_surface
            and self.schedule_safe_asset_created_at(asset) >= cutoff
        ]

    def schedule_safe_asset_created_at(self, asset: dict[str, Any]) -> datetime:
        raw = str(asset.get("created_at") or "").strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return datetime(1970, 1, 1, tzinfo=UTC)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def schedule_safe_production_waterfall_rows(
        self, assets: list[dict[str, Any]], surface: str
    ) -> list[dict[str, Any]]:
        parent_assets = [
            asset for asset in assets if not self.schedule_safe_is_variant_asset(asset)
        ]
        variant_assets = [
            asset for asset in assets if self.schedule_safe_is_variant_asset(asset)
        ]
        parent_ids = {str(asset["id"]) for asset in parent_assets}
        accepted_parents = [
            asset
            for asset in parent_assets
            if str(asset.get("review_state") or "").lower()
            in {"approved", "review_ready"}
            or str(asset.get("audit_status") or "").lower()
            in {"passed", "pass", "approved", "approved_candidate"}
        ]
        caption_families = self.schedule_safe_related_count(
            "caption_families", "parent_asset_id", parent_ids
        )
        caption_versions = self.schedule_safe_related_count(
            "caption_versions", "parent_asset_id", parent_ids
        )
        checks = [
            self.schedule_safe_production_variant_checks(asset, surface)
            for asset in variant_assets
        ]
        visual = sum(1 for item in checks if item["visual_qc_passed"])
        placement = sum(
            1
            for item in checks
            if item["visual_qc_passed"] and item["caption_placement_qc_passed"]
        )
        discoverability = sum(
            1
            for item in checks
            if item["visual_qc_passed"]
            and item["caption_placement_qc_passed"]
            and item["discoverability_passed"]
        )
        caption_quality = sum(
            1
            for item in checks
            if item["visual_qc_passed"]
            and item["caption_placement_qc_passed"]
            and item["discoverability_passed"]
            and item["instagram_post_caption_quality_passed"]
        )
        publishability = sum(
            1
            for item in checks
            if item["visual_qc_passed"]
            and item["caption_placement_qc_passed"]
            and item["discoverability_passed"]
            and item["instagram_post_caption_quality_passed"]
            and item["publishability_passed"]
        )
        schedule_safe = sum(1 for item in checks if item["schedule_safe"])
        stage_counts = [
            ("raw_parent_reels", len(parent_assets), len(parent_assets)),
            ("accepted_parent_reels", len(parent_assets), len(accepted_parents)),
            ("caption_families_created", len(accepted_parents), caption_families),
            (
                "caption_families_accepted",
                caption_families,
                min(caption_families, caption_versions),
            ),
            (
                "contentforge_variants_created",
                max(caption_versions, len(accepted_parents), len(variant_assets)),
                len(variant_assets),
            ),
            ("visual_qc_passed", len(variant_assets), visual),
            ("caption_placement_qc_passed", visual, placement),
            ("discoverability_passed", placement, discoverability),
            ("instagram_post_caption_quality_passed", discoverability, caption_quality),
            ("publishability_passed", caption_quality, publishability),
            ("schedule_safe_assets_produced", publishability, schedule_safe),
        ]
        return [
            {
                "stage": stage,
                "inputCount": int(input_count),
                "outputCount": int(output_count),
                "lossCount": max(0, int(input_count) - int(output_count)),
                "yieldPct": round(self._ratio(output_count, input_count) * 100, 1),
            }
            for stage, input_count, output_count in stage_counts
        ]

    def schedule_safe_is_variant_asset(self, asset: dict[str, Any]) -> bool:
        return bool(asset.get("parent_asset_id") or asset.get("variant_id"))

    def schedule_safe_related_count(
        self, table: str, column: str, asset_ids: set[str]
    ) -> int:
        if not asset_ids:
            return 0
        placeholders = ",".join("?" for _ in asset_ids)
        try:
            return int(
                self.conn.execute(
                    f"SELECT COUNT(*) AS c FROM {table} WHERE {column} IN ({placeholders})",
                    sorted(asset_ids),
                ).fetchone()["c"]
                or 0
            )
        except sqlite3.OperationalError:
            return 0

    def schedule_safe_production_variant_checks(
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
        blockers = {
            str(reason).replace("publishability:", "")
            for reason in readiness.get("blockingReasons") or []
        }
        blockers.update(
            str(reason)
            for reason in publishability.get("publishability_failure_reasons") or []
        )
        visual_passed = bool(
            checks.get(
                "operator_visual_review_passed",
                "operator_visual_review_required" not in blockers,
            )
        )
        placement_passed = bool(
            checks.get(
                "caption_placement_qc_passed",
                "caption_placement_qc_failed" not in blockers,
            )
        )
        discoverability_passed = bool(
            readiness.get("discoverabilitySafe")
            and checks.get(
                "discoverability_safe", "discoverability_safety_failed" not in blockers
            )
        )
        caption_quality_passed = bool(
            checks.get(
                "instagram_post_caption_quality_passed",
                "instagram_post_caption_quality_failed" not in blockers,
            )
        )
        publishability_passed = (
            bool(publishability.get("publishableCandidate"))
            if surface == "reel"
            else not blockers
        )
        return {
            "assetId": asset["id"],
            "visual_qc_passed": visual_passed,
            "caption_placement_qc_passed": placement_passed,
            "discoverability_passed": discoverability_passed,
            "instagram_post_caption_quality_passed": caption_quality_passed,
            "publishability_passed": publishability_passed,
            "schedule_safe": bool(readiness.get("canHandoff")),
        }

    def schedule_safe_production_largest_loss(
        self, waterfall: list[dict[str, Any]]
    ) -> dict[str, Any]:
        total_loss = sum(int(row.get("lossCount") or 0) for row in waterfall)
        largest = max(
            waterfall,
            key=lambda row: (
                int(row.get("lossCount") or 0),
                str(row.get("stage") or ""),
            ),
            default={},
        )
        loss = int(largest.get("lossCount") or 0)
        return {
            "largestLossGate": largest.get("stage") or "",
            "lossCount": loss,
            "percentOfTotalLoss": round((loss / max(1, total_loss)) * 100, 1)
            if total_loss
            else 0,
        }

    def schedule_safe_production_capacity(
        self,
        *,
        current_inventory: int,
        daily_production: float,
        required_for_25: int,
    ) -> dict[str, Any]:
        targets = {
            "25Accounts": int(required_for_25),
            "50Accounts": 450,
            "100Accounts": 900,
        }
        projections: dict[str, Any] = {}
        for key, required in targets.items():
            shortfall = max(0, required - int(current_inventory or 0))
            days = (
                math.ceil(shortfall / daily_production)
                if daily_production > 0 and shortfall > 0
                else (0 if shortfall == 0 else None)
            )
            projections[key] = {
                "requiredInventory": required,
                "currentInventory": int(current_inventory or 0),
                "shortfall": shortfall,
                "daysToReachBuffer": days,
                "blockedReason": ""
                if days is not None
                else "no_schedule_safe_production_observed",
            }
        return {
            "capacityProjections": projections,
            "daysToReach25AccountBuffer": projections["25Accounts"][
                "daysToReachBuffer"
            ],
            "daysToReach50AccountBuffer": projections["50Accounts"][
                "daysToReachBuffer"
            ],
            "daysToReach100AccountBuffer": projections["100Accounts"][
                "daysToReachBuffer"
            ],
        }

    def schedule_safe_required_parents_per_day(
        self, produced_per_day: float, produced: int, parent_count: int
    ) -> int:
        if produced_per_day <= 0 or produced <= 0:
            return 0
        parents_per_asset = parent_count / max(1, produced)
        return int(math.ceil(75 * parents_per_asset))

    def schedule_safe_required_variants_per_day(
        self, produced_per_day: float, produced: int, variant_count: int
    ) -> int:
        if produced_per_day <= 0 or produced <= 0:
            return 0
        variants_per_asset = variant_count / max(1, produced)
        return int(math.ceil(75 * variants_per_asset))

    def schedule_safe_production_summary_key(self, stage: str) -> str:
        return {
            "raw_parent_reels": "rawParents",
            "accepted_parent_reels": "acceptedParents",
            "caption_families_created": "captionFamilies",
            "caption_families_accepted": "captionFamiliesAccepted",
            "contentforge_variants_created": "variantsCreated",
            "visual_qc_passed": "visualQcPassed",
            "caption_placement_qc_passed": "captionPlacementPassed",
            "discoverability_passed": "discoverabilityPassed",
            "instagram_post_caption_quality_passed": "captionQualityPassed",
            "publishability_passed": "publishabilityPassed",
            "schedule_safe_assets_produced": "scheduleSafeAssets",
        }.get(stage, stage)
