from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from pipeline_contracts import (
    ContractValidationError,
    validate_local_model_arena_review_packet,
    validate_local_model_arena_summary,
    validate_local_model_arena_unblinding_receipt,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
NOW = "2026-07-22T12:00:00Z"


def _attestation() -> dict[str, Any]:
    return {
        "schema": "creator_os.evidence_attestation.v1",
        "algorithm": "hmac-sha256",
        "issuer": "reel_factory.local_model_arena",
        "keyId": "test-key",
        "issuedAt": NOW,
        "payloadFingerprint": SHA_A,
        "signature": SHA_B,
    }


def _candidate(
    *, ordinal: int = 1, candidate_id: str = "blind-1", subject_sha: str = SHA_C
) -> dict[str, Any]:
    return {
        "reviewOrdinal": ordinal,
        "blindedCandidateId": candidate_id,
        "creatorId": "stacey",
        "contentIntentId": "intent-1",
        "subjectPath": "/review/blind-1.mp4",
        "subjectSha256": subject_sha,
    }


def _review_packet() -> dict[str, Any]:
    return {
        "schema": "reel_factory.local_model_arena_review_packet.v1",
        "packetId": "packet-1",
        "arenaPlanId": "plan-1",
        "arenaPlanFingerprint": SHA_D,
        "createdAt": NOW,
        "expectedCandidateCount": 1,
        "candidates": [_candidate()],
        "providerCalls": 0,
        "productionWrites": 0,
        "producerAttestation": _attestation(),
        "packetFingerprint": SHA_E,
    }


def _binding(
    *,
    candidate_id: str = "blind-1",
    subject_sha: str = SHA_C,
    review_id: str = "review-1",
    sample_id: str = "sample-1",
) -> dict[str, Any]:
    return {
        "blindedCandidateId": candidate_id,
        "subjectSha256": subject_sha,
        "humanReviewId": review_id,
        "humanReviewFingerprint": SHA_A,
        "sampleId": sample_id,
        "modelId": "local-wan",
        "modelRevision": "revision-1",
        "modelManifestSha256": SHA_B,
        "modelDeepVerificationFingerprint": SHA_D,
        "modelFingerprint": SHA_E,
    }


def _unblinding_receipt() -> dict[str, Any]:
    return {
        "schema": "reel_factory.local_model_arena_unblinding_receipt.v1",
        "receiptId": "unblinding-1",
        "arenaPlanId": "plan-1",
        "arenaPlanFingerprint": SHA_D,
        "reviewPacketId": "packet-1",
        "reviewPacketFingerprint": SHA_E,
        "createdAt": NOW,
        "expectedReviewCount": 1,
        "lockedReviewSetFingerprint": SHA_F,
        "bindings": [_binding()],
        "providerCalls": 0,
        "productionWrites": 0,
        "producerAttestation": _attestation(),
        "receiptFingerprint": SHA_A,
    }


def _review_evidence(*, populated: bool) -> dict[str, Any]:
    if not populated:
        return {
            "reviewPacketId": None,
            "reviewPacketFingerprint": None,
            "unblindingReceiptId": None,
            "unblindingReceiptFingerprint": None,
        }
    return {
        "reviewPacketId": "packet-1",
        "reviewPacketFingerprint": SHA_E,
        "unblindingReceiptId": "unblinding-1",
        "unblindingReceiptFingerprint": SHA_A,
    }


def _arena_summary(*, purpose: str = "promotion_eligible") -> dict[str, Any]:
    return {
        "schema": "reel_factory.local_model_arena_summary.v1",
        "summaryId": "summary-1",
        "planId": "plan-1",
        "planFingerprint": SHA_D,
        "purpose": purpose,
        "expectedSampleCount": 1,
        "sampleCounts": {
            "cancelled": 0,
            "failed": 0,
            "interrupted": 0,
            "missing": 0,
            "resource_blocked": 0,
            "succeeded": 1,
            "unsupported": 0,
        },
        "promotionEligibleYield": 1.0,
        "samples": [
            {
                "sampleId": "sample-1",
                "creatorId": "stacey",
                "identityProfileId": "identity-1",
                "identityProfileFingerprint": SHA_A,
                "contentIntentId": "intent-1",
                "contentIntentFingerprint": SHA_B,
                "modelId": "local-wan",
                "capabilityCohort": "image_to_video",
                "taskKind": "image_to_video",
                "status": "succeeded",
                "reason": "measured",
                "outputSha256": SHA_C,
                "benchmarkId": "benchmark-1",
                "humanReviewId": "review-1",
                "qualityScore": 0.9,
                "wallTimeSeconds": 12.5,
                "peakMemoryBytes": 1024,
                "executionEvidence": {
                    "status": "succeeded",
                    "attemptCount": 1,
                    "retryCount": 0,
                    "admissionBlockCount": 0,
                    "failureClass": None,
                    "hardwareFingerprint": SHA_A,
                    "executionMeasurement": {
                        "available": True,
                        "wallTimeSeconds": 12.5,
                        "peakMemoryBytes": 1024,
                        "memoryMeasurementMethod": "resource.getrusage",
                    },
                    "localCost": {
                        "available": False,
                        "currency": "USD",
                        "reason": "not_measured",
                        "value": None,
                    },
                },
                "blockingReasons": [],
                "promotionEvidenceValid": True,
            }
        ],
        "candidateAggregates": [
            {
                "modelId": "local-wan",
                "capabilityCohort": "image_to_video",
                "plannedSamples": 1,
                "succeededSamples": 1,
                "failedSamples": 0,
                "failureRate": 0.0,
                "validSamples": 1,
                "promotionEligibleYield": 1.0,
                "meanHumanQualityScore": 0.9,
                "medianWallTimeSeconds": 12.5,
                "medianPeakMemoryBytes": 1024,
                "benchmarkIds": ["benchmark-1"],
            }
        ],
        "reviewEvidence": _review_evidence(populated=purpose == "promotion_eligible"),
        "providerCalls": 0,
        "productionWrites": 0,
        "summaryFingerprint": SHA_F,
    }


def test_arena_review_evidence_records_validate() -> None:
    validate_local_model_arena_review_packet(_review_packet())
    validate_local_model_arena_unblinding_receipt(_unblinding_receipt())
    validate_local_model_arena_summary(_arena_summary())


@pytest.mark.parametrize(
    "leaked_field",
    ("modelId", "sampleId", "queueJobId", "benchmarkRecipeId", "recipeFingerprint"),
)
def test_blinded_packet_rejects_identity_and_execution_leakage(
    leaked_field: str,
) -> None:
    packet = _review_packet()
    packet["candidates"][0][leaked_field] = "leaked"

    with pytest.raises(ContractValidationError, match=leaked_field):
        validate_local_model_arena_review_packet(packet)


@pytest.mark.parametrize(
    "validator,payload_factory",
    (
        (validate_local_model_arena_review_packet, _review_packet),
        (validate_local_model_arena_unblinding_receipt, _unblinding_receipt),
    ),
)
def test_arena_evidence_requires_producer_attestation(
    validator: Any, payload_factory: Any
) -> None:
    payload = payload_factory()
    del payload["producerAttestation"]

    with pytest.raises(ContractValidationError, match="producerAttestation"):
        validator(payload)


@pytest.mark.parametrize(
    "validator,payload_factory",
    (
        (validate_local_model_arena_review_packet, _review_packet),
        (validate_local_model_arena_unblinding_receipt, _unblinding_receipt),
    ),
)
def test_arena_evidence_rejects_malformed_attestation_signature(
    validator: Any, payload_factory: Any
) -> None:
    payload = payload_factory()
    payload["producerAttestation"]["signature"] = "forged"

    with pytest.raises(ContractValidationError, match="signature"):
        validator(payload)


@pytest.mark.parametrize(
    "duplicate_field", ("reviewOrdinal", "blindedCandidateId", "subjectSha256")
)
def test_review_packet_rejects_duplicate_candidate_bindings(
    duplicate_field: str,
) -> None:
    packet = _review_packet()
    second = _candidate(ordinal=2, candidate_id="blind-2", subject_sha=SHA_F)
    second[duplicate_field] = packet["candidates"][0][duplicate_field]
    packet["candidates"].append(second)
    packet["expectedCandidateCount"] = 2

    with pytest.raises(ContractValidationError, match=duplicate_field):
        validate_local_model_arena_review_packet(packet)


def test_review_packet_rejects_noncontiguous_ordinals() -> None:
    packet = _review_packet()
    packet["candidates"].append(
        _candidate(ordinal=3, candidate_id="blind-2", subject_sha=SHA_F)
    )
    packet["expectedCandidateCount"] = 2

    with pytest.raises(ContractValidationError, match="contiguous"):
        validate_local_model_arena_review_packet(packet)


def test_review_packet_rejects_declared_count_mismatch() -> None:
    packet = _review_packet()
    packet["expectedCandidateCount"] = 2

    with pytest.raises(ContractValidationError, match="expectedCandidateCount"):
        validate_local_model_arena_review_packet(packet)


@pytest.mark.parametrize(
    "duplicate_field",
    ("blindedCandidateId", "subjectSha256", "humanReviewId", "sampleId"),
)
def test_unblinding_receipt_rejects_duplicate_bindings(duplicate_field: str) -> None:
    receipt = _unblinding_receipt()
    second = _binding(
        candidate_id="blind-2",
        subject_sha=SHA_F,
        review_id="review-2",
        sample_id="sample-2",
    )
    second[duplicate_field] = receipt["bindings"][0][duplicate_field]
    receipt["bindings"].append(second)
    receipt["expectedReviewCount"] = 2

    with pytest.raises(ContractValidationError, match=duplicate_field):
        validate_local_model_arena_unblinding_receipt(receipt)


def test_unblinding_receipt_rejects_declared_count_mismatch() -> None:
    receipt = _unblinding_receipt()
    receipt["expectedReviewCount"] = 2

    with pytest.raises(ContractValidationError, match="expectedReviewCount"):
        validate_local_model_arena_unblinding_receipt(receipt)


@pytest.mark.parametrize(
    "field",
    (
        "reviewPacketId",
        "reviewPacketFingerprint",
        "unblindingReceiptId",
        "unblindingReceiptFingerprint",
    ),
)
def test_promotion_eligible_summary_requires_complete_review_evidence(
    field: str,
) -> None:
    summary = _arena_summary()
    summary["reviewEvidence"][field] = None

    with pytest.raises(ContractValidationError, match=field):
        validate_local_model_arena_summary(summary)


def test_exploratory_summary_allows_null_review_evidence() -> None:
    validate_local_model_arena_summary(_arena_summary(purpose="exploratory"))


@pytest.mark.parametrize(
    "payload_factory,validator,path",
    (
        (
            _review_packet,
            validate_local_model_arena_review_packet,
            ("arenaPlanFingerprint",),
        ),
        (
            _unblinding_receipt,
            validate_local_model_arena_unblinding_receipt,
            ("lockedReviewSetFingerprint",),
        ),
        (
            _arena_summary,
            validate_local_model_arena_summary,
            ("reviewEvidence", "reviewPacketFingerprint"),
        ),
    ),
)
def test_arena_evidence_rejects_wrong_fingerprint_shapes(
    payload_factory: Any, validator: Any, path: tuple[str, ...]
) -> None:
    payload = deepcopy(payload_factory())
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = "not-a-sha256"

    with pytest.raises(ContractValidationError, match=path[-1]):
        validator(payload)
