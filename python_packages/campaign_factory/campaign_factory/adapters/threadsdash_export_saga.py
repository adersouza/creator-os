from __future__ import annotations

import json
from typing import Any

from ..persistence import utc_now
from .threadsdash_handoff_evidence import (
    canonical_fingerprint,
    contract_binding,
    handoff_idempotency_key,
)

EXPORT_STATES = {
    "prepared",
    "submitted",
    "acceptance_unknown",
    "accepted",
    "rejected",
    "superseded",
}


def export_identity(payload: dict[str, Any]) -> dict[str, Any]:
    drafts = [draft for draft in payload.get("drafts") or [] if isinstance(draft, dict)]
    return {
        "renderedAssetIds": list(
            dict.fromkeys(str(draft.get("renderedAssetId") or "") for draft in drafts)
        ),
        "sourceAssetIds": list(
            dict.fromkeys(str(draft.get("sourceAssetId") or "") for draft in drafts)
        ),
        "finalSha256s": list(
            dict.fromkeys(str(draft.get("contentHash") or "") for draft in drafts)
        ),
        "destinationIds": list(
            dict.fromkeys(
                str(
                    draft.get("instagramAccountId")
                    or draft.get("accountId")
                    or "unassigned"
                )
                for draft in drafts
            )
        ),
        "reservationIds": list(
            dict.fromkeys(
                str(draft.get("inventoryReservationId") or "")
                for draft in drafts
                if draft.get("inventoryReservationId")
            )
        ),
    }


def prepare_export(
    conn: Any,
    *,
    export_id: str,
    campaign_id: str,
    user_id: str,
    manifest_path: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    now = utc_now()
    key = handoff_idempotency_key(export_id)
    contract = contract_binding(str(payload.get("schema") or ""))
    identity = export_identity(payload)
    fingerprint = canonical_fingerprint(payload)
    existing = conn.execute(
        "SELECT * FROM threadsdash_exports WHERE idempotency_key = ?", (key,)
    ).fetchone()
    if existing is not None:
        if str(existing["request_fingerprint"] or "") != fingerprint:
            raise ValueError("export idempotency key was reused with different content")
        return dict(existing)
    conn.execute(
        """
        INSERT INTO threadsdash_exports
        (id, campaign_id, manifest_path, user_id, dry_run, status,
         idempotency_key, request_fingerprint, contract_schema, contract_version,
         contract_fingerprint, rendered_asset_ids_json, source_asset_ids_json,
         final_sha256s_json, destination_ids_json, reservation_ids_json,
         source_system, owning_system, created_at, updated_at)
        VALUES (?, ?, ?, ?, 0, 'prepared', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                'creator_os', 'threadsdashboard', ?, ?)
        """,
        (
            export_id,
            campaign_id,
            manifest_path,
            user_id,
            key,
            fingerprint,
            contract["schemaName"],
            contract["schemaVersion"],
            contract["contractFingerprint"],
            json.dumps(identity["renderedAssetIds"], sort_keys=True),
            json.dumps(identity["sourceAssetIds"], sort_keys=True),
            json.dumps(identity["finalSha256s"], sort_keys=True),
            json.dumps(identity["destinationIds"], sort_keys=True),
            json.dumps(identity["reservationIds"], sort_keys=True),
            now,
            now,
        ),
    )
    conn.commit()
    return dict(
        conn.execute(
            "SELECT * FROM threadsdash_exports WHERE id = ?", (export_id,)
        ).fetchone()
    )


def set_export_state(
    conn: Any,
    export_id: str,
    state: str,
    *,
    acknowledgment: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    if state not in EXPORT_STATES:
        raise ValueError(f"invalid ThreadsDashboard export state: {state}")
    now = utc_now()
    timestamp_column = {
        "submitted": "submitted_at",
        "accepted": "acknowledged_at",
        "rejected": "rejected_at",
        "superseded": "superseded_at",
    }.get(state)
    assignments = ["status = ?", "updated_at = ?", "last_error = ?"]
    values: list[Any] = [state, now, error]
    if timestamp_column:
        assignments.append(f"{timestamp_column} = ?")
        values.append(now)
    if acknowledgment is not None:
        assignments.append("acknowledgment_json = ?")
        values.append(json.dumps(acknowledgment, ensure_ascii=False, sort_keys=True))
    values.append(export_id)
    conn.execute(
        f"UPDATE threadsdash_exports SET {', '.join(assignments)} WHERE id = ?",
        values,
    )
    conn.commit()
