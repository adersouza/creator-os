"""Explicit, hash-bound creator source approval for normal production."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.sqlite import connect_sqlite

from .config import get_settings

SOURCE_TRANSITIONS = {
    "discovered": {"cataloged", "quarantined"},
    "cataloged": {"approved", "rejected", "quarantined", "superseded", "archived"},
    "quarantined": {"cataloged", "rejected", "archived"},
    "approved": {"rejected", "quarantined", "superseded", "archived"},
    "rejected": {"archived"},
    "superseded": {"archived"},
    "archived": {"deleted"},
    "deleted": set(),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect() -> sqlite3.Connection:
    return connect_sqlite(get_settings().db_path)


def list_sources(conn: sqlite3.Connection, *, creator: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT s.id, m.slug AS creator, c.slug AS campaign, s.filename,
               s.stored_path, s.content_hash, s.media_type, s.status,
               s.created_at, s.updated_at
        FROM source_assets s
        JOIN models m ON m.id = s.model_id
        JOIN campaigns c ON c.id = s.campaign_id
        WHERE lower(m.slug) = lower(?)
        ORDER BY s.updated_at DESC, s.id
        """,
        (creator,),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        path = Path(str(item["stored_path"])).expanduser()
        item["bytesPresent"] = path.is_file() and not path.is_symlink()
        item["hashValid"] = (
            _sha256(path.resolve()) == str(item["content_hash"])
            if item["bytesPresent"]
            else False
        )
        result.append(item)
    return result


def plan_decision(
    conn: sqlite3.Connection,
    *,
    creator: str,
    source: str,
    decision: str,
    operator: str,
    reason: str,
) -> dict[str, Any]:
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")
    if not operator.strip() or not reason.strip():
        raise ValueError("operator and reason are required")
    rows = conn.execute(
        """
        SELECT s.*, m.slug AS creator_slug, c.slug AS campaign_slug
        FROM source_assets s
        JOIN models m ON m.id = s.model_id
        JOIN campaigns c ON c.id = s.campaign_id
        WHERE lower(m.slug) = lower(?)
          AND (s.id = ? OR s.content_hash = ? OR s.stored_path = ?)
        """,
        (creator, source, source, str(Path(source).expanduser())),
    ).fetchall()
    if len(rows) != 1:
        raise ValueError(
            "source must resolve to exactly one creator-bound asset by ID, SHA, or path"
        )
    row = dict(rows[0])
    lifecycle_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_asset_lifecycle'"
    ).fetchone()
    lifecycle: sqlite3.Row | None = None
    if lifecycle_table:
        lifecycle = conn.execute(
            "SELECT * FROM source_asset_lifecycle WHERE source_asset_id = ?",
            (row["id"],),
        ).fetchone()
        if not lifecycle:
            raise ValueError(
                "source lifecycle evidence is missing; reconcile before approval"
            )
        previous_lifecycle_state = str(lifecycle["lifecycle_state"])
        if previous_lifecycle_state == "quarantined" and decision == "approved":
            raise ValueError(
                "quarantined source requires probe/intake repair before approval"
            )
        if (
            decision != previous_lifecycle_state
            and decision not in SOURCE_TRANSITIONS.get(previous_lifecycle_state, set())
        ):
            raise ValueError(
                "invalid source lifecycle transition: "
                f"{previous_lifecycle_state}->{decision}"
            )
        if (
            decision == "approved"
            and lifecycle["storage_policy"] == "external_reference"
            and lifecycle["backup_state"] != "managed"
        ):
            raise ValueError(
                "external source approval requires a verified managed backup"
            )
    path = Path(str(row["stored_path"])).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("source bytes are missing or symlinked")
    actual_sha = _sha256(path.resolve())
    if actual_sha != str(row["content_hash"]):
        raise ValueError("source SHA-256 does not match registered bytes")
    return {
        "schema": "creator_os.source_approval_plan.v1",
        "sourceAssetId": row["id"],
        "creator": row["creator_slug"],
        "campaign": row["campaign_slug"],
        "path": str(path.resolve()),
        "sha256": actual_sha,
        "previousStatus": row["status"],
        "decision": decision,
        "operator": operator.strip(),
        "reason": reason.strip(),
        "previousLifecycleState": (
            str(lifecycle["lifecycle_state"]) if lifecycle else None
        ),
        "lifecycleVersion": int(lifecycle["version"]) if lifecycle else None,
        "wouldChange": str(row["status"]).lower() != decision
        or bool(lifecycle and lifecycle["lifecycle_state"] != decision),
    }


def apply_decision(conn: sqlite3.Connection, plan: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    source_id = str(plan["sourceAssetId"])
    lifecycle_version = plan.get("lifecycleVersion")
    with conn:
        if not plan["wouldChange"]:
            current = conn.execute(
                "SELECT status FROM source_assets WHERE id = ?", (source_id,)
            ).fetchone()
            if not current or current["status"] != plan["previousStatus"]:
                raise RuntimeError("source status changed after preview")
            if lifecycle_version is not None:
                lifecycle = conn.execute(
                    """
                    SELECT lifecycle_state, version FROM source_asset_lifecycle
                    WHERE source_asset_id = ?
                    """,
                    (source_id,),
                ).fetchone()
                if (
                    not lifecycle
                    or lifecycle["lifecycle_state"] != plan["previousLifecycleState"]
                    or lifecycle["version"] != lifecycle_version
                ):
                    raise RuntimeError("source lifecycle changed after preview")
            return {
                **plan,
                "applied": True,
                "changed": False,
                "decidedAt": now,
            }
        if lifecycle_version is not None:
            lifecycle_cursor = conn.execute(
                """
                UPDATE source_asset_lifecycle
                SET lifecycle_state = ?,
                    quarantine_reason = CASE
                      WHEN ? = 'approved' THEN NULL ELSE quarantine_reason END,
                    version = version + 1, updated_at = ?
                WHERE source_asset_id = ? AND lifecycle_state = ? AND version = ?
                """,
                (
                    plan["decision"],
                    plan["decision"],
                    now,
                    source_id,
                    plan["previousLifecycleState"],
                    lifecycle_version,
                ),
            )
            if lifecycle_cursor.rowcount != 1:
                raise RuntimeError("source lifecycle changed after preview")
        source_cursor = conn.execute(
            """
            UPDATE source_assets SET status = ?, updated_at = ?
            WHERE id = ? AND status = ?
            """,
            (
                plan["decision"],
                now,
                source_id,
                plan["previousStatus"],
            ),
        )
        if source_cursor.rowcount != 1:
            raise RuntimeError("source status changed after preview")
        has_events = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='activity_events'"
        ).fetchone()
        if has_events:
            event_core = {
                "sourceAssetId": plan["sourceAssetId"],
                "sha256": plan["sha256"],
                "decision": plan["decision"],
                "operator": plan["operator"],
                "reason": plan["reason"],
                "decidedAt": now,
            }
            event_id = (
                "event_source_"
                + hashlib.sha256(
                    json.dumps(event_core, sort_keys=True).encode()
                ).hexdigest()[:20]
            )
            campaign_id = conn.execute(
                "SELECT campaign_id FROM source_assets WHERE id = ?",
                (source_id,),
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO activity_events (
                  id, event_type, campaign_id, source_asset_id, status, message,
                  metadata_json, created_at
                ) VALUES (?, 'source_approval_decided', ?, ?, 'success', ?, ?, ?)
                """,
                (
                    event_id,
                    campaign_id,
                    plan["sourceAssetId"],
                    f"Source {plan['decision']} by {plan['operator']}",
                    json.dumps(event_core, sort_keys=True),
                    now,
                ),
            )
        if lifecycle_version is not None:
            lifecycle_evidence = {
                "sha256": plan["sha256"],
                "operator": plan["operator"],
                "reason": plan["reason"],
            }
            lifecycle_id = (
                "source_lifecycle_"
                + hashlib.sha256(
                    json.dumps(
                        {
                            "sourceAssetId": source_id,
                            "previousState": plan["previousLifecycleState"],
                            "newState": plan["decision"],
                            **lifecycle_evidence,
                        },
                        sort_keys=True,
                    ).encode()
                ).hexdigest()[:20]
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO source_asset_lifecycle_events
                (id, source_asset_id, previous_state, new_state, reason,
                 actor, evidence_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lifecycle_id,
                    source_id,
                    plan["previousLifecycleState"],
                    plan["decision"],
                    plan["reason"],
                    plan["operator"],
                    json.dumps(lifecycle_evidence, sort_keys=True),
                    now,
                ),
            )
    return {
        **plan,
        "applied": True,
        "changed": bool(plan["wouldChange"]),
        "decidedAt": now,
    }


def plan_lifecycle_transition(
    conn: sqlite3.Connection,
    *,
    creator: str,
    source: str,
    new_state: str,
    operator: str,
    reason: str,
    replacement_source_asset_id: str | None = None,
) -> dict[str, Any]:
    if not operator.strip() or not reason.strip():
        raise ValueError("operator and reason are required")
    row = conn.execute(
        """
        SELECT s.*, m.slug AS creator_slug, l.lifecycle_state,
               l.storage_policy, l.backup_state, l.version
        FROM source_assets s
        JOIN models m ON m.id = s.model_id
        JOIN source_asset_lifecycle l ON l.source_asset_id = s.id
        WHERE lower(m.slug) = lower(?)
          AND (s.id = ? OR s.content_hash = ? OR s.stored_path = ?)
        """,
        (creator, source, source, str(Path(source).expanduser())),
    ).fetchall()
    if len(row) != 1:
        raise ValueError("source must resolve to exactly one governed creator asset")
    item = dict(row[0])
    previous = str(item["lifecycle_state"])
    if new_state not in SOURCE_TRANSITIONS.get(previous, set()):
        raise ValueError(
            f"invalid source lifecycle transition: {previous}->{new_state}"
        )
    path = Path(str(item["stored_path"])).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("source bytes are missing or symlinked")
    actual_sha = _sha256(path.resolve())
    if actual_sha != str(item["content_hash"]):
        raise ValueError("source SHA-256 does not match registered bytes")
    if new_state == "superseded":
        if not replacement_source_asset_id:
            raise ValueError("superseded requires replacement_source_asset_id")
        replacement = conn.execute(
            """
            SELECT s.id FROM source_assets s
            JOIN source_asset_lifecycle l ON l.source_asset_id = s.id
            WHERE s.id = ? AND s.model_id = ?
              AND l.lifecycle_state IN ('cataloged', 'approved')
            """,
            (replacement_source_asset_id, item["model_id"]),
        ).fetchone()
        if not replacement:
            raise ValueError(
                "replacement must be a governed source for the same creator"
            )
    elif replacement_source_asset_id:
        raise ValueError("replacement_source_asset_id is only valid for superseded")
    return {
        "schema": "creator_os.source_lifecycle_transition_plan.v1",
        "sourceAssetId": item["id"],
        "creator": item["creator_slug"],
        "sha256": actual_sha,
        "previousSourceStatus": item["status"],
        "previousState": previous,
        "newState": new_state,
        "operator": operator.strip(),
        "reason": reason.strip(),
        "replacementSourceAssetId": replacement_source_asset_id,
        "version": int(item["version"]),
    }


def apply_lifecycle_transition(
    conn: sqlite3.Connection, plan: dict[str, Any]
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    source_id = str(plan["sourceAssetId"])
    event_core = {
        "sourceAssetId": source_id,
        "sha256": plan["sha256"],
        "previousState": plan["previousState"],
        "newState": plan["newState"],
        "operator": plan["operator"],
        "reason": plan["reason"],
        "replacementSourceAssetId": plan.get("replacementSourceAssetId"),
        "transitionedAt": now,
    }
    event_id = (
        "source_lifecycle_"
        + hashlib.sha256(json.dumps(event_core, sort_keys=True).encode()).hexdigest()[
            :20
        ]
    )
    with conn:
        cursor = conn.execute(
            """
            UPDATE source_asset_lifecycle
            SET lifecycle_state = ?,
                quarantine_reason = CASE
                  WHEN ? = 'quarantined' THEN ? ELSE quarantine_reason END,
                tombstoned_at = CASE WHEN ? = 'deleted' THEN ? ELSE tombstoned_at END,
                version = version + 1, updated_at = ?
            WHERE source_asset_id = ? AND lifecycle_state = ? AND version = ?
            """,
            (
                plan["newState"],
                plan["newState"],
                plan["reason"],
                plan["newState"],
                now,
                now,
                source_id,
                plan["previousState"],
                plan["version"],
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("source lifecycle changed after preview")
        source_cursor = conn.execute(
            """
            UPDATE source_assets SET status = ?, updated_at = ?
            WHERE id = ? AND status = ?
            """,
            (
                plan["newState"],
                now,
                source_id,
                plan["previousSourceStatus"],
            ),
        )
        if source_cursor.rowcount != 1:
            raise RuntimeError("source status changed after preview")
        replacement = plan.get("replacementSourceAssetId")
        if replacement:
            conn.execute(
                """
                UPDATE source_asset_lifecycle
                SET supersedes_source_asset_id = ?, version = version + 1,
                    updated_at = ?
                WHERE source_asset_id = ?
                """,
                (source_id, now, replacement),
            )
        conn.execute(
            """
            INSERT INTO source_asset_lifecycle_events
            (id, source_asset_id, previous_state, new_state, reason, actor,
             evidence_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                source_id,
                plan["previousState"],
                plan["newState"],
                plan["reason"],
                plan["operator"],
                json.dumps(event_core, sort_keys=True),
                now,
            ),
        )
    return {
        **plan,
        "applied": True,
        "changed": True,
        "eventId": event_id,
        "transitionedAt": now,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--creator", required=True)
    for action in ("approve", "reject"):
        decision = sub.add_parser(action)
        decision.add_argument("--creator", required=True)
        decision.add_argument("--source", required=True)
        decision.add_argument("--operator", required=True)
        decision.add_argument("--reason", required=True)
        decision.add_argument("--apply", action="store_true")
    lifecycle = sub.add_parser("transition")
    lifecycle.add_argument("--creator", required=True)
    lifecycle.add_argument("--source", required=True)
    lifecycle.add_argument(
        "--state",
        required=True,
        choices=["quarantined", "superseded", "archived", "deleted"],
    )
    lifecycle.add_argument("--replacement-source-asset-id")
    lifecycle.add_argument("--operator", required=True)
    lifecycle.add_argument("--reason", required=True)
    lifecycle.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with _connect() as conn:
        if args.command == "list":
            payload: dict[str, Any] = {
                "schema": "creator_os.source_inventory.v1",
                "creator": args.creator,
                "sources": list_sources(conn, creator=args.creator),
            }
        elif args.command in {"approve", "reject"}:
            payload = plan_decision(
                conn,
                creator=args.creator,
                source=args.source,
                decision="approved" if args.command == "approve" else "rejected",
                operator=args.operator,
                reason=args.reason,
            )
            if args.apply:
                payload = apply_decision(conn, payload)
            else:
                payload = {**payload, "applied": False, "changed": False}
        else:
            payload = plan_lifecycle_transition(
                conn,
                creator=args.creator,
                source=args.source,
                new_state=args.state,
                operator=args.operator,
                reason=args.reason,
                replacement_source_asset_id=args.replacement_source_asset_id,
            )
            if args.apply:
                payload = apply_lifecycle_transition(conn, payload)
            else:
                payload = {**payload, "applied": False, "changed": False}
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
