from __future__ import annotations

from collections.abc import Callable
from typing import Any


class CreatorOSRecommendationRepository:
    def __init__(
        self,
        *,
        creator_label: Callable[[Any], str],
        build_creative_performance_analysis: Callable[..., dict[str, Any]],
        first_lineage_value: Callable[..., str],
        surface_from_pattern: Callable[[dict[str, Any], dict[str, Any]], str],
        recommendation_explainability: Callable[..., dict[str, Any]],
    ) -> None:
        self._creator_label = creator_label
        self._build_creative_performance_analysis = build_creative_performance_analysis
        self._first_lineage_value = first_lineage_value
        self._surface_from_pattern = surface_from_pattern
        self._recommendation_explainability = recommendation_explainability

    def creator_os_winner_recommendations(
        self,
        *,
        creator: str,
        inventory_shortfall: int,
        variant_available: int,
        winner_expansion_report: dict[str, Any] | None,
        winner_expansion_plan: dict[str, Any] | None,
        variant_metrics_rollup: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if inventory_shortfall <= 0:
            return []
        remaining = max(0, inventory_shortfall - max(0, int(variant_available or 0)))
        recommendations: list[dict[str, Any]] = []
        if variant_available:
            recommendations.append(
                {
                    "parentAssetId": "",
                    "variantFamilyId": "",
                    "reason": "unused_validated_variants_available",
                    "recommendedAction": "fanout_existing_variants",
                    "recommendedVariantCount": min(
                        inventory_shortfall, int(variant_available or 0)
                    ),
                    "wouldWrite": False,
                }
            )
        if remaining <= 0:
            return recommendations

        report_items = []
        if isinstance(winner_expansion_report, dict):
            report_items.extend(
                item
                for item in (winner_expansion_report.get("recommendations") or [])
                if isinstance(item, dict)
            )
            report_items.extend(
                item
                for item in (winner_expansion_report.get("winners") or [])
                if isinstance(item, dict)
            )
        seen: set[str] = set()
        for item in report_items:
            item_creator = self._creator_label(item.get("creator") or creator)
            if item_creator not in {creator, "unknown"}:
                continue
            parent_asset_id = str(
                item.get("parentAssetId")
                or item.get("parent_asset_id")
                or item.get("assetId")
                or item.get("asset_id")
                or ""
            ).strip()
            variant_family_id = str(
                item.get("variantFamilyId") or item.get("variant_family_id") or ""
            ).strip()
            key = f"{parent_asset_id}:{variant_family_id}:{item.get('reason')}"
            if key in seen:
                continue
            seen.add(key)
            recommendations.append(
                {
                    "parentAssetId": parent_asset_id,
                    "variantFamilyId": variant_family_id,
                    "reason": str(item.get("reason") or "manual_winner"),
                    "recommendedAction": self.creator_os_winner_action(
                        item.get("recommendedAction")
                    ),
                    "recommendedVariantCount": remaining,
                    "wouldWrite": False,
                }
            )
            break

        if len(recommendations) == (1 if variant_available else 0) and isinstance(
            winner_expansion_plan, dict
        ):
            can_proceed = bool(
                winner_expansion_plan.get("canProceed")
                or winner_expansion_plan.get("canGenerate")
            )
            if can_proceed:
                recommendations.append(
                    {
                        "parentAssetId": str(
                            winner_expansion_plan.get("parentAssetId")
                            or winner_expansion_plan.get("parent_asset_id")
                            or ""
                        ),
                        "variantFamilyId": str(
                            winner_expansion_plan.get("variantFamilyId")
                            or winner_expansion_plan.get("variant_family_id")
                            or ""
                        ),
                        "reason": "winner_expansion_plan_available",
                        "recommendedAction": "generate_more_variants",
                        "recommendedVariantCount": remaining,
                        "wouldWrite": False,
                    }
                )

        if len(recommendations) == (1 if variant_available else 0) and isinstance(
            variant_metrics_rollup, dict
        ):
            family = self.creator_os_best_rollup_family(variant_metrics_rollup)
            if family:
                recommendations.append(
                    {
                        "parentAssetId": str(family.get("parentAssetId") or ""),
                        "variantFamilyId": str(family.get("variantFamilyId") or ""),
                        "reason": "high_views",
                        "recommendedAction": "generate_more_variants",
                        "recommendedVariantCount": remaining,
                        "wouldWrite": False,
                    }
                )
        return recommendations

    def creator_os_winner_action(self, value: Any) -> str:
        raw = str(value or "").strip()
        mapping = {
            "create_more_variants": "generate_more_variants",
            "generate_more_variants": "generate_more_variants",
            "fan_out_existing_variants": "fanout_existing_variants",
            "fanout_existing_variants": "fanout_existing_variants",
            "make_similar_reel_factory_content": "make_similar_reel",
            "make_similar_reel": "make_similar_reel",
            "hold": "hold",
        }
        return mapping.get(raw, "generate_more_variants")

    def creator_os_best_rollup_family(
        self, variant_metrics_rollup: dict[str, Any]
    ) -> dict[str, Any] | None:
        families = [
            item
            for item in (variant_metrics_rollup.get("families") or [])
            if isinstance(item, dict)
        ]
        if not families:
            return None

        def views(item: dict[str, Any]) -> int:
            try:
                return int(
                    (((item.get("performance") or {}).get("totals") or {}).get("views"))
                    or 0
                )
            except (TypeError, ValueError):
                return 0

        winner = max(families, key=views)
        if views(winner) <= 0:
            return None
        return winner

    def creator_os_recommended_inventory(
        self, *, creator: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        analysis = self._build_creative_performance_analysis(
            creator=creator,
            minimum_sample_size=3,
            limit=max(limit, 10),
        )
        if analysis.get("insufficientData"):
            return []
        recommendations: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for pattern in analysis.get("bestPerformingPatterns") or []:
            if not isinstance(pattern, dict):
                continue
            lineage = (
                pattern.get("lineage")
                if isinstance(pattern.get("lineage"), dict)
                else {}
            )
            dimension = str(pattern.get("dimension") or "")
            concept_id = (
                str(pattern.get("key") or "")
                if dimension == "concept"
                else self._first_lineage_value(lineage, "conceptIds")
            )
            caption_angle = (
                str(pattern.get("key") or "")
                if dimension == "captionAngle"
                else self._first_lineage_value(lineage, "captionAngles")
            )
            audio_id = (
                str(pattern.get("key") or "")
                if dimension == "audioId"
                else self._first_lineage_value(lineage, "audioIds")
            )
            story_intent = (
                str(pattern.get("key") or "") if dimension == "storyIntent" else ""
            )
            posting_window = (
                str(pattern.get("key") or "")
                if dimension == "postingWindow"
                else self.creator_os_lineage_posting_window(pattern)
            )
            surface = self._surface_from_pattern(pattern, lineage)
            key = (surface, concept_id, caption_angle, audio_id, story_intent)
            if key in seen:
                continue
            seen.add(key)
            recommendations.append(
                {
                    "sourceSystem": "campaign_factory.creative_performance_analysis",
                    "surface": surface,
                    "reason": pattern.get("reason")
                    or "Pattern outperformed creator baseline.",
                    "confidence": analysis.get("confidence") or "low",
                    "conceptId": concept_id,
                    "captionAngle": caption_angle,
                    "postingWindow": posting_window,
                    "audioId": audio_id,
                    "storyIntent": story_intent,
                    "parentAssetId": self._first_lineage_value(
                        lineage, "parentAssetIds"
                    ),
                    "sampleSize": int(pattern.get("sampleSize") or 0),
                    "baselineMetric": pattern.get("baselineMetric") or "score",
                    "observedMetric": pattern.get("observedMetric") or "score",
                    "scoreLiftPct": pattern.get("scoreLiftPct") or 0,
                    "explainability": self._recommendation_explainability(
                        {
                            "reason": pattern.get("reason")
                            or "Pattern outperformed creator baseline.",
                            "confidence": analysis.get("confidence") or "low",
                            "sampleSize": int(pattern.get("sampleSize") or 0),
                            "baselineMetric": pattern.get("baselineMetric") or "score",
                            "observedMetric": pattern.get("observedMetric") or "score",
                            "scoreLiftPct": pattern.get("scoreLiftPct") or 0,
                        },
                        item=pattern,
                        confidence=analysis.get("confidence") or "low",
                    ),
                    "wouldWrite": False,
                }
            )
            if len(recommendations) >= max(1, int(limit or 5)):
                break
        return recommendations

    def creator_os_lineage_posting_window(self, pattern: dict[str, Any]) -> str:
        lineage = (
            pattern.get("lineage") if isinstance(pattern.get("lineage"), dict) else {}
        )
        windows = (
            lineage.get("postingWindows")
            if isinstance(lineage.get("postingWindows"), list)
            else []
        )
        return str(windows[0]) if windows else ""
