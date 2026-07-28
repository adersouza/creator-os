from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from campaign_factory.source_governance import apply_decision, plan_decision


def _conn(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE models (id TEXT PRIMARY KEY, slug TEXT);
        CREATE TABLE campaigns (id TEXT PRIMARY KEY, slug TEXT);
        CREATE TABLE source_assets (
          id TEXT PRIMARY KEY, campaign_id TEXT, model_id TEXT,
          content_hash TEXT, stored_path TEXT, status TEXT, updated_at TEXT
        );
        CREATE TABLE activity_events (
          id TEXT PRIMARY KEY, event_type TEXT, campaign_id TEXT,
          source_asset_id TEXT, status TEXT, message TEXT,
          metadata_json TEXT, created_at TEXT
        );
        INSERT INTO models VALUES ('model_stacey', 'stacey');
        INSERT INTO campaigns VALUES ('campaign_1', 'stacey-main');
        """
    )
    source = tmp_path / "stacey.png"
    source.write_bytes(b"approved-stacey-source")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    conn.execute(
        "INSERT INTO source_assets VALUES "
        "('src_1', 'campaign_1', 'model_stacey', ?, ?, 'imported', 'now')",
        (digest, str(source)),
    )
    return conn, source


def test_source_approval_is_dry_run_by_default_and_hash_bound(tmp_path: Path) -> None:
    conn, source = _conn(tmp_path)
    plan = plan_decision(
        conn,
        creator="stacey",
        source=str(source),
        decision="approved",
        operator="operator",
        reason="reviewed identity and composition",
    )
    assert plan["wouldChange"] is True
    assert conn.execute("SELECT status FROM source_assets").fetchone()[0] == "imported"

    result = apply_decision(conn, plan)
    assert result["changed"] is True
    assert conn.execute("SELECT status FROM source_assets").fetchone()[0] == "approved"
    assert conn.execute("SELECT count(*) FROM activity_events").fetchone()[0] == 1


def test_source_approval_rejects_changed_bytes(tmp_path: Path) -> None:
    conn, source = _conn(tmp_path)
    source.write_bytes(b"substituted")
    with pytest.raises(ValueError, match="SHA-256"):
        plan_decision(
            conn,
            creator="stacey",
            source="src_1",
            decision="approved",
            operator="operator",
            reason="reviewed",
        )


def test_source_approval_cannot_cross_creator(tmp_path: Path) -> None:
    conn, _ = _conn(tmp_path)
    with pytest.raises(ValueError, match="exactly one creator-bound"):
        plan_decision(
            conn,
            creator="larissa",
            source="src_1",
            decision="approved",
            operator="operator",
            reason="wrong creator",
        )
