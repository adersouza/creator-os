from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .config import DEFAULT_DB_PATH, ensure_data_dirs


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
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
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
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(reference_id, target_tool, model_profile)
);

CREATE INDEX IF NOT EXISTS idx_source_files_kind ON source_files(kind);
CREATE INDEX IF NOT EXISTS idx_source_files_account ON source_files(account);
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
"""


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    ensure_data_dirs(db_path.parent)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


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
