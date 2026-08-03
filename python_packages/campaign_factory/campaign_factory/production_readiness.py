from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .adapters.threadsdash_draft_payload import DEFAULT_DRAFT_PAYLOAD_SCHEMA
from .adapters.threadsdash_handoff_evidence import contract_binding
from .asset_inventory import current_handoff_evidence_read_only
from .core import new_id, slugify, utc_now
from .creator_governance import CreatorGovernanceRepository
from .daily_orchestrator import _planned_mode
from .derived_stills import validate_static_source_assets

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def build_production_readiness_proof(
    conn: sqlite3.Connection,
    *,
    creative_approvals_dir: Path,
    promotion_receipt: dict[str, Any] | None = None,
    expected_runtime_sha: str | None = None,
    threadsdash_deployed_sha: str | None = None,
    threadsdash_deployed_at: str | None = None,
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
        handoff_sha256s=set(handoff["handoffReadySha256s"]),
        deployed_sha=threadsdash_deployed_sha,
        deployed_at=threadsdash_deployed_at,
    )
    gates = {
        "governanceAndSources": governance["ready"],
        "exactFinalHandoff": handoff["ready"],
        "currentThreadsDashboardAcceptance": threadsdash["ready"],
        "postPromotionDailyOrchestrator": runtime["ready"],
    }
    operator_blockers = list(
        dict.fromkeys(
            governance["blockers"]
            + handoff["blockers"]
            + threadsdash["operatorBlockers"]
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
            source_reasons: list[str] = []
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
                    "finalSha256": evidence["currentSha256"],
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
    handoff_sha256s: set[str],
    deployed_sha: str | None,
    deployed_at: str | None,
) -> dict[str, Any]:
    proof_blockers: list[str] = []
    if not _COMMIT_RE.fullmatch(str(deployed_sha or "")):
        proof_blockers.append("threadsdashboard_deployed_sha_missing_or_invalid")
    cutoff = _parse_time(deployed_at)
    if cutoff is None:
        proof_blockers.append("threadsdashboard_deployed_at_missing_or_invalid")
    expected_contract = contract_binding(DEFAULT_DRAFT_PAYLOAD_SCHEMA)
    accepted: list[dict[str, Any]] = []
    if not proof_blockers:
        rows = conn.execute(
            """
            SELECT * FROM threadsdash_exports
            WHERE status = 'accepted' AND acknowledged_at IS NOT NULL
              AND datetime(acknowledged_at) >= datetime(?)
            ORDER BY acknowledged_at DESC, id
            """,
            (deployed_at,),
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            try:
                final_sha256s = set(json.loads(row["final_sha256s_json"] or "[]"))
                acknowledgment = json.loads(row["acknowledgment_json"] or "null")
            except json.JSONDecodeError:
                continue
            if (
                row.get("contract_schema") != expected_contract["schemaName"]
                or row.get("contract_version") != expected_contract["schemaVersion"]
                or row.get("contract_fingerprint")
                != expected_contract["contractFingerprint"]
                or not row.get("request_fingerprint")
                or not isinstance(acknowledgment, dict)
                or acknowledgment.get("status") != "accepted"
                or not acknowledgment.get("postIds")
                or not final_sha256s.intersection(handoff_sha256s)
            ):
                continue
            accepted.append(
                {
                    "exportId": row["id"],
                    "acknowledgedAt": row["acknowledged_at"],
                    "finalSha256s": sorted(final_sha256s),
                    "postIds": list(acknowledgment["postIds"]),
                }
            )
    operator_blockers = (
        [] if accepted else ["current_threadsdashboard_acceptance_missing"]
    )
    return {
        "ready": bool(accepted) and not proof_blockers,
        "deployedSha": deployed_sha,
        "deployedAt": deployed_at,
        "requiredContract": expected_contract,
        "acceptedExportCount": len(accepted),
        "acceptedExports": accepted,
        "operatorBlockers": operator_blockers,
        "proofBlockers": proof_blockers,
    }


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
                SELECT state, result_json FROM daily_orchestrator_items
                WHERE run_id = ? ORDER BY ordinal
                """,
                (run["id"],),
            ).fetchall()
            if len(items) != int(run["selected_items"]):
                continue
            parsed_results = []
            valid = True
            for item in items:
                try:
                    result = json.loads(item["result_json"] or "null")
                except json.JSONDecodeError:
                    valid = False
                    break
                if item["state"] != "completed" or not isinstance(result, dict):
                    valid = False
                    break
                parsed_results.append(result)
            if valid:
                completed.append(
                    {
                        "runId": run["id"],
                        "runKey": run["run_key"],
                        "createdAt": run["created_at"],
                        "selectedItems": run["selected_items"],
                        "completedResults": len(parsed_results),
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
