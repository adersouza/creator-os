"""Deterministic evidence-only router for approved local video models."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from .local_generation_queue import LocalQueueError, fingerprint
from .local_model_arena import CREATORS, validate_arena_summary
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
        if not 0 <= self.minimum_yield <= 1 or not 0 <= self.minimum_quality_score <= 1:
            raise ValueError("router_quality_threshold_invalid")
        if self.maximum_evidence_age_days <= 0:
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


def _aggregate_for_model(
    summary: dict[str, Any], model_id: str, capability_cohort: str
) -> dict[str, Any] | None:
    matches = [
        dict(item)
        for item in summary.get("candidateAggregates", [])
        if isinstance(item, dict)
        and item.get("modelId") == model_id
        and item.get("capabilityCohort") == capability_cohort
    ]
    if len(matches) > 1:
        raise LocalQueueError("router_duplicate_candidate_aggregate")
    return matches[0] if matches else None


def route_local_model(
    request: RouterRequest,
    *,
    arena_summary: dict[str, Any],
    benchmark_store: LocalModelBenchmarkStore,
) -> dict[str, Any]:
    """Select one approved local model or fail closed with exact exclusions."""

    summary = validate_arena_summary(arena_summary)
    if summary.get("purpose") != "promotion_eligible":
        raise LocalQueueError("router_requires_promotion_eligible_arena")
    observed_at = datetime.fromisoformat(request.observed_at.replace("Z", "+00:00"))
    receipts = benchmark_store.all_receipts()
    considered: list[dict[str, Any]] = []
    for aggregate in summary.get("candidateAggregates", []):
        if not isinstance(aggregate, dict):
            continue
        model_id = str(aggregate.get("modelId") or "")
        if aggregate.get("capabilityCohort") != request.capability_cohort:
            continue
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
        if not aggregate_samples:
            exclusions.append("arena_sample_evidence_missing")
        elif not creator_samples:
            exclusions.append("creator_evidence_unsupported")
        elif not identity_samples:
            exclusions.append("identity_profile_evidence_mismatch")
        elif not intent_samples:
            exclusions.append("content_intent_evidence_mismatch")
        else:
            if any(
                item.get("taskKind") != request.task_kind for item in intent_samples
            ):
                exclusions.append("arena_task_evidence_mismatch")
            if not any(
                item.get("promotionEvidenceValid") is True for item in intent_samples
            ):
                exclusions.append("creator_intent_evidence_ineligible")
        try:
            model = video_model(model_id)
            spec = local_video_model_spec(model_id)
        except ValueError:
            exclusions.append("model_catalog_missing")
            considered.append({"modelId": model_id, "exclusions": exclusions})
            continue
        if model.backend != "local_mlx" or model.paid:
            exclusions.append("model_not_local_free")
        if request.task_kind not in (model.supported_tasks or (model.task,)):
            exclusions.append("capability_mismatch")
        status = model_status(model_id, deep=False)
        if not status.get("ready"):
            exclusions.append("model_unavailable_or_drifted")
        try:
            expected_model_fingerprint = _model_fingerprint(model_id, status)
        except LocalQueueError:
            expected_model_fingerprint = ""
            exclusions.append("model_manifest_missing")
        required_memory = max(24 * 1024**3, int(spec.estimated_bytes * 1.35))
        if required_memory > request.available_memory_bytes:
            exclusions.append("resource_shortage")
        benchmark_ids = tuple(str(item) for item in aggregate.get("benchmarkIds", []))
        if not benchmark_ids or len(benchmark_ids) != len(set(benchmark_ids)):
            exclusions.append("benchmark_cohort_missing_or_duplicate")
        candidate_receipts = []
        for benchmark_id in benchmark_ids:
            receipt = receipts.get(benchmark_id)
            if receipt is None:
                exclusions.append("benchmark_receipt_missing")
                continue
            candidate_receipts.append(receipt)
            if receipt.model_fingerprint != expected_model_fingerprint:
                exclusions.append("benchmark_model_fingerprint_mismatch")
            if receipt.task_kind != request.task_kind:
                exclusions.append("benchmark_task_mismatch")
            if not receipt.all_qc_passed:
                exclusions.append("benchmark_qc_failed")
            if (
                receipt.benchmark_recipe_fingerprint is None
                or receipt.analyzer_registry_fingerprint is None
            ):
                exclusions.append("historical_unlinked_benchmark")
        recorded = _benchmark_recorded_at(benchmark_store, set(benchmark_ids))
        for benchmark_id in benchmark_ids:
            timestamp = recorded.get(benchmark_id)
            if timestamp is None:
                exclusions.append("benchmark_timestamp_missing")
                continue
            recorded_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if (observed_at - recorded_at).total_seconds() > (
                request.maximum_evidence_age_days * 86400
            ):
                exclusions.append("benchmark_evidence_stale")
        approval: dict[str, Any] | None = None
        if expected_model_fingerprint:
            try:
                approval = benchmark_store.active_promotion(
                    candidate_model_fingerprint=expected_model_fingerprint,
                    task_kind=request.task_kind,
                    observed_at=request.observed_at,
                )
            except LocalQueueError:
                exclusions.append("active_promotion_missing_or_invalid")
        measured_yield = aggregate.get("promotionEligibleYield")
        measured_quality = aggregate.get("meanHumanQualityScore")
        latency = aggregate.get("medianWallTimeSeconds")
        peak_memory = aggregate.get("medianPeakMemoryBytes")
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
                    str(item.get("sampleId") or "") for item in intent_samples
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
            "promotionApproval": winner["promotionApproval"],
            "score": winner["score"],
        },
        "operatorOverride": override,
        "paidProviderFallbackAllowed": False,
        "legacyLocalMotionFallbackAllowed": False,
    }
    return {**core, "decisionFingerprint": fingerprint(core)}


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
        decision = route_local_model(
            RouterRequest(**request_payload),
            arena_summary=summary,
            benchmark_store=default_local_model_benchmark_store(args.benchmark_root),
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
