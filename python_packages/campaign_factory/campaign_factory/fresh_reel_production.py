from __future__ import annotations

import math
import sqlite3
from typing import Any, Callable


class FreshReelProductionRepository:
    FRESH_REEL_PARENT_YIELD_EVIDENCE = {
        "realProductionParentTrial": {
            "rawCandidates": 64,
            "acceptedParents": 57,
            "yieldPct": 89.1,
        },
        "postGateFreshBatch": {
            "rawCandidates": 64,
            "acceptedParents": 53,
            "yieldPct": 82.8,
        },
    }
    FRESH_REEL_STAGE_YIELDS = (
        ("parent_accepted", 82.8, "low"),
        ("caption_family_created", 100.0, "medium"),
        ("caption_versions_created", 100.0, "medium"),
        ("contentforge_variants_created", 100.0, "medium"),
        ("visual_qc_passed", 90.0, "high"),
        ("caption_placement_qc_passed", 95.0, "medium"),
        ("instagram_post_caption_quality_passed", 95.0, "medium"),
        ("discoverability_passed", 98.0, "low"),
        ("publishability_passed", 90.0, "high"),
        ("schedule_safe_asset_produced", 95.0, "high"),
    )
    FRESH_REEL_GATES_TO_VERIFY = (
        "discoverability_generation_gate",
        "visual_qc",
        "caption_placement_qc",
        "instagram_post_caption_quality",
        "publishability",
        "handoff_manifest",
    )

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

    def fresh_schedule_safe_production_plan(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        target_schedule_safe_inventory: int = 270,
        current_inventory: int | None = None,
        caption_versions_per_parent: int = 5,
        variants_per_caption: int = 3,
        batch_schedule_safe_target: int = 90,
    ) -> dict[str, Any]:
        target = max(0, int(target_schedule_safe_inventory or 270))
        current = (
            int(current_inventory)
            if current_inventory is not None
            else self.fresh_reel_current_schedule_safe_inventory(creator=creator, campaign_slug=campaign_slug)
        )
        needed = max(0, target - current)
        versions_per_parent = max(1, int(caption_versions_per_parent or 5))
        variants_per_version = max(1, int(variants_per_caption or 3))
        variants_per_parent = versions_per_parent * variants_per_version
        downstream_yield = self.fresh_reel_downstream_schedule_safe_yield_pct()
        variants_needed = int(math.ceil(needed / max(0.01, downstream_yield / 100))) if needed else 0
        parents_needed = int(math.ceil(variants_needed / variants_per_parent)) if variants_needed else 0
        raw_parent_candidates_needed = int(math.ceil(parents_needed / 0.828)) if parents_needed else 0
        caption_families_needed = parents_needed
        caption_versions_needed = parents_needed * versions_per_parent
        stages = self.fresh_reel_expected_stage_rows(
            raw_parent_candidates_needed=raw_parent_candidates_needed,
            parents_needed=parents_needed,
            caption_families_needed=caption_families_needed,
            caption_versions_needed=caption_versions_needed,
            variants_needed=variants_needed,
        )
        execution_batches = self.fresh_reel_execution_batches(
            fresh_needed=needed,
            downstream_yield_pct=downstream_yield,
            variants_per_parent=variants_per_parent,
            batch_target=batch_schedule_safe_target,
        )
        batch_count = len(execution_batches)
        daily_schedule_safe_target = min(max(1, int(batch_schedule_safe_target or 90)), needed) if needed else 0
        estimated_days = int(math.ceil(needed / daily_schedule_safe_target)) if daily_schedule_safe_target else 0
        conservative_yield = 50.0
        conservative_variants = int(math.ceil(needed / (conservative_yield / 100))) if needed else 0
        conservative_parents = int(math.ceil(conservative_variants / variants_per_parent)) if conservative_variants else 0
        conservative_daily = (
            max(1, int(math.floor(daily_schedule_safe_target * (conservative_yield / max(0.01, downstream_yield)))))
            if daily_schedule_safe_target
            else 0
        )
        return {
            "schema": "creator_os.fresh_schedule_safe_production_plan.v1",
            "creator": creator,
            "campaign": campaign_slug,
            "contentSurface": "reel",
            "reelsOnly": True,
            "targetScheduleSafeInventory": target,
            "currentScheduleSafeInventory": current,
            "freshScheduleSafeAssetsNeeded": needed,
            "parentsNeeded": parents_needed,
            "rawParentCandidatesNeeded": raw_parent_candidates_needed,
            "captionFamiliesNeeded": caption_families_needed,
            "captionVersionsNeeded": caption_versions_needed,
            "variantsNeeded": variants_needed,
            "expectedYield": downstream_yield,
            "expectedYieldEvidence": self.FRESH_REEL_PARENT_YIELD_EVIDENCE,
            "downstreamYieldEvidenceStatus": "insufficient_schedule_safe_variant_production_evidence",
            "largestProductionRisk": "variant_to_schedule_safe_yield_not_yet_proven",
            "stagePlan": stages,
            "executionBatches": execution_batches,
            "batchesRequired": batch_count,
            "estimatedDaysToBuffer": estimated_days,
            "dailyParentTarget": int(math.ceil(parents_needed / max(1, estimated_days))) if parents_needed else 0,
            "dailyVariantTarget": int(math.ceil(variants_needed / max(1, estimated_days))) if variants_needed else 0,
            "dailyScheduleSafeTarget": daily_schedule_safe_target,
            "conservativeScenario": {
                "conservativeYieldPct": conservative_yield,
                "parentsNeededConservative": conservative_parents,
                "variantsNeededConservative": conservative_variants,
                "estimatedDaysConservative": int(math.ceil(needed / conservative_daily)) if conservative_daily and needed else 0,
            },
            "constraints": {
                "noStoryFeedCarouselPadding": True,
                "noOldQuarantinedAssets": True,
                "noScheduling": True,
                "noPublishing": True,
                "noExport": True,
                "noAssetMutation": True,
                "noCaptionMutation": True,
                "noProductionDbMutation": True,
            },
            "wouldWrite": False,
        }

    def fresh_reel_production_batch_plan(self, **kwargs: Any) -> dict[str, Any]:
        report = self.fresh_schedule_safe_production_plan(**kwargs)
        return {
            "schema": "creator_os.fresh_reel_production_batch_plan.v1",
            "creator": report.get("creator"),
            "campaign": report.get("campaign"),
            "contentSurface": "reel",
            "freshScheduleSafeAssetsNeeded": report.get("freshScheduleSafeAssetsNeeded"),
            "batchesRequired": report.get("batchesRequired"),
            "executionBatches": report.get("executionBatches"),
            "largestProductionRisk": report.get("largestProductionRisk"),
            "wouldWrite": False,
        }

    def fresh_reel_production_capacity_plan(self, **kwargs: Any) -> dict[str, Any]:
        report = self.fresh_schedule_safe_production_plan(**kwargs)
        return {
            "schema": "creator_os.fresh_reel_production_capacity_plan.v1",
            "creator": report.get("creator"),
            "campaign": report.get("campaign"),
            "targetScheduleSafeInventory": report.get("targetScheduleSafeInventory"),
            "currentScheduleSafeInventory": report.get("currentScheduleSafeInventory"),
            "freshScheduleSafeAssetsNeeded": report.get("freshScheduleSafeAssetsNeeded"),
            "parentsNeeded": report.get("parentsNeeded"),
            "captionFamiliesNeeded": report.get("captionFamiliesNeeded"),
            "variantsNeeded": report.get("variantsNeeded"),
            "expectedYield": report.get("expectedYield"),
            "batchesRequired": report.get("batchesRequired"),
            "estimatedDaysToBuffer": report.get("estimatedDaysToBuffer"),
            "dailyParentTarget": report.get("dailyParentTarget"),
            "dailyVariantTarget": report.get("dailyVariantTarget"),
            "dailyScheduleSafeTarget": report.get("dailyScheduleSafeTarget"),
            "conservativeScenario": report.get("conservativeScenario"),
            "largestProductionRisk": report.get("largestProductionRisk"),
            "wouldWrite": False,
        }

    def fresh_reel_production_master_report(self, **kwargs: Any) -> dict[str, Any]:
        report = self.fresh_schedule_safe_production_plan(**kwargs)
        return {
            **report,
            "schema": "creator_os.fresh_reel_production_master_report.v1",
            "wouldWrite": False,
        }

    def fresh_reel_current_schedule_safe_inventory(
        self,
        *,
        creator: str | None,
        campaign_slug: str | None,
    ) -> int:
        assets = [
            asset for asset in self._surface_report_assets(creator=creator, campaign_slug=campaign_slug)
            if self._normalize_content_surface(asset.get("content_surface") or asset.get("source_content_surface")) == "reel"
        ]
        return sum(1 for readiness in self._build_surface_readiness(assets) if readiness.get("canHandoff"))

    def fresh_reel_downstream_schedule_safe_yield_pct(self) -> float:
        yield_pct = 100.0
        for stage, stage_yield, _risk in self.FRESH_REEL_STAGE_YIELDS:
            if stage == "parent_accepted":
                continue
            if stage in {
                "caption_family_created",
                "caption_versions_created",
                "contentforge_variants_created",
            }:
                continue
            yield_pct *= float(stage_yield) / 100
        return round(yield_pct, 1)

    def fresh_reel_expected_stage_rows(
        self,
        *,
        raw_parent_candidates_needed: int,
        parents_needed: int,
        caption_families_needed: int,
        caption_versions_needed: int,
        variants_needed: int,
    ) -> list[dict[str, Any]]:
        counts = {
            "parent_accepted": (raw_parent_candidates_needed, parents_needed),
            "caption_family_created": (parents_needed, caption_families_needed),
            "caption_versions_created": (caption_families_needed, caption_versions_needed),
            "contentforge_variants_created": (caption_versions_needed, variants_needed),
        }
        current = variants_needed
        for stage, yield_pct, _risk in self.FRESH_REEL_STAGE_YIELDS:
            if stage in counts:
                continue
            output = int(round(current * (float(yield_pct) / 100)))
            counts[stage] = (current, output)
            current = output
        rows = []
        for stage, yield_pct, risk in self.FRESH_REEL_STAGE_YIELDS:
            input_count, output_count = counts.get(stage, (0, 0))
            rows.append({
                "stage": stage,
                "expectedInput": int(input_count),
                "expectedOutput": int(output_count),
                "assumedYieldPct": float(yield_pct),
                "risk": risk,
                "evidence": self.fresh_reel_stage_evidence(stage),
            })
        return rows

    def fresh_reel_stage_evidence(self, stage: str) -> str:
        if stage == "parent_accepted":
            return "measured_post_gate_parent_trials"
        if stage == "discoverability_passed":
            return "upstream_discoverability_gate_fixture_proof"
        if stage in {
            "visual_qc_passed",
            "publishability_passed",
            "schedule_safe_asset_produced",
        }:
            return "conservative_assumption_pending_fresh_schedule_safe_batch"
        return "deterministic_pipeline_step_assumption_pending_batch_verification"

    def fresh_reel_execution_batches(
        self,
        *,
        fresh_needed: int,
        downstream_yield_pct: float,
        variants_per_parent: int,
        batch_target: int,
    ) -> list[dict[str, Any]]:
        batches = []
        remaining = max(0, int(fresh_needed or 0))
        target = max(1, int(batch_target or 90))
        batch_index = 1
        while remaining > 0:
            schedule_safe_target = min(target, remaining)
            variants_required = int(math.ceil(schedule_safe_target / max(0.01, downstream_yield_pct / 100)))
            parents_required = int(math.ceil(variants_required / max(1, variants_per_parent)))
            batches.append({
                "batchId": f"fresh_reel_batch_{batch_index:02d}",
                "targetScheduleSafeAssets": schedule_safe_target,
                "parentsRequired": parents_required,
                "captionFamiliesRequired": parents_required,
                "variantsRequired": variants_required,
                "expectedScheduleSafeOutput": schedule_safe_target,
                "gatesToVerify": list(self.FRESH_REEL_GATES_TO_VERIFY),
                "wouldWrite": False,
            })
            remaining -= schedule_safe_target
            batch_index += 1
        return batches
