from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest
from reel_factory.db_migrations import (
    QUEUE_BASE_SCHEMA,
    Migration,
    migration_readiness_report,
    run_manifest_migrations,
    run_migrations,
    run_queue_migrations,
)
from reel_factory.manifest import Manifest
from reel_factory.render_queue import RenderQueue


def test_clean_manifest_records_version_and_protects_evidence(
    tmp_path: Path,
) -> None:
    manifest = Manifest(tmp_path / "manifest.json")
    conn = manifest.conn

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 9
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert [
        tuple(row)
        for row in conn.execute(
            "SELECT version, status FROM reel_schema_migrations ORDER BY version"
        )
    ] == [(8, "applied"), (9, "applied")]
    with pytest.raises(sqlite3.IntegrityError, match="invalid variation status"):
        conn.execute(
            """
            INSERT INTO variations (
              job_key, video_id, recipe, recipe_params_json, caption_text,
              caption_hash, output_path, output_hash, output_size_bytes,
              duration_sec, audio, encoded_at, encoder, status
            ) VALUES ('bad', 'missing', '', '{}', '', '', '', '', 0, 0, '', 0, '', 'x')
            """
        )
    conn.execute(
        """
        INSERT INTO prompt_runs (
          prompt_run_id, model, prompt_json_path, prompt_fields_json, created_at
        ) VALUES ('prompt', 'model', '/prompt.json', '{}', 1)
        """
    )
    with pytest.raises(
        sqlite3.IntegrityError, match="prompt run evidence is immutable"
    ):
        conn.execute("UPDATE prompt_runs SET model='other'")


