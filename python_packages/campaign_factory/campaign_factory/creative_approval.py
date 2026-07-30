"""Immutable creative approval binding for the ordinary operator workflow."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from creator_os_core.evidence_attestation import (
    EvidenceAttestationError,
    load_evidence_secret,
    sign_evidence_attestation,
    verify_evidence_attestation,
)
from creator_os_core.fileops import atomic_write_json, file_lock

from pipeline_contracts import (
    validate_creative_approval_v2 as validate_v2_contract,
)
from pipeline_contracts import (
    validate_paid_motion_execution_receipt,
    validate_provider_spend_authorization_v2,
)

from .creative_approval_support import (
    LEGACY_INVENTORY_SCHEMA,
    CreativeApprovalError,
)
from .creative_approval_support import (
    creative_export_projection as _creative_export_projection,
)
from .creative_approval_support import (
    fingerprint as _fingerprint,
)
from .creative_approval_support import (
    is_sha as _is_sha,
)
from .creative_approval_support import (
    load_bound_json as _load_bound_json,
)
from .creative_approval_support import (
    operator_media_review_receipt as _operator_media_review_receipt_impl,
)
from .creative_approval_support import (
    required_text as _required_text,
)
from .creative_approval_support import (
    sha as _sha,
)
from .creative_approval_support import (
    sha256_file as _sha256_file,
)
from .creative_approval_support import (
    timestamp as _timestamp,
)
from .creative_approval_support import (
    validate_operator_media_review as _validate_operator_media_review_impl,
)
from .creative_approval_support import (
    verify_bound_file as _verify_bound_file,
)
from .creative_approval_support import (
    write_content_addressed_json as _write_content_addressed_json,
)
from .motion_qc_publishability import (
    MOTION_QC_POLICY_ID,
    MOTION_QC_POLICY_VERSION,
    MotionQcPublishabilityMixin,
)
from .production_quality_policy import is_observed_passive_derivative

SCHEMA: Final = "campaign_factory.creative_approval.v1"
SCHEMA_V2: Final = "campaign_factory.creative_approval.v2"
EXPORT_PROJECTION_SCHEMA: Final = "campaign_factory.creative_export_projection.v1"
APPROVAL_ATTESTATION_ISSUER: Final = "campaign_factory.creative_approval"
REVIEW_MANIFEST_SCHEMA: Final = "campaign_factory.creative_review_manifest.v1"
OPERATOR_MEDIA_REVIEW_SCHEMA: Final = "creator_os.operator_media_review.v1"
FINAL_ARTIFACT_AUDIT_POLICY_ID: Final = "contentforge.final_artifact_audit"


def _asset_metadata(asset: dict[str, Any]) -> dict[str, Any]:
    metadata = asset.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    try:
        decoded = json.loads(asset.get("metadata_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _is_motion_generation_asset(asset: dict[str, Any]) -> bool:
    metadata = _asset_metadata(asset)
    return bool(
        metadata.get("schema") == "campaign_factory.motion_generation_asset.v1"
        or str(asset.get("frame_type") or "") == "generated_motion"
    )


def asset_requires_creative_approval(asset: dict[str, Any]) -> bool:
    """Derive approval policy from asset lineage, never generic review state."""

    if is_observed_passive_derivative(asset):
        return False
    metadata = _asset_metadata(asset)
    return bool(
        _is_motion_generation_asset(asset)
        or str(asset.get("recipe") or "") == "static_mp4"
        or metadata.get("humanReviewRequired") is True
    )


def validate_creative_approval(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") == SCHEMA_V2:
        return validate_creative_approval_v2(payload)
    if payload.get("schema") != SCHEMA:
        raise CreativeApprovalError("creative_approval_schema_mismatch")
    core = dict(payload)
    claimed = _sha(core.pop("approvalFingerprint", None), "fingerprint")
    if _fingerprint(core) != claimed:
        raise CreativeApprovalError("creative_approval_fingerprint_mismatch")
    _required_text(payload.get("approvalId"), "id")
    _required_text(payload.get("approvedBy"), "approved_by")
    _required_text(payload.get("approvedAt"), "approved_at")
    for field in ("creatorIdentity", "contentIntent", "benchmarkRecipe", "model"):
        record = payload.get(field)
        if not isinstance(record, dict):
            raise CreativeApprovalError(f"creative_approval_{field}_invalid")
        _required_text(record.get("id"), f"{field}_id")
        _sha(record.get("fingerprint"), f"{field}_fingerprint")
    _verify_bound_file(payload.get("input"), "input")
    output = _verify_bound_file(payload.get("output"), "output")
    qc = payload.get("qcEvidence")
    if not isinstance(qc, list) or not qc:
        raise CreativeApprovalError("creative_approval_qc_evidence_missing")
    identities: set[str] = set()
    for item in qc:
        if not isinstance(item, dict):
            raise CreativeApprovalError("creative_approval_qc_evidence_invalid")
        check_id = _required_text(item.get("checkId"), "qc_check_id")
        if check_id in identities:
            raise CreativeApprovalError("creative_approval_duplicate_qc_identity")
        identities.add(check_id)
        if item.get("passed") is not True:
            raise CreativeApprovalError(f"creative_approval_qc_blocked:{check_id}")
        if _sha(item.get("subjectSha256"), "qc_subject_sha256") != output["sha256"]:
            raise CreativeApprovalError(
                f"creative_approval_qc_subject_mismatch:{check_id}"
            )
        receipt = (
            Path(_required_text(item.get("receiptPath"), "qc_receipt_path"))
            .expanduser()
            .resolve()
        )
        if (
            not receipt.is_file()
            or receipt.is_symlink()
            or _sha256_file(receipt)
            != _sha(item.get("receiptSha256"), "qc_receipt_sha256")
        ):
            raise CreativeApprovalError(
                f"creative_approval_qc_receipt_substituted:{check_id}"
            )
    export = payload.get("exportPayload")
    if not isinstance(export, dict):
        raise CreativeApprovalError("creative_approval_export_payload_invalid")
    _required_text(export.get("schema"), "export_schema")
    _sha(export.get("fingerprint"), "export_fingerprint")
    semantics = payload.get("contentSemantics")
    if not isinstance(semantics, dict):
        raise CreativeApprovalError("creative_approval_content_semantics_missing")
    required_semantics = {
        "burnedOverlayText",
        "instagramPostCaption",
        "generatedAudio",
        "sourceAudio",
        "nativeInstagramAudio",
    }
    if set(semantics) != required_semantics:
        raise CreativeApprovalError("creative_approval_content_semantics_invalid")
    return payload


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


def _validate_v2_qc(
    payload: dict[str, Any],
    *,
    input_binding: dict[str, str],
    prompt_source: dict[str, str] | None,
    output_binding: dict[str, str],
    approved_at: datetime,
) -> None:
    evidence = payload.get("qcEvidence")
    if not isinstance(evidence, list) or not evidence:
        raise CreativeApprovalError("creative_approval_qc_evidence_missing")
    identities: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise CreativeApprovalError("creative_approval_qc_evidence_invalid")
        check_id = _required_text(item.get("checkId"), "qc_check_id")
        if check_id in identities:
            raise CreativeApprovalError("creative_approval_duplicate_qc_identity")
        identities.add(check_id)
        if item.get("passed") is not True:
            raise CreativeApprovalError(f"creative_approval_qc_blocked:{check_id}")
        if (
            _sha(item.get("subjectSha256"), "qc_subject_sha256")
            != output_binding["sha256"]
        ):
            raise CreativeApprovalError(
                f"creative_approval_qc_subject_mismatch:{check_id}"
            )
        receipt = (
            Path(_required_text(item.get("receiptPath"), "qc_receipt_path"))
            .expanduser()
            .resolve()
        )
        expected_receipt_sha = _sha(item.get("receiptSha256"), "qc_receipt_sha256")
        if (
            not receipt.is_file()
            or receipt.is_symlink()
            or _sha256_file(receipt) != expected_receipt_sha
        ):
            raise CreativeApprovalError(
                f"creative_approval_qc_receipt_substituted:{check_id}"
            )
        try:
            decoded = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CreativeApprovalError(
                f"creative_approval_qc_receipt_invalid_json:{check_id}"
            ) from exc
        if not isinstance(decoded, dict):
            raise CreativeApprovalError(
                f"creative_approval_qc_receipt_invalid_json:{check_id}"
            )
        receipt_subject = (
            decoded.get("subjectSha256")
            or decoded.get("mediaSha256")
            or decoded.get("outputSha256")
        )
        if receipt_subject != output_binding["sha256"]:
            raise CreativeApprovalError(
                f"creative_approval_qc_receipt_subject_mismatch:{check_id}"
            )
        if decoded.get("checkId") not in {None, check_id}:
            raise CreativeApprovalError(
                f"creative_approval_qc_receipt_identity_mismatch:{check_id}"
            )
        if check_id == FINAL_ARTIFACT_AUDIT_POLICY_ID:
            readiness = decoded.get("readinessSummary")
            integrity = decoded.get("finalArtifactIntegrity")
            analyzer = decoded.get("analyzerEvidence")
            if (
                decoded.get("overallVerdict") != "pass"
                or not isinstance(readiness, dict)
                or readiness.get("uploadReady") is not True
                or readiness.get("blockingReasons")
                or readiness.get("blockingCodes")
                or not isinstance(integrity, dict)
                or integrity.get("schema")
                != "campaign_factory.final_artifact_integrity.v1"
                or integrity.get("subjectSha256") != output_binding["sha256"]
                or integrity.get("passed") is not True
                or (integrity.get("decode") or {}).get("passed") is not True
                or (integrity.get("probe") or {}).get("passed") is not True
                or (integrity.get("captionBinding") or {}).get("passed") is not True
                or (integrity.get("audioBinding") or {}).get("passed") is not True
                or not isinstance(analyzer, dict)
                or not _is_sha(analyzer.get("implementationFingerprint"))
                or str(analyzer.get("analyzerVersion") or "") in {"", "unknown"}
                or not isinstance(analyzer.get("implementationComponents"), dict)
                or not analyzer.get("implementationComponents")
            ):
                raise CreativeApprovalError(
                    f"creative_approval_qc_receipt_not_passed:{check_id}"
                )
            continue
        if decoded.get("passed") is not True and decoded.get("status") != "passed":
            raise CreativeApprovalError(
                f"creative_approval_qc_receipt_not_passed:{check_id}"
            )
        policy = decoded.get("policy")
        if check_id != MOTION_QC_POLICY_ID:
            raise CreativeApprovalError(
                f"creative_approval_qc_policy_unsupported:{check_id}"
            )
        if not isinstance(policy, dict) or policy != {
            "id": MOTION_QC_POLICY_ID,
            "version": MOTION_QC_POLICY_VERSION,
        }:
            raise CreativeApprovalError(
                f"creative_approval_qc_policy_mismatch:{check_id}"
            )
        synthetic_asset = {
            "content_hash": output_binding["sha256"],
            "metadata_json": json.dumps(
                (
                    {"promptSource": prompt_source}
                    if prompt_source is not None
                    else {"generationInput": input_binding}
                ),
                sort_keys=True,
            ),
        }
        trusted_failures = MotionQcPublishabilityMixin._trusted_motion_qc_failures(
            synthetic_asset, decoded
        )
        if trusted_failures:
            raise CreativeApprovalError(
                f"creative_approval_qc_untrusted:{check_id}:" + trusted_failures[0]
            )
        trusted = decoded.get("trustedEvidence")
        trusted = trusted if isinstance(trusted, dict) else {}
        analysis = trusted.get("analysis")
        analysis = analysis if isinstance(analysis, dict) else {}
        review = trusted.get("humanReview")
        review = review if isinstance(review, dict) else {}
        registry = trusted.get("analyzerRegistry")
        registry = registry if isinstance(registry, dict) else {}
        registry_provenance = registry.get("provenance")
        registry_provenance = (
            registry_provenance if isinstance(registry_provenance, dict) else {}
        )
        registry_at = _timestamp(
            registry_provenance.get("producedAt"), "qc_registry_produced_at"
        )
        analysis_at = _timestamp(analysis.get("producedAt"), "qc_analysis_produced_at")
        review_at = _timestamp(review.get("reviewedAt"), "qc_reviewed_at")
        if not registry_at <= analysis_at <= review_at <= approved_at:
            raise CreativeApprovalError(
                f"creative_approval_qc_time_order_invalid:{check_id}"
            )
        if max(registry_at, analysis_at, review_at) > datetime.now(UTC):
            raise CreativeApprovalError(f"creative_approval_qc_time_future:{check_id}")
    if FINAL_ARTIFACT_AUDIT_POLICY_ID not in identities:
        raise CreativeApprovalError("creative_approval_final_artifact_audit_missing")


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


def validate_creative_approval_v2(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != SCHEMA_V2:
        raise CreativeApprovalError("creative_approval_schema_mismatch")
    approved_at = _timestamp(payload.get("approvedAt"), "approved_at")
    if approved_at > datetime.now(UTC):
        raise CreativeApprovalError("creative_approval_approved_at_future")
    try:
        validate_v2_contract(payload)
    except Exception as exc:
        raise CreativeApprovalError("creative_approval_contract_invalid") from exc
    attested_payload = dict(payload)
    attestation = attested_payload.pop("operatorAttestation", None)
    if not isinstance(attestation, dict):
        raise CreativeApprovalError("creative_approval_operator_attestation_missing")
    _required_text(payload.get("approvalId"), "id")
    _required_text(payload.get("approvedBy"), "approved_by")
    semantic_core = dict(attested_payload)
    claimed = _sha(semantic_core.pop("approvalFingerprint", None), "fingerprint")
    if _fingerprint(semantic_core) != claimed:
        raise CreativeApprovalError("creative_approval_fingerprint_mismatch")
    try:
        verify_evidence_attestation(
            attestation,
            attested_payload,
            secret=load_evidence_secret(),
            expected_issuer=APPROVAL_ATTESTATION_ISSUER,
        )
    except EvidenceAttestationError as exc:
        raise CreativeApprovalError(
            f"creative_approval_operator_attestation_invalid:{exc}"
        ) from exc
    if _timestamp(attestation.get("issuedAt"), "attestation_issued_at") != approved_at:
        raise CreativeApprovalError("creative_approval_attestation_time_mismatch")
    campaign = payload.get("campaign")
    if not isinstance(campaign, dict) or set(campaign) != {"id", "slug"}:
        raise CreativeApprovalError("creative_approval_campaign_invalid")
    _required_text(campaign.get("id"), "campaign_id")
    _required_text(campaign.get("slug"), "campaign_slug")
    bindings: dict[str, dict[str, str] | None] = {}
    for field in (
        "renderedAsset",
        "creatorIdentity",
        "contentIntent",
        "generationRecipe",
        "model",
    ):
        bindings[field] = _binding(payload.get(field), field)
    model_binding = bindings["model"]
    assert isinstance(model_binding, dict)
    input_binding = _verify_bound_file(payload.get("input"), "input")
    prompt_source = (
        _verify_bound_file(payload.get("promptSource"), "prompt_source")
        if payload.get("promptSource") is not None
        else None
    )
    if prompt_source is not None and prompt_source != input_binding:
        raise CreativeApprovalError("creative_approval_prompt_source_input_mismatch")
    output = _verify_bound_file(payload.get("output"), "output")
    _validate_execution_evidence(
        payload.get("executionEvidence"),
        model_binding=model_binding,
        input_binding=input_binding,
        output_binding=output,
        approved_at=approved_at,
    )
    review_manifest, review_manifest_binding = _load_bound_json(
        payload.get("reviewManifest"), "review_manifest"
    )
    if review_manifest.get("schema") != REVIEW_MANIFEST_SCHEMA:
        raise CreativeApprovalError("creative_approval_review_manifest_schema_invalid")
    manifest_core = dict(review_manifest)
    manifest_claimed = _sha(
        manifest_core.pop("manifestFingerprint", None), "review_manifest_fingerprint"
    )
    if _fingerprint(manifest_core) != manifest_claimed:
        raise CreativeApprovalError(
            "creative_approval_review_manifest_fingerprint_mismatch"
        )
    if review_manifest.get("renderedAsset") != bindings["renderedAsset"]:
        raise CreativeApprovalError("creative_approval_review_manifest_asset_mismatch")
    if review_manifest.get("promptSource") != prompt_source:
        raise CreativeApprovalError(
            "creative_approval_review_manifest_prompt_source_mismatch"
        )
    _validate_v2_qc(
        payload,
        input_binding=input_binding,
        prompt_source=prompt_source,
        output_binding=output,
        approved_at=approved_at,
    )
    rendered_asset_binding = bindings["renderedAsset"]
    assert isinstance(rendered_asset_binding, dict)
    _validate_operator_media_review(
        payload.get("operatorReview"),
        rendered_asset_id=rendered_asset_binding["id"],
        final_sha256=output["sha256"],
        review_manifest_sha256=review_manifest_binding["sha256"],
        approved_by=_required_text(payload.get("approvedBy"), "approved_by"),
        approved_at=approved_at,
    )
    projection = payload.get("exportProjection")
    if (
        not isinstance(projection, dict)
        or projection.get("schema") != EXPORT_PROJECTION_SCHEMA
    ):
        raise CreativeApprovalError("creative_approval_export_projection_invalid")
    projection_core = dict(projection)
    projection_claimed = _sha(
        projection_core.pop("fingerprint", None), "export_projection_fingerprint"
    )
    if _fingerprint(projection_core) != projection_claimed:
        raise CreativeApprovalError(
            "creative_approval_export_projection_fingerprint_mismatch"
        )
    manifest_draft = review_manifest.get("draft")
    manifest_campaign = review_manifest.get("campaign")
    if (
        not isinstance(manifest_draft, dict)
        or manifest_campaign != campaign
        or creative_export_projection(
            manifest_draft,
            campaign_slug=str(campaign["slug"]),
            prompt_source=prompt_source,
        )
        != projection
    ):
        raise CreativeApprovalError(
            "creative_approval_review_manifest_projection_mismatch"
        )
    semantics = payload.get("contentSemantics")
    required_semantics = {
        "burnedOverlayText",
        "instagramPostCaption",
        "generatedAudio",
        "sourceAudio",
        "nativeInstagramAudio",
    }
    if not isinstance(semantics, dict) or set(semantics) != required_semantics:
        raise CreativeApprovalError("creative_approval_content_semantics_invalid")
    return payload


def rendered_asset_approval_fingerprint(asset: dict[str, Any]) -> str:
    metadata = _asset_metadata(asset)
    admission = (
        metadata.get("localMotionAdmission") if isinstance(metadata, dict) else None
    )
    return _fingerprint(
        {
            "campaignId": asset.get("campaign_id") or asset.get("campaignId"),
            "renderedAssetId": asset.get("id") or asset.get("renderedAssetId"),
            "sourceAssetId": asset.get("source_asset_id") or asset.get("sourceAssetId"),
            "contentSha256": asset.get("content_hash") or asset.get("contentHash"),
            "outputPath": str(
                asset.get("output_path")
                or asset.get("campaign_path")
                or asset.get("filePath")
                or ""
            ),
            "modelId": metadata.get("modelId")
            or asset.get("recipe")
            or asset.get("modelId"),
            "requestFingerprint": metadata.get("requestFingerprint"),
            "generationAdmissionFingerprint": admission.get("admissionFingerprint")
            if isinstance(admission, dict)
            else None,
            "paidGenerationEvidenceFingerprint": _fingerprint(
                metadata["paidGenerationEvidence"]
            )
            if isinstance(metadata.get("paidGenerationEvidence"), dict)
            else None,
        }
    )


def canonical_asset_approval_bindings(asset: dict[str, Any]) -> dict[str, Any]:
    """Derive every approval binding from the stored generated-asset lineage."""

    if not asset_requires_creative_approval(asset):
        raise CreativeApprovalError("creative_approval_not_required_for_asset")
    if not _is_motion_generation_asset(asset):
        return _canonical_ordinary_asset_approval_bindings(asset)
    metadata = _asset_metadata(asset)
    model_id = _required_text(metadata.get("modelId"), "asset_model_id")
    paid = metadata.get("paidGeneration") is True
    if paid:
        paid_evidence = metadata.get("paidGenerationEvidence")
        if not isinstance(paid_evidence, dict):
            raise CreativeApprovalError("creative_approval_paid_evidence_missing")
        identity = paid_evidence.get("creatorIdentityProfile")
        intent = paid_evidence.get("contentIntent")
        recipe = paid_evidence.get("generationRecipe")
        execution_evidence = paid_evidence.get("executionEvidence")
        selected_model_fingerprint = _sha(
            paid_evidence.get("modelFingerprint"), "asset_model_fingerprint"
        )
        if not all(
            isinstance(value, dict)
            for value in (identity, intent, recipe, execution_evidence)
        ):
            raise CreativeApprovalError("creative_approval_paid_evidence_invalid")
        assert isinstance(identity, dict)
        assert isinstance(intent, dict)
        assert isinstance(recipe, dict)
        assert isinstance(execution_evidence, dict)
    else:
        admission = metadata.get("localMotionAdmission")
        if not isinstance(admission, dict):
            raise CreativeApprovalError(
                "creative_approval_generation_admission_missing"
            )
        admission_core = dict(admission)
        admission_fingerprint = _sha(
            admission_core.pop("admissionFingerprint", None),
            "generation_admission_fingerprint",
        )
        if _fingerprint(admission_core) != admission_fingerprint:
            raise CreativeApprovalError(
                "creative_approval_generation_admission_fingerprint_mismatch"
            )
        records = admission.get("evidenceRecords")
        decision = admission.get("routerDecision")
        if not isinstance(records, dict) or not isinstance(decision, dict):
            raise CreativeApprovalError("creative_approval_generation_evidence_missing")
        identity = records.get("creatorIdentityProfile")
        intent = records.get("contentIntent")
        recipe = records.get("benchmarkRecipe")
        if not all(isinstance(value, dict) for value in (identity, intent, recipe)):
            raise CreativeApprovalError("creative_approval_generation_evidence_invalid")
        assert isinstance(identity, dict)
        assert isinstance(intent, dict)
        assert isinstance(recipe, dict)
        if decision.get("selectedModelId") != model_id:
            raise CreativeApprovalError("creative_approval_asset_model_mismatch")
        selected_model_fingerprint = _sha(
            decision.get("selectedModelFingerprint"), "asset_model_fingerprint"
        )
        decision_id = _required_text(decision.get("decisionId"), "router_decision_id")
        execution_evidence = {
            "class": "local_model",
            "admission": {
                "id": decision_id,
                "fingerprint": admission_fingerprint,
            },
        }
    source_role = metadata.get("sourceAssetRole")
    prompt_source: dict[str, str] | None = None
    input_record: Any
    if source_role == "prompt_provenance_only":
        if (
            metadata.get("generationInput") is not None
            or metadata.get("staticFallbackSource") is not None
            or metadata.get("identityRole") != "non_creator_broll"
        ):
            raise CreativeApprovalError("creative_approval_prompt_source_role_mismatch")
        prompt_source = _verify_bound_file(
            metadata.get("promptSource"), "canonical_prompt_source"
        )
        input_record = prompt_source
    else:
        if metadata.get("promptSource") is not None:
            raise CreativeApprovalError("creative_approval_prompt_source_unexpected")
        input_record = metadata.get("generationInput") or metadata.get(
            "staticFallbackSource"
        )
    input_binding = _verify_bound_file(input_record, "canonical_input")
    output_binding = _verify_bound_file(
        {
            "path": asset.get("output_path")
            or asset.get("campaign_path")
            or asset.get("filePath"),
            "sha256": asset.get("content_hash") or asset.get("contentHash"),
        },
        "canonical_output",
    )
    if paid:
        assert isinstance(paid_evidence, dict)
        assert isinstance(execution_evidence, dict)
        spend_record = paid_evidence.get("spendRecord")
        if (
            identity.get("schema") != "creator_os.creator_identity_profile.v1"
            or intent.get("schema") != "creator_os.content_intent.v1"
            or intent.get("creatorIdentityProfileId") != identity.get("profileId")
            or input_binding["sha256"]
            not in (intent.get("sourceAssetFingerprints") or [])
            or recipe.get("schema") != "campaign_factory.paid_motion_recipe.v1"
            or recipe.get("creatorOsModelId") != model_id
            or recipe.get("providerRequestFingerprint")
            != execution_evidence.get("requestFingerprint")
            or paid_evidence.get("input") != input_binding
            or paid_evidence.get("output") != output_binding
            or not isinstance(spend_record, dict)
            or _fingerprint(spend_record)
            != (execution_evidence.get("spendRecord") or {}).get("fingerprint")
        ):
            raise CreativeApprovalError("creative_approval_paid_lineage_mismatch")
        _validate_execution_evidence(
            execution_evidence,
            model_binding={"id": model_id, "fingerprint": selected_model_fingerprint},
            input_binding=input_binding,
            output_binding=output_binding,
        )
    bindings = {
        "renderedAsset": {
            "id": _required_text(
                asset.get("id") or asset.get("renderedAssetId"), "rendered_asset_id"
            ),
            "fingerprint": rendered_asset_approval_fingerprint(asset),
        },
        "creatorIdentity": {
            "id": _required_text(identity.get("profileId"), "creator_identity_id"),
            "fingerprint": _fingerprint(identity),
        },
        "contentIntent": {
            "id": _required_text(intent.get("intentId"), "content_intent_id"),
            "fingerprint": _fingerprint(intent),
        },
        "generationRecipe": {
            "id": _required_text(recipe.get("recipeId"), "benchmark_recipe_id"),
            "fingerprint": _fingerprint(recipe),
        },
        "model": {"id": model_id, "fingerprint": selected_model_fingerprint},
        "executionEvidence": execution_evidence,
        "input": input_binding,
        "output": output_binding,
    }
    if prompt_source is not None:
        bindings["promptSource"] = prompt_source
    return bindings


def _canonical_ordinary_asset_approval_bindings(
    asset: dict[str, Any],
) -> dict[str, Any]:
    metadata = _asset_metadata(asset)
    lineage = metadata.get("generatedAssetLineage")
    lineage = lineage if isinstance(lineage, dict) else {}
    render = metadata.get("staticMp4Render")
    render = render if isinstance(render, dict) else {}
    source = lineage.get("source")
    source = source if isinstance(source, dict) else {}
    input_binding = _verify_bound_file(
        {
            "path": render.get("stillPath") or source.get("parentStillPath"),
            "sha256": source.get("parentStillHash"),
        },
        "canonical_input",
    )
    output_binding = _verify_bound_file(
        {
            "path": asset.get("output_path")
            or asset.get("campaign_path")
            or asset.get("filePath"),
            "sha256": asset.get("content_hash") or asset.get("contentHash"),
        },
        "canonical_output",
    )
    identity = {
        "creatorModel": str(
            asset.get("creator_model")
            or asset.get("model_slug")
            or asset.get("source_asset_id")
            or "unknown_creator"
        ),
        "sourceAssetId": asset.get("source_asset_id") or asset.get("sourceAssetId"),
    }
    intent = {
        "contentIntent": metadata.get("contentIntent"),
        "contentSurface": asset.get("content_surface") or asset.get("contentSurface"),
    }
    recipe = {
        "recipe": str(asset.get("recipe") or "deterministic_render"),
        "lineage": lineage,
    }
    generation = lineage.get("generation")
    tool = generation.get("tool") if isinstance(generation, dict) else recipe["recipe"]
    model = {"tool": tool, "render": render}
    admission_fingerprint = _fingerprint(
        lineage
        or {
            "input": input_binding,
            "output": output_binding,
            "recipe": recipe["recipe"],
        }
    )
    return {
        "renderedAsset": {
            "id": _required_text(
                asset.get("id") or asset.get("renderedAssetId"),
                "rendered_asset_id",
            ),
            "fingerprint": rendered_asset_approval_fingerprint(asset),
        },
        "creatorIdentity": {
            "id": _required_text(identity["creatorModel"], "creator_identity_id"),
            "fingerprint": _fingerprint(identity),
        },
        "contentIntent": {
            "id": _required_text(
                metadata.get("contentIntent") or recipe["recipe"],
                "content_intent_id",
            ),
            "fingerprint": _fingerprint(intent),
        },
        "generationRecipe": {
            "id": _required_text(recipe["recipe"], "generation_recipe_id"),
            "fingerprint": _fingerprint(recipe),
        },
        "model": {
            "id": "local_" + str(tool or recipe["recipe"]).replace(".", "_"),
            "fingerprint": _fingerprint(model),
        },
        "executionEvidence": {
            "class": "local_model",
            "admission": {
                "id": "asset-lineage-" + admission_fingerprint[:24],
                "fingerprint": admission_fingerprint,
            },
        },
        "input": input_binding,
        "output": output_binding,
    }


def creative_export_projection(
    draft: dict[str, Any],
    *,
    campaign_slug: str,
    prompt_source: dict[str, str] | None = None,
) -> dict[str, Any]:
    return _creative_export_projection(
        draft,
        campaign_slug=campaign_slug,
        schema=EXPORT_PROJECTION_SCHEMA,
        prompt_source=prompt_source,
    )


def validate_approval_for_draft(
    approval: dict[str, Any], draft: dict[str, Any], *, campaign_slug: str
) -> dict[str, Any]:
    validated = validate_creative_approval_v2(approval)
    projection = creative_export_projection(
        draft,
        campaign_slug=campaign_slug,
        prompt_source=(
            validated.get("promptSource")
            if isinstance(validated.get("promptSource"), dict)
            else None
        ),
    )
    if validated["exportProjection"] != projection:
        raise CreativeApprovalError("creative_approval_export_projection_mismatch")
    semantics = validated["contentSemantics"]
    audio_intent = draft.get("audioIntent") or {}
    expected_semantics = {
        "burnedOverlayText": draft.get("burnedCaptionText"),
        "instagramPostCaption": draft.get("instagramPostCaption"),
        "generatedAudio": audio_intent.get("generatedAudio")
        if isinstance(audio_intent, dict)
        else None,
        "sourceAudio": audio_intent.get("sourceAudio")
        if isinstance(audio_intent, dict)
        else None,
        "nativeInstagramAudio": audio_intent.get("nativeInstagramAudio")
        if isinstance(audio_intent, dict)
        else None,
    }
    if semantics != expected_semantics:
        raise CreativeApprovalError("creative_approval_content_semantics_mismatch")
    return {"approval": validated, "projection": projection}


def _operator_media_review_receipt(
    decision: dict[str, Any],
    *,
    rendered_asset_id: str,
    final_sha256: str,
    review_manifest_sha256: str,
    reviewed_by: str,
    reviewed_at: str,
) -> dict[str, Any]:
    return _operator_media_review_receipt_impl(
        decision,
        rendered_asset_id=rendered_asset_id,
        final_sha256=final_sha256,
        review_manifest_sha256=review_manifest_sha256,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        schema=OPERATOR_MEDIA_REVIEW_SCHEMA,
    )


def _validate_operator_media_review(
    binding: Any,
    *,
    rendered_asset_id: str,
    final_sha256: str,
    review_manifest_sha256: str,
    approved_by: str,
    approved_at: datetime,
) -> dict[str, Any]:
    return _validate_operator_media_review_impl(
        binding,
        rendered_asset_id=rendered_asset_id,
        final_sha256=final_sha256,
        review_manifest_sha256=review_manifest_sha256,
        approved_by=approved_by,
        approved_at=approved_at,
        schema=OPERATOR_MEDIA_REVIEW_SCHEMA,
    )


def build_and_record_creative_approval_v2(
    factory: Any,
    *,
    campaign_slug: str,
    rendered_asset_id: str,
    user_id: str,
    approved_by: str,
    review_decision: dict[str, Any],
    root: Path,
    surface: str = "regular_reel",
    publish_mode: str | None = None,
) -> dict[str, Any]:
    """Build, attest, validate, and persist one ordinary operator approval.

    The review draft is generated by Campaign Factory in dry-run mode. This
    function never calls a provider, uploads media, schedules, or publishes.
    """

    operator = _required_text(approved_by, "approved_by")
    campaign = factory.domains.campaign_by_slug(campaign_slug)
    asset = factory.domains.publishability.rendered_asset(rendered_asset_id)
    if str(asset.get("campaign_id") or "") != str(campaign["id"]):
        raise CreativeApprovalError("creative_approval_asset_campaign_mismatch")
    current_audit = factory.domains.publishability.latest_audit_for_asset(
        rendered_asset_id
    )
    if not isinstance(current_audit, dict) or current_audit.get(
        "subjectSha256"
    ) != asset.get("content_hash"):
        raise CreativeApprovalError("creative_approval_current_sha_audit_missing")
    canonical = canonical_asset_approval_bindings(asset)
    report_path = Path(
        str(current_audit.get("reportPath") or current_audit.get("report_path") or "")
    ).expanduser()
    try:
        final_audit_receipt = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CreativeApprovalError(
            "creative_approval_final_artifact_audit_invalid"
        ) from exc
    if not isinstance(final_audit_receipt, dict) or final_audit_receipt.get(
        "subjectSha256"
    ) != asset.get("content_hash"):
        raise CreativeApprovalError("creative_approval_final_artifact_audit_invalid")
    final_audit_binding = _write_content_addressed_json(
        root,
        label="registered_final_artifact_audit",
        payload=final_audit_receipt,
    )
    qc_evidence = [
        {
            "checkId": FINAL_ARTIFACT_AUDIT_POLICY_ID,
            "receiptPath": final_audit_binding["path"],
            "receiptSha256": final_audit_binding["sha256"],
            "subjectSha256": canonical["output"]["sha256"],
            "passed": True,
        }
    ]
    if _is_motion_generation_asset(asset):
        gate = factory.domains.publishability.motion_qc_gate(asset)
        if gate.get("failures"):
            raise CreativeApprovalError(
                "creative_approval_motion_qc_blocked:"
                + ",".join(str(value) for value in gate["failures"])
            )
        row = factory.domains.publishability.latest_motion_qc_receipt(rendered_asset_id)
        if row is None:
            raise CreativeApprovalError("creative_approval_motion_qc_missing")
        try:
            receipt = json.loads(row["receipt_json"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise CreativeApprovalError("creative_approval_motion_qc_invalid") from exc
        if not isinstance(receipt, dict):
            raise CreativeApprovalError("creative_approval_motion_qc_invalid")
        motion_qc_binding = _write_content_addressed_json(
            root, label="registered_motion_qc", payload=receipt
        )
        if motion_qc_binding["sha256"] != row.get("receipt_sha256"):
            raise CreativeApprovalError("creative_approval_motion_qc_registry_mismatch")
        qc_evidence.append(
            {
                "checkId": MOTION_QC_POLICY_ID,
                "receiptPath": motion_qc_binding["path"],
                "receiptSha256": motion_qc_binding["sha256"],
                "subjectSha256": canonical["output"]["sha256"],
                "passed": True,
            }
        )

    from .adapters.threadsdash_draft_delivery import export_threadsdash

    review_export = export_threadsdash(
        factory,
        campaign_slug=campaign_slug,
        user_id=_required_text(user_id, "user_id"),
        dry_run=True,
        max_drafts=1,
        rendered_asset_ids=[rendered_asset_id],
        surface=surface,
        schedule_mode="draft",
        publish_mode=publish_mode,
        review_only=True,
    )
    payload = review_export.get("payload")
    if not isinstance(payload, dict):
        raise CreativeApprovalError("creative_approval_review_payload_missing")
    drafts = payload.get("drafts")
    matching = [
        value
        for value in (drafts or [])
        if isinstance(value, dict) and value.get("renderedAssetId") == rendered_asset_id
    ]
    if len(matching) != 1 or len(drafts or []) != 1:
        raise CreativeApprovalError("creative_approval_review_draft_not_exact")
    draft = matching[0]
    approved_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    manifest_core = {
        "schema": REVIEW_MANIFEST_SCHEMA,
        "generatedAt": approved_at,
        "campaign": {"id": str(campaign["id"]), "slug": str(campaign["slug"])},
        "renderedAsset": canonical["renderedAsset"],
        "promptSource": canonical.get("promptSource"),
        "draftPayloadSchema": payload.get("schema"),
        "draft": draft,
        "providerCalls": 0,
        "productionWrites": 0,
    }
    manifest = {
        **manifest_core,
        "manifestFingerprint": _fingerprint(manifest_core),
    }
    manifest_binding = _write_content_addressed_json(
        root, label="review_manifests", payload=manifest
    )
    review_receipt = _operator_media_review_receipt(
        review_decision,
        rendered_asset_id=rendered_asset_id,
        final_sha256=canonical["output"]["sha256"],
        review_manifest_sha256=manifest_binding["sha256"],
        reviewed_by=operator,
        reviewed_at=approved_at,
    )
    review_binding = _write_content_addressed_json(
        root, label="operator_media_reviews", payload=review_receipt
    )
    projection = creative_export_projection(
        draft,
        campaign_slug=campaign_slug,
        prompt_source=(
            canonical.get("promptSource")
            if isinstance(canonical.get("promptSource"), dict)
            else None
        ),
    )
    audio_intent = draft.get("audioIntent")
    audio_intent = audio_intent if isinstance(audio_intent, dict) else {}
    approval_core = {
        "schema": SCHEMA_V2,
        "approvalId": (
            "creative-approval-"
            + _fingerprint(
                {
                    "renderedAsset": canonical["renderedAsset"],
                    "reviewManifest": manifest_binding,
                    "operatorReview": review_binding,
                    "approvedBy": operator,
                    "approvedAt": approved_at,
                }
            )[:24]
        ),
        "approvedBy": operator,
        "approvedAt": approved_at,
        "campaign": {"id": str(campaign["id"]), "slug": str(campaign["slug"])},
        **canonical,
        "qcEvidence": qc_evidence,
        "reviewManifest": manifest_binding,
        "operatorReview": review_binding,
        "exportProjection": projection,
        "contentSemantics": {
            "burnedOverlayText": draft.get("burnedCaptionText"),
            "instagramPostCaption": draft.get("instagramPostCaption"),
            "generatedAudio": audio_intent.get("generatedAudio"),
            "sourceAudio": audio_intent.get("sourceAudio"),
            "nativeInstagramAudio": audio_intent.get("nativeInstagramAudio"),
        },
    }
    attested_payload = {
        **approval_core,
        "approvalFingerprint": _fingerprint(approval_core),
    }
    approval = {
        **attested_payload,
        "operatorAttestation": sign_evidence_attestation(
            attested_payload,
            issuer=APPROVAL_ATTESTATION_ISSUER,
            issued_at=approved_at,
            secret=load_evidence_secret(),
        ),
    }
    validate_approval_for_draft(approval, draft, campaign_slug=campaign_slug)
    approval_path = CreativeApprovalStore(root).record(approval)
    local_campaign_writes = 0
    if str(asset.get("review_state") or "") != "approved":
        factory.domains.finished_video.approve_rendered_asset(
            rendered_asset_id,
            notes=f"creative_approval_v2:{approval['approvalId']}",
            require_safe_audit=True,
        )
        local_campaign_writes = 1
    return {
        "schema": "campaign_factory.creative_approval_built.v2",
        "approvalId": approval["approvalId"],
        "approvalFingerprint": approval["approvalFingerprint"],
        "approvalPath": str(approval_path),
        "reviewManifest": manifest_binding,
        "operatorReview": review_binding,
        "renderedAssetId": rendered_asset_id,
        "executionClass": approval["executionEvidence"]["class"],
        "providerCalls": 0,
        "productionWrites": 0,
        "localCampaignWrites": local_campaign_writes,
        "schedulingAllowed": False,
        "publishingAllowed": False,
    }


class CreativeApprovalStore:
    """Content-addressed approvals beside Campaign evidence, without a new database."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self._lock = self.root / "creative_approvals"

    def record(self, payload: dict[str, Any]) -> Path:
        if payload.get("schema") != SCHEMA_V2:
            raise CreativeApprovalError("creative_approval_v1_read_only")
        if self.root.exists() and self.root.is_symlink():
            raise CreativeApprovalError("creative_approval_directory_unsafe")
        approval = validate_creative_approval_v2(payload)
        path = self.root / f"{approval['approvalId']}.json"
        with file_lock(self._lock):
            if path.exists():
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or json.loads(path.read_text(encoding="utf-8")) != approval
                ):
                    raise CreativeApprovalError("creative_approval_identity_collision")
                return path
            atomic_write_json(path, approval)
            validate_creative_approval_v2(json.loads(path.read_text(encoding="utf-8")))
        return path

    def legacy_inventory(self) -> dict[str, Any]:
        """Classify historical v1 records without treating them as approvals.

        V1 does not bind the campaign, rendered-asset identity, generation recipe,
        Router decision, execution evidence, exact export projection, or operator
        attestation required by v2.  Those facts cannot be inferred safely, so the
        only honest migration is to preserve the record as non-operational evidence
        and require a new v2 approval for the current exact asset.
        """

        if self.root.exists() and self.root.is_symlink():
            raise CreativeApprovalError("creative_approval_directory_unsafe")
        records: list[dict[str, Any]] = []
        unsafe_paths: list[str] = []
        if self.root.exists():
            for path in sorted(self.root.glob("*.json")):
                if path.is_symlink() or not path.is_file():
                    unsafe_paths.append(str(path.absolute()))
                    continue
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
                    continue
                try:
                    validate_creative_approval(raw)
                    validity = "valid_historical_v1"
                except CreativeApprovalError:
                    validity = "invalid_historical_v1"
                records.append(
                    {
                        "approvalId": str(raw.get("approvalId") or ""),
                        "path": str(path.resolve()),
                        "fileSha256": _sha256_file(path),
                        "classification": validity,
                        "operationallyEligible": False,
                        "automaticallyMigratable": False,
                        "blockingReason": "creative_approval_v1_not_operational",
                        "missingV2Bindings": [
                            "campaign",
                            "renderedAsset",
                            "generationRecipe",
                            "routerDecision",
                            "executionEvidence",
                            "reviewManifest",
                            "exportProjection",
                            "operatorAttestation",
                        ],
                    }
                )
        core = {
            "schema": LEGACY_INVENTORY_SCHEMA,
            "records": records,
            "summary": {
                "historicalV1Records": len(records),
                "operationallyEligible": 0,
                "automaticallyMigratable": 0,
                "unsafeJsonPaths": len(unsafe_paths),
            },
            "unsafePaths": unsafe_paths,
        }
        return {**core, "inventoryFingerprint": _fingerprint(core)}

    def status_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        rendered_asset_id = str(asset.get("id") or asset.get("renderedAssetId") or "")
        matching: list[dict[str, Any]] = []
        invalid = False
        matching_legacy: list[dict[str, str]] = []
        try:
            canonical_bindings = canonical_asset_approval_bindings(asset)
        except CreativeApprovalError:
            return {
                "state": "invalid",
                "blockingReason": "creative_approval_canonical_asset_invalid",
            }
        if not self.root.exists():
            return {"state": "missing", "blockingReason": "creative_approval_missing"}
        if self.root.is_symlink():
            return {
                "state": "invalid",
                "blockingReason": "creative_approval_directory_unsafe",
            }
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                invalid = True
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict):
                continue
            if raw.get("schema") == SCHEMA:
                legacy_output = raw.get("output")
                canonical_output = canonical_bindings.get("output")
                if (
                    isinstance(legacy_output, dict)
                    and isinstance(canonical_output, dict)
                    and legacy_output.get("path") == canonical_output.get("path")
                    and legacy_output.get("sha256") == canonical_output.get("sha256")
                ):
                    matching_legacy.append(
                        {
                            "approvalId": str(raw.get("approvalId") or ""),
                            "path": str(path.resolve()),
                        }
                    )
                continue
            binding = raw.get("renderedAsset")
            if not isinstance(binding, dict) or binding.get("id") != rendered_asset_id:
                continue
            try:
                approval = validate_creative_approval_v2(raw)
            except CreativeApprovalError:
                invalid = True
                continue
            if approval["campaign"]["id"] != (
                asset.get("campaign_id") or asset.get("campaignId")
            ):
                continue
            if any(
                approval.get(field) != expected
                for field, expected in canonical_bindings.items()
            ):
                invalid = True
                continue
            created_at = asset.get("created_at") or asset.get("createdAt")
            if created_at is not None and _timestamp(
                approval.get("approvedAt"), "approved_at"
            ) < _timestamp(created_at, "asset_created_at"):
                invalid = True
                continue
            matching.append(approval)
        if len(matching) > 1:
            return {
                "state": "ambiguous",
                "blockingReason": "creative_approval_ambiguous",
            }
        if len(matching) == 1:
            approval = matching[0]
            return {
                "state": "approved",
                "approvalId": approval["approvalId"],
                "approvalFingerprint": approval["approvalFingerprint"],
                "approval": approval,
            }
        if matching_legacy and not invalid:
            return {
                "state": "legacy_unmigrated",
                "blockingReason": "creative_approval_v1_not_operational",
                "historicalRecords": matching_legacy,
            }
        return {
            "state": "invalid" if invalid else "missing",
            "blockingReason": (
                "creative_approval_invalid" if invalid else "creative_approval_missing"
            ),
        }


def load_creative_approval(path: Path) -> dict[str, Any]:
    candidate = path.expanduser()
    if candidate.is_symlink():
        raise CreativeApprovalError("creative_approval_missing_or_unsafe")
    resolved = candidate.resolve()
    if not resolved.is_file():
        raise CreativeApprovalError("creative_approval_missing_or_unsafe")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CreativeApprovalError("creative_approval_invalid_json") from exc
    if not isinstance(payload, dict):
        raise CreativeApprovalError("creative_approval_invalid_json")
    return validate_creative_approval(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    try:
        approval = load_creative_approval(args.approval)
        if args.root is None:
            from .config import get_settings

            root = get_settings().creative_approvals_dir
        else:
            root = args.root
        path = CreativeApprovalStore(root).record(approval)
    except (CreativeApprovalError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "schema": "campaign_factory.creative_approval_recorded.v1",
                "approvalId": approval["approvalId"],
                "approvalFingerprint": approval["approvalFingerprint"],
                "path": str(path),
                "productionWrites": 0,
                "providerCalls": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
