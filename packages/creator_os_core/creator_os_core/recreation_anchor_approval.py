"""Exact-byte approval receipts for recreation identity anchors."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from .fileops import sha256_file as _sha256_file

SCHEMA_V1: Final = "creator_os.recreation_anchor_approval.v1"
SCHEMA_V2: Final = "creator_os.recreation_anchor_approval.v2"
SCHEMA: Final = "creator_os.recreation_anchor_approval.v3"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RECEIPT_FIELDS_V1: Final = {
    "schema",
    "creator",
    "soulId",
    "anchorGenerationId",
    "anchorModel",
    "anchorPromptPackId",
    "promptPackFingerprint",
    "anchorPromptFingerprint",
    "creatorImageSha256",
    "referenceVideoSha256",
    "selectedCompositionFrameSha256",
    "anchorFilePath",
    "anchorFileSha256",
    "anchorFileBytes",
    "anchorApprovalDecision",
    "approvedBy",
    "approvedAt",
    "approvalFingerprint",
}
_RECEIPT_FIELDS_V2: Final = _RECEIPT_FIELDS_V1 | {
    "referenceId",
    "recreationPlanFingerprint",
    "selectedRecreationMode",
    "referenceClassification",
    "referenceProviderRights",
}
_RECEIPT_FIELDS: Final = _RECEIPT_FIELDS_V2 | {"soulIdentity"}


def write_recreation_anchor_approval(
    *,
    output_dir: Path,
    creator: str,
    soul_id: str,
    anchor_generation_id: str,
    anchor_file: Path,
    prompt_pack_id: str,
    prompt_pack_fingerprint: str,
    anchor_prompt_fingerprint: str,
    creator_image_sha256: str | None,
    reference_video_sha256: str,
    selected_composition_frame_sha256: str,
    approved_by: str,
    reference_id: str | None = None,
    recreation_plan_fingerprint: str | None = None,
    selected_recreation_mode: str | None = None,
    reference_classification: str | None = None,
    reference_provider_rights: dict[str, Any] | None = None,
    soul_identity: dict[str, Any] | None = None,
    approved_at: str | None = None,
) -> dict[str, Any]:
    """Write one immutable receipt approving the exact local anchor bytes."""

    source_anchor = _regular_file(anchor_file, "anchor file")
    creator_slug = _required(creator, "creator").lower()
    anchor_sha256 = _sha256_file(source_anchor)
    anchor = _retain_exact_file(
        source_anchor,
        (
            Path(output_dir).expanduser().resolve()
            / creator_slug
            / "assets"
            / f"{anchor_sha256}{source_anchor.suffix.lower() or '.bin'}"
        ),
    )
    execution_binding_values = (
        reference_id,
        recreation_plan_fingerprint,
        selected_recreation_mode,
        reference_classification,
        reference_provider_rights,
    )
    has_execution_binding = any(value is not None for value in execution_binding_values)
    if has_execution_binding and any(
        value is None for value in execution_binding_values
    ):
        raise ValueError("recreation execution binding must be complete")
    execution_binding = (
        _validated_execution_binding(
            reference_id=str(reference_id),
            recreation_plan_fingerprint=str(recreation_plan_fingerprint),
            selected_recreation_mode=str(selected_recreation_mode),
            reference_classification=str(reference_classification),
            reference_provider_rights=dict(reference_provider_rights or {}),
            reference_video_sha256=reference_video_sha256,
        )
        if has_execution_binding
        else {}
    )
    validated_soul_identity = (
        _validated_soul_identity(
            soul_identity,
            creator=creator_slug,
            soul_id=soul_id,
        )
        if soul_identity is not None
        else None
    )
    if validated_soul_identity is not None and not has_execution_binding:
        raise ValueError("soul-bound recreation approval requires execution binding")
    core = {
        "schema": (
            SCHEMA
            if validated_soul_identity is not None
            else SCHEMA_V2
            if has_execution_binding
            else SCHEMA_V1
        ),
        "creator": creator_slug,
        "soulId": _required(soul_id, "soul id"),
        "anchorGenerationId": _required(anchor_generation_id, "anchor generation id"),
        "anchorModel": "soul_2",
        "anchorPromptPackId": _required(prompt_pack_id, "prompt pack id"),
        "promptPackFingerprint": _sha(
            prompt_pack_fingerprint, "prompt pack fingerprint"
        ),
        "anchorPromptFingerprint": _sha(
            anchor_prompt_fingerprint, "anchor prompt fingerprint"
        ),
        "creatorImageSha256": (
            None
            if validated_soul_identity is not None
            else _sha(creator_image_sha256, "creator image sha256")
        ),
        "referenceVideoSha256": _sha(reference_video_sha256, "reference video sha256"),
        "selectedCompositionFrameSha256": _sha(
            selected_composition_frame_sha256,
            "selected composition frame sha256",
        ),
        "anchorFilePath": str(anchor),
        "anchorFileSha256": anchor_sha256,
        "anchorFileBytes": anchor.stat().st_size,
        "anchorApprovalDecision": "approved",
        "approvedBy": _required(approved_by, "approved by"),
        "approvedAt": approved_at
        or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        **execution_binding,
        **(
            {"soulIdentity": validated_soul_identity}
            if validated_soul_identity is not None
            else {}
        ),
    }
    receipt = {**core, "approvalFingerprint": _fingerprint(core)}
    destination = (
        Path(output_dir).expanduser().resolve()
        / core["creator"]
        / f"{receipt['approvalFingerprint']}.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    try:
        with destination.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if destination.is_symlink():
            raise PermissionError("recreation_anchor_approval_collision") from None
        if destination.read_text(encoding="utf-8") != serialized:
            raise PermissionError("recreation_anchor_approval_collision") from None
    os.chmod(destination, 0o600)
    return {
        **receipt,
        "receiptPath": str(destination),
        "receiptSha256": _sha256_file(destination),
    }


def load_recreation_anchor_approval(
    path: Path,
    *,
    expected_creator: str,
    expected_soul_id: str,
    expected_creator_image_sha256: str | None,
    expected_reference_video_sha256: str,
    expected_prompt_pack_fingerprint: str,
    expected_anchor_file: Path | None = None,
    expected_recreation_plan_fingerprint: str | None = None,
    expected_selected_recreation_mode: str | None = None,
    expected_reference_classification: str | None = None,
    expected_reference_provider_rights_fingerprint: str | None = None,
    expected_soul_identity_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Validate the receipt and its exact anchor bytes against one request."""

    receipt = inspect_recreation_anchor_approval(path)
    if (
        receipt.get("creator") != expected_creator.strip().lower()
        or receipt.get("soulId") != expected_soul_id
        or (
            receipt.get("creatorImageSha256")
            != _sha(expected_creator_image_sha256, "creator image sha256")
            if expected_creator_image_sha256 is not None
            else receipt.get("creatorImageSha256") is not None
        )
        or receipt.get("referenceVideoSha256")
        != _sha(expected_reference_video_sha256, "reference video sha256")
        or receipt.get("promptPackFingerprint")
        != _sha(expected_prompt_pack_fingerprint, "prompt pack fingerprint")
    ):
        raise PermissionError("recreation_anchor_approval_binding_mismatch")
    if expected_soul_identity_fingerprint is not None and (
        receipt.get("schema") != SCHEMA
        or (receipt.get("soulIdentity") or {}).get("bindingFingerprint")
        != _sha(expected_soul_identity_fingerprint, "soul identity fingerprint")
    ):
        raise PermissionError("recreation_soul_identity_binding_mismatch")
    if expected_recreation_plan_fingerprint is not None and (
        receipt.get("schema") not in {SCHEMA_V2, SCHEMA}
        or receipt.get("recreationPlanFingerprint")
        != _sha(expected_recreation_plan_fingerprint, "recreation plan fingerprint")
        or receipt.get("selectedRecreationMode")
        != _required(expected_selected_recreation_mode, "selected recreation mode")
        or receipt.get("referenceClassification")
        != _required(expected_reference_classification, "reference classification")
        or (receipt.get("referenceProviderRights") or {}).get(
            "rightsEvidenceFingerprint"
        )
        != _sha(
            expected_reference_provider_rights_fingerprint,
            "reference provider rights fingerprint",
        )
    ):
        raise PermissionError("recreation_execution_plan_binding_mismatch")
    anchor = Path(str(receipt["anchorFilePath"]))
    if expected_anchor_file is not None and anchor != _regular_file(
        expected_anchor_file, "request anchor file"
    ):
        raise PermissionError("recreation_anchor_approval_path_mismatch")
    return receipt