def test_legacy_manifest_upgrades_columns_and_filename(tmp_path: Path) -> None:
    db_path = tmp_path / "manifest.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL);
        CREATE TABLE videos (
          video_id TEXT PRIMARY KEY, source_path TEXT NOT NULL,
          source_video_hash TEXT NOT NULL, source_duration_sec REAL NOT NULL,
          ingested_at INTEGER NOT NULL
        );
        CREATE TABLE variations (
          job_key TEXT PRIMARY KEY, video_id TEXT NOT NULL, recipe TEXT NOT NULL,
          recipe_params_json TEXT NOT NULL, caption_text TEXT NOT NULL,
          caption_hash TEXT NOT NULL, output_path TEXT NOT NULL,
          output_hash TEXT NOT NULL, output_size_bytes INTEGER NOT NULL,
          duration_sec REAL NOT NULL, audio TEXT NOT NULL, encoded_at INTEGER NOT NULL,
          encoder TEXT NOT NULL, status TEXT NOT NULL,
          FOREIGN KEY(video_id) REFERENCES videos(video_id)
        );
        CREATE TABLE render_attempts (
          attempt_id TEXT PRIMARY KEY, job_key TEXT NOT NULL, attempt_no INTEGER NOT NULL,
          status TEXT NOT NULL, temp_path TEXT NOT NULL, final_path TEXT NOT NULL,
          ffmpeg_cmd TEXT NOT NULL, started_at INTEGER NOT NULL, ended_at INTEGER,
          error_message TEXT
        );
        CREATE TABLE analysis_cache (
          cache_key TEXT PRIMARY KEY, source_hash TEXT NOT NULL, analyzer TEXT NOT NULL,
          payload_json TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        INSERT INTO videos VALUES ('v', '/source', 'sha', 1.0, 1);
        INSERT INTO variations VALUES (
          'job', 'v', 'recipe', '{}', '', '', '/tmp/output.mp4', 'sha', 1,
          1.0, 'stripped', 1, 'encoder', 'ok'
        );
        PRAGMA user_version=8;
        """
    )
    conn.close()

    upgraded = Manifest(tmp_path / "manifest.json")
    row = upgraded.conn.execute(
        "SELECT filename, error_message, render_time_sec FROM variations"
    ).fetchone()

    assert tuple(row) == ("output.mp4", None, None)
    assert upgraded.conn.execute("PRAGMA user_version").fetchone()[0] == 9


def test_manifest_migration_readiness_uses_copy_and_preserves_source(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "manifest.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE schema_migrations (
          version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL
        );
        CREATE TABLE videos (
          video_id TEXT PRIMARY KEY, source_path TEXT NOT NULL,
          source_video_hash TEXT NOT NULL, source_duration_sec REAL NOT NULL,
          ingested_at INTEGER NOT NULL
        );
        CREATE TABLE variations (
          job_key TEXT PRIMARY KEY, video_id TEXT NOT NULL, recipe TEXT NOT NULL,
          recipe_params_json TEXT NOT NULL, caption_text TEXT NOT NULL,
          caption_hash TEXT NOT NULL, output_path TEXT NOT NULL,
          output_hash TEXT NOT NULL, output_size_bytes INTEGER NOT NULL,
          duration_sec REAL NOT NULL, audio TEXT NOT NULL, encoded_at INTEGER NOT NULL,
          encoder TEXT NOT NULL, status TEXT NOT NULL
        );
        CREATE TABLE render_attempts (
          attempt_id TEXT PRIMARY KEY, job_key TEXT NOT NULL, attempt_no INTEGER NOT NULL,
          status TEXT NOT NULL, temp_path TEXT NOT NULL, final_path TEXT NOT NULL,
          ffmpeg_cmd TEXT NOT NULL, started_at INTEGER NOT NULL, ended_at INTEGER,
          error_message TEXT
        );
        CREATE TABLE analysis_cache (
          cache_key TEXT PRIMARY KEY, source_hash TEXT NOT NULL, analyzer TEXT NOT NULL,
          payload_json TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        PRAGMA user_version=8;
        """
    )
    conn.close()
    before = db_path.read_bytes()
    before_mtime = db_path.stat().st_mtime_ns

    report = migration_readiness_report(db_path, database_kind="manifest")

    assert report["status"] == "ready"
    assert report["sourceUserVersion"] == 8
    assert report["targetUserVersion"] == 9
    assert report["migratedCopyUserVersion"] == 9
    assert report["sourceBytesPreserved"] is True
    assert [row["version"] for row in report["migrationLedger"]] == [8, 9]
    assert db_path.read_bytes() == before
    assert db_path.stat().st_mtime_ns == before_mtime
    with sqlite3.connect(db_path) as unchanged:
        assert unchanged.execute("PRAGMA user_version").fetchone()[0] == 8
        assert (
            unchanged.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='reel_schema_migrations'"
            ).fetchone()
            is None
        )


def test_queue_migration_readiness_uses_copy_and_preserves_source(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "render_queue.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(QUEUE_BASE_SCHEMA)
    conn.execute("PRAGMA user_version=0")
    conn.commit()
    conn.close()
    before = db_path.read_bytes()

    report = migration_readiness_report(db_path, database_kind="queue")

    assert report["status"] == "ready"
    assert report["sourceUserVersion"] == 0
    assert report["targetUserVersion"] == 3
    assert report["migratedCopyUserVersion"] == 3
    assert report["sourceBytesPreserved"] is True
    assert [row["version"] for row in report["migrationLedger"]] == [1, 2, 3]
    assert db_path.read_bytes() == before
    with sqlite3.connect(db_path) as unchanged:
        assert unchanged.execute("PRAGMA user_version").fetchone()[0] == 0
        assert (
            unchanged.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='reel_queue_schema_migrations'"
            ).fetchone()
            is None
        )


