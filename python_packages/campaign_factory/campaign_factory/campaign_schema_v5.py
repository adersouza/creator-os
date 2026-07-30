from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Final

MIGRATION_ID: Final = "20260730_orchestration_cost_guards_v2"

# These are immutable migration inputs. Runtime provider/cost schemas evolve
# through later migrations, never by changing this historical snapshot.
ORCHESTRATION_GUARDS_SQL = """
DROP TRIGGER IF EXISTS operator_authority_events_immutable_update;

CREATE TRIGGER operator_authority_events_immutable_update
BEFORE UPDATE ON operator_authority_events
WHEN NEW.id != OLD.id
  OR NEW.operation_id != OLD.operation_id
  OR NEW.effect_class != OLD.effect_class
  OR NEW.decision != OLD.decision
  OR NEW.actor_fingerprint != OLD.actor_fingerprint
  OR NEW.role != OLD.role
  OR NEW.request_fingerprint != OLD.request_fingerprint
  OR NEW.reason != OLD.reason
  OR NEW.created_at != OLD.created_at
  OR NEW.idempotency_key IS NOT OLD.idempotency_key
  OR NEW.preview != OLD.preview
  OR NEW.apply_requested != OLD.apply_requested
  OR NEW.rollback_owner IS NOT OLD.rollback_owner
  OR NEW.reconciliation_owner IS NOT OLD.reconciliation_owner
  OR NEW.attempt_count < OLD.attempt_count
  OR NEW.attempt_count > OLD.attempt_count + 1
  OR (
    NEW.attempt_count = OLD.attempt_count + 1
    AND NEW.execution_state != 'claimed'
  )
  OR (
    NEW.execution_state = OLD.execution_state
    AND (
      NEW.attempt_count != OLD.attempt_count
      OR NEW.claim_updated_at IS NOT OLD.claim_updated_at
      OR NEW.completed_at IS NOT OLD.completed_at
      OR NEW.outcome_json IS NOT OLD.outcome_json
      OR NEW.error_json IS NOT OLD.error_json
      OR NEW.retryable != OLD.retryable
    )
  )
  OR NOT (
    NEW.execution_state = OLD.execution_state
    OR (OLD.execution_state = 'claimed'
        AND NEW.execution_state IN ('succeeded', 'failed'))
    OR (OLD.execution_state = 'failed'
        AND OLD.retryable = 1
        AND NEW.execution_state = 'claimed')
  )
  OR (
    NEW.execution_state = 'claimed'
    AND (
      NEW.completed_at IS NOT NULL
      OR NEW.outcome_json IS NOT NULL
      OR NEW.error_json IS NOT NULL
      OR NEW.retryable != 0
    )
  )
  OR (
    NEW.execution_state IN ('succeeded', 'failed')
    AND NEW.completed_at IS NULL
  )
  OR (NEW.execution_state = 'succeeded' AND NEW.outcome_json IS NULL)
  OR (NEW.execution_state = 'succeeded' AND NEW.retryable != 0)
  OR (
    OLD.execution_state = 'claimed'
    AND NEW.execution_state IN ('succeeded', 'failed')
    AND (
      NEW.attempt_count != OLD.attempt_count
      OR NEW.claim_updated_at IS NOT OLD.claim_updated_at
    )
  )
BEGIN
  SELECT RAISE(ABORT, 'operator authority event transition is invalid');
END;

CREATE TRIGGER daily_orchestrator_runs_update_guard
BEFORE UPDATE ON daily_orchestrator_runs
WHEN NEW.run_key != OLD.run_key
  OR NEW.algorithm_version != OLD.algorithm_version
  OR NEW.policy_fingerprint != OLD.policy_fingerprint
  OR NEW.requested_items != OLD.requested_items
  OR NEW.selected_items != OLD.selected_items
  OR NEW.limits_json != OLD.limits_json
  OR NEW.stop_reason != OLD.stop_reason
  OR NEW.next_run_reason != OLD.next_run_reason
  OR NEW.created_at != OLD.created_at
  OR (
    OLD.status = 'completed'
    AND NEW.status = 'completed'
    AND NEW.updated_at != OLD.updated_at
  )
  OR NOT (
    NEW.status = OLD.status
    OR (OLD.status = 'planned' AND NEW.status IN ('running', 'completed', 'blocked'))
    OR (OLD.status = 'running' AND NEW.status IN ('completed', 'blocked'))
    OR (OLD.status = 'blocked' AND NEW.status IN ('running', 'completed'))
  )
BEGIN
  SELECT RAISE(ABORT, 'daily orchestrator run evidence is immutable');
END;

CREATE TRIGGER daily_orchestrator_items_update_guard
BEFORE UPDATE ON daily_orchestrator_items
WHEN NEW.run_id != OLD.run_id
  OR NEW.ordinal != OLD.ordinal
  OR NEW.creator_id != OLD.creator_id
  OR NEW.campaign_id != OLD.campaign_id
  OR NEW.source_asset_id IS NOT OLD.source_asset_id
  OR NEW.mode != OLD.mode
  OR NEW.intent != OLD.intent
  OR NEW.max_attempts != OLD.max_attempts
  OR NEW.selection_reason_json != OLD.selection_reason_json
  OR NEW.decision_fingerprint != OLD.decision_fingerprint
  OR NEW.created_at != OLD.created_at
  OR NEW.attempt_count < OLD.attempt_count
  OR NEW.attempt_count > OLD.attempt_count + 1
  OR (NEW.attempt_count = OLD.attempt_count + 1 AND NEW.state != 'running')
  OR NOT (
    NEW.state = OLD.state
    OR (OLD.state = 'selected' AND NEW.state = 'running')
    OR (OLD.state = 'selected' AND NEW.state = 'exhausted')
    OR (OLD.state = 'running' AND NEW.state IN ('completed', 'blocked', 'exhausted'))
    OR (OLD.state = 'blocked' AND NEW.state IN ('running', 'exhausted'))
  )
  OR (NEW.state = 'completed' AND NEW.result_json IS NULL)
  OR (NEW.state != 'completed' AND NEW.result_json IS NOT NULL)
  OR (
    OLD.state = 'completed'
    AND NEW.state = 'completed'
    AND (
      NEW.attempt_count != OLD.attempt_count
      OR NEW.next_attempt_at IS NOT OLD.next_attempt_at
      OR NEW.result_json IS NOT OLD.result_json
      OR NEW.error_code IS NOT OLD.error_code
      OR NEW.updated_at != OLD.updated_at
    )
  )
BEGIN
  SELECT RAISE(ABORT, 'daily orchestrator item evidence is immutable');
END;
"""
AUTHORIZATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS provider_spend_authorizations (
    authorization_id TEXT PRIMARY KEY,
    reservation_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    campaign_id TEXT,
    cohort_id TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL UNIQUE,
    amount REAL NOT NULL,
    unit TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    provider_quote_json TEXT NOT NULL,
    creator_id TEXT,
    identity_profile_id TEXT,
    governance_fingerprint TEXT,
    governance_context_json TEXT,
    status TEXT NOT NULL CHECK(status IN ('authorized', 'consumed', 'cancelled')),
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    cancelled_at TEXT
)
"""
COST_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ai_cost_events (
    id              TEXT PRIMARY KEY,
    source_event_key TEXT,
    reservation_id  TEXT,
    campaign_id     TEXT,
    provider        TEXT NOT NULL,
    operation       TEXT NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    generations     INTEGER,
    amount          REAL,
    unit            TEXT,
    provider_quote_json TEXT,
    cohort_id       TEXT,
    estimated_cost_usd REAL NOT NULL,
    cost_state      TEXT NOT NULL DEFAULT 'estimated'
        CHECK(cost_state IN ('actual', 'estimated', 'unknown')),
    usd_cost_state  TEXT NOT NULL DEFAULT 'known'
        CHECK(usd_cost_state IN ('known', 'unknown')),
    unknown_reason  TEXT,
    metadata_json   TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""
COST_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_ai_cost_events_campaign
    ON ai_cost_events (campaign_id, created_at)
"""
COST_SOURCE_KEY_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_cost_events_source_key
    ON ai_cost_events (source_event_key)
    WHERE source_event_key IS NOT NULL
