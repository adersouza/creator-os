RECOVERY_SCHEMA = """
CREATE TABLE IF NOT EXISTS performance_snapshot_observations (
  id TEXT PRIMARY KEY,
  post_id TEXT NOT NULL,
  snapshot_at TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  normalized_json TEXT NOT NULL,
  supersedes_observation_id TEXT,
  correction_reason TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(post_id, snapshot_at, source_hash),
  FOREIGN KEY(supersedes_observation_id)
    REFERENCES performance_snapshot_observations(id)
);

CREATE INDEX IF NOT EXISTS idx_performance_observation_window
  ON performance_snapshot_observations(post_id, snapshot_at, created_at);

CREATE TRIGGER IF NOT EXISTS performance_observations_immutable_update
BEFORE UPDATE ON performance_snapshot_observations
BEGIN
  SELECT RAISE(ABORT, 'raw performance observations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS performance_observations_immutable_delete
BEFORE DELETE ON performance_snapshot_observations
BEGIN
  SELECT RAISE(ABORT, 'raw performance observations are immutable');
END;

CREATE TABLE IF NOT EXISTS asset_inventory_reservation_events (
  id TEXT PRIMARY KEY,
  reservation_row_id TEXT NOT NULL,
  reservation_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  post_id TEXT,
  instagram_media_id TEXT,
  occurred_at TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  evidence_sha256 TEXT NOT NULL UNIQUE,
  FOREIGN KEY(reservation_row_id) REFERENCES asset_inventory_reservations(id)
    ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_asset_inventory_reservation_events_reservation
  ON asset_inventory_reservation_events(reservation_id, occurred_at);

CREATE TRIGGER IF NOT EXISTS asset_inventory_reservation_events_immutable_update
BEFORE UPDATE ON asset_inventory_reservation_events
BEGIN
  SELECT RAISE(ABORT, 'inventory reservation events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS asset_inventory_reservation_events_immutable_delete
BEFORE DELETE ON asset_inventory_reservation_events
BEGIN
  SELECT RAISE(ABORT, 'inventory reservation events are immutable');
END;

CREATE TABLE IF NOT EXISTS audio_publication_history (
  id TEXT PRIMARY KEY,
  audio_selection_id TEXT NOT NULL,
  campaign_id TEXT,
  rendered_asset_id TEXT NOT NULL,
  post_id TEXT,
  instagram_media_id TEXT NOT NULL,
  account_id TEXT,
  published_at TEXT NOT NULL,
  final_media_sha256 TEXT NOT NULL,
  track_sha256 TEXT NOT NULL,
  processed_segment_sha256 TEXT NOT NULL,
  segment_start_seconds REAL NOT NULL,
  segment_end_seconds REAL NOT NULL,
  linkage_json TEXT NOT NULL,
  linkage_sha256 TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  UNIQUE(audio_selection_id, instagram_media_id),
  FOREIGN KEY(audio_selection_id) REFERENCES audio_selections(id) ON UPDATE CASCADE,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_audio_publication_history_account
  ON audio_publication_history(account_id, published_at);

CREATE INDEX IF NOT EXISTS idx_audio_publication_history_track
  ON audio_publication_history(track_sha256, published_at);

CREATE TRIGGER IF NOT EXISTS audio_publication_history_immutable_update
BEFORE UPDATE ON audio_publication_history
BEGIN
  SELECT RAISE(ABORT, 'audio publication history is immutable');
END;

CREATE TRIGGER IF NOT EXISTS audio_publication_history_immutable_delete
BEFORE DELETE ON audio_publication_history
BEGIN
  SELECT RAISE(ABORT, 'audio publication history is immutable');
END;
"""
