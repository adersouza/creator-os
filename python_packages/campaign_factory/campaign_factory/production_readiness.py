from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from creator_os_core.evidence_attestation import (
    EvidenceAttestationError,
    load_evidence_secret,
    verify_evidence_attestation,
)

from .adapters.threadsdash_draft_payload import DEFAULT_DRAFT_PAYLOAD_SCHEMA
from .adapters.threadsdash_handoff_evidence import (
    canonical_fingerprint,
    contract_binding,
)
from .asset_inventory import current_handoff_evidence_read_only
from .core import new_id, slugify, utc_now
from .creator_governance import CreatorGovernanceRepository
from .daily_orchestrator import _batch_succeeded, _planned_mode
from .derived_stills import validate_static_source_assets

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TD_DEPLOYMENT_SCHEMA = "threadsdashboard.deployment_receipt.v1"
_TD_DEPLOYMENT_ISSUER = "threadsdashboard.deployment"
_TD_REPOSITORY = "adersouza/ThreadsDashboard"
_TD_PROVIDER = "vercel"
_TD_DEPLOYMENT_MAX_AGE = timedelta(hours=1)


def build_production_readiness_proof(
    conn: sqlite3.Connection,
    *,
    creative_approvals_dir: Path,
    promotion_receipt: dict[str, Any] | None = None,
    expected_runtime_sha: str | None = None,
    threadsdash_deployment_receipt: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Prove supervised-run prerequisites without mutating production state."""

    evaluated_at = now or utc_now()
    governance = _governance_readiness(conn, now=evaluated_at)
    handoff = _handoff_readiness(conn, creative_approvals_dir=creative_approvals_dir)
    runtime = _runtime_readiness(
        conn,
        promotion_receipt=promotion_receipt,
        expected_runtime_sha=expected_runtime_sha,
    )
    threadsdash = _threadsdash_readiness(
        conn,
        handoff_assets=handoff["handoffReadyAssets"],
        deployment_receipt=threadsdash_deployment_receipt,
        now=evaluated_at,
    )
    linked_candidates = _linked_canary_candidates(
        governance=governance,
        handoff=handoff,
        runtime=runtime,
        threadsdash=threadsdash,
    )
    gates = {
        "governanceAndSources": governance["ready"],
        "exactFinalHandoff": handoff["ready"],
        "currentThreadsDashboardAcceptance": threadsdash["ready"],
        "schedulingEligibility": threadsdash["scheduleEligibleCount"] > 0,
        "postPromotionDailyOrchestrator": runtime["ready"],
        "linkedCanaryChain": bool(linked_candidates),
    }
    operator_blockers = list(
        dict.fromkeys(
            governance["blockers"]
            + handoff["blockers"]
            + threadsdash["operatorBlockers"]
            + ([] if linked_candidates else ["no_linked_canary_chain"])
        )
    )
    proof_blockers = list(
        dict.fromkeys(runtime["blockers"] + threadsdash["proofBlockers"])
    )
    return {
        "schema": "creator_os.production_readiness_proof.v1",
        "evaluatedAt": evaluated_at,
        "readyForSupervisedCanary": all(gates.values()),
        "readyForUnattendedOperation": False,
        "gates": gates,
        "operatorDataBlockers": operator_blockers,
        "runtimeProofBlockers": proof_blockers,
        "governance": governance,
        "handoff": handoff,
        "threadsdashboard": threadsdash,
        "runtime": runtime,
        "canaryCandidates": linked_candidates,
        "wouldWrite": False,
    }


def _governance_readiness(conn: sqlite3.Connection, *, now: str) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT c.id AS campaign_id, c.slug AS campaign_slug,
                   m.id AS creator_id, m.slug AS creator_slug,
                   cg.lifecycle_status, cg.blocker_codes_json,
                   cp.style_lanes_json
            FROM campaign_governance cg
            JOIN campaigns c ON c.id = cg.campaign_id
            JOIN models m ON m.id = cg.model_id
            LEFT JOIN creative_plans cp ON cp.linked_campaign_slug = c.slug
              AND cp.status IN ('planned', 'active')
            ORDER BY c.id
            """
        ).fetchall()
    ]
    repository = CreatorGovernanceRepository(
        conn, new_id=new_id, slugify=slugify, utc_now=lambda: now
    )
    eligible: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for campaign in rows:
        reasons: list[str] = []
        state = str(campaign.get("lifecycle_status") or "missing")
        if state not in {"production_ready", "producing"}:
            reasons.append(f"campaign_not_production_ready:{state}")
        try:
            configured_blockers = json.loads(
                str(campaign.get("blocker_codes_json") or "[]")
            )
        except json.JSONDecodeError:
            configured_blockers = ["invalid_campaign_blocker_codes"]
        if configured_blockers:
            reasons.extend(f"campaign_blocked:{code}" for code in configured_blockers)
        sources = [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM source_assets
                WHERE campaign_id = ? AND model_id = ?
                  AND media_type = 'image' AND lower(COALESCE(status, '')) = 'approved'
                ORDER BY updated_at DESC, id
                """,
                (campaign["campaign_id"], campaign["creator_id"]),
            ).fetchall()
        ]
        source_proofs: list[dict[str, Any]] = []
        if not sources:
            reasons.append("approved_creator_source_missing")
        for source in sources:
            source_reasons = _source_byte_blockers(source)
            mode = _planned_mode(campaign.get("style_lanes_json"))
            provider = "internal" if mode == "static_reel" else "higgsfield"
            if mode == "static_reel":
                try:
                    validate_static_source_assets(
                        SimpleNamespace(conn=conn),
                        (str(source["id"]),),
                    )
                except (OSError, PermissionError, ValueError) as exc:
                    source_reasons.append(str(exc))
            try:
                operation = repository.resolve_operation(
                    creator=str(campaign["creator_id"]),
                    campaign=str(campaign["campaign_id"]),
                    operation="generation",
                    provider=provider,
                    source_asset_id=str(source["id"]),
                    at=now,
                )
            except (OSError, PermissionError, ValueError) as exc:
                operation = None
                source_reasons.append(str(exc))
            source_proofs.append(
                {
                    "sourceAssetId": source["id"],
                    "sourceSha256": source.get("content_hash"),
                    "mode": mode,
                    "provider": provider,
                    "eligible": not reasons and not source_reasons,
                    "governanceFingerprint": (
                        operation.get("governanceFingerprint") if operation else None
                    ),
                    "blockers": list(dict.fromkeys(source_reasons)),
                }
            )
        item = {
            "campaignId": campaign["campaign_id"],
            "campaignSlug": campaign["campaign_slug"],
            "creatorId": campaign["creator_id"],
            "creatorSlug": campaign["creator_slug"],
            "lifecycleStatus": state,
            "sources": source_proofs,
            "eligible": any(source["eligible"] for source in source_proofs),
            "blockers": list(dict.fromkeys(reasons)),
        }
        (eligible if item["eligible"] else blocked).append(item)
    blockers = [] if eligible else ["no_governance_eligible_campaign_source"]
    return {
        "ready": bool(eligible),
        "eligibleCampaignCount": len(eligible),
        "eligibleCampaigns": eligible,
        "blockedCampaignCount": len(blocked),
        "blockedCampaigns": blocked,
        "blockers": blockers,
    }


def _source_byte_blockers(source: dict[str, Any]) -> list[str]:
    path = Path(
        str(source.get("stored_path") or source.get("original_path") or "")
    ).expanduser()
    expected = str(source.get("content_hash") or "").lower()
    if path.is_symlink() or not path.is_file() or not _SHA256_RE.fullmatch(expected):
        return ["approved_source_bytes_unverified"]
    try:
        from .asset_inventory import _sha256_file

        actual = _sha256_file(path)
    except OSError:
        return ["approved_source_bytes_unverified"]
    return [] if actual == expected else ["approved_source_bytes_unverified"]


def _handoff_readiness(
    conn: sqlite3.Connection, *, creative_approvals_dir: Path
) -> dict[str, Any]:
    assets = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM rendered_assets
            WHERE review_state = 'approved'
            ORDER BY updated_at DESC, id
            """
        ).fetchall()
    ]
    ready: list[dict[str, Any]] = []
    blocker_counts: Counter[str] = Counter()
    for asset in assets:
        evidence = current_handoff_evidence_read_only(
            conn,
            asset,
            creative_approvals_dir=creative_approvals_dir,
        )
        if evidence["canHandoff"]:
            ready.append(
                {
                    "assetId": asset["id"],
                    "campaignId": asset["campaign_id"],
                    "sourceAssetId": asset["source_asset_id"],
                    "finalSha256": evidence["currentSha256"],
                    "auditReportId": evidence["auditReportId"],
                    "auditReportSha256": evidence["auditReportSha256"],
                    "contentForgeRunId": evidence["contentForgeRunId"],
                    "creativeApprovalState": evidence["creativeApprovalState"],
                }
            )
        else:
            blocker_counts.update(evidence["blockers"])
    return {
        "ready": bool(ready),
        "approvedAssetsExamined": len(assets),
        "handoffReadyCount": len(ready),
        "handoffReadyAssets": ready,
        "handoffReadySha256s": [item["finalSha256"] for item in ready],
        "blockerCounts": dict(sorted(blocker_counts.items())),
        "blockers": [] if ready else ["no_exact_final_asset_can_handoff"],
    }


