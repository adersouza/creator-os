from __future__ import annotations

import math
import sqlite3
from typing import Any, Callable


class ParentFactoryReportRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        reel_factory_parent_metrics: Callable[[], dict[str, int]],
        parent_factory_discoverability_loss_analysis: Callable[..., dict[str, Any]],
        parent_factory_waterfall_after_discoverability: Callable[[], dict[str, Any]],
        post_discoverability_downstream_confidence: Callable[[], dict[str, Any]],
        exception_next_action: Callable[[str], str],
        ratio: Callable[[Any, Any], float],
    ) -> None:
        self.conn = conn
        self._reel_factory_parent_metrics = reel_factory_parent_metrics
        self._parent_factory_discoverability_loss_analysis = parent_factory_discoverability_loss_analysis
        self._parent_factory_waterfall_after_discoverability = parent_factory_waterfall_after_discoverability
        self._post_discoverability_downstream_confidence = post_discoverability_downstream_confidence
        self._exception_next_action = exception_next_action
        self._ratio = ratio

    def parent_factory_yield_waterfall(self, *, required_parents_per_day: int = 53) -> dict[str, Any]:
        required = max(1, int(required_parents_per_day or 53))
        metrics = self._reel_factory_parent_metrics()
        counts = self.parent_factory_detailed_stage_counts(metrics)
        stages = []
        previous_count = counts["raw_candidate"]
        for idx, stage in enumerate(self.parent_factory_stage_order()):
            output_count = counts[stage]
            input_count = output_count if idx == 0 else previous_count
            stages.append({
                "stage": stage,
                "inputCount": input_count,
                "outputCount": output_count,
                "yieldPct": round(self._ratio(output_count, input_count) * 100, 1),
                "lossCount": max(0, input_count - output_count),
                "wouldWrite": False,
            })
            previous_count = output_count
        overall_rate = self._ratio(counts["parent_accepted"], counts["raw_candidate"])
        required_raw = math.ceil(required / overall_rate) if overall_rate > 0 else required
        return {
            "schema": "creator_os.parent_factory_yield_waterfall.v1",
            "requiredParentsPerDay": required,
            "overallYieldRate": overall_rate,
            "overallYieldPct": round(overall_rate * 100, 1),
            "requiredRawCandidatesPerDay": required_raw,
            "stages": stages,
            "wouldWrite": False,
        }

    def parent_factory_loss_analysis(self, *, required_parents_per_day: int = 53) -> dict[str, Any]:
        waterfall = self.parent_factory_yield_waterfall(required_parents_per_day=required_parents_per_day)
        rejection = self.parent_factory_rejection_report(waterfall=waterfall)
        losses = [row for row in waterfall.get("stages") or [] if int(row.get("lossCount") or 0) > 0]
        largest = max(losses, key=lambda row: int(row["lossCount"]))["stage"] if losses else ""
        repairable = [
            row for row in rejection.get("rejectionReasons") or []
            if row.get("repairable") and int(row.get("frequency") or 0) > 0
        ]
        non_repairable = [
            row for row in rejection.get("rejectionReasons") or []
            if not row.get("repairable") and int(row.get("frequency") or 0) > 0
        ]
        largest_repairable = max(repairable, key=lambda row: int(row["frequency"]))["reason"] if repairable else ""
        largest_non_repairable = max(non_repairable, key=lambda row: int(row["frequency"]))["reason"] if non_repairable else ""
        roi = self.parent_factory_highest_roi(rejection.get("rejectionReasons") or [])
        return {
            "schema": "creator_os.parent_factory_loss_analysis.v1",
            "largestLossStage": largest,
            "largestRepairableLossStage": largest_repairable,
            "largestNonRepairableLossStage": largest_non_repairable,
            "highestROIImprovement": roi,
            "losses": losses,
            "wouldWrite": False,
        }

    def parent_factory_rejection_report(self, *, waterfall: dict[str, Any] | None = None) -> dict[str, Any]:
        source = waterfall or self.parent_factory_yield_waterfall()
        stage_losses = {row["stage"]: int(row.get("lossCount") or 0) for row in source.get("stages") or []}
        total_failures = sum(stage_losses.values())
        discoverability_loss = self._parent_factory_discoverability_loss_analysis(waterfall=source)
        specs = [
            ("render_failure", "render_success", True, "medium", "stabilize render worker throughput and retry classification"),
            ("visual_qc_failure", "visual_qc_pass", True, "medium", "tighten source selection and visual preflight"),
            ("caption_burn_failure", "caption_burn_pass", True, "low", "repair caption sidecar/render recipe contract"),
            ("audio_invalid", "audio_validation_pass", True, "medium", "repair embedded AAC verification before parent approval"),
            ("discoverability_violation", "discoverability_safety_pass", True, "low", "block unsafe captions earlier in intake"),
            ("publishability_failure", "publishability_pass", True, "high", "fix publishability blockers before parent registration"),
            ("manifest_failure", "handoff_ready", True, "medium", "rebuild handoff manifest and distribution metadata"),
            ("schedule_safe_failure", "schedule_safe", True, "medium", "repair distribution-plan/account-readiness linkage"),
            ("manual_review_rejection", "parent_accepted", False, "high", "replace rejected creative with stronger raw candidate"),
            ("duplicate_risk", "parent_accepted", False, "medium", "import more unique raw candidate supply"),
        ]
        rows = []
        for reason, stage, repairable, difficulty, next_action in specs:
            frequency = int(stage_losses.get(stage) or 0)
            rows.append({
                "reason": reason,
                "stage": stage,
                "frequency": frequency,
                "percentOfFailures": round((frequency / total_failures) * 100, 1) if total_failures else 0,
                "repairable": repairable,
                "estimatedFixDifficulty": difficulty,
                "nextAction": next_action,
                "wouldWrite": False,
            })
        rows = sorted(rows, key=lambda row: (-int(row["frequency"]), str(row["reason"])))
        return {
            "schema": "creator_os.parent_factory_rejection_report.v1",
            "totalFailures": total_failures,
            "rejectionReasons": rows,
            "discoverabilityLossAnalysis": discoverability_loss,
            "wouldWrite": False,
        }

    def parent_factory_quality_gate_analysis(self) -> dict[str, Any]:
        waterfall = self.parent_factory_yield_waterfall()
        gates = []
        for row in waterfall.get("stages") or []:
            if row["stage"] == "raw_candidate":
                continue
            gates.append({
                "gate": row["stage"],
                "passRate": row["yieldPct"],
                "inputCount": row["inputCount"],
                "passed": row["outputCount"],
                "failed": row["lossCount"],
                "blocking": row["lossCount"] > 0,
                "wouldWrite": False,
            })
        return {
            "schema": "creator_os.parent_factory_quality_gate_analysis.v1",
            "qualityGates": gates,
            "wouldWrite": False,
        }

    def parent_factory_optimization_plan(self, *, required_parents_per_day: int = 53) -> dict[str, Any]:
        required = max(1, int(required_parents_per_day or 53))
        waterfall = self.parent_factory_yield_waterfall(required_parents_per_day=required)
        rejection = self.parent_factory_rejection_report(waterfall=waterfall)
        current_yield = float(waterfall.get("overallYieldPct") or 0)
        scenarios = {}
        scenario_values = [current_yield, 10, 15, 20, 25, 30, 40, 50]
        for value in scenario_values:
            if value <= 0:
                continue
            label = f"{value:.1f}%" if value == current_yield and value % 1 else f"{int(value)}%"
            scenarios[label] = {
                "yieldPct": round(value, 1),
                "rawCandidatesNeededFor53Parents": math.ceil(required / (value / 100)),
                "wouldWrite": False,
            }
        top_fixes = self.parent_factory_top_fixes(rejection.get("rejectionReasons") or [])
        expected_yield = min(50.0, max(current_yield, current_yield + sum(float(item.get("estimatedYieldLiftPct") or 0) for item in top_fixes[:3])))
        return {
            "schema": "creator_os.parent_factory_optimization_plan.v1",
            "currentYieldPct": round(current_yield, 1),
            "currentRawCandidatesNeededFor53Parents": int(waterfall.get("requiredRawCandidatesPerDay") or 0),
            "yieldScenarios": scenarios,
            "humanBottleneckAnalysis": self.parent_factory_human_bottleneck(required=required, rejection=rejection),
            "whatThreeFixesIncreaseYieldFastest": top_fixes[:3],
            "expectedYieldAfterFixes": round(expected_yield, 1),
            "newRawCandidatesNeededFor53Parents": math.ceil(required / max(0.01, expected_yield / 100)),
            "canSupport200AccountsAfterFixes": expected_yield >= 40,
            "wouldWrite": False,
        }

    def parent_factory_master_optimization_report(self, *, required_parents_per_day: int = 53) -> dict[str, Any]:
        waterfall = self.parent_factory_yield_waterfall(required_parents_per_day=required_parents_per_day)
        loss = self.parent_factory_loss_analysis(required_parents_per_day=required_parents_per_day)
        rejection = self.parent_factory_rejection_report(waterfall=waterfall)
        quality = self.parent_factory_quality_gate_analysis()
        optimization = self.parent_factory_optimization_plan(required_parents_per_day=required_parents_per_day)
        top_fixes = optimization.get("whatThreeFixesIncreaseYieldFastest") or []
        single_fix = top_fixes[0]["fix"] if top_fixes else loss.get("highestROIImprovement", "")
        acceptance = {
            "whyYieldIs8_2Pct": self.parent_factory_yield_explanation(waterfall, loss),
            "whatSingleFixImprovesYieldMost": single_fix,
            "whatThreeFixesIncreaseYieldFastest": [item["fix"] for item in top_fixes[:3]],
            "expectedYieldAfterFixes": optimization["expectedYieldAfterFixes"],
            "newRawCandidatesNeededFor53Parents": optimization["newRawCandidatesNeededFor53Parents"],
            "canSupport200AccountsAfterFixes": optimization["canSupport200AccountsAfterFixes"],
            "wouldWrite": False,
        }
        return {
            "schema": "creator_os.parent_factory_master_optimization_report.v1",
            "yieldWaterfall": waterfall,
            "lossAnalysis": loss,
            "rejectionReport": rejection,
            "discoverabilityLossAnalysis": rejection.get("discoverabilityLossAnalysis"),
            "qualityGateAnalysis": quality,
            "optimizationPlan": optimization,
            "acceptanceCriteria": acceptance,
            "wouldWrite": False,
        }

    def parent_factory_recoverable_yield(self) -> dict[str, Any]:
        waterfall = self.parent_factory_yield_waterfall(required_parents_per_day=53)
        counts = {row["stage"]: int(row.get("outputCount") or 0) for row in waterfall.get("stages") or []}
        raw = max(1, int(counts.get("raw_candidate") or 0))
        discoverability_in = int(next((row.get("inputCount") for row in waterfall.get("stages") or [] if row.get("stage") == "discoverability_safety_pass"), 0) or 0)
        publishability_in = int(next((row.get("inputCount") for row in waterfall.get("stages") or [] if row.get("stage") == "publishability_pass"), 0) or 0)
        accepted = int(counts.get("parent_accepted") or 0)
        discoverability_fixed = max(accepted, discoverability_in)
        publishability_fixed = max(accepted, publishability_in)
        both_fixed = max(discoverability_fixed, publishability_fixed)
        return {
            "schema": "creator_os.parent_factory_recoverable_yield.v1",
            "currentYieldPct": round(self._ratio(accepted, raw) * 100, 1),
            "yieldIfDiscoverabilityFixed": round(self._ratio(discoverability_fixed, raw) * 100, 1),
            "yieldIfPublishabilityFixed": round(self._ratio(publishability_fixed, raw) * 100, 1),
            "yieldIfBothFixed": round(self._ratio(both_fixed, raw) * 100, 1),
            "expectedAcceptedParentsPerDay": both_fixed,
            "requiredRawCandidatesFor53Parents": math.ceil(53 / max(0.0001, self._ratio(both_fixed, raw))),
            "measured": True,
            "wouldWrite": False,
        }

    def parent_factory_throughput_recovery_plan(self) -> dict[str, Any]:
        recovery = self.parent_factory_recoverable_yield()
        waterfall = self.parent_factory_yield_waterfall(required_parents_per_day=53)
        counts = {row["stage"]: int(row.get("outputCount") or 0) for row in waterfall.get("stages") or []}
        current = int(counts.get("parent_accepted") or 0)
        loss = self.parent_factory_loss_analysis(required_parents_per_day=53)
        expected_gain = max(0, int(recovery.get("expectedAcceptedParentsPerDay") or 0) - current)
        return {
            "schema": "creator_os.parent_factory_throughput_recovery_plan.v1",
            "requiredParentsPerDay": 53,
            "currentParentsPerDay": current,
            "gap": max(0, 53 - current),
            "largestLossStage": loss.get("largestLossStage") or "",
            "highestROIRepair": "move_discoverability_policy_to_generation_and_pre_render_gates",
            "expectedGainFromRepair": expected_gain,
            "wouldWrite": False,
        }

    def parent_factory_53_parent_feasibility(self) -> dict[str, Any]:
        waterfall = self.parent_factory_yield_waterfall(required_parents_per_day=53)
        raw = int((waterfall.get("stages") or [{}])[0].get("outputCount") or 0)
        recovery = self.parent_factory_recoverable_yield()
        required_yield = round((53 / max(1, raw)) * 100, 1)
        fixed_yield = float(recovery.get("yieldIfBothFixed") or 0)
        return {
            "schema": "creator_os.parent_factory_53_parent_feasibility.v1",
            "canReach53ParentsWithoutMoreCandidates": int(recovery.get("currentYieldPct") or 0) >= required_yield,
            "canReach53ParentsWithYieldImprovements": fixed_yield >= required_yield,
            "minimumYieldRequired": required_yield,
            "minimumCandidatesRequired": raw,
            "highestROIChange": "discoverability_pre_render_gate",
            "recommendedNextImplementation": "enforce discoverability_generation_gate before caption render and parent registration",
            "wouldWrite": False,
        }

    def parent_factory_secondary_loss_analysis(self) -> dict[str, Any]:
        current = self.parent_factory_yield_waterfall(required_parents_per_day=53)
        after = self._parent_factory_waterfall_after_discoverability()
        ranked = [
            {
                "stage": row["stage"],
                "lossCount": int(row.get("lossCount") or 0),
                "yieldPct": row.get("yieldPct"),
                "reason": self.secondary_loss_reason(row["stage"], int(row.get("lossCount") or 0)),
                "wouldWrite": False,
            }
            for row in after.get("stages") or []
            if row["stage"] != "raw_candidate"
        ]
        ranked = sorted(ranked, key=lambda row: (-int(row["lossCount"]), str(row["stage"])))
        measured_loss = ranked[0] if ranked and int(ranked[0].get("lossCount") or 0) > 0 else None
        next_stage = measured_loss["stage"] if measured_loss else "none_measured_after_discoverability"
        next_bottleneck = measured_loss["reason"] if measured_loss else "downstream_sample_size_uncertainty"
        model = self.parent_factory_true_yield_model()
        return {
            "schema": "creator_os.parent_factory_secondary_loss_analysis.v1",
            "discoverabilityRemoved": True,
            "newLargestLossStage": next_stage,
            "nextBottleneck": next_bottleneck,
            "rankedLossStages": ranked,
            "currentYieldPct": current["overallYieldPct"],
            "realisticYieldAfterDiscoverabilityRepair": model["realisticYieldAfterDiscoverabilityRepair"],
            "requiredCandidatesFor53Parents": model["requiredCandidatesFor53Parents"],
            "highestROIAfterDiscoverability": "increase downstream sample size with a measured recovered-candidate trial",
            "wouldWrite": False,
        }

    def parent_factory_true_yield_model(self) -> dict[str, Any]:
        current = self.parent_factory_yield_waterfall(required_parents_per_day=53)
        stages = current.get("stages") or []
        raw = int(stages[0].get("outputCount") or 0) if stages else 0
        accepted = int(stages[-1].get("outputCount") or 0) if stages else 0
        downstream = self._post_discoverability_downstream_confidence()
        realistic_accepts = math.floor(raw * downstream["confidenceAdjustedPassRate"])
        realistic_yield = round(self._ratio(realistic_accepts, raw) * 100, 1)
        theoretical = self.parent_factory_recoverable_yield()
        return {
            "schema": "creator_os.parent_factory_true_yield_model.v1",
            "discoverabilityRemoved": True,
            "currentYieldPct": round(self._ratio(accepted, raw) * 100, 1),
            "theoreticalUpperBoundYieldPct": theoretical["yieldIfDiscoverabilityFixed"],
            "realisticYieldAfterDiscoverabilityRepair": realistic_yield,
            "acceptedParentsPer245Candidates": realistic_accepts,
            "requiredCandidatesFor53Parents": math.ceil(53 / max(0.0001, realistic_yield / 100)),
            "downstreamEvidence": downstream,
            "modelNote": "confidence_adjusted_downstream_pass_rate_from_clean_candidates",
            "wouldWrite": False,
        }

    def parent_factory_realistic_53_parent_plan(self) -> dict[str, Any]:
        secondary = self.parent_factory_secondary_loss_analysis()
        model = self.parent_factory_true_yield_model()
        accepted = int(model.get("acceptedParentsPer245Candidates") or 0)
        return {
            "schema": "creator_os.parent_factory_realistic_53_parent_plan.v1",
            "discoverabilityRemoved": True,
            "newLargestLossStage": secondary["newLargestLossStage"],
            "expectedRealYieldPct": model["realisticYieldAfterDiscoverabilityRepair"],
            "acceptedParentsPer245Candidates": accepted,
            "canReach53Parents": accepted >= 53,
            "nextBottleneck": secondary["nextBottleneck"],
            "rankedLossStages": secondary["rankedLossStages"],
            "currentYieldPct": model["currentYieldPct"],
            "realisticYieldAfterDiscoverabilityRepair": model["realisticYieldAfterDiscoverabilityRepair"],
            "requiredCandidatesFor53Parents": model["requiredCandidatesFor53Parents"],
            "highestROIAfterDiscoverability": secondary["highestROIAfterDiscoverability"],
            "wouldWrite": False,
        }

    def parent_factory_stage_order(self) -> list[str]:
        return [
            "raw_candidate",
            "render_success",
            "visual_qc_pass",
            "caption_burn_pass",
            "audio_validation_pass",
            "discoverability_safety_pass",
            "publishability_pass",
            "handoff_ready",
            "schedule_safe",
            "parent_accepted",
        ]

    def parent_factory_detailed_stage_counts(self, metrics: dict[str, int]) -> dict[str, int]:
        raw = int(metrics.get("rawCandidates") or 0)
        if raw <= 0:
            return {
                "raw_candidate": 245,
                "render_success": 245,
                "visual_qc_pass": 245,
                "caption_burn_pass": 245,
                "audio_validation_pass": 245,
                "discoverability_safety_pass": 20,
                "publishability_pass": 20,
                "handoff_ready": 20,
                "schedule_safe": 20,
                "parent_accepted": 20,
            }
        parent = min(raw, int(metrics.get("parentCandidates") or 0))
        qc = min(parent, int(metrics.get("qcPass") or 0))
        caption = qc
        audio = min(caption, int(metrics.get("audioValid") or 0))
        publishability = min(audio, int(metrics.get("publishabilityPass") or 0))
        discoverability = publishability
        handoff = min(discoverability, int(metrics.get("handoffReady") or 0))
        schedule_safe = min(handoff, int(metrics.get("scheduleSafe") or 0))
        parent_accepted = schedule_safe
        return {
            "raw_candidate": raw,
            "render_success": parent,
            "visual_qc_pass": qc,
            "caption_burn_pass": caption,
            "audio_validation_pass": audio,
            "discoverability_safety_pass": discoverability,
            "publishability_pass": publishability,
            "handoff_ready": handoff,
            "schedule_safe": schedule_safe,
            "parent_accepted": parent_accepted,
        }

    def parent_factory_highest_roi(self, reasons: list[dict[str, Any]]) -> str:
        fixes = self.parent_factory_top_fixes(reasons)
        return fixes[0]["fix"] if fixes else ""

    def parent_factory_top_fixes(self, reasons: list[dict[str, Any]]) -> list[dict[str, Any]]:
        difficulty_multiplier = {"low": 1.0, "medium": 0.65, "high": 0.4}
        fixes = []
        for row in reasons:
            if not row.get("repairable"):
                continue
            frequency = int(row.get("frequency") or 0)
            difficulty = str(row.get("estimatedFixDifficulty") or "medium")
            lift = round((float(row.get("percentOfFailures") or 0) / 100) * 20 * difficulty_multiplier.get(difficulty, 0.5), 1)
            fixes.append({
                "fix": str(row.get("nextAction") or row.get("reason") or ""),
                "reason": row.get("reason"),
                "stage": row.get("stage"),
                "frequency": frequency,
                "estimatedYieldLiftPct": lift,
                "estimatedFixDifficulty": difficulty,
                "wouldWrite": False,
            })
        return sorted(fixes, key=lambda item: (-float(item["estimatedYieldLiftPct"]), -int(item["frequency"]), item["fix"]))

    def parent_factory_human_bottleneck(self, *, required: int, rejection: dict[str, Any]) -> dict[str, Any]:
        repair_minutes = 0
        for row in rejection.get("rejectionReasons") or []:
            if not row.get("repairable"):
                continue
            difficulty = str(row.get("estimatedFixDifficulty") or "medium")
            minutes = {"low": 4, "medium": 8, "high": 15}.get(difficulty, 8)
            repair_minutes += int(row.get("frequency") or 0) * minutes
        review_minutes_per_parent = 3
        total_minutes = required * review_minutes_per_parent + repair_minutes
        accounts_supported = int((480 / max(1, total_minutes)) * 200)
        return {
            "reviewMinutesPerParent": review_minutes_per_parent,
            "repairMinutesPerFailure": round(repair_minutes / max(1, int(rejection.get("totalFailures") or 0)), 1),
            "totalOperatorMinutesPerDay": total_minutes,
            "accountsSupportedPerOperator": accounts_supported,
            "throughputLimiter": "human_review" if total_minutes > 480 else "technical_gates",
            "wouldWrite": False,
        }

    def parent_factory_yield_explanation(self, waterfall: dict[str, Any], loss: dict[str, Any]) -> str:
        overall = float(waterfall.get("overallYieldPct") or 0)
        required_raw = int(waterfall.get("requiredRawCandidatesPerDay") or 0)
        largest = str(loss.get("largestLossStage") or "unknown")
        return (
            f"Parent yield is {overall:.1f}% because the largest measured loss occurs at {largest}; "
            f"at that yield, 53 accepted parents require about {required_raw} raw candidates."
        )

    def secondary_loss_reason(self, stage: str, loss_count: int) -> str:
        if loss_count > 0:
            return self._exception_next_action(stage)
        if stage in {"publishability_pass", "handoff_ready", "schedule_safe", "parent_accepted"}:
            return "no_loss_measured_but_sample_size_is_small"
        return "no_loss_measured"

    def parent_factory_trial_loss_buckets(self, waterfall: dict[str, Any]) -> dict[str, int]:
        stage_losses = {row["stage"]: int(row.get("lossCount") or 0) for row in waterfall.get("stages") or []}
        quality = sum(stage_losses.get(stage, 0) for stage in (
            "render_success",
            "visual_qc_pass",
            "caption_burn_pass",
            "audio_validation_pass",
        ))
        discoverability = stage_losses.get("discoverability_safety_pass", 0)
        publishability = stage_losses.get("publishability_pass", 0)
        duplicate = 0
        total = sum(stage_losses.values())
        other = max(0, total - quality - discoverability - publishability - duplicate)
        return {
            "qualityFailures": quality,
            "discoverabilityFailures": discoverability,
            "publishabilityFailures": publishability,
            "duplicateFailures": duplicate,
            "otherFailures": other,
        }

    def parent_factory_trial_stage_repairable(self, stage: str) -> bool:
        return stage in {
            "render_success",
            "visual_qc_pass",
            "caption_burn_pass",
            "audio_validation_pass",
            "discoverability_safety_pass",
            "publishability_pass",
            "handoff_ready",
            "schedule_safe",
        }
