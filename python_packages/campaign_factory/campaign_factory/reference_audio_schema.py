"""Durable reference-audio occurrence and segment schema."""

REFERENCE_AUDIO_SCHEMA = """
CREATE TABLE IF NOT EXISTS audio_reference_occurrences (
  id TEXT PRIMARY KEY,
  audio_catalog_id TEXT,
  reference_id TEXT NOT NULL,
  source_platform TEXT NOT NULL,
  native_media_id TEXT,
  source_video_sha256 TEXT NOT NULL,
  encoded_audio_sha256 TEXT,
  canonical_pcm_sha256 TEXT,
  chromaprint TEXT,
  speaking_classification TEXT NOT NULL DEFAULT 'UNKNOWN',
  audio_policy_classification TEXT NOT NULL,
  source_start_seconds REAL NOT NULL DEFAULT 0,
  source_end_seconds REAL NOT NULL,
  extraction_receipt_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(reference_id),
  FOREIGN KEY(audio_catalog_id) REFERENCES audio_catalog(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS audio_segments (
  id TEXT PRIMARY KEY,
  audio_catalog_id TEXT,
  audio_reference_occurrence_id TEXT NOT NULL,
  start_seconds REAL NOT NULL,
  end_seconds REAL NOT NULL,
  duration_seconds REAL NOT NULL,
  start_sample INTEGER NOT NULL,
  end_sample INTEGER NOT NULL,
  sample_rate INTEGER NOT NULL DEFAULT 16000,
  canonical_pcm_segment_sha256 TEXT NOT NULL,
  decoded_fingerprint TEXT NOT NULL,
  onset_beat_json TEXT NOT NULL DEFAULT '{}',
  speech_private_voice_status TEXT NOT NULL DEFAULT 'unknown',
  reuse_status TEXT NOT NULL DEFAULT 'analysis_only',
  final_media_sha256 TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(audio_reference_occurrence_id, start_sample, end_sample),
  FOREIGN KEY(audio_catalog_id) REFERENCES audio_catalog(id) ON UPDATE CASCADE,
  FOREIGN KEY(audio_reference_occurrence_id) REFERENCES audio_reference_occurrences(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_audio_reference_catalog
  ON audio_reference_occurrences(audio_catalog_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audio_reference_sha
  ON audio_reference_occurrences(canonical_pcm_sha256, encoded_audio_sha256);
CREATE INDEX IF NOT EXISTS idx_audio_segments_catalog
  ON audio_segments(audio_catalog_id, created_at);
"""
