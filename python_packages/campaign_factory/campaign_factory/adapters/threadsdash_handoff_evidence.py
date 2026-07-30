from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pipeline_contracts import schema_path

from ..persistence import utc_now

_SHA256 = set("0123456789abcdef")


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
