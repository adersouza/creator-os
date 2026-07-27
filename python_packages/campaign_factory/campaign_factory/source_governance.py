"""Explicit, hash-bound creator source approval for normal production."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import get_settings


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    return conn


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
        "wouldChange": str(row["status"]).lower() != decision,
    }


def apply_decision(conn: sqlite3.Connection, plan: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    if plan["wouldChange"]:
        conn.execute(
            "UPDATE source_assets SET status = ?, updated_at = ? WHERE id = ?",
            (plan["decision"], now, plan["sourceAssetId"]),
        )
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
                (plan["sourceAssetId"],),
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
        conn.commit()
    return {
        **plan,
        "applied": True,
        "changed": bool(plan["wouldChange"]),
        "decidedAt": now,
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
        else:
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
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
