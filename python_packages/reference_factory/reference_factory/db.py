from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.sqlite import connect_sqlite
from creator_os_core.sqlite import ensure_columns as _ensure_columns

from .config import DEFAULT_DB_PATH, ensure_data_dirs
from .db_migrations import Migration, run_migrations

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS source_files (
  reference_id TEXT PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  account TEXT,
  file_name TEXT NOT NULL,
  extension TEXT NOT NULL,
  kind TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  mtime TEXT NOT NULL,
  path_hash TEXT NOT NULL,
  content_hash TEXT,
  source_views INTEGER,
  source_likes INTEGER,
  source_comments INTEGER,
  source_posted_at TEXT,
  source_platform TEXT,
  native_media_id TEXT,
  original_url TEXT,
  canonical_url TEXT,
  extractor TEXT,
  extractor_version TEXT,
  intake_metadata_json TEXT NOT NULL DEFAULT '{}',
  intake_receipt_path TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reference_anchor_receipts (
  id TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL REFERENCES source_files(reference_id),
  source_media_sha256 TEXT NOT NULL,
  selected_frame_sample_id TEXT NOT NULL REFERENCES frame_samples(id),
  selected_frame_sha256 TEXT NOT NULL,
  selected_time_sec REAL NOT NULL,
  score REAL NOT NULL,
  candidate_measurements_json TEXT NOT NULL,
  toolchain_json TEXT NOT NULL,
  implementation_fingerprint TEXT NOT NULL,
  receipt_path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(reference_id, implementation_fingerprint)
);

CREATE TABLE IF NOT EXISTS video_probes (
  reference_id TEXT PRIMARY KEY REFERENCES source_files(reference_id),
  valid INTEGER NOT NULL,
  duration_seconds REAL,
  width INTEGER,
  height INTEGER,
  fps REAL,
  codec TEXT,
  aspect_ratio REAL,
  rotation INTEGER,
  probe_json TEXT,
  error TEXT,
  probed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS frame_samples (
  id TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL REFERENCES source_files(reference_id),
  time_sec REAL NOT NULL,
  role TEXT NOT NULL,
  frame_path TEXT NOT NULL,
  width INTEGER,
  height INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE(reference_id, role)
);

CREATE TABLE IF NOT EXISTS ocr_results (
  id TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL REFERENCES source_files(reference_id),
  frame_sample_id TEXT REFERENCES frame_samples(id),
  engine TEXT NOT NULL,
  engine_version TEXT,
  requested_engine TEXT NOT NULL,
  fallback_used INTEGER NOT NULL DEFAULT 0,
  fallback_reason TEXT,
  ocr_text TEXT NOT NULL DEFAULT '',
  confidence REAL,
  boxes_json TEXT NOT NULL DEFAULT '[]',
  error TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(frame_sample_id, requested_engine)
);

CREATE TABLE IF NOT EXISTS caption_patterns (
  caption_hash TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL REFERENCES source_files(reference_id),
  normalized_text TEXT NOT NULL,
  raw_text TEXT NOT NULL,
  first_line TEXT,
  line_count INTEGER NOT NULL,
  char_count INTEGER NOT NULL,
  avg_confidence REAL,
  placement_json TEXT NOT NULL DEFAULT '{}',
  source_ocr_result_id TEXT REFERENCES ocr_results(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_labels (
  id TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL REFERENCES source_files(reference_id),
  label TEXT NOT NULL,
  tags_json TEXT NOT NULL DEFAULT '[]',
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(reference_id, label)
);

CREATE TABLE IF NOT EXISTS contact_sheets (
  id TEXT PRIMARY KEY,
  mode TEXT NOT NULL,
  sheet_path TEXT NOT NULL,
  html_path TEXT NOT NULL,
  reference_ids_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS public_posts (
  id TEXT PRIMARY KEY,
  owner_username TEXT,
  short_code TEXT,
  url TEXT,
  timestamp TEXT,
  product_type TEXT,
  post_type TEXT,
  caption TEXT,
  video_view_count INTEGER,
  video_play_count INTEGER,
  likes_count INTEGER,
  comments_count INTEGER,
  owner_follower_count INTEGER,
  public_rate_score REAL,
  public_follower_engagement_rate REAL,
  display_url TEXT,
  video_url TEXT,
  match_type TEXT NOT NULL DEFAULT 'external_only',
  reference_id TEXT REFERENCES source_files(reference_id),
  local_path TEXT,
  raw_json TEXT NOT NULL DEFAULT '{}',
  imported_at TEXT NOT NULL,
  UNIQUE(short_code)
);

CREATE TABLE IF NOT EXISTS prompt_cards (
  id TEXT PRIMARY KEY,
  public_post_id TEXT REFERENCES public_posts(id),
  rank INTEGER NOT NULL,
  prompt_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reference_patterns (
  id TEXT PRIMARY KEY,
  reference_id TEXT REFERENCES source_files(reference_id),
  public_post_id TEXT REFERENCES public_posts(id),
  rank INTEGER,
  provider TEXT NOT NULL,
  model TEXT,
  analyzer_version TEXT NOT NULL,
  suggested_label TEXT,
  visual_format TEXT,
  hook_type TEXT,
  caption_archetype TEXT,
  quality_score REAL NOT NULL,
  pattern_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(reference_id, public_post_id, analyzer_version)
);

CREATE TABLE IF NOT EXISTS audio_patterns (
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  audio_id TEXT NOT NULL,
  audio_title TEXT,
  artist_name TEXT,
  usage_type TEXT NOT NULL,
  visual_format TEXT,
  hook_type TEXT,
  caption_archetype TEXT,
  post_count INTEGER NOT NULL,
  total_plays INTEGER NOT NULL,
  median_plays INTEGER,
  top_accounts_json TEXT NOT NULL DEFAULT '[]',
  example_posts_json TEXT NOT NULL DEFAULT '[]',
  recommendation_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(platform, audio_id, visual_format, hook_type, caption_archetype)
);

CREATE TABLE IF NOT EXISTS audio_catalog (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  artist_name TEXT,
  source TEXT,
  platform TEXT NOT NULL,
  native_audio_id TEXT,
  native_audio_url TEXT,
  local_preview_path TEXT,
  mood_tags_json TEXT NOT NULL DEFAULT '[]',
  best_content_types_json TEXT NOT NULL DEFAULT '[]',
  account_fit_json TEXT NOT NULL DEFAULT '[]',
  bpm REAL,
  energy REAL,
  vocality TEXT,
  danceability REAL,
  valence REAL,
  trend_status TEXT NOT NULL DEFAULT 'unknown',
  usage_count INTEGER,
  safe_usage_notes TEXT,
  date_discovered TEXT,
  expires_at TEXT,
  example_reels_json TEXT NOT NULL DEFAULT '[]',
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(platform, native_audio_id)
);

CREATE TABLE IF NOT EXISTS audio_trend_snapshots (
  id TEXT PRIMARY KEY,
  audio_catalog_id TEXT NOT NULL REFERENCES audio_catalog(id),
  platform TEXT NOT NULL,
  native_audio_id TEXT,
  observed_at TEXT NOT NULL,
  trend_status TEXT NOT NULL DEFAULT 'unknown',
  usage_count INTEGER,
  saturation_score REAL,
  velocity_score REAL,
  curator TEXT,
  source TEXT,
  notes TEXT,
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(audio_catalog_id, observed_at)
);

CREATE TABLE IF NOT EXISTS learning_runs (
  id TEXT PRIMARY KEY,
  analyzer_version TEXT NOT NULL,
  limit_count INTEGER NOT NULL,
  output_dir TEXT,
  summary_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learning_clusters (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES learning_runs(id),
  cluster_key TEXT NOT NULL,
  rank INTEGER NOT NULL,
  label TEXT NOT NULL,
  visual_format TEXT NOT NULL,
  hook_type TEXT NOT NULL,
  caption_archetype TEXT NOT NULL,
  item_count INTEGER NOT NULL,
  avg_quality_score REAL NOT NULL,
  total_plays INTEGER NOT NULL,
  median_plays INTEGER,
  account_count INTEGER NOT NULL,
  top_reference_id TEXT,
  tags_json TEXT NOT NULL DEFAULT '[]',
  pattern_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(run_id, cluster_key)
);

CREATE TABLE IF NOT EXISTS reference_analysis_jobs (
  id TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL REFERENCES source_files(reference_id),
  source_platform TEXT NOT NULL DEFAULT 'unknown',
  provider_target TEXT NOT NULL DEFAULT 'gemini',
  account_profile TEXT,
  status TEXT NOT NULL DEFAULT 'needs_analysis',
  prompt_text TEXT NOT NULL,
  analysis_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(reference_id, provider_target, account_profile)
);

CREATE TABLE IF NOT EXISTS viral_pattern_cards (
  id TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL REFERENCES source_files(reference_id),
  analysis_job_id TEXT REFERENCES reference_analysis_jobs(id),
  platform TEXT NOT NULL DEFAULT 'unknown',
  status TEXT NOT NULL DEFAULT 'pattern_ready',
  pattern_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(reference_id, analysis_job_id)
);

CREATE TABLE IF NOT EXISTS reference_video_analyses (
  id TEXT PRIMARY KEY,
  reference_id TEXT NOT NULL REFERENCES source_files(reference_id),
  analysis_job_id TEXT REFERENCES reference_analysis_jobs(id),
  provider TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'analyzed',
  media_json TEXT NOT NULL DEFAULT '{}',
  signals_json TEXT NOT NULL DEFAULT '{}',
  pattern_card_id TEXT REFERENCES viral_pattern_cards(id),
  analysis_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(reference_id, provider)
);

CREATE TABLE IF NOT EXISTS generated_video_prompts (
  id TEXT PRIMARY KEY,
  analysis_job_id TEXT REFERENCES reference_analysis_jobs(id),
  reference_id TEXT NOT NULL REFERENCES source_files(reference_id),
  target_tool TEXT NOT NULL,
  model_profile TEXT,
  prompt_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  outcome_sample_count INTEGER NOT NULL DEFAULT 0,
  outcome_reward_score REAL,
  outcome_confidence REAL,
  outcome_updated_at TEXT,
  outcome_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(reference_id, target_tool, model_profile)
);

CREATE TABLE IF NOT EXISTS generated_prompt_reference_links (
  prompt_id TEXT NOT NULL REFERENCES generated_video_prompts(id) ON DELETE CASCADE,
  reference_id TEXT NOT NULL REFERENCES source_files(reference_id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  attribution_weight REAL NOT NULL DEFAULT 1.0,
  provenance_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(prompt_id, reference_id, role)
);

CREATE TABLE IF NOT EXISTS generated_prompt_external_references (
  prompt_id TEXT NOT NULL REFERENCES generated_video_prompts(id) ON DELETE CASCADE,
  external_reference_id TEXT NOT NULL,
  role TEXT NOT NULL,
  provenance_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(prompt_id, external_reference_id, role)
);

CREATE TABLE IF NOT EXISTS prompt_post_outcomes (
  prompt_id TEXT NOT NULL REFERENCES generated_video_prompts(id) ON DELETE CASCADE,
  post_id TEXT NOT NULL,
  reward_score REAL NOT NULL,
  confidence REAL,
  source_snapshot_at TEXT NOT NULL,
  scoring_version TEXT NOT NULL,
  baseline_provenance_json TEXT NOT NULL DEFAULT '{}',
  outcome_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(prompt_id, post_id)
);

CREATE INDEX IF NOT EXISTS idx_source_files_kind ON source_files(kind);
CREATE INDEX IF NOT EXISTS idx_source_files_account ON source_files(account);
CREATE UNIQUE INDEX IF NOT EXISTS idx_source_files_platform_media
  ON source_files(source_platform, native_media_id)
  WHERE source_platform IS NOT NULL AND native_media_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_source_files_content_hash ON source_files(content_hash);
CREATE INDEX IF NOT EXISTS idx_reference_anchor_reference
  ON reference_anchor_receipts(reference_id, created_at);
CREATE INDEX IF NOT EXISTS idx_video_probes_valid ON video_probes(valid);
CREATE INDEX IF NOT EXISTS idx_review_labels_reference ON review_labels(reference_id);
CREATE INDEX IF NOT EXISTS idx_public_posts_owner ON public_posts(owner_username);
CREATE INDEX IF NOT EXISTS idx_public_posts_rank ON public_posts(video_play_count, video_view_count);
CREATE INDEX IF NOT EXISTS idx_reference_patterns_reference ON reference_patterns(reference_id);
CREATE INDEX IF NOT EXISTS idx_reference_patterns_public_post ON reference_patterns(public_post_id);
CREATE INDEX IF NOT EXISTS idx_reference_patterns_quality ON reference_patterns(quality_score);
CREATE INDEX IF NOT EXISTS idx_audio_patterns_rank ON audio_patterns(total_plays, post_count);
CREATE INDEX IF NOT EXISTS idx_audio_catalog_platform ON audio_catalog(platform, trend_status);
CREATE INDEX IF NOT EXISTS idx_audio_catalog_expiry ON audio_catalog(expires_at);
CREATE INDEX IF NOT EXISTS idx_audio_trend_snapshots_audio ON audio_trend_snapshots(audio_catalog_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_audio_trend_snapshots_platform ON audio_trend_snapshots(platform, trend_status);
CREATE INDEX IF NOT EXISTS idx_learning_clusters_run ON learning_clusters(run_id);
CREATE INDEX IF NOT EXISTS idx_learning_clusters_rank ON learning_clusters(rank);
CREATE INDEX IF NOT EXISTS idx_reference_analysis_jobs_status ON reference_analysis_jobs(status, provider_target);
CREATE INDEX IF NOT EXISTS idx_viral_pattern_cards_status ON viral_pattern_cards(status, platform);
CREATE INDEX IF NOT EXISTS idx_reference_video_analyses_provider ON reference_video_analyses(provider, status);
CREATE INDEX IF NOT EXISTS idx_generated_video_prompts_tool ON generated_video_prompts(target_tool, status);
CREATE INDEX IF NOT EXISTS idx_generated_prompt_links_reference ON generated_prompt_reference_links(reference_id, role);
CREATE INDEX IF NOT EXISTS idx_generated_prompt_external_reference ON generated_prompt_external_references(external_reference_id, role);
CREATE INDEX IF NOT EXISTS idx_prompt_post_outcomes_post ON prompt_post_outcomes(post_id);
CREATE INDEX IF NOT EXISTS idx_prompt_post_outcomes_snapshot ON prompt_post_outcomes(source_snapshot_at);
"""

EVIDENCE_GUARDS = """
CREATE TABLE IF NOT EXISTS reference_compatibility_runs (
  run_id TEXT PRIMARY KEY,
  step_id TEXT NOT NULL,
  checksum TEXT NOT NULL,
  affected_rows INTEGER NOT NULL,
  source_version TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS reference_schema_migrations_applied_immutable_update
BEFORE UPDATE ON reference_schema_migrations
WHEN OLD.status = 'applied'
BEGIN
  SELECT RAISE(ABORT, 'applied reference migrations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS reference_schema_migrations_applied_immutable_delete
BEFORE DELETE ON reference_schema_migrations
WHEN OLD.status = 'applied'
BEGIN
  SELECT RAISE(ABORT, 'applied reference migrations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS reference_compatibility_runs_immutable_update
BEFORE UPDATE ON reference_compatibility_runs
BEGIN
  SELECT RAISE(ABORT, 'reference compatibility receipts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS reference_compatibility_runs_immutable_delete
BEFORE DELETE ON reference_compatibility_runs
BEGIN
  SELECT RAISE(ABORT, 'reference compatibility receipts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS reference_anchor_receipts_immutable_update
BEFORE UPDATE ON reference_anchor_receipts
BEGIN
  SELECT RAISE(ABORT, 'reference anchor receipts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS reference_anchor_receipts_immutable_delete
BEFORE DELETE ON reference_anchor_receipts
BEGIN
  SELECT RAISE(ABORT, 'reference anchor receipts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS learning_runs_immutable_update
BEFORE UPDATE ON learning_runs
BEGIN
  SELECT RAISE(ABORT, 'learning runs are immutable');
END;
CREATE TRIGGER IF NOT EXISTS learning_runs_immutable_delete
BEFORE DELETE ON learning_runs
BEGIN
  SELECT RAISE(ABORT, 'learning runs are immutable');
END;
CREATE TRIGGER IF NOT EXISTS learning_clusters_immutable_update
BEFORE UPDATE ON learning_clusters
BEGIN
  SELECT RAISE(ABORT, 'learning clusters are immutable');
END;
CREATE TRIGGER IF NOT EXISTS learning_clusters_immutable_delete
BEFORE DELETE ON learning_clusters
BEGIN
  SELECT RAISE(ABORT, 'learning clusters are immutable');
END;
CREATE TRIGGER IF NOT EXISTS audio_trend_snapshots_immutable_update
BEFORE UPDATE ON audio_trend_snapshots
BEGIN
  SELECT RAISE(ABORT, 'audio trend snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS audio_trend_snapshots_immutable_delete
BEFORE DELETE ON audio_trend_snapshots
BEGIN
  SELECT RAISE(ABORT, 'audio trend snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS reference_analysis_jobs_status_insert
BEFORE INSERT ON reference_analysis_jobs
WHEN NEW.status NOT IN ('needs_analysis', 'analyzed', 'pattern_ready')
BEGIN
  SELECT RAISE(ABORT, 'invalid reference analysis status');
END;
CREATE TRIGGER IF NOT EXISTS reference_analysis_jobs_status_update
BEFORE UPDATE OF status ON reference_analysis_jobs
WHEN NEW.status NOT IN ('needs_analysis', 'analyzed', 'pattern_ready')
BEGIN
  SELECT RAISE(ABORT, 'invalid reference analysis status');
END;
"""


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    ensure_data_dirs(db_path.parent)
    conn = connect_sqlite(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn, _migrations())
    with conn:
        updated = backfill_source_metrics_from_sidecars(conn)
        if updated:
            _record_compatibility_run(
                conn, "source_metric_sidecar_backfill_v1", updated
            )
    return conn


def _migrations() -> tuple[Migration, ...]:
    return (
        Migration(
            version=1,
            migration_id="20260730_reference_schema_baseline_v1",
            checksum_material=SCHEMA,
            apply=_apply_schema,
            postcondition=_schema_postcondition,
        ),
        Migration(
            version=2,
            migration_id="20260730_reference_evidence_guards_v1",
            checksum_material=EVIDENCE_GUARDS,
            apply=_apply_evidence_guards,
            postcondition=_guard_postcondition,
        ),
    )


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in _schema_statements("TABLE"):
        conn.execute(statement)
    _ensure_schema_columns(conn)
    for statement in _schema_statements("INDEX"):
        conn.execute(statement)


def _apply_evidence_guards(conn: sqlite3.Connection) -> None:
    statement = ""
    for line in EVIDENCE_GUARDS.splitlines():
        statement += f"{line}\n"
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise RuntimeError("reference_schema_guard_sql_incomplete")


def _schema_postcondition(conn: sqlite3.Connection) -> None:
    required = {
        "source_files",
        "reference_anchor_receipts",
        "reference_analysis_jobs",
        "generated_video_prompts",
        "prompt_post_outcomes",
    }
    actual = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if missing := required - actual:
        raise RuntimeError(
            f"reference_schema_tables_missing:{','.join(sorted(missing))}"
        )
    source_columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(source_files)").fetchall()
    }
    if (
        "source_platform" not in source_columns
        or "intake_metadata_json" not in source_columns
    ):
        raise RuntimeError("reference_schema_compatibility_columns_missing")


def _guard_postcondition(conn: sqlite3.Connection) -> None:
    required = {
        "reference_schema_migrations_applied_immutable_update",
        "reference_anchor_receipts_immutable_update",
        "learning_runs_immutable_update",
        "audio_trend_snapshots_immutable_update",
        "reference_analysis_jobs_status_update",
    }
    actual = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    if missing := required - actual:
        raise RuntimeError(
            f"reference_schema_triggers_missing:{','.join(sorted(missing))}"
        )


def _record_compatibility_run(
    conn: sqlite3.Connection, step_id: str, affected_rows: int
) -> None:
    now = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    state_rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT reference_id, source_views, source_likes, source_comments,
                   source_posted_at
            FROM source_files
            WHERE source_views IS NOT NULL OR source_likes IS NOT NULL
               OR source_comments IS NOT NULL OR source_posted_at IS NOT NULL
            ORDER BY reference_id
            """
        ).fetchall()
    ]
    state_checksum = hashlib.sha256(
        json.dumps(state_rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt_checksum = hashlib.sha256(
        f"{step_id}\n{state_checksum}".encode()
    ).hexdigest()
    conn.execute(
        """
        INSERT OR IGNORE INTO reference_compatibility_runs (
          run_id, step_id, checksum, affected_rows, source_version,
          details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"compat_{receipt_checksum[:32]}",
            step_id,
            receipt_checksum,
            affected_rows,
            os.environ.get("CREATOR_OS_SOURCE_SHA") or "unknown",
            json.dumps({"stateChecksum": state_checksum}, sort_keys=True),
            now,
        ),
    )


def _schema_statements(kind: str) -> list[str]:
    return re.findall(
        rf"CREATE (?:UNIQUE )?{kind} IF NOT EXISTS\b.*?;",
        SCHEMA,
        flags=re.S,
    )


def _ensure_schema_columns(conn: sqlite3.Connection) -> None:
    for table, columns in _declared_schema_columns().items():
        _ensure_columns(conn, table, columns)


def _declared_schema_columns() -> dict[str, dict[str, str]]:
    tables: dict[str, dict[str, str]] = {}
    for table, body in re.findall(
        r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s+\((.*?)\);",
        SCHEMA,
        flags=re.S,
    ):
        columns: dict[str, str] = {}
        for raw_line in body.splitlines():
            line = raw_line.strip().rstrip(",")
            if not line or line.upper().startswith(
                ("UNIQUE(", "FOREIGN ", "PRIMARY ", "CHECK(", "CONSTRAINT ")
            ):
                continue
            name, _, ddl = line.partition(" ")
            if not re.match(r"^[A-Za-z_]\w*$", name):
                continue
            if "PRIMARY KEY" in ddl.upper():
                continue
            columns[name] = ddl
        tables[table] = columns
    return tables


def source_metrics_from_info_json(media_path: Path) -> dict[str, Any]:
    for sidecar in _info_json_candidates(media_path):
        if not sidecar.exists():
            continue
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        return _source_metrics_from_payload(payload)
    return {
        "source_views": None,
        "source_likes": None,
        "source_comments": None,
        "source_posted_at": None,
    }


def backfill_source_metrics_from_sidecars(conn: sqlite3.Connection) -> int:
    updated = 0
    rows = conn.execute(
        """
        SELECT reference_id, path
        FROM source_files
        WHERE (source_views IS NULL OR source_likes IS NULL
          OR source_comments IS NULL OR source_posted_at IS NULL)
        """
    ).fetchall()
    for row in rows:
        metrics = source_metrics_from_info_json(Path(str(row["path"])))
        if not any(value is not None for value in metrics.values()):
            continue
        cursor = conn.execute(
            """
            UPDATE source_files
            SET source_views = COALESCE(source_views, ?),
                source_likes = COALESCE(source_likes, ?),
                source_comments = COALESCE(source_comments, ?),
                source_posted_at = COALESCE(source_posted_at, ?)
            WHERE reference_id = ?
              AND (
                (source_views IS NULL AND ? IS NOT NULL)
                OR (source_likes IS NULL AND ? IS NOT NULL)
                OR (source_comments IS NULL AND ? IS NOT NULL)
                OR (source_posted_at IS NULL AND ? IS NOT NULL)
              )
            """,
            (
                metrics["source_views"],
                metrics["source_likes"],
                metrics["source_comments"],
                metrics["source_posted_at"],
                row["reference_id"],
                metrics["source_views"],
                metrics["source_likes"],
                metrics["source_comments"],
                metrics["source_posted_at"],
            ),
        )
        updated += max(cursor.rowcount, 0)
    return updated


def _info_json_candidates(media_path: Path) -> list[Path]:
    return [
        media_path.with_suffix(".info.json"),
        Path(f"{media_path}.info.json"),
    ]


def _source_metrics_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_views": _int_or_none(
            _first_value(
                payload,
                "view_count",
                "views",
                "play_count",
                "video_view_count",
                "videoViewCount",
                "video_play_count",
                "videoPlayCount",
            )
        ),
        "source_likes": _int_or_none(
            _first_value(payload, "like_count", "likes", "likes_count", "likesCount")
        ),
        "source_comments": _int_or_none(
            _first_value(
                payload,
                "comment_count",
                "comments",
                "comments_count",
                "commentsCount",
            )
        ),
        "source_posted_at": _posted_at_from_payload(payload),
    }


def _first_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _posted_at_from_payload(payload: dict[str, Any]) -> str | None:
    timestamp = _int_or_none(
        _first_value(payload, "timestamp", "release_timestamp", "created_at")
    )
    if timestamp is not None:
        return datetime.fromtimestamp(timestamp, UTC).isoformat()
    upload_date = str(_first_value(payload, "upload_date", "release_date") or "")
    if re.fullmatch(r"\d{8}", upload_date):
        return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=UTC).isoformat()
    value = _first_value(payload, "posted_at", "postedAt", "uploadDate")
    return str(value) if value not in (None, "") else None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback
