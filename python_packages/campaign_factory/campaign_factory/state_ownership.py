from __future__ import annotations

import json
from typing import Any

from pipeline_contracts import schema_path

from .adapters.threadsdash_export_saga import set_export_state
from .adapters.threadsdash_owner_api import reconcile_draft_handoff


def _registry() -> dict[str, Any]:
    path = (
        schema_path("campaign_draft_payload.v3.schema.json").parent.parent
        / "ownership_registry.v1.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def explain_state(record_or_id: str) -> dict[str, Any]:
    query = str(record_or_id or "").strip()
    registry = _registry()
    matches = [
        domain
        for domain in registry["domains"]
        if query in domain["canonicalTables"]
        or any(
            query.startswith(prefix)
            for prefix in (
                "tdexp_"
                if domain["domain"] == "campaign_and_creative_production"
                else "",
                "asset_"
                if domain["domain"] == "campaign_and_creative_production"
                else "",
                "render_" if domain["domain"] == "render_evidence_and_cache" else "",
            )
            if prefix
        )
    ]
    if not matches:
        return {
            "ok": False,
            "record": query,
            "reason": "ownership_not_found",
            "registry": registry["schema"],
        }
    domain = matches[0]
    canonical_store = domain["canonicalStore"]
    classification = (
        "outbound_handoff_evidence"
        if query.startswith("tdexp_")
        else (
            "contract" if canonical_store == "canonical_json_schemas" else "canonical"
        )
    )
    return {
        "ok": True,
        "record": query,
        "domain": domain["domain"],
        "repository": domain["repository"],
        "canonicalStore": canonical_store,
        "classification": classification,
        "allowedWriters": domain["allowedWriters"],
        "allowedReaders": domain["allowedReaders"],
        "joinDirections": {
            "imports": domain["importDirection"],
            "exports": domain["exportDirection"],
        },
        "externalSourceOfTruth": domain["externalSourceOfTruth"],
        "registry": registry["schema"],
    }


def reconcile_bridge(
    factory: Any,
    *,
    export_id: str | None = None,
    ingest_url: str | None = None,
    ingest_secret: str | None = None,
) -> dict[str, Any]:
    if export_id:
        rows = factory.conn.execute(
            "SELECT * FROM threadsdash_exports WHERE id = ? ORDER BY created_at",
            (export_id,),
        ).fetchall()
    else:
        rows = factory.conn.execute(
            """
            SELECT * FROM threadsdash_exports
            WHERE status IN ('submitted', 'acceptance_unknown', 'accepted')
            ORDER BY created_at
            """
        ).fetchall()
    findings: list[dict[str, Any]] = []
    repaired: list[str] = []
    for raw in rows:
        row = dict(raw)
        acknowledgment = json.loads(row["acknowledgment_json"] or "null")
        if not isinstance(acknowledgment, dict):
            try:
                response = reconcile_draft_handoff(
                    export_id=row["id"],
                    user_id=row["user_id"],
                    ingest_url=ingest_url,
                    ingest_secret=ingest_secret,
                )
                acknowledgment = response.get("acknowledgment")
            except Exception as exc:
                findings.append(
                    {
                        "owner": "threadsdashboard",
                        "record": row["id"],
                        "conflict": "export_without_durable_acknowledgment",
                        "safeAutomaticAction": "none",
                        "manualAction": "retry reconciliation with owner API available",
                        "evidence": str(exc),
                    }
                )
                continue
        expected_sha = set(json.loads(row["final_sha256s_json"] or "[]"))
        items = acknowledgment.get("items") or []
        observed_sha = {
            str(item.get("submittedContentSha256") or "")
            for item in items
            if isinstance(item, dict)
        }
        if expected_sha and expected_sha != observed_sha:
            findings.append(
                {
                    "owner": "creator_os_and_threadsdashboard",
                    "record": row["id"],
                    "conflict": "accepted_content_hash_mismatch",
                    "safeAutomaticAction": "none",
                    "manualAction": "inspect the exact media and acknowledgment receipts",
                    "evidence": {
                        "expectedSha256s": sorted(expected_sha),
                        "observedSha256s": sorted(observed_sha),
                    },
                }
            )
            continue
        set_export_state(
            factory.conn, row["id"], "accepted", acknowledgment=acknowledgment
        )
        repaired.append(row["id"])
    return {
        "schema": "creator_os.bridge_reconciliation.v1",
        "checked": len(rows),
        "acknowledgmentsAttached": repaired,
        "findings": findings,
        "ok": not findings,
        "sourceSystem": "creator_os",
        "owningSystem": "creator_os",
        "recordType": "bridge_reconciliation_report",
    }
