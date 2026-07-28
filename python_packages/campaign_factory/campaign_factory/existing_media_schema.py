"""SQLite schema fragment for exact-lineage existing Creator OS media intake."""

from __future__ import annotations

EXISTING_MEDIA_SCHEMA = """
CREATE TABLE IF NOT EXISTS existing_media_intakes (
  id TEXT PRIMARY KEY,
  intake_identity TEXT NOT NULL UNIQUE,
  campaign_id TEXT NOT NULL,
  source_asset_id TEXT NOT NULL,
  rendered_asset_id TEXT NOT NULL,
  generation_attempt_id TEXT NOT NULL,
  final_sha256 TEXT NOT NULL,
  manifest_path TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL,
  audio_receipt_path TEXT NOT NULL,
  audio_receipt_sha256 TEXT NOT NULL,
  qc_receipt_path TEXT,
  qc_receipt_sha256 TEXT,
  eligibility_state TEXT NOT NULL,
  receipt_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
  FOREIGN KEY(source_asset_id) REFERENCES source_assets(id),
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id),
  FOREIGN KEY(generation_attempt_id) REFERENCES generation_attempts(id)
);

CREATE INDEX IF NOT EXISTS idx_existing_media_intakes_asset
  ON existing_media_intakes(rendered_asset_id, created_at);

CREATE TABLE IF NOT EXISTS existing_media_asset_reviews (
  id TEXT PRIMARY KEY,
  rendered_asset_id TEXT NOT NULL,
  final_sha256 TEXT NOT NULL,
  creator TEXT NOT NULL,
  reviewer TEXT NOT NULL,
  verdict TEXT NOT NULL,
  results_json TEXT NOT NULL DEFAULT '{}',
  notes TEXT,
  contract_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(rendered_asset_id, final_sha256, reviewer, verdict),
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id)
);

CREATE INDEX IF NOT EXISTS idx_existing_media_reviews_asset
  ON existing_media_asset_reviews(rendered_asset_id, created_at);

CREATE TRIGGER IF NOT EXISTS existing_media_reviews_immutable_update
BEFORE UPDATE ON existing_media_asset_reviews
BEGIN
  SELECT RAISE(ABORT, 'existing media reviews are immutable');
END;

CREATE TRIGGER IF NOT EXISTS existing_media_reviews_immutable_delete
BEFORE DELETE ON existing_media_asset_reviews
BEGIN
  SELECT RAISE(ABORT, 'existing media reviews are immutable');
END;
"""
