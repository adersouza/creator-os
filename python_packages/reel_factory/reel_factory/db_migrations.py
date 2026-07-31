"""Explicit SQLite migration ledgers for Reel Factory state databases."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from creator_os_core.sqlite import connect_sqlite

MANIFEST_SCHEMA_VERSION = 9
QUEUE_SCHEMA_VERSION = 3

MANIFEST_BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
  video_id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL,
  source_video_hash TEXT NOT NULL,
  source_duration_sec REAL NOT NULL,
  ingested_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS variations (
  job_key TEXT PRIMARY KEY,
  video_id TEXT NOT NULL,
  recipe TEXT NOT NULL,
  recipe_params_json TEXT NOT NULL,
  caption_text TEXT NOT NULL,
  caption_hash TEXT NOT NULL,
  output_path TEXT NOT NULL,
  filename TEXT,
  output_hash TEXT NOT NULL,
  output_size_bytes INTEGER NOT NULL,
  duration_sec REAL NOT NULL,
  audio TEXT NOT NULL,
  encoded_at INTEGER NOT NULL,
  encoder TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ok', 'failed')),
  render_time_sec REAL,
  error_message TEXT,
  FOREIGN KEY(video_id) REFERENCES videos(video_id)
);
CREATE TABLE IF NOT EXISTS render_attempts (
  attempt_id TEXT PRIMARY KEY,
  job_key TEXT NOT NULL,
  attempt_no INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ok', 'failed', 'interrupted')),
  temp_path TEXT NOT NULL,
  final_path TEXT NOT NULL,
  ffmpeg_cmd TEXT NOT NULL,
  started_at INTEGER NOT NULL,
  ended_at INTEGER,
  error_message TEXT
);
CREATE TABLE IF NOT EXISTS analysis_cache (
  cache_key TEXT PRIMARY KEY,
  source_hash TEXT NOT NULL,
  analyzer TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_variations_video_id ON variations(video_id);
CREATE INDEX IF NOT EXISTS idx_variations_recipe ON variations(recipe);
CREATE INDEX IF NOT EXISTS idx_variations_caption_hash ON variations(caption_hash);
CREATE INDEX IF NOT EXISTS idx_variations_active_failures
  ON variations(encoded_at, recipe) WHERE status = 'failed';
CREATE INDEX IF NOT EXISTS idx_render_attempts_job_key
  ON render_attempts(job_key, attempt_no);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_source
  ON analysis_cache(source_hash, analyzer);
"""

MANIFEST_GUARDS = """
CREATE TRIGGER IF NOT EXISTS reel_schema_migrations_applied_immutable_update
BEFORE UPDATE ON reel_schema_migrations
WHEN OLD.status = 'applied'
BEGIN
  SELECT RAISE(ABORT, 'applied reel migrations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS reel_schema_migrations_applied_immutable_delete
BEFORE DELETE ON reel_schema_migrations
WHEN OLD.status = 'applied'
BEGIN
  SELECT RAISE(ABORT, 'applied reel migrations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS variations_status_insert
BEFORE INSERT ON variations
WHEN NEW.status NOT IN ('ok', 'failed')
BEGIN
  SELECT RAISE(ABORT, 'invalid variation status');
END;
CREATE TRIGGER IF NOT EXISTS variations_status_update
BEFORE UPDATE OF status ON variations
WHEN NEW.status NOT IN ('ok', 'failed')
BEGIN
  SELECT RAISE(ABORT, 'invalid variation status');
END;
CREATE TRIGGER IF NOT EXISTS render_attempts_status_insert
BEFORE INSERT ON render_attempts
WHEN NEW.status NOT IN ('ok', 'failed', 'interrupted')
BEGIN
  SELECT RAISE(ABORT, 'invalid render attempt status');
END;
CREATE TRIGGER IF NOT EXISTS render_attempts_immutable_update
BEFORE UPDATE ON render_attempts
BEGIN
  SELECT RAISE(ABORT, 'render attempts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS render_attempts_immutable_delete
BEFORE DELETE ON render_attempts
BEGIN
  SELECT RAISE(ABORT, 'render attempts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS prompt_runs_immutable_update
BEFORE UPDATE ON prompt_runs
BEGIN
  SELECT RAISE(ABORT, 'prompt run evidence is immutable');
END;
CREATE TRIGGER IF NOT EXISTS prompt_runs_immutable_delete
BEFORE DELETE ON prompt_runs
BEGIN
  SELECT RAISE(ABORT, 'prompt run evidence is immutable');
END;
"""

