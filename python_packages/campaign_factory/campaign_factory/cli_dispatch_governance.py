from __future__ import annotations

import hashlib
from pathlib import Path

from .cli_support import load_json_object, print_json


def dispatch_governance_commands(args, cf) -> int | None:
    if args.cmd == "creator-governance-status":
        print_json(cf.domains.creator_governance.creator_status(args.creator))
        return 0
    if args.cmd == "creator-governance-transition":
        kwargs = {
            "new_status": args.status,
            "actor": args.actor,
            "reason": args.reason,
            "evidence": load_json_object(args.evidence_json),
        }
        if not args.apply:
            kwargs["validate_only"] = True
        print_json(
            cf.domains.creator_governance.transition_creator(args.creator, **kwargs)
        )
        return 0
    if args.cmd == "creator-governance-rename":
        kwargs = {
            "new_slug": args.new_slug,
            "actor": args.actor,
            "reason": args.reason,
        }
        if not args.apply:
            kwargs["validate_only"] = True
        print_json(cf.domains.creator_governance.rename_creator(args.creator, **kwargs))
        return 0
    if args.cmd == "creator-identity-enroll":
        profile_path = Path(args.profile_json).expanduser().resolve()
        kwargs = {
            "provider": args.provider,
            "provider_identity_id": args.provider_identity_id,
            "profile": load_json_object(str(profile_path)) or {},
            "canonical_source_asset_id": args.canonical_source_asset_id,
            "identity_manifest_path": profile_path,
            "identity_manifest_sha256": hashlib.sha256(
                profile_path.read_bytes()
            ).hexdigest(),
            "operator": args.operator,
        }
        if not args.apply:
            kwargs["validate_only"] = True
        print_json(
            cf.domains.creator_governance.enroll_identity_profile(
                args.creator, **kwargs
            )
        )
        return 0
    if args.cmd == "creator-authorization-grant":
        evidence = Path(args.evidence).expanduser().resolve()
        kwargs = {
            "scope": args.scope,
            "provider": args.provider,
            "evidence_path": evidence,
            "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "actor": args.actor,
            "reason": args.reason,
            "effective_at": args.effective_at,
            "expires_at": args.expires_at,
            "territories": args.territory,
            "account_scope": args.account_id,
            "reference_video_use": args.reference_video_use,
            "training_reference_use": args.training_reference_use,
            "voice_authorized": args.voice_authorized,
            "legal_hold": args.legal_hold,
        }
        if not args.apply:
            kwargs["validate_only"] = True
        print_json(
            cf.domains.creator_governance.grant_authorization(args.creator, **kwargs)
        )
        return 0
    if args.cmd == "creator-authorization-revoke":
        evidence = Path(args.evidence).expanduser().resolve()
        kwargs = {
            "actor": args.actor,
            "reason": args.reason,
            "evidence_path": evidence,
            "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        }
        if not args.apply:
            kwargs["validate_only"] = True
        print_json(
            cf.domains.creator_governance.revoke_authorization(
                args.authorization_id, **kwargs
            )
        )
        return 0
    if args.cmd == "campaign-governance-status":
        print_json(cf.domains.creator_governance.campaign_status(args.campaign))
        return 0
    if args.cmd == "campaign-governance-transition":
        kwargs = {
            "new_status": args.status,
            "actor": args.actor,
            "reason": args.reason,
            "blocker_codes": args.blocker_code,
            "evidence": load_json_object(args.evidence_json) or {},
            "related_ids": args.related_id,
        }
        if not args.apply:
            kwargs["validate_only"] = True
        print_json(
            cf.domains.creator_governance.transition_campaign(args.campaign, **kwargs)
        )
        return 0
    return None
