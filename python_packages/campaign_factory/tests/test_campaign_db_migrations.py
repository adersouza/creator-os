from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import campaign_factory.db as campaign_db
import pytest
from campaign_factory.db import (
    _campaign_schema_checksum,
    _ensure_campaign_schema_ledger,
    _run_campaign_schema_migration,
    connect,
    init_db,
)


def _db(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(tmp_path / "campaign.db")
    init_db(conn)
    return conn


def _db_at_v1(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(tmp_path / "campaign-v1.db")
    _ensure_campaign_schema_ledger(conn)
    _run_campaign_schema_migration(
        conn, version=1, migration_id="20260730_campaign_schema_baseline_v1"
    )
    return conn


def test_campaign_schema_migrations_are_versioned_and_replay_safe(tmp_path: Path):
    conn = _db(tmp_path)
    try:
        rows = conn.execute(
            """
            SELECT migration_id, checksum, status, source_version, details_json
            FROM campaign_schema_migrations
            ORDER BY migration_id
            """
        ).fetchall()
        assert len(rows) == 3
        assert {row["status"] for row in rows} == {"applied"}
        assert all(len(row["checksum"]) == 64 for row in rows)
        assert all(row["source_version"] for row in rows)
        assert {json.loads(row["details_json"])["schemaVersion"] for row in rows} == {
            1,
            2,
            3,
        }
        assert (
            conn.execute(
                "SELECT version FROM campaign_schema_state WHERE singleton = 1"
            ).fetchone()["version"]
            == 3
        )
        assert conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='source_asset_lifecycle'"
        ).fetchone()
        assert conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='artifact_reconciliation_repairs'"
        ).fetchone()
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

        before = [tuple(row) for row in rows]
        init_db(conn)
        after = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT migration_id, checksum, status, source_version, details_json
                FROM campaign_schema_migrations
                ORDER BY migration_id
                """
            ).fetchall()
        ]
        assert after == before
    finally:
        conn.close()


def test_legacy_external_approval_is_quarantined_until_backup_is_verified(
    tmp_path: Path,
) -> None:
    conn = _db_at_v1(tmp_path)
    try:
        now = "2026-07-30T00:00:00Z"
        conn.execute(
            """
            INSERT INTO models(id, slug, name, created_at, updated_at)
            VALUES ('model_1', 'model-1', 'Model 1', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO campaigns
            (id, slug, name, root_path, created_at, updated_at)
            VALUES ('campaign_1', 'campaign-1', 'Campaign 1', '/tmp', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO campaign_governance
            (campaign_id, model_id, lifecycle_status, blocker_codes_json,
             status_reason, changed_by, effective_at, version, updated_at)
            VALUES ('campaign_1', 'model_1', 'created', '[]', 'fixture',
                    'fixture', ?, 1, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path,
             filename, status, created_at, updated_at)
            VALUES ('source_1', 'campaign_1', 'model_1', ?, '/tmp/source',
                    '/tmp/source', 'source.mp4', 'approved', ?, ?)
            """,
            ("1" * 64, now, now),
        )
        conn.commit()

        init_db(conn)

        row = conn.execute(
            """
            SELECT s.status, l.lifecycle_state, l.storage_policy, l.backup_state,
                   l.quarantine_reason
            FROM source_assets s
            JOIN source_asset_lifecycle l ON l.source_asset_id = s.id
            WHERE s.id = 'source_1'
            """
        ).fetchone()
        assert tuple(row) == (
            "quarantined",
            "quarantined",
            "external_reference",
            "unknown",
            "legacy_approved_source_requires_managed_backup",
        )
    finally:
        conn.close()


def test_campaign_schema_blocks_newer_database(tmp_path: Path):
    conn = _db(tmp_path)
    try:
        conn.execute(
            "UPDATE campaign_schema_state SET version = 999 WHERE singleton = 1"
        )
        conn.commit()
        with pytest.raises(
            RuntimeError, match="campaign_schema_newer_than_runtime:999>3"
        ):
            init_db(conn)
    finally:
        conn.close()


def test_campaign_schema_checksum_drift_fails_closed(tmp_path: Path):
    conn = _db_at_v1(tmp_path)
    try:
        conn.execute(
            """
            INSERT INTO campaign_schema_migrations
            (migration_id, checksum, status, started_at, applied_at,
             source_version, details_json, error, repair_instructions)
            VALUES ('20260730_campaign_state_evidence_guards_v1', ?,
                    'applying', '2026-07-30T00:00:00Z', NULL, 'fixture',
                    '{}', NULL, 'fixture repair')
            """,
            ("0" * 64,),
        )
        conn.commit()
        with pytest.raises(
            RuntimeError,
            match="campaign_schema_migration_checksum_drift:"
            "20260730_campaign_state_evidence_guards_v1",
        ):
            init_db(conn)
    finally:
        conn.close()


def test_interrupted_campaign_migration_is_retried(tmp_path: Path):
    conn = _db_at_v1(tmp_path)
    try:
        conn.execute(
            """
            INSERT INTO campaign_schema_migrations
            (migration_id, checksum, status, started_at, applied_at,
             source_version, details_json, error, repair_instructions)
            VALUES ('20260730_campaign_state_evidence_guards_v1', ?,
                    'applying', '2026-07-30T00:00:00Z', NULL, 'fixture',
                    '{}', NULL, 'fixture repair')
            """,
            (
                _campaign_schema_checksum(
                    2, "20260730_campaign_state_evidence_guards_v1"
                ),
            ),
        )
        conn.commit()

        init_db(conn)

        assert (
            conn.execute(
                "SELECT version FROM campaign_schema_state WHERE singleton = 1"
            ).fetchone()["version"]
            == 3
        )
        assert (
            conn.execute(
                """
                SELECT status FROM campaign_schema_migrations
                WHERE migration_id =
                  '20260730_campaign_state_evidence_guards_v1'
                """
            ).fetchone()["status"]
            == "applied"
        )
    finally:
        conn.close()


def test_campaign_checksum_excludes_future_dispatch_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_id = "20260730_campaign_schema_baseline_v1"
    before = _campaign_schema_checksum(1, migration_id)

    monkeypatch.setattr(
        campaign_db,
        "_CAMPAIGN_SCHEMA_MIGRATIONS",
        (*campaign_db._CAMPAIGN_SCHEMA_MIGRATIONS, (4, "future_v1")),
    )
    monkeypatch.setattr(
        campaign_db,
        "_campaign_schema_postcondition",
        lambda conn, *, version: None,
    )

    assert _campaign_schema_checksum(1, migration_id) == before


def test_later_campaign_migration_rolls_back_and_retries(tmp_path: Path) -> None:
    conn = _db_at_v1(tmp_path)
    migration_id = "20260730_campaign_state_evidence_guards_v1"
    try:
        conn.execute("DROP TABLE activity_events")
        conn.commit()

        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            _run_campaign_schema_migration(
                conn,
                version=2,
                migration_id=migration_id,
            )

        assert (
            conn.execute(
                "SELECT version FROM campaign_schema_state WHERE singleton = 1"
            ).fetchone()["version"]
            == 1
        )
        assert (
            conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type='trigger'
                  AND name='approval_decisions_immutable_update'
                """
            ).fetchone()
            is None
        )
        failed = conn.execute(
            """
            SELECT status, error FROM campaign_schema_migrations
            WHERE migration_id = ?
            """,
            (migration_id,),
        ).fetchone()
        assert failed["status"] == "failed"
        assert "no such table" in failed["error"]

        conn.execute(
            """
            CREATE TABLE activity_events (
              id TEXT PRIMARY KEY,
              event_type TEXT NOT NULL,
              status TEXT NOT NULL,
              message TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        _run_campaign_schema_migration(conn, version=2, migration_id=migration_id)

        assert (
            conn.execute(
                "SELECT version FROM campaign_schema_state WHERE singleton = 1"
            ).fetchone()["version"]
            == 2
        )
        assert (
            conn.execute(
                "SELECT status FROM campaign_schema_migrations WHERE migration_id = ?",
                (migration_id,),
            ).fetchone()["status"]
            == "applied"
        )
    finally:
        conn.close()


def test_legacy_duplicates_are_reported_without_deleting_rows(tmp_path: Path):
    conn = _db_at_v1(tmp_path)
    try:
        now = "2026-07-30T00:00:00Z"
        conn.execute(
            """
            INSERT INTO models(id, slug, name, created_at, updated_at)
            VALUES ('model_1', 'model-1', 'Model 1', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO campaigns
            (id, slug, name, root_path, created_at, updated_at)
            VALUES ('campaign_1', 'campaign-1', 'Campaign 1', '/tmp', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO campaign_governance
            (campaign_id, model_id, lifecycle_status, blocker_codes_json,
             status_reason, changed_by, effective_at, version, updated_at)
            VALUES ('campaign_1', 'model_1', 'created', '[]', 'fixture',
                    'fixture', ?, 1, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO source_assets
            (id, campaign_id, model_id, content_hash, original_path, stored_path,
             filename, created_at, updated_at)
            VALUES ('source_1', 'campaign_1', 'model_1', ?, '/tmp/source',
                    '/tmp/source', 'source.mp4', ?, ?)
            """,
            ("1" * 64, now, now),
        )
        conn.execute(
            """
            INSERT INTO rendered_assets
            (id, campaign_id, source_asset_id, content_hash, output_path,
             campaign_path, filename, created_at, updated_at)
            VALUES ('asset_1', 'campaign_1', 'source_1', ?, '/tmp/final',
                    '/tmp/final', 'final.mp4', ?, ?)
            """,
            ("2" * 64, now, now),
        )
        conn.execute("DROP INDEX idx_asset_account_assignments_uniqueness")
        for assignment_id in ("assignment_1", "assignment_2"):
            conn.execute(
                """
                INSERT INTO asset_account_assignments
                (id, campaign_id, rendered_asset_id, planned_window_start,
                 created_at, updated_at)
                VALUES (?, 'campaign_1', 'asset_1', ?, ?, ?)
                """,
                (assignment_id, now, now, now),
            )
        conn.execute("DELETE FROM campaign_schema_migrations")
        conn.execute("UPDATE campaign_schema_state SET version = 0 WHERE singleton = 1")
        conn.commit()

        with pytest.raises(
            RuntimeError,
            match="campaign_schema_duplicate_repair_required:asset_account_assignments",
        ):
            init_db(conn)
        assert (
            conn.execute("SELECT COUNT(*) FROM asset_account_assignments").fetchone()[0]
            == 2
        )
        failed = conn.execute(
            """
            SELECT status, error FROM campaign_schema_migrations
            WHERE migration_id = '20260730_campaign_schema_baseline_v1'
            """
        ).fetchone()
        assert failed["status"] == "failed"
        assert "assignment_1" not in failed["error"]

        conn.execute("DELETE FROM asset_account_assignments WHERE id = 'assignment_2'")
        conn.commit()
        init_db(conn)
        assert (
            conn.execute("SELECT COUNT(*) FROM asset_account_assignments").fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_campaign_evidence_and_state_guards_are_database_enforced(tmp_path: Path):
    conn = _db(tmp_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="invalid approval decision"):
            conn.execute(
                """
                INSERT INTO approval_decisions
                (id, campaign_id, rendered_asset_id, decision, created_at)
                VALUES ('bad', 'missing', 'missing', 'maybe', '2026-07-30T00:00:00Z')
                """
            )
        with pytest.raises(sqlite3.IntegrityError, match="invalid pipeline job state"):
            conn.execute(
                """
                INSERT INTO pipeline_jobs
                (id, job_type, status, effect_state, recovery_policy, input_json,
                 result_json, attempt_count, created_at, updated_at)
                VALUES ('bad_job', 'test', 'invented', 'PRE_EFFECT',
                        'NEVER_AUTOMATIC', '{}', '{}', 0,
                        '2026-07-30T00:00:00Z', '2026-07-30T00:00:00Z')
                """
            )

        conn.execute(
            """
            INSERT INTO activity_events
            (id, event_type, status, message, created_at)
            VALUES ('evt_1', 'test', 'info', 'evidence', '2026-07-30T00:00:00Z')
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE activity_events SET message = 'changed'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM activity_events")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                """
                UPDATE campaign_schema_migrations
                SET checksum = ?
                WHERE migration_id = '20260730_campaign_schema_baseline_v1'
                """,
                ("0" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                """
                DELETE FROM campaign_schema_migrations
                WHERE migration_id = '20260730_campaign_schema_baseline_v1'
                """
            )
    finally:
        conn.close()