def inspect_recreation_anchor_approval(path: Path) -> dict[str, Any]:
    """Validate one immutable receipt and its exact local anchor bytes."""

    receipt_path = _regular_file(path, "anchor approval receipt")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PermissionError("recreation_anchor_approval_invalid") from exc
    if not isinstance(receipt, dict):
        raise PermissionError("recreation_anchor_approval_invalid")
    try:
        required_values_valid = all(
            _required(str(receipt.get(key) or ""), key)
            for key in (
                "creator",
                "soulId",
                "anchorGenerationId",
                "anchorPromptPackId",
                "anchorFilePath",
                "approvedBy",
                "approvedAt",
            )
        )
        sha_keys = [
            "promptPackFingerprint",
            "anchorPromptFingerprint",
            "referenceVideoSha256",
            "selectedCompositionFrameSha256",
            "anchorFileSha256",
            "approvalFingerprint",
        ]
        if receipt.get("schema") != SCHEMA:
            sha_keys.append("creatorImageSha256")
        sha_values_valid = all(
            _sha(str(receipt.get(key) or ""), key) for key in sha_keys
        )
    except ValueError as exc:
        raise PermissionError("recreation_anchor_approval_invalid") from exc
    core = {
        key: value for key, value in receipt.items() if key != "approvalFingerprint"
    }
    schema = receipt.get("schema")
    expected_fields = (
        _RECEIPT_FIELDS
        if schema == SCHEMA
        else _RECEIPT_FIELDS_V2
        if schema == SCHEMA_V2
        else _RECEIPT_FIELDS_V1
    )
    execution_binding_valid = True
    if schema in {SCHEMA_V2, SCHEMA}:
        try:
            execution_binding_valid = bool(
                _validated_execution_binding(
                    reference_id=str(receipt.get("referenceId") or ""),
                    recreation_plan_fingerprint=str(
                        receipt.get("recreationPlanFingerprint") or ""
                    ),
                    selected_recreation_mode=str(
                        receipt.get("selectedRecreationMode") or ""
                    ),
                    reference_classification=str(
                        receipt.get("referenceClassification") or ""
                    ),
                    reference_provider_rights=dict(
                        receipt.get("referenceProviderRights") or {}
                    ),
                    reference_video_sha256=str(
                        receipt.get("referenceVideoSha256") or ""
                    ),
                )
            )
        except (TypeError, ValueError):
            execution_binding_valid = False
    if (
        set(receipt) != expected_fields
        or not required_values_valid
        or not sha_values_valid
        or schema not in {SCHEMA_V1, SCHEMA_V2, SCHEMA}
        or (
            schema == SCHEMA
            and not _valid_soul_identity_receipt(
                receipt.get("soulIdentity"),
                creator=str(receipt.get("creator") or ""),
                soul_id=str(receipt.get("soulId") or ""),
            )
        )
        or not execution_binding_valid
        or receipt.get("anchorModel") != "soul_2"
        or receipt.get("anchorApprovalDecision") != "approved"
        or not isinstance(receipt.get("anchorFileBytes"), int)
        or receipt["anchorFileBytes"] <= 0
        or receipt.get("approvalFingerprint") != _fingerprint(core)
    ):
        raise PermissionError("recreation_anchor_approval_binding_mismatch")
    anchor = _regular_file(
        Path(str(receipt.get("anchorFilePath") or "")), "approved anchor file"
    )
    if (
        receipt.get("anchorFileSha256") != _sha256_file(anchor)
        or receipt.get("anchorFileBytes") != anchor.stat().st_size
    ):
        raise PermissionError("recreation_anchor_approval_sha_mismatch")
    return {
        **receipt,
        "anchorFilePath": str(anchor),
        "receiptPath": str(receipt_path),
        "receiptSha256": _sha256_file(receipt_path),
    }


