"""Campaign-owned source intake and reconciliation evidence schema."""

SOURCE_LIFECYCLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_asset_lifecycle (
  source_asset_id TEXT PRIMARY KEY,
  lifecycle_state TEXT NOT NULL
    CHECK(lifecycle_state IN (
      'discovered', 'cataloged', 'quarantined', 'approved', 'rejected',
      'superseded', 'archived', 'deleted'
    )),
  storage_policy TEXT NOT NULL
    CHECK(storage_policy IN ('managed_copy', 'external_reference')),
  root_key TEXT,
  relative_path TEXT,
  classification_authority TEXT NOT NULL
    CHECK(classification_authority IN (
      'probe', 'probe_extension_agree', 'extension_fallback', 'unknown'
    )),
  detected_mime TEXT,
  probe_json TEXT NOT NULL DEFAULT '{}',
  quarantine_reason TEXT,
  backup_state TEXT NOT NULL DEFAULT 'unknown'
    CHECK(backup_state IN ('managed', 'external_unverified', 'unknown')),
  supersedes_source_asset_id TEXT,
  version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
  tombstoned_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  FOREIGN KEY(source_asset_id) REFERENCES source_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(supersedes_source_asset_id)
    REFERENCES source_assets(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_source_asset_lifecycle_state
  ON source_asset_lifecycle(lifecycle_state, updated_at);
CREATE INDEX IF NOT EXISTS idx_source_asset_lifecycle_storage
  ON source_asset_lifecycle(storage_policy, backup_state);

CREATE TRIGGER IF NOT EXISTS source_asset_lifecycle_transition_guard
BEFORE UPDATE OF lifecycle_state ON source_asset_lifecycle
WHEN OLD.lifecycle_state != NEW.lifecycle_state
 AND NOT (
   (OLD.lifecycle_state = 'discovered'
      AND NEW.lifecycle_state IN ('cataloged', 'quarantined'))
   OR (OLD.lifecycle_state = 'cataloged'
      AND NEW.lifecycle_state IN (
        'approved', 'rejected', 'quarantined', 'superseded', 'archived'
      ))
   OR (OLD.lifecycle_state = 'quarantined'
      AND NEW.lifecycle_state IN ('cataloged', 'rejected', 'archived'))
   OR (OLD.lifecycle_state = 'approved'
      AND NEW.lifecycle_state IN (
        'rejected', 'quarantined', 'superseded', 'archived'
      ))
   OR (OLD.lifecycle_state = 'rejected' AND NEW.lifecycle_state = 'archived')
   OR (OLD.lifecycle_state = 'superseded' AND NEW.lifecycle_state = 'archived')
   OR (OLD.lifecycle_state = 'archived' AND NEW.lifecycle_state = 'deleted')
 )
BEGIN
  SELECT RAISE(ABORT, 'invalid source lifecycle transition');
END;

CREATE TRIGGER IF NOT EXISTS source_asset_lifecycle_approval_backup_guard_insert
BEFORE INSERT ON source_asset_lifecycle
WHEN NEW.lifecycle_state = 'approved'
 AND NEW.storage_policy = 'external_reference'
 AND NEW.backup_state != 'managed'
BEGIN
  SELECT RAISE(ABORT, 'external source approval requires verified managed backup');
END;

CREATE TRIGGER IF NOT EXISTS source_asset_lifecycle_approval_backup_guard_update
BEFORE UPDATE OF lifecycle_state, storage_policy, backup_state
  ON source_asset_lifecycle
WHEN NEW.lifecycle_state = 'approved'
 AND NEW.storage_policy = 'external_reference'
 AND NEW.backup_state != 'managed'
BEGIN
  SELECT RAISE(ABORT, 'external source approval requires verified managed backup');
END;

CREATE TRIGGER IF NOT EXISTS source_asset_lifecycle_terminal_guard
BEFORE UPDATE ON source_asset_lifecycle
WHEN OLD.lifecycle_state = 'deleted'
BEGIN
  SELECT RAISE(ABORT, 'deleted source lifecycle is terminal');
END;

CREATE TRIGGER IF NOT EXISTS source_asset_lifecycle_delete_guard
BEFORE DELETE ON source_asset_lifecycle
BEGIN
  SELECT RAISE(ABORT, 'source lifecycle rows cannot be deleted');
END;

CREATE TABLE IF NOT EXISTS source_asset_lifecycle_events (
  id TEXT PRIMARY KEY,
  source_asset_id TEXT NOT NULL,
  previous_state TEXT,
  new_state TEXT NOT NULL,
  reason TEXT NOT NULL,
  actor TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY(source_asset_id) REFERENCES source_assets(id) ON UPDATE CASCADE
);

CREATE TRIGGER IF NOT EXISTS source_asset_lifecycle_events_immutable_update
BEFORE UPDATE ON source_asset_lifecycle_events
BEGIN
  SELECT RAISE(ABORT, 'source lifecycle events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS source_asset_lifecycle_events_immutable_delete
BEFORE DELETE ON source_asset_lifecycle_events
BEGIN
  SELECT RAISE(ABORT, 'source lifecycle events are immutable');
END;

CREATE TABLE IF NOT EXISTS artifact_reconciliation_repairs (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  case_fingerprint TEXT NOT NULL,
  finding_class TEXT NOT NULL,
  action TEXT NOT NULL,
  operator TEXT NOT NULL,
  reason TEXT NOT NULL,
  database_backup_path TEXT NOT NULL,
  database_backup_sha256 TEXT NOT NULL,
  file_backup_path TEXT,
  file_backup_sha256 TEXT,
  result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(case_id, case_fingerprint, action)
);

CREATE TRIGGER IF NOT EXISTS artifact_reconciliation_repairs_immutable_update
BEFORE UPDATE ON artifact_reconciliation_repairs
BEGIN
  SELECT RAISE(ABORT, 'artifact reconciliation repairs are immutable');
END;

CREATE TRIGGER IF NOT EXISTS artifact_reconciliation_repairs_immutable_delete
BEFORE DELETE ON artifact_reconciliation_repairs
BEGIN
  SELECT RAISE(ABORT, 'artifact reconciliation repairs are immutable');
END;
"""
