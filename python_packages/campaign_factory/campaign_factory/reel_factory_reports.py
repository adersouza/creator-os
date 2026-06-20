from __future__ import annotations

import math
import sqlite3
from typing import Any, Callable

from .caption_outcome import load_context_json


class ReelFactoryReportRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        build_surface_readiness: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        inventory_count_related: Callable[[str, str, set[str]], int],
        inventory_production_requirements: Callable[..., dict[str, Any]],
        ratio: Callable[[Any, Any], float],
    ) -> None:
        self.conn = conn
        self._build_surface_readiness = build_surface_readiness
        self._inventory_count_related = inventory_count_related
        self._inventory_production_requirements = inventory_production_requirements
        self._ratio = ratio

    def reel_factory_parent_throughput_proof(
        self,
        *,
        required_parents_per_day: int = 53,
        lookback_days: int = 1,
    ) -> dict[str, Any]:
        required = max(1, int(required_parents_per_day or 53))
        metrics = self.reel_factory_parent_metrics()
        yield_report = self.reel_factory_yield_analysis(metrics=metrics)
        capacity = self.reel_factory_capacity_model(required_parents_per_day=required)
        overall_rate = float(yield_report.get("overallYieldRate") or 0)
        required_raw = math.ceil(required / overall_rate) if overall_rate > 0 else int(capacity["passRateScenarios"]["60%"])
        schedule_safe_count = int(metrics["scheduleSafe"])
        daily_capacity = schedule_safe_count // max(1, int(lookback_days or 1))
        can_produce = daily_capacity >= required and overall_rate >= 0.60
        return {
            "schema": "creator_os.reel_factory_parent_throughput_proof.v1",
            "canProduce53QualityParentsPerDay": bool(can_produce and required == 53),
            "canProduceRequiredQualityParentsPerDay": bool(can_produce),
            "confidence": self.reel_factory_confidence(metrics),
            "limitingStep": yield_report.get("largestDropoff") or "raw_candidate_supply",
            "requiredParentsPerDay": required,
            "measuredParentCapacityPerDay": daily_capacity,
            "requiredRawCandidatesPerDay": required_raw,
            "qualityParentPassRate": float(yield_report.get("qcPassRate") or 0),
            "publishabilityPassRate": float(yield_report.get("publishabilityPassRate") or 0),
            "captionFamilyEligibleRate": float(yield_report.get("captionFamilyEligibleRate") or 0),
            "audioValidRate": float(yield_report.get("audioValidRate") or 0),
            "handoffReadyRate": float(yield_report.get("handoffReadyRate") or 0),
            "operatorReviewMinutesPerParent": self.operator_review_minutes_per_parent(metrics),
            "intake": self.reel_factory_intake_metrics(metrics),
            "parentCreation": self.reel_factory_parent_creation_metrics(metrics),
            "qualityGates": self.reel_factory_quality_gate_metrics(yield_report),
            "operationalReadiness": self.reel_factory_operational_readiness_metrics(yield_report),
            "humanCost": self.reel_factory_human_cost(metrics),
            "yieldFunnel": yield_report.get("funnel") or [],
            "wouldWrite": False,
        }

    def reel_factory_yield_analysis(self, *, metrics: dict[str, int] | None = None) -> dict[str, Any]:
        values = metrics or self.reel_factory_parent_metrics()
        funnel = [
            {"stage": "raw_candidates", "count": int(values["rawCandidates"])},
            {"stage": "parent_candidates", "count": int(values["parentCandidates"])},
            {"stage": "qc_pass", "count": int(values["qcPass"])},
            {"stage": "publishability_pass", "count": int(values["publishabilityPass"])},
            {"stage": "handoff_ready", "count": int(values["handoffReady"])},
            {"stage": "schedule_safe", "count": int(values["scheduleSafe"])},
        ]
        transitions = []
        for before, after in zip(funnel, funnel[1:]):
            rate = self._ratio(after["count"], before["count"])
            transitions.append({
                "from": before["stage"],
                "to": after["stage"],
                "fromCount": before["count"],
                "toCount": after["count"],
                "yieldRate": rate,
                "yieldPct": round(rate * 100, 1),
                "lost": max(0, before["count"] - after["count"]),
            })
        non_zero = [row for row in transitions if row["fromCount"] > 0]
        largest_dropoff_row = min(non_zero, key=lambda row: row["yieldRate"]) if non_zero else transitions[0]
        overall_rate = self._ratio(funnel[-1]["count"], funnel[0]["count"])
        return {
            "schema": "creator_os.reel_factory_yield_analysis.v1",
            "funnel": funnel,
            "transitions": transitions,
            "overallYieldRate": overall_rate,
            "overallYieldPct": round(overall_rate * 100, 1),
            "rawCandidateToParentRate": self._ratio(values["parentCandidates"], values["rawCandidates"]),
            "qcPassRate": self._ratio(values["qcPass"], values["parentCandidates"]),
            "publishabilityPassRate": self._ratio(values["publishabilityPass"], values["qcPass"]),
            "captionFamilyEligibleRate": self._ratio(values["captionFamilyEligible"], values["parentCandidates"]),
            "audioValidRate": self._ratio(values["audioValid"], values["parentCandidates"]),
            "handoffReadyRate": self._ratio(values["handoffReady"], values["publishabilityPass"]),
            "scheduleSafeRate": self._ratio(values["scheduleSafe"], values["handoffReady"]),
            "largestDropoff": largest_dropoff_row["to"],
            "wouldWrite": False,
        }

    def reel_factory_failure_analysis(self) -> dict[str, Any]:
        metrics = self.reel_factory_parent_metrics()
        yield_report = self.reel_factory_yield_analysis(metrics=metrics)
        lost_by_stage = {
            row["to"]: int(row["lost"])
            for row in yield_report.get("transitions") or []
        }
        failure_specs = [
            ("source_acquisition", max(0, 53 - int(metrics["rawCandidates"])), "high", 0),
            ("render_throughput", lost_by_stage.get("parent_candidates", 0), "high", 8),
            ("quality_review", lost_by_stage.get("qc_pass", 0), "high", 6),
            ("publishability", lost_by_stage.get("publishability_pass", 0), "high", 12),
            ("handoff_readiness", lost_by_stage.get("handoff_ready", 0), "medium", 5),
            ("schedule_safe_inventory", lost_by_stage.get("schedule_safe", 0), "medium", 4),
        ]
        failures = [
            {
                "failure": failure,
                "frequency": frequency,
                "impact": impact,
                "repairCostMinutes": repair,
                "operationalImpactScore": frequency * max(1, repair),
            }
            for failure, frequency, impact, repair in failure_specs
        ]
        failures = sorted(failures, key=lambda item: (-int(item["operationalImpactScore"]), item["failure"]))
        what_breaks = failures[0]["failure"] if failures else "unknown"
        return {
            "schema": "creator_os.reel_factory_failure_analysis.v1",
            "failures": failures,
            "whatBreaksFirst": what_breaks,
            "categories": [
                "generation_throughput",
                "render_throughput",
                "quality_review",
                "audio_validation",
                "caption_placement",
                "publishability",
                "operator_review",
                "handoff_readiness",
                "inventory_management",
            ],
            "wouldWrite": False,
        }

    def reel_factory_capacity_model(self, *, required_parents_per_day: int = 53) -> dict[str, Any]:
        required = max(1, int(required_parents_per_day or 53))
        scenarios = {
            "95%": math.ceil(required / 0.95),
            "90%": math.ceil(required / 0.90),
            "80%": math.ceil(required / 0.80),
            "70%": math.ceil(required / 0.70),
            "60%": math.ceil(required / 0.60),
        }
        return {
            "schema": "creator_os.reel_factory_capacity_model.v1",
            "requiredParentsPerDay": required,
            "passRateScenarios": scenarios,
            "wouldWrite": False,
        }

    def reel_factory_200_account_readiness(self) -> dict[str, Any]:
        scaling = {}
        for accounts in (25, 50, 100, 200, 500):
            production = self._inventory_production_requirements(accounts=accounts, posts_per_account_per_day=3)
            proof = self.reel_factory_parent_throughput_proof(required_parents_per_day=int(production["requiredParentsPerDay"]))
            scaling[f"{accounts}Accounts"] = {
                "accounts": accounts,
                "requiredParentsPerDay": int(production["requiredParentsPerDay"]),
                "requiredValidatedDraftsPerDay": int(production["requiredValidatedDraftsPerDay"]),
                "requiredInventoryBuffer": int(production["postsPerDay"]) * 3,
                "largestBottleneck": proof["limitingStep"],
                "confidence": proof["confidence"],
                "canSupport": bool(proof["canProduceRequiredQualityParentsPerDay"]),
                "wouldWrite": False,
            }
        return {
            "schema": "creator_os.reel_factory_200_account_readiness.v1",
            "requiredParentsPerDay": scaling["200Accounts"]["requiredParentsPerDay"],
            "scalingAnalysis": scaling,
            "wouldWrite": False,
        }

    def reel_factory_master_report(self) -> dict[str, Any]:
        proof = self.reel_factory_parent_throughput_proof(required_parents_per_day=53)
        yield_report = self.reel_factory_yield_analysis()
        failure = self.reel_factory_failure_analysis()
        capacity = self.reel_factory_capacity_model(required_parents_per_day=53)
        readiness = self.reel_factory_200_account_readiness()
        final = {
            "currentParentFactoryRating": self.reel_factory_rating(proof),
            "canSupport200Accounts": bool(proof["canProduce53QualityParentsPerDay"]),
            "requiredParentsPerDay": 53,
            "requiredRawCandidatesPerDay": int(proof["requiredRawCandidatesPerDay"]),
            "largestBottleneck": str(proof["limitingStep"]),
            "largestHumanBottleneck": "operator_review" if proof["operatorReviewMinutesPerParent"] > 0 else "quality_review_capacity_unproven",
            "largestTechnicalBottleneck": str(proof["limitingStep"]),
            "recommendedNextSprint": "run_measured_reel_factory_53_parent_day_throughput_trial",
        }
        return {
            "schema": "creator_os.reel_factory_master_report.v1",
            "parentThroughputProof": proof,
            "yieldAnalysis": yield_report,
            "failureAnalysis": failure,
            "capacityModel": capacity,
            "readinessAtScale": readiness,
            "finalVerdict": final,
            "wouldWrite": False,
        }

    def reel_factory_parent_metrics(self) -> dict[str, int]:
        source_rows = [dict(row) for row in self.conn.execute("SELECT * FROM source_assets WHERE content_surface = 'reel' OR content_surface IS NULL").fetchall()]
        render_rows = [dict(row) for row in self.conn.execute("SELECT * FROM render_jobs").fetchall()]
        asset_rows = [
            dict(row)
            for row in self.conn.execute("SELECT * FROM rendered_assets WHERE content_surface = 'reel' OR content_surface IS NULL").fetchall()
        ]
        parent_assets = [row for row in asset_rows if not row.get("parent_asset_id")]
        readiness = self._build_surface_readiness(parent_assets)
        parent_ids = {row["id"] for row in parent_assets}
        caption_family_count = self._inventory_count_related("caption_families", "parent_asset_id", parent_ids)
        concepts_count = self._inventory_count_related("concepts", "parent_asset_id", parent_ids)
        raw_candidates = max(len(source_rows), len(render_rows), len(parent_assets))
        parent_candidates = len(parent_assets)
        qc_pass = sum(1 for row in parent_assets if self.reel_factory_parent_qc_pass(row))
        explicit_publishability_pass = sum(1 for item in readiness if (item.get("publishability") or {}).get("publishableCandidate"))
        handoff_ready = sum(1 for item in readiness if item.get("handoffManifest") or item.get("handoffManifestV2"))
        schedule_safe = sum(1 for item in readiness if item.get("canHandoff"))
        publishability_pass = max(explicit_publishability_pass, handoff_ready, schedule_safe)
        qc_pass = max(qc_pass, publishability_pass)
        audio_valid = sum(1 for item in readiness if (item.get("publishability") or {}).get("checks", {}).get("embedded_audio_verified") is not False)
        return {
            "rawCandidates": raw_candidates,
            "sourceAssets": len(source_rows),
            "renderJobs": len(render_rows),
            "renderedJobs": sum(1 for row in render_rows if str(row.get("status") or "").lower() in {"rendered", "completed", "synced"}),
            "generationFailures": sum(1 for row in render_rows if str(row.get("status") or "").lower() in {"failed", "error"}),
            "parentCandidates": parent_candidates,
            "qcPass": qc_pass,
            "publishabilityPass": publishability_pass,
            "captionFamilyEligible": caption_family_count if caption_family_count else concepts_count,
            "audioValid": min(audio_valid, parent_candidates),
            "handoffReady": handoff_ready,
            "scheduleSafe": schedule_safe,
            "reviewQueue": sum(1 for row in parent_assets if str(row.get("review_state") or "").lower() not in {"approved", "review_ready"}),
        }

    def reel_factory_parent_qc_pass(self, asset: dict[str, Any]) -> bool:
        context = load_context_json(asset.get("caption_outcome_context_json"))
        placement = context.get("captionPlacementDecision") if isinstance(context, dict) else {}
        placement_pass = (
            not placement
            or str(placement.get("status") or "").lower() in {"passed", "pass", "ok"}
        )
        has_caption = bool(str(asset.get("caption") or "").strip())
        has_hash = bool(asset.get("content_hash"))
        approved = str(asset.get("review_state") or "").lower() in {"approved", "review_ready"}
        return bool(has_caption and has_hash and approved and placement_pass)

    def reel_factory_confidence(self, metrics: dict[str, int]) -> str:
        raw = int(metrics.get("rawCandidates") or 0)
        if raw >= 100:
            return "high"
        if raw >= 25:
            return "medium"
        return "low"

    def operator_review_minutes_per_parent(self, metrics: dict[str, int]) -> float:
        parents = max(1, int(metrics.get("parentCandidates") or 0))
        review_queue = int(metrics.get("reviewQueue") or 0)
        return round((review_queue * 3) / parents, 1)

    def reel_factory_intake_metrics(self, metrics: dict[str, int]) -> dict[str, Any]:
        raw = int(metrics.get("rawCandidates") or 0)
        return {
            "sourceReelAcquisitionRate": raw,
            "importSuccessRate": self._ratio(metrics.get("sourceAssets"), raw),
            "downloadSuccessRate": self._ratio(metrics.get("sourceAssets"), raw),
            "metadataExtractionSuccessRate": self._ratio(metrics.get("sourceAssets"), raw),
            "wouldWrite": False,
        }

    def reel_factory_parent_creation_metrics(self, metrics: dict[str, int]) -> dict[str, Any]:
        raw = int(metrics.get("rawCandidates") or 0)
        render_jobs = int(metrics.get("renderJobs") or 0)
        rendered = int(metrics.get("renderedJobs") or 0)
        return {
            "rawCandidatesCreatedPerDay": raw,
            "parentsGeneratedPerDay": int(metrics.get("parentCandidates") or 0),
            "generationFailures": int(metrics.get("generationFailures") or 0),
            "renderFailures": max(0, render_jobs - rendered - int(metrics.get("generationFailures") or 0)),
            "retryRate": self._ratio(max(0, render_jobs - rendered), render_jobs),
            "wouldWrite": False,
        }

    def reel_factory_quality_gate_metrics(self, yield_report: dict[str, Any]) -> dict[str, Any]:
        return {
            "visualQcPassRate": yield_report.get("qcPassRate") or 0,
            "captionBurnCorrectnessPassRate": yield_report.get("qcPassRate") or 0,
            "captionPlacementPassRate": yield_report.get("qcPassRate") or 0,
            "audioValidationPassRate": yield_report.get("audioValidRate") or 0,
            "discoverabilitySafetyPassRate": yield_report.get("publishabilityPassRate") or 0,
            "publishabilityPassRate": yield_report.get("publishabilityPassRate") or 0,
            "wouldWrite": False,
        }

    def reel_factory_operational_readiness_metrics(self, yield_report: dict[str, Any]) -> dict[str, Any]:
        return {
            "handoffReadyRate": yield_report.get("handoffReadyRate") or 0,
            "manifestReadyRate": yield_report.get("handoffReadyRate") or 0,
            "distributionPlanReadyRate": yield_report.get("scheduleSafeRate") or 0,
            "scheduleSafeRate": yield_report.get("scheduleSafeRate") or 0,
            "wouldWrite": False,
        }

    def reel_factory_human_cost(self, metrics: dict[str, int]) -> dict[str, Any]:
        review_minutes = self.operator_review_minutes_per_parent(metrics)
        failed = max(0, int(metrics.get("parentCandidates") or 0) - int(metrics.get("scheduleSafe") or 0))
        return {
            "operatorReviewTimePerParent": review_minutes,
            "operatorRepairTimePerFailedParent": 12,
            "operatorReviewQueueGrowth": failed,
            "wouldWrite": False,
        }

    def reel_factory_rating(self, proof: dict[str, Any]) -> float:
        score = 0.0
        score += 2.0 if proof.get("confidence") == "high" else (1.0 if proof.get("confidence") == "medium" else 0.3)
        score += min(2.0, float(proof.get("qualityParentPassRate") or 0) * 2)
        score += min(2.0, float(proof.get("publishabilityPassRate") or 0) * 2)
        score += min(2.0, float(proof.get("handoffReadyRate") or 0) * 2)
        score += 2.0 if proof.get("canProduceRequiredQualityParentsPerDay") else 0.0
        return round(min(10.0, score), 1)
