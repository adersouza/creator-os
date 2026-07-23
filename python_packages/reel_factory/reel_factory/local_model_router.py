"""Deterministic evidence-only router for approved local video models."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import fmean, median
from typing import Any, Final

from pipeline_contracts import validate_local_model_router_decision

from .human_media_review import HumanMediaReviewStore
from .local_generation_queue import LocalQueueError, fingerprint
from .local_model_arena import (
    CREATORS,
    LocalModelArenaStore,
    _human_review_evidence,
    validate_arena_plan,
    validate_arena_review_packet,
    validate_arena_summary,
    validate_arena_unblinding_receipt,
)
from .local_model_benchmark import (
    LocalModelBenchmarkStore,
    default_local_model_benchmark_store,
)
from .local_model_manager import model_status
from .local_video_models import local_video_model_spec
from .video_provider_models import video_model

ROUTER_SCHEMA: Final = "reel_factory.local_model_router_decision.v1"
ROUTER_POLICY_ID: Final = "reel_factory.local_model_router"
ROUTER_POLICY_VERSION: Final = "1.0.0"
MINIMUM_ALLOWED_YIELD: Final = 0.5
MINIMUM_ALLOWED_QUALITY_SCORE: Final = 0.6
MAXIMUM_ALLOWED_EVIDENCE_AGE_DAYS: Final = 30


@dataclass(frozen=True, slots=True)
class RouterRequest:
    creator_id: str
    identity_profile_id: str
    identity_profile_fingerprint: str
    content_intent_id: str
    content_intent_fingerprint: str
    task_kind: str
    capability_cohort: str
    available_memory_bytes: int
    observed_at: str
    minimum_yield: float = 0.5
    minimum_quality_score: float = 0.6
    maximum_evidence_age_days: int = 30
    override_model_id: str | None = None
    override_operator: str | None = None
    override_reason: str | None = None

    def __post_init__(self) -> None:
        if self.creator_id.lower() not in CREATORS:
            raise ValueError(f"router_creator_unsupported:{self.creator_id}")
        for field_name in (
            "identity_profile_id",
            "content_intent_id",
            "task_kind",
            "capability_cohort",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"router_{field_name}_missing")
        for value in (
            self.identity_profile_fingerprint,
            self.content_intent_fingerprint,
        ):
            if len(value) != 64 or any(
                char not in "0123456789abcdef" for char in value
            ):
                raise ValueError("router_evidence_fingerprint_invalid")
        observed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError("router_observed_at_timezone_required")
        if self.available_memory_bytes <= 0:
            raise ValueError("router_available_memory_must_be_positive")
        if (
            not math.isfinite(float(self.minimum_yield))
            or not math.isfinite(float(self.minimum_quality_score))
            or not MINIMUM_ALLOWED_YIELD <= self.minimum_yield <= 1
            or not MINIMUM_ALLOWED_QUALITY_SCORE <= self.minimum_quality_score <= 1
        ):
            raise ValueError("router_quality_threshold_invalid")
        if not 0 < self.maximum_evidence_age_days <= MAXIMUM_ALLOWED_EVIDENCE_AGE_DAYS:
            raise ValueError("router_evidence_age_must_be_positive")
        override_values = (
            self.override_model_id,
            self.override_operator,
            self.override_reason,
        )
        if any(value is not None for value in override_values) and not all(
            value is not None and str(value).strip() for value in override_values
        ):
            raise ValueError("router_override_evidence_must_be_complete")


def _model_fingerprint(model_id: str, status: dict[str, Any]) -> str:
    manifest = status.get("manifest")
    if not isinstance(manifest, dict):
        raise LocalQueueError(f"router_model_manifest_missing:{model_id}")
    return fingerprint(
        {
            "modelId": model_id,
            "modelRevision": str(manifest.get("revision") or ""),
            "modelManifestSha256": str(status.get("manifestSha256") or ""),
        }
    )


def _benchmark_recorded_at(
    store: LocalModelBenchmarkStore, benchmark_ids: set[str]
) -> dict[str, str]:
    observed: dict[str, str] = {}
    for event in store.benchmarks.read().events:
        if event.get("eventType") != "benchmark_recorded":
            continue
        benchmark_id = str(event.get("payload", {}).get("benchmarkId") or "")
        if benchmark_id in benchmark_ids:
            if benchmark_id in observed:
                raise LocalQueueError("router_duplicate_benchmark_identity")
            observed[benchmark_id] = str(event["occurredAt"])
    return observed


def _numeric_values(samples: list[dict[str, Any]], field: str) -> list[float] | None:
    values = [item.get(field) for item in samples]
    if not values or any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in values
    ):
        return None
    result: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        result.append(float(value))
    return result


def _arithmetic_mean(values: list[float]) -> float | None:
    return float(fmean(values)) if values else None


def route_local_model(
    request: RouterRequest,
    *,
    arena_plan: Mapping[str, Any],
    arena_summary: dict[str, Any],
    benchmark_store: LocalModelBenchmarkStore,
    human_review_store: HumanMediaReviewStore,
    review_packet: Mapping[str, Any],
    unblinding_receipt: Mapping[str, Any],
    evidence_secret: str | None = None,
) -> dict[str, Any]:
    """Select one approved local model or fail closed with exact exclusions."""

    plan = validate_arena_plan(arena_plan)
    summary = validate_arena_summary(arena_summary, arena_plan=plan)
    if summary.get("purpose") != "promotion_eligible":
        raise LocalQueueError("router_requires_promotion_eligible_arena")
    packet = validate_arena_review_packet(
        review_packet, arena_plan=plan, evidence_secret=evidence_secret
    )
    unblinding = validate_arena_unblinding_receipt(
        unblinding_receipt,
        arena_plan=plan,
        review_packet=packet,
        human_reviews=human_review_store,
        evidence_secret=evidence_secret,
    )
    expected_review_evidence = {
        "reviewPacketId": packet["packetId"],
        "reviewPacketFingerprint": packet["packetFingerprint"],
        "unblindingReceiptId": unblinding["receiptId"],
        "unblindingReceiptFingerprint": unblinding["receiptFingerprint"],
    }
    if summary.get("reviewEvidence") != expected_review_evidence:
        raise LocalQueueError("router_review_evidence_chain_mismatch")
    observed_at = datetime.fromisoformat(request.observed_at.replace("Z", "+00:00"))
    receipts = benchmark_store.all_receipts()
    reviews = human_review_store.reviews()
    planned_by_sample = {
        str(sample["sampleId"]): sample for sample in plan.get("samples", [])
    }
    considered: list[dict[str, Any]] = []
    aggregate_keys: list[tuple[str, str]] = []
    for aggregate in summary.get("candidateAggregates", []):
        if not isinstance(aggregate, dict):
            continue
        aggregate_keys.append(
            (
                str(aggregate.get("modelId") or ""),
                str(aggregate.get("capabilityCohort") or ""),
            )
        )
    if len(aggregate_keys) != len(set(aggregate_keys)):
        raise LocalQueueError("router_duplicate_candidate_aggregate")
    candidate_model_ids = sorted(
        model_id
        for model_id, capability in aggregate_keys
        if capability == request.capability_cohort
    )
    for model_id in candidate_model_ids:
        exclusions: list[str] = []
        aggregate_samples = [
            item
            for item in summary.get("samples", [])
            if isinstance(item, dict)
            and item.get("modelId") == model_id
            and item.get("capabilityCohort") == request.capability_cohort
        ]
        creator_samples = [
            item
            for item in aggregate_samples
            if str(item.get("creatorId") or "").lower() == request.creator_id.lower()
        ]
        identity_samples = [
            item
            for item in creator_samples
            if item.get("identityProfileId") == request.identity_profile_id
            and item.get("identityProfileFingerprint")
            == request.identity_profile_fingerprint
        ]
        intent_samples = [
            item
            for item in identity_samples
            if item.get("contentIntentId") == request.content_intent_id
            and item.get("contentIntentFingerprint")
            == request.content_intent_fingerprint
        ]
        task_samples = [
            item for item in intent_samples if item.get("taskKind") == request.task_kind
        ]
        valid_task_samples = [
            item for item in task_samples if item.get("promotionEvidenceValid") is True
        ]
        if not aggregate_samples:
            exclusions.append("arena_sample_evidence_missing")
        elif not creator_samples:
            exclusions.append("creator_evidence_unsupported")
        elif not identity_samples:
            exclusions.append("identity_profile_evidence_mismatch")
        elif not intent_samples:
            exclusions.append("content_intent_evidence_mismatch")
        elif not task_samples:
            exclusions.append("arena_task_evidence_mismatch")
        else:
            if not valid_task_samples:
                exclusions.append("creator_intent_evidence_ineligible")
        try:
            model = video_model(model_id)
            spec = local_video_model_spec(model_id)
        except ValueError:
            exclusions.append("model_catalog_missing")
            considered.append(
                {
                    "modelId": model_id,
                    "modelFingerprint": None,
                    "capabilityCohort": request.capability_cohort,
                    "requiredMemoryBytes": None,
                    "benchmarkIds": [],
                    "matchedArenaSampleIds": sorted(
                        str(item.get("sampleId") or "") for item in task_samples
                    ),
                    "validArenaSampleIds": sorted(
                        str(item.get("sampleId") or "") for item in valid_task_samples
                    ),
                    "arenaSummaryFingerprint": summary["summaryFingerprint"],
                    "promotionApproval": None,
                    "measurements": {
                        "promotionEligibleYield": None,
                        "meanHumanQualityScore": None,
                        "medianWallTimeSeconds": None,
                        "medianPeakMemoryBytes": None,
                    },
                    "score": None,
                    "exclusions": sorted(set(exclusions)),
                }
            )
            continue
        if model.backend != "local_mlx" or model.paid:
            exclusions.append("model_not_local_free")
        if request.task_kind not in (model.supported_tasks or (model.task,)):
            exclusions.append("capability_mismatch")
        status = model_status(model_id, deep=True)
        deep_verification = status.get("deepVerificationReceipt")
        if (
            not status.get("ready")
            or status.get("deepVerified") is not True
            or not isinstance(deep_verification, dict)
        ):
            exclusions.append("model_unavailable_or_drifted")
        try:
            expected_model_fingerprint = _model_fingerprint(model_id, status)
        except LocalQueueError:
            expected_model_fingerprint = ""
            exclusions.append("model_manifest_missing")
        required_memory = max(24 * 1024**3, int(spec.estimated_bytes * 1.35))
        if required_memory > request.available_memory_bytes:
            exclusions.append("resource_shortage")
        benchmark_ids = tuple(
            str(item.get("benchmarkId") or "") for item in valid_task_samples
        )
        if (
            not benchmark_ids
            or any(not benchmark_id for benchmark_id in benchmark_ids)
            or len(benchmark_ids) != len(set(benchmark_ids))
            or len(benchmark_ids) != len(valid_task_samples)
        ):
            exclusions.append("benchmark_cohort_missing_or_duplicate")
        cohort_hardware_fingerprints = {
            receipt.hardware_fingerprint
            for benchmark_id in benchmark_ids
            if (receipt := receipts.get(benchmark_id)) is not None
        }
        cohort_hardware_fingerprint = (
            next(iter(cohort_hardware_fingerprints))
            if len(cohort_hardware_fingerprints) == 1
            else ""
        )
        if len(cohort_hardware_fingerprints) != 1:
            exclusions.append("benchmark_hardware_cohort_mismatch")
        for arena_sample in valid_task_samples:
            benchmark_id = str(arena_sample.get("benchmarkId") or "")
            sample_id = str(arena_sample.get("sampleId") or "")
            planned_sample = planned_by_sample.get(sample_id)
            if planned_sample is None:
                exclusions.append("arena_plan_sample_missing")
                continue
            receipt = receipts.get(benchmark_id)
            if receipt is None:
                exclusions.append("benchmark_receipt_missing")
                continue
            if receipt.model_fingerprint != expected_model_fingerprint:
                exclusions.append("benchmark_model_fingerprint_mismatch")
            if receipt.task_kind != request.task_kind:
                exclusions.append("benchmark_task_mismatch")
            execution = arena_sample.get("executionEvidence")
            measurement = (
                execution.get("executionMeasurement")
                if isinstance(execution, dict)
                else None
            )
            expected_bindings = {
                "job": (
                    receipt.job_id,
                    planned_sample["queueJob"]["jobId"],
                ),
                "model": (
                    receipt.model_fingerprint,
                    planned_sample["modelFingerprint"],
                ),
                "task": (
                    receipt.task_fingerprint,
                    planned_sample["queueJob"]["taskFingerprint"],
                ),
                "output": (
                    receipt.output_sha256,
                    arena_sample.get("outputSha256"),
                ),
                "recipe_id": (
                    receipt.benchmark_recipe_id,
                    planned_sample["benchmarkRecipe"]["recipeId"],
                ),
                "recipe": (
                    receipt.benchmark_recipe_fingerprint,
                    planned_sample["benchmarkRecipeFingerprint"],
                ),
                "registry_id": (
                    receipt.analyzer_registry_id,
                    planned_sample["analyzerRegistry"]["registryId"],
                ),
                "registry": (
                    receipt.analyzer_registry_fingerprint,
                    planned_sample["analyzerRegistryFingerprint"],
                ),
                "wall_time": (
                    receipt.wall_time_seconds,
                    arena_sample.get("wallTimeSeconds"),
                ),
                "peak_memory": (
                    receipt.peak_memory_bytes,
                    arena_sample.get("peakMemoryBytes"),
                ),
                "memory_method": (
                    receipt.memory_measurement_method,
                    measurement.get("memoryMeasurementMethod")
                    if isinstance(measurement, dict)
                    else None,
                ),
                "attempt_count": (
                    receipt.execution_attempt_count,
                    execution.get("attemptCount")
                    if isinstance(execution, dict)
                    else None,
                ),
                "retry_count": (
                    receipt.execution_retry_count,
                    execution.get("retryCount")
                    if isinstance(execution, dict)
                    else None,
                ),
            }
            for binding, (observed, expected) in expected_bindings.items():
                if observed != expected:
                    exclusions.append(f"benchmark_{binding}_binding_mismatch")
            if receipt.model_id != model_id:
                exclusions.append("benchmark_model_id_mismatch")
            if not isinstance(
                deep_verification, dict
            ) or receipt.model_deep_verification_fingerprint != deep_verification.get(
                "verificationFingerprint"
            ):
                exclusions.append("benchmark_model_deep_verification_drift")
            if not receipt.all_qc_passed:
                exclusions.append("benchmark_qc_failed")
            if (
                receipt.benchmark_recipe_fingerprint is None
                or receipt.analyzer_registry_fingerprint is None
            ):
                exclusions.append("historical_unlinked_benchmark")
            review = reviews.get(str(arena_sample.get("humanReviewId") or ""))
            if review is None:
                exclusions.append("human_review_missing")
            else:
                review_blockers, review_quality = _human_review_evidence(review)
                if (
                    review.arena_plan_id != plan["planId"]
                    or review.sample_id != sample_id
                    or review.blinded_candidate_id
                    != planned_sample["blindedCandidateId"]
                    or review.subject_sha256 != arena_sample.get("outputSha256")
                    or review.source_sha256 != planned_sample["sourceSha256"]
                    or review.provenance.review_mode != "blinded"
                ):
                    exclusions.append("human_review_plan_binding_mismatch")
                if review_blockers:
                    exclusions.append("human_review_policy_failed")
                if review_quality != arena_sample.get("qualityScore"):
                    exclusions.append("human_review_quality_binding_mismatch")
        recorded = _benchmark_recorded_at(benchmark_store, set(benchmark_ids))
        for benchmark_id in benchmark_ids:
            timestamp = recorded.get(benchmark_id)
            if timestamp is None:
                exclusions.append("benchmark_timestamp_missing")
                continue
            try:
                recorded_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                exclusions.append("benchmark_timestamp_invalid")
                continue
            if recorded_at.tzinfo is None:
                exclusions.append("benchmark_timestamp_invalid")
            elif recorded_at > observed_at:
                exclusions.append("benchmark_evidence_from_future")
            elif (observed_at - recorded_at).total_seconds() > (
                request.maximum_evidence_age_days * 86400
            ):
                exclusions.append("benchmark_evidence_stale")
        approval: dict[str, Any] | None = None
        if expected_model_fingerprint and cohort_hardware_fingerprint:
            try:
                approval = benchmark_store.active_promotion(
                    candidate_model_fingerprint=expected_model_fingerprint,
                    task_kind=request.task_kind,
                    candidate_benchmark_ids=benchmark_ids,
                    hardware_fingerprint=cohort_hardware_fingerprint,
                    observed_at=request.observed_at,
                )
            except LocalQueueError:
                exclusions.append("active_promotion_missing_or_invalid")
        if approval is not None:
            try:
                approved_at = datetime.fromisoformat(
                    str(approval.get("approvedAt") or "").replace("Z", "+00:00")
                )
            except ValueError:
                exclusions.append("promotion_approval_timestamp_invalid")
            else:
                if approved_at.tzinfo is None:
                    exclusions.append("promotion_approval_timestamp_invalid")
                elif approved_at > observed_at:
                    exclusions.append("promotion_approval_from_future")
        measured_yield = (
            len(valid_task_samples) / len(task_samples) if task_samples else None
        )
        quality_values = _numeric_values(valid_task_samples, "qualityScore")
        latency_values = _numeric_values(valid_task_samples, "wallTimeSeconds")
        memory_values = _numeric_values(valid_task_samples, "peakMemoryBytes")
        measured_quality = (
            _arithmetic_mean(quality_values) if quality_values is not None else None
        )
        latency = median(latency_values) if latency_values else None
        peak_memory = int(median(memory_values)) if memory_values else None
        if (
            not isinstance(measured_yield, (int, float))
            or measured_yield < request.minimum_yield
        ):
            exclusions.append("measured_yield_below_policy")
        if not isinstance(measured_quality, (int, float)):
            exclusions.append("human_quality_evidence_unavailable")
        elif measured_quality < request.minimum_quality_score:
            exclusions.append("human_quality_below_policy")
        if not isinstance(latency, (int, float)) or latency <= 0:
            exclusions.append("latency_evidence_unavailable")
        if not isinstance(peak_memory, int) or peak_memory <= 0:
            exclusions.append("memory_evidence_unavailable")
        score = None
        if not exclusions:
            assert isinstance(measured_quality, (int, float))
            assert isinstance(measured_yield, (int, float))
            assert isinstance(peak_memory, int)
            assert isinstance(latency, (int, float))
            score = round(
                float(measured_quality) * 0.60
                + float(measured_yield) * 0.30
                + min(1.0, request.available_memory_bytes / float(peak_memory)) * 0.05
                + (1.0 / (1.0 + float(latency) / 600.0)) * 0.05,
                9,
            )
        considered.append(
            {
                "modelId": model_id,
                "modelFingerprint": expected_model_fingerprint or None,
                "capabilityCohort": request.capability_cohort,
                "requiredMemoryBytes": required_memory,
                "benchmarkIds": list(benchmark_ids),
                "matchedArenaSampleIds": sorted(
                    str(item.get("sampleId") or "") for item in task_samples
                ),
                "validArenaSampleIds": sorted(
                    str(item.get("sampleId") or "") for item in valid_task_samples
                ),
                "arenaSummaryFingerprint": summary["summaryFingerprint"],
                "promotionApproval": approval,
                "measurements": {
                    "promotionEligibleYield": measured_yield,
                    "meanHumanQualityScore": measured_quality,
                    "medianWallTimeSeconds": latency,
                    "medianPeakMemoryBytes": peak_memory,
                },
                "score": score,
                "exclusions": sorted(set(exclusions)),
            }
        )
    valid = [candidate for candidate in considered if not candidate["exclusions"]]
    valid.sort(
        key=lambda candidate: (-float(candidate["score"]), str(candidate["modelId"]))
    )
    override = None
    if request.override_model_id is not None:
        selected_matches = [
            candidate
            for candidate in valid
            if candidate["modelId"] == request.override_model_id
        ]
        if len(selected_matches) != 1:
            raise LocalQueueError("router_override_model_not_valid")
        winner = selected_matches[0]
        override = {
            "modelId": request.override_model_id,
            "operator": request.override_operator,
            "reason": request.override_reason,
            "excludedFromBenchmarkLearning": True,
        }
    elif valid:
        winner = valid[0]
    else:
        raise LocalQueueError(
            "router_no_valid_model:" + json.dumps(considered, sort_keys=True)
        )
    request_payload = {
        "creatorId": request.creator_id.lower(),
        "identityProfileId": request.identity_profile_id,
        "identityProfileFingerprint": request.identity_profile_fingerprint,
        "contentIntentId": request.content_intent_id,
        "contentIntentFingerprint": request.content_intent_fingerprint,
        "taskKind": request.task_kind,
        "capabilityCohort": request.capability_cohort,
        "availableMemoryBytes": request.available_memory_bytes,
        "observedAt": request.observed_at,
        "minimumYield": request.minimum_yield,
        "minimumQualityScore": request.minimum_quality_score,
        "maximumEvidenceAgeDays": request.maximum_evidence_age_days,
    }
    core = {
        "schema": ROUTER_SCHEMA,
        "decisionId": f"router_decision_{fingerprint({'request': request_payload, 'summary': summary['summaryFingerprint']})[:24]}",
        "policy": {"id": ROUTER_POLICY_ID, "version": ROUTER_POLICY_VERSION},
        "request": request_payload,
        "consideredCandidates": considered,
        "selectedModelId": winner["modelId"],
        "selectedModelFingerprint": winner["modelFingerprint"],
        "winningEvidence": {
            "arenaSummaryFingerprint": summary["summaryFingerprint"],
            "benchmarkIds": winner["benchmarkIds"],
            "cohortKey": {
                "creatorId": request.creator_id.lower(),
                "identityProfileId": request.identity_profile_id,
                "identityProfileFingerprint": request.identity_profile_fingerprint,
                "contentIntentId": request.content_intent_id,
                "contentIntentFingerprint": request.content_intent_fingerprint,
                "taskKind": request.task_kind,
                "capabilityCohort": request.capability_cohort,
            },
            "matchedArenaSampleIds": winner["matchedArenaSampleIds"],
            "validArenaSampleIds": winner["validArenaSampleIds"],
            "measurements": winner["measurements"],
            "promotionApproval": winner["promotionApproval"],
            "score": winner["score"],
        },
        "operatorOverride": override,
        "paidProviderFallbackAllowed": False,
        "legacyLocalMotionFallbackAllowed": False,
    }
    decision = {**core, "decisionFingerprint": fingerprint(core)}
    return validate_router_decision(decision, arena_plan=plan, arena_summary=summary)


def validate_router_decision(
    decision: dict[str, Any],
    *,
    arena_plan: Mapping[str, Any],
    arena_summary: dict[str, Any],
) -> dict[str, Any]:
    validate_arena_summary(arena_summary, arena_plan=arena_plan)
    validate_local_model_router_decision(decision)
    core = dict(decision)
    claimed = str(core.pop("decisionFingerprint"))
    if fingerprint(core) != claimed:
        raise LocalQueueError("router_decision_fingerprint_mismatch")
    selected = [
        candidate
        for candidate in decision["consideredCandidates"]
        if candidate["modelId"] == decision["selectedModelId"]
    ]
    if len(selected) != 1:
        raise LocalQueueError("router_selected_candidate_not_exactly_once")
    winner = selected[0]
    if (
        winner["exclusions"]
        or winner["score"] is None
        or winner["modelFingerprint"] != decision["selectedModelFingerprint"]
    ):
        raise LocalQueueError("router_selected_candidate_not_eligible")
    winning = decision["winningEvidence"]
    expected_winning = {
        "arenaSummaryFingerprint": arena_summary["summaryFingerprint"],
        "benchmarkIds": winner["benchmarkIds"],
        "cohortKey": {
            field: decision["request"][field]
            for field in (
                "creatorId",
                "identityProfileId",
                "identityProfileFingerprint",
                "contentIntentId",
                "contentIntentFingerprint",
                "taskKind",
                "capabilityCohort",
            )
        },
        "matchedArenaSampleIds": winner["matchedArenaSampleIds"],
        "validArenaSampleIds": winner["validArenaSampleIds"],
        "measurements": winner["measurements"],
        "promotionApproval": winner["promotionApproval"],
        "score": winner["score"],
    }
    if winning != expected_winning:
        raise LocalQueueError("router_winning_evidence_mismatch")
    override = decision["operatorOverride"]
    if override is not None and override["modelId"] != winner["modelId"]:
        raise LocalQueueError("router_override_winner_mismatch")
    return decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--arena-summary", type=Path, required=True)
    parser.add_argument(
        "--benchmark-root",
        type=Path,
        default=Path(
            os.environ.get(
                "CREATOR_OS_LOCAL_MODEL_BENCHMARK_ROOT",
                Path.home() / ".creator-os/state/reel_factory/local_benchmarks",
            )
        ),
    )
    args = parser.parse_args(argv)
    try:
        request_payload = json.loads(args.request.read_text(encoding="utf-8"))
        summary = json.loads(args.arena_summary.read_text(encoding="utf-8"))
        if not isinstance(request_payload, dict) or not isinstance(summary, dict):
            raise ValueError("router_json_object_required")
        arena_store = LocalModelArenaStore(args.benchmark_root)
        human_reviews = HumanMediaReviewStore(args.benchmark_root)
        plan_id = str(summary.get("planId") or "")
        review_packet = arena_store.load_review_packet(plan_id)
        decision = route_local_model(
            RouterRequest(**request_payload),
            arena_plan=arena_store.load_plan(plan_id),
            arena_summary=summary,
            benchmark_store=default_local_model_benchmark_store(args.benchmark_root),
            human_review_store=human_reviews,
            review_packet=review_packet,
            unblinding_receipt=arena_store.load_unblinding_receipt(
                plan_id, human_reviews=human_reviews
            ),
        )
    except (
        LocalQueueError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
