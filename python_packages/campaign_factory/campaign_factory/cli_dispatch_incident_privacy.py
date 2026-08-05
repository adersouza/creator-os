from __future__ import annotations

import json

from .cli_support import load_json_object, print_json


def dispatch_incident_privacy_commands(args, cf) -> int | None:
    if args.cmd == "incident-report":
        print_json(cf.domains.incidents.report(args.incident_id))
        return 0
    if args.cmd == "incident-create":
        payload = {
            "category": args.category,
            "severity": args.severity,
            "domain_owner": args.domain_owner,
            "owner": args.owner,
            "next_action": args.next_action,
            "operator": args.operator,
            "model_id": args.creator_id,
            "campaign_id": args.campaign_id,
            "affected_assets": args.affected_asset_id,
            "external_effect_state": args.external_effect_state,
            "financial_exposure": load_json_object(args.financial_exposure_json) or {},
            "privacy_exposure": load_json_object(args.privacy_exposure_json) or {},
        }
        print_json(
            cf.domains.incidents.create(**payload)
            if args.apply
            else {
                "schema": "campaign_factory.incident_create.preview.v1",
                "applyRequired": True,
                "request": payload,
            }
        )
        return 0
    if args.cmd == "incident-transition":
        payload = {
            "state": args.state,
            "actor": args.actor,
            "action": args.action,
            "evidence": load_json_object(args.evidence_json) or {},
            "owner": args.owner,
            "next_action": args.next_action,
            "repair_actions": (
                json.loads(args.repair_actions_json)
                if args.repair_actions_json
                else None
            ),
            "verification_evidence": (
                json.loads(args.verification_evidence_json)
                if args.verification_evidence_json
                else None
            ),
            "closure_receipt": load_json_object(args.closure_receipt_json),
        }
        print_json(
            cf.domains.incidents.transition(args.incident_id, **payload)
            if args.apply
            else {
                "schema": "campaign_factory.incident_transition.preview.v1",
                "applyRequired": True,
                "current": cf.domains.incidents.get(args.incident_id),
                "request": payload,
            }
        )
        return 0
    if args.cmd == "creator-privacy-report":
        print_json(cf.domains.creator_privacy.privacy_report(args.creator))
        return 0
    if args.cmd == "creator-privacy-request":
        payload = {
            "creator": args.creator,
            "request_type": args.request_type,
            "operator": args.operator,
            "legal_basis": args.legal_basis,
            "deletion_scope": load_json_object(args.deletion_scope_json) or {},
            "retention_policy": load_json_object(args.retention_policy_json) or {},
            "effective_at": args.effective_at,
        }
        print_json(
            cf.domains.creator_privacy.create_request(**payload)
            if args.apply
            else {
                "schema": "campaign_factory.creator_privacy_request.preview.v1",
                "applyRequired": True,
                "request": payload,
            }
        )
        return 0
    if args.cmd == "creator-privacy-transition":
        payload = {
            "state": args.state,
            "actor": args.actor,
            "action": args.action,
            "evidence": load_json_object(args.evidence_json) or {},
            "verification_receipt": load_json_object(args.verification_receipt_json),
            "closure_receipt": load_json_object(args.closure_receipt_json),
        }
        print_json(
            cf.domains.creator_privacy.transition_request(args.request_id, **payload)
            if args.apply
            else {
                "schema": "campaign_factory.creator_privacy_transition.preview.v1",
                "applyRequired": True,
                "current": cf.domains.creator_privacy.get_request(args.request_id),
                "request": payload,
            }
        )
        return 0
    if args.cmd == "creator-privacy-verify":
        print_json(
            cf.domains.creator_privacy.verify_request(
                args.request_id, operator=args.operator
            )
            if args.apply
            else cf.domains.creator_privacy.verification_readiness(args.request_id)
        )
        return 0
    return None
