"""Fail-closed registration for local Wan/LTX LoRA adapters."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .fileops import atomic_write_text
from .local_video_models import local_video_model_spec

SCHEMA = "reel_factory.local_lora_registration.v1"


def lora_receipt_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    return resolved.with_suffix(resolved.suffix + ".creator-os-lora.json")


def register_local_lora(
    path: Path,
    *,
    lora_id: str,
    compatible_model_ids: Sequence[str],
    license_id: str,
    source_repository: str,
    source_revision: str,
    apply: bool,
) -> dict[str, Any]:
    resolved = _valid_lora_path(path)
    normalized_id = str(lora_id or "").strip().lower().replace("-", "_")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]{2,79}", normalized_id):
        raise ValueError(
            "local LoRA id must be 3-80 lowercase letters, digits, or underscores"
        )
    if not compatible_model_ids:
        raise ValueError("local LoRA requires at least one compatible model")
    models: dict[str, str] = {}
    families: set[str] = set()
    for model_id in compatible_model_ids:
        spec = local_video_model_spec(model_id)
        if spec.family not in {"wan_2", "ltx_2"}:
            raise ValueError(f"{model_id} does not support registered LoRAs")
        models[spec.model_id] = spec.revision
        families.add(spec.family)
    if len(families) != 1:
        raise ValueError("one LoRA registration cannot span Wan and LTX families")
    for label, value in {
        "license_id": license_id,
        "source_repository": source_repository,
        "source_revision": source_revision,
    }.items():
        if not str(value or "").strip():
            raise ValueError(f"{label} must be explicit")
    payload = {
        "schema": SCHEMA,
        "loraId": normalized_id,
        "path": str(resolved),
        "sha256": _sha256_file(resolved),
        "sizeBytes": resolved.stat().st_size,
        "family": next(iter(families)),
        "compatibleModels": models,
        "licenseId": license_id.strip(),
        "sourceRepository": source_repository.strip(),
        "sourceRevision": source_revision.strip(),
        "manualRegistrationRequired": True,
        "automaticPromotionAllowed": False,
    }
    receipt = lora_receipt_path(resolved)
    result = {**payload, "receiptPath": str(receipt), "status": "planned"}
    if not apply:
        return result
    if receipt.exists():
        raise FileExistsError(f"local_lora_registration_collision:{receipt}")
    atomic_write_text(
        receipt,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {**result, "status": "registered"}


def verify_local_lora(path: Path, *, model_id: str) -> dict[str, Any]:
    resolved = _valid_lora_path(path)
    receipt = lora_receipt_path(resolved)
    try:
        payload = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("local_lora_registration_missing_or_invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("local_lora_registration_schema_mismatch")
    spec = local_video_model_spec(model_id)
    expected = {
        "path": str(resolved),
        "sha256": _sha256_file(resolved),
        "sizeBytes": resolved.stat().st_size,
        "family": spec.family,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"local_lora_registration_mismatch:{key}")
    compatible = payload.get("compatibleModels")
    if (
        not isinstance(compatible, dict)
        or compatible.get(spec.model_id) != spec.revision
    ):
        raise ValueError("local_lora_base_model_revision_mismatch")
    for key in ("licenseId", "sourceRepository", "sourceRevision", "loraId"):
        if not str(payload.get(key) or "").strip():
            raise ValueError(f"local_lora_registration_missing:{key}")
    return {
        **payload,
        "receiptPath": str(receipt),
        "receiptSha256": _sha256_file(receipt),
        "verified": True,
    }


def _valid_lora_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.suffix != ".safetensors":
        raise FileNotFoundError("local LoRA must be an existing .safetensors file")
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
