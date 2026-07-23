"""Measured local-model benchmark receipts and explicit promotion decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import resource
import statistics
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from creator_os_core.evidence_attestation import (
    EvidenceAttestationError,
    load_evidence_secret,
    verify_evidence_attestation,
)

from pipeline_contracts import (
    validate_human_media_review,
    validate_motion_specific_qc_receipt_v2,
    validate_trusted_media_analysis,
)

from .fileops import atomic_write_text, file_lock
from .human_media_review import HumanMediaReview
from .identity_verification import (
    MINIMUM_REFERENCE_SOURCES,
    REFERENCE_OUTLIER_MINIMUM_MEDIAN_COSINE,
    REFERENCE_QUALITY_POLICY_ID,
    REFERENCE_QUALITY_POLICY_VERSION,
    REFERENCE_SET_SCHEMA,
)
from .local_generation_queue import (
    AppendOnlyJournal,
    EvidenceRecord,
    JournalCorruptionError,
    LocalGenerationJob,
    LocalGenerationQueue,
    LocalQueueError,
    default_local_generation_queue,
    evidence_record_payload,
    fingerprint,
    sha256_file,
)
from .local_model_manager import model_status

BENCHMARK_SOURCE: Final = "measured_local_execution"
BENCHMARK_SCHEMA: Final = "reel_factory.local_model_benchmark.v1"
PROMOTION_SCHEMA: Final = "reel_factory.local_model_promotion.v1"
SUPPORTED_QC_POLICIES: Final = {
    "contentforge.motion_specific_qc": frozenset({"2.0.0"}),
    "contentforge.media_integrity": frozenset({"1.0.0"}),
    "contentforge.temporal_motion": frozenset({"1.0.0"}),
    "contentforge.audio_integrity": frozenset({"1.0.0"}),
    "contentforge.overlay_delivery": frozenset({"1.0.0"}),
    "reel_factory.identity_preservation": frozenset({"2.0.0"}),
    "reel_factory.structured_human_media_review": frozenset({"1.0.0"}),
}
CONTENTFORGE_COMPONENT_POLICIES: Final = frozenset(
    {
        "contentforge.media_integrity",
        "contentforge.temporal_motion",
        "contentforge.audio_integrity",
        "contentforge.overlay_delivery",
    }
)
DEFAULT_IMPLEMENTATION_ROOT: Final = Path(__file__).resolve().parents[3]


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _canonical_record_text(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _qc_receipt_verdict(
    payload: dict[str, Any], *, check_id: str, expected_version: str | None = None
) -> bool:
    policy = payload.get("policy")
    if isinstance(policy, dict):
        policy_id = str(policy.get("id") or "")
        policy_version = str(policy.get("version") or "")
        if policy_id != check_id or policy_version not in SUPPORTED_QC_POLICIES.get(
            policy_id, frozenset()
        ):
            raise LocalQueueError(f"benchmark_qc_receipt_policy_mismatch:{check_id}")
        if expected_version is not None and policy_version != expected_version:
            raise LocalQueueError(f"benchmark_qc_receipt_policy_drift:{check_id}")
    else:
        raise LocalQueueError(f"benchmark_qc_receipt_policy_missing:{check_id}")
    raw_passed = payload.get("passed")
    if not isinstance(raw_passed, bool):
        raise LocalQueueError(f"benchmark_qc_receipt_verdict_missing:{check_id}")
    verdict = payload.get("verdict")
    if verdict is not None:
        if verdict not in {"pass", "fail", "blocked"}:
            raise LocalQueueError(f"benchmark_qc_receipt_verdict_invalid:{check_id}")
        if raw_passed != (verdict == "pass"):
            raise LocalQueueError(
                f"benchmark_qc_receipt_verdict_inconsistent:{check_id}"
            )
    return raw_passed


def _require_zero_external_activity(payload: Mapping[str, Any], check_id: str) -> None:
    if (
        payload.get("evidenceOnly") is not True
        or payload.get("providerCalls") != 0
        or payload.get("modelCalls", 0) != 0
    ):
        raise LocalQueueError(f"benchmark_qc_receipt_not_evidence_only:{check_id}")


def _validate_trusted_analysis_payload(
    analysis: Any, *, expected_subject_sha256: str
) -> dict[str, Any]:
    if not isinstance(analysis, dict):
        raise LocalQueueError("benchmark_trusted_analysis_missing")
    validate_trusted_media_analysis(analysis)
    claimed = analysis.get("analysisFingerprint")
    core = dict(analysis)
    attestation = core.pop("producerAttestation", None)
    core.pop("analysisFingerprint", None)
    if not isinstance(claimed, str) or fingerprint(core) != claimed:
        raise LocalQueueError("benchmark_trusted_analysis_fingerprint_mismatch")
    attested_payload = {**core, "analysisFingerprint": claimed}
    try:
        verified = verify_evidence_attestation(
            attestation if isinstance(attestation, dict) else {},
            attested_payload,
            secret=load_evidence_secret(),
            expected_issuer="contentforge.trusted_media_analysis",
        )
    except EvidenceAttestationError as exc:
        raise LocalQueueError("benchmark_trusted_analysis_attestation_invalid") from exc
    if verified.get("issuedAt") != analysis.get("producedAt"):
        raise LocalQueueError("benchmark_trusted_analysis_attestation_time_mismatch")
    subject = analysis.get("subject")
    if (
        not isinstance(subject, dict)
        or subject.get("mediaSha256") != expected_subject_sha256
    ):
        raise LocalQueueError("benchmark_trusted_analysis_subject_mismatch")
    return analysis


def _trusted_analysis_verdict(
    analysis: dict[str, Any], *, check_id: str, expected_subject_sha256: str
) -> dict[str, Any]:
    """Select a component verdict only from its complete trusted analysis."""

    _validate_trusted_analysis_payload(
        analysis, expected_subject_sha256=expected_subject_sha256
    )
    verdicts = analysis.get("analyzerVerdicts")
    observations = analysis.get("rawObservations")
    if not isinstance(verdicts, list) or not isinstance(observations, list):
        raise LocalQueueError("benchmark_trusted_analysis_components_missing")
    matching_verdicts = [
        item
        for item in verdicts
        if isinstance(item, dict) and item.get("policy", {}).get("id") == check_id
    ]
    if len(matching_verdicts) != 1:
        raise LocalQueueError(
            f"benchmark_trusted_analysis_verdict_count_mismatch:{check_id}"
        )
    verdict = matching_verdicts[0]
    version = str(verdict.get("policy", {}).get("version") or "")
    matching_observations = [
        item
        for item in observations
        if isinstance(item, dict)
        and item.get("analyzerId") == check_id
        and item.get("analyzerVersion") == version
    ]
    if len(matching_observations) != 1:
        raise LocalQueueError(
            f"benchmark_trusted_analysis_observation_count_mismatch:{check_id}"
        )
    observation = matching_observations[0]
    registry = analysis.get("analyzerRegistry")
    if (
        not isinstance(registry, dict)
        or verdict.get("analysisId") != analysis.get("analysisId")
        or verdict.get("observationFingerprint") != fingerprint(observation)
        or verdict.get("implementationRef") != observation.get("implementationRef")
        or verdict.get("implementationFingerprint")
        != observation.get("implementationFingerprint")
        or verdict.get("analyzerRegistryId") != registry.get("registryId")
        or verdict.get("analyzerRegistryFingerprint")
        != registry.get("registryFingerprint")
        or observation.get("analyzerRegistryId") != registry.get("registryId")
        or observation.get("analyzerRegistryFingerprint")
        != registry.get("registryFingerprint")
    ):
        raise LocalQueueError(
            f"benchmark_trusted_analysis_component_binding_mismatch:{check_id}"
        )
    _validate_contentforge_analyzer_receipt(
        verdict, expected_subject_sha256=expected_subject_sha256
    )
    return verdict


def _receipt_payload_for_check(
    payload: dict[str, Any], *, check_id: str, expected_subject_sha256: str
) -> dict[str, Any]:
    if check_id in CONTENTFORGE_COMPONENT_POLICIES:
        if payload.get("schema") != "contentforge.trusted_media_analysis.v1":
            raise LocalQueueError(f"benchmark_trusted_analysis_required:{check_id}")
        return _trusted_analysis_verdict(
            payload,
            check_id=check_id,
            expected_subject_sha256=expected_subject_sha256,
        )
    return payload


def _validate_contentforge_analyzer_receipt(
    payload: dict[str, Any], *, expected_subject_sha256: str
) -> None:
    check_id = str(payload.get("policy", {}).get("id") or "contentforge")
    _require_zero_external_activity(payload, check_id)
    if payload.get("schema") != "contentforge.trusted_analyzer_receipt.v1":
        raise LocalQueueError(f"benchmark_qc_receipt_schema_mismatch:{check_id}")
    for field in (
        "observationFingerprint",
        "analyzerRegistryFingerprint",
        "implementationFingerprint",
    ):
        if not _valid_sha256(str(payload.get(field) or "")):
            raise LocalQueueError(
                f"benchmark_qc_receipt_trusted_binding_missing:{check_id}:{field}"
            )
    if not str(payload.get("analysisId") or "").strip():
        raise LocalQueueError(
            f"benchmark_qc_receipt_trusted_binding_missing:{check_id}:analysisId"
        )
    if not str(payload.get("analyzerRegistryId") or "").strip():
        raise LocalQueueError(
            f"benchmark_qc_receipt_trusted_binding_missing:{check_id}:registryId"
        )
    if not str(payload.get("implementationRef") or "").strip():
        raise LocalQueueError(
            f"benchmark_qc_receipt_trusted_binding_missing:{check_id}:implementationRef"
        )
    if payload.get("subjectSha256") != expected_subject_sha256:
        raise LocalQueueError(f"benchmark_qc_receipt_subject_mismatch:{check_id}")


def _validate_motion_receipt(
    payload: dict[str, Any], *, expected_subject_sha256: str
) -> None:
    version = str(payload.get("policy", {}).get("version") or "")
    _require_zero_external_activity(payload, "contentforge.motion_specific_qc")
    if version != "2.0.0":
        raise LocalQueueError("benchmark_motion_qc_v2_required")
    validate_motion_specific_qc_receipt_v2(payload)
    claimed = payload.get("receiptFingerprint")
    core = dict(payload)
    producer_attestation = core.pop("producerAttestation", None)
    core.pop("receiptFingerprint", None)
    if not isinstance(claimed, str) or fingerprint(core) != claimed:
        raise LocalQueueError("benchmark_motion_qc_receipt_fingerprint_mismatch")
    trusted = payload.get("trustedEvidence")
    bindings = payload.get("bindings")
    if not isinstance(trusted, dict) or not isinstance(bindings, dict):
        raise LocalQueueError("benchmark_motion_qc_trusted_evidence_missing")
    analysis = _validate_trusted_analysis_payload(
        trusted.get("analysis"), expected_subject_sha256=expected_subject_sha256
    )
    review = trusted.get("humanReview")
    if not isinstance(review, dict):
        raise LocalQueueError("benchmark_motion_qc_human_review_missing")
    validate_human_media_review(review)
    parsed_review = HumanMediaReview.from_dict(review)
    review_claimed = review.get("reviewFingerprint")
    if review_claimed != parsed_review.review_fingerprint:
        raise LocalQueueError("benchmark_motion_qc_human_review_fingerprint_mismatch")
    try:
        verified_attestation = verify_evidence_attestation(
            producer_attestation if isinstance(producer_attestation, dict) else {},
            {**core, "receiptFingerprint": claimed},
            secret=load_evidence_secret(),
            expected_issuer="contentforge.trusted_motion_qc",
        )
    except EvidenceAttestationError as exc:
        raise LocalQueueError("benchmark_motion_qc_attestation_invalid") from exc
    if verified_attestation.get("issuedAt") != review.get("reviewedAt"):
        raise LocalQueueError("benchmark_motion_qc_attestation_time_mismatch")
    registry = trusted.get("analyzerRegistry")
    if not isinstance(registry, dict):
        raise LocalQueueError("benchmark_motion_qc_registry_missing")
    if (
        bindings.get("analysisId") != analysis.get("analysisId")
        or bindings.get("analysisFingerprint") != analysis.get("analysisFingerprint")
        or bindings.get("analyzerRegistryId") != registry.get("registryId")
        or bindings.get("analyzerRegistryFingerprint") != fingerprint(registry)
        or bindings.get("humanReviewId") != review.get("reviewId")
        or bindings.get("humanReviewFingerprint") != review_claimed
        or review.get("subjectSha256") != expected_subject_sha256
        or review.get("sourceSha256") != payload.get("sourceSha256")
    ):
        raise LocalQueueError("benchmark_motion_qc_trusted_binding_mismatch")
    references = review.get("provenance", {}).get("sourceReferences", [])
    if not any(
        isinstance(reference, dict)
        and reference.get("recordId") == analysis.get("analysisId")
        and reference.get("fingerprint") == analysis.get("analysisFingerprint")
        for reference in references
    ):
        raise LocalQueueError("benchmark_motion_qc_analysis_reference_missing")


def _validate_identity_receipt(
    payload: dict[str, Any], *, expected_subject_sha256: str
) -> None:
    _require_zero_external_activity(payload, "reel_factory.identity_preservation")
    if payload.get("schema") != "reel_factory.identity_qc_receipt.v1":
        raise LocalQueueError("benchmark_identity_qc_schema_mismatch")
    result = payload.get("identityResult")
    if not isinstance(result, dict):
        raise LocalQueueError("benchmark_identity_result_missing")
    attestation = payload.get("producerAttestation")
    attested_payload = dict(payload)
    attested_payload.pop("producerAttestation", None)
    try:
        verified = verify_evidence_attestation(
            attestation if isinstance(attestation, dict) else {},
            attested_payload,
            secret=load_evidence_secret(),
            expected_issuer="reel_factory.identity_verification",
        )
    except EvidenceAttestationError as exc:
        raise LocalQueueError("benchmark_identity_attestation_invalid") from exc
    if verified.get("issuedAt") != result.get("observedAt"):
        raise LocalQueueError("benchmark_identity_attestation_time_mismatch")
    result_fingerprint = hashlib.sha256(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    unresolved_reference_path = Path(str(payload.get("referenceSetPath") or ""))
    reference_path = unresolved_reference_path.resolve()
    creator_profile = payload.get("creatorIdentityProfile")
    analyzer = result.get("analyzer")
    if (
        payload.get("identityResultFingerprint") != result_fingerprint
        or result.get("subjectSha256") != expected_subject_sha256
        or result.get("referenceSetId") != payload.get("referenceSetId")
        or result.get("referenceSetFingerprint")
        != payload.get("referenceSetFingerprint")
        or result.get("referenceSetPath") != payload.get("referenceSetPath")
        or unresolved_reference_path.is_symlink()
        or not reference_path.is_file()
        or sha256_file(reference_path) != payload.get("referenceSetFingerprint")
        or not isinstance(creator_profile, dict)
        or creator_profile != result.get("creatorIdentityProfile")
        or not str(creator_profile.get("profileId") or "").strip()
        or not _valid_sha256(str(creator_profile.get("profileFingerprint") or ""))
        or not isinstance(analyzer, dict)
        or payload.get("arcFaceModelFingerprint") != analyzer.get("modelFingerprint")
        or payload.get("implementationFingerprint")
        != analyzer.get("implementationFingerprint")
        or not _valid_sha256(str(payload.get("arcFaceModelFingerprint") or ""))
        or not _valid_sha256(str(payload.get("implementationFingerprint") or ""))
    ):
        raise LocalQueueError("benchmark_identity_reference_set_binding_mismatch")
    try:
        reference_set = json.loads(reference_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise LocalQueueError("benchmark_identity_reference_set_invalid") from exc
    if (
        not isinstance(reference_set, dict)
        or reference_set.get("schema") != REFERENCE_SET_SCHEMA
        or reference_set.get("referenceSetId") != payload.get("referenceSetId")
        or reference_set.get("creator") != payload.get("creator")
        or reference_set.get("qualityPolicy")
        != {
            "id": REFERENCE_QUALITY_POLICY_ID,
            "version": REFERENCE_QUALITY_POLICY_VERSION,
            "exactlyOneFacePerSource": True,
            "minimumAcceptedSources": MINIMUM_REFERENCE_SOURCES,
            "outlierMinimumMedianCosine": REFERENCE_OUTLIER_MINIMUM_MEDIAN_COSINE,
        }
    ):
        raise LocalQueueError("benchmark_identity_reference_set_identity_mismatch")
    sources = reference_set.get("sourceImages")
    if not isinstance(sources, list) or not sources:
        raise LocalQueueError("benchmark_identity_reference_sources_missing")
    accepted_sources = []
    for source in sources:
        if not isinstance(source, dict) or source.get("faceCount") != 1:
            raise LocalQueueError("benchmark_identity_reference_source_invalid")
        if source.get("status") != "embedded":
            continue
        accepted_sources.append(source)
        unresolved_source = Path(str(source.get("path") or ""))
        if (
            unresolved_source.is_symlink()
            or not unresolved_source.is_file()
            or sha256_file(unresolved_source.resolve()) != source.get("sha256")
        ):
            raise LocalQueueError("benchmark_identity_reference_source_substituted")
    if (
        len(accepted_sources) < MINIMUM_REFERENCE_SOURCES
        or reference_set.get("acceptedSourceCount") != len(accepted_sources)
        or reference_set.get("rejectedSourceCount")
        != len(sources) - len(accepted_sources)
        or len(reference_set.get("embeddings") or []) != len(accepted_sources)
    ):
        raise LocalQueueError("benchmark_identity_reference_consensus_invalid")


def _validate_human_review_receipt(
    payload: dict[str, Any], *, expected_subject_sha256: str
) -> None:
    _require_zero_external_activity(
        payload, "reel_factory.structured_human_media_review"
    )
    if payload.get("schema") != "reel_factory.human_media_review_qc.v1":
        raise LocalQueueError("benchmark_human_review_qc_schema_mismatch")
    review = payload.get("humanReview")
    if not isinstance(review, dict):
        raise LocalQueueError("benchmark_human_review_record_missing")
    validate_human_media_review(review)
    parsed_review = HumanMediaReview.from_dict(review)
    claimed = review.get("reviewFingerprint")
    expected_passed = bool(
        parsed_review.decisions.creator_identity_preserved
        and parsed_review.decisions.anatomy_acceptable
        and parsed_review.decisions.operator_useful
        and parsed_review.decisions.approved_for_benchmark
    )
    reviewed_at = datetime.fromisoformat(
        str(review.get("reviewedAt") or "").replace("Z", "+00:00")
    )
    if reviewed_at.tzinfo is None or reviewed_at > datetime.now(UTC):
        raise LocalQueueError("benchmark_human_review_timestamp_invalid")
    if (
        not isinstance(claimed, str)
        or parsed_review.review_fingerprint != claimed
        or review.get("subjectSha256") != expected_subject_sha256
        or review.get("provenance", {}).get("reviewMode") != "blinded"
        or payload.get("reviewFingerprint") != claimed
        or payload.get("arenaPlanId") != review.get("arenaPlanId")
        or payload.get("sampleId") != review.get("sampleId")
        or payload.get("blindedCandidateId") != review.get("blindedCandidateId")
        or payload.get("sourceSha256") != review.get("sourceSha256")
        or payload.get("passed") is not expected_passed
        or payload.get("verdict") != ("pass" if expected_passed else "blocked")
    ):
        raise LocalQueueError("benchmark_human_review_binding_mismatch")


QC_POLICY_VALIDATORS: Final = {
    "contentforge.media_integrity": _validate_contentforge_analyzer_receipt,
    "contentforge.temporal_motion": _validate_contentforge_analyzer_receipt,
    "contentforge.audio_integrity": _validate_contentforge_analyzer_receipt,
    "contentforge.overlay_delivery": _validate_contentforge_analyzer_receipt,
    "contentforge.motion_specific_qc": _validate_motion_receipt,
    "reel_factory.identity_preservation": _validate_identity_receipt,
    "reel_factory.structured_human_media_review": _validate_human_review_receipt,
}


def _validate_policy_specific_qc_receipt(
    payload: dict[str, Any], *, check_id: str, expected_subject_sha256: str
) -> None:
    validator = QC_POLICY_VALIDATORS.get(check_id)
    if validator is None:
        raise LocalQueueError(f"benchmark_qc_validator_missing:{check_id}")
    validator(payload, expected_subject_sha256=expected_subject_sha256)


PROMOTION_MEMORY_MEASUREMENT_METHOD = (
    "resource.getrusage.rusage_children.fresh_maximum.ru_maxrss"
)
_CUMULATIVE_MEMORY_MEASUREMENT_METHOD = (
    "resource.getrusage.max_self_children.cumulative_not_promotion_eligible"
)


def _rss_bytes(value: int) -> int:
    # Darwin reports bytes; Linux and most BSD tooling report KiB.
    if value <= 0:
        raise RuntimeError("peak_memory_measurement_unavailable")
    if __import__("platform").system() == "Darwin":
        return value
    return value * 1024


def _child_peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    return 0 if value <= 0 else _rss_bytes(value)


def _peak_rss_bytes() -> int:
    self_value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    child_value = int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    return _rss_bytes(max(self_value, child_value))


@dataclass(frozen=True)
class LocalExecutionMeasurement:
    wall_time_seconds: float
    peak_memory_bytes: int
    memory_measurement_method: str


@dataclass(frozen=True)
class LocalBenchmarkTimer:
    started_monotonic: float
    child_peak_before_bytes: int = 0

    @classmethod
    def start(cls) -> LocalBenchmarkTimer:
        return cls(
            started_monotonic=time.monotonic(),
            child_peak_before_bytes=_child_peak_rss_bytes(),
        )

    def finish(self) -> LocalExecutionMeasurement:
        wall_time = time.monotonic() - self.started_monotonic
        if wall_time <= 0:
            raise RuntimeError("wall_time_measurement_unavailable")
        child_peak_after = _child_peak_rss_bytes()
        if child_peak_after > self.child_peak_before_bytes:
            peak_memory = child_peak_after
            method = PROMOTION_MEMORY_MEASUREMENT_METHOD
        else:
            # RUSAGE_CHILDREN is a process-lifetime high-water mark. If this
            # child did not establish a new maximum, its individual peak is
            # unknowable. Preserve a diagnostic value but make the receipt
            # explicitly ineligible for model promotion.
            peak_memory = _peak_rss_bytes()
            method = _CUMULATIVE_MEMORY_MEASUREMENT_METHOD
        return LocalExecutionMeasurement(
            wall_time_seconds=wall_time,
            peak_memory_bytes=peak_memory,
            memory_measurement_method=method,
        )


@dataclass(frozen=True)
class QCReference:
    check_id: str
    receipt_uri: str
    receipt_sha256: str
    subject_sha256: str
    passed: bool

    def __post_init__(self) -> None:
        if not self.check_id.strip() or not self.receipt_uri.strip():
            raise ValueError("QC reference check_id and receipt_uri must be non-empty")
        if not _valid_sha256(self.receipt_sha256):
            raise ValueError("QC receipt_sha256 must be a lowercase SHA-256")
        if not _valid_sha256(self.subject_sha256):
            raise ValueError("QC subject_sha256 must be a lowercase SHA-256")

    def as_dict(self) -> dict[str, Any]:
        return {
            "checkId": self.check_id,
            "receiptUri": self.receipt_uri,
            "receiptSha256": self.receipt_sha256,
            "subjectSha256": self.subject_sha256,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class BenchmarkReceipt:
    benchmark_id: str
    job_id: str
    model_fingerprint: str
    task_fingerprint: str
    task_kind: str
    hardware_fingerprint: str
    model_id: str
    model_deep_verification_fingerprint: str
    output_sha256: str
    wall_time_seconds: float
    peak_memory_bytes: int
    memory_measurement_method: str
    qc_references: tuple[QCReference, ...]
    execution_attempt_count: int | None = None
    execution_retry_count: int | None = None
    local_cost_usd: float | None = None
    local_cost_measurement_method: str | None = None
    benchmark_recipe_id: str | None = None
    benchmark_recipe_fingerprint: str | None = None
    analyzer_registry_id: str | None = None
    analyzer_registry_fingerprint: str | None = None
    source: str = BENCHMARK_SOURCE

    def __post_init__(self) -> None:
        for name, value in {
            "benchmark_id": self.benchmark_id,
            "job_id": self.job_id,
            "model_fingerprint": self.model_fingerprint,
            "task_fingerprint": self.task_fingerprint,
            "task_kind": self.task_kind,
            "hardware_fingerprint": self.hardware_fingerprint,
            "model_id": self.model_id,
        }.items():
            if not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if self.source != BENCHMARK_SOURCE:
            raise ValueError("benchmark_source_must_be_measured_local_execution")
        if not _valid_sha256(self.output_sha256):
            raise ValueError("output_sha256 must be a lowercase SHA-256")
        if (
            not _valid_sha256(self.model_deep_verification_fingerprint)
            or not math.isfinite(self.wall_time_seconds)
            or self.wall_time_seconds <= 0
            or self.peak_memory_bytes <= 0
        ):
            raise ValueError(
                "wall time and peak memory must be measured positive values"
            )
        if not self.memory_measurement_method.strip():
            raise ValueError("memory_measurement_method must be non-empty")
        if not self.qc_references:
            raise ValueError("at least one output QC reference is required")
        execution_linkage = (
            self.execution_attempt_count,
            self.execution_retry_count,
            self.local_cost_measurement_method,
        )
        if any(value is not None for value in execution_linkage) and not all(
            value is not None for value in execution_linkage
        ):
            raise ValueError("benchmark_execution_evidence_must_be_complete")
        if self.execution_attempt_count is not None:
            if (
                self.execution_attempt_count <= 0
                or self.execution_retry_count is None
                or self.execution_retry_count != self.execution_attempt_count - 1
            ):
                raise ValueError("benchmark_execution_attempt_evidence_invalid")
            if self.local_cost_measurement_method == "measured":
                if (
                    self.local_cost_usd is None
                    or not math.isfinite(self.local_cost_usd)
                    or self.local_cost_usd < 0
                ):
                    raise ValueError("benchmark_local_cost_measurement_invalid")
            elif self.local_cost_measurement_method == "unavailable:not_metered":
                if self.local_cost_usd is not None:
                    raise ValueError("benchmark_unavailable_local_cost_must_be_null")
            else:
                raise ValueError("benchmark_local_cost_method_invalid")
        linkage = (
            self.benchmark_recipe_id,
            self.benchmark_recipe_fingerprint,
            self.analyzer_registry_id,
            self.analyzer_registry_fingerprint,
        )
        if any(value is not None for value in linkage) and not all(
            value is not None for value in linkage
        ):
            raise ValueError("benchmark_evidence_linkage_must_be_complete")
        if self.benchmark_recipe_id is not None:
            if (
                not self.benchmark_recipe_id.strip()
                or self.analyzer_registry_id is None
                or not self.analyzer_registry_id.strip()
            ):
                raise ValueError("benchmark_evidence_linkage_ids_must_be_non_empty")
            for linkage_fingerprint in (
                self.benchmark_recipe_fingerprint,
                self.analyzer_registry_fingerprint,
            ):
                if linkage_fingerprint is None or not _valid_sha256(
                    linkage_fingerprint
                ):
                    raise ValueError(
                        "benchmark_evidence_linkage_fingerprints_must_be_sha256"
                    )

    @property
    def all_qc_passed(self) -> bool:
        return all(reference.passed for reference in self.qc_references)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schema": BENCHMARK_SCHEMA,
            "benchmarkId": self.benchmark_id,
            "jobId": self.job_id,
            "modelFingerprint": self.model_fingerprint,
            "taskFingerprint": self.task_fingerprint,
            "taskKind": self.task_kind,
            "hardwareFingerprint": self.hardware_fingerprint,
            "modelId": self.model_id,
            "modelDeepVerificationFingerprint": self.model_deep_verification_fingerprint,
            "outputSha256": self.output_sha256,
            "wallTimeSeconds": self.wall_time_seconds,
            "peakMemoryBytes": self.peak_memory_bytes,
            "memoryMeasurementMethod": self.memory_measurement_method,
            "qcReferences": [reference.as_dict() for reference in self.qc_references],
            "source": self.source,
        }
        if self.benchmark_recipe_id is not None:
            payload.update(
                {
                    "benchmarkRecipeId": self.benchmark_recipe_id,
                    "benchmarkRecipeFingerprint": self.benchmark_recipe_fingerprint,
                    "analyzerRegistryId": self.analyzer_registry_id,
                    "analyzerRegistryFingerprint": self.analyzer_registry_fingerprint,
                }
            )
        if self.execution_attempt_count is not None:
            payload.update(
                {
                    "executionAttemptCount": self.execution_attempt_count,
                    "executionRetryCount": self.execution_retry_count,
                    "localCostUsd": self.local_cost_usd,
                    "localCostMeasurementMethod": self.local_cost_measurement_method,
                }
            )
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BenchmarkReceipt:
        if not payload.get("modelId") or not payload.get(
            "modelDeepVerificationFingerprint"
        ):
            raise ValueError("historical_benchmark_missing_deep_model_evidence")
        references = tuple(
            QCReference(
                check_id=str(item["checkId"]),
                receipt_uri=str(item["receiptUri"]),
                receipt_sha256=str(item["receiptSha256"]),
                subject_sha256=str(item["subjectSha256"]),
                passed=bool(item["passed"]),
            )
            for item in payload["qcReferences"]
        )
        return cls(
            benchmark_id=str(payload["benchmarkId"]),
            job_id=str(payload["jobId"]),
            model_fingerprint=str(payload["modelFingerprint"]),
            task_fingerprint=str(payload["taskFingerprint"]),
            task_kind=str(payload["taskKind"]),
            hardware_fingerprint=str(payload["hardwareFingerprint"]),
            model_id=str(payload["modelId"]),
            model_deep_verification_fingerprint=str(
                payload["modelDeepVerificationFingerprint"]
            ),
            output_sha256=str(payload["outputSha256"]),
            wall_time_seconds=float(payload["wallTimeSeconds"]),
            peak_memory_bytes=int(payload["peakMemoryBytes"]),
            memory_measurement_method=str(payload["memoryMeasurementMethod"]),
            qc_references=references,
            execution_attempt_count=(
                int(payload["executionAttemptCount"])
                if payload.get("executionAttemptCount") is not None
                else None
            ),
            execution_retry_count=(
                int(payload["executionRetryCount"])
                if payload.get("executionRetryCount") is not None
                else None
            ),
            local_cost_usd=(
                float(payload["localCostUsd"])
                if payload.get("localCostUsd") is not None
                else None
            ),
            local_cost_measurement_method=(
                str(payload["localCostMeasurementMethod"])
                if payload.get("localCostMeasurementMethod") is not None
                else None
            ),
            benchmark_recipe_id=(
                str(payload["benchmarkRecipeId"])
                if payload.get("benchmarkRecipeId") is not None
                else None
            ),
            benchmark_recipe_fingerprint=(
                str(payload["benchmarkRecipeFingerprint"])
                if payload.get("benchmarkRecipeFingerprint") is not None
                else None
            ),
            analyzer_registry_id=(
                str(payload["analyzerRegistryId"])
                if payload.get("analyzerRegistryId") is not None
                else None
            ),
            analyzer_registry_fingerprint=(
                str(payload["analyzerRegistryFingerprint"])
                if payload.get("analyzerRegistryFingerprint") is not None
                else None
            ),
            source=str(payload["source"]),
        )


@dataclass(frozen=True)
class PromotionPolicy:
    minimum_candidate_samples: int = 2
    minimum_baseline_samples: int = 2
    maximum_wall_time_ratio: float = 1.25
    maximum_peak_memory_ratio: float = 1.25

    def __post_init__(self) -> None:
        if self.minimum_candidate_samples < 2 or self.minimum_baseline_samples < 2:
            raise ValueError("promotion sample minimums cannot weaken the fixed floor")
        if (
            not math.isfinite(self.maximum_wall_time_ratio)
            or not math.isfinite(self.maximum_peak_memory_ratio)
            or not 0 < self.maximum_wall_time_ratio <= 1.25
            or not 0 < self.maximum_peak_memory_ratio <= 1.25
        ):
            raise ValueError("promotion ratios cannot weaken the fixed ceiling")


@dataclass(frozen=True)
class PromotionEvaluation:
    evaluation_id: str
    candidate_model_fingerprint: str
    baseline_model_fingerprint: str
    task_kind: str
    hardware_fingerprint: str
    eligible: bool
    blocking_reasons: tuple[str, ...]
    candidate_benchmark_ids: tuple[str, ...]
    baseline_benchmark_ids: tuple[str, ...]
    evidence_fingerprint: str
    wall_time_ratio: float | None
    peak_memory_ratio: float | None


class LocalModelBenchmarkStore:
    """Store real benchmark observations and manual, evidence-bound promotions."""

    def __init__(
        self,
        root: Path,
        *,
        implementation_root: Path | None = None,
        model_status_resolver: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.implementation_root = (
            implementation_root or DEFAULT_IMPLEMENTATION_ROOT
        ).resolve()
        self.benchmarks = AppendOnlyJournal(self.root / "benchmarks.jsonl")
        self.promotions = AppendOnlyJournal(self.root / "promotions.jsonl")
        self._mutation_path = self.root / "benchmark_mutation"
        self._model_status_resolver = model_status_resolver or model_status

    def all_receipts(self) -> dict[str, BenchmarkReceipt]:
        receipts: dict[str, BenchmarkReceipt] = {}
        for event in self.benchmarks.read().events:
            if event.get("eventType") != "benchmark_recorded":
                continue
            receipt = BenchmarkReceipt.from_dict(dict(event["payload"]))
            if receipt.benchmark_id in receipts:
                raise LocalQueueError(f"duplicate_benchmark_id:{receipt.benchmark_id}")
            receipts[receipt.benchmark_id] = receipt
        return receipts

    def _verify_benchmark_evidence_linkage(
        self,
        job: LocalGenerationJob,
        *,
        benchmark_recipe: EvidenceRecord | None,
        analyzer_registry: EvidenceRecord | None,
    ) -> dict[str, str]:
        if benchmark_recipe is None:
            raise LocalQueueError("benchmark_recipe_evidence_required")
        if analyzer_registry is None:
            raise LocalQueueError("benchmark_analyzer_registry_evidence_required")
        recipe_payload = evidence_record_payload(benchmark_recipe)
        registry_payload = evidence_record_payload(analyzer_registry)
        if recipe_payload.get("schema") != "creator_os.benchmark_recipe.v1":
            raise LocalQueueError("benchmark_recipe_schema_mismatch")
        if registry_payload.get("schema") != "creator_os.analyzer_registry.v1":
            raise LocalQueueError("benchmark_analyzer_registry_schema_mismatch")
        recipe_fingerprint = fingerprint(recipe_payload)
        registry_fingerprint = fingerprint(registry_payload)
        if job.benchmark_recipe_id is None:
            raise LocalQueueError("benchmark_job_recipe_linkage_missing")
        if (
            job.benchmark_recipe_id != recipe_payload.get("recipeId")
            or job.benchmark_recipe_fingerprint != recipe_fingerprint
        ):
            raise LocalQueueError("benchmark_job_recipe_linkage_mismatch")
        if (
            job.analyzer_registry_id != registry_payload.get("registryId")
            or job.analyzer_registry_fingerprint != registry_fingerprint
        ):
            raise LocalQueueError("benchmark_job_analyzer_registry_drift")
        if recipe_payload.get("taskKind") != job.task_kind:
            raise LocalQueueError("benchmark_recipe_task_kind_mismatch")
        if recipe_payload.get("expectedProviderCalls") != 0:
            raise LocalQueueError("benchmark_recipe_provider_calls_must_be_zero")
        if recipe_payload.get("productionWritesAllowed") is not False:
            raise LocalQueueError("benchmark_recipe_production_writes_must_be_false")
        required = self._required_analyzers(
            benchmark_recipe=recipe_payload,
            analyzer_registry=registry_payload,
        )
        self._verify_analyzer_implementations(registry_payload)
        return required

    @staticmethod
    def _required_analyzers(
        *,
        benchmark_recipe: Mapping[str, Any],
        analyzer_registry: Mapping[str, Any],
    ) -> dict[str, str]:
        raw_requirements = benchmark_recipe.get("requiredAnalyzers")
        raw_registrations = analyzer_registry.get("analyzers")
        if not isinstance(raw_requirements, list) or not raw_requirements:
            raise LocalQueueError("benchmark_recipe_required_analyzers_missing")
        if not isinstance(raw_registrations, list) or not raw_registrations:
            raise LocalQueueError("benchmark_analyzer_registry_empty")
        required = {
            str(requirement["analyzerId"]): str(requirement["analyzerVersion"])
            for requirement in raw_requirements
            if isinstance(requirement, dict)
            and requirement.get("analyzerId")
            and requirement.get("analyzerVersion")
        }
        if len(required) != len(raw_requirements):
            raise LocalQueueError("benchmark_recipe_duplicate_analyzer_identity")
        registered = {
            str(registration["analyzerId"]): registration
            for registration in raw_registrations
            if isinstance(registration, dict)
            and registration.get("analyzerId")
            and registration.get("analyzerVersion")
        }
        if len(registered) != len(raw_registrations):
            raise LocalQueueError("benchmark_analyzer_registration_invalid")
        for analyzer_id, analyzer_version in required.items():
            registration = registered.get(analyzer_id)
            if registration is None:
                raise LocalQueueError(
                    f"benchmark_required_analyzer_unregistered:{analyzer_id}"
                )
            if registration.get("analyzerVersion") != analyzer_version:
                raise LocalQueueError(
                    f"benchmark_required_analyzer_version_drift:{analyzer_id}"
                )
            evidence_kinds = registration.get("evidenceKinds")
            if (
                not isinstance(evidence_kinds, list)
                or not evidence_kinds
                or any(
                    not isinstance(kind, str) or not kind.strip()
                    for kind in evidence_kinds
                )
            ):
                raise LocalQueueError(
                    f"benchmark_analyzer_evidence_kinds_invalid:{analyzer_id}"
                )
        return required

    def _verify_analyzer_implementations(
        self, analyzer_registry: Mapping[str, Any]
    ) -> None:
        registrations = analyzer_registry.get("analyzers")
        if not isinstance(registrations, list) or not registrations:
            raise LocalQueueError("benchmark_analyzer_registry_empty")
        for registration in registrations:
            if not isinstance(registration, dict):
                raise LocalQueueError("benchmark_analyzer_registration_invalid")
            analyzer_id = str(registration.get("analyzerId") or "")
            relative = Path(str(registration.get("implementationRef") or ""))
            if relative.is_absolute():
                raise LocalQueueError(
                    f"benchmark_analyzer_implementation_ref_not_relative:{analyzer_id}"
                )
            unresolved = self.implementation_root / relative
            resolved = unresolved.resolve()
            if not resolved.is_relative_to(self.implementation_root):
                raise LocalQueueError(
                    f"benchmark_analyzer_implementation_ref_escapes_root:{analyzer_id}"
                )
            if (
                not resolved.is_file()
                or unresolved.is_symlink()
                or sha256_file(resolved)
                != registration.get("implementationFingerprint")
            ):
                raise LocalQueueError(
                    f"benchmark_analyzer_implementation_drift:{analyzer_id}"
                )

    def _persist_benchmark_evidence(
        self,
        *,
        benchmark_recipe: Mapping[str, Any],
        analyzer_registry: Mapping[str, Any],
    ) -> None:
        records = (
            (
                "recipes",
                fingerprint(benchmark_recipe),
                dict(benchmark_recipe),
            ),
            (
                "analyzer_registries",
                fingerprint(analyzer_registry),
                dict(analyzer_registry),
            ),
        )
        for directory, expected_fingerprint, payload in records:
            path = self.root / directory / f"{expected_fingerprint}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            encoded = _canonical_record_text(payload)
            if path.exists():
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or sha256_file(path) != expected_fingerprint
                ):
                    raise LocalQueueError(
                        f"benchmark_evidence_collision:{expected_fingerprint}"
                    )
                continue
            atomic_write_text(path, encoded)
            if sha256_file(path) != expected_fingerprint:
                raise LocalQueueError(
                    f"benchmark_evidence_persistence_failed:{expected_fingerprint}"
                )

    def _load_receipt_evidence(
        self, receipt: BenchmarkReceipt
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if (
            receipt.benchmark_recipe_id is None
            or receipt.benchmark_recipe_fingerprint is None
            or receipt.analyzer_registry_id is None
            or receipt.analyzer_registry_fingerprint is None
        ):
            raise LocalQueueError("benchmark_receipt_evidence_linkage_missing")
        recipe_payload = self._load_evidence_payload(
            "recipes", receipt.benchmark_recipe_fingerprint
        )
        registry_payload = self._load_evidence_payload(
            "analyzer_registries", receipt.analyzer_registry_fingerprint
        )
        if recipe_payload.get("schema") != "creator_os.benchmark_recipe.v1":
            raise LocalQueueError("benchmark_persisted_recipe_schema_mismatch")
        if registry_payload.get("schema") != "creator_os.analyzer_registry.v1":
            raise LocalQueueError("benchmark_persisted_registry_schema_mismatch")
        if recipe_payload.get("recipeId") != receipt.benchmark_recipe_id:
            raise LocalQueueError("benchmark_receipt_recipe_id_mismatch")
        if registry_payload.get("registryId") != receipt.analyzer_registry_id:
            raise LocalQueueError("benchmark_receipt_analyzer_registry_id_mismatch")
        self._required_analyzers(
            benchmark_recipe=recipe_payload,
            analyzer_registry=registry_payload,
        )
        self._verify_analyzer_implementations(registry_payload)
        return recipe_payload, registry_payload

    def _load_evidence_payload(
        self, directory: str, expected_fingerprint: str
    ) -> dict[str, Any]:
        path = self.root / directory / f"{expected_fingerprint}.json"
        if (
            not path.is_file()
            or path.is_symlink()
            or sha256_file(path) != expected_fingerprint
        ):
            raise LocalQueueError(
                f"benchmark_persisted_evidence_missing_or_substituted:"
                f"{expected_fingerprint}"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise LocalQueueError("benchmark_persisted_evidence_invalid") from exc
        if (
            not isinstance(payload, dict)
            or fingerprint(payload) != expected_fingerprint
        ):
            raise LocalQueueError("benchmark_persisted_evidence_fingerprint_mismatch")
        return payload

    def _deep_model_verification(self, model_id: str) -> dict[str, Any]:
        status = self._model_status_resolver(model_id, deep=True)
        receipt = status.get("deepVerificationReceipt")
        if (
            status.get("ready") is not True
            or status.get("deepVerified") is not True
            or not isinstance(receipt, dict)
        ):
            raise LocalQueueError(f"benchmark_model_not_deep_verified:{model_id}")
        claimed = receipt.get("verificationFingerprint")
        core = dict(receipt)
        core.pop("verificationFingerprint", None)
        if not isinstance(claimed, str) or fingerprint(core) != claimed:
            raise LocalQueueError(
                f"benchmark_model_deep_verification_receipt_invalid:{model_id}"
            )
        if (
            receipt.get("modelId") != model_id
            or receipt.get("manifestSha256") != status.get("manifestSha256")
            or receipt.get("providerCalls") != 0
            or receipt.get("paidGeneration") is not False
        ):
            raise LocalQueueError(
                f"benchmark_model_deep_verification_binding_mismatch:{model_id}"
            )
        return receipt

    def record_completed_job(
        self,
        queue: LocalGenerationQueue,
        *,
        job_id: str,
        qc_references: tuple[QCReference, ...],
        benchmark_id: str | None = None,
        benchmark_recipe: EvidenceRecord | None = None,
        analyzer_registry: EvidenceRecord | None = None,
    ) -> BenchmarkReceipt:
        state = queue.states().get(job_id)
        if state is None or state.status != "succeeded":
            status = "missing" if state is None else state.status
            raise LocalQueueError(f"benchmark_requires_succeeded_job:{job_id}:{status}")
        required_analyzers = self._verify_benchmark_evidence_linkage(
            state.job,
            benchmark_recipe=benchmark_recipe,
            analyzer_registry=analyzer_registry,
        )
        deep_model_receipt = self._deep_model_verification(state.job.model_id)
        deep_model_fingerprint = fingerprint(
            {
                "modelId": state.job.model_id,
                "modelRevision": deep_model_receipt["revision"],
                "modelManifestSha256": deep_model_receipt["manifestSha256"],
            }
        )
        if deep_model_fingerprint != state.job.model_fingerprint:
            raise LocalQueueError("benchmark_deep_verified_model_job_mismatch")
        terminal_payload = state.last_event.get("payload", {})
        output_sha256 = str(terminal_payload.get("outputSha256", ""))
        output_path = Path(str(terminal_payload.get("outputPath") or "")).resolve()
        if not output_path.is_file() or sha256_file(output_path) != output_sha256:
            raise LocalQueueError("benchmark_output_missing_or_substituted")
        measurement = self._measurement_from_terminal_payload(terminal_payload)
        execution = queue.execution_evidence(job_id)
        if execution.get("status") != "succeeded":
            raise LocalQueueError("benchmark_execution_status_mismatch")
        attempt_count = int(execution.get("attemptCount") or 0)
        retry_count = int(execution.get("retryCount") or 0)
        if attempt_count <= 0 or retry_count != attempt_count - 1:
            raise LocalQueueError("benchmark_execution_attempt_evidence_invalid")
        if execution.get("failureClass") is not None:
            raise LocalQueueError("benchmark_success_claims_failure_class")
        local_cost = execution.get("localCost")
        if not isinstance(local_cost, dict):
            raise LocalQueueError("benchmark_local_cost_evidence_missing")
        if local_cost.get("available") is False:
            if local_cost.get("reason") != "local_compute_cost_not_metered":
                raise LocalQueueError("benchmark_local_cost_unavailable_reason_invalid")
            local_cost_usd = None
            local_cost_method = "unavailable:not_metered"
        elif local_cost.get("available") is True:
            try:
                local_cost_usd = float(local_cost["value"])
            except (KeyError, TypeError, ValueError) as exc:
                raise LocalQueueError(
                    "benchmark_local_cost_measurement_invalid"
                ) from exc
            if (
                local_cost.get("currency") != "USD"
                or not math.isfinite(local_cost_usd)
                or local_cost_usd < 0
            ):
                raise LocalQueueError("benchmark_local_cost_measurement_invalid")
            local_cost_method = "measured"
        else:
            raise LocalQueueError("benchmark_local_cost_evidence_invalid")
        self._verify_artifact_event(
            queue,
            state.job,
            terminal_event=state.last_event,
            output_path=output_path,
            output_sha256=output_sha256,
            measurement=measurement,
        )
        start_event = self._start_event(queue, job_id)
        hardware = start_event.get("payload", {}).get("hardware", {})
        hardware_fp = str(hardware.get("fingerprint", ""))
        if not hardware_fp:
            raise LocalQueueError("benchmark_missing_hardware_fingerprint")
        check_ids = [reference.check_id for reference in qc_references]
        if len(check_ids) != len(set(check_ids)):
            raise LocalQueueError("benchmark_duplicate_qc_check_id")
        missing_qc = sorted(set(required_analyzers).difference(check_ids))
        if missing_qc:
            raise LocalQueueError(
                "benchmark_required_qc_missing:" + ",".join(missing_qc)
            )
        for reference in qc_references:
            self._verify_qc_reference(
                reference,
                expected_subject_sha256=output_sha256,
                expected_version=required_analyzers.get(reference.check_id),
            )
        assert benchmark_recipe is not None
        assert analyzer_registry is not None
        recipe_payload = evidence_record_payload(benchmark_recipe)
        registry_payload = evidence_record_payload(analyzer_registry)
        deterministic_material = {
            "jobId": job_id,
            "outputSha256": output_sha256,
            "benchmarkRecipeFingerprint": fingerprint(recipe_payload),
            "analyzerRegistryFingerprint": fingerprint(registry_payload),
            "qcReferences": [reference.as_dict() for reference in qc_references],
            "modelDeepVerificationFingerprint": deep_model_receipt[
                "verificationFingerprint"
            ],
        }
        receipt = BenchmarkReceipt(
            benchmark_id=benchmark_id
            or f"benchmark_{fingerprint(deterministic_material)[:24]}",
            job_id=job_id,
            model_fingerprint=state.job.model_fingerprint,
            task_fingerprint=state.job.task_fingerprint,
            task_kind=state.job.task_kind,
            hardware_fingerprint=hardware_fp,
            model_id=state.job.model_id,
            model_deep_verification_fingerprint=str(
                deep_model_receipt["verificationFingerprint"]
            ),
            output_sha256=output_sha256,
            wall_time_seconds=measurement.wall_time_seconds,
            peak_memory_bytes=measurement.peak_memory_bytes,
            memory_measurement_method=measurement.memory_measurement_method,
            qc_references=qc_references,
            execution_attempt_count=attempt_count,
            execution_retry_count=retry_count,
            local_cost_usd=local_cost_usd,
            local_cost_measurement_method=local_cost_method,
            benchmark_recipe_id=str(recipe_payload["recipeId"]),
            benchmark_recipe_fingerprint=fingerprint(recipe_payload),
            analyzer_registry_id=str(registry_payload["registryId"]),
            analyzer_registry_fingerprint=fingerprint(registry_payload),
        )
        with file_lock(self._mutation_path):
            existing_receipts = self.all_receipts()
            existing_by_id = existing_receipts.get(receipt.benchmark_id)
            if existing_by_id is not None:
                if existing_by_id == receipt:
                    return existing_by_id
                raise LocalQueueError(
                    f"benchmark_identity_collision:{receipt.benchmark_id}"
                )
            existing_by_job = next(
                (
                    existing
                    for existing in existing_receipts.values()
                    if existing.job_id == receipt.job_id
                ),
                None,
            )
            if existing_by_job is not None:
                if existing_by_job == receipt:
                    return existing_by_job
                raise LocalQueueError(f"benchmark_job_collision:{receipt.job_id}")
            self._persist_benchmark_evidence(
                benchmark_recipe=recipe_payload,
                analyzer_registry=registry_payload,
            )
            self._verify_analyzer_implementations(registry_payload)
            self.benchmarks.append("benchmark_recorded", receipt.as_dict())
            return receipt

    def ingest_qc_reference(
        self, *, check_id: str, receipt_path: Path, expected_subject_sha256: str
    ) -> QCReference:
        """Copy one exact, output-bound QC receipt into durable evidence storage."""

        if not check_id.strip():
            raise ValueError("QC check_id must be non-empty")
        source = receipt_path.expanduser().resolve()
        if not source.is_file() or source.is_symlink():
            raise LocalQueueError(f"benchmark_qc_receipt_missing:{check_id}")
        digest = sha256_file(source)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise LocalQueueError(f"benchmark_qc_receipt_not_json:{check_id}") from exc
        if not isinstance(payload, dict):
            raise LocalQueueError(f"benchmark_qc_receipt_not_json:{check_id}")
        subject = (
            payload.get("subject", {}).get("mediaSha256")
            if payload.get("schema") == "contentforge.trusted_media_analysis.v1"
            and isinstance(payload.get("subject"), dict)
            else (
                payload.get("subjectSha256")
                or payload.get("mediaSha256")
                or payload.get("outputSha256")
            )
        )
        if subject != expected_subject_sha256:
            raise LocalQueueError(f"benchmark_qc_receipt_subject_mismatch:{check_id}")
        receipt_payload = _receipt_payload_for_check(
            payload,
            check_id=check_id,
            expected_subject_sha256=expected_subject_sha256,
        )
        passed = _qc_receipt_verdict(receipt_payload, check_id=check_id)
        _validate_policy_specific_qc_receipt(
            receipt_payload,
            check_id=check_id,
            expected_subject_sha256=expected_subject_sha256,
        )
        relative = Path("qc") / f"{digest}.json"
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if not destination.is_file() or sha256_file(destination) != digest:
                raise LocalQueueError(f"benchmark_qc_evidence_collision:{check_id}")
        else:
            atomic_write_text(destination, source.read_text(encoding="utf-8"))
            if sha256_file(destination) != digest:
                raise LocalQueueError(f"benchmark_qc_evidence_copy_failed:{check_id}")
        return QCReference(
            check_id=check_id,
            receipt_uri=str(relative),
            receipt_sha256=digest,
            subject_sha256=expected_subject_sha256,
            passed=passed,
        )

    def evaluate_promotion(
        self,
        *,
        candidate_model_fingerprint: str,
        baseline_model_fingerprint: str,
        task_kind: str,
        hardware_fingerprint: str,
        candidate_benchmark_ids: tuple[str, ...],
        baseline_benchmark_ids: tuple[str, ...],
        policy: PromotionPolicy = PromotionPolicy(),
    ) -> PromotionEvaluation:
        receipts = self.all_receipts()
        blockers: list[str] = []
        candidate = self._resolve_receipts(
            receipts, candidate_benchmark_ids, "candidate", blockers
        )
        baseline = self._resolve_receipts(
            receipts, baseline_benchmark_ids, "baseline", blockers
        )
        if len(candidate) < policy.minimum_candidate_samples:
            blockers.append("insufficient_candidate_samples")
        if len(baseline) < policy.minimum_baseline_samples:
            blockers.append("insufficient_baseline_samples")
        if candidate_model_fingerprint == baseline_model_fingerprint:
            blockers.append("candidate_matches_baseline_model")
        for label, group, expected_model in (
            ("candidate", candidate, candidate_model_fingerprint),
            ("baseline", baseline, baseline_model_fingerprint),
        ):
            for receipt in group:
                if receipt.source != BENCHMARK_SOURCE:
                    blockers.append(f"{label}_benchmark_not_measured")
                if receipt.model_fingerprint != expected_model:
                    blockers.append(f"{label}_model_fingerprint_mismatch")
                if receipt.task_kind != task_kind:
                    blockers.append(f"{label}_task_kind_mismatch")
                if receipt.hardware_fingerprint != hardware_fingerprint:
                    blockers.append(f"{label}_hardware_fingerprint_mismatch")
                if (
                    receipt.execution_attempt_count is None
                    or receipt.execution_retry_count is None
                    or receipt.local_cost_measurement_method is None
                ):
                    blockers.append(f"{label}_execution_evidence_missing")
                if not receipt.all_qc_passed:
                    blockers.append(f"{label}_qc_failed")
                expected_versions: dict[str, str] = {}
                try:
                    recipe, registry = self._load_receipt_evidence(receipt)
                    expected_versions = self._required_analyzers(
                        benchmark_recipe=recipe,
                        analyzer_registry=registry,
                    )
                    if recipe.get("taskKind") != receipt.task_kind:
                        blockers.append(f"{label}_recipe_task_kind_mismatch")
                    missing_qc = set(expected_versions).difference(
                        reference.check_id for reference in receipt.qc_references
                    )
                    if missing_qc:
                        blockers.append(f"{label}_required_qc_missing")
                except LocalQueueError as exc:
                    blockers.append(f"{label}_benchmark_evidence_invalid:{exc}")
                for reference in receipt.qc_references:
                    try:
                        self._verify_qc_reference(
                            reference,
                            expected_subject_sha256=receipt.output_sha256,
                            expected_version=expected_versions.get(reference.check_id),
                        )
                    except LocalQueueError:
                        blockers.append(
                            f"{label}_qc_evidence_unavailable:{reference.check_id}"
                        )
        if sorted(receipt.task_fingerprint for receipt in candidate) != sorted(
            receipt.task_fingerprint for receipt in baseline
        ):
            blockers.append("task_fingerprint_cohort_mismatch")
        if sorted(self._recipe_link(receipt) for receipt in candidate) != sorted(
            self._recipe_link(receipt) for receipt in baseline
        ):
            blockers.append("benchmark_recipe_cohort_mismatch")
        if sorted(self._registry_link(receipt) for receipt in candidate) != sorted(
            self._registry_link(receipt) for receipt in baseline
        ):
            blockers.append("analyzer_registry_cohort_mismatch")
        wall_ratio = self._median_ratio(candidate, baseline, "wall_time_seconds")
        memory_ratio = self._median_ratio(candidate, baseline, "peak_memory_bytes")
        if wall_ratio is None:
            blockers.append("wall_time_evidence_missing")
        elif wall_ratio > policy.maximum_wall_time_ratio:
            blockers.append("wall_time_regression_exceeds_policy")
        if memory_ratio is None:
            blockers.append("peak_memory_evidence_missing")
        elif memory_ratio > policy.maximum_peak_memory_ratio:
            blockers.append("peak_memory_regression_exceeds_policy")
        evidence = {
            "candidateBenchmarkIds": list(candidate_benchmark_ids),
            "baselineBenchmarkIds": list(baseline_benchmark_ids),
            "candidateModelFingerprint": candidate_model_fingerprint,
            "baselineModelFingerprint": baseline_model_fingerprint,
            "taskKind": task_kind,
            "hardwareFingerprint": hardware_fingerprint,
            "benchmarkEvidenceLinks": {
                "candidate": [
                    self._receipt_evidence_link(receipt) for receipt in candidate
                ],
                "baseline": [
                    self._receipt_evidence_link(receipt) for receipt in baseline
                ],
            },
            "policy": {
                "minimumCandidateSamples": policy.minimum_candidate_samples,
                "minimumBaselineSamples": policy.minimum_baseline_samples,
                "maximumWallTimeRatio": policy.maximum_wall_time_ratio,
                "maximumPeakMemoryRatio": policy.maximum_peak_memory_ratio,
            },
        }
        evaluation = PromotionEvaluation(
            evaluation_id=str(uuid.uuid4()),
            candidate_model_fingerprint=candidate_model_fingerprint,
            baseline_model_fingerprint=baseline_model_fingerprint,
            task_kind=task_kind,
            hardware_fingerprint=hardware_fingerprint,
            eligible=not blockers,
            blocking_reasons=tuple(sorted(set(blockers))),
            candidate_benchmark_ids=candidate_benchmark_ids,
            baseline_benchmark_ids=baseline_benchmark_ids,
            evidence_fingerprint=fingerprint(evidence),
            wall_time_ratio=wall_ratio,
            peak_memory_ratio=memory_ratio,
        )
        self.promotions.append(
            "promotion_evaluated",
            {
                "schema": PROMOTION_SCHEMA,
                "evaluationId": evaluation.evaluation_id,
                **evidence,
                "evidenceFingerprint": evaluation.evidence_fingerprint,
                "eligible": evaluation.eligible,
                "blockingReasons": list(evaluation.blocking_reasons),
                "wallTimeRatio": wall_ratio,
                "peakMemoryRatio": memory_ratio,
            },
        )
        return evaluation

    def approve_promotion(
        self,
        evaluation: PromotionEvaluation,
        *,
        approved_by: str,
        reason: str,
        scope: tuple[str, ...] = (),
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        persisted = self.evaluation(evaluation.evaluation_id)
        if persisted != evaluation:
            raise LocalQueueError("promotion_evaluation_caller_payload_mismatch")
        if not persisted.eligible:
            raise LocalQueueError(
                "promotion_not_evidence_eligible:"
                + ",".join(persisted.blocking_reasons)
            )
        if not approved_by.strip() or not reason.strip():
            raise ValueError("approved_by and reason must be non-empty")
        if len(scope) != len(set(scope)) or any(not item.strip() for item in scope):
            raise ValueError("promotion_scope_must_be_distinct_non_empty_values")
        if expires_at is not None:
            parsed_expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if parsed_expiry.tzinfo is None:
                raise ValueError("promotion_expiry_timezone_required")
        with file_lock(self._mutation_path):
            return self._approve_promotion_locked(
                persisted,
                approved_by=approved_by,
                reason=reason,
                scope=scope,
                expires_at=expires_at,
            )

    def evaluation(self, evaluation_id: str) -> PromotionEvaluation:
        events = [
            event
            for event in self.promotions.read().events
            if event.get("eventType") == "promotion_evaluated"
            and event.get("payload", {}).get("evaluationId") == evaluation_id
        ]
        if len(events) != 1:
            raise LocalQueueError(
                f"promotion_evaluation_not_found_exactly_once:{evaluation_id}"
            )
        payload = events[0]["payload"]
        return PromotionEvaluation(
            evaluation_id=str(payload["evaluationId"]),
            candidate_model_fingerprint=str(payload["candidateModelFingerprint"]),
            baseline_model_fingerprint=str(payload["baselineModelFingerprint"]),
            task_kind=str(payload["taskKind"]),
            hardware_fingerprint=str(payload["hardwareFingerprint"]),
            eligible=bool(payload["eligible"]),
            blocking_reasons=tuple(str(item) for item in payload["blockingReasons"]),
            candidate_benchmark_ids=tuple(
                str(item) for item in payload["candidateBenchmarkIds"]
            ),
            baseline_benchmark_ids=tuple(
                str(item) for item in payload["baselineBenchmarkIds"]
            ),
            evidence_fingerprint=str(payload["evidenceFingerprint"]),
            wall_time_ratio=(
                float(payload["wallTimeRatio"])
                if payload.get("wallTimeRatio") is not None
                else None
            ),
            peak_memory_ratio=(
                float(payload["peakMemoryRatio"])
                if payload.get("peakMemoryRatio") is not None
                else None
            ),
        )

    def approve_persisted_promotion(
        self,
        evaluation_id: str,
        *,
        approved_by: str,
        reason: str,
        scope: tuple[str, ...] = (),
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Explicitly approve one persisted, still-verifiable evaluation."""

        evaluation = self.evaluation(evaluation_id)
        return self.approve_promotion(
            evaluation,
            approved_by=approved_by,
            reason=reason,
            scope=scope,
            expires_at=expires_at,
        )

    def _approve_promotion_locked(
        self,
        evaluation: PromotionEvaluation,
        *,
        approved_by: str,
        reason: str,
        scope: tuple[str, ...],
        expires_at: str | None,
    ) -> dict[str, Any]:
        evaluation_events = [
            event
            for event in self.promotions.read().events
            if event.get("eventType") == "promotion_evaluated"
            and event.get("payload", {}).get("evaluationId") == evaluation.evaluation_id
        ]
        if len(evaluation_events) != 1:
            raise LocalQueueError("promotion_evaluation_not_persisted_exactly_once")
        payload = evaluation_events[0]["payload"]
        if payload.get("evidenceFingerprint") != evaluation.evidence_fingerprint:
            raise LocalQueueError("promotion_evidence_fingerprint_mismatch")
        self._verify_evaluation_evidence(payload)
        prior_approvals = [
            event
            for event in self.promotions.read().events
            if event.get("eventType") == "promotion_approved"
            and event.get("payload", {}).get("evaluationId") == evaluation.evaluation_id
        ]
        if prior_approvals:
            raise LocalQueueError("promotion_evaluation_already_approved")
        event = self.promotions.append(
            "promotion_approved",
            {
                "schema": PROMOTION_SCHEMA,
                "evaluationId": evaluation.evaluation_id,
                "candidateModelFingerprint": evaluation.candidate_model_fingerprint,
                "baselineModelFingerprint": evaluation.baseline_model_fingerprint,
                "evidenceFingerprint": evaluation.evidence_fingerprint,
                "approvedBy": approved_by,
                "reason": reason,
                "scope": list(scope),
                "expiresAt": expires_at,
                "automatic": False,
            },
        )
        return event

    def revoke_promotion(
        self, evaluation_id: str, *, revoked_by: str, reason: str
    ) -> dict[str, Any]:
        """Append an explicit revocation; approvals are never edited in place."""

        if not revoked_by.strip() or not reason.strip():
            raise ValueError("revoked_by and reason must be non-empty")
        with file_lock(self._mutation_path):
            approvals = [
                event
                for event in self.promotions.read().events
                if event.get("eventType") == "promotion_approved"
                and event.get("payload", {}).get("evaluationId") == evaluation_id
            ]
            if len(approvals) != 1:
                raise LocalQueueError("promotion_approval_not_found_exactly_once")
            prior = [
                event
                for event in self.promotions.read().events
                if event.get("eventType") == "promotion_revoked"
                and event.get("payload", {}).get("evaluationId") == evaluation_id
            ]
            if prior:
                raise LocalQueueError("promotion_already_revoked")
            return self.promotions.append(
                "promotion_revoked",
                {
                    "schema": PROMOTION_SCHEMA,
                    "evaluationId": evaluation_id,
                    "approvalEventHash": approvals[0]["eventHash"],
                    "revokedBy": revoked_by,
                    "reason": reason,
                    "automatic": False,
                },
            )

    def active_promotion(
        self,
        *,
        candidate_model_fingerprint: str,
        task_kind: str,
        candidate_benchmark_ids: tuple[str, ...],
        hardware_fingerprint: str,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        """Return exactly one active, still-verifiable approval for routing."""

        if (
            not candidate_benchmark_ids
            or len(candidate_benchmark_ids) != len(set(candidate_benchmark_ids))
            or any(not item.strip() for item in candidate_benchmark_ids)
        ):
            raise ValueError("promotion_candidate_benchmark_ids_invalid")
        if not hardware_fingerprint.strip():
            raise ValueError("promotion_hardware_fingerprint_missing")
        now = (
            datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            if observed_at is not None
            else datetime.now(UTC)
        )
        if now.tzinfo is None:
            raise ValueError("promotion_observed_at_timezone_required")
        events = self.promotions.read().events
        revoked = {
            str(event.get("payload", {}).get("evaluationId"))
            for event in events
            if event.get("eventType") == "promotion_revoked"
        }
        candidates: list[dict[str, Any]] = []
        for event in events:
            if event.get("eventType") != "promotion_approved":
                continue
            payload = event.get("payload", {})
            evaluation_id = str(payload.get("evaluationId") or "")
            if evaluation_id in revoked:
                continue
            if payload.get("candidateModelFingerprint") != candidate_model_fingerprint:
                continue
            scope = payload.get("scope", [])
            if scope and task_kind not in scope:
                continue
            expires_at = payload.get("expiresAt")
            if expires_at is not None:
                expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if expiry.tzinfo is None or expiry <= now:
                    continue
            evaluation = self.evaluation(evaluation_id)
            if (
                evaluation.task_kind != task_kind
                or not evaluation.eligible
                or tuple(sorted(evaluation.candidate_benchmark_ids))
                != tuple(sorted(candidate_benchmark_ids))
                or evaluation.hardware_fingerprint != hardware_fingerprint
            ):
                continue
            self._verify_evaluation_evidence(
                next(
                    persisted["payload"]
                    for persisted in events
                    if persisted.get("eventType") == "promotion_evaluated"
                    and persisted.get("payload", {}).get("evaluationId")
                    == evaluation_id
                )
            )
            candidates.append(
                {
                    "evaluationId": evaluation_id,
                    "approvalEventId": event["eventId"],
                    "approvalEventHash": event["eventHash"],
                    "approvedAt": event["occurredAt"],
                    "approvedBy": payload.get("approvedBy"),
                    "scope": list(scope),
                    "expiresAt": expires_at,
                    "candidateModelFingerprint": candidate_model_fingerprint,
                    "taskKind": task_kind,
                    "candidateBenchmarkIds": list(candidate_benchmark_ids),
                    "hardwareFingerprint": hardware_fingerprint,
                    "evidenceFingerprint": evaluation.evidence_fingerprint,
                }
            )
        if len(candidates) != 1:
            raise LocalQueueError(
                "active_promotion_not_found_exactly_once:"
                f"{candidate_model_fingerprint}:{task_kind}:{len(candidates)}"
            )
        return candidates[0]

    @staticmethod
    def _resolve_receipts(
        receipts: dict[str, BenchmarkReceipt],
        identifiers: tuple[str, ...],
        label: str,
        blockers: list[str],
    ) -> list[BenchmarkReceipt]:
        if len(set(identifiers)) != len(identifiers):
            blockers.append(f"duplicate_{label}_benchmark_id")
        found: list[BenchmarkReceipt] = []
        for identifier in identifiers:
            receipt = receipts.get(identifier)
            if receipt is None:
                blockers.append(f"missing_{label}_benchmark:{identifier}")
            else:
                found.append(receipt)
        return found

    @staticmethod
    def _recipe_link(receipt: BenchmarkReceipt) -> tuple[str, str]:
        return (
            receipt.benchmark_recipe_id or "",
            receipt.benchmark_recipe_fingerprint or "",
        )

    @staticmethod
    def _registry_link(receipt: BenchmarkReceipt) -> tuple[str, str]:
        return (
            receipt.analyzer_registry_id or "",
            receipt.analyzer_registry_fingerprint or "",
        )

    @classmethod
    def _receipt_evidence_link(cls, receipt: BenchmarkReceipt) -> dict[str, Any]:
        return {
            "benchmarkId": receipt.benchmark_id,
            "benchmarkRecipeId": receipt.benchmark_recipe_id,
            "benchmarkRecipeFingerprint": receipt.benchmark_recipe_fingerprint,
            "analyzerRegistryId": receipt.analyzer_registry_id,
            "analyzerRegistryFingerprint": receipt.analyzer_registry_fingerprint,
        }

    @staticmethod
    def _median_ratio(
        candidate: list[BenchmarkReceipt],
        baseline: list[BenchmarkReceipt],
        attribute: str,
    ) -> float | None:
        if not candidate or not baseline:
            return None
        baseline_median = float(
            statistics.median(getattr(receipt, attribute) for receipt in baseline)
        )
        if baseline_median <= 0:
            return None
        candidate_median = float(
            statistics.median(getattr(receipt, attribute) for receipt in candidate)
        )
        return candidate_median / baseline_median

    @staticmethod
    def _start_event(queue: LocalGenerationQueue, job_id: str) -> dict[str, Any]:
        starts = [
            event
            for event in queue.journal.read().events
            if event.get("eventType") == "job_started"
            and event.get("payload", {}).get("jobId") == job_id
        ]
        if not starts:
            raise LocalQueueError("benchmark_missing_job_start_event")
        return starts[-1]

    @staticmethod
    def _measurement_from_terminal_payload(
        terminal_payload: dict[str, Any],
    ) -> LocalExecutionMeasurement:
        raw = terminal_payload.get("executionMeasurement")
        if not isinstance(raw, dict):
            raise LocalQueueError("benchmark_missing_execution_measurement")
        try:
            measurement = LocalExecutionMeasurement(
                wall_time_seconds=float(raw["wallTimeSeconds"]),
                peak_memory_bytes=int(raw["peakMemoryBytes"]),
                memory_measurement_method=str(raw["memoryMeasurementMethod"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LocalQueueError("benchmark_execution_measurement_invalid") from exc
        if (
            not math.isfinite(measurement.wall_time_seconds)
            or measurement.wall_time_seconds <= 0
            or measurement.peak_memory_bytes <= 0
            or not measurement.memory_measurement_method.strip()
        ):
            raise LocalQueueError("benchmark_execution_measurement_invalid")
        if measurement.memory_measurement_method != PROMOTION_MEMORY_MEASUREMENT_METHOD:
            raise LocalQueueError(
                "benchmark_peak_memory_measurement_not_promotion_eligible"
            )
        return measurement

    @staticmethod
    def _verify_artifact_event(
        queue: LocalGenerationQueue,
        job: LocalGenerationJob,
        *,
        terminal_event: Mapping[str, Any],
        output_path: Path,
        output_sha256: str,
        measurement: LocalExecutionMeasurement,
    ) -> None:
        if not job.owned_artifact_paths:
            raise LocalQueueError("benchmark_job_owned_artifact_paths_missing")
        events = queue.journal.read().events
        try:
            terminal_index = events.index(terminal_event)
        except ValueError as exc:
            raise JournalCorruptionError("benchmark_terminal_event_missing") from exc
        start_indices = [
            index
            for index, event in enumerate(events[:terminal_index])
            if event.get("eventType") == "job_started"
            and event.get("payload", {}).get("jobId") == job.job_id
        ]
        if not start_indices:
            raise JournalCorruptionError("benchmark_start_event_missing")
        verified_events = [
            event
            for event in events[start_indices[-1] + 1 : terminal_index]
            if event.get("eventType") == "job_artifacts_verified"
            and event.get("payload", {}).get("jobId") == job.job_id
        ]
        if len(verified_events) != 1:
            raise LocalQueueError(
                "benchmark_requires_exactly_one_artifact_verification"
            )
        payload = verified_events[0].get("payload", {})
        expected_measurement = {
            "wallTimeSeconds": measurement.wall_time_seconds,
            "peakMemoryBytes": measurement.peak_memory_bytes,
            "memoryMeasurementMethod": measurement.memory_measurement_method,
        }
        if (
            payload.get("jobFingerprint") != fingerprint(job.as_dict())
            or payload.get("outputPath") != str(output_path)
            or payload.get("outputSha256") != output_sha256
            or payload.get("executionMeasurement") != expected_measurement
            or not isinstance(payload.get("outputProbe"), dict)
        ):
            raise LocalQueueError("benchmark_artifact_verification_mismatch")

    def _verify_evaluation_evidence(self, payload: dict[str, Any]) -> None:
        if payload.get("eligible") is not True:
            raise LocalQueueError("promotion_not_evidence_eligible")
        evidence = {
            "candidateBenchmarkIds": payload.get("candidateBenchmarkIds"),
            "baselineBenchmarkIds": payload.get("baselineBenchmarkIds"),
            "candidateModelFingerprint": payload.get("candidateModelFingerprint"),
            "baselineModelFingerprint": payload.get("baselineModelFingerprint"),
            "taskKind": payload.get("taskKind"),
            "hardwareFingerprint": payload.get("hardwareFingerprint"),
            "benchmarkEvidenceLinks": payload.get("benchmarkEvidenceLinks"),
            "policy": payload.get("policy"),
        }
        if fingerprint(evidence) != payload.get("evidenceFingerprint"):
            raise LocalQueueError("promotion_evidence_fingerprint_mismatch")
        receipts = self.all_receipts()
        persisted_links = payload.get("benchmarkEvidenceLinks")
        if not isinstance(persisted_links, dict):
            raise LocalQueueError("promotion_benchmark_evidence_links_missing")
        for label in ("candidate", "baseline"):
            key = f"{label}BenchmarkIds"
            identifiers = payload.get(key)
            if not isinstance(identifiers, list) or not identifiers:
                raise LocalQueueError(f"promotion_{label}_evidence_missing")
            actual_links: list[dict[str, Any]] = []
            for identifier in identifiers:
                receipt = receipts.get(str(identifier))
                if receipt is None:
                    raise LocalQueueError(
                        f"promotion_{label}_benchmark_missing:{identifier}"
                    )
                recipe, registry = self._load_receipt_evidence(receipt)
                expected_versions = self._required_analyzers(
                    benchmark_recipe=recipe,
                    analyzer_registry=registry,
                )
                actual_links.append(self._receipt_evidence_link(receipt))
                if set(expected_versions).difference(
                    reference.check_id for reference in receipt.qc_references
                ):
                    raise LocalQueueError(
                        f"promotion_{label}_required_qc_missing:{identifier}"
                    )
                for reference in receipt.qc_references:
                    self._verify_qc_reference(
                        reference,
                        expected_subject_sha256=receipt.output_sha256,
                        expected_version=expected_versions.get(reference.check_id),
                    )
            if actual_links != persisted_links.get(label):
                raise LocalQueueError(
                    f"promotion_{label}_benchmark_evidence_links_changed"
                )

    def _verify_qc_reference(
        self,
        reference: QCReference,
        *,
        expected_subject_sha256: str,
        expected_version: str | None = None,
    ) -> None:
        if reference.subject_sha256 != expected_subject_sha256:
            raise LocalQueueError(f"benchmark_qc_subject_mismatch:{reference.check_id}")
        path = Path(reference.receipt_uri)
        if path.is_absolute():
            raise LocalQueueError(
                f"benchmark_qc_receipt_uri_not_store_relative:{reference.check_id}"
            )
        resolved = (self.root / path).resolve()
        if not resolved.is_relative_to(self.root):
            raise LocalQueueError(
                f"benchmark_qc_receipt_uri_escapes_store:{reference.check_id}"
            )
        if not resolved.is_file() or resolved.is_symlink():
            raise LocalQueueError(f"benchmark_qc_receipt_missing:{reference.check_id}")
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != reference.receipt_sha256:
            raise LocalQueueError(
                f"benchmark_qc_receipt_sha256_mismatch:{reference.check_id}"
            )
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise LocalQueueError(
                f"benchmark_qc_receipt_not_json:{reference.check_id}"
            ) from exc
        bound_subject = None
        if isinstance(payload, dict):
            if payload.get("schema") == "contentforge.trusted_media_analysis.v1":
                subject = payload.get("subject")
                bound_subject = (
                    subject.get("mediaSha256") if isinstance(subject, dict) else None
                )
            else:
                bound_subject = (
                    payload.get("subjectSha256")
                    or payload.get("mediaSha256")
                    or payload.get("outputSha256")
                )
        if bound_subject != expected_subject_sha256:
            raise LocalQueueError(
                f"benchmark_qc_receipt_subject_mismatch:{reference.check_id}"
            )
        receipt_payload = _receipt_payload_for_check(
            payload,
            check_id=reference.check_id,
            expected_subject_sha256=expected_subject_sha256,
        )
        receipt_passed = _qc_receipt_verdict(
            receipt_payload,
            check_id=reference.check_id,
            expected_version=expected_version,
        )
        _validate_policy_specific_qc_receipt(
            receipt_payload,
            check_id=reference.check_id,
            expected_subject_sha256=expected_subject_sha256,
        )
        if receipt_passed != reference.passed:
            raise LocalQueueError(
                f"benchmark_qc_receipt_passed_mismatch:{reference.check_id}"
            )


def default_local_model_benchmark_store(
    root: Path | None = None,
) -> LocalModelBenchmarkStore:
    selected = root or os.environ.get("CREATOR_OS_LOCAL_MODEL_BENCHMARK_ROOT")
    evidence_root = (
        Path(selected).expanduser().resolve()
        if selected
        else (Path.home() / ".creator-os/state/reel_factory/local_benchmarks").resolve()
    )
    return LocalModelBenchmarkStore(evidence_root)


def _qc_argument(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("QC must use CHECK_ID=/path/to/receipt.json")
    check_id, raw_path = value.split("=", 1)
    if not check_id.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("QC must use CHECK_ID=/path/to/receipt.json")
    return check_id.strip(), Path(raw_path)


def _benchmark_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record and evaluate measured local-video benchmark evidence."
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--queue-root", type=Path)
    parser.add_argument("--implementation-root", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")

    record = sub.add_parser("record")
    record.add_argument("--job-id", required=True)
    record.add_argument("--lineage", required=True, type=Path)
    record.add_argument("--qc", required=True, action="append", type=_qc_argument)
    record.add_argument("--benchmark-id")
    record.add_argument("--benchmark-recipe", required=True, type=Path)
    record.add_argument("--analyzer-registry", required=True, type=Path)

    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--candidate-benchmark-id", required=True, action="append")
    evaluate.add_argument("--baseline-benchmark-id", required=True, action="append")
    evaluate.add_argument("--minimum-candidate-samples", type=int, default=2)
    evaluate.add_argument("--minimum-baseline-samples", type=int, default=2)
    evaluate.add_argument("--maximum-wall-time-ratio", type=float, default=1.25)
    evaluate.add_argument("--maximum-peak-memory-ratio", type=float, default=1.25)

    approve = sub.add_parser("approve")
    approve.add_argument("--evaluation-id", required=True)
    approve.add_argument("--approved-by", required=True)
    approve.add_argument("--reason", required=True)
    return parser


def _verify_completed_lineage(
    lineage_path: Path, *, job_id: str, terminal_payload: dict[str, Any]
) -> dict[str, Any]:
    resolved = lineage_path.expanduser().resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise LocalQueueError("benchmark_lineage_missing_or_unsafe")
    try:
        lineage = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise LocalQueueError("benchmark_lineage_invalid") from exc
    if not isinstance(lineage, dict):
        raise LocalQueueError("benchmark_lineage_invalid")
    queue_payload = lineage.get("queue")
    if not isinstance(queue_payload, dict) or queue_payload.get("jobId") != job_id:
        raise LocalQueueError("benchmark_lineage_job_mismatch")
    if lineage.get("status") != "completed":
        raise LocalQueueError("benchmark_lineage_not_completed")
    output = Path(str(lineage.get("outputPath") or "")).expanduser().resolve()
    expected_lineage = output.with_suffix(output.suffix + ".local_video.json")
    if expected_lineage != resolved:
        raise LocalQueueError("benchmark_lineage_path_mismatch")
    terminal_output = Path(str(terminal_payload.get("outputPath") or "")).resolve()
    if output != terminal_output:
        raise LocalQueueError("benchmark_lineage_output_path_mismatch")
    output_sha256 = str(terminal_payload.get("outputSha256") or "")
    if lineage.get("outputSha256") != output_sha256:
        raise LocalQueueError("benchmark_lineage_output_sha256_mismatch")
    if not output.is_file() or sha256_file(output) != output_sha256:
        raise LocalQueueError("benchmark_output_missing_or_substituted")
    if lineage.get("executionMeasurement") != terminal_payload.get(
        "executionMeasurement"
    ):
        raise LocalQueueError("benchmark_lineage_measurement_mismatch")
    return lineage


def _read_evidence_record(path: Path, *, kind: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise LocalQueueError(f"benchmark_{kind}_missing_or_unsafe")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise LocalQueueError(f"benchmark_{kind}_invalid") from exc
    if not isinstance(payload, dict):
        raise LocalQueueError(f"benchmark_{kind}_invalid")
    return payload


def _evaluation_payload(evaluation: PromotionEvaluation) -> dict[str, Any]:
    return {
        "schema": PROMOTION_SCHEMA,
        "evaluationId": evaluation.evaluation_id,
        "eligible": evaluation.eligible,
        "blockingReasons": list(evaluation.blocking_reasons),
        "candidateBenchmarkIds": list(evaluation.candidate_benchmark_ids),
        "baselineBenchmarkIds": list(evaluation.baseline_benchmark_ids),
        "candidateModelFingerprint": evaluation.candidate_model_fingerprint,
        "baselineModelFingerprint": evaluation.baseline_model_fingerprint,
        "taskKind": evaluation.task_kind,
        "hardwareFingerprint": evaluation.hardware_fingerprint,
        "evidenceFingerprint": evaluation.evidence_fingerprint,
        "wallTimeRatio": evaluation.wall_time_ratio,
        "peakMemoryRatio": evaluation.peak_memory_ratio,
        "automatic": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = _benchmark_parser().parse_args(argv)
    root = args.root or os.environ.get("CREATOR_OS_LOCAL_MODEL_BENCHMARK_ROOT")
    store = LocalModelBenchmarkStore(
        (
            Path(root).expanduser().resolve()
            if root
            else Path.home() / ".creator-os/state/reel_factory/local_benchmarks"
        ),
        implementation_root=args.implementation_root,
    )
    try:
        if args.command == "status":
            payload: dict[str, Any] = {
                "schema": "reel_factory.local_model_benchmark_status.v1",
                "root": str(store.root),
                "benchmarks": [
                    receipt.as_dict()
                    for _, receipt in sorted(store.all_receipts().items())
                ],
                "promotionEvents": [
                    event["payload"] for event in store.promotions.read().events
                ],
            }
        elif args.command == "record":
            queue = default_local_generation_queue(args.queue_root)
            state = queue.states().get(args.job_id)
            if state is None or state.status != "succeeded":
                status = "missing" if state is None else state.status
                raise LocalQueueError(
                    f"benchmark_requires_succeeded_job:{args.job_id}:{status}"
                )
            terminal_payload = dict(state.last_event.get("payload", {}))
            _verify_completed_lineage(
                args.lineage, job_id=args.job_id, terminal_payload=terminal_payload
            )
            check_ids = [check_id for check_id, _ in args.qc]
            if len(set(check_ids)) != len(check_ids):
                raise LocalQueueError("benchmark_duplicate_qc_check_id")
            output_sha256 = str(terminal_payload["outputSha256"])
            benchmark_recipe = _read_evidence_record(
                args.benchmark_recipe, kind="recipe_evidence"
            )
            analyzer_registry = _read_evidence_record(
                args.analyzer_registry, kind="analyzer_registry_evidence"
            )
            references = tuple(
                store.ingest_qc_reference(
                    check_id=check_id,
                    receipt_path=path,
                    expected_subject_sha256=output_sha256,
                )
                for check_id, path in args.qc
            )
            payload = store.record_completed_job(
                queue,
                job_id=args.job_id,
                qc_references=references,
                benchmark_id=args.benchmark_id,
                benchmark_recipe=benchmark_recipe,
                analyzer_registry=analyzer_registry,
            ).as_dict()
        elif args.command == "evaluate":
            receipts = store.all_receipts()
            candidate_ids = tuple(args.candidate_benchmark_id)
            baseline_ids = tuple(args.baseline_benchmark_id)
            candidate = receipts.get(candidate_ids[0])
            baseline = receipts.get(baseline_ids[0])
            if candidate is None or baseline is None:
                raise LocalQueueError("promotion_seed_benchmark_missing")
            evaluation = store.evaluate_promotion(
                candidate_model_fingerprint=candidate.model_fingerprint,
                baseline_model_fingerprint=baseline.model_fingerprint,
                task_kind=candidate.task_kind,
                hardware_fingerprint=candidate.hardware_fingerprint,
                candidate_benchmark_ids=candidate_ids,
                baseline_benchmark_ids=baseline_ids,
                policy=PromotionPolicy(
                    minimum_candidate_samples=args.minimum_candidate_samples,
                    minimum_baseline_samples=args.minimum_baseline_samples,
                    maximum_wall_time_ratio=args.maximum_wall_time_ratio,
                    maximum_peak_memory_ratio=args.maximum_peak_memory_ratio,
                ),
            )
            payload = _evaluation_payload(evaluation)
        else:
            event = store.approve_persisted_promotion(
                args.evaluation_id,
                approved_by=args.approved_by,
                reason=args.reason,
            )
            payload = dict(event["payload"])
    except (LocalQueueError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
