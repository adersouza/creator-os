from __future__ import annotations

import hashlib
from pathlib import Path

from .cli_support import load_json_object, print_json


def dispatch_creator_governance_commands(args, cf) -> int | None:
    if args.cmd != "creator-identity-enroll":
        return None

    profile_path = Path(args.profile_json).expanduser().resolve()
    identity_profile = load_json_object(str(profile_path))
    profile_sha = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    provider_evidence_path = (
        Path(args.provider_identity_evidence).expanduser().resolve()
        if args.provider_identity_evidence
        else None
    )
    provider_evidence_sha = (
        hashlib.sha256(provider_evidence_path.read_bytes()).hexdigest()
        if provider_evidence_path is not None
        else None
    )
    enrollment = {
        "provider": args.provider,
        "provider_identity_id": args.provider_identity_id,
        "profile": identity_profile or {},
        "canonical_source_asset_id": args.canonical_source_asset_id,
        "identity_manifest_path": profile_path,
        "identity_manifest_sha256": profile_sha,
        "operator": args.operator,
        "provider_identity_evidence_path": provider_evidence_path,
        "provider_identity_evidence_sha256": provider_evidence_sha,
        "canonical_evidence_type": (
            "provider_identity_attestation"
            if provider_evidence_path is not None
            else "operator_approved_original"
        ),
    }
    if not args.apply:
        enrollment["validate_only"] = True
    print_json(
        cf.domains.creator_governance.enroll_identity_profile(
            args.creator,
            **enrollment,
        )
    )
    return 0
