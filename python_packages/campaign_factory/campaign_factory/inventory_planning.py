from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable
from typing import Any


class InventoryPlanningRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        creator_label: Callable[[Any], str],
        normalize_content_surface: Callable[[str | None], str],
        surface_report_assets: Callable[..., list[dict[str, Any]]],
        build_surface_readiness: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        build_surface_inventory: Callable[..., dict[str, Any]],
        ratio: Callable[[Any, Any], float],
        score_fraction: Callable[[Any, Any], float],
        road_to_accounts_payload: Callable[..., dict[str, Any]],
        exception_next_action: Callable[[str], str],
        content_surfaces: tuple[str, ...],
    ) -> None:
        self.conn = conn
        self._creator_label = creator_label
        self._normalize_content_surface = normalize_content_surface
        self._surface_report_assets = surface_report_assets
        self._build_surface_readiness = build_surface_readiness
        self._build_surface_inventory = build_surface_inventory
        self._ratio = ratio
        self._score_fraction = score_fraction
        self._road_to_accounts_payload = road_to_accounts_payload
        self._exception_next_action = exception_next_action
        self._content_surfaces = content_surfaces

    def inventory_slo_report(
        self,
        *,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
        creators: int = 3,
        minimum_inventory_days: int = 3,
        current_validated_drafts: int = 0,
        current_drafts_by_surface: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        daily_posts = max(0, int(accounts or 0)) * max(
            0, int(posts_per_account_per_day or 0)
        )
        minimum_days = max(1, int(minimum_inventory_days or 1))
        minimum_buffer = daily_posts * minimum_days
        creator_count = max(1, int(creators or 1))
        base_per_creator = minimum_buffer // creator_count
        remainder = minimum_buffer % creator_count
        minimum_by_creator = {
            f"Creator {idx}": base_per_creator + (1 if idx <= remainder else 0)
            for idx in range(1, creator_count + 1)
        }
        minimum_by_surface = self.inventory_slo_surface_targets(minimum_buffer)
        current_by_surface = {
            surface: int((current_drafts_by_surface or {}).get(surface) or 0)
            for surface in self._content_surfaces
        }
        current = max(0, int(current_validated_drafts or 0))
        health = self.inventory_health(current=current, minimum=minimum_buffer)
        return {
            "schema": "creator_os.inventory_slo_report.v1",
            "minimumInventoryDays": minimum_days,
            "accounts": max(0, int(accounts or 0)),
            "postsPerAccountPerDay": max(0, int(posts_per_account_per_day or 0)),
            "dailyPostObligations": daily_posts,
            "minimumValidatedDraftBuffer": minimum_buffer,
            "minimumDraftsPerCreator": minimum_by_creator,
            "minimumDraftsPerSurface": minimum_by_surface,
            "currentValidatedDrafts": current,
            "currentDraftsPerSurface": current_by_surface,
            "draftShortfall": max(0, minimum_buffer - current),
            "inventoryHealth": health,
            "wouldWrite": False,
        }

    def inventory_buffer_report(self, **kwargs: Any) -> dict[str, Any]:
        report = self.inventory_slo_report(**kwargs)
        current = int(report.get("currentValidatedDrafts") or 0)
        minimum = int(report.get("minimumValidatedDraftBuffer") or 0)
        return {
            **report,
            "schema": "creator_os.inventory_buffer_report.v1",
            "draftSurplus": max(0, current - minimum),
            "bufferDaysAvailable": round(
                current / max(1, int(report.get("dailyPostObligations") or 1)), 2
            ),
            "wouldWrite": False,
        }

    def inventory_factory_audit(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
    ) -> dict[str, Any]:
        counts = self.inventory_stage_counts(
            creator=creator, campaign_slug=campaign_slug
        )
        daily_demand = max(0, int(accounts or 0)) * max(
            0, int(posts_per_account_per_day or 0)
        )
        schedule_safe = int(counts["scheduleSafeAssets"])
        validated = int(counts["validatedAssets"])
        publishable = int(counts["publishableAssets"])
        limiting_stage = self.inventory_limiting_stage(counts)
        return {
            "schema": "creator_os.inventory_factory_audit.v1",
            "inventoryPipelineMapped": True,
            "pipeline": [
                "Reel Factory",
                "ContentForge",
                "Campaign Factory",
                "Validated Inventory",
                "Schedule-Safe Inventory",
                "Daily Plan Consumption",
            ],
            "largestBottleneck": limiting_stage,
            "dailyDemand": daily_demand,
            "dailyCapacityEstimate": min(schedule_safe, daily_demand)
            if daily_demand
            else schedule_safe,
            "validatedInventoryCapacity": validated,
            "publishableInventoryCapacity": publishable,
            "scheduleSafeInventoryCapacity": schedule_safe,
            "limitingStage": limiting_stage,
            "inventoryLostByStage": self.inventory_loss_by_stage(counts),
            "wouldWrite": False,
        }

    def inventory_yield_analysis(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
    ) -> dict[str, Any]:
        counts = self.inventory_stage_counts(
            creator=creator, campaign_slug=campaign_slug
        )
        parent_to_variant = self._ratio(counts["variantAssets"], counts["parentAssets"])
        variant_to_validated = self._ratio(
            counts["validatedAssets"], counts["variantAssets"]
        )
        validated_to_schedule_safe = self._ratio(
            counts["scheduleSafeAssets"], counts["validatedAssets"]
        )
        yields = {
            "parent_to_variant": parent_to_variant,
            "variant_to_validated": variant_to_validated,
            "validated_to_schedule_safe": validated_to_schedule_safe,
        }
        non_zero = {key: value for key, value in yields.items() if value > 0}
        largest_dropoff = (
            min(non_zero.items(), key=lambda item: item[1])[0]
            if non_zero
            else "parent_to_variant"
        )
        return {
            "schema": "creator_os.inventory_yield_analysis.v1",
            "stageCounts": counts,
            "parentToVariantYield": parent_to_variant,
            "variantToValidatedYield": variant_to_validated,
            "validatedToScheduleSafeYield": validated_to_schedule_safe,
            "largestDropoff": largest_dropoff,
            "wouldWrite": False,
        }

    def inventory_buffer_policy_plan(
        self,
        *,
        creator: str,
        surface: str,
        daily_demand: int,
        buffer_target_days: int = 3,
        available_inventory: int | None = None,
    ) -> dict[str, Any]:
        normalized_surface = self._normalize_content_surface(surface)
        demand = max(0, int(daily_demand or 0))
        days = max(1, int(buffer_target_days or 1))
        required = demand * days
        if available_inventory is None:
            inventory = (
                self._build_surface_inventory(creator=self._creator_label(creator)).get(
                    "inventoryBySurface"
                )
                or {}
            )
            available = int(
                (inventory.get(normalized_surface) or {}).get("scheduleSafe") or 0
            )
        else:
            available = max(0, int(available_inventory or 0))
        return {
            "schema": "creator_os.inventory_buffer_policy_plan.v1",
            "creator": self._creator_label(creator),
            "surface": normalized_surface,
            "dailyDemand": demand,
            "bufferTargetDays": days,
            "requiredInventory": required,
            "availableInventory": available,
            "shortfall": max(0, required - available),
            "health": self.inventory_health(current=available, minimum=required),
            "wouldWrite": False,
        }

    def inventory_slo_enforcement_audit(
        self,
        *,
        creators: list[str] | None = None,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
        minimum_inventory_days: int = 3,
        available_by_creator_surface: dict[str, dict[str, int]] | None = None,
    ) -> dict[str, Any]:
        creator_names = [
            self._creator_label(item)
            for item in (creators or ["Creator 1"])
            if str(item or "").strip()
        ] or ["Creator 1"]
        total_required = (
            max(0, int(accounts or 0))
            * max(0, int(posts_per_account_per_day or 0))
            * max(1, int(minimum_inventory_days or 1))
        )
        required_per_creator = math.ceil(total_required / max(1, len(creator_names)))
        required_by_surface = self.inventory_slo_surface_targets(required_per_creator)
        availability = available_by_creator_surface or {}
        violations = []
        creator_shortfalls: dict[str, int] = {}
        surface_shortfalls: dict[str, int] = {
            surface: 0 for surface in self._content_surfaces
        }
        for creator in creator_names:
            available_surfaces = availability.get(creator) or {}
            for surface, required in required_by_surface.items():
                available = max(0, int(available_surfaces.get(surface) or 0))
                shortfall = max(0, required - available)
                if shortfall:
                    violations.append(
                        {
                            "creator": creator,
                            "surface": surface,
                            "requiredInventory": required,
                            "availableInventory": available,
                            "shortfall": shortfall,
                            "severity": "critical" if available == 0 else "high",
                            "wouldWrite": False,
                        }
                    )
                    creator_shortfalls[creator] = (
                        creator_shortfalls.get(creator, 0) + shortfall
                    )
                    surface_shortfalls[surface] = (
                        surface_shortfalls.get(surface, 0) + shortfall
                    )
        return {
            "schema": "creator_os.inventory_slo_enforcement_audit.v1",
            "slosDefined": True,
            "minimumInventoryDays": max(1, int(minimum_inventory_days or 1)),
            "minimumPerCreator": required_per_creator,
            "minimumPerSurface": required_by_surface,
            "violations": violations,
            "highestRiskCreator": max(
                creator_shortfalls.items(), key=lambda item: item[1]
            )[0]
            if creator_shortfalls
            else "",
            "highestRiskSurface": max(
                surface_shortfalls.items(), key=lambda item: item[1]
            )[0]
            if any(surface_shortfalls.values())
            else "",
            "wouldWrite": False,
        }

    def inventory_consumption_simulation(
        self,
        *,
        available_inventory: int = 0,
        account_tiers: list[int] | None = None,
        posts_per_account_per_day: int = 3,
    ) -> dict[str, Any]:
        inventory = max(0, int(available_inventory or 0))
        tiers = account_tiers or [25, 50, 100, 200, 500]
        rows = []
        for account_count in tiers:
            daily_demand = max(0, int(account_count or 0)) * max(
                0, int(posts_per_account_per_day or 0)
            )
            rows.append(
                {
                    "accounts": int(account_count),
                    "dailyDemand": daily_demand,
                    "inventoryConsumed": min(inventory, daily_demand),
                    "daysUntilEmpty": inventory // max(1, daily_demand),
                    "requiredProductionRate": daily_demand,
                    "warmingEnabled": True,
                    "accountHealthEnabled": True,
                    "discoverabilityEnabled": True,
                    "wouldWrite": False,
                }
            )
        return {
            "schema": "creator_os.inventory_consumption_simulation.v1",
            "availableInventory": inventory,
            "simulations": rows,
            "wouldWrite": False,
        }

    def inventory_production_requirements(
        self,
        *,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
        variants_per_parent: int = 15,
        variant_to_validated_yield: float = 0.85,
        validated_to_schedule_safe_yield: float = 0.90,
    ) -> dict[str, Any]:
        posts = max(0, int(accounts or 0)) * max(0, int(posts_per_account_per_day or 0))
        effective_yield = max(
            0.01,
            float(variant_to_validated_yield or 0)
            * float(validated_to_schedule_safe_yield or 0),
        )
        required_variants = math.ceil(posts / effective_yield) if posts else 0
        per_parent = max(1, int(variants_per_parent or 1))
        required_parents = (
            math.ceil(required_variants / per_parent) if required_variants else 0
        )
        return {
            "schema": "creator_os.inventory_production_requirements.v1",
            "accounts": max(0, int(accounts or 0)),
            "postsPerDay": posts,
            "requiredParentsPerDay": required_parents,
            "requiredCaptionFamiliesPerDay": required_parents,
            "requiredCaptionVersionsPerDay": math.ceil(required_variants / 3)
            if required_variants
            else 0,
            "requiredVariantsPerDay": required_variants,
            "requiredValidatedDraftsPerDay": posts,
            "assumptions": {
                "variantsPerParent": per_parent,
                "variantToValidatedYield": variant_to_validated_yield,
                "validatedToScheduleSafeYield": validated_to_schedule_safe_yield,
            },
            "wouldWrite": False,
        }

    def road_to_200_accounts(self) -> dict[str, Any]:
        production = self.inventory_production_requirements(
            accounts=200, posts_per_account_per_day=3
        )
        return self._road_to_accounts_payload(accounts=200, production=production)

    def inventory_exception_audit(
        self,
        *,
        execution_readiness: dict[str, Any] | None = None,
        surface_readiness_report: dict[str, Any] | None = None,
        publishability_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for blocker in (execution_readiness or {}).get("blockers") or []:
            reason = str(blocker)
            counts[reason] = counts.get(reason, 0) + 1
        for source in (surface_readiness_report or {}, publishability_report or {}):
            for item in source.get("assets") or source.get("items") or []:
                if not isinstance(item, dict):
                    continue
                for reason in (
                    item.get("blockingReasons") or item.get("failureReasons") or []
                ):
                    reason_text = str(reason).replace("publishability:", "")
                    counts[reason_text] = counts.get(reason_text, 0) + 1
        if not counts:
            default_reasons = [
                "publishability_failed",
                "discoverability_failed",
                "caption_blocked",
                "account_health_blocked",
                "surface_mismatch",
                "missing_audio",
                "missing_metadata",
                "duplicate_risk",
                "restriction_event",
            ]
            counts = {reason: 0 for reason in default_reasons}
        top = (
            max(counts.items(), key=lambda item: (item[1], item[0]))[0]
            if counts
            else ""
        )
        total = sum(counts.values())
        avoidable = sum(
            count
            for reason, count in counts.items()
            if reason not in {"restriction_event", "account_health_blocked"}
        )
        return {
            "schema": "creator_os.inventory_exception_audit.v1",
            "inventoryLossReasons": [
                {
                    "reason": reason,
                    "count": count,
                    "avoidable": reason
                    not in {"restriction_event", "account_health_blocked"},
                    "nextAction": self._exception_next_action(reason),
                }
                for reason, count in sorted(
                    counts.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "topLossReason": top,
            "avoidableLossPct": round((avoidable / total) * 100, 1) if total else 0,
            "wouldWrite": False,
        }

    def inventory_factory_readiness_report(
        self,
        *,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
        available_inventory: int = 0,
        execution_readiness: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        audit = self.inventory_factory_audit(
            accounts=accounts, posts_per_account_per_day=posts_per_account_per_day
        )
        yield_report = self.inventory_yield_analysis()
        slo = self.inventory_slo_report(
            accounts=accounts,
            posts_per_account_per_day=posts_per_account_per_day,
            creators=3,
            minimum_inventory_days=3,
            current_validated_drafts=available_inventory,
        )
        exceptions = self.inventory_exception_audit(
            execution_readiness=execution_readiness
        )
        daily_demand = int(slo.get("dailyPostObligations") or 0)
        current_score = self._score_fraction(
            available_inventory, int(slo.get("minimumValidatedDraftBuffer") or 1)
        )
        capacity_score = self._score_fraction(
            audit.get("scheduleSafeInventoryCapacity") or 0, daily_demand
        )
        buffer_score = self._score_fraction(
            available_inventory, int(slo.get("minimumValidatedDraftBuffer") or 1)
        )
        yield_score = round(
            10
            * min(
                1.0,
                max(
                    yield_report.get("parentToVariantYield") or 0,
                    yield_report.get("variantToValidatedYield") or 0,
                    yield_report.get("validatedToScheduleSafeYield") or 0,
                ),
            ),
            1,
        )
        exception_score = max(
            0.0, round(10 - ((exceptions.get("avoidableLossPct") or 0) / 20), 1)
        )
        overall = round(
            (
                current_score
                + capacity_score
                + buffer_score
                + yield_score
                + exception_score
            )
            / 5,
            1,
        )
        return {
            "schema": "creator_os.inventory_factory_readiness_report.v1",
            "currentInventoryScore": current_score,
            "inventoryCapacityScore": capacity_score,
            "inventoryBufferScore": buffer_score,
            "inventoryYieldScore": yield_score,
            "inventoryExceptionScore": exception_score,
            "overallInventoryReadiness": overall,
            "inputs": {
                "accounts": accounts,
                "postsPerAccountPerDay": posts_per_account_per_day,
                "availableInventory": available_inventory,
            },
            "wouldWrite": False,
        }

    def inventory_factory_master_report(
        self,
        *,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
        available_inventory: int = 0,
        execution_readiness: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        audit = self.inventory_factory_audit(
            accounts=accounts, posts_per_account_per_day=posts_per_account_per_day
        )
        yield_report = self.inventory_yield_analysis()
        buffer = self.inventory_buffer_policy_plan(
            creator="All",
            surface="all",
            daily_demand=max(0, int(accounts or 0))
            * max(0, int(posts_per_account_per_day or 0)),
            buffer_target_days=3,
            available_inventory=available_inventory,
        )
        simulation = self.inventory_consumption_simulation(
            available_inventory=available_inventory
        )
        production = self.inventory_production_requirements(
            accounts=accounts, posts_per_account_per_day=posts_per_account_per_day
        )
        exceptions = self.inventory_exception_audit(
            execution_readiness=execution_readiness
        )
        score = self.inventory_factory_readiness_report(
            accounts=accounts,
            posts_per_account_per_day=posts_per_account_per_day,
            available_inventory=available_inventory,
            execution_readiness=execution_readiness,
        )
        return {
            "schema": "creator_os.inventory_factory_master_report.v1",
            "currentInventoryReadiness": score,
            "inventoryBottlenecks": {
                "largestBottleneck": audit["largestBottleneck"],
                "limitingStage": audit["limitingStage"],
                "inventoryLostByStage": audit["inventoryLostByStage"],
            },
            "inventoryYieldAnalysis": yield_report,
            "bufferRequirements": buffer,
            "consumptionSimulations": simulation["simulations"],
            "productionRequirements": production,
            "exceptionAnalysis": exceptions,
            "inventoryScore": score,
            "requirementsFor200Accounts": self._road_to_accounts_payload(
                accounts=200,
                production=self.inventory_production_requirements(
                    accounts=200, posts_per_account_per_day=posts_per_account_per_day
                ),
            ),
            "requirementsFor500Accounts": self._road_to_accounts_payload(
                accounts=500,
                production=self.inventory_production_requirements(
                    accounts=500, posts_per_account_per_day=posts_per_account_per_day
                ),
            ),
            "wouldWrite": False,
        }

    def inventory_autopilot_plan(
        self,
        *,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
        available_inventory: int = 0,
        buffer_target_days: int = 3,
        surface: str = "reel",
    ) -> dict[str, Any]:
        daily_demand = max(0, int(accounts or 0)) * max(
            0, int(posts_per_account_per_day or 0)
        )
        policy = self.inventory_buffer_policy_plan(
            creator="All",
            surface=surface,
            daily_demand=daily_demand,
            buffer_target_days=buffer_target_days,
            available_inventory=available_inventory,
        )
        days_remaining = round(
            max(0, int(available_inventory or 0)) / max(1, daily_demand), 2
        )
        repair_actions = self.inventory_repair_actions(policy)
        return {
            "schema": "creator_os.inventory_autopilot_plan.v1",
            "surface": self._normalize_content_surface(surface),
            "dailyDemand": daily_demand,
            "requiredInventory": policy["requiredInventory"],
            "availableInventory": policy["availableInventory"],
            "shortfall": policy["shortfall"],
            "daysRemaining": days_remaining,
            "health": policy["health"],
            "repairActions": repair_actions,
            "wouldWrite": False,
        }

    def inventory_shortage_repair_plan(self, **kwargs: Any) -> dict[str, Any]:
        plan = self.inventory_autopilot_plan(**kwargs)
        return {
            **plan,
            "schema": "creator_os.inventory_shortage_repair_plan.v1",
            "wouldWrite": False,
        }

    def inventory_buffer_protection_report(self, **kwargs: Any) -> dict[str, Any]:
        plan = self.inventory_autopilot_plan(**kwargs)
        return {
            "schema": "creator_os.inventory_buffer_protection_report.v1",
            "surface": plan["surface"],
            "requiredInventory": plan["requiredInventory"],
            "availableInventory": plan["availableInventory"],
            "daysRemaining": plan["daysRemaining"],
            "shortfall": plan["shortfall"],
            "health": plan["health"],
            "repairActions": plan["repairActions"],
            "wouldWrite": False,
        }

    def inventory_slo_surface_targets(self, minimum_buffer: int) -> dict[str, int]:
        weights = {
            "reel": 0.45,
            "story": 0.35,
            "feed_single": 0.15,
            "feed_carousel": 0.05,
        }
        targets = {
            surface: int(minimum_buffer * weights[surface])
            for surface in self._content_surfaces
        }
        remainder = minimum_buffer - sum(targets.values())
        for surface in self._content_surfaces:
            if remainder <= 0:
                break
            targets[surface] += 1
            remainder -= 1
        return targets

    def inventory_health(self, *, current: int, minimum: int) -> str:
        if current >= minimum:
            return "healthy"
        if current >= math.ceil(minimum * 0.67):
            return "warning"
        return "critical"

    def inventory_stage_counts(
        self, *, creator: str | None = None, campaign_slug: str | None = None
    ) -> dict[str, int]:
        assets = self._surface_report_assets(
            creator=self._creator_label(creator) if creator else None,
            campaign_slug=campaign_slug,
        )
        asset_ids = {asset["id"] for asset in assets}
        if campaign_slug or creator:
            parent_assets = sum(
                1 for asset in assets if not asset.get("parent_asset_id")
            )
            variant_assets = sum(
                1
                for asset in assets
                if asset.get("parent_asset_id") or asset.get("variant_id")
            )
        else:
            parent_assets = int(
                self.conn.execute("SELECT COUNT(*) AS c FROM concepts").fetchone()["c"]
            )
            variant_assets = int(
                self.conn.execute(
                    "SELECT COUNT(*) AS c FROM variant_assets"
                ).fetchone()["c"]
            )
        caption_families = self.inventory_count_related(
            "caption_families", "parent_asset_id", asset_ids
        )
        caption_versions = self.inventory_count_related(
            "caption_versions", "parent_asset_id", asset_ids
        )
        readiness = self._build_surface_readiness(assets)
        schedule_safe = sum(1 for item in readiness if item.get("canHandoff"))
        validated = sum(
            1
            for asset in assets
            if str(asset.get("review_state") or "").lower()
            in {"approved", "review_ready"}
        )
        publishable = sum(
            1
            for asset in assets
            if str(asset.get("audit_status") or "").lower()
            in {"passed", "pass", "approved", "approved_candidate"}
            or str(asset.get("review_state") or "").lower()
            in {"approved", "review_ready"}
        )
        return {
            "parentAssets": parent_assets,
            "captionFamilies": caption_families,
            "captionVersions": caption_versions,
            "variantAssets": variant_assets,
            "validatedAssets": validated,
            "publishableAssets": publishable,
            "scheduleSafeAssets": schedule_safe,
        }

    def inventory_count_related(
        self, table: str, column: str, asset_ids: set[str]
    ) -> int:
        if not asset_ids:
            try:
                return int(
                    self.conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()[
                        "c"
                    ]
                )
            except sqlite3.OperationalError:
                return 0
        placeholders = ",".join("?" for _ in asset_ids)
        try:
            return int(
                self.conn.execute(
                    f"SELECT COUNT(*) AS c FROM {table} WHERE {column} IN ({placeholders})",
                    sorted(asset_ids),
                ).fetchone()["c"]
            )
        except sqlite3.OperationalError:
            return 0

    def inventory_limiting_stage(self, counts: dict[str, int]) -> str:
        if int(counts.get("scheduleSafeAssets") or 0) <= 0:
            return "validated_inventory"
        if int(counts.get("publishableAssets") or 0) < int(
            counts.get("validatedAssets") or 0
        ):
            return "publishability"
        if int(counts.get("validatedAssets") or 0) < int(
            counts.get("variantAssets") or 0
        ):
            return "validation"
        if int(counts.get("variantAssets") or 0) <= 0:
            return "contentforge_variants"
        return "schedule_safe_inventory"

    def inventory_loss_by_stage(self, counts: dict[str, int]) -> dict[str, int]:
        return {
            "parentsWithoutVariants": max(
                0,
                int(counts.get("parentAssets") or 0)
                - int(counts.get("variantAssets") or 0),
            ),
            "variantsNotValidated": max(
                0,
                int(counts.get("variantAssets") or 0)
                - int(counts.get("validatedAssets") or 0),
            ),
            "validatedNotPublishable": max(
                0,
                int(counts.get("validatedAssets") or 0)
                - int(counts.get("publishableAssets") or 0),
            ),
            "publishableNotScheduleSafe": max(
                0,
                int(counts.get("publishableAssets") or 0)
                - int(counts.get("scheduleSafeAssets") or 0),
            ),
        }

    def inventory_repair_actions(self, policy: dict[str, Any]) -> list[dict[str, Any]]:
        shortfall = int(policy.get("shortfall") or 0)
        if shortfall <= 0:
            return []
        surface = str(policy.get("surface") or "reel")
        return [
            {
                "action": "expand_existing_safe_parents"
                if surface == "reel"
                else "register_surface_safe_assets",
                "surface": surface,
                "targetCount": shortfall,
                "reason": "buffer_below_required_inventory",
                "owner": "campaign_factory_operator",
                "wouldWrite": False,
            },
            {
                "action": "repair_blocked_inventory",
                "surface": surface,
                "targetCount": math.ceil(shortfall * 0.2),
                "reason": "recover_publishability_or_metadata_failures_without_lowering_gates",
                "owner": "campaign_factory_operator",
                "wouldWrite": False,
            },
        ]