def _validated_soul_identity(
    value: dict[str, Any], *, creator: str, soul_id: str
) -> dict[str, Any]:
    if not _valid_soul_identity_receipt(value, creator=creator, soul_id=soul_id):
        raise ValueError("soul identity binding is invalid")
    return dict(value)


def _valid_soul_identity_receipt(value: Any, *, creator: str, soul_id: str) -> bool:
    if not isinstance(value, dict):
        return False
    core = {key: item for key, item in value.items() if key != "bindingFingerprint"}
    return bool(
        core.get("schema") == "campaign_factory.verified_soul_identity_binding.v1"
        and core.get("creatorSlug") == creator
        and core.get("provider") == "higgsfield"
        and core.get("soulId") == soul_id
        and str(core.get("identityProfileId") or "").strip()
        and isinstance(core.get("identityProfileVersion"), int)
        and int(core["identityProfileVersion"]) >= 1
        and _SHA256.fullmatch(str(core.get("identityProfileFingerprint") or ""))
        and value.get("bindingFingerprint") == _fingerprint(core)
    )


def _validated_execution_binding(
    *,
    reference_id: str,
    recreation_plan_fingerprint: str,
    selected_recreation_mode: str,
    reference_classification: str,
    reference_provider_rights: dict[str, Any],
    reference_video_sha256: str,
) -> dict[str, Any]:
    reference = _required(reference_id, "reference id")
    plan_fingerprint = _sha(recreation_plan_fingerprint, "recreation plan fingerprint")
    if selected_recreation_mode not in {"calm", "structural"}:
        raise ValueError("selected recreation mode must be calm or structural")
    classification = _required(reference_classification, "reference classification")
    rights = dict(reference_provider_rights)
    if (
        rights.get("schema") != "reference_factory.provider_rights_eligibility.v1"
        or rights.get("eligible") is not True
        or rights.get("referenceId") != reference
        or rights.get("provider") != "higgsfield"
        or rights.get("operation") != "recreation_generation"
        or rights.get("sourceSha256")
        != _sha(reference_video_sha256, "reference video sha256")
        or not _required(rights.get("rightsEventId"), "rights event id")
        or not _sha(
            rights.get("rightsEvidenceFingerprint"), "rights evidence fingerprint"
        )
        or not _required(rights.get("rightsExpiresAt"), "rights expiry")
    ):
        raise ValueError("reference provider rights receipt is invalid")
    return {
        "referenceId": reference,
        "recreationPlanFingerprint": plan_fingerprint,
        "selectedRecreationMode": selected_recreation_mode,
        "referenceClassification": classification,
        "referenceProviderRights": rights,
    }


def _regular_file(path: Path, label: str) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink():
        raise PermissionError(f"{label} must not be a symlink")
    resolved = raw.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def _required(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _retain_exact_file(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    try:
        with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        try:
            os.link(temporary_name, destination)
        except FileExistsError:
            if destination.is_symlink() or not destination.is_file():
                raise PermissionError("recreation_anchor_asset_collision") from None
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    if (
        _sha256_file(destination) != _sha256_file(source)
        or destination.stat().st_size != source.stat().st_size
    ):
        raise PermissionError("recreation_anchor_asset_collision")
    os.chmod(destination, 0o600)
    return destination.resolve()


def _sha(value: str, label: str) -> str:
    digest = str(value or "").strip().lower()
    if not _SHA256.fullmatch(digest):
        raise ValueError(f"{label} must be a sha256")
    return digest


def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
