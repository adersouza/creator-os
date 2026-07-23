from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeGuard

from creator_os_core.evidence_attestation import (
    EvidenceAttestationError,
    load_evidence_secret,
    payload_fingerprint,
    verify_evidence_attestation,
)

from pipeline_contracts import validate_motion_specific_qc_receipt_v2

from .canonical_analyzer_registry import (
    CanonicalAnalyzerRegistryError,
    validate_canonical_analyzer_registry,
)
from .persistence import json_load

MOTION_QC_POLICY_ID = "contentforge.motion_specific_qc"
MOTION_QC_POLICY_VERSION = "2.0.0"
MOTION_QC_CORE_REQUIREMENTS = (
    "motion",
    "temporal",
    "freeze",
    "anatomy",
    "identity",
)
MOTION_QC_BLOCKING_CODES = {
    "motion_specific_qc_required",
    "audio_video_alignment_qc_required",
    "lip_sync_qc_required",
}
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_TRUSTED_ANALYZER_IDS = {
    ("contentforge.media_integrity", "1.0.0"),
    ("contentforge.temporal_motion", "1.0.0"),
    ("contentforge.audio_integrity", "1.0.0"),
    ("contentforge.overlay_delivery", "1.0.0"),
    ("contentforge.local_lip_sync", "1.0.0"),
}
_DECISIVE_ANALYZER_IDS = {
    (MOTION_QC_POLICY_ID, MOTION_QC_POLICY_VERSION),
    ("reel_factory.structured_human_media_review", "1.0.0"),
}
_MOTION_QC_THRESHOLDS = {
    "minMotionScore": 0.03,
    "subtleMotionMax": 0.18,
    "moderateMotionMax": 0.5,
    "maxTemporalDiscontinuityScore": 0.25,
    "maxFrozenFrameRatio": 0.2,
    "maxLoopSeamScore": 0.25,
    "maxFaceAnomalyScore": 0.25,
    "maxHandAnomalyScore": 0.3,
    "maxBodyAnomalyScore": 0.25,
    "minIdentitySimilarityScore": 0.75,
    "minLipSyncConfidence": 0.65,
    "maxLipSyncOffsetMs": 120,
    "minAudioAlignmentConfidence": 0.65,
    "maxAudioAlignmentOffsetMs": 120,
}
_ANALYSIS_ATTESTATION_ISSUER = "contentforge.trusted_media_analysis"
_REVIEW_ATTESTATION_ISSUER = "reel_factory.structured_human_media_review"
_RECEIPT_ATTESTATION_ISSUER = "contentforge.trusted_motion_qc"


def _fingerprint(value: Any) -> str:
    if not isinstance(value, dict):
        raise TypeError("motion QC fingerprints require a JSON object")
    return payload_fingerprint(value)


def _without_fingerprint(value: dict[str, Any], field: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != field}


def _without_fields(value: dict[str, Any], *fields: str) -> dict[str, Any]:
    omitted = set(fields)
    return {key: item for key, item in value.items() if key not in omitted}


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _finite(value: Any) -> TypeGuard[int | float]:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and float("-inf") < float(value) < float("inf")
    )


def _utc_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _motion_amount(score: float) -> str:
    if score < _MOTION_QC_THRESHOLDS["minMotionScore"]:
        return "none"
    if score <= _MOTION_QC_THRESHOLDS["subtleMotionMax"]:
        return "subtle"
    if score <= _MOTION_QC_THRESHOLDS["moderateMotionMax"]:
        return "moderate"
    return "high"


