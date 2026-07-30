from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from reference_factory.db import SCHEMA, _migrations, _schema_statements, connect
from reference_factory.db_migrations import Migration, run_migrations


def test_clean_database_records_version_and_enforces_evidence(tmp_path: Path) -> None:
    conn = connect(tmp_path / "reference.sqlite")

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert [
        tuple(row)
        for row in conn.execute(
            "SELECT version, status FROM reference_schema_migrations ORDER BY version"
        )
    ] == [(1, "applied"), (2, "applied"), (3, "applied")]
    assert (
        conn.execute(
            """
        SELECT COUNT(*) FROM sqlite_master
        WHERE type='table' AND name IN (
          'reference_lifecycle_events',
          'reference_lifecycle_state',
          'reference_pattern_lifecycle_events',
          'reference_pattern_lifecycle_state'
        )
        """
        ).fetchone()[0]
        == 4
    )
    with pytest.raises(
        sqlite3.IntegrityError, match="invalid reference analysis status"
    ):
        conn.execute(
            """
            INSERT INTO reference_analysis_jobs (
              id, reference_id, status, prompt_text, created_at, updated_at
            ) VALUES ('bad', 'missing', 'invented', '', '', '')
            """
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO video_probes (reference_id, valid, probed_at)
            VALUES ('missing', 1, '')
            """
        )


def test_unversioned_historical_schema_upgrades(tmp_path: Path) -> None:
    db_path = tmp_path / "reference.sqlite"
    legacy = sqlite3.connect(db_path)
    for statement in _schema_statements_from(SCHEMA, "TABLE"):
        legacy.execute(statement)
    legacy.commit()
    legacy.close()

    upgraded = connect(db_path)

    assert upgraded.execute("PRAGMA user_version").fetchone()[0] == 3
    assert (
        upgraded.execute(
            "SELECT COUNT(*) FROM reference_schema_migrations WHERE status='applied'"
        ).fetchone()[0]
        == 3
    )


def test_failed_migration_is_recorded_and_retries(tmp_path: Path) -> None:
    db_path = tmp_path / "retry.sqlite"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    should_fail = True

    def apply(db: sqlite3.Connection) -> None:
        db.execute("CREATE TABLE retry_subject (id TEXT PRIMARY KEY)")
        if should_fail:
            raise RuntimeError("simulated interruption")

    migration = Migration(1, "retry_v1", "stable", apply, lambda db: None)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        run_migrations(conn, (migration,))
    assert (
        conn.execute(
            "SELECT status FROM reference_schema_migrations WHERE migration_id='retry_v1'"
        ).fetchone()[0]
        == "failed"
    )
    assert (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='retry_subject'"
        ).fetchone()
        is None
    )

    should_fail = False
    run_migrations(conn, (migration,))
    assert (
        conn.execute(
            "SELECT status FROM reference_schema_migrations WHERE migration_id='retry_v1'"
        ).fetchone()[0]
        == "applied"
    )


def test_checksum_drift_and_newer_schema_fail_closed(tmp_path: Path) -> None:
    drift = tmp_path / "drift.sqlite"
    conn = sqlite3.connect(drift)
    conn.row_factory = sqlite3.Row
    _create_ledger(conn)
    first = _migrations()[0]
    conn.execute(
        """
        INSERT INTO reference_schema_migrations (
          migration_id, version, checksum, status, started_at, source_version,
          repair_instructions
        ) VALUES (?, ?, 'wrong', 'applied', '', '', '')
        """,
        (first.migration_id, first.version),
    )
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="checksum_drift"):
        connect(drift)

    newer = tmp_path / "newer.sqlite"
    conn = sqlite3.connect(newer)
    conn.execute("PRAGMA user_version=99")
    conn.close()
    with pytest.raises(RuntimeError, match="newer_than_runtime"):
        connect(newer)
    probe = sqlite3.connect(newer)
    assert (
        probe.execute(
            """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='reference_schema_migrations'
        """
        ).fetchone()
        is None
    )


def test_reference_evidence_and_applied_migrations_are_immutable(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "reference.sqlite")
    conn.execute(
        """
        INSERT INTO learning_runs (
          id, analyzer_version, limit_count, summary_json, created_at
        ) VALUES ('run', 'v1', 1, '{}', '')
        """
    )
    with pytest.raises(sqlite3.IntegrityError, match="learning runs are immutable"):
        conn.execute("UPDATE learning_runs SET analyzer_version='v2' WHERE id='run'")
    with pytest.raises(
        sqlite3.IntegrityError, match="applied reference migrations are immutable"
    ):
        conn.execute(
            "DELETE FROM reference_schema_migrations WHERE migration_id=?",
            (_migrations()[0].migration_id,),
        )


def _schema_statements_from(schema: str, kind: str) -> list[str]:
    # Exercise the same current unversioned schema an older runtime left behind.
    assert schema is SCHEMA
    return _schema_statements(kind)


def _create_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE reference_schema_migrations (
          migration_id TEXT PRIMARY KEY,
          version INTEGER NOT NULL UNIQUE,
          checksum TEXT NOT NULL,
          status TEXT NOT NULL,
          started_at TEXT NOT NULL,
          applied_at TEXT,
          source_version TEXT NOT NULL,
          error TEXT,
          repair_instructions TEXT NOT NULL
        )
        """
    )
