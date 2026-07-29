from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_registered_asset_bytes(asset: dict[str, Any]) -> dict[str, Any]:
    path = (
        Path(str(asset.get("campaign_path") or asset.get("output_path") or ""))
        .expanduser()
        .resolve()
    )
    registered = str(asset.get("content_hash") or "")
    try:
        actual = sha256_file(path) if path.is_file() and not path.is_symlink() else None
    except OSError:
        actual = None
    return {
        "path": str(path),
        "registeredSha256": registered or None,
        "actualSha256": actual,
        "passed": bool(registered and actual == registered),
    }


def require_current_asset_audit(
    conn: sqlite3.Connection, asset: dict[str, Any]
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT * FROM audit_reports
        WHERE rendered_asset_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (asset["id"],),
    ).fetchone()
    if not row:
        raise ValueError("approval blocked: current_sha_audit_missing")
    audit = dict(row)
    if audit.get("subject_sha256") != asset.get("content_hash"):
        raise ValueError("approval blocked: current_sha_audit_mismatch")
    return audit


def invalidate_asset_evidence_after_byte_change(
    conn: sqlite3.Connection,
    *,
    rendered_asset_id: str,
    previous_sha: str,
    new_sha: str,
    mutation_type: str,
    mutation_receipt: dict[str, Any],
    changed_at: str,
) -> None:
    row = conn.execute(
        "SELECT content_hash, metadata_json FROM rendered_assets WHERE id = ?",
        (rendered_asset_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"rendered asset not found: {rendered_asset_id}")
    if row["content_hash"] not in {previous_sha, new_sha}:
        raise ValueError("asset byte-change previous SHA mismatch")
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    invalidations = metadata.get("evidenceInvalidations")
    if not isinstance(invalidations, list):
        invalidations = []
    record = {
        "previousSha256": previous_sha,
        "newSha256": new_sha,
        "mutationType": mutation_type,
        "mutationReceipt": mutation_receipt,
        "changedAt": changed_at,
    }
    if record not in invalidations:
        invalidations.append(record)
    metadata["evidenceInvalidations"] = invalidations
    conn.execute(
        """
        UPDATE rendered_assets
        SET content_hash = ?, audit_status = 'pending',
            review_state = 'review_ready', metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            new_sha,
            json.dumps(metadata, sort_keys=True),
            changed_at,
            rendered_asset_id,
        ),
    )
