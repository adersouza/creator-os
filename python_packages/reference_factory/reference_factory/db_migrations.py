"""Explicit SQLite migration ledger for Reference Factory."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class Migration:
    version: int
    migration_id: str
    checksum_material: str
    apply: Callable[[sqlite3.Connection], None]
    postcondition: Callable[[sqlite3.Connection], None]

    @property
    def checksum(self) -> str:
        return hashlib.sha256(
            f"{self.version}:{self.migration_id}\n{self.checksum_material}".encode()
        ).hexdigest()


def run_migrations(conn: sqlite3.Connection, migrations: Sequence[Migration]) -> None:
    """Apply ordered migrations and fail closed on incompatible schema history."""

    ordered = tuple(sorted(migrations, key=lambda item: item.version))
    if not ordered or len({item.version for item in ordered}) != len(ordered):
        raise RuntimeError("reference_schema_migration_order_invalid")
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    supported = ordered[-1].version
    if current > supported:
        raise RuntimeError(f"reference_schema_newer_than_runtime:{current}>{supported}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reference_schema_migrations (
          migration_id TEXT PRIMARY KEY,
          version INTEGER NOT NULL UNIQUE,
          checksum TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('applying', 'applied', 'failed')),
          started_at TEXT NOT NULL,
          applied_at TEXT,
          source_version TEXT NOT NULL,
          error TEXT,
          repair_instructions TEXT NOT NULL
        )
        """
    )
    conn.commit()
    for migration in ordered:
        _apply_one(conn, migration)
    final = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if final != supported:
        raise RuntimeError(f"reference_schema_version_mismatch:{final}!={supported}")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError("reference_schema_foreign_key_check_failed")


def _apply_one(conn: sqlite3.Connection, migration: Migration) -> None:
    prior = conn.execute(
        """
        SELECT checksum, status FROM reference_schema_migrations
        WHERE migration_id = ?
        """,
        (migration.migration_id,),
    ).fetchone()
    if prior is not None:
        if str(prior["checksum"]) != migration.checksum:
            raise RuntimeError(
                f"reference_schema_migration_checksum_drift:{migration.migration_id}"
            )
        if str(prior["status"]) == "applied":
            migration.postcondition(conn)
            return
    now = _now()
    source_version = os.environ.get("CREATOR_OS_SOURCE_SHA") or "unknown"
    conn.execute(
        """
        INSERT INTO reference_schema_migrations (
          migration_id, version, checksum, status, started_at, applied_at,
          source_version, error, repair_instructions
        ) VALUES (?, ?, ?, 'applying', ?, NULL, ?, NULL, ?)
        ON CONFLICT(migration_id) DO UPDATE SET
          status='applying', started_at=excluded.started_at, applied_at=NULL,
          source_version=excluded.source_version, error=NULL,
          repair_instructions=excluded.repair_instructions
        """,
        (
            migration.migration_id,
            migration.version,
            migration.checksum,
            now,
            source_version,
            "restore a backup, fix the reported migration, then reconnect to retry",
        ),
    )
    conn.commit()
    try:
        conn.execute("BEGIN IMMEDIATE")
        migration.apply(conn)
        migration.postcondition(conn)
        conn.execute(f"PRAGMA user_version={migration.version}")
        conn.execute(
            """
            UPDATE reference_schema_migrations
            SET status='applied', applied_at=?, error=NULL
            WHERE migration_id=?
            """,
            (_now(), migration.migration_id),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        conn.execute(
            """
            UPDATE reference_schema_migrations
            SET status='failed', error=?
            WHERE migration_id=?
            """,
            (f"{type(exc).__name__}:{exc}"[:2000], migration.migration_id),
        )
        conn.commit()
        raise


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
