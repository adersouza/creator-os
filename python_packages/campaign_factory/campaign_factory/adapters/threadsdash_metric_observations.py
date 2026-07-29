from __future__ import annotations

import hashlib
import json
from typing import Any


def record_immutable_performance_observation(
    conn: Any, snapshot: dict[str, Any]
) -> str:
    raw_json = str(snapshot.get("raw_json") or "{}")
    try:
        raw_payload = json.loads(raw_json)
    except json.JSONDecodeError:
        raw_payload = raw_json
    canonical_raw = json.dumps(
        raw_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    source_hash = hashlib.sha256(canonical_raw.encode("utf-8")).hexdigest()
    observation_id = (
        "perfobs_"
        + hashlib.sha256(
            f"{snapshot['post_id']}:{snapshot['snapshot_at']}:{source_hash}".encode()
        ).hexdigest()[:24]
    )
    previous = conn.execute(
        """
        SELECT id, source_hash
        FROM performance_snapshot_observations
        WHERE post_id = ? AND snapshot_at = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (snapshot["post_id"], snapshot["snapshot_at"]),
    ).fetchone()
    if previous is not None and previous["source_hash"] == source_hash:
        return str(previous["id"])
    normalized = {
        key: value
        for key, value in snapshot.items()
        if key not in {"id", "created_at", "raw_json"}
    }
    conn.execute(
        """
        INSERT OR IGNORE INTO performance_snapshot_observations
        (id, post_id, snapshot_at, source_hash, raw_json, normalized_json,
         supersedes_observation_id, correction_reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observation_id,
            snapshot["post_id"],
            snapshot["snapshot_at"],
            source_hash,
            canonical_raw,
            json.dumps(normalized, ensure_ascii=False, sort_keys=True),
            str(previous["id"]) if previous is not None else None,
            "source_payload_changed" if previous is not None else None,
            snapshot["created_at"],
        ),
    )
    return observation_id
