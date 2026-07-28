"""Private Audio Radar cache schema and immutable prune evidence."""

AUDIO_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS audio_cache_objects (
  id TEXT PRIMARY KEY, audio_catalog_id TEXT NOT NULL,
  provider TEXT NOT NULL, platform TEXT NOT NULL, platform_sound_id TEXT NOT NULL,
  cache_path TEXT NOT NULL, byte_sha256 TEXT NOT NULL,
  acoustic_fingerprint TEXT NOT NULL, duration_seconds REAL NOT NULL,
  size_bytes INTEGER NOT NULL, codec TEXT NOT NULL, sample_rate INTEGER, channels INTEGER,
  source_fingerprint TEXT NOT NULL, source_metadata_json TEXT NOT NULL DEFAULT '{}',
  cached INTEGER NOT NULL DEFAULT 1, retrieved_at TEXT NOT NULL,
  pruned_at TEXT, prune_reason TEXT, created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  encoded_audio_sha256 TEXT, canonical_pcm_sha256 TEXT, chromaprint TEXT,
  chromaprint_version TEXT, chromaprint_duration_seconds REAL, container TEXT,
  channel_layout TEXT, loudness_json TEXT NOT NULL DEFAULT '{}',
  extraction_receipt_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(audio_catalog_id, byte_sha256),
  FOREIGN KEY(audio_catalog_id) REFERENCES audio_catalog(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS audio_cache_prune_receipts (
  id TEXT PRIMARY KEY, refresh_run_id TEXT NOT NULL,
  audio_cache_object_id TEXT NOT NULL, audio_catalog_id TEXT NOT NULL,
  cache_path TEXT NOT NULL, byte_sha256 TEXT NOT NULL,
  acoustic_fingerprint TEXT NOT NULL, size_bytes INTEGER NOT NULL,
  reason TEXT NOT NULL, pruned_at TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(refresh_run_id, audio_cache_object_id),
  FOREIGN KEY(refresh_run_id) REFERENCES audio_refresh_runs(id) ON UPDATE CASCADE,
  FOREIGN KEY(audio_cache_object_id) REFERENCES audio_cache_objects(id) ON UPDATE CASCADE,
  FOREIGN KEY(audio_catalog_id) REFERENCES audio_catalog(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_audio_cache_catalog
  ON audio_cache_objects(audio_catalog_id, cached, retrieved_at);
"""
