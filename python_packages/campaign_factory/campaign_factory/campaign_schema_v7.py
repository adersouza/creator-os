from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Final

MIGRATION_ID: Final = "20260730_learning_governance_registry_v1"

LEARNING_GOVERNANCE_SCHEMA_SQL = """
CREATE TABLE learning_governance_registry (
  id TEXT PRIMARY KEY,
  root_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK(revision > 0),
  previous_revision_id TEXT,
  event_key TEXT NOT NULL UNIQUE,
  campaign_id TEXT,
  experiment_id TEXT,
  recommendation_item_id TEXT,
  knowledge_pack_id TEXT,
  creator TEXT NOT NULL,
  creator_identity_profile TEXT NOT NULL DEFAULT '',
  account_id TEXT NOT NULL DEFAULT '',
  content_intent TEXT NOT NULL,
  evidence_class TEXT NOT NULL CHECK(evidence_class IN (
    'correlation', 'experiment_result', 'operator_preference', 'production_rule'
  )),
  state TEXT NOT NULL CHECK(state IN (
    'designed', 'assigned', 'measured', 'interpreted', 'recommended',
    'policy_authorized', 'rolled_back'
  )),
  hypothesis_json TEXT NOT NULL DEFAULT '{}',
  assignment_refs_json TEXT NOT NULL DEFAULT '[]',
  cohort_refs_json TEXT NOT NULL DEFAULT '[]',
  metric_contract_json TEXT NOT NULL DEFAULT '{}',
  sample_requirement_json TEXT NOT NULL DEFAULT '{}',
  measurement_window_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT NOT NULL DEFAULT '{}',
  operator_interpretation_json TEXT NOT NULL DEFAULT '{}',
  recommendation_json TEXT NOT NULL DEFAULT '{}',
  production_policy_json TEXT NOT NULL DEFAULT '{}',
  rollback_json TEXT NOT NULL DEFAULT '{}',
  eligibility_json TEXT NOT NULL DEFAULT '{}',
  record_fingerprint TEXT NOT NULL UNIQUE CHECK(length(record_fingerprint) = 64),
  created_at TEXT NOT NULL,
  UNIQUE(root_id, revision),
  FOREIGN KEY(previous_revision_id) REFERENCES learning_governance_registry(id),
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(experiment_id) REFERENCES creative_plan_experiments(id)
    ON UPDATE CASCADE,
  FOREIGN KEY(recommendation_item_id) REFERENCES recommendation_items(id)
    ON UPDATE CASCADE,
  FOREIGN KEY(knowledge_pack_id) REFERENCES reference_knowledge_packs(id)
    ON UPDATE CASCADE
);

CREATE INDEX idx_learning_governance_root
  ON learning_governance_registry(root_id, revision DESC);
CREATE INDEX idx_learning_governance_recommendation
  ON learning_governance_registry(recommendation_item_id, revision DESC);
CREATE INDEX idx_learning_governance_experiment
  ON learning_governance_registry(experiment_id, revision DESC);
CREATE INDEX idx_learning_governance_scope
  ON learning_governance_registry(
    creator, creator_identity_profile, account_id, content_intent,
    state, revision DESC
  );

CREATE TRIGGER learning_governance_registry_no_update
BEFORE UPDATE ON learning_governance_registry
BEGIN
  SELECT RAISE(ABORT, 'learning governance revisions are immutable');
END;

CREATE TRIGGER learning_governance_registry_no_delete
BEFORE DELETE ON learning_governance_registry
BEGIN
  SELECT RAISE(ABORT, 'learning governance revisions are retained evidence');
END;
"""

REQUIRED_TABLES = frozenset({"learning_governance_registry"})
REQUIRED_INDEXES = frozenset(
    {
        "idx_learning_governance_root",
        "idx_learning_governance_recommendation",
        "idx_learning_governance_experiment",
        "idx_learning_governance_scope",
    }
)
REQUIRED_TRIGGERS = frozenset(
    {
        "learning_governance_registry_no_update",
        "learning_governance_registry_no_delete",
    }
)


def checksum(migration_id: str) -> str:
    if migration_id != MIGRATION_ID:
        raise ValueError(f"unexpected campaign schema v7 migration id: {migration_id}")
    payload = json.dumps(
        {
            "migrationId": MIGRATION_ID,
            "schemaSql": LEARNING_GOVERNANCE_SCHEMA_SQL,
            "requiredTables": sorted(REQUIRED_TABLES),
            "requiredIndexes": sorted(REQUIRED_INDEXES),
            "requiredTriggers": sorted(REQUIRED_TRIGGERS),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def apply(conn: sqlite3.Connection) -> None:
    _execute_transactional_script(conn, LEARNING_GOVERNANCE_SCHEMA_SQL)


def postcondition(conn: sqlite3.Connection) -> None:
    objects: dict[str, set[str]] = {}
    for row in conn.execute(
        """
        SELECT type, name FROM sqlite_master
        WHERE type IN ('table', 'index', 'trigger')
        """
    ).fetchall():
        objects.setdefault(str(row["type"]), set()).add(str(row["name"]))
    requirements = {
        "table": REQUIRED_TABLES,
        "index": REQUIRED_INDEXES,
        "trigger": REQUIRED_TRIGGERS,
    }
    for kind, required in requirements.items():
        if missing := required - objects.get(kind, set()):
            raise RuntimeError(
                f"campaign_schema_v7_{kind}s_missing:" + ",".join(sorted(missing))
            )


def _execute_transactional_script(conn: sqlite3.Connection, script: str) -> None:
    statement = ""
    for line in script.splitlines():
        statement += f"{line}\n"
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise RuntimeError("campaign_schema_v7_sql_incomplete")
