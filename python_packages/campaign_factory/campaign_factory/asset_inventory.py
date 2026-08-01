from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .creative_approval import asset_requires_creative_approval

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def explain_asset(factory: Any, sha256: str) -> dict[str, Any]:
    digest = str(sha256 or "").strip().lower()
    if not SHA256_RE.fullmatch(digest):
        raise ValueError("sha must be a 64-character lowercase SHA-256 digest")
    matches = [
        dict(row)
        for row in factory.conn.execute(
            "SELECT * FROM rendered_assets WHERE lower(content_hash) = ? ORDER BY created_at",
            (digest,),
        ).fetchall()
    ]
    if not matches:
        return {
            "schema": "campaign_factory.asset_lineage_explanation.v1",
            "querySha256": digest,
            "lineageStatus": "not_found",
            "blockers": ["final_sha_not_registered"],
        }
    if len(matches) > 1:
        return {
            "schema": "campaign_factory.asset_lineage_explanation.v1",
            "querySha256": digest,
            "lineageStatus": "ambiguous",
            "matches": [
                {
                    "renderedAssetId": row["id"],
                    "campaignId": row["campaign_id"],
                    "outputPath": row["output_path"],
                }
                for row in matches
            ],
            "blockers": ["final_sha_matches_multiple_assets"],
        }

    asset = matches[0]
    metadata = _json_object(asset.get("metadata_json"))
    caption = _json_object(asset.get("caption_generation_json"))
    source_row = factory.conn.execute(
        "SELECT * FROM source_assets WHERE id = ?", (asset["source_asset_id"],)
    ).fetchone()
    source = dict(source_row) if source_row else None
    attempts = [
        dict(row)
        for row in factory.conn.execute(
            """
            SELECT ga.*, gob.content_sha256 AS output_sha256,
                   gob.byte_size AS output_byte_size
            FROM generation_attempts ga
            JOIN generation_output_blobs gob ON gob.id = ga.output_blob_id
            WHERE ga.rendered_asset_id = ?
            ORDER BY ga.created_at
            """,
            (asset["id"],),
        ).fetchall()
    ]
    edges = [
        {**dict(row), "lineage": _json_object(row["lineage_json"])}
        for row in factory.conn.execute(
            """
            SELECT *
            FROM generation_lineage_edges
            WHERE rendered_asset_id = ?
            ORDER BY created_at, relation
            """,
            (asset["id"],),
        ).fetchall()
    ]
    approvals = [
        dict(row)
        for row in factory.conn.execute(
            """
            SELECT *
            FROM approval_decisions
            WHERE rendered_asset_id = ?
            ORDER BY created_at
            """,
            (asset["id"],),
        ).fetchall()
    ]
    audits = [
        dict(row)
        for row in factory.conn.execute(
            """
            SELECT * FROM audit_reports
            WHERE rendered_asset_id = ?
            ORDER BY created_at, id
            """,
            (asset["id"],),
        ).fetchall()
    ]
    reservations = [
        dict(row)
        for row in factory.conn.execute(
            """
            SELECT *
            FROM asset_inventory_reservations
            WHERE asset_id = ?
            ORDER BY reserved_at
            """,
            (asset["id"],),
        ).fetchall()
    ]
    assignments = [
        dict(row)
        for row in factory.conn.execute(
            """
            SELECT *
            FROM asset_account_assignments
            WHERE rendered_asset_id = ?
            ORDER BY created_at
            """,
            (asset["id"],),
        ).fetchall()
    ]
    path = Path(str(asset.get("output_path") or ""))
    bytes_status = "missing"
    actual_sha = None
    if path.is_file():
        actual_sha = _sha256_file(path)
        bytes_status = "verified" if actual_sha == digest else "hash_mismatch"
    blockers: list[str] = []
    if source is None:
        blockers.append("source_asset_missing")
    if bytes_status != "verified":
        blockers.append(f"final_bytes_{bytes_status}")
    generated_lineage = caption.get("generatedAssetLineage")
    if not attempts and not generated_lineage:
        blockers.append("generation_lineage_unproven")
    cooldown = _recursive_value(caption, "variantCooldownCheck")
    cooldown_status = str(cooldown or "unproven")
    if cooldown_status != "clear":
        blockers.append(f"variant_cooldown_{cooldown_status}")
    handoff_evidence = current_handoff_evidence(factory, asset, path=path)
    blockers.extend(handoff_evidence["blockers"])
    blockers = list(dict.fromkeys(blockers))
    return {
        "schema": "campaign_factory.asset_lineage_explanation.v1",
        "querySha256": digest,
        "lineageStatus": "verified" if not blockers else "incomplete",
        "blockers": blockers,
        "source": source,
        "generatedStillAndMotion": {
            "attempts": attempts,
            "lineageEdges": edges,
            "embeddedLineage": generated_lineage,
        },
        "overlay": {
            "captionPlacementDecision": _recursive_value(
                caption, "captionPlacementDecision"
            ),
            "captionHash": _recursive_value(caption, "caption_hash", "captionHash"),
        },
        "audio": metadata.get("audioEmbeddingReceipt")
        or caption.get("audioEmbeddingReceipt"),
        "final": {
            "renderedAssetId": asset["id"],
            "path": str(path),
            "registeredSha256": asset["content_hash"],
            "actualSha256": actual_sha,
            "bytesStatus": bytes_status,
            "recipe": asset.get("recipe"),
        },
        "review": {
            "auditStatus": asset.get("audit_status"),
            "reviewState": asset.get("review_state"),
            "approvalDecisions": approvals,
            "auditReports": audits,
            "currentExactByteEvidence": handoff_evidence,
        },
        "reuse": {
            "requireFreshBypassesReuse": True,
            "variantCooldownCheck": cooldown_status,
            "reservations": reservations,
            "assignments": assignments,
        },
    }


