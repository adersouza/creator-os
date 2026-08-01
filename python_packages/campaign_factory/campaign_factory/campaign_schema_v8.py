from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Final

MIGRATION_ID: Final = "20260801_learning_cohort_schema_v1"

LEARNING_COHORT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS learning_cohorts (
  id TEXT PRIMARY KEY,
  campaign_slug TEXT NOT NULL,
  creator TEXT NOT NULL,
  soul_id TEXT NOT NULL,
  account_handle TEXT NOT NULL,
  timezone TEXT NOT NULL,
  start_date TEXT NOT NULL,
  seed TEXT NOT NULL,
  status TEXT NOT NULL,
  autoposter_enabled INTEGER NOT NULL DEFAULT 0,
  automatic_trial_graduation INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_cohort_assignments (
  id TEXT PRIMARY KEY,
  cohort_id TEXT NOT NULL,
  day_index INTEGER NOT NULL,
  arm TEXT NOT NULL CHECK (arm IN ('ranked', 'control')),
  surface TEXT NOT NULL CHECK (surface IN ('regular_reel', 'trial_reel')),
  scheduled_for TEXT NOT NULL,
  assignment_seed TEXT NOT NULL,
  reference_id TEXT,
  candidate_rank INTEGER,
  source_family TEXT,
  perceptual_cluster TEXT,
  content_fingerprint TEXT,
  source_asset_id TEXT,
  rendered_asset_id TEXT,
  artifact_path TEXT,
  lineage_path TEXT,
  provider_reservation_id TEXT,
  draft_id TEXT,
  post_id TEXT,
  published_at TEXT,
  generation_state TEXT NOT NULL DEFAULT 'planned',
  approval_state TEXT NOT NULL DEFAULT 'pending',
  schedule_state TEXT NOT NULL DEFAULT 'blocked_pending_approval',
  publish_state TEXT NOT NULL DEFAULT 'not_published',
  metric_1h_state TEXT NOT NULL DEFAULT 'pending',
  metric_24h_state TEXT NOT NULL DEFAULT 'pending',
  metric_72h_state TEXT NOT NULL DEFAULT 'not_required',
  reward_24h REAL,
  retry_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(cohort_id, day_index, surface),
  UNIQUE(cohort_id, content_fingerprint),
  FOREIGN KEY(cohort_id) REFERENCES learning_cohorts(id)
);
CREATE INDEX IF NOT EXISTS idx_learning_cohort_assignment_state
  ON learning_cohort_assignments(cohort_id, day_index, generation_state);
"""

_ADDITIVE_ASSIGNMENT_COLUMNS: Final = {
    "source_asset_id": "TEXT",
    "rendered_asset_id": "TEXT",
    "artifact_path": "TEXT",
    "lineage_path": "TEXT",
    "published_at": "TEXT",
}


def checksum(migration_id: str) -> str:
    if migration_id != MIGRATION_ID:
        raise ValueError(f"unexpected campaign schema v8 migration id: {migration_id}")
    payload = json.dumps(
        {
            "migrationId": MIGRATION_ID,
            "schemaSql": LEARNING_COHORT_SCHEMA_SQL,
            "additiveColumns": _ADDITIVE_ASSIGNMENT_COLUMNS,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def apply(conn: sqlite3.Connection) -> None:
    _execute_transactional_script(conn, LEARNING_COHORT_SCHEMA_SQL)
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(learning_cohort_assignments)")
    }
    for name, definition in _ADDITIVE_ASSIGNMENT_COLUMNS.items():
        if name not in columns:
            conn.execute(
                f"ALTER TABLE learning_cohort_assignments ADD COLUMN {name} {definition}"
            )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_learning_cohort_assignment_source
        ON learning_cohort_assignments(cohort_id, source_asset_id)"""
    )


def postcondition(conn: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    required_tables = {"learning_cohorts", "learning_cohort_assignments"}
    if missing := required_tables - tables:
        raise RuntimeError(
            "campaign_schema_v8_tables_missing:" + ",".join(sorted(missing))
        )
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(learning_cohort_assignments)")
    }
    if missing := set(_ADDITIVE_ASSIGNMENT_COLUMNS) - columns:
        raise RuntimeError(
            "campaign_schema_v8_columns_missing:" + ",".join(sorted(missing))
        )
    indexes = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    required_indexes = {
        "idx_learning_cohort_assignment_state",
        "idx_learning_cohort_assignment_source",
    }
    if missing := required_indexes - indexes:
        raise RuntimeError(
            "campaign_schema_v8_indexes_missing:" + ",".join(sorted(missing))
        )


def _execute_transactional_script(conn: sqlite3.Connection, script: str) -> None:
    statement = ""
    for line in script.splitlines():
        statement += f"{line}\n"
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise RuntimeError("campaign_schema_v8_sql_incomplete")
