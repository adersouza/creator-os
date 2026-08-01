"""Execution-evidence validation for immutable creative approvals."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from creator_os_core.evidence_attestation import (
    EvidenceAttestationError,
    load_evidence_secret,
    verify_evidence_attestation,
)

from pipeline_contracts import (
    validate_paid_motion_execution_receipt,
    validate_provider_spend_authorization_v2,
)

from .creative_approval_support import (
    CreativeApprovalError,
)
from .creative_approval_support import (
    fingerprint as _fingerprint,
)
from .creative_approval_support import (
    load_bound_json as _load_bound_json,
)
from .creative_approval_support import (
    required_text as _required_text,
)
from .creative_approval_support import (
    sha as _sha,
)
from .creative_approval_support import (
    timestamp as _timestamp,
)
from .creative_approval_support import (
    verify_bound_file as _verify_bound_file,
)


def _binding(
    value: Any, field: str, *, nullable: bool = False
) -> dict[str, str] | None:
    if value is None and nullable:
        return None
    if not isinstance(value, dict) or set(value) != {"id", "fingerprint"}:
        raise CreativeApprovalError(f"creative_approval_{field}_invalid")
    return {
        "id": _required_text(value.get("id"), f"{field}_id"),
        "fingerprint": _sha(value.get("fingerprint"), f"{field}_fingerprint"),
    }


def _validate_execution_evidence(
    value: Any,
    *,
    model_binding: dict[str, str],
    input_binding: dict[str, str],
    output_binding: dict[str, str],
    approved_at: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CreativeApprovalError("creative_approval_execution_evidence_invalid")
    execution_class = value.get("class")
    if execution_class == "local_model":
        if set(value) != {"class", "admission"}:
            raise CreativeApprovalError("creative_approval_local_evidence_invalid")
        admission = _binding(value.get("admission"), "local_admission")
        assert isinstance(admission, dict)
        if not model_binding["id"].startswith("local_"):
            raise CreativeApprovalError("creative_approval_local_model_mismatch")
        return {"class": "local_model", "admission": admission}
    if execution_class != "paid_provider":
        raise CreativeApprovalError("creative_approval_execution_class_invalid")
    if model_binding["id"].startswith("local_"):
        raise CreativeApprovalError("creative_approval_paid_model_mismatch")
    if value.get("provider") == "higgsfield":
        expected_keys = {
            "class",
            "provider",
            "providerModel",
            "requestFingerprint",
            "authorizationId",
            "generationId",
            "soulId",
            "providerEvidence",
            "source",
            "output",
            "costEventIds",
        }
        if set(value) != expected_keys:
            raise CreativeApprovalError("creative_approval_paid_evidence_invalid")
        provider_model = _required_text(value.get("providerModel"), "provider_model")
        request_fingerprint = _sha(
            value.get("requestFingerprint"), "provider_request_fingerprint"
        )
        authorization_id = _required_text(
            value.get("authorizationId"), "provider_authorization_id"
        )
        generation_id = _required_text(
            value.get("generationId"), "provider_generation_id"
        )
        soul_id = _required_text(value.get("soulId"), "provider_soul_id")
        source = _verify_bound_file(value.get("source"), "provider_source")
        output = _verify_bound_file(value.get("output"), "provider_output")
        cost_event_ids = value.get("costEventIds")
        if (
            source != input_binding
            or output != output_binding
            or not isinstance(cost_event_ids, list)
            or not cost_event_ids
            or any(not isinstance(item, str) or not item for item in cost_event_ids)
        ):
            raise CreativeApprovalError(
                "creative_approval_higgsfield_execution_binding_mismatch"
            )
        provider_payload, provider_file = _load_bound_json(
            value.get("providerEvidence"), "provider_execution_evidence"
        )
        receipt_source = provider_payload.get("source")
        receipt_output = provider_payload.get("finalOutput")
        if (
            provider_payload.get("schema")
            != "reel_factory.higgsfield_production_receipt.v1"
            or provider_payload.get("status") != "completed"
            or provider_payload.get("authorizationId") != authorization_id
            or provider_payload.get("providerRequestFingerprint") != request_fingerprint
            or provider_payload.get("model") != provider_model
            or provider_payload.get("generationId") != generation_id
            or provider_payload.get("soulId") != soul_id
            or not isinstance(receipt_source, dict)
            or {
                "path": receipt_source.get("path"),
                "sha256": receipt_source.get("sha256"),
            }
            != source
            or not isinstance(receipt_output, dict)
            or {
                "path": receipt_output.get("path"),
                "sha256": receipt_output.get("sha256"),
            }
            != output
        ):
            raise CreativeApprovalError(
                "creative_approval_higgsfield_execution_binding_mismatch"
            )
        return {**value, "providerEvidence": provider_file}
    expected_keys = {
        "class",
        "provider",
        "providerModel",
        "requestFingerprint",
        "authorization",
        "authorizationEvidence",
        "prediction",
        "providerEvidence",
        "spendRecord",
        "executionReceipt",
        "executionReceiptEvidence",
    }
    if set(value) != expected_keys or value.get("provider") != "wavespeed":
        raise CreativeApprovalError("creative_approval_paid_evidence_invalid")
    provider_model = _required_text(value.get("providerModel"), "provider_model")
    request_fingerprint = _sha(
        value.get("requestFingerprint"), "provider_request_fingerprint"
    )
    authorization = _binding(value.get("authorization"), "provider_authorization")
    prediction = _binding(value.get("prediction"), "provider_prediction")
    spend_record = _binding(value.get("spendRecord"), "provider_spend_record")
    execution_receipt = _binding(
        value.get("executionReceipt"), "paid_execution_receipt"
    )
    assert isinstance(authorization, dict)
    assert isinstance(prediction, dict)
    assert isinstance(spend_record, dict)
    assert isinstance(execution_receipt, dict)
    authorization_payload, authorization_file = _load_bound_json(
        value.get("authorizationEvidence"), "provider_authorization_evidence"
    )
    provider_payload, provider_file = _load_bound_json(
        value.get("providerEvidence"), "provider_execution_evidence"
    )
    execution_payload, execution_file = _load_bound_json(
        value.get("executionReceiptEvidence"), "paid_execution_receipt_evidence"
    )
    try:
        validate_provider_spend_authorization_v2(authorization_payload)
        validate_paid_motion_execution_receipt(execution_payload)
    except Exception as exc:
        raise CreativeApprovalError(
            "creative_approval_paid_execution_contract_invalid"
        ) from exc
    verified_at = _timestamp(
        execution_payload.get("authorizationVerifiedAt"),
        "paid_execution_authorization_verified_at",
    )
    recorded_at = _timestamp(
        execution_payload.get("recordedAt"), "paid_execution_recorded_at"
    )
    if verified_at > recorded_at or recorded_at > (approved_at or datetime.now(UTC)):
        raise CreativeApprovalError("creative_approval_paid_execution_time_invalid")
    authorization_scope = authorization_payload.get("scope")
    authorization_scope = (
        authorization_scope if isinstance(authorization_scope, dict) else {}
    )
    if (
        authorization_payload.get("authorizationId") != authorization["id"]
        or _fingerprint(authorization_payload) != authorization["fingerprint"]
        or authorization_scope.get("requestFingerprint") != request_fingerprint
        or authorization_scope.get("providerModel") != provider_model
        or authorization_scope.get("provider") != "wavespeed"
    ):
        raise CreativeApprovalError(
            "creative_approval_provider_authorization_binding_mismatch"
        )
    if (
        provider_payload.get("schema") != "reel_factory.wavespeed_submission.v1"
        or provider_payload.get("status") != "completed"
        or provider_payload.get("authorizationId") != authorization["id"]
        or provider_payload.get("requestFingerprint") != request_fingerprint
        or provider_payload.get("providerModel") != provider_model
        or provider_payload.get("predictionId") != prediction["id"]
        or provider_payload.get("outputSha256") != output_binding["sha256"]
        or _fingerprint(
            {
                "provider": "wavespeed",
                "providerModel": provider_model,
                "predictionId": prediction["id"],
                "requestFingerprint": request_fingerprint,
                "inputSha256": input_binding["sha256"],
                "outputSha256": output_binding["sha256"],
            }
        )
        != prediction["fingerprint"]
    ):
        raise CreativeApprovalError(
            "creative_approval_provider_execution_binding_mismatch"
        )
    receipt_attested = dict(execution_payload)
    receipt_attestation = receipt_attested.pop("attestation", None)
    receipt_core = dict(receipt_attested)
    receipt_fingerprint = _sha(
        receipt_core.pop("receiptFingerprint", None),
        "paid_execution_receipt_fingerprint",
    )
    if (
        not isinstance(receipt_attestation, dict)
        or receipt_fingerprint != execution_receipt["fingerprint"]
        or _fingerprint(receipt_core) != receipt_fingerprint
        or execution_payload.get("receiptId") != execution_receipt["id"]
    ):
        raise CreativeApprovalError("creative_approval_paid_execution_receipt_mismatch")
    try:
        verify_evidence_attestation(
            receipt_attestation,
            receipt_attested,
            secret=load_evidence_secret(),
            expected_issuer="campaign_factory.motion_generation_stage",
        )
    except EvidenceAttestationError as exc:
        raise CreativeApprovalError(
            f"creative_approval_paid_execution_attestation_invalid:{exc}"
        ) from exc
    receipt_cost = execution_payload.get("costRecord")
    if (
        execution_payload.get("authorization") != authorization
        or execution_payload.get("authorizationEvidence") != authorization_file
        or execution_payload.get("scope") != authorization_scope
        or execution_payload.get("requestFingerprint") != request_fingerprint
        or execution_payload.get("providerModel") != provider_model
        or execution_payload.get("input") != input_binding
        or execution_payload.get("output") != output_binding
        or execution_payload.get("prediction") != prediction
        or execution_payload.get("providerEvidence") != provider_file
        or not isinstance(receipt_cost, dict)
        or receipt_cost.get("id") != spend_record["id"]
        or receipt_cost.get("fingerprint") != spend_record["fingerprint"]
        or _fingerprint(receipt_cost.get("snapshot") or {})
        != spend_record["fingerprint"]
    ):
        raise CreativeApprovalError("creative_approval_paid_execution_chain_mismatch")
    return {
        **value,
        "authorizationEvidence": authorization_file,
        "providerEvidence": provider_file,
        "executionReceiptEvidence": execution_file,
    }
