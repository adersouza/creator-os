from __future__ import annotations

from typing import Any, Callable


class ParentFactoryPlanningRepository:
    def __init__(
        self,
        *,
        inventory_production_requirements: Callable[..., dict[str, Any]],
        reel_factory_parent_metrics: Callable[[], dict[str, int]],
        parent_factory_yield_waterfall: Callable[..., dict[str, Any]],
        parent_factory_loss_analysis: Callable[..., dict[str, Any]],
    ) -> None:
        self._inventory_production_requirements = inventory_production_requirements
        self._reel_factory_parent_metrics = reel_factory_parent_metrics
        self._parent_factory_yield_waterfall = parent_factory_yield_waterfall
        self._parent_factory_loss_analysis = parent_factory_loss_analysis

    def parent_factory_autopilot_plan(
        self,
        *,
        accounts: int = 200,
        posts_per_account_per_day: int = 3,
    ) -> dict[str, Any]:
        production = self._inventory_production_requirements(
            accounts=accounts,
            posts_per_account_per_day=posts_per_account_per_day,
        )
        required_parents = int(production.get("requiredParentsPerDay") or 0)
        metrics = self._reel_factory_parent_metrics()
        available = int(metrics.get("scheduleSafe") or 0)
        waterfall = self._parent_factory_yield_waterfall(required_parents_per_day=max(1, required_parents or 1))
        shortfall = max(0, required_parents - available)
        return {
            "schema": "creator_os.parent_factory_autopilot_plan.v1",
            "requiredParentsToday": required_parents,
            "availableParents": available,
            "shortfall": shortfall,
            "requiredRawCandidates": int(waterfall.get("requiredRawCandidatesPerDay") or required_parents),
            "requiredCaptionFamilies": required_parents,
            "requiredVariants": int(production.get("requiredVariantsPerDay") or 0),
            "requiredValidatedDrafts": int(production.get("requiredValidatedDraftsPerDay") or 0),
            "largestBottleneck": self._parent_factory_loss_analysis(
                required_parents_per_day=max(1, required_parents or 1),
            ).get("largestLossStage"),
            "nextAction": "produce_or_import_parent_reels" if shortfall else "hold_parent_factory",
            "wouldWrite": False,
        }

    def parent_factory_shortfall_report(self, **kwargs: Any) -> dict[str, Any]:
        plan = self.parent_factory_autopilot_plan(**kwargs)
        return {
            **plan,
            "schema": "creator_os.parent_factory_shortfall_report.v1",
            "canMeetToday": int(plan.get("shortfall") or 0) == 0,
            "wouldWrite": False,
        }

    def parent_factory_production_targets(self, **kwargs: Any) -> dict[str, Any]:
        plan = self.parent_factory_autopilot_plan(**kwargs)
        return {
            "schema": "creator_os.parent_factory_production_targets.v1",
            "requiredParentsToday": plan["requiredParentsToday"],
            "requiredRawCandidates": plan["requiredRawCandidates"],
            "requiredCaptionFamilies": plan["requiredCaptionFamilies"],
            "requiredVariants": plan["requiredVariants"],
            "dailyTargets": {
                "parents": plan["requiredParentsToday"],
                "rawCandidates": plan["requiredRawCandidates"],
                "captionFamilies": plan["requiredCaptionFamilies"],
                "variants": plan["requiredVariants"],
            },
            "wouldWrite": False,
        }
