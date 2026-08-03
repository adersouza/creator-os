from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pipeline_contracts import schema_path, validate_visual_derivative_receipt

from ..persistence import utc_now

_SHA256 = set("0123456789abcdef")
_ALLOWED_OBSERVED_PROFILES = {
    "mirror_crop_tone": "ofm",
    "opening_trim": "ofm",
    "tilt_crop_dark": "spoofzy",
}


def canonical_fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()


def handoff_idempotency_key(export_id: str) -> str:
    export_id = str(export_id or "").strip()
    if not export_id:
        raise ValueError("draft handoff requires a stable export ID")
    return f"campaign-factory-export:{export_id}"


def contract_binding(schema: str) -> dict[str, Any]:
    version = str(schema).rsplit(".v", 1)[-1]
    schema_file = schema_path(f"campaign_draft_payload.v{version}.schema.json")
    registry_file = schema_file.parent.parent / "ownership_registry.v1.json"
    registry = json.loads(registry_file.read_text(encoding="utf-8"))
    package = registry["contractPackage"]
    return {
        "schemaName": schema,
        "schemaVersion": version,
        "producerPackage": package["name"],
        "producerPackageVersion": package["version"],
        "contractFingerprint": hashlib.sha256(schema_file.read_bytes()).hexdigest(),
        "ownershipRegistrySchema": registry["schema"],
        "ownershipRegistryVersion": registry["version"],
        "ownershipRegistryFingerprint": hashlib.sha256(
            registry_file.read_bytes()
        ).hexdigest(),
    }


def creative_approval_evidence(approval: Any) -> dict[str, Any] | None:
    if not isinstance(approval, dict):
        return None
    if approval.get("schema") != "campaign_factory.creative_approval.v2":
        return None
    output = approval.get("output")
    projection = approval.get("exportProjection")
    rendered_asset = approval.get("renderedAsset")
    evidence = {
        "schema": str(approval.get("schema") or ""),
        "approvalId": str(approval.get("approvalId") or ""),
        "approvalFingerprint": str(approval.get("approvalFingerprint") or ""),
        "approvedFinalSha256": (
            str(output.get("sha256") or "") if isinstance(output, dict) else ""
        ),
        "renderedAssetId": (
            str(rendered_asset.get("id") or "")
            if isinstance(rendered_asset, dict)
            else ""
        ),
        "exportProjectionFingerprint": (
            str(projection.get("fingerprint") or "")
            if isinstance(projection, dict)
            else ""
        ),
    }
    if not evidence["approvalId"] or any(
        len(str(evidence[key])) != 64 or not set(str(evidence[key]).lower()) <= _SHA256
        for key in (
            "approvalFingerprint",
            "approvedFinalSha256",
            "exportProjectionFingerprint",
        )
    ):
        raise ValueError("creative approval export evidence is incomplete")
    return evidence