def _threadsdash_readiness(
    conn: sqlite3.Connection,
    *,
    handoff_assets: list[dict[str, Any]],
    deployment_receipt: dict[str, Any] | None,
    now: str,
) -> dict[str, Any]:
    expected_contract = contract_binding(DEFAULT_DRAFT_PAYLOAD_SCHEMA)
    deployment, proof_blockers = _threadsdash_deployment_evidence(
        deployment_receipt,
        expected_contract=expected_contract,
        now=now,
    )
    deployed_at = deployment.get("deployedAt")
    evaluated_at = _parse_time(now)
    handoff_by_key = {
        (
            str(item["campaignId"]),
            str(item["sourceAssetId"]),
            str(item["assetId"]),
            str(item["finalSha256"]),
        ): item
        for item in handoff_assets
    }
    accepted: list[dict[str, Any]] = []
    blocker_counts: Counter[str] = Counter()
    examined_rows = 0
    if not proof_blockers and evaluated_at is not None:
        rows = conn.execute(
            """
            SELECT * FROM threadsdash_exports
            WHERE status = 'accepted' AND acknowledged_at IS NOT NULL
              AND datetime(acknowledged_at) >= datetime(?)
              AND datetime(acknowledged_at) <= datetime(?)
            ORDER BY acknowledged_at DESC, id
            """,
            (deployed_at, now),
        ).fetchall()
        examined_rows = len(rows)
        for raw in rows:
            row = dict(raw)
            candidate, blockers = _accepted_threadsdash_candidate(
                row,
                expected_contract=expected_contract,
                handoff_by_key=handoff_by_key,
                now=now,
            )
            blocker_counts.update(blockers)
            if candidate is not None:
                accepted.append(candidate)
    operator_blockers: list[str] = []
    if not accepted:
        operator_blockers.append("current_threadsdashboard_acceptance_missing")
    if examined_rows and not accepted:
        operator_blockers.append("schedule_eligible_threadsdashboard_draft_missing")
    return {
        "ready": bool(accepted) and not proof_blockers,
        "deployment": deployment or None,
        "requiredContract": expected_contract,
        "acceptedExportCount": len(accepted),
        "acceptedExports": accepted,
        "scheduleEligibleCount": len(accepted),
        "blockerCounts": dict(sorted(blocker_counts.items())),
        "operatorBlockers": operator_blockers,
        "proofBlockers": proof_blockers,
    }


