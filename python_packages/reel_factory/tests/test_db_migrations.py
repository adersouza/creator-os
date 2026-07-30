from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from reel_factory.db_migrations import (
    Migration,
    run_manifest_migrations,
    run_migrations,
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
    queue.finish(job_id, "succeeded")

    assert [
        row["new_status"]
        for row in queue.conn.execute(
            "SELECT new_status FROM queue_job_events ORDER BY rowid"
        )
    ] == ["queued", "claimed", "running", "succeeded"]
    with pytest.raises(sqlite3.IntegrityError, match="invalid queue job transition"):
        queue.conn.execute(
            "UPDATE queue_jobs SET status='queued' WHERE job_id=?", (job_id,)
        )
    with pytest.raises(sqlite3.IntegrityError, match="queue job events are immutable"):
        queue.conn.execute("DELETE FROM queue_job_events")


def _row_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn
