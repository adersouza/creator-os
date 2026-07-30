"""Audited operator recovery for capped learning fanout rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from typing import Any

from .config import get_settings
from .core import CampaignFactory
from .persistence import utc_now


def reset_failed_capped(
    conn: sqlite3.Connection,
    *,
    post_id: str,
    snapshot_at: str,
    destination: str,
    operator: str,
    reason: str,
    apply: bool,
) -> dict[str, Any]:
    if destination not in {"campaign", "reference"}:
        raise ValueError("destination must be campaign or reference")
    if not all(
        str(value).strip() for value in (post_id, snapshot_at, operator, reason)
    ):
        raise ValueError("post, snapshot, operator, and reason are required")
    row = conn.execute(
        """
        SELECT * FROM learning_fanout_ledger
        WHERE post_id = ? AND snapshot_at = ? AND destination = ?
        """,
        (post_id, snapshot_at, destination),
    ).fetchone()
    if row is None:
        raise ValueError("learning fanout ledger row not found")
    before = dict(row)
    if before["status"] != "failed_capped":
        raise ValueError("learning fanout ledger row is not failed_capped")
    now = utc_now()
    receipt_id = (
        "mgr_"
        + hashlib.sha256(
            f"{post_id}:{snapshot_at}:{destination}:{operator}:{reason}".encode()
        ).hexdigest()[:24]
    )
    receipt = {
        "schema": "creator_os.learning_failed_capped_reset.v1",
        "receiptId": receipt_id,
        "workItemId": f"{post_id}:{snapshot_at}:{destination}",
        "authorizationId": f"operator:{operator}",
        "attemptId": receipt_id,
        "externalOperationId": None,
        "postId": post_id,
        "snapshotAt": snapshot_at,
        "destination": destination,
        "operator": operator,
        "reason": reason,
        "previousStatus": before["status"],
        "previousAttemptCount": before["attempt_count"],
        "resetAt": now,
        "apply": apply,
    }
    if not apply:
        return {**receipt, "status": "previewed", "wouldReset": True}
    with conn:
        updated = conn.execute(
            """
            UPDATE learning_fanout_ledger
            SET status = 'pending', attempt_count = 0, last_error = NULL,
                updated_at = ?
            WHERE post_id = ? AND snapshot_at = ? AND destination = ?
              AND status = 'failed_capped'
            """,
            (now, post_id, snapshot_at, destination),
        )
        if updated.rowcount != 1:
            raise RuntimeError("learning reset compare-and-swap failed")
        conn.execute(
            """
            INSERT INTO manager_decisions (
              id, decision_type, reason, source_system, explanation,
              context_snapshot_json, decision_payload_json, status,
              created_at, updated_at
            ) VALUES (?, 'learning_failed_capped_reset', ?, 'creator_os_operator',
                      ?, ?, ?, 'applied', ?, ?)
            """,
            (
                receipt_id,
                reason,
                f"{operator} reset one exact failed_capped ledger row",
                json.dumps(before, ensure_ascii=False, sort_keys=True),
                json.dumps(receipt, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
    return {**receipt, "status": "applied", "wouldReset": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-id", required=True)
    parser.add_argument("--snapshot-at", required=True)
    parser.add_argument(
        "--destination", choices=["campaign", "reference"], required=True
    )
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reason", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    factory = CampaignFactory(get_settings())
    try:
        result = reset_failed_capped(
            factory.conn,
            post_id=args.post_id,
            snapshot_at=args.snapshot_at,
            destination=args.destination,
            operator=args.operator,
            reason=args.reason,
            apply=args.apply,
        )
    finally:
        factory.close()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