def media_preparation_evidence(
    asset: dict[str, Any], *, final_sha256: str
) -> dict[str, Any]:
    """Return path-free preparation proof bound to the exact final bytes."""
    metadata = asset.get("_metadata")
    if not isinstance(metadata, dict):
        raise ValueError("media preparation evidence is missing")
    reference = metadata.get("visualDerivativeReceipt")
    if not isinstance(reference, dict):
        return _exact_final_media_evidence(metadata, final_sha256=final_sha256)
    receipt_path = Path(str(reference.get("path") or "")).expanduser().resolve()
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ValueError("media preparation receipt file is unavailable")
    receipt_bytes = receipt_path.read_bytes()
    receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
    if receipt_sha256 != str(reference.get("sha256") or "").lower():
        raise ValueError("media preparation receipt SHA-256 mismatch")
    receipt = json.loads(receipt_bytes)
    validate_visual_derivative_receipt(receipt)
    profile = receipt["profile"]
    profile_id = str(profile["id"])
    observed_source = str(profile["observedSource"])
    if _ALLOWED_OBSERVED_PROFILES.get(profile_id) != observed_source:
        raise ValueError("media preparation profile is not OFM/Spoofzy observed")
    if metadata.get("observedProfile") != f"{profile_id}@{profile['version']}":
        raise ValueError("media preparation profile binding mismatch")
    normalized_final_sha = str(final_sha256 or "").lower()
    profile_output_sha = str(reference.get("outputSha256") or "").lower()
    accepted = next(
        (
            item
            for item in receipt["accepted"]
            if str(item["output"]["sha256"]).lower() == profile_output_sha
            and item["qc"].get("status") == "passed"
            and not item["qc"].get("blockingCodes")
        ),
        None,
    )
    if accepted is None:
        raise ValueError("profile output is not accepted by the preparation receipt")
    if (
        int(reference.get("acceptedIndex") or 0) != accepted["acceptedIndex"]
        or str(reference.get("sourceSha256") or "").lower()
        != str(receipt["source"]["sha256"]).lower()
        or str(reference.get("toolchainFingerprint") or "").lower()
        != str(receipt["toolchain"]["fingerprint"]).lower()
    ):
        raise ValueError("media preparation receipt metadata is inconsistent")
    post_process_chain: list[dict[str, Any]] = []
    current_sha = profile_output_sha
    caption_receipt = metadata.get("captionRenderReceipt")
    if isinstance(caption_receipt, dict):
        caption_input = str(caption_receipt.get("replacesSha256") or "").lower()
        caption_output = str(caption_receipt.get("outputSha256") or "").lower()
        if caption_input != current_sha or not _is_sha256(caption_output):
            raise ValueError("caption render is not bound to the prepared media")
        post_process_chain.append(
            {
                "type": "caption_render",
                "inputSha256": caption_input,
                "outputSha256": caption_output,
                "receiptSha256": canonical_fingerprint(caption_receipt),
            }
        )
        current_sha = caption_output
    audio_receipt = metadata.get("audioEmbeddingReceipt")
    if isinstance(audio_receipt, dict):
        original = audio_receipt.get("originalVideo")
        final = audio_receipt.get("finalVideo")
        audio_input = (
            str(original.get("sha256") or "").lower()
            if isinstance(original, dict)
            else ""
        )
        audio_output = (
            str(final.get("sha256") or "").lower() if isinstance(final, dict) else ""
        )
        verification = audio_receipt.get("verification")
        if (
            audio_receipt.get("schema") != "creator_os.audio_embedding_receipt.v1"
            or audio_input != current_sha
            or not _is_sha256(audio_output)
            or not isinstance(verification, dict)
            or verification.get("status") != "verified"
        ):
            raise ValueError("audio embedding is not bound to the prepared media")
        post_process_chain.append(
            {
                "type": "audio_embedding",
                "inputSha256": audio_input,
                "outputSha256": audio_output,
                "receiptSha256": canonical_fingerprint(audio_receipt),
            }
        )
        current_sha = audio_output
    if current_sha != normalized_final_sha:
        raise ValueError("final media bytes are not bound to the preparation lineage")
    return {
        "schema": "creator_os.media_preparation_evidence.v1",
        "method": "observed_profile",
        "observedSource": observed_source,
        "profileId": profile_id,
        "profileVersion": profile["version"],
        "definitionSha256": str(profile["definitionSha256"]).lower(),
        "receiptSha256": receipt_sha256,
        "sourceSha256": str(receipt["source"]["sha256"]).lower(),
        "profileOutputSha256": profile_output_sha,
        "outputSha256": normalized_final_sha,
        "toolchainFingerprint": str(receipt["toolchain"]["fingerprint"]).lower(),
        "acceptedIndex": accepted["acceptedIndex"],
        "qcStatus": "passed",
        "postProcessChain": post_process_chain,
    }


