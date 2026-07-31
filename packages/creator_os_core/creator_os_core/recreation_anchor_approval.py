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

SCHEMA: Final = "creator_os.recreation_anchor_approval.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RECEIPT_FIELDS: Final = {
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
    creator_image_sha256: str,
    reference_video_sha256: str,
    selected_composition_frame_sha256: str,
    approved_by: str,
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
    core = {
        "schema": SCHEMA,
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
        "creatorImageSha256": _sha(creator_image_sha256, "creator image sha256"),
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
    expected_creator_image_sha256: str,
    expected_reference_video_sha256: str,
    expected_prompt_pack_fingerprint: str,
    expected_anchor_file: Path | None = None,
) -> dict[str, Any]:
    """Validate the receipt and its exact anchor bytes against one request."""

    receipt = inspect_recreation_anchor_approval(path)
    if (
        receipt.get("creator") != expected_creator.strip().lower()
        or receipt.get("soulId") != expected_soul_id
        or receipt.get("creatorImageSha256")
        != _sha(expected_creator_image_sha256, "creator image sha256")
        or receipt.get("referenceVideoSha256")
        != _sha(expected_reference_video_sha256, "reference video sha256")
        or receipt.get("promptPackFingerprint")
        != _sha(expected_prompt_pack_fingerprint, "prompt pack fingerprint")
    ):
        raise PermissionError("recreation_anchor_approval_binding_mismatch")
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
        sha_values_valid = all(
            _sha(str(receipt.get(key) or ""), key)
            for key in (
                "promptPackFingerprint",
                "anchorPromptFingerprint",
                "creatorImageSha256",
                "referenceVideoSha256",
                "selectedCompositionFrameSha256",
                "anchorFileSha256",
                "approvalFingerprint",
            )
        )
    except ValueError as exc:
        raise PermissionError("recreation_anchor_approval_invalid") from exc
    core = {
        key: value for key, value in receipt.items() if key != "approvalFingerprint"
    }
    if (
        set(receipt) != _RECEIPT_FIELDS
        or not required_values_valid
        or not sha_values_valid
        or receipt.get("schema") != SCHEMA
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