def load_threadsdashboard_deployment_receipt_file(path: Path) -> dict[str, Any]:
    candidate = path.expanduser()
    if candidate.is_symlink() or not candidate.is_file() or candidate.suffix != ".json":
        raise ValueError("threadsdashboard_deployment_receipt_path_unsafe")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("threadsdashboard_deployment_receipt_unreadable") from exc
    if not isinstance(payload, dict):
        raise ValueError("threadsdashboard_deployment_receipt_invalid")
    return payload


def _threadsdash_deployment_evidence(
    receipt: dict[str, Any] | None,
    *,
    expected_contract: dict[str, Any],
    now: str,
) -> tuple[dict[str, Any], list[str]]:
    payload = dict(receipt or {})
    expected_fields = {
        "schema",
        "receiptId",
        "repository",
        "environment",
        "provider",
        "projectId",
        "deploymentId",
        "deploymentStatus",
        "productionAliasCurrent",
        "deployedCommit",
        "deployedAt",
        "observedAt",
        "contract",
        "producerAttestation",
    }
    deployed_at = _parse_time(payload.get("deployedAt"))
    observed_at = _parse_time(payload.get("observedAt"))
    current = _parse_time(now)
    if (
        set(payload) != expected_fields
        or payload.get("schema") != _TD_DEPLOYMENT_SCHEMA
        or payload.get("repository") != _TD_REPOSITORY
        or payload.get("environment") != "production"
        or payload.get("provider") != _TD_PROVIDER
        or payload.get("deploymentStatus") != "READY"
        or payload.get("productionAliasCurrent") is not True
        or not all(
            str(payload.get(field) or "").strip()
            for field in (
                "receiptId",
                "repository",
                "provider",
                "projectId",
                "deploymentId",
            )
        )
        or not _COMMIT_RE.fullmatch(str(payload.get("deployedCommit") or ""))
        or deployed_at is None
        or observed_at is None
        or current is None
        or deployed_at > observed_at
        or observed_at > current
        or payload.get("contract") != expected_contract
    ):
        return {}, ["threadsdashboard_deployment_receipt_missing_or_invalid"]
    attestation = payload.pop("producerAttestation")
    try:
        verify_evidence_attestation(
            attestation if isinstance(attestation, dict) else {},
            payload,
            secret=load_evidence_secret(),
            expected_issuer=_TD_DEPLOYMENT_ISSUER,
            now=current,
        )
    except EvidenceAttestationError:
        return {}, ["threadsdashboard_deployment_receipt_unauthentic"]
    if current - observed_at > _TD_DEPLOYMENT_MAX_AGE:
        return {}, ["threadsdashboard_deployment_receipt_stale"]
    return {
        "receiptId": payload["receiptId"],
        "repository": payload["repository"],
        "provider": payload["provider"],
        "projectId": payload["projectId"],
        "deploymentId": payload["deploymentId"],
        "deploymentStatus": payload["deploymentStatus"],
        "productionAliasCurrent": payload["productionAliasCurrent"],
        "deployedCommit": payload["deployedCommit"],
        "deployedAt": payload["deployedAt"],
        "observedAt": payload["observedAt"],
    }, []


