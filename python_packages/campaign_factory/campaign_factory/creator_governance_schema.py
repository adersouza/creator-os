CREATOR_GOVERNANCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS creator_lifecycle_state (
  model_id TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK(status IN (
      'active', 'suspended', 'departed', 'revoked',
      'deletion_pending', 'deleted'
    )),
  status_reason TEXT NOT NULL,
  effective_at TEXT NOT NULL,
  changed_by TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
  offboarding_state TEXT,
  retention_state TEXT NOT NULL DEFAULT 'retain_audit'
    CHECK(retention_state IN ('retain_audit', 'legal_hold', 'deletion_authorized')),
  updated_at TEXT NOT NULL,
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS creator_lifecycle_events (
  id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL,
  old_status TEXT,
  new_status TEXT NOT NULL,
  reason TEXT NOT NULL,
  actor TEXT NOT NULL,
  effective_at TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL CHECK(version > 0),
  created_at TEXT NOT NULL,
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS creator_slug_history (
  id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL,
  slug TEXT NOT NULL,
  effective_at TEXT NOT NULL,
  retired_at TEXT,
  actor TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE,
  UNIQUE(model_id, slug)
);

CREATE TABLE IF NOT EXISTS creator_identity_profiles (
  id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  provider_identity_id TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version > 0),
  profile_json TEXT NOT NULL,
  profile_fingerprint TEXT NOT NULL,
  identity_manifest_path TEXT NOT NULL,
  identity_manifest_sha256 TEXT NOT NULL,
  canonical_source_asset_id TEXT NOT NULL,
  canonical_evidence_type TEXT NOT NULL
    CHECK(canonical_evidence_type IN ('operator_approved_original')),
  status TEXT NOT NULL DEFAULT 'active'
    CHECK(status IN ('active', 'retired', 'revoked')),
  activated_at TEXT NOT NULL,
  retired_at TEXT,
  operator TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE,
  FOREIGN KEY(canonical_source_asset_id) REFERENCES source_assets(id)
    ON UPDATE CASCADE,
  UNIQUE(model_id, provider, version),
  UNIQUE(profile_fingerprint)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_creator_identity_profiles_active
  ON creator_identity_profiles(model_id, provider)
  WHERE status = 'active';

CREATE TABLE IF NOT EXISTS creator_authorization_events (
  id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL,
  authorization_id TEXT NOT NULL,
  event_type TEXT NOT NULL CHECK(event_type IN ('grant', 'revoke')),
  scope TEXT NOT NULL,
  provider TEXT NOT NULL,
  commercial_use INTEGER NOT NULL CHECK(commercial_use IN (0, 1)),
  territory_json TEXT NOT NULL DEFAULT '[]',
  account_scope_json TEXT NOT NULL DEFAULT '[]',
  provider_use INTEGER NOT NULL CHECK(provider_use IN (0, 1)),
  reference_video_use INTEGER NOT NULL CHECK(reference_video_use IN (0, 1)),
  training_reference_use INTEGER NOT NULL CHECK(training_reference_use IN (0, 1)),
  voice_authorized INTEGER NOT NULL CHECK(voice_authorized IN (0, 1)),
  effective_at TEXT NOT NULL,
  expires_at TEXT,
  evidence_path TEXT NOT NULL,
  evidence_sha256 TEXT NOT NULL,
  actor TEXT NOT NULL,
  reason TEXT NOT NULL,
  legal_hold INTEGER NOT NULL DEFAULT 0 CHECK(legal_hold IN (0, 1)),
  prior_event_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE,
  FOREIGN KEY(prior_event_id) REFERENCES creator_authorization_events(id),
  UNIQUE(authorization_id, event_type)
);

CREATE INDEX IF NOT EXISTS idx_creator_authorization_lookup
  ON creator_authorization_events(model_id, scope, provider, created_at);

CREATE INDEX IF NOT EXISTS idx_creator_lifecycle_events_model
  ON creator_lifecycle_events(model_id, version);

CREATE UNIQUE INDEX IF NOT EXISTS idx_creator_lifecycle_events_version
  ON creator_lifecycle_events(model_id, version);

CREATE INDEX IF NOT EXISTS idx_creator_slug_history_lookup
  ON creator_slug_history(slug, retired_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_creator_slug_history_active
  ON creator_slug_history(model_id)
  WHERE retired_at IS NULL;

CREATE TABLE IF NOT EXISTS campaign_governance (
  campaign_id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL,
  lifecycle_status TEXT NOT NULL DEFAULT 'created'
    CHECK(lifecycle_status IN (
      'created', 'configured', 'reference_ready', 'source_ready',
      'production_ready', 'producing', 'reviewing', 'approved',
      'exporting', 'paused', 'blocked', 'completed', 'cancelled', 'archived'
    )),
  blocker_codes_json TEXT NOT NULL DEFAULT '[]',
  status_reason TEXT NOT NULL,
  changed_by TEXT NOT NULL,
  effective_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
  updated_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS campaign_lifecycle_events (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  old_status TEXT,
  new_status TEXT NOT NULL,
  reason TEXT NOT NULL,
  actor TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  related_ids_json TEXT NOT NULL DEFAULT '[]',
  version INTEGER NOT NULL CHECK(version > 0),
  created_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE,
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_campaign_lifecycle_events_campaign
  ON campaign_lifecycle_events(campaign_id, version);

CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_lifecycle_events_version
  ON campaign_lifecycle_events(campaign_id, version);

CREATE TRIGGER IF NOT EXISTS trg_creator_lifecycle_state_no_delete
BEFORE DELETE ON creator_lifecycle_state
BEGIN
  SELECT RAISE(ABORT, 'creator lifecycle state requires a governed transition');
END;

CREATE TRIGGER IF NOT EXISTS trg_creator_lifecycle_state_event_required
BEFORE UPDATE ON creator_lifecycle_state
WHEN NEW.version <> OLD.version + 1
  OR NOT EXISTS (
    SELECT 1 FROM creator_lifecycle_events e
    WHERE e.model_id = OLD.model_id
      AND e.version = NEW.version
      AND e.old_status = OLD.status
      AND e.new_status = NEW.status
  )
BEGIN
  SELECT RAISE(ABORT, 'creator lifecycle update requires matching event');
END;

CREATE TRIGGER IF NOT EXISTS trg_campaign_governance_no_delete
BEFORE DELETE ON campaign_governance
BEGIN
  SELECT RAISE(ABORT, 'campaign governance requires a governed transition');
END;

CREATE TRIGGER IF NOT EXISTS trg_campaign_governance_event_required
BEFORE UPDATE ON campaign_governance
WHEN NEW.version <> OLD.version + 1
  OR NOT EXISTS (
    SELECT 1 FROM campaign_lifecycle_events e
    WHERE e.campaign_id = OLD.campaign_id
      AND e.version = NEW.version
      AND e.old_status = OLD.lifecycle_status
      AND e.new_status = NEW.lifecycle_status
  )
BEGIN
  SELECT RAISE(ABORT, 'campaign governance update requires matching event');
END;

CREATE TRIGGER IF NOT EXISTS trg_creator_lifecycle_events_no_update
BEFORE UPDATE ON creator_lifecycle_events
BEGIN
  SELECT RAISE(ABORT, 'creator_lifecycle_events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_creator_lifecycle_events_no_delete
BEFORE DELETE ON creator_lifecycle_events
BEGIN
  SELECT RAISE(ABORT, 'creator_lifecycle_events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_creator_authorization_events_no_update
BEFORE UPDATE ON creator_authorization_events
BEGIN
  SELECT RAISE(ABORT, 'creator_authorization_events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_creator_authorization_events_no_delete
BEFORE DELETE ON creator_authorization_events
BEGIN
  SELECT RAISE(ABORT, 'creator_authorization_events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_creator_slug_history_no_delete
BEFORE DELETE ON creator_slug_history
BEGIN
  SELECT RAISE(ABORT, 'creator_slug_history is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_creator_slug_history_identity_immutable
BEFORE UPDATE ON creator_slug_history
WHEN NEW.model_id <> OLD.model_id
  OR NEW.slug <> OLD.slug
  OR NEW.effective_at <> OLD.effective_at
  OR NEW.actor <> OLD.actor
  OR NEW.reason <> OLD.reason
  OR NEW.created_at <> OLD.created_at
  OR OLD.retired_at IS NOT NULL
  OR NEW.retired_at IS NULL
BEGIN
  SELECT RAISE(ABORT, 'creator slug evidence is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_campaign_lifecycle_events_no_update
BEFORE UPDATE ON campaign_lifecycle_events
BEGIN
  SELECT RAISE(ABORT, 'campaign_lifecycle_events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_campaign_lifecycle_events_no_delete
BEFORE DELETE ON campaign_lifecycle_events
BEGIN
  SELECT RAISE(ABORT, 'campaign_lifecycle_events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_creator_identity_profile_identity_immutable
BEFORE UPDATE ON creator_identity_profiles
WHEN NEW.model_id <> OLD.model_id
  OR NEW.provider <> OLD.provider
  OR NEW.provider_identity_id <> OLD.provider_identity_id
  OR NEW.version <> OLD.version
  OR NEW.profile_json <> OLD.profile_json
  OR NEW.profile_fingerprint <> OLD.profile_fingerprint
  OR NEW.identity_manifest_path <> OLD.identity_manifest_path
  OR NEW.identity_manifest_sha256 <> OLD.identity_manifest_sha256
  OR NEW.canonical_source_asset_id <> OLD.canonical_source_asset_id
  OR NEW.canonical_evidence_type <> OLD.canonical_evidence_type
  OR NEW.activated_at <> OLD.activated_at
  OR NEW.operator <> OLD.operator
  OR NEW.created_at <> OLD.created_at
BEGIN
  SELECT RAISE(ABORT, 'creator identity evidence is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_creator_identity_profile_transition
BEFORE UPDATE ON creator_identity_profiles
WHEN (
  NEW.status <> OLD.status
  OR NEW.retired_at IS NOT OLD.retired_at
)
AND NOT (
    OLD.status = 'active'
    AND NEW.status IN ('retired', 'revoked')
    AND OLD.retired_at IS NULL
    AND NEW.retired_at IS NOT NULL
  )
BEGIN
  SELECT RAISE(ABORT, 'creator identity transition is invalid');
END;

CREATE TRIGGER IF NOT EXISTS trg_creator_identity_profile_no_delete
BEFORE DELETE ON creator_identity_profiles
BEGIN
  SELECT RAISE(ABORT, 'creator identity profiles are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_source_asset_campaign_creator_insert
BEFORE INSERT ON source_assets
WHEN NOT EXISTS (
  SELECT 1 FROM campaign_governance cg
  WHERE cg.campaign_id = NEW.campaign_id AND cg.model_id = NEW.model_id
)
BEGIN
  SELECT RAISE(ABORT, 'source asset creator does not own campaign');
END;

CREATE TRIGGER IF NOT EXISTS trg_source_asset_campaign_creator_update
BEFORE UPDATE OF campaign_id, model_id ON source_assets
WHEN NOT EXISTS (
  SELECT 1 FROM campaign_governance cg
  WHERE cg.campaign_id = NEW.campaign_id AND cg.model_id = NEW.model_id
)
BEGIN
  SELECT RAISE(ABORT, 'source asset creator does not own campaign');
END;
"""