def _exact_final_media_evidence(
    metadata: dict[str, Any], *, final_sha256: str
) -> dict[str, Any]:
    audit = metadata.get("exactFinalAudit")
    if not isinstance(audit, dict):
        raise ValueError("media preparation receipt is missing")
    output_sha = str(final_sha256 or "").lower()
    subject_sha = str(audit.get("auditSubjectSha256") or "").lower()
    report_sha = str(audit.get("auditReportSha256") or "").lower()
    if (
        not _is_sha256(output_sha)
        or subject_sha != output_sha
        or not _is_sha256(report_sha)
        or str(audit.get("auditStatus") or "").lower()
        not in {"pass", "passed", "approved", "approved_candidate"}
        or str(audit.get("auditOverallVerdict") or "").lower() != "pass"
        or not str(audit.get("auditReportId") or "").strip()
    ):
        raise ValueError("exact-final audit is not bound to the final media")
    return {
        "schema": "creator_os.media_preparation_evidence.v1",
        "method": "exact_final",
        "outputSha256": output_sha,
        "auditReportId": str(audit["auditReportId"]),
        "auditReportSha256": report_sha,
        "auditSubjectSha256": subject_sha,
        "auditStatus": str(audit["auditStatus"]).lower(),
        "auditOverallVerdict": "pass",
        "qcStatus": "passed",
        "postProcessChain": [],
    }


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and set(value) <= _SHA256


def attach_handoff_evidence(
    draft: dict[str, Any],
    *,
    schema: str,
    campaign_id: str,
    source_asset_id: str | None,
) -> None:
    export_id = str(draft.get("campaignFactoryExportId") or "")
    if not export_id:
        return
    record_id = str(draft.get("campaignFactoryDraftKey") or "")
    rendered_asset_id = str(draft.get("renderedAssetId") or "")
    final_sha256 = str(draft.get("contentHash") or "")
    approval = creative_approval_evidence(
        (draft.get("publishability") or {}).get("creativeApproval")
        if isinstance(draft.get("publishability"), dict)
        else None
    )
    bridge = {
        "schema": "creator_os.threadsdashboard_handoff_intent.v1",
        "exportId": export_id,
        "idempotencyKey": handoff_idempotency_key(export_id),
        "campaignId": campaign_id,
        "renderedAssetId": rendered_asset_id,
        "sourceAssetId": source_asset_id,
        "finalContentSha256": final_sha256,
        "mediaPreparation": draft.get("mediaPreparation"),
        "creativeApproval": approval,
        "destinationAccountId": draft.get("accountId"),
        "destinationInstagramAccountId": draft.get("instagramAccountId"),
        "requestedSurface": draft.get("distributionSurface"),
        "contentSurface": draft.get("contentSurface"),
        "inventoryReservationId": draft.get("inventoryReservationId"),
        "contract": contract_binding(schema),
        "sourceSystem": "creator_os",
        "owningSystem": "threadsdashboard",
        "recordType": "draft_handoff_intent",
        "recordId": record_id,
        "observedAt": utc_now(),
    }
    bridge["handoffFingerprint"] = canonical_fingerprint(bridge)
    metadata = draft.get("metadata") if isinstance(draft.get("metadata"), dict) else {}
    campaign_factory = (
        metadata.get("campaign_factory")
        if isinstance(metadata.get("campaign_factory"), dict)
        else {}
    )
    campaign_factory["creative_approval"] = approval
    campaign_factory["handoff_evidence"] = bridge
    campaign_factory["ownership"] = {
        "sourceSystem": "creator_os",
        "owningSystem": "threadsdashboard",
        "recordType": "draft_handoff_intent",
        "recordId": record_id,
        "schemaVersion": 1,
        "observedAt": bridge["observedAt"],
    }
    metadata["campaign_factory"] = campaign_factory
    draft["metadata"] = metadata
    draft["handoffEvidence"] = bridge


def shared_handoff_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove producer-private paths and helper fields before signing the request."""

    def sanitize(value: Any, key: str | None = None) -> Any:
        if key and key.startswith("_"):
            return None
        if key == "creativeApproval":
            return creative_approval_evidence(value)
        if isinstance(value, dict):
            return {
                child_key: sanitize(child_value, child_key)
                for child_key, child_value in value.items()
                if not child_key.startswith("_")
            }
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        if isinstance(value, str) and Path(value).is_absolute():
            return Path(value).name
        return value

    return sanitize(payload)