def _accepted_threadsdash_candidate(
    row: dict[str, Any],
    *,
    expected_contract: dict[str, Any],
    handoff_by_key: dict[tuple[str, str, str, str], dict[str, Any]],
    now: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    blockers: list[str] = []
    manifest_path = Path(str(row["manifest_path"])).expanduser()
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return None, ["threadsdashboard_export_receipt_unreadable"]
    try:
        acknowledgment = json.loads(row["acknowledgment_json"] or "null")
        wrapper = json.loads(manifest_path.read_text(encoding="utf-8"))
        rendered_asset_ids = json.loads(row["rendered_asset_ids_json"] or "[]")
        source_asset_ids = json.loads(row["source_asset_ids_json"] or "[]")
        final_sha256s = json.loads(row["final_sha256s_json"] or "[]")
        destination_ids = json.loads(row["destination_ids_json"] or "[]")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, ["threadsdashboard_export_receipt_unreadable"]
    payload = wrapper.get("payload") if isinstance(wrapper, dict) else None
    drafts = payload.get("drafts") if isinstance(payload, dict) else None
    post_ids = (
        acknowledgment.get("postIds") if isinstance(acknowledgment, dict) else None
    )
    if (
        row.get("contract_schema") != expected_contract["schemaName"]
        or row.get("contract_version") != expected_contract["schemaVersion"]
        or row.get("contract_fingerprint") != expected_contract["contractFingerprint"]
        or not isinstance(payload, dict)
        or payload.get("schema") != expected_contract["schemaName"]
        or canonical_fingerprint(payload) != row.get("request_fingerprint")
        or not isinstance(drafts, list)
        or len(drafts) != 1
        or not isinstance(drafts[0], dict)
        or not isinstance(acknowledgment, dict)
        or acknowledgment.get("status") != "accepted"
        or not isinstance(post_ids, list)
        or len(post_ids) != 1
        or not str(post_ids[0]).strip()
    ):
        return None, ["threadsdashboard_export_receipt_binding_mismatch"]
    draft = drafts[0]
    destination_id = str(
        draft.get("instagramAccountId") or draft.get("accountId") or "unassigned"
    )
    if (
        str(draft.get("campaignId") or "") != str(row.get("campaign_id") or "")
        or rendered_asset_ids != [str(draft.get("renderedAssetId") or "")]
        or source_asset_ids != [str(draft.get("sourceAssetId") or "")]
        or final_sha256s != [str(draft.get("contentHash") or "")]
        or destination_ids != [destination_id]
    ):
        return None, ["threadsdashboard_export_receipt_identity_mismatch"]
    key = (
        str(row.get("campaign_id") or ""),
        str(draft.get("sourceAssetId") or ""),
        str(draft.get("renderedAssetId") or ""),
        str(draft.get("contentHash") or ""),
    )
    handoff = handoff_by_key.get(key)
    if handoff is None:
        blockers.append("threadsdashboard_export_not_bound_to_handoff_asset")
    preparation = draft.get("mediaPreparation")
    if (
        not isinstance(preparation, dict)
        or handoff is None
        or (
            preparation.get("method") != "exact_final"
            or preparation.get("outputSha256") != handoff["finalSha256"]
            or preparation.get("auditReportId") != handoff["auditReportId"]
            or preparation.get("auditReportSha256") != handoff["auditReportSha256"]
            or preparation.get("auditSubjectSha256") != handoff["finalSha256"]
            or preparation.get("qcStatus") != "passed"
            or preparation.get("postProcessChain") != []
        )
    ):
        blockers.append("threadsdashboard_exact_final_receipt_mismatch")
    blockers.extend(_draft_schedule_blockers(draft, now=now))
    if blockers:
        return None, list(dict.fromkeys(blockers))
    return {
        "exportId": row["id"],
        "acknowledgedAt": row["acknowledged_at"],
        "campaignId": key[0],
        "sourceAssetId": key[1],
        "assetId": key[2],
        "finalSha256": key[3],
        "postId": str(post_ids[0]),
        "destinationAccountId": draft.get("instagramAccountId")
        or draft.get("accountId"),
        "distributionPlanId": draft.get("distributionPlanId"),
        "plannedWindowStart": draft.get("plannedWindowStart"),
        "plannedWindowEnd": draft.get("plannedWindowEnd"),
    }, []


def _draft_schedule_blockers(draft: dict[str, Any], *, now: str) -> list[str]:
    blockers: list[str] = []
    publishability = draft.get("publishability")
    publishability = publishability if isinstance(publishability, dict) else {}
    handoff = draft.get("handoffManifest")
    handoff = handoff if isinstance(handoff, dict) else {}
    surface = handoff.get("surfaceReadiness")
    surface = surface if isinstance(surface, dict) else {}
    metadata = draft.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    campaign_metadata = metadata.get("campaign_factory")
    campaign_metadata = campaign_metadata if isinstance(campaign_metadata, dict) else {}
    account = campaign_metadata.get("account_eligibility")
    account = account if isinstance(account, dict) else {}
    if (
        publishability.get("exportable") is not True
        or publishability.get("publishableCandidate") is not True
        or publishability.get("failureReasons")
        or surface.get("canHandoff") is not True
        or surface.get("scheduleSafe") is not True
    ):
        blockers.append("threadsdashboard_draft_not_schedule_safe")
    if account.get("allowed") is not True:
        blockers.append("threadsdashboard_destination_account_ineligible")
    if not (
        str(draft.get("distributionPlanId") or "").strip()
        and str(draft.get("instagramAccountId") or draft.get("accountId") or "").strip()
    ):
        blockers.append("threadsdashboard_schedule_destination_incomplete")
    start = _parse_time(draft.get("plannedWindowStart"))
    end = _parse_time(draft.get("plannedWindowEnd"))
    current = _parse_time(now)
    if (
        start is None
        or end is None
        or current is None
        or start <= current
        or end <= start
    ):
        blockers.append("threadsdashboard_schedule_window_invalid")
    blockers.extend(
        _audio_schedule_blockers(
            draft.get("audioIntent"),
            final_sha256=str(draft.get("contentHash") or ""),
            now=now,
        )
    )
    return blockers


def _audio_schedule_blockers(value: Any, *, final_sha256: str, now: str) -> list[str]:
    intent = value if isinstance(value, dict) else {}
    fulfillment = intent.get("fulfillment")
    fulfillment = fulfillment if isinstance(fulfillment, dict) else {}
    gates = intent.get("gates")
    gates = gates if isinstance(gates, dict) else {}
    rights = intent.get("rights")
    rights = rights if isinstance(rights, dict) else {}
    if (
        intent.get("schema") != "pipeline.audio_intent.v1"
        or intent.get("policy") != "embedded_trending_required"
        or intent.get("mode") != "embedded_trending_audio"
        or intent.get("required") is not True
        or intent.get("status") != "verified"
        or fulfillment.get("status") != "verified"
        or fulfillment.get("proof_type") != "embedded_output_audio_stream"
        or fulfillment.get("evidence_class") != "EXACT_BYTE_VERIFIED"
        or fulfillment.get("output_sha256") != final_sha256
        or gates.get("allow_live_schedule") is not True
        or gates.get("allow_publish") is not True
    ):
        return ["audio_not_exactly_fulfilled_for_live_schedule"]
    if (
        rights.get("required") is not True
        or rights.get("usageRightsStatus")
        not in {
            "platform_native_authorized",
            "operator_supplied_authorized",
            "licensed",
        }
        or rights.get("commercialUseAllowed") is not True
        or not all(
            rights.get(field)
            for field in (
                "rightsSource",
                "territory",
                "accountScope",
                "evidenceReceipt",
            )
        )
    ):
        return ["audio_rights_receipt_missing_or_invalid"]
    expires_at = (
        _parse_time(rights.get("expiresAt")) if rights.get("expiresAt") else None
    )
    current = _parse_time(now)
    if rights.get("expiresAt") and (
        expires_at is None or current is None or expires_at <= current
    ):
        return ["audio_rights_receipt_expired"]
    return []


def _runtime_readiness(
    conn: sqlite3.Connection,
    *,
    promotion_receipt: dict[str, Any] | None,
    expected_runtime_sha: str | None,
) -> dict[str, Any]:
    blockers: list[str] = []
    receipt = promotion_receipt or {}
    promoted_at = _parse_time(receipt.get("createdAt"))
    receipt_sha = str(receipt.get("destinationCommitAfter") or "")
    if (
        receipt.get("schema") != "creator_os.runtime_promotion_receipt.v1"
        or receipt.get("receiptAuthority") != "authoritative"
        or receipt.get("status") not in {"promoted", "already_current"}
        or promoted_at is None
    ):
        blockers.append("authoritative_runtime_promotion_receipt_missing")
    if not _COMMIT_RE.fullmatch(str(expected_runtime_sha or "")):
        blockers.append("expected_runtime_sha_missing_or_invalid")
    elif receipt_sha != expected_runtime_sha:
        blockers.append("runtime_promotion_sha_mismatch")

    completed: list[dict[str, Any]] = []
    if promoted_at is not None:
        runs = conn.execute(
            """
            SELECT * FROM daily_orchestrator_runs
            WHERE status = 'completed' AND selected_items > 0
              AND datetime(created_at) >= datetime(?)
            ORDER BY created_at DESC, id
            """,
            (receipt["createdAt"],),
        ).fetchall()
        for raw in runs:
            run = dict(raw)
            items = conn.execute(
                """
                SELECT campaign_id, source_asset_id, state, result_json
                FROM daily_orchestrator_items
                WHERE run_id = ? ORDER BY ordinal
                """,
                (run["id"],),
            ).fetchall()
            if len(items) != int(run["selected_items"]):
                continue
            result_bindings: list[dict[str, Any]] = []
            valid = True
            for item in items:
                try:
                    result = json.loads(item["result_json"] or "null")
                except json.JSONDecodeError:
                    valid = False
                    break
                if item["state"] != "completed" or not _batch_succeeded(result):
                    valid = False
                    break
                bindings = _runtime_result_bindings(result)
                if not bindings:
                    valid = False
                    break
                result_bindings.extend(
                    {
                        "campaignId": item["campaign_id"],
                        "sourceAssetId": item["source_asset_id"],
                        **binding,
                    }
                    for binding in bindings
                )
            if valid:
                completed.append(
                    {
                        "runId": run["id"],
                        "runKey": run["run_key"],
                        "createdAt": run["created_at"],
                        "selectedItems": run["selected_items"],
                        "completedResults": len(result_bindings),
                        "resultBindings": result_bindings,
                    }
                )
    if not completed:
        blockers.append("post_promotion_daily_orchestrator_run_missing")
    return {
        "ready": not blockers,
        "expectedRuntimeSha": expected_runtime_sha,
        "promotionReceipt": (
            {
                "promotionId": receipt.get("promotionId"),
                "createdAt": receipt.get("createdAt"),
                "destinationCommitAfter": receipt.get("destinationCommitAfter"),
                "status": receipt.get("status"),
            }
            if receipt
            else None
        ),
        "postPromotionCompletedRunCount": len(completed),
        "postPromotionCompletedRuns": completed,
        "blockers": list(dict.fromkeys(blockers)),
    }


def _runtime_result_bindings(result: dict[str, Any]) -> list[dict[str, str]]:
    bindings: list[dict[str, str]] = []
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        nested = item.get("result")
        nested = nested if isinstance(nested, dict) else {}
        stage = nested.get("result")
        stage = stage if isinstance(stage, dict) else nested
        registered = stage.get("registeredAsset")
        registered = registered if isinstance(registered, dict) else {}
        audit = nested.get("finalContentForgeAudit")
        audit = audit if isinstance(audit, dict) else {}
        audio = nested.get("audioFulfillment")
        audio = audio if isinstance(audio, dict) else {}
        asset_id = str(
            item.get("renderedAssetId")
            or registered.get("id")
            or audit.get("renderedAssetId")
            or ""
        )
        final_sha = str(
            item.get("outputSha256")
            or audio.get("finalVideoSha256")
            or registered.get("content_hash")
            or audit.get("subjectSha256")
            or ""
        )
        if asset_id and _SHA256_RE.fullmatch(final_sha):
            bindings.append({"assetId": asset_id, "finalSha256": final_sha})
    return bindings


def _linked_canary_candidates(
    *,
    governance: dict[str, Any],
    handoff: dict[str, Any],
    runtime: dict[str, Any],
    threadsdash: dict[str, Any],
) -> list[dict[str, Any]]:
    governance_keys = {
        (str(campaign["campaignId"]), str(source["sourceAssetId"]))
        for campaign in governance["eligibleCampaigns"]
        for source in campaign["sources"]
        if source["eligible"]
    }
    handoff_by_key = {
        (
            str(item["campaignId"]),
            str(item["sourceAssetId"]),
            str(item["assetId"]),
            str(item["finalSha256"]),
        ): item
        for item in handoff["handoffReadyAssets"]
    }
    runtime_keys = {
        (
            str(item["campaignId"]),
            str(item["sourceAssetId"]),
            str(item["assetId"]),
            str(item["finalSha256"]),
        )
        for run in runtime["postPromotionCompletedRuns"]
        for item in run["resultBindings"]
    }
    candidates: list[dict[str, Any]] = []
    for accepted in threadsdash["acceptedExports"]:
        key = (
            str(accepted["campaignId"]),
            str(accepted["sourceAssetId"]),
            str(accepted["assetId"]),
            str(accepted["finalSha256"]),
        )
        if key in handoff_by_key and key in runtime_keys and key[:2] in governance_keys:
            candidates.append(
                {
                    **accepted,
                    "auditReportId": handoff_by_key[key]["auditReportId"],
                    "auditReportSha256": handoff_by_key[key]["auditReportSha256"],
                }
            )
    return candidates


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)
