from __future__ import annotations

import sqlite3
from typing import Any

from campaign_factory.learning_score import (
    learning_eligible_sql,
    learning_loop_cutover_iso,
)

from .persistence import json_load
from .recommendation_constants import (
    RECOMMENDATION_MEASUREMENT_VERSION,
    RECOMMENDATION_STATUS_TRANSITIONS,
)


class RecommendationScoringMixin:
    def validate_recommendation_transition(
        self,
        current_status: str,
        next_status: str,
        *,
        admin_override: bool = False,
        override_reason: str | None = None,
    ) -> None:
        current_status = current_status or "proposed"
        if current_status == next_status:
            return
        if admin_override:
            if not override_reason:
                raise ValueError(
                    "override_reason is required when admin_override is true"
                )
            return
        allowed = RECOMMENDATION_STATUS_TRANSITIONS.get(current_status, set())
        if next_status not in allowed:
            raise ValueError(
                f"invalid recommendation status transition: {current_status} -> {next_status}"
            )

    def recommendation_baseline_payload(
        self,
        baseline_summary: dict[str, Any],
        *,
        baseline_score: int | None,
        threshold: int,
    ) -> dict[str, Any]:
        count = int(baseline_summary.get("count") or 0)
        avg = baseline_summary.get("averages") or {}
        snapshots = []
        latest = baseline_summary.get("latest")
        if latest:
            snapshots.append(latest)
        confidence = (
            "usable" if count >= 3 and baseline_score is not None else "insufficient"
        )
        return {
            "baselineType": "campaign_account_history",
            "sampleSize": count,
            "avgScore": baseline_score,
            "medianScore": None,
            "threshold": threshold,
            "confidence": confidence,
            "averages": avg,
            "rates": baseline_summary.get("rates") or {},
            "latestSnapshot": snapshots[0] if snapshots else None,
            "measurementVersion": RECOMMENDATION_MEASUREMENT_VERSION,
        }

    def recommendation_performance_rows(self, row: dict[str, Any]) -> list[sqlite3.Row]:
        cutover_iso = learning_loop_cutover_iso()
        if cutover_iso is None:
            return []
        predicate = learning_eligible_sql()
        evidence = json_load(row.get("evidence_json"), {})
        links = evidence.get("links") if isinstance(evidence, dict) else {}
        snapshot_id = (
            links.get("performanceSnapshotId") if isinstance(links, dict) else None
        )
        if snapshot_id:
            rows = self.conn.execute(
                "SELECT * FROM performance_snapshots WHERE id = ? AND " + predicate,
                (snapshot_id, cutover_iso),
            ).fetchall()
            if rows:
                return rows
        if row.get("rendered_asset_id"):
            return self.conn.execute(
                "SELECT * FROM performance_snapshots WHERE rendered_asset_id = ? AND "
                + predicate
                + " ORDER BY snapshot_at DESC, created_at DESC",
                (row["rendered_asset_id"], cutover_iso),
            ).fetchall()
        return []

    def best_asset_history_score(self, asset: dict[str, Any]) -> int | None:
        scores = [
            self._performance_quality_score(asset.get("sourcePerformance") or {}),
            self._performance_quality_score(asset.get("captionPerformance") or {}),
            self._performance_quality_score(asset.get("recipePerformance") or {}),
        ]
        available = [score for score in scores if score is not None]
        return max(available) if available else None

    def reference_pattern_score(self, pattern: dict[str, Any] | None) -> int:
        if not pattern:
            return 45
        rank = pattern.get("rank")
        score = 70
        if isinstance(rank, int):
            score = max(50, 92 - min(rank, 50))
        if pattern.get("audioRecommendations"):
            score += 4
        if pattern.get("captionFormulas"):
            score += 4
        if pattern.get("promptTemplate"):
            score += 3
        return int(max(0, min(100, score)))

    def recommendation_account_score(
        self, asset: dict[str, Any], account: str | None
    ) -> int:
        evidence = self.recommendation_account_fit_evidence(
            asset["campaign_id"], asset, account
        )
        if evidence.get("score") is not None:
            return int(evidence["score"])
        assignments = self.assignments_for_asset(asset["id"])
        if account and any(
            account in {row.get("instagram_account_id"), row.get("account_id")}
            for row in assignments
        ):
            return 72
        if assignments:
            return 62
        account_ids = asset.get("account_ids") or []
        if account and account in account_ids:
            return 65
        return 50

    def recommendation_account_fit_evidence(
        self, campaign_id: str, asset: dict[str, Any], account: str | None
    ) -> dict[str, Any]:
        target = account or self.asset_target_account(asset)
        if not target:
            return {
                "level": "low",
                "score": None,
                "reasons": ["missing_account_assignment"],
                "memory": None,
            }
        memory = self._account_memory_for(campaign_id, target)
        if not memory:
            return {
                "level": "low",
                "score": None,
                "account": target,
                "reasons": ["account_memory_missing_or_not_rebuilt"],
                "memory": None,
            }
        score = int(memory.get("performanceScore") or 50)
        fatigue = memory.get("fatigue") or {}
        fatigue_level = fatigue.get("level")
        reasons = [
            f"account memory confidence {memory.get('confidence')} with {memory.get('sampleSize')} samples"
        ]
        if fatigue_level == "high":
            score -= 20
            reasons.append("high account fatigue pressure")
        elif fatigue_level == "medium":
            score -= 10
            reasons.append("medium account fatigue pressure")
        if memory.get("confidence") == "low":
            score = round((score + 50) / 2)
        return {
            "level": memory.get("confidence") or "low",
            "score": int(max(0, min(100, score))),
            "account": target,
            "reasons": reasons,
            "memory": memory,
        }

    def operational_recommendation_score(self, asset: dict[str, Any]) -> int:
        readiness = asset.get("export_readiness") or {}
        if readiness.get("state") == "ready":
            score = 100
        elif readiness.get("state") == "warning":
            score = 65
        else:
            score = 20
        audio = (
            asset.get("audioRecommendations")
            if isinstance(asset.get("audioRecommendations"), dict)
            else {}
        )
        if audio.get("recommendations") or audio.get("primaryStrategy"):
            score += 5
        return int(max(0, min(100, score)))

    def recommendation_confidence(
        self, asset: dict[str, Any], pattern: dict[str, Any] | None
    ) -> tuple[str, str]:
        summaries = [
            asset.get("sourcePerformance") or {},
            asset.get("captionPerformance") or {},
            asset.get("recipePerformance") or {},
        ]
        sample_size = sum(int(summary.get("count") or 0) for summary in summaries)
        completeness = 0
        completeness += 1 if asset.get("latest_audit") else 0
        completeness += 1 if pattern else 0
        completeness += 1 if sample_size else 0
        rendered_asset_id = asset.get("id") or asset.get("renderedAssetId")
        completeness += (
            1
            if asset.get("graphId")
            or self.graph_id_for(
                "rendered_assets", rendered_asset_id, entity_type="rendered_asset"
            )
            else 0
        )
        if sample_size >= 10 and completeness >= 3:
            return (
                "high",
                f"{sample_size} matched performance samples and complete graph/audit context",
            )
        if sample_size >= 3 or completeness >= 3:
            return (
                "medium",
                f"{sample_size} matched performance samples with partial context",
            )
        return (
            "low",
            "Limited performance history; score is mostly quality, readiness, and reference-pattern based",
        )

    def recommendation_data_quality(
        self, asset: dict[str, Any], pattern: dict[str, Any] | None
    ) -> dict[str, Any]:
        summaries = [
            asset.get("sourcePerformance") or {},
            asset.get("captionPerformance") or {},
            asset.get("recipePerformance") or {},
        ]
        sample_size = sum(int(summary.get("count") or 0) for summary in summaries)
        missing = []
        if not sample_size:
            missing.append("performance_history")
        if not asset.get("latest_audit"):
            missing.append("audit_report")
        if not pattern:
            missing.append("reference_pattern")
        rendered_asset_id = asset.get("id") or asset.get("renderedAssetId")
        if not asset.get("graphId") and (
            not self.graph_id_for(
                "rendered_assets", rendered_asset_id, entity_type="rendered_asset"
            )
        ):
            missing.append("rendered_asset_graph_id")
        if sample_size >= 10 and (not missing):
            level = "high"
        elif sample_size >= 3 or len(missing) <= 1:
            level = "medium"
        else:
            level = "low"
        return {
            "level": level,
            "sampleSize": sample_size,
            "missing": missing,
            "hasAudit": bool(asset.get("latest_audit")),
            "hasReferencePattern": bool(pattern),
            "hasGraphEvidence": not bool("rendered_asset_graph_id" in missing),
        }

    def recommendation_reasons(
        self,
        *,
        performance_score: int,
        reference_score: int,
        audit_score: int,
        account_score: int,
        novelty_score: int,
        operational_score: int,
        candidate: dict[str, Any],
        reference_pattern: dict[str, Any] | None,
    ) -> list[str]:
        reasons = list(candidate.get("reasons") or [])
        if performance_score >= 70:
            reasons.append("performance history is positive")
        if reference_score >= 80 and reference_pattern:
            reasons.append(
                f"reference pattern is strong: {reference_pattern.get('label')}"
            )
        if audit_score >= 80:
            reasons.append("ContentForge/readiness quality is strong")
        if account_score > 55:
            reasons.append("account assignment or account fit is available")
        if novelty_score >= 80:
            reasons.append("low reuse/fatigue warning pressure")
        if operational_score >= 80:
            reasons.append("operational gates are ready or near-ready")
        return sorted(set(str(reason) for reason in reasons if reason))

    def asset_target_account(self, asset: dict[str, Any]) -> str | None:
        assignments = self.assignments_for_asset(asset["id"])
        for row in assignments:
            if row.get("instagram_account_id") or row.get("account_id"):
                return row.get("instagram_account_id") or row.get("account_id")
        account_ids = asset.get("account_ids") or []
        return str(account_ids[0]) if account_ids else None

    def recommendation_reference_summary(
        self, pattern: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not pattern:
            return None
        return {
            "id": pattern.get("id"),
            "clusterKey": pattern.get("clusterKey"),
            "rank": pattern.get("rank"),
            "label": pattern.get("label"),
            "visualFormat": pattern.get("visualFormat"),
            "hookType": pattern.get("hookType"),
            "captionArchetype": pattern.get("captionArchetype"),
        }

    def first_suggested_recipe(self, pattern: dict[str, Any] | None) -> str | None:
        recipes = (
            ((pattern or {}).get("raw") or {})
            .get("bank", {})
            .get("suggestedVariantRecipes")
            if pattern
            else []
        )
        if isinstance(recipes, list) and recipes:
            return str(recipes[0])
        suggested = (pattern or {}).get("suggestedVariantRecipes") if pattern else []
        return str(suggested[0]) if isinstance(suggested, list) and suggested else None

    def hook_guidance(
        self, pattern: dict[str, Any] | None, asset: dict[str, Any]
    ) -> str:
        if pattern and pattern.get("hookType"):
            return f"Use a {pattern['hookType']} hook from {pattern.get('label') or pattern.get('clusterKey')}."
        caption = asset.get("caption")
        return (
            f"Adapt the existing hook/caption: {caption[:120]}"
            if caption
            else "Use a proven short curiosity hook."
        )

    def caption_guidance(
        self, pattern: dict[str, Any] | None, asset: dict[str, Any]
    ) -> str:
        formulas = (pattern or {}).get("captionFormulas") or []
        if formulas and isinstance(formulas[0], dict):
            formula = formulas[0].get("formula") or formulas[0].get("label")
            if formula:
                return str(formula)
        caption = asset.get("caption")
        return (
            caption[:160]
            if caption
            else "Keep caption short, native, and matched to the visual pattern."
        )