def inventory_report(
    factory: Any,
    *,
    campaign_slug: str | None = None,
    content_surface: str | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    clauses = ["r.review_state = 'approved'"]
    resolved_campaign_slug = campaign_slug
    if campaign_slug:
        campaign = factory.domains.campaign_by_slug(campaign_slug)
        clauses.append("r.campaign_id = ?")
        params.append(campaign["id"])
        resolved_campaign_slug = campaign["slug"]
    if content_surface:
        clauses.append("r.content_surface = ?")
        params.append(content_surface)
    rows = factory.conn.execute(
        f"""
        SELECT r.*
        FROM rendered_assets r
        JOIN campaigns c ON c.id = r.campaign_id
        WHERE {" AND ".join(clauses)}
        ORDER BY r.created_at
        """,
        params,
    ).fetchall()
    readiness = []
    exclusions: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        path = Path(str(row.get("output_path") or ""))
        evidence = current_handoff_evidence(factory, row, path=path)
        readiness.append(
            {
                "assetId": row["id"],
                "contentSurface": row.get("content_surface"),
                "canHandoff": evidence["canHandoff"],
            }
        )
        if evidence["blockers"]:
            exclusions.append({"assetId": row["id"], "blockers": evidence["blockers"]})
    counts = factory.domains.inventory_reservations.reservation_adjusted_inventory(
        readiness,
        content_surface=content_surface,
        reconcile_expired=False,
        ensure_metadata=False,
    )
    return {
        "schema": "campaign_factory.inventory_report.v1",
        "campaign": resolved_campaign_slug,
        "contentSurface": content_surface,
        **counts,
        "approvedRowsExamined": len(rows),
        "excludedForCurrentEvidence": len(exclusions),
        "evidenceExclusions": exclusions[:20],
    }


def current_handoff_evidence(
    factory: Any, asset: dict[str, Any], *, path: Path | None = None
) -> dict[str, Any]:
    """Require current bytes, audit, exact decision, and v2 approval as applicable."""

    current_sha = str(asset.get("content_hash") or "").strip().lower()
    path = path or Path(str(asset.get("output_path") or ""))
    blockers: list[str] = []
    if (
        not SHA256_RE.fullmatch(current_sha)
        or not path.is_file()
        or path.is_symlink()
        or _sha256_file(path) != current_sha
    ):
        blockers.append("current_final_bytes_unverified")

    audit_row = factory.conn.execute(
        """
        SELECT subject_sha256, status, overall_verdict
        FROM audit_reports
        WHERE rendered_asset_id = ?
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (asset["id"],),
    ).fetchone()
    audit = dict(audit_row) if audit_row else {}
    if audit.get("subject_sha256") != current_sha:
        blockers.append("current_sha_audit_missing")
    elif str(audit.get("overall_verdict") or "").lower() != "pass" or str(
        audit.get("status") or ""
    ).lower() not in {"pass", "passed", "approved_candidate"}:
        blockers.append("current_sha_audit_not_passed")

    decision_row = factory.conn.execute(
        """
        SELECT subject_sha256, decision
        FROM approval_decisions
        WHERE rendered_asset_id = ?
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (asset["id"],),
    ).fetchone()
    decision = dict(decision_row) if decision_row else {}
    if decision.get("subject_sha256") != current_sha:
        blockers.append("current_sha_approval_missing")
    elif str(decision.get("decision") or "").lower() != "approved":
        blockers.append("current_sha_not_approved")

    creative_approval_state = "not_required"
    if asset_requires_creative_approval(asset):
        creative = factory.domains.publishability.creative_approval_for_asset(
            str(asset["id"])
        )
        creative_approval_state = str(creative.get("state") or "missing")
        if creative_approval_state != "approved":
            blockers.append(
                str(creative.get("blockingReason") or "creative_approval_v2_missing")
            )
    return {
        "canHandoff": not blockers,
        "currentSha256": current_sha or None,
        "auditSubjectSha256": audit.get("subject_sha256"),
        "approvalSubjectSha256": decision.get("subject_sha256"),
        "creativeApprovalState": creative_approval_state,
        "blockers": list(dict.fromkeys(blockers)),
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _recursive_value(value: Any, *keys: str) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                return value[key]
        for child in value.values():
            found = _recursive_value(child, *keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _recursive_value(child, *keys)
            if found is not None:
                return found
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