def test_manifest_migration_failure_retries_and_checksum_drift_is_blocked(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(tmp_path / "custom.sqlite")
    conn.row_factory = sqlite3.Row
    should_fail = True

    def apply(db: sqlite3.Connection) -> None:
        db.execute("CREATE TABLE migration_subject (id TEXT PRIMARY KEY)")
        if should_fail:
            raise RuntimeError("interrupted")

    migration = Migration(1, "custom_v1", "stable", apply, lambda db: None)
    with pytest.raises(RuntimeError, match="interrupted"):
        run_migrations(
            conn,
            ledger="custom_migrations",
            error_prefix="custom",
            migrations=(migration,),
        )
    assert (
        conn.execute(
            "SELECT status FROM custom_migrations WHERE migration_id='custom_v1'"
        ).fetchone()[0]
        == "failed"
    )
    should_fail = False
    run_migrations(
        conn,
        ledger="custom_migrations",
        error_prefix="custom",
        migrations=(migration,),
    )
    conn.execute("DROP TRIGGER IF EXISTS custom_migrations_applied_immutable_update")
    conn.execute("UPDATE custom_migrations SET checksum='wrong'")
    conn.commit()
    with pytest.raises(RuntimeError, match="checksum_drift"):
        run_migrations(
            conn,
            ledger="custom_migrations",
            error_prefix="custom",
            migrations=(migration,),
        )


def test_manifest_and_queue_reject_newer_database(tmp_path: Path) -> None:
    manifest_db = tmp_path / "manifest.sqlite"
    conn = sqlite3.connect(manifest_db)
    conn.execute("PRAGMA user_version=99")
    conn.close()
    with pytest.raises(RuntimeError, match="newer_than_runtime"):
        run_manifest_migrations(_row_connection(manifest_db))

    queue_root = tmp_path / "queue"
    queue_root.mkdir()
    queue_db = queue_root / "render_queue.sqlite"
    conn = sqlite3.connect(queue_db)
    conn.execute("PRAGMA user_version=99")
    conn.close()
    with pytest.raises(RuntimeError, match="newer_than_runtime"):
        RenderQueue(queue_root)


def test_queue_transitions_are_audited_and_terminal_state_is_guarded(
    tmp_path: Path,
) -> None:
    queue = RenderQueue(tmp_path)
    job_id = queue.enqueue(job_key="job", command=["true"], cwd=tmp_path)
    queue.claim("worker")
    queue.mark_running(job_id, "worker")
    queue.finish(job_id, "succeeded", worker_id="worker")

    assert [
        row["new_status"]
        for row in queue.conn.execute(
            "SELECT new_status FROM queue_job_events ORDER BY rowid"
        )
    ] == ["queued", "claimed", "running", "succeeded"]
    with pytest.raises(sqlite3.IntegrityError, match="invalid queue job"):
        queue.conn.execute(
            "UPDATE queue_jobs SET status='queued' WHERE job_id=?", (job_id,)
        )
    with pytest.raises(sqlite3.IntegrityError, match="queue job events are immutable"):
        queue.conn.execute("DELETE FROM queue_job_events")
    with pytest.raises(sqlite3.IntegrityError, match="queue job identity is immutable"):
        queue.conn.execute(
            "UPDATE queue_jobs SET command_json='[]' WHERE job_id=?", (job_id,)
        )


def test_queue_database_rejects_skipped_execution_and_invalid_lease_shape(
    tmp_path: Path,
) -> None:
    queue = RenderQueue(tmp_path)
    job_id = queue.enqueue(job_key="strict", command=["true"], cwd=tmp_path)
    queue.claim("worker")

    with pytest.raises(RuntimeError, match="job_not_active"):
        queue.finish(job_id, "succeeded", worker_id="worker")
    with pytest.raises(sqlite3.IntegrityError, match="attempt progression"):
        queue.conn.execute(
            """
            UPDATE queue_jobs SET status='running', started_at=claimed_at,
              attempts=attempts+2
            WHERE job_id=?
            """,
            (job_id,),
        )
    queue.conn.rollback()
    with pytest.raises(RuntimeError, match="heartbeat_lease_mismatch"):
        queue.heartbeat(job_id, "other-worker")


def test_queue_strict_migration_normalizes_exhausted_active_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "render_queue.sqlite"
    conn = _row_connection(db_path)
    conn.executescript(QUEUE_BASE_SCHEMA)
    conn.executemany(
        """
        INSERT INTO queue_jobs (
          job_id, job_key, command_json, cwd, status, worker_id, attempts,
          max_attempts, created_at, claimed_at, started_at, heartbeat_at
        ) VALUES (?, ?, '["true"]', '/tmp', ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        [
            (
                "queued_exhausted",
                "queued_exhausted",
                "queued",
                None,
                2,
                2,
                None,
                None,
                None,
            ),
            (
                "claimed_exhausted",
                "claimed_exhausted",
                "claimed",
                "worker",
                2,
                2,
                10,
                None,
                10,
            ),
            ("running_over", "running_over", "running", "worker", 3, 2, 10, 5, 10),
            ("running_final", "running_final", "running", "worker", 2, 2, 10, 5, 10),
        ],
    )
    conn.execute("PRAGMA user_version=1")
    conn.commit()

    run_queue_migrations(conn)

    rows = {
        row["job_id"]: dict(row)
        for row in conn.execute("SELECT * FROM queue_jobs ORDER BY job_id")
    }
    for job_id in ("queued_exhausted", "claimed_exhausted", "running_over"):
        assert rows[job_id]["status"] == "interrupted"
        assert rows[job_id]["ended_at"] is not None
        assert "attempt budget exhausted" in rows[job_id]["error_text"]
    assert rows["running_final"]["status"] == "running"
    assert rows["running_final"]["started_at"] == rows["running_final"]["claimed_at"]
    assert {
        row["job_id"]: row["new_status"]
        for row in conn.execute(
            """
            SELECT event.job_id, event.new_status
            FROM queue_job_events event
            JOIN (
              SELECT job_id, MAX(rowid) AS rowid
              FROM queue_job_events GROUP BY job_id
            ) latest ON latest.rowid = event.rowid
            """
        )
    } == {
        "queued_exhausted": "interrupted",
        "claimed_exhausted": "interrupted",
        "running_over": "interrupted",
        "running_final": "running",
    }


def test_queue_strict_migration_preserves_claimed_direct_success(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "render_queue.sqlite"
    conn = _row_connection(db_path)
    conn.executescript(QUEUE_BASE_SCHEMA)
    conn.execute(
        """
        INSERT INTO queue_jobs (
          job_id, job_key, command_json, cwd, status, worker_id, attempts,
          max_attempts, created_at, claimed_at, started_at, ended_at,
          heartbeat_at, error_text
        ) VALUES (
          'legacy_success', 'legacy_success', '["true"]', '/tmp', 'succeeded',
          'legacy-worker', 0, 2, 1, 2, NULL, 3, 2, NULL
        )
        """
    )
    conn.execute("PRAGMA user_version=1")
    conn.commit()

    run_queue_migrations(conn)

    row = conn.execute(
        "SELECT * FROM queue_jobs WHERE job_id='legacy_success'"
    ).fetchone()
    assert row["status"] == "succeeded"
    assert row["started_at"] == row["claimed_at"] == 2
    assert row["ended_at"] == 3
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3


def test_stale_recovery_does_not_overwrite_concurrent_lease_renewal(
    tmp_path: Path,
) -> None:
    queue = RenderQueue(tmp_path)
    job_id = queue.enqueue(job_key="renewed", command=["true"], cwd=tmp_path)
    queue.claim("worker")
    queue.mark_running(job_id, "worker")
    queue.conn.execute(
        "UPDATE queue_jobs SET heartbeat_at=1 WHERE job_id=?",
        (job_id,),
    )
    queue.conn.commit()
    renewed = threading.Event()

    def renew_while_recovery_waits() -> None:
        conn = sqlite3.connect(queue.db_path, timeout=5)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE queue_jobs SET heartbeat_at=? WHERE job_id=?",
                (int(time.time()), job_id),
            )
            renewed.set()
            time.sleep(0.15)
            conn.commit()
        finally:
            conn.close()

    thread = threading.Thread(target=renew_while_recovery_waits)
    thread.start()
    assert renewed.wait(timeout=2)
    try:
        assert queue.recover_stale(stale_after_sec=60) == 0
    finally:
        thread.join(timeout=2)
    row = queue.conn.execute(
        "SELECT status, worker_id FROM queue_jobs WHERE job_id=?",
        (job_id,),
    ).fetchone()
    assert tuple(row) == ("running", "worker")


def test_queue_strict_guards_reject_bad_inserts_and_fabricated_events(
    tmp_path: Path,
) -> None:
    queue = RenderQueue(tmp_path)
    with pytest.raises(sqlite3.IntegrityError, match="state shape"):
        queue.conn.execute(
            """
            INSERT INTO queue_jobs (
              job_id, job_key, command_json, cwd, status, worker_id,
              attempts, max_attempts, created_at
            ) VALUES (
              'malformed', 'malformed', '["true"]', '/tmp', 'queued',
              'forged-worker', 0, 2, 1
            )
            """
        )
    queue.conn.rollback()

    job_id = queue.enqueue(job_key="event-guard", command=["true"], cwd=tmp_path)
    with pytest.raises(sqlite3.IntegrityError, match="does not match job transition"):
        queue.conn.execute(
            """
            INSERT INTO queue_job_events (
              event_id, job_id, old_status, new_status, actor, reason, created_at
            ) VALUES ('noop', ?, 'queued', 'queued', 'forged', 'no-op', 2)
            """,
            (job_id,),
        )
    queue.conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="does not match job transition"):
        queue.conn.execute(
            """
            INSERT INTO queue_job_events (
              event_id, job_id, old_status, new_status, actor, reason, created_at
            ) VALUES (
              'fabricated', ?, 'queued', 'succeeded', 'forged',
              'fabricated transition', 2
            )
            """,
            (job_id,),
        )


def test_queue_applied_migration_postcondition_scans_existing_row_shapes(
    tmp_path: Path,
) -> None:
    queue = RenderQueue(tmp_path)
    queue.conn.execute("DROP TRIGGER queue_jobs_state_shape_insert")
    queue.conn.execute(
        """
        CREATE TRIGGER queue_jobs_state_shape_insert
        BEFORE INSERT ON queue_jobs
        BEGIN
          SELECT 1;
        END
        """
    )
    queue.conn.execute(
        """
        INSERT INTO queue_jobs (
          job_id, job_key, command_json, cwd, status, worker_id,
          attempts, max_attempts, created_at
        ) VALUES (
          'postcondition_bad', 'postcondition_bad', '["true"]', '/tmp',
          'queued', 'forged-worker', 0, 2, 1
        )
        """
    )
    queue.conn.execute(
        """
        INSERT INTO queue_job_events (
          event_id, job_id, old_status, new_status, actor, reason, created_at
        ) VALUES (
          'postcondition_event', 'postcondition_bad', NULL, 'queued',
          'schema_fixture', 'fixture baseline', 1
        )
        """
    )
    queue.conn.commit()

    with pytest.raises(RuntimeError, match="invalid_state_shape"):
        run_queue_migrations(queue.conn)


def test_queue_applied_migration_postcondition_requires_latest_event_matches_state(
    tmp_path: Path,
) -> None:
    queue = RenderQueue(tmp_path)
    job_id = queue.enqueue(job_key="event-state", command=["true"], cwd=tmp_path)
    queue.conn.execute("DROP TRIGGER queue_job_events_transition_insert")
    queue.conn.execute(
        """
        CREATE TRIGGER queue_job_events_transition_insert
        BEFORE INSERT ON queue_job_events
        BEGIN
          SELECT 1;
        END
        """
    )
    queue.conn.execute(
        """
        INSERT INTO queue_job_events (
          event_id, job_id, old_status, new_status, actor, reason, created_at
        ) VALUES (
          'forged_latest', ?, 'queued', 'succeeded',
          'schema_fixture', 'fixture mismatch', 2
        )
        """,
        (job_id,),
    )
    queue.conn.commit()

    with pytest.raises(RuntimeError, match="event_state_mismatch"):
        run_queue_migrations(queue.conn)


def _row_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn
