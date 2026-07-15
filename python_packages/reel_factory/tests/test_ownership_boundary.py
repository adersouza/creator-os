from __future__ import annotations

import sqlite3
from pathlib import Path

from reel_factory.legacy_outcome_evidence import export_legacy_outcome_evidence
from reel_factory.manifest import Manifest

RETIRED_TABLES = {
    "reel_outcomes",
    "publish_metrics",
    "winner_dna",
    "review_decisions",
    "review_decision_history",
    "operator_ratings",
    "experiments",
    "experiment_assignments",
    "cost_events",
}


def test_fresh_reel_manifest_owns_only_worker_state(tmp_path: Path) -> None:
    manifest = Manifest(tmp_path / "manifest.json")
    tables = {
        str(row[0])
        for row in manifest.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    assert tables.isdisjoint(RETIRED_TABLES)
    variation_columns = {
        str(row[1])
        for row in manifest.conn.execute("PRAGMA table_info(variations)").fetchall()
    }
    assert "review_state" not in variation_columns


def test_legacy_evidence_export_is_read_only(tmp_path: Path) -> None:
    source = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE reel_outcomes (outcome_id TEXT, views INTEGER)")
    conn.execute("INSERT INTO reel_outcomes VALUES ('old_1', 7)")
    conn.execute("CREATE TABLE review_decisions (decision_id TEXT)")
    conn.execute("INSERT INTO review_decisions VALUES ('review_1')")
    conn.commit()
    before = source.read_bytes()

    result = export_legacy_outcome_evidence(source)

    assert result["readOnly"] is True
    assert result["rowCounts"] == {"reel_outcomes": 1, "review_decisions": 1}
    assert source.read_bytes() == before
