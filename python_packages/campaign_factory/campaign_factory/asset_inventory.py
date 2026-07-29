from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

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
        WHERE {' AND '.join(clauses)}
        ORDER BY r.created_at
        """,
        params,
    ).fetchall()
    readiness = []
    for raw in rows:
        row = dict(raw)
        path = Path(str(row.get("output_path") or ""))
        readiness.append(
            {
                "assetId": row["id"],
                "contentSurface": row.get("content_surface"),
                "canHandoff": bool(
                    path.is_file()
                    and row.get("content_hash")
                    and _sha256_file(path) == row["content_hash"]
                ),
            }
        )
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
