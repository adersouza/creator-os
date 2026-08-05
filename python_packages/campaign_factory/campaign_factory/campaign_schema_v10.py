"""Add unified cost/authorization columns to pre-existing campaign databases.

``cost_tracker.CREATE_TABLE_SQL`` has carried ``cost_state``, ``usd_cost_state``
and ``unknown_reason`` for some time, so every freshly created database has them.
No migration ever added them to a database created before that, and
``CREATE TABLE IF NOT EXISTS`` is a no-op on an existing table. The v5 unified
cost migration adds eleven other columns but not these three.

The result was that any database predating those columns could never execute a
paid action: ``all_provider_cost.ensure_unified_cost_columns`` fails closed with
``campaign_schema_v5_required:ai_cost_events_columns:...``. Tests never caught it
because they build new databases, which already have the columns.

Column definitions here are copied verbatim from ``cost_tracker`` so a migrated
database and a freshly created one are identical, including CHECK constraints
and defaults.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Final

MIGRATION_ID: Final = "20260805_unified_cost_state_columns_v1"

# name -> DDL fragment, verbatim from cost_tracker.CREATE_TABLE_SQL.
COST_STATE_COLUMNS: Final[dict[str, str]] = {
    "cost_state": (
        "TEXT NOT NULL DEFAULT 'estimated' "
        "CHECK(cost_state IN ('actual', 'estimated', 'unknown'))"
    ),
    "usd_cost_state": (
        "TEXT NOT NULL DEFAULT 'known' CHECK(usd_cost_state IN ('known', 'unknown'))"
    ),
    "unknown_reason": "TEXT",
}

# Same defect in provider_spend_authorizations: v5's AUTHORIZATION_TABLE_SQL
# declares these four, but CREATE TABLE IF NOT EXISTS never adds them to a table
# that already exists, and no ALTER ever did. All nullable, so no backfill.
AUTHORIZATION_COLUMNS: Final[dict[str, str]] = {
    "creator_id": "TEXT",
    "identity_profile_id": "TEXT",
    "governance_fingerprint": "TEXT",
    "governance_context_json": "TEXT",
}


def checksum(migration_id: str) -> str:
    if migration_id != MIGRATION_ID:
        raise ValueError(f"unexpected campaign schema v10 migration id: {migration_id}")
    payload = json.dumps(
        {
            "migrationId": MIGRATION_ID,
            "costStateColumns": COST_STATE_COLUMNS,
            "authorizationColumns": AUTHORIZATION_COLUMNS,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def apply(conn: sqlite3.Connection) -> None:
    """Add any missing cost-state column. Idempotent; existing rows take defaults."""

    existing = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(ai_cost_events)")
    }
    for name, ddl in COST_STATE_COLUMNS.items():
        if name in existing:
            continue
        # SQLite cannot ALTER ... ADD COLUMN with a CHECK constraint, so the
        # constraint is enforced by a trigger for migrated databases. Fresh
        # databases keep the inline CHECK from cost_tracker.
        bare = ddl.split(" CHECK(")[0]
        conn.execute(f"ALTER TABLE ai_cost_events ADD COLUMN {name} {bare}")
    existing_auth = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(provider_spend_authorizations)")
    }
    for name, ddl in AUTHORIZATION_COLUMNS.items():
        if name not in existing_auth:
            conn.execute(
                f"ALTER TABLE provider_spend_authorizations ADD COLUMN {name} {ddl}"
            )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_ai_cost_events_cost_state_valid
        BEFORE INSERT ON ai_cost_events
        WHEN NEW.cost_state NOT IN ('actual', 'estimated', 'unknown')
          OR NEW.usd_cost_state NOT IN ('known', 'unknown')
        BEGIN
          SELECT RAISE(ABORT, 'invalid ai_cost_events cost state');
        END;
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_ai_cost_events_cost_state_valid_update
        BEFORE UPDATE ON ai_cost_events
        WHEN NEW.cost_state NOT IN ('actual', 'estimated', 'unknown')
          OR NEW.usd_cost_state NOT IN ('known', 'unknown')
        BEGIN
          SELECT RAISE(ABORT, 'invalid ai_cost_events cost state');
        END;
        """
    )


def postcondition(conn: sqlite3.Connection) -> None:
    columns = {
        str(row[1]): {"notnull": int(row[3]), "default": row[4]}
        for row in conn.execute("PRAGMA table_info(ai_cost_events)")
    }
    if missing := set(COST_STATE_COLUMNS) - columns.keys():
        raise RuntimeError(
            "campaign_schema_v10_columns_missing:" + ",".join(sorted(missing))
        )
    for name, expected in (
        ("cost_state", "'estimated'"),
        ("usd_cost_state", "'known'"),
    ):
        if columns[name]["notnull"] != 1:
            raise RuntimeError(f"campaign_schema_v10_{name}_must_be_not_null")
        if str(columns[name]["default"]) != expected:
            raise RuntimeError(f"campaign_schema_v10_{name}_default_mismatch")
    triggers = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    required = {
        "trg_ai_cost_events_cost_state_valid",
        "trg_ai_cost_events_cost_state_valid_update",
    }
    if missing_triggers := required - triggers:
        raise RuntimeError(
            "campaign_schema_v10_triggers_missing:" + ",".join(sorted(missing_triggers))
        )
    auth_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(provider_spend_authorizations)")
    }
    if missing_auth := set(AUTHORIZATION_COLUMNS) - auth_columns:
        raise RuntimeError(
            "campaign_schema_v10_authorization_columns_missing:"
            + ",".join(sorted(missing_auth))
        )
    invalid = conn.execute(
        """
        SELECT COUNT(*) FROM ai_cost_events
        WHERE cost_state NOT IN ('actual', 'estimated', 'unknown')
           OR usd_cost_state NOT IN ('known', 'unknown')
        """
    ).fetchone()[0]
    if int(invalid):
        raise RuntimeError(f"campaign_schema_v10_invalid_cost_state_rows:{invalid}")