QUEUE_BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS queue_jobs (
  job_id TEXT PRIMARY KEY,
  job_key TEXT NOT NULL UNIQUE,
  command_json TEXT NOT NULL,
  cwd TEXT NOT NULL,
  status TEXT NOT NULL CHECK(
    status IN ('queued', 'claimed', 'running', 'succeeded', 'failed', 'interrupted')
  ),
  worker_id TEXT,
  attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
  max_attempts INTEGER NOT NULL DEFAULT 2 CHECK(max_attempts > 0),
  created_at INTEGER NOT NULL,
  claimed_at INTEGER,
  started_at INTEGER,
  ended_at INTEGER,
  heartbeat_at INTEGER,
  error_text TEXT
);
CREATE INDEX IF NOT EXISTS idx_queue_status ON queue_jobs(status, created_at);
"""

QUEUE_GUARDS = """
CREATE TABLE IF NOT EXISTS queue_job_events (
  event_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES queue_jobs(job_id),
  old_status TEXT,
  new_status TEXT NOT NULL,
  actor TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_queue_job_events_job
  ON queue_job_events(job_id, created_at);
CREATE TRIGGER IF NOT EXISTS reel_queue_schema_migrations_applied_immutable_update
BEFORE UPDATE ON reel_queue_schema_migrations
WHEN OLD.status = 'applied'
BEGIN
  SELECT RAISE(ABORT, 'applied reel queue migrations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS reel_queue_schema_migrations_applied_immutable_delete
BEFORE DELETE ON reel_queue_schema_migrations
WHEN OLD.status = 'applied'
BEGIN
  SELECT RAISE(ABORT, 'applied reel queue migrations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS queue_jobs_status_insert
BEFORE INSERT ON queue_jobs
WHEN NEW.status != 'queued'
BEGIN
  SELECT RAISE(ABORT, 'queue jobs must begin queued');
END;
CREATE TRIGGER IF NOT EXISTS queue_jobs_status_update
BEFORE UPDATE OF status ON queue_jobs
WHEN OLD.status != NEW.status AND NOT (
  (OLD.status = 'queued' AND NEW.status = 'claimed') OR
  (OLD.status = 'claimed' AND NEW.status IN ('running', 'queued', 'succeeded', 'failed', 'interrupted')) OR
  (OLD.status = 'running' AND NEW.status IN ('queued', 'succeeded', 'failed', 'interrupted'))
)
BEGIN
  SELECT RAISE(ABORT, 'invalid queue job transition');
END;
CREATE TRIGGER IF NOT EXISTS queue_jobs_attempt_bounds_insert
BEFORE INSERT ON queue_jobs
WHEN NEW.attempts < 0 OR NEW.max_attempts <= 0
BEGIN
  SELECT RAISE(ABORT, 'invalid queue attempt bounds');
END;
CREATE TRIGGER IF NOT EXISTS queue_jobs_attempt_bounds_update
BEFORE UPDATE OF attempts, max_attempts ON queue_jobs
WHEN NEW.attempts < 0 OR NEW.max_attempts <= 0
BEGIN
  SELECT RAISE(ABORT, 'invalid queue attempt bounds');
END;
CREATE TRIGGER IF NOT EXISTS queue_job_events_immutable_update
BEFORE UPDATE ON queue_job_events
BEGIN
  SELECT RAISE(ABORT, 'queue job events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS queue_job_events_immutable_delete
BEFORE DELETE ON queue_job_events
BEGIN
  SELECT RAISE(ABORT, 'queue job events are immutable');
END;
"""

QUEUE_STRICT_GUARDS = """
DROP TRIGGER IF EXISTS queue_jobs_status_update;
CREATE TRIGGER queue_jobs_status_update
BEFORE UPDATE OF status ON queue_jobs
WHEN OLD.status != NEW.status AND NOT (
  (OLD.status = 'queued' AND NEW.status = 'claimed') OR
  (OLD.status = 'claimed' AND NEW.status IN ('running', 'queued', 'interrupted')) OR
  (OLD.status = 'running' AND NEW.status IN ('queued', 'succeeded', 'failed', 'interrupted'))
)
BEGIN
  SELECT RAISE(ABORT, 'invalid queue job transition');
END;
CREATE TRIGGER IF NOT EXISTS queue_jobs_identity_immutable
BEFORE UPDATE OF job_key, command_json, cwd, max_attempts, created_at ON queue_jobs
BEGIN
  SELECT RAISE(ABORT, 'queue job identity is immutable');
END;
CREATE TRIGGER IF NOT EXISTS queue_jobs_attempt_progression
BEFORE UPDATE OF status, attempts ON queue_jobs
WHEN (
  (OLD.status = 'claimed' AND NEW.status = 'running'
    AND NEW.attempts != OLD.attempts + 1)
  OR
  (NOT (OLD.status = 'claimed' AND NEW.status = 'running')
    AND NEW.attempts != OLD.attempts)
  OR NEW.attempts > NEW.max_attempts
)
BEGIN
  SELECT RAISE(ABORT, 'invalid queue attempt progression');
END;
CREATE TRIGGER IF NOT EXISTS queue_jobs_state_shape_insert
BEFORE INSERT ON queue_jobs
WHEN NOT (
  NEW.status = 'queued'
  AND NEW.worker_id IS NULL AND NEW.claimed_at IS NULL
  AND NEW.started_at IS NULL AND NEW.ended_at IS NULL
  AND NEW.heartbeat_at IS NULL AND NEW.error_text IS NULL
  AND NEW.attempts < NEW.max_attempts
  AND json_valid(NEW.command_json) = 1
)
BEGIN
  SELECT RAISE(ABORT, 'invalid queue job state shape');
END;
CREATE TRIGGER IF NOT EXISTS queue_jobs_state_shape_update
BEFORE UPDATE ON queue_jobs
WHEN NOT (
  (NEW.status = 'queued'
    AND NEW.worker_id IS NULL AND NEW.claimed_at IS NULL
    AND NEW.started_at IS NULL AND NEW.ended_at IS NULL
    AND NEW.heartbeat_at IS NULL AND NEW.error_text IS NULL
    AND NEW.attempts < NEW.max_attempts)
  OR
  (NEW.status = 'claimed'
    AND LENGTH(TRIM(COALESCE(NEW.worker_id, ''))) > 0
    AND NEW.claimed_at IS NOT NULL AND NEW.started_at IS NULL
    AND NEW.ended_at IS NULL AND NEW.heartbeat_at IS NOT NULL
    AND NEW.error_text IS NULL AND NEW.attempts < NEW.max_attempts)
  OR
  (NEW.status = 'running'
    AND LENGTH(TRIM(COALESCE(NEW.worker_id, ''))) > 0
    AND NEW.claimed_at IS NOT NULL AND NEW.started_at IS NOT NULL
    AND NEW.started_at >= NEW.claimed_at
    AND NEW.ended_at IS NULL AND NEW.heartbeat_at IS NOT NULL
    AND NEW.error_text IS NULL AND NEW.attempts <= NEW.max_attempts)
  OR
  (NEW.status = 'succeeded'
    AND LENGTH(TRIM(COALESCE(NEW.worker_id, ''))) > 0
    AND NEW.claimed_at IS NOT NULL AND NEW.started_at IS NOT NULL
    AND NEW.ended_at IS NOT NULL AND NEW.ended_at >= NEW.started_at
    AND NEW.error_text IS NULL)
  OR
  (NEW.status IN ('failed', 'interrupted')
    AND NEW.ended_at IS NOT NULL
    AND LENGTH(TRIM(COALESCE(NEW.error_text, ''))) > 0)
)
BEGIN
  SELECT RAISE(ABORT, 'invalid queue job state shape');
END;
CREATE TRIGGER IF NOT EXISTS queue_job_events_transition_insert
BEFORE INSERT ON queue_job_events
WHEN NOT (
  NEW.new_status = (SELECT status FROM queue_jobs WHERE job_id=NEW.job_id)
  AND (
    (NOT EXISTS (
      SELECT 1 FROM queue_job_events WHERE job_id=NEW.job_id
    ) AND NEW.old_status IS NULL AND NEW.new_status='queued')
    OR
    (NEW.old_status = (
      SELECT new_status FROM queue_job_events
      WHERE job_id=NEW.job_id ORDER BY rowid DESC LIMIT 1
    )
      AND NEW.old_status != NEW.new_status
      AND (
        (NEW.old_status = 'queued' AND NEW.new_status = 'claimed')
        OR
        (NEW.old_status = 'claimed'
          AND NEW.new_status IN ('running', 'queued', 'interrupted'))
        OR
        (NEW.old_status = 'running'
          AND NEW.new_status IN (
            'queued', 'succeeded', 'failed', 'interrupted'
          ))
      )
    )
  )
)
BEGIN
  SELECT RAISE(ABORT, 'queue event does not match job transition');
END;
"""


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


def run_migrations(
    conn: sqlite3.Connection,
    *,
    ledger: str,
    error_prefix: str,
    migrations: Sequence[Migration],
) -> None:
    """Apply ordered migrations without accepting a newer database."""

    if not ledger.isidentifier():
        raise ValueError("migration ledger must be an identifier")
    ordered = tuple(sorted(migrations, key=lambda item: item.version))
    if not ordered or len({item.version for item in ordered}) != len(ordered):
        raise RuntimeError(f"{error_prefix}_migration_order_invalid")
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    supported = ordered[-1].version
    if current > supported:
        raise RuntimeError(f"{error_prefix}_newer_than_runtime:{current}>{supported}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ledger} (
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
        _apply_one(
            conn,
            ledger=ledger,
            error_prefix=error_prefix,
            migration=migration,
        )
    final = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if final != supported:
        raise RuntimeError(f"{error_prefix}_version_mismatch:{final}!={supported}")
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError(f"{error_prefix}_foreign_key_check_failed")


def _apply_one(
    conn: sqlite3.Connection,
    *,
    ledger: str,
    error_prefix: str,
    migration: Migration,
) -> None:
    prior = conn.execute(
        f"SELECT checksum, status FROM {ledger} WHERE migration_id=?",
        (migration.migration_id,),
    ).fetchone()
    if prior is not None:
        if str(prior["checksum"]) != migration.checksum:
            raise RuntimeError(
                f"{error_prefix}_migration_checksum_drift:{migration.migration_id}"
            )
        if str(prior["status"]) == "applied":
            migration.postcondition(conn)
            return
    now = _now()
    conn.execute(
        f"""
        INSERT INTO {ledger} (
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
            os.environ.get("CREATOR_OS_SOURCE_SHA") or "unknown",
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
            f"""
            UPDATE {ledger}
            SET status='applied', applied_at=?, error=NULL
            WHERE migration_id=?
            """,
            (_now(), migration.migration_id),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        conn.execute(
            f"UPDATE {ledger} SET status='failed', error=? WHERE migration_id=?",
            (f"{type(exc).__name__}:{exc}"[:2000], migration.migration_id),
        )
        conn.commit()
        raise


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def run_manifest_migrations(conn: sqlite3.Connection) -> None:
    run_migrations(
        conn,
        ledger="reel_schema_migrations",
        error_prefix="reel_schema",
        migrations=(
            Migration(
                8,
                "20260730_reel_manifest_baseline_v8",
                MANIFEST_BASE_SCHEMA,
                _apply_manifest_baseline,
                _manifest_baseline_postcondition,
            ),
            Migration(
                9,
                "20260730_reel_evidence_guards_v1",
                MANIFEST_GUARDS,
                _apply_manifest_guards,
                _manifest_guard_postcondition,
            ),
        ),
    )


def run_queue_migrations(conn: sqlite3.Connection) -> None:
    run_migrations(
        conn,
        ledger="reel_queue_schema_migrations",
        error_prefix="reel_queue_schema",
        migrations=(
            Migration(
                1,
                "20260730_reel_queue_baseline_v1",
                QUEUE_BASE_SCHEMA,
                lambda db: execute_script(db, QUEUE_BASE_SCHEMA),
                _queue_baseline_postcondition,
            ),
            Migration(
                2,
                "20260730_reel_queue_guards_v1",
                f"legacy_event_backfill_v1\n{QUEUE_GUARDS}",
                _apply_queue_guards,
                _queue_guard_postcondition,
            ),
            Migration(
                3,
                "20260730_reel_queue_strict_state_machine_v2",
                QUEUE_STRICT_GUARDS,
                _apply_queue_strict_guards,
                _queue_strict_guard_postcondition,
            ),
        ),
    )


def migration_readiness_report(
    source_path: Path,
    *,
    database_kind: Literal["manifest", "queue"],
) -> dict[str, Any]:
    """Prove migrations on a temporary SQLite copy without mutating the source."""

    selected = source_path.expanduser()
    if selected.is_symlink() or not selected.is_file():
        raise FileNotFoundError(f"migration source is not a regular file: {selected}")
    source = selected.resolve()
    before_stat = source.stat()
    before_sha = _sha256_path(source)
    if database_kind == "manifest":
        runner = run_manifest_migrations
        ledger = "reel_schema_migrations"
        target_version = MANIFEST_SCHEMA_VERSION
    elif database_kind == "queue":
        runner = run_queue_migrations
        ledger = "reel_queue_schema_migrations"
        target_version = QUEUE_SCHEMA_VERSION
    else:
        raise ValueError(f"unsupported database kind: {database_kind}")

    with tempfile.TemporaryDirectory(prefix="creator-os-reel-migration-") as raw:
        copy_path = Path(raw) / source.name
        with connect_sqlite(source, readonly=True, wal=False) as source_conn:
            source_version = int(
                source_conn.execute("PRAGMA user_version").fetchone()[0]
            )
            with connect_sqlite(copy_path, wal=False) as copy_conn:
                source_conn.backup(copy_conn)
        with connect_sqlite(copy_path, wal=False) as migrated:
            runner(migrated)
            migrated_version = int(
                migrated.execute("PRAGMA user_version").fetchone()[0]
            )
            quick_check = str(migrated.execute("PRAGMA quick_check").fetchone()[0])
            foreign_key_violations = [
                tuple(row) for row in migrated.execute("PRAGMA foreign_key_check")
            ]
            ledger_rows = [
                {
                    "migrationId": str(row["migration_id"]),
                    "version": int(row["version"]),
                    "status": str(row["status"]),
                    "checksum": str(row["checksum"]),
                }
                for row in migrated.execute(
                    f"""
                    SELECT migration_id, version, status, checksum
                    FROM {ledger}
                    ORDER BY version
                    """
                )
            ]

    after_stat = source.stat()
    after_sha = _sha256_path(source)
    preserved = (
        before_sha == after_sha
        and before_stat.st_size == after_stat.st_size
        and before_stat.st_mtime_ns == after_stat.st_mtime_ns
    )
    if not preserved:
        raise RuntimeError("reel_migration_readiness_source_changed")
    if (
        migrated_version != target_version
        or quick_check != "ok"
        or foreign_key_violations
        or any(row["status"] != "applied" for row in ledger_rows)
    ):
        raise RuntimeError("reel_migration_readiness_postcondition_failed")
    return {
        "schema": "creator_os.reel_database_migration_readiness.v1",
        "mode": "copied_database_only",
        "databaseKind": database_kind,
        "sourcePath": str(source),
        "sourceSha256": before_sha,
        "sourceUserVersion": source_version,
        "targetUserVersion": target_version,
        "migratedCopyUserVersion": migrated_version,
        "quickCheck": quick_check,
        "foreignKeyViolationCount": len(foreign_key_violations),
        "migrationLedger": ledger_rows,
        "sourceBytesPreserved": preserved,
        "status": "ready",
    }


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _apply_manifest_baseline(conn: sqlite3.Connection) -> None:
    from creator_os_core.sqlite import ensure_columns

    execute_script(conn, MANIFEST_BASE_SCHEMA)
    ensure_columns(
        conn,
        "variations",
        {
            "filename": "TEXT",
            "error_message": "TEXT",
            "render_time_sec": "REAL",
        },
    )
    rows = conn.execute(
        "SELECT job_key, output_path FROM variations WHERE filename IS NULL OR filename=''"
    ).fetchall()
    conn.executemany(
        "UPDATE variations SET filename=? WHERE job_key=?",
        [
            (
                str(row["output_path"]).replace("\\", "/").rsplit("/", 1)[-1],
                row["job_key"],
            )
            for row in rows
        ],
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_variations_filename ON variations(filename)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (8, strftime('%s','now'))"
    )


def _apply_manifest_guards(conn: sqlite3.Connection) -> None:
    # Lazy imports avoid a module cycle while preserving the historical helpers.
    from .evidence_store import ensure_evidence_schema
    from .intelligence_store import ensure_intelligence_schema

    ensure_evidence_schema(conn)
    ensure_intelligence_schema(conn)
    execute_script(conn, MANIFEST_GUARDS)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (9, strftime('%s','now'))"
    )


def _apply_queue_guards(conn: sqlite3.Connection) -> None:
    execute_script(conn, QUEUE_GUARDS)
    conn.execute(
        """
        INSERT OR IGNORE INTO queue_job_events (
          event_id, job_id, old_status, new_status, actor, reason, created_at
        )
        SELECT 'qe_migration_' || job_id, job_id, NULL, status,
               'schema_migration', 'legacy queue state baseline', created_at
        FROM queue_jobs
        """
    )


def _apply_queue_strict_guards(conn: sqlite3.Connection) -> None:
    now = int(datetime.now(UTC).timestamp())
    # The v2 transition trigger does not permit migration-only normalization
    # such as queued -> interrupted. Reinstall the strict trigger after legacy
    # rows and their audit events have been normalized in this transaction.
    conn.execute("DROP TRIGGER IF EXISTS queue_jobs_status_update")
    conn.execute(
        """
        UPDATE queue_jobs SET
          status='interrupted', ended_at=?,
          error_text='queue state normalized during strict migration'
        WHERE status IN ('claimed', 'running') AND (
          worker_id IS NULL OR TRIM(worker_id)='' OR claimed_at IS NULL
          OR heartbeat_at IS NULL
        )
        """,
        (now,),
    )
    conn.execute(
        """
        UPDATE queue_jobs SET
          status='interrupted', ended_at=?,
          error_text='queue attempt budget exhausted before strict migration'
        WHERE (status IN ('queued', 'claimed') AND attempts >= max_attempts)
           OR (status='running' AND attempts > max_attempts)
        """,
        (now,),
    )
    conn.execute(
        """
        UPDATE queue_jobs SET worker_id=NULL, claimed_at=NULL, started_at=NULL,
          ended_at=NULL, heartbeat_at=NULL, error_text=NULL
        WHERE status='queued'
        """
    )
    conn.execute(
        """
        UPDATE queue_jobs SET started_at=NULL, ended_at=NULL, error_text=NULL
        WHERE status='claimed'
        """
    )
    conn.execute(
        """
        UPDATE queue_jobs SET
          started_at=CASE
            WHEN started_at IS NULL OR started_at < claimed_at THEN claimed_at
            ELSE started_at
          END,
          attempts=MAX(attempts, 1), ended_at=NULL, error_text=NULL
        WHERE status='running'
        """
    )
    conn.execute(
        """
        UPDATE queue_jobs SET
          started_at=COALESCE(started_at, claimed_at),
          ended_at=CASE
            WHEN COALESCE(ended_at, heartbeat_at, claimed_at, created_at)
              < COALESCE(started_at, claimed_at)
            THEN COALESCE(started_at, claimed_at)
            ELSE COALESCE(ended_at, heartbeat_at, started_at, claimed_at, created_at)
          END,
          error_text=NULL
        WHERE status='succeeded'
          AND LENGTH(TRIM(COALESCE(worker_id, ''))) > 0
          AND claimed_at IS NOT NULL
        """
    )
    conn.execute(
        """
        UPDATE queue_jobs SET ended_at=COALESCE(ended_at, heartbeat_at, started_at,
          claimed_at, created_at), error_text=COALESCE(NULLIF(error_text, ''),
          'historical terminal queue failure')
        WHERE status IN ('failed', 'interrupted')
        """
    )
    rows = conn.execute(
        """
        SELECT q.job_id, q.status, q.created_at,
          (SELECT e.new_status FROM queue_job_events e
           WHERE e.job_id=q.job_id ORDER BY e.rowid DESC LIMIT 1) AS event_status
        FROM queue_jobs q
        WHERE COALESCE((
          SELECT e.new_status FROM queue_job_events e
          WHERE e.job_id=q.job_id ORDER BY e.rowid DESC LIMIT 1
        ), '') != q.status
        """
    ).fetchall()
    conn.executemany(
        """
        INSERT INTO queue_job_events (
          event_id, job_id, old_status, new_status, actor, reason, created_at
        ) VALUES (?, ?, ?, ?, 'schema_migration',
          'strict queue state normalization', ?)
        """,
        [
            (
                f"qe_strict_{row['job_id']}",
                row["job_id"],
                row["event_status"],
                row["status"],
                now,
            )
            for row in rows
        ],
    )
    execute_script(conn, QUEUE_STRICT_GUARDS)


def _manifest_baseline_postcondition(conn: sqlite3.Connection) -> None:
    _require_tables(conn, {"videos", "variations", "render_attempts", "analysis_cache"})
    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(variations)").fetchall()
    }
    if not {"filename", "error_message", "render_time_sec"} <= columns:
        raise RuntimeError("reel_schema_compatibility_columns_missing")
    invalid = conn.execute(
        "SELECT status FROM variations WHERE status NOT IN ('ok', 'failed') LIMIT 1"
    ).fetchone()
    if invalid is not None:
        raise RuntimeError(f"reel_schema_invalid_variation_status:{invalid['status']}")
    invalid = conn.execute(
        """
        SELECT status FROM render_attempts
        WHERE status NOT IN ('ok', 'failed', 'interrupted') LIMIT 1
        """
    ).fetchone()
    if invalid is not None:
        raise RuntimeError(f"reel_schema_invalid_attempt_status:{invalid['status']}")


def _manifest_guard_postcondition(conn: sqlite3.Connection) -> None:
    _require_tables(
        conn,
        {
            "prompt_runs",
            "asset_generations",
            "campaign_outputs",
            "reference_analysis",
            "media_embeddings",
            "reel_features",
        },
    )
    _require_triggers(
        conn,
        {
            "reel_schema_migrations_applied_immutable_update",
            "variations_status_update",
            "render_attempts_immutable_update",
            "prompt_runs_immutable_update",
        },
    )


def _queue_baseline_postcondition(conn: sqlite3.Connection) -> None:
    _require_tables(conn, {"queue_jobs"})
    invalid = conn.execute(
        """
        SELECT status FROM queue_jobs
        WHERE status NOT IN (
          'queued', 'claimed', 'running', 'succeeded', 'failed', 'interrupted'
        ) OR attempts < 0 OR max_attempts <= 0 OR json_valid(command_json) = 0
        LIMIT 1
        """
    ).fetchone()
    if invalid is not None:
        raise RuntimeError(f"reel_queue_schema_invalid_job:{invalid['status']}")


def _queue_guard_postcondition(conn: sqlite3.Connection) -> None:
    _require_tables(conn, {"queue_job_events"})
    _require_triggers(
        conn,
        {
            "reel_queue_schema_migrations_applied_immutable_update",
            "queue_jobs_status_update",
            "queue_job_events_immutable_update",
        },
    )
    missing = conn.execute(
        """
        SELECT q.job_id FROM queue_jobs q
        WHERE NOT EXISTS (
          SELECT 1 FROM queue_job_events e WHERE e.job_id=q.job_id
        )
        LIMIT 1
        """
    ).fetchone()
    if missing is not None:
        raise RuntimeError(f"reel_queue_schema_event_missing:{missing['job_id']}")


def _queue_strict_guard_postcondition(conn: sqlite3.Connection) -> None:
    _queue_guard_postcondition(conn)
    _require_triggers(
        conn,
        {
            "queue_jobs_identity_immutable",
            "queue_jobs_attempt_progression",
            "queue_jobs_state_shape_insert",
            "queue_jobs_state_shape_update",
            "queue_job_events_transition_insert",
        },
    )
    invalid = conn.execute(
        """
        SELECT job_id, status
        FROM queue_jobs
        WHERE NOT (
          (status = 'queued'
            AND worker_id IS NULL AND claimed_at IS NULL
            AND started_at IS NULL AND ended_at IS NULL
            AND heartbeat_at IS NULL AND error_text IS NULL
            AND attempts < max_attempts)
          OR
          (status = 'claimed'
            AND LENGTH(TRIM(COALESCE(worker_id, ''))) > 0
            AND claimed_at IS NOT NULL AND started_at IS NULL
            AND ended_at IS NULL AND heartbeat_at IS NOT NULL
            AND error_text IS NULL AND attempts < max_attempts)
          OR
          (status = 'running'
            AND LENGTH(TRIM(COALESCE(worker_id, ''))) > 0
            AND claimed_at IS NOT NULL AND started_at IS NOT NULL
            AND started_at >= claimed_at
            AND ended_at IS NULL AND heartbeat_at IS NOT NULL
            AND error_text IS NULL AND attempts <= max_attempts)
          OR
          (status = 'succeeded'
            AND LENGTH(TRIM(COALESCE(worker_id, ''))) > 0
            AND claimed_at IS NOT NULL AND started_at IS NOT NULL
            AND ended_at IS NOT NULL AND ended_at >= started_at
            AND error_text IS NULL)
          OR
          (status IN ('failed', 'interrupted')
            AND ended_at IS NOT NULL
            AND LENGTH(TRIM(COALESCE(error_text, ''))) > 0)
        )
        LIMIT 1
        """
    ).fetchone()
    if invalid is not None:
        raise RuntimeError(
            "reel_queue_schema_invalid_state_shape:"
            f"{invalid['job_id']}:{invalid['status']}"
        )
    event_mismatch = conn.execute(
        """
        SELECT q.job_id, q.status, latest.new_status
        FROM queue_jobs q
        JOIN queue_job_events latest
          ON latest.rowid = (
            SELECT MAX(event.rowid)
            FROM queue_job_events event
            WHERE event.job_id = q.job_id
          )
        WHERE latest.new_status != q.status
        LIMIT 1
        """
    ).fetchone()
    if event_mismatch is not None:
        raise RuntimeError(
            "reel_queue_schema_event_state_mismatch:"
            f"{event_mismatch['job_id']}:{event_mismatch['new_status']}:"
            f"{event_mismatch['status']}"
        )


def execute_script(conn: sqlite3.Connection, script: str) -> None:
    statement = ""
    for line in script.splitlines():
        statement += f"{line}\n"
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise RuntimeError("reel_schema_sql_incomplete")


def _require_tables(conn: sqlite3.Connection, required: set[str]) -> None:
    actual = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if missing := required - actual:
        raise RuntimeError(f"reel_schema_tables_missing:{','.join(sorted(missing))}")


def _require_triggers(conn: sqlite3.Connection, required: set[str]) -> None:
    actual = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    if missing := required - actual:
        raise RuntimeError(f"reel_schema_triggers_missing:{','.join(sorted(missing))}")
