from __future__ import annotations

import sqlite3

from campaign_factory.learning_recovery import reset_failed_capped


def test_failed_capped_reset_is_exact_and_audited() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE learning_fanout_ledger (
          post_id TEXT, snapshot_at TEXT, destination TEXT, status TEXT,
          attempt_count INTEGER, last_error TEXT, updated_at TEXT,
          PRIMARY KEY(post_id, snapshot_at, destination)
        );
        CREATE TABLE manager_decisions (
          id TEXT PRIMARY KEY, decision_type TEXT, reason TEXT,
          source_system TEXT, explanation TEXT, context_snapshot_json TEXT,
          decision_payload_json TEXT, status TEXT, created_at TEXT, updated_at TEXT
        );
        INSERT INTO learning_fanout_ledger VALUES (
          'post-1', '2026-07-29T12:00:00Z', 'reference',
          'failed_capped', 5, 'provider timeout', '2026-07-29T13:00:00Z'
        );
        """
    )

    result = reset_failed_capped(
        conn,
        post_id="post-1",
        snapshot_at="2026-07-29T12:00:00Z",
        destination="reference",
        operator="operator-1",
        reason="provider recovered",
        apply=True,
    )

    row = conn.execute("SELECT * FROM learning_fanout_ledger").fetchone()
    audit = conn.execute("SELECT * FROM manager_decisions").fetchone()
    assert result["status"] == "applied"
    assert row["status"] == "pending"
    assert row["attempt_count"] == 0
    assert row["last_error"] is None
    assert audit["decision_type"] == "learning_failed_capped_reset"
    assert audit["status"] == "applied"