"""
AUTHORIZATION_STATUS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_provider_spend_authorizations_status
    ON provider_spend_authorizations(provider, status, issued_at)
"""
AUTHORITY_IDEMPOTENCY_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_operator_authority_idempotency
    ON operator_authority_events(operation_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL
"""
COST_AUTHORIZATION_ATTEMPT_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_cost_events_authorization_attempt
    ON ai_cost_events(authorization_id, attempt_id)
    WHERE authorization_id IS NOT NULL AND attempt_id IS NOT NULL
"""
COST_REPORT_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_ai_cost_events_unified_report
    ON ai_cost_events(provider, creator_id, campaign_id, action_type, created_at)
"""
UNIFIED_COST_COLUMNS = {
    "creator_id": "TEXT",
    "authorization_id": "TEXT",
    "action_type": "TEXT",
    "attempt_id": "TEXT",
    "run_id": "TEXT",
    "quoted_usd": "REAL",
    "authorized_usd": "REAL",
    "actual_usd": "REAL",
    "refunded_usd": "REAL NOT NULL DEFAULT 0",
    "reconciliation_state": "TEXT",
    "provider_reference": "TEXT",
}
OPERATOR_AUTHORITY_COLUMNS = {
    "idempotency_key": "TEXT",
    "preview": "INTEGER NOT NULL DEFAULT 0",
    "apply_requested": "INTEGER NOT NULL DEFAULT 0",
    "rollback_owner": "TEXT",
    "reconciliation_owner": "TEXT",
    "execution_state": (
        "TEXT NOT NULL DEFAULT 'claimed' "
        "CHECK(execution_state IN ('claimed', 'succeeded', 'failed'))"
    ),
    "attempt_count": "INTEGER NOT NULL DEFAULT 1 CHECK(attempt_count > 0)",
    "claim_updated_at": "TEXT",
    "completed_at": "TEXT",
    "outcome_json": "TEXT",
    "error_json": "TEXT",
    "retryable": "INTEGER NOT NULL DEFAULT 0 CHECK(retryable IN (0, 1))",
}
REQUIRED_TABLES = frozenset(
    {
        "ai_cost_events",
        "provider_spend_authorizations",
        "operator_authority_events",
        "daily_orchestrator_runs",
        "daily_orchestrator_items",
    }
)
REQUIRED_INDEXES = frozenset(
    {
        "idx_ai_cost_events_authorization_attempt",
        "idx_ai_cost_events_campaign",
        "idx_ai_cost_events_source_key",
        "idx_ai_cost_events_unified_report",
        "idx_daily_orchestrator_items_campaign",
        "idx_daily_orchestrator_items_creator",
        "idx_operator_authority_idempotency",
        "idx_provider_spend_authorizations_status",
    }
)
REQUIRED_TRIGGERS = frozenset(
    {
        "daily_orchestrator_items_no_delete",
        "daily_orchestrator_items_update_guard",
        "daily_orchestrator_runs_no_delete",
        "daily_orchestrator_runs_update_guard",
        "operator_authority_events_immutable_delete",
        "operator_authority_events_immutable_update",
    }
)


def checksum(migration_id: str) -> str:
    if migration_id != MIGRATION_ID:
        raise ValueError(f"unexpected campaign schema v5 migration id: {migration_id}")
    material = {
        "migrationId": MIGRATION_ID,
        "sql": {
            "authorizationTable": AUTHORIZATION_TABLE_SQL,
            "authorizationStatusIndex": AUTHORIZATION_STATUS_INDEX_SQL,
            "authorityIdempotencyIndex": AUTHORITY_IDEMPOTENCY_INDEX_SQL,
            "costAuthorizationAttemptIndex": COST_AUTHORIZATION_ATTEMPT_INDEX_SQL,
            "costReportIndex": COST_REPORT_INDEX_SQL,
            "costSourceKeyIndex": COST_SOURCE_KEY_INDEX_SQL,
            "costTable": COST_TABLE_SQL,
            "costTableIndex": COST_INDEX_SQL,
            "orchestrationGuards": ORCHESTRATION_GUARDS_SQL,
        },
        "columns": {
            "operatorAuthorityEvents": OPERATOR_AUTHORITY_COLUMNS,
            "unifiedCosts": UNIFIED_COST_COLUMNS,
        },
        "postcondition": {
            "indexes": sorted(REQUIRED_INDEXES),
            "tables": sorted(REQUIRED_TABLES),
            "triggers": sorted(REQUIRED_TRIGGERS),
        },
    }
    payload = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def apply(conn: sqlite3.Connection) -> None:
    _ensure_columns(conn, "operator_authority_events", OPERATOR_AUTHORITY_COLUMNS)
    _execute_transactional_script(conn, ORCHESTRATION_GUARDS_SQL)
    conn.execute(AUTHORITY_IDEMPOTENCY_INDEX_SQL)
    _execute_transactional_script(
        conn,
        f"{AUTHORIZATION_TABLE_SQL};\n"
        f"{COST_TABLE_SQL};\n"
        f"{COST_INDEX_SQL};\n"
        f"{COST_SOURCE_KEY_INDEX_SQL};\n"
        f"{AUTHORIZATION_STATUS_INDEX_SQL};",
    )
    _ensure_columns(conn, "ai_cost_events", UNIFIED_COST_COLUMNS)
    conn.execute(COST_AUTHORIZATION_ATTEMPT_INDEX_SQL)
    conn.execute(COST_REPORT_INDEX_SQL)


def postcondition(conn: sqlite3.Connection) -> None:
    tables = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if missing_tables := REQUIRED_TABLES - tables:
        raise RuntimeError(
            "campaign_schema_tables_missing:" + ",".join(sorted(missing_tables))
        )
    cost_columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(ai_cost_events)").fetchall()
    }
    if missing_cost_columns := set(UNIFIED_COST_COLUMNS) - cost_columns:
        raise RuntimeError(
            "campaign_schema_cost_columns_missing:"
            + ",".join(sorted(missing_cost_columns))
        )
    authority_columns = {
        str(row["name"])
        for row in conn.execute(
            "PRAGMA table_info(operator_authority_events)"
        ).fetchall()
    }
    if missing_authority_columns := (
        set(OPERATOR_AUTHORITY_COLUMNS) - authority_columns
    ):
        raise RuntimeError(
            "campaign_schema_authority_columns_missing:"
            + ",".join(sorted(missing_authority_columns))
        )
    indexes = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    if missing_indexes := REQUIRED_INDEXES - indexes:
        raise RuntimeError(
            "campaign_schema_indexes_missing:" + ",".join(sorted(missing_indexes))
        )
    _require_triggers(conn, set(REQUIRED_TRIGGERS))


def _ensure_columns(
    conn: sqlite3.Connection, table: str, columns: dict[str, str]
) -> None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if not exists:
        return
    existing = {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, ddl in columns.items():
        if name not in existing:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise


def _execute_transactional_script(conn: sqlite3.Connection, script: str) -> None:
    statement = ""
    for line in script.splitlines():
        statement += f"{line}\n"
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise RuntimeError("campaign_schema_sql_incomplete")


def _require_triggers(conn: sqlite3.Connection, required_triggers: set[str]) -> None:
    triggers = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    if missing := required_triggers - triggers:
        raise RuntimeError(
            "campaign_schema_triggers_missing:" + ",".join(sorted(missing))
        )