def _trusted_motion_semantic_failures(
    receipt: dict[str, Any],
    *,
    analysis: dict[str, Any],
    registry: dict[str, Any],
    review: dict[str, Any],
    registrations: dict[tuple[str, str], dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    if not _DECISIVE_ANALYZER_IDS.issubset(registrations):
        failures.append("motion_specific_qc_decisive_analyzer_registration_missing")
    decisions = review.get("decisions")
    decisions = decisions if isinstance(decisions, dict) else {}
    if decisions != {
        "creatorIdentityPreserved": True,
        "anatomyAcceptable": True,
        "operatorUseful": True,
        "approvedForBenchmark": True,
    }:
        failures.append("motion_specific_qc_human_decision_not_approved")
    if review.get("rubricVersion") != "1.0.0":
        failures.append("motion_specific_qc_human_rubric_unsupported")
    exact_reference = [
        {
            "recordId": analysis.get("analysisId"),
            "fingerprint": analysis.get("analysisFingerprint"),
        }
    ]
    provenance = review.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    if provenance.get("sourceReferences") != exact_reference:
        failures.append("motion_specific_qc_human_source_reference_mismatch")
    registry_provenance = registry.get("provenance")
    registry_provenance = (
        registry_provenance if isinstance(registry_provenance, dict) else {}
    )
    registry_at = _utc_timestamp(registry_provenance.get("producedAt"))
    analysis_at = _utc_timestamp(analysis.get("producedAt"))
    review_at = _utc_timestamp(review.get("reviewedAt"))
    now = datetime.now(UTC)
    if (
        registry_at is None
        or analysis_at is None
        or review_at is None
        or not registry_at <= analysis_at <= review_at <= now
    ):
        failures.append("motion_specific_qc_evidence_time_order_invalid")
    if receipt.get("thresholds") != _MOTION_QC_THRESHOLDS:
        failures.append("motion_specific_qc_thresholds_mismatch")
    measurements = receipt.get("measurements")
    if not isinstance(measurements, dict) or not measurements:
        return [*failures, "motion_specific_qc_measurements_missing"]
    raw_by_id = {
        str(item.get("analyzerId") or ""): item
        for item in analysis.get("rawObservations") or []
        if isinstance(item, dict)
    }
    temporal_observation = raw_by_id.get("contentforge.temporal_motion") or {}
    temporal_values = temporal_observation.get("observations")
    temporal_values = temporal_values if isinstance(temporal_values, dict) else {}
    temporal_sampling = temporal_values.get("sampling")
    temporal_sampling = temporal_sampling if isinstance(temporal_sampling, dict) else {}
    analysis_sampling = analysis.get("humanReviewSampling")
    expected_analysis_sampling = {
        "sampleFps": temporal_sampling.get("framesPerSecond"),
        "width": temporal_sampling.get("width"),
        "height": temporal_sampling.get("height"),
        "sampledFrames": temporal_sampling.get("sampledFrames"),
        "totalFrames": temporal_sampling.get("totalFrames"),
        "durationSeconds": temporal_sampling.get("durationSeconds"),
        "durationCoverageRatio": temporal_sampling.get("durationCoverageRatio"),
        "frameSetFingerprint": temporal_sampling.get("frameSetFingerprint"),
        "briefFrameOutlierCount": temporal_sampling.get("briefFrameOutlierCount"),
    }
    sampling_evidence = review.get("samplingEvidence")
    expected_sampling_evidence = {
        "analysisId": analysis.get("analysisId"),
        "analysisFingerprint": analysis.get("analysisFingerprint"),
        **expected_analysis_sampling,
        "briefFrameOutliersReviewed": True,
    }
    if (
        analysis_sampling != expected_analysis_sampling
        or sampling_evidence != expected_sampling_evidence
    ):
        failures.append("motion_specific_qc_human_sampling_evidence_mismatch")
    ratings = review.get("ratings")
    ratings = ratings if isinstance(ratings, dict) else {}

    motion = measurements.get("motion")
    temporal = measurements.get("temporal")
    freeze = measurements.get("freeze")
    loop = measurements.get("loop")
    anatomy = measurements.get("anatomy")
    identity = measurements.get("identity")
    if not all(
        isinstance(value, dict)
        for value in (motion, temporal, freeze, loop, anatomy, identity)
    ):
        return [*failures, "motion_specific_qc_measurement_shape_invalid"]
    assert isinstance(motion, dict)
    assert isinstance(temporal, dict)
    assert isinstance(freeze, dict)
    assert isinstance(loop, dict)
    assert isinstance(anatomy, dict)
    assert isinstance(identity, dict)
    motion_score = motion.get("score")
    discontinuity = temporal.get("discontinuityScore")
    discontinuity_candidate_count = temporal.get("discontinuityCandidateCount")
    discontinuity_comparison_count = temporal.get("discontinuityComparisonCount")
    discontinuity_rate = temporal.get("discontinuityRate")
    outlier_threshold = temporal.get("outlierThreshold")
    frozen_ratio = freeze.get("frozenFrameRatio")
    loop_seam = loop.get("seamScore")
    if (
        not _finite(motion_score)
        or not 0 <= float(motion_score) <= 1
        or float(motion_score) < _MOTION_QC_THRESHOLDS["minMotionScore"]
        or motion.get("amount") != _motion_amount(float(motion_score))
        or motion_score != temporal_values.get("meanNormalizedFrameDelta")
    ):
        failures.append("motion_specific_qc_motion_measurement_invalid")
    temporal_counts_valid = (
        isinstance(discontinuity_candidate_count, int)
        and not isinstance(discontinuity_candidate_count, bool)
        and discontinuity_candidate_count >= 0
        and isinstance(discontinuity_comparison_count, int)
        and not isinstance(discontinuity_comparison_count, bool)
        and discontinuity_comparison_count > 0
        and discontinuity_candidate_count <= discontinuity_comparison_count
    )
    exact_rate: float | None = None
    if (
        isinstance(discontinuity_candidate_count, int)
        and not isinstance(discontinuity_candidate_count, bool)
        and isinstance(discontinuity_comparison_count, int)
        and not isinstance(discontinuity_comparison_count, bool)
        and discontinuity_comparison_count > 0
    ):
        exact_rate = discontinuity_candidate_count / discontinuity_comparison_count
    if (
        not _finite(discontinuity)
        or not 0
        <= float(discontinuity)
        <= _MOTION_QC_THRESHOLDS["maxTemporalDiscontinuityScore"]
        or not temporal_counts_valid
        or not _finite(discontinuity_rate)
        or not 0 <= float(discontinuity_rate) <= 1
        or not _finite(outlier_threshold)
        or not 0 <= float(outlier_threshold) <= 1
        or exact_rate is None
        or abs(float(discontinuity_rate) - exact_rate) > 1e-9
        or abs(float(discontinuity) - float(discontinuity_rate)) > 1e-9
        or discontinuity_candidate_count
        != temporal_values.get("discontinuityCandidateCount")
        or discontinuity_comparison_count
        != temporal_values.get("discontinuityComparisonCount")
        or discontinuity_rate != temporal_values.get("discontinuityRate")
        or outlier_threshold != temporal_values.get("discontinuityThreshold")
    ):
        failures.append("motion_specific_qc_temporal_measurement_invalid")
    if (
        not _finite(frozen_ratio)
        or not 0 <= float(frozen_ratio) <= _MOTION_QC_THRESHOLDS["maxFrozenFrameRatio"]
        or frozen_ratio != temporal_values.get("frozenFrameRatio")
    ):
        failures.append("motion_specific_qc_freeze_measurement_invalid")
    if (
        not _finite(loop_seam)
        or not 0 <= float(loop_seam) <= _MOTION_QC_THRESHOLDS["maxLoopSeamScore"]
        or loop_seam != temporal_values.get("loopSeamScore")
        or loop.get("loopable") is not ratings.get("loopAcceptable")
    ):
        failures.append("motion_specific_qc_loop_measurement_invalid")
    anatomy_fields = {
        "face": ("faceArtifactScore", "maxFaceAnomalyScore"),
        "body": ("bodyArtifactScore", "maxBodyAnomalyScore"),
    }
    for name, (rating_name, threshold_name) in anatomy_fields.items():
        part = anatomy.get(name)
        if (
            not isinstance(part, dict)
            or part.get("applicable") is not True
            or not _finite(part.get("anomalyScore"))
            or part.get("anomalyScore") != ratings.get(rating_name)
            or float(part["anomalyScore"]) > _MOTION_QC_THRESHOLDS[threshold_name]
        ):
            failures.append(f"motion_specific_qc_anatomy_{name}_measurement_invalid")
    hands = anatomy.get("hands")
    if ratings.get("handsVisible") is False:
        if (
            not isinstance(hands, dict)
            or hands.get("applicable") is not False
            or hands.get("anomalyScore") is not None
            or not str(hands.get("notApplicableReason") or "").strip()
        ):
            failures.append("motion_specific_qc_anatomy_hands_measurement_invalid")
    elif (
        not isinstance(hands, dict)
        or hands.get("applicable") is not True
        or not _finite(hands.get("anomalyScore"))
        or hands.get("anomalyScore") != ratings.get("handArtifactScore")
        or float(hands["anomalyScore"]) > _MOTION_QC_THRESHOLDS["maxHandAnomalyScore"]
    ):
        failures.append("motion_specific_qc_anatomy_hands_measurement_invalid")
    similarity = identity.get("similarityScore")
    if (
        not _finite(similarity)
        or similarity != ratings.get("creatorIdentitySimilarity")
        or float(similarity) < _MOTION_QC_THRESHOLDS["minIdentitySimilarityScore"]
        or identity.get("matched") is not decisions.get("creatorIdentityPreserved")
        or identity.get("matched") is not True
    ):
        failures.append("motion_specific_qc_identity_measurement_invalid")

    requirements = receipt.get("requirements")
    requirements = requirements if isinstance(requirements, dict) else {}
    for name, confidence_key, offset_key in (
        ("lipSync", "minLipSyncConfidence", "maxLipSyncOffsetMs"),
        (
            "audioAlignment",
            "minAudioAlignmentConfidence",
            "maxAudioAlignmentOffsetMs",
        ),
    ):
        if requirements.get(name) is not True:
            continue
        value = measurements.get(name)
        if (
            not isinstance(value, dict)
            or not _finite(value.get("confidence"))
            or float(value["confidence"]) < _MOTION_QC_THRESHOLDS[confidence_key]
            or not _finite(value.get("offsetMs"))
            or abs(float(value["offsetMs"])) > _MOTION_QC_THRESHOLDS[offset_key]
            or value.get("aligned") is not True
        ):
            failures.append(f"motion_specific_qc_{name}_measurement_invalid")
    if requirements.get("lipSync") is True:
        lip_sync = measurements.get("lipSync")
        lip_observation = raw_by_id.get("contentforge.local_lip_sync") or {}
        lip_values = lip_observation.get("observations")
        lip_values = lip_values if isinstance(lip_values, dict) else {}
        if (
            not isinstance(lip_sync, dict)
            or not _finite(lip_sync.get("correlation"))
            or not -1 <= float(lip_sync["correlation"]) <= 1
            or not isinstance(lip_sync.get("sampleCount"), int)
            or isinstance(lip_sync.get("sampleCount"), bool)
            or lip_sync["sampleCount"] < 7
            or not _finite(lip_sync.get("faceTrackCoverage"))
            or not 0 <= float(lip_sync["faceTrackCoverage"]) <= 1
            or not _finite(lip_sync.get("speechActivityRatio"))
            or not 0 <= float(lip_sync["speechActivityRatio"]) <= 1
            or any(
                lip_sync.get(field) != lip_values.get(field)
                for field in (
                    "confidence",
                    "offsetMs",
                    "aligned",
                    "correlation",
                    "sampleCount",
                    "faceTrackCoverage",
                    "speechActivityRatio",
                )
            )
            or abs(
                float(lip_sync["confidence"])
                - max(0.0, min(1.0, (float(lip_sync["correlation"]) + 1.0) / 2.0))
            )
            > 1e-9
        ):
            failures.append("motion_specific_qc_lipSync_evidence_mismatch")
    if requirements.get("audioAlignment") is True:
        audio_alignment = measurements.get("audioAlignment")
        audio_observation = raw_by_id.get("contentforge.audio_integrity") or {}
        audio_values = audio_observation.get("observations")
        audio_values = audio_values if isinstance(audio_values, dict) else {}
        start_offset = audio_values.get("avStreamStartOffsetMs")
        duration_delta = audio_values.get("avDurationDeltaMs")
        exact_confidence: float | None = None
        exact_aligned: bool | None = None
        if _finite(start_offset) and _finite(duration_delta):
            exact_confidence = max(
                0.0,
                1.0
                - min(
                    1.0,
                    max(abs(float(start_offset)), abs(float(duration_delta))) / 1000.0,
                ),
            )
            exact_aligned = (
                abs(float(start_offset))
                <= _MOTION_QC_THRESHOLDS["maxAudioAlignmentOffsetMs"]
            )
        if (
            not isinstance(audio_alignment, dict)
            or exact_confidence is None
            or exact_aligned is None
            or audio_alignment.get("offsetMs") != start_offset
            or audio_alignment.get("confidence") != exact_confidence
            or audio_alignment.get("aligned") is not exact_aligned
        ):
            failures.append("motion_specific_qc_audioAlignment_evidence_mismatch")
    evidence_sources = receipt.get("evidenceSources")
    evidence_sources = evidence_sources if isinstance(evidence_sources, dict) else {}
    for name in ("motion", "temporal", "freeze", "loop"):
        source = evidence_sources.get(name)
        if not isinstance(source, dict) or (
            source.get("analyzer"),
            source.get("analyzerVersion"),
        ) != ("contentforge.temporal_motion", "1.0.0"):
            failures.append(f"motion_specific_qc_decisive_source_mismatch:{name}")
    for name in ("identity", "anatomy"):
        source = evidence_sources.get(name)
        if not isinstance(source, dict) or (
            source.get("analyzer"),
            source.get("analyzerVersion"),
        ) != ("reel_factory.structured_human_media_review", "1.0.0"):
            failures.append(f"motion_specific_qc_decisive_source_mismatch:{name}")
    expected_optional_sources = {
        "lipSync": ("contentforge.local_lip_sync", "1.0.0"),
        "audioAlignment": ("contentforge.audio_integrity", "1.0.0"),
    }
    for name, identity in expected_optional_sources.items():
        if requirements.get(name) is not True:
            continue
        source = evidence_sources.get(name)
        if (
            not isinstance(source, dict)
            or (
                source.get("analyzer"),
                source.get("analyzerVersion"),
            )
            != identity
        ):
            failures.append(f"motion_specific_qc_decisive_source_mismatch:{name}")
    return failures


class MotionQcPublishabilityMixin:
    """Fail-closed generated-motion evidence boundary for Campaign Factory."""

    conn: sqlite3.Connection
    _utc_now: Callable[[], str]
    _sanitize_for_storage: Callable[[Any], Any]
    _verification_id: Callable[..., str]
    rendered_asset: Callable[[str], dict[str, Any]]
    record_event: Callable[..., dict[str, Any]]

    @staticmethod
    def _trusted_motion_qc_failures(
        asset: dict[str, Any],
        receipt: dict[str, Any],
    ) -> list[str]:
        failures: list[str] = []
        try:
            validate_motion_specific_qc_receipt_v2(receipt)
        except Exception:
            return ["motion_specific_qc_contract_invalid"]
        if receipt.get("receiptFingerprint") != _fingerprint(
            _without_fields(receipt, "receiptFingerprint", "producerAttestation")
        ):
            failures.append("motion_specific_qc_receipt_fingerprint_mismatch")
        trusted = receipt.get("trustedEvidence")
        trusted = trusted if isinstance(trusted, dict) else {}
        analysis = trusted.get("analysis")
        analysis = analysis if isinstance(analysis, dict) else {}
        registry = trusted.get("analyzerRegistry")
        registry = registry if isinstance(registry, dict) else {}
        review = trusted.get("humanReview")
        review = review if isinstance(review, dict) else {}
        try:
            validate_canonical_analyzer_registry(registry)
        except CanonicalAnalyzerRegistryError:
            failures.append("motion_specific_qc_analyzer_registry_not_canonical")
        bindings = receipt.get("bindings")
        bindings = bindings if isinstance(bindings, dict) else {}
        analysis_fingerprint = _fingerprint(
            _without_fields(analysis, "analysisFingerprint", "producerAttestation")
        )
        review_fingerprint = _fingerprint(
            _without_fields(review, "reviewFingerprint", "operatorAttestation")
        )
        registry_fingerprint = _fingerprint(registry)
        if analysis.get("analysisFingerprint") != analysis_fingerprint:
            failures.append("motion_specific_qc_analysis_fingerprint_mismatch")
        if review.get("reviewFingerprint") != review_fingerprint:
            failures.append("motion_specific_qc_human_review_fingerprint_mismatch")
        try:
            secret = load_evidence_secret()
            receipt_attested = dict(receipt)
            receipt_attestation = receipt_attested.pop("producerAttestation")
            analysis_attested = dict(analysis)
            analysis_attestation = analysis_attested.pop("producerAttestation")
            review_attested = dict(review)
            review_attestation = review_attested.pop("operatorAttestation")
            verify_evidence_attestation(
                analysis_attestation,
                analysis_attested,
                secret=secret,
                expected_issuer=_ANALYSIS_ATTESTATION_ISSUER,
            )
            verify_evidence_attestation(
                review_attestation,
                review_attested,
                secret=secret,
                expected_issuer=_REVIEW_ATTESTATION_ISSUER,
            )
            verify_evidence_attestation(
                receipt_attestation,
                receipt_attested,
                secret=secret,
                expected_issuer=_RECEIPT_ATTESTATION_ISSUER,
            )
            if analysis_attestation.get("issuedAt") != analysis.get("producedAt"):
                failures.append("motion_specific_qc_analysis_attestation_time_mismatch")
            if review_attestation.get("issuedAt") != review.get("reviewedAt"):
                failures.append("motion_specific_qc_review_attestation_time_mismatch")
            if receipt_attestation.get("issuedAt") != review.get("reviewedAt"):
                failures.append("motion_specific_qc_receipt_attestation_time_mismatch")
        except (EvidenceAttestationError, KeyError, TypeError):
            failures.append("motion_specific_qc_attestation_invalid")
        analysis_registry = analysis.get("analyzerRegistry")
        analysis_registry = (
            analysis_registry if isinstance(analysis_registry, dict) else {}
        )
        exact_bindings = {
            "analysisId": analysis.get("analysisId"),
            "analysisFingerprint": analysis_fingerprint,
            "analyzerRegistryId": registry.get("registryId"),
            "analyzerRegistryFingerprint": registry_fingerprint,
            "humanReviewId": review.get("reviewId"),
            "humanReviewFingerprint": review_fingerprint,
        }
        if bindings != exact_bindings:
            failures.append("motion_specific_qc_evidence_bindings_mismatch")
        if (
            analysis_registry.get("registryId") != registry.get("registryId")
            or analysis_registry.get("registryFingerprint") != registry_fingerprint
        ):
            failures.append("motion_specific_qc_registry_snapshot_mismatch")
        content_hash = str(asset.get("content_hash") or "")
        source_sha = (
            analysis.get("subject", {}).get("sourceSha256")
            if isinstance(analysis.get("subject"), dict)
            else None
        )
        metadata = json_load(asset.get("metadata_json"), {})
        metadata = metadata if isinstance(metadata, dict) else {}
        source_binding = metadata.get("generationInput") or metadata.get(
            "staticFallbackSource"
        )
        source_binding = source_binding if isinstance(source_binding, dict) else {}
        if (
            analysis.get("subject", {}).get("mediaSha256") != content_hash
            or receipt.get("subjectSha256") != content_hash
            or review.get("subjectSha256") != content_hash
        ):
            failures.append("motion_specific_qc_trusted_subject_mismatch")
        if (
            not isinstance(source_sha, str)
            or receipt.get("sourceSha256") != source_sha
            or review.get("sourceSha256") != source_sha
        ):
            failures.append("motion_specific_qc_trusted_source_mismatch")
        if source_binding.get("sha256") != source_sha:
            failures.append("motion_specific_qc_asset_source_mismatch")
        registrations: dict[tuple[str, str], dict[str, Any]] = {}
        for registration in registry.get("analyzers") or []:
            if not isinstance(registration, dict):
                failures.append("motion_specific_qc_registry_entry_invalid")
                continue
            identity = (
                str(registration.get("analyzerId") or ""),
                str(registration.get("analyzerVersion") or ""),
            )
            if identity in registrations:
                failures.append("motion_specific_qc_registry_duplicate_identity")
            registrations[identity] = registration
            implementation_ref = str(registration.get("implementationRef") or "")
            implementation_path = (_REPOSITORY_ROOT / implementation_ref).resolve()
            try:
                implementation_path.relative_to(_REPOSITORY_ROOT)
                implementation_sha, _ = _sha256_file(implementation_path)
            except (OSError, ValueError):
                failures.append("motion_specific_qc_registry_implementation_missing")
            else:
                if implementation_sha != registration.get("implementationFingerprint"):
                    failures.append("motion_specific_qc_registry_implementation_drift")
        observations = analysis.get("rawObservations") or []
        if not isinstance(observations, list) or not observations:
            failures.append("motion_specific_qc_analysis_observations_missing")
        else:
            seen: set[tuple[str, str]] = set()
            for observation in observations:
                if not isinstance(observation, dict):
                    failures.append("motion_specific_qc_analysis_observation_invalid")
                    continue
                identity = (
                    str(observation.get("analyzerId") or ""),
                    str(observation.get("analyzerVersion") or ""),
                )
                registration = registrations.get(identity)
                if identity in seen or registration is None:
                    failures.append(
                        "motion_specific_qc_analysis_registry_identity_mismatch"
                    )
                seen.add(identity)
                if registration and any(
                    observation.get(field) != registration.get(field)
                    for field in (
                        "evidenceKinds",
                        "implementationRef",
                        "implementationFingerprint",
                    )
                ):
                    failures.append(
                        "motion_specific_qc_analysis_implementation_mismatch"
                    )
                if (
                    observation.get("analyzerRegistryId") != registry.get("registryId")
                    or observation.get("analyzerRegistryFingerprint")
                    != registry_fingerprint
                ):
                    failures.append(
                        "motion_specific_qc_analysis_registry_binding_mismatch"
                    )
            if seen != _TRUSTED_ANALYZER_IDS:
                failures.append("motion_specific_qc_analysis_analyzer_set_mismatch")
            expected_analysis_id = (
                "analysis_"
                + _fingerprint(
                    {
                        "mediaSha256": content_hash,
                        "sourceSha256": source_sha,
                        "registryFingerprint": registry_fingerprint,
                        "analyzers": observations,
                    }
                )[:24]
            )
            if analysis.get("analysisId") != expected_analysis_id:
                failures.append("motion_specific_qc_analysis_id_mismatch")
            verdicts = analysis.get("analyzerVerdicts") or []
            verdict_by_id = {
                (
                    str(item.get("policy", {}).get("id") or ""),
                    str(item.get("policy", {}).get("version") or ""),
                ): item
                for item in verdicts
                if isinstance(item, dict) and isinstance(item.get("policy"), dict)
            }
            for observation in observations:
                if not isinstance(observation, dict):
                    continue
                identity = (
                    str(observation.get("analyzerId") or ""),
                    str(observation.get("analyzerVersion") or ""),
                )
                verdict = verdict_by_id.get(identity)
                expected_pass = observation.get("status") in {
                    "measured",
                    "not_applicable",
                }
                if (
                    not isinstance(verdict, dict)
                    or verdict.get("analysisId") != analysis.get("analysisId")
                    or verdict.get("observationFingerprint")
                    != _fingerprint(observation)
                    or verdict.get("passed") is not expected_pass
                    or verdict.get("verdict")
                    != ("pass" if expected_pass else "blocked")
                ):
                    failures.append("motion_specific_qc_analysis_verdict_mismatch")
            if len(verdict_by_id) != len(observations):
                failures.append("motion_specific_qc_analysis_verdict_set_mismatch")
        evidence_sources = receipt.get("evidenceSources")
        evidence_sources = (
            evidence_sources if isinstance(evidence_sources, dict) else {}
        )
        for name in MOTION_QC_CORE_REQUIREMENTS:
            source = evidence_sources.get(name)
            source = source if isinstance(source, dict) else {}
            if name in {"identity", "anatomy"}:
                if source.get("reviewFingerprint") != review_fingerprint:
                    failures.append(f"motion_specific_qc_review_binding_missing:{name}")
            elif source.get("analysisFingerprint") != analysis_fingerprint:
                failures.append(f"motion_specific_qc_analysis_binding_missing:{name}")
        failures.extend(
            _trusted_motion_semantic_failures(
                receipt,
                analysis=analysis,
                registry=registry,
                review=review,
                registrations=registrations,
            )
        )
        return sorted(set(failures))

    def motion_qc_requirements(self, asset: dict[str, Any]) -> dict[str, bool]:
        metadata = json_load(asset.get("metadata_json"), {})
        metadata = metadata if isinstance(metadata, dict) else {}
        publishability = metadata.get("publishability")
        publishability = publishability if isinstance(publishability, dict) else {}
        blocking_issues = {
            str(value)
            for value in publishability.get("blockingIssues") or []
            if isinstance(value, str)
        }
        generated_motion = bool(
            metadata.get("schema") == "campaign_factory.motion_generation_asset.v1"
            or str(asset.get("frame_type") or "") == "generated_motion"
            or blocking_issues & MOTION_QC_BLOCKING_CODES
        )
        embedded_audio = bool(
            metadata.get("audioBurned") is True
            or str(metadata.get("embeddedAudioMode") or "") in {"source", "generated"}
            or "audio_video_alignment_qc_required" in blocking_issues
        )
        lip_sync = bool(
            str(metadata.get("modelId") or "") == "local_longcat_avatar15_q4_mlx"
            or "lip_sync_qc_required" in blocking_issues
        )
        return {
            "motion": generated_motion,
            "audioAlignment": generated_motion and embedded_audio,
            "lipSync": generated_motion and lip_sync,
        }

    def generated_motion_identity_failures(self, asset: dict[str, Any]) -> list[str]:
        metadata = json_load(asset.get("metadata_json"), {})
        metadata = metadata if isinstance(metadata, dict) else {}
        if metadata.get("schema") != "campaign_factory.motion_generation_asset.v1":
            return []
        publishability = metadata.get("publishability")
        publishability = publishability if isinstance(publishability, dict) else {}
        blocking_issues = {
            str(value)
            for value in publishability.get("blockingIssues") or []
            if isinstance(value, str)
        }
        text_only_unassigned = bool(
            metadata.get("identityRole") == "non_creator_broll"
            or metadata.get("sourceAssetRole") == "static_fallback_only"
            or "text_to_video_identity_assignment_forbidden" in blocking_issues
        )
        return (
            ["text_to_video_identity_assignment_forbidden"]
            if text_only_unassigned
            else []
        )

    def _motion_qc_receipt_validation(
        self,
        asset: dict[str, Any],
        receipt: dict[str, Any],
    ) -> tuple[list[str], dict[str, bool]]:
        requirements = self.motion_qc_requirements(asset)
        if not requirements["motion"]:
            return [], requirements
        failures: list[str] = []
        failures.extend(self._trusted_motion_qc_failures(asset, receipt))
        subject_sha256 = str(receipt.get("subjectSha256") or "")
        content_hash = str(asset.get("content_hash") or "")
        if not re.fullmatch(r"[a-f0-9]{64}", subject_sha256):
            failures.append("motion_specific_qc_subject_invalid")
        if subject_sha256 != content_hash:
            failures.append("motion_specific_qc_subject_mismatch")
        policy = receipt.get("policy")
        policy = policy if isinstance(policy, dict) else {}
        if (
            policy.get("id") != MOTION_QC_POLICY_ID
            or policy.get("version") != MOTION_QC_POLICY_VERSION
        ):
            failures.append("motion_specific_qc_policy_mismatch")
        receipt_requirements = receipt.get("requirements")
        receipt_requirements = (
            receipt_requirements if isinstance(receipt_requirements, dict) else {}
        )
        evidence_sources = receipt.get("evidenceSources")
        evidence_sources = (
            evidence_sources if isinstance(evidence_sources, dict) else {}
        )
        required_evidence = list(MOTION_QC_CORE_REQUIREMENTS)
        if requirements["audioAlignment"]:
            required_evidence.append("audioAlignment")
        if requirements["lipSync"]:
            required_evidence.append("lipSync")
        for name in required_evidence:
            if receipt_requirements.get(name) is not True:
                failures.append(f"motion_specific_qc_requirement_missing:{name}")
                continue
            source = evidence_sources.get(name)
            source = source if isinstance(source, dict) else {}
            if (
                source.get("available") is not True
                or not str(source.get("analyzer") or "").strip()
                or source.get("subjectSha256") != content_hash
            ):
                failures.append(f"motion_specific_qc_evidence_invalid:{name}")
        if (
            receipt.get("passed") is not True
            or receipt.get("verdict") != "pass"
            or receipt.get("evidenceOnly") is not True
            or receipt.get("modelCalls") != 0
            or receipt.get("providerCalls") != 0
            or receipt.get("reasons") != []
        ):
            failures.append("motion_specific_qc_not_passed")
        return sorted(set(failures)), requirements

    def register_motion_qc_receipt(
        self,
        rendered_asset_id: str,
        *,
        receipt_path: str | Path,
        created_by: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Register one immutable ContentForge motion-QC result."""

        asset = self.rendered_asset(rendered_asset_id)
        requirements = self.motion_qc_requirements(asset)
        if not requirements["motion"]:
            raise ValueError("motion QC receipts only apply to generated motion assets")
        path = Path(receipt_path).expanduser().resolve()
        try:
            raw_receipt = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"motion QC receipt is unreadable: {path}") from exc
        try:
            receipt = json.loads(raw_receipt)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("motion QC receipt must be a JSON object") from exc
        if not isinstance(receipt, dict):
            raise ValueError("motion QC receipt must be a JSON object")
        failures, requirements = self._motion_qc_receipt_validation(asset, receipt)
        if failures:
            raise ValueError("invalid motion QC receipt: " + ", ".join(failures))
        media_path = Path(
            str(asset.get("campaign_path") or asset.get("output_path") or "")
        )
        try:
            media_sha256, media_size_bytes = _sha256_file(media_path)
        except OSError as exc:
            raise ValueError(
                f"generated motion media is unreadable: {media_path}"
            ) from exc
        if media_sha256 != str(asset.get("content_hash") or ""):
            raise ValueError(
                "generated motion media no longer matches its content hash"
            )
        canonical_receipt = json.dumps(
            receipt,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        receipt_sha256 = hashlib.sha256(canonical_receipt.encode("utf-8")).hexdigest()
        receipt_id = self._verification_id(
            "motionqc", rendered_asset_id, media_sha256, receipt_sha256
        )
        bindings = receipt["bindings"]
        trusted_analysis = receipt["trustedEvidence"]["analysis"]
        now = self._utc_now()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO motion_qc_receipts
            (id, campaign_id, rendered_asset_id, subject_sha256, policy_id,
             policy_version, receipt_path, receipt_sha256, analysis_fingerprint,
             analyzer_registry_id, analyzer_registry_fingerprint,
             human_review_fingerprint, source_sha256, receipt_json,
             requirements_json, media_size_bytes, created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                asset["campaign_id"],
                rendered_asset_id,
                media_sha256,
                MOTION_QC_POLICY_ID,
                MOTION_QC_POLICY_VERSION,
                str(path),
                receipt_sha256,
                bindings["analysisFingerprint"],
                bindings["analyzerRegistryId"],
                bindings["analyzerRegistryFingerprint"],
                bindings["humanReviewFingerprint"],
                trusted_analysis["subject"]["sourceSha256"],
                canonical_receipt,
                json.dumps(requirements, sort_keys=True),
                media_size_bytes,
                now,
                created_by,
            ),
        )
        row = self.conn.execute(
            "SELECT * FROM motion_qc_receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                """SELECT * FROM motion_qc_receipts
                WHERE rendered_asset_id = ? AND receipt_sha256 = ?""",
                (rendered_asset_id, receipt_sha256),
            ).fetchone()
        if row is None:
            raise RuntimeError("motion QC receipt registration failed")
        self.record_event(
            "motion_qc_receipt_registered",
            campaign_id=asset["campaign_id"],
            rendered_asset_id=rendered_asset_id,
            status="success",
            message="Immutable motion QC receipt registered",
            metadata={
                "receiptId": row["id"],
                "receiptSha256": receipt_sha256,
                "subjectSha256": media_sha256,
                "policyId": MOTION_QC_POLICY_ID,
                "policyVersion": MOTION_QC_POLICY_VERSION,
            },
            commit=False,
        )
        if commit:
            self.conn.commit()
        return self.motion_qc_receipt_payload(dict(row))

    def motion_qc_receipt_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "renderedAssetId": row["rendered_asset_id"],
            "subjectSha256": row["subject_sha256"],
            "policy": {
                "id": row["policy_id"],
                "version": row["policy_version"],
            },
            "receiptPath": row["receipt_path"],
            "receiptSha256": row["receipt_sha256"],
            "analysisFingerprint": row["analysis_fingerprint"],
            "analyzerRegistry": {
                "id": row["analyzer_registry_id"],
                "fingerprint": row["analyzer_registry_fingerprint"],
            },
            "humanReviewFingerprint": row["human_review_fingerprint"],
            "sourceSha256": row["source_sha256"],
            "requirements": json_load(row["requirements_json"], {}),
            "mediaSizeBytes": row["media_size_bytes"],
            "createdAt": row["created_at"],
            "createdBy": row["created_by"],
        }

    def latest_motion_qc_receipt(self, rendered_asset_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """SELECT * FROM motion_qc_receipts
            WHERE rendered_asset_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (rendered_asset_id,),
        ).fetchone()
        return dict(row) if row else None

    def motion_qc_gate(self, asset: dict[str, Any]) -> dict[str, Any]:
        requirements = self.motion_qc_requirements(asset)
        identity_failures = self.generated_motion_identity_failures(asset)
        receipt_payload = None
        failures: list[str] = []
        if requirements["motion"]:
            row = self.latest_motion_qc_receipt(str(asset["id"]))
            if row is None:
                failures.append("motion_specific_qc_required")
                if requirements["audioAlignment"]:
                    failures.append("audio_video_alignment_qc_required")
                if requirements["lipSync"]:
                    failures.append("lip_sync_qc_required")
            else:
                receipt = json_load(row.get("receipt_json"), {})
                if not isinstance(receipt, dict):
                    failures.append("motion_specific_qc_receipt_invalid")
                else:
                    canonical_receipt = json.dumps(
                        receipt,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    if hashlib.sha256(
                        canonical_receipt.encode("utf-8")
                    ).hexdigest() != row.get("receipt_sha256"):
                        failures.append("motion_specific_qc_receipt_invalid")
                    validation_failures, _ = self._motion_qc_receipt_validation(
                        asset, receipt
                    )
                    failures.extend(validation_failures)
                    if row.get("subject_sha256") != asset.get("content_hash"):
                        failures.append("motion_specific_qc_subject_mismatch")
                    media_path = Path(
                        str(
                            asset.get("campaign_path") or asset.get("output_path") or ""
                        )
                    )
                    try:
                        media_sha256, media_size_bytes = _sha256_file(media_path)
                    except OSError:
                        failures.append("motion_specific_qc_media_unreadable")
                    else:
                        if media_sha256 != asset.get("content_hash"):
                            failures.append("motion_specific_qc_media_hash_mismatch")
                        if media_size_bytes != row.get("media_size_bytes"):
                            failures.append("motion_specific_qc_media_size_mismatch")
                    receipt_payload = self.motion_qc_receipt_payload(row)
        failures.extend(identity_failures)
        failures = sorted(set(failures))
        motion_only_failures = [
            value
            for value in failures
            if value != "text_to_video_identity_assignment_forbidden"
        ]
        return {
            "failures": failures,
            "requirements": requirements,
            "receipt": receipt_payload,
            "checks": {
                "motion_specific_qc_passed": bool(
                    not requirements["motion"] or not motion_only_failures
                ),
                "audio_video_alignment_qc_passed": bool(
                    not requirements["audioAlignment"] or not motion_only_failures
                ),
                "lip_sync_qc_passed": bool(
                    not requirements["lipSync"] or not motion_only_failures
                ),
                "creator_identity_assignment_allowed": not bool(identity_failures),
            },
        }
