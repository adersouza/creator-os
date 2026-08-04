from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pipeline_contracts import validate_creator_identity_profile


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular_evidence_file(value: Path, label: str) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file")
    return path.resolve()


def validate_identity_manifest(identity: Any) -> dict[str, Any]:
    manifest_path = Path(str(identity["identity_manifest_path"]))
    if (
        manifest_path.is_symlink()
        or not manifest_path.is_file()
        or file_sha256(manifest_path) != identity["identity_manifest_sha256"]
    ):
        raise PermissionError("creator_identity_manifest_stale")
    try:
        manifest_profile = json.loads(manifest_path.read_text(encoding="utf-8"))
        stored_profile = json.loads(str(identity["profile_json"]))
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise PermissionError("creator_identity_manifest_stale") from exc
    if (
        not isinstance(manifest_profile, dict)
        or not isinstance(stored_profile, dict)
        or manifest_profile != stored_profile
        or canonical_sha256(stored_profile) != identity["profile_fingerprint"]
    ):
        raise PermissionError("creator_identity_manifest_stale")
    return stored_profile


def validate_profile_identity_binding(
    profile: dict[str, Any],
    *,
    creator_slug: str,
    provider: str,
    provider_identity_id: str,
) -> None:
    if profile.get("schema") != "creator_os.creator_identity_profile.v1":
        raise ValueError("creator_identity_profile_schema_invalid")
    if str(profile.get("creatorKey") or "") != creator_slug:
        raise ValueError("creator_identity_profile_creator_mismatch")
    validate_creator_identity_profile(profile)
    provider_key = provider.strip().lower()
    provider_references = [
        item
        for item in profile["identityReferences"]
        if str(item["namespace"]).lower().split(".", 1)[0] == provider_key
        and str(item["externalId"]) == provider_identity_id
    ]
    if not provider_references:
        raise ValueError("provider_identity_profile_binding_mismatch")


def validate_provider_identity_evidence(
    profile: dict[str, Any],
    *,
    evidence_path: Path,
    evidence_sha256: str,
    creator_slug: str,
    provider: str,
    provider_identity_id: str,
) -> None:
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise PermissionError("provider_identity_evidence_invalid") from exc
    if (
        not isinstance(evidence, dict)
        or evidence.get("schema") != "reel_factory.reviewed_creator_identity_facts.v1"
        or str(evidence.get("creatorKey") or "") != creator_slug
        or not str(evidence.get("reviewedBy") or "").strip()
        or not str(evidence.get("reviewedAt") or "").strip()
        or evidence.get("modelProfile") != profile.get("modelProfile")
    ):
        raise PermissionError("provider_identity_evidence_invalid")
    evidence_references = evidence.get("identityReferences")
    provider_key = provider.strip().lower()
    matching_references = [
        item
        for item in evidence_references or []
        if isinstance(item, dict)
        and str(item.get("namespace") or "").lower().split(".", 1)[0] == provider_key
        and str(item.get("externalId") or "") == provider_identity_id
    ]
    if not isinstance(evidence_references, list) or not matching_references:
        raise PermissionError("provider_identity_evidence_binding_mismatch")
    expected_model_profiles = {
        f"{str(item['namespace'])}:{provider_identity_id}"
        for item in matching_references
    }
    if str(evidence.get("modelProfile") or "") not in expected_model_profiles:
        raise PermissionError("provider_identity_evidence_binding_mismatch")
    expected_record_id = f"reviewed_identity_facts:{evidence_sha256[:24]}"
    provenance = profile.get("provenance")
    sources = (
        provenance.get("sourceReferences") if isinstance(provenance, dict) else None
    )
    if not isinstance(sources, list) or not any(
        isinstance(item, dict)
        and str(item.get("recordId") or "") == expected_record_id
        and str(item.get("fingerprint") or "") == evidence_sha256
        for item in sources
    ):
        raise ValueError("provider_identity_profile_evidence_binding_mismatch")
