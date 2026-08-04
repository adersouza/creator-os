from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import campaign_factory.db as campaign_db
import pytest
from campaign_factory.campaign_schema_v5 import postcondition as v5_postcondition
from campaign_factory.campaign_schema_v6 import postcondition as v6_postcondition
from campaign_factory.campaign_schema_v7 import postcondition as v7_postcondition
from campaign_factory.campaign_schema_v8 import postcondition as v8_postcondition
from campaign_factory.campaign_schema_v9 import postcondition as v9_postcondition
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
        assert len(rows) == 9
        assert {row["status"] for row in rows} == {"applied"}
        assert all(len(row["checksum"]) == 64 for row in rows)
        assert all(row["source_version"] for row in rows)
        assert {json.loads(row["details_json"])["schemaVersion"] for row in rows} == {
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
        }
        assert (
            conn.execute(
                "SELECT version FROM campaign_schema_state WHERE singleton = 1"
            ).fetchone()["version"]
            == 9
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


def test_v9_allows_only_proven_provider_identity_without_canonical_source(
    tmp_path: Path,
) -> None:
    conn = _db(tmp_path)
    try:
        v9_postcondition(conn)
        columns = {
            row[1]: row[3]
            for row in conn.execute(
                "PRAGMA table_info(creator_identity_profiles)"
            ).fetchall()
        }
        assert columns["canonical_source_asset_id"] == 0
        assert "provider_identity_evidence_path" in columns
        assert "provider_identity_evidence_sha256" in columns
        table_sql = conn.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'creator_identity_profiles'
            """
        ).fetchone()[0]
        assert "provider_identity_attestation" in table_sql
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
            RuntimeError, match="campaign_schema_newer_than_runtime:999>9"
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
            == 9
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
        (*campaign_db._CAMPAIGN_SCHEMA_MIGRATIONS, (6, "future_v1")),
    )
    monkeypatch.setattr(
        campaign_db,
        "_campaign_schema_postcondition",
        lambda conn, *, version: None,
    )

    assert _campaign_schema_checksum(1, migration_id) == before


def test_applied_v4_checksum_is_frozen_and_upgrades_forward_to_v8(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "campaign-v4.db")
    try:
        _ensure_campaign_schema_ledger(conn)
        for version, migration_id in campaign_db._CAMPAIGN_SCHEMA_MIGRATIONS[:4]:
            _run_campaign_schema_migration(
                conn,
                version=version,
                migration_id=migration_id,
            )
        assert (
            _campaign_schema_checksum(4, "20260730_daily_orchestration_authority_v1")
            == "b44fff4781a02bfbd61db2a9fa57af796a6d5f89b49584c29235db3df30144a1"
        )

        init_db(conn)

        assert (
            conn.execute(
                "SELECT version FROM campaign_schema_state WHERE singleton = 1"
            ).fetchone()["version"]
            == 9
        )
        assert conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='trigger' AND name='daily_orchestrator_items_update_guard'"
        ).fetchone()
        assert conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='index' AND name='idx_ai_cost_events_unified_report'"
        ).fetchone()
    finally:
        conn.close()


def test_applied_v5_checksum_is_frozen_from_live_provider_schema_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import campaign_factory.cost_tracker as cost_tracker
    import campaign_factory.orchestration_schema as orchestration_schema
    import campaign_factory.provider_spend as provider_spend

    migration_id = "20260730_orchestration_cost_guards_v2"
    expected = "6aaa603abf9955cb652491f82dbee01903504b1a77b77398de175f65c688780a"
    assert _campaign_schema_checksum(5, migration_id) == expected

    monkeypatch.setattr(
        provider_spend,
        "AUTHORIZATION_TABLE_SQL",
        "CREATE TABLE future_authorizations(id TEXT PRIMARY KEY)",
    )
    monkeypatch.setattr(
        cost_tracker,
        "CREATE_TABLE_SQL",
        "CREATE TABLE future_costs(id TEXT PRIMARY KEY)",
    )
    monkeypatch.setattr(
        orchestration_schema,
        "DAILY_ORCHESTRATION_GUARDS_V2",
        "CREATE TRIGGER future_live_guard BEFORE UPDATE ON future BEGIN SELECT 1; END",
    )

    assert _campaign_schema_checksum(5, migration_id) == expected


def test_v5_postcondition_requires_every_guard_and_index(tmp_path: Path) -> None:
    conn = _db(tmp_path)
    try:
        conn.execute("DROP TRIGGER operator_authority_events_immutable_delete")
        conn.execute("DROP INDEX idx_provider_spend_authorizations_status")
        conn.commit()

        with pytest.raises(
            RuntimeError,
            match="campaign_schema_indexes_missing:"
            "idx_provider_spend_authorizations_status",
        ):
            v5_postcondition(conn)

        conn.execute(
            """
            CREATE INDEX idx_provider_spend_authorizations_status
            ON provider_spend_authorizations(provider, status, issued_at)
            """
        )
        conn.commit()
        with pytest.raises(
            RuntimeError,
            match="campaign_schema_triggers_missing:"
            "operator_authority_events_immutable_delete",
        ):
            v5_postcondition(conn)
    finally:
        conn.close()


def test_applied_v6_checksum_is_frozen() -> None:
    assert (
        _campaign_schema_checksum(6, "20260730_incident_privacy_observability_v1")
        == "cc7fe98a416fd74cb5f9f9df8286ef602e797473966d71fbc8d7dc5de51f6a97"
    )


def test_v6_postcondition_requires_incident_and_privacy_guards(
    tmp_path: Path,
) -> None:
    conn = _db(tmp_path)
    try:
        conn.execute("DROP TRIGGER incident_records_transition_guard")
        conn.commit()
        with pytest.raises(
            RuntimeError,
            match="campaign_schema_v6_triggers_missing:"
            "incident_records_transition_guard",
        ):
            v6_postcondition(conn)
    finally:
        conn.close()


def test_v7_postcondition_requires_learning_governance_guards(
    tmp_path: Path,
) -> None:
    conn = _db(tmp_path)
    try:
        conn.execute("DROP TRIGGER learning_governance_registry_no_update")
        conn.commit()
        with pytest.raises(
            RuntimeError,
            match="campaign_schema_v7_triggers_missing:"
            "learning_governance_registry_no_update",
        ):
            v7_postcondition(conn)
    finally:
        conn.close()


def test_applied_v7_checksum_is_frozen() -> None:
    assert (
        _campaign_schema_checksum(7, "20260730_learning_governance_registry_v1")
        == "37ea2fe1e3fb46eeddd9a54480fcf2525693b9162a2715b98b025a92db0cd076"
    )


def test_v8_owns_learning_cohort_tables_and_upgrades_lazy_legacy_shape(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "campaign-v7.db")
    try:
        _ensure_campaign_schema_ledger(conn)
        for version, migration_id in campaign_db._CAMPAIGN_SCHEMA_MIGRATIONS[:7]:
            _run_campaign_schema_migration(
                conn,
                version=version,
                migration_id=migration_id,
            )
        conn.executescript(
            """
            CREATE TABLE learning_cohorts (
              id TEXT PRIMARY KEY, campaign_slug TEXT NOT NULL,
              creator TEXT NOT NULL, soul_id TEXT NOT NULL,
              account_handle TEXT NOT NULL, timezone TEXT NOT NULL,
              start_date TEXT NOT NULL, seed TEXT NOT NULL, status TEXT NOT NULL,
              autoposter_enabled INTEGER NOT NULL DEFAULT 0,
              automatic_trial_graduation INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE learning_cohort_assignments (
              id TEXT PRIMARY KEY, cohort_id TEXT NOT NULL, day_index INTEGER NOT NULL,
              arm TEXT NOT NULL, surface TEXT NOT NULL, scheduled_for TEXT NOT NULL,
              assignment_seed TEXT NOT NULL, source_asset_id TEXT,
              generation_state TEXT NOT NULL DEFAULT 'planned',
              approval_state TEXT NOT NULL DEFAULT 'pending',
              schedule_state TEXT NOT NULL DEFAULT 'blocked_pending_approval',
              publish_state TEXT NOT NULL DEFAULT 'not_published',
              metric_1h_state TEXT NOT NULL DEFAULT 'pending',
              metric_24h_state TEXT NOT NULL DEFAULT 'pending',
              metric_72h_state TEXT NOT NULL DEFAULT 'not_required',
              retry_count INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(cohort_id, day_index, surface)
            );
            """
        )
        conn.commit()

        init_db(conn)
        v8_postcondition(conn)

        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(learning_cohort_assignments)"
            ).fetchall()
        }
        assert {
            "rendered_asset_id",
            "artifact_path",
            "lineage_path",
            "published_at",
        } <= columns
        assert (
            conn.execute(
                "SELECT version FROM campaign_schema_state WHERE singleton = 1"
            ).fetchone()["version"]
            == 9
        )
    finally:
        conn.close()


def test_terminal_authority_and_orchestration_evidence_is_immutable(
    tmp_path: Path,
) -> None:
    conn = _db(tmp_path)
    now = "2026-07-30T00:00:00Z"
    later = "2026-07-30T00:01:00Z"
    try:
        conn.execute(
            """
            INSERT INTO models(id, slug, name, created_at, updated_at)
            VALUES ('model_terminal', 'model-terminal', 'Model', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO campaigns
            (id, slug, name, root_path, created_at, updated_at)
            VALUES ('campaign_terminal', 'campaign-terminal', 'Campaign',
                    '/tmp/campaign-terminal', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO operator_authority_events
            (id, operation_id, effect_class, decision, actor_fingerprint, role,
             request_fingerprint, reason, created_at, idempotency_key,
             execution_state, attempt_count, claim_updated_at)
            VALUES ('authority_terminal', 'operation_terminal', 'local_mutation',
                    'allowed', 'actor', 'operator', ?, 'fixture', ?,
                    'terminal-key', 'claimed', 1, ?)
            """,
            ("a" * 64, now, now),
        )
        conn.execute(
            """
            UPDATE operator_authority_events
            SET execution_state = 'succeeded', completed_at = ?,
                outcome_json = '{"result":"original"}'
            WHERE id = 'authority_terminal'
            """,
            (later,),
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="operator authority event transition is invalid",
        ):
            conn.execute(
                """
                UPDATE operator_authority_events
                SET outcome_json = '{"result":"rewritten"}'
                WHERE id = 'authority_terminal'
                """
            )

        conn.execute(
            """
            INSERT INTO daily_orchestrator_runs
            (id, run_key, status, algorithm_version, policy_fingerprint,
             requested_items, selected_items, limits_json, stop_reason,
             next_run_reason, created_at, updated_at)
            VALUES ('run_terminal', 'run-terminal', 'planned', 'v1', ?,
                    1, 1, '{}', 'planned', 'next', ?, ?)
            """,
            ("b" * 64, now, now),
        )
        conn.execute(
            """
            UPDATE daily_orchestrator_runs
            SET status = 'completed', updated_at = ?
            WHERE id = 'run_terminal'
            """,
            (later,),
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="daily orchestrator run evidence is immutable",
        ):
            conn.execute(
                """
                UPDATE daily_orchestrator_runs
                SET updated_at = '2026-07-30T00:02:00Z'
                WHERE id = 'run_terminal'
                """
            )

        conn.execute(
            """
            INSERT INTO daily_orchestrator_items
            (id, run_id, ordinal, creator_id, campaign_id, mode, intent, state,
             attempt_count, max_attempts, selection_reason_json,
             decision_fingerprint, created_at, updated_at)
            VALUES ('item_terminal', 'run_terminal', 0, 'model_terminal',
                    'campaign_terminal', 'static_reel', 'passive', 'selected',
                    0, 2, '{}', ?, ?, ?)
            """,
            ("c" * 64, now, now),
        )
        conn.execute(
            """
            UPDATE daily_orchestrator_items
            SET state = 'running', attempt_count = 1, updated_at = ?
            WHERE id = 'item_terminal'
            """,
            (later,),
        )
        conn.execute(
            """
            UPDATE daily_orchestrator_items
            SET state = 'completed', result_json = '{"asset":"original"}'
            WHERE id = 'item_terminal'
            """
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="daily orchestrator item evidence is immutable",
        ):
            conn.execute(
                """
                UPDATE daily_orchestrator_items
                SET result_json = '{"asset":"rewritten"}'
                WHERE id = 'item_terminal'
                """
            )
    finally:
        conn.close()


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
