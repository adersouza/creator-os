from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Final

MIGRATION_ID: Final = "20260730_incident_privacy_observability_v1"

INCIDENT_PRIVACY_SCHEMA_SQL = """
CREATE TABLE incident_records (
  id TEXT PRIMARY KEY,
  incident_fingerprint TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL CHECK(category IN (
    'provider_ambiguity', 'overspend', 'missing_files', 'stale_approvals',
    'migration_failure', 'reconciliation_mismatch', 'consent_revocation',
    'cross_creator_contamination', 'failed_backup', 'failed_restore',
    'runtime_promotion_failure', 'handoff_ambiguity', 'security_finding'
  )),
  state TEXT NOT NULL CHECK(state IN (
    'detected', 'triaged', 'contained', 'manual_hold', 'repairing',
    'reconciled', 'verified', 'closed'
  )),
  severity TEXT NOT NULL CHECK(severity IN (
    'info', 'low', 'medium', 'high', 'critical'
  )),
  domain_owner TEXT NOT NULL,
  model_id TEXT,
  campaign_id TEXT,
  affected_assets_json TEXT NOT NULL DEFAULT '[]',
  external_effect_state TEXT NOT NULL CHECK(external_effect_state IN (
    'none', 'pre_effect', 'ambiguous', 'external_id_known',
    'finalized', 'reconciled', 'unknown'
  )),
  financial_exposure_json TEXT NOT NULL DEFAULT '{}',
  privacy_exposure_json TEXT NOT NULL DEFAULT '{}',
  owner TEXT NOT NULL,
  next_action TEXT NOT NULL,
  operator TEXT NOT NULL,
  detected_at TEXT NOT NULL,
  triaged_at TEXT,
  contained_at TEXT,
  manual_hold_at TEXT,
  repairing_at TEXT,
  reconciled_at TEXT,
  verified_at TEXT,
  closed_at TEXT,
  repair_actions_json TEXT NOT NULL DEFAULT '[]',
  verification_evidence_json TEXT NOT NULL DEFAULT '[]',
  closure_receipt_json TEXT,
  version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE,
  FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON UPDATE CASCADE
);

CREATE TABLE incident_events (
  id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  previous_state TEXT,
  new_state TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL CHECK(version > 0),
  created_at TEXT NOT NULL,
  FOREIGN KEY(incident_id) REFERENCES incident_records(id) ON UPDATE CASCADE,
  UNIQUE(incident_id, version)
);

CREATE TABLE incident_evidence_links (
  id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  evidence_sha256 TEXT,
  evidence_path TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY(incident_id) REFERENCES incident_records(id) ON UPDATE CASCADE,
  UNIQUE(incident_id, evidence_type, evidence_id)
);

CREATE INDEX idx_incident_records_open
  ON incident_records(state, severity, updated_at);
CREATE INDEX idx_incident_records_creator
  ON incident_records(model_id, state, updated_at);
CREATE INDEX idx_incident_records_campaign
  ON incident_records(campaign_id, state, updated_at);
CREATE INDEX idx_incident_events_incident
  ON incident_events(incident_id, version);

CREATE TABLE creator_privacy_requests (
  id TEXT PRIMARY KEY,
  request_fingerprint TEXT NOT NULL UNIQUE,
  model_id TEXT NOT NULL,
  request_type TEXT NOT NULL CHECK(request_type IN (
    'consent_revocation', 'creator_departure', 'account_disassociation',
    'deletion_request', 'legal_hold', 'backup_purge'
  )),
  state TEXT NOT NULL CHECK(state IN (
    'requested', 'scoped', 'manual_hold', 'authorized', 'executing',
    'verification_pending', 'verified', 'closed', 'blocked'
  )),
  future_use_required INTEGER NOT NULL CHECK(future_use_required IN (0, 1)),
  account_disassociation_required INTEGER NOT NULL
    CHECK(account_disassociation_required IN (0, 1)),
  provider_inventory_required INTEGER NOT NULL
    CHECK(provider_inventory_required IN (0, 1)),
  deletion_scope_json TEXT NOT NULL DEFAULT '{}',
  retention_policy_json TEXT NOT NULL DEFAULT '{}',
  operator TEXT NOT NULL,
  legal_basis TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  effective_at TEXT NOT NULL,
  verification_receipt_json TEXT,
  closure_receipt_json TEXT,
  closed_at TEXT,
  version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE
);

CREATE TABLE creator_privacy_request_events (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  previous_state TEXT,
  new_state TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL CHECK(version > 0),
  created_at TEXT NOT NULL,
  FOREIGN KEY(request_id) REFERENCES creator_privacy_requests(id)
    ON UPDATE CASCADE,
  UNIQUE(request_id, version)
);

CREATE TABLE creator_future_use_blocks (
  id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  block_reason TEXT NOT NULL,
  effective_at TEXT NOT NULL,
  operator TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE,
  FOREIGN KEY(request_id) REFERENCES creator_privacy_requests(id)
    ON UPDATE CASCADE,
  UNIQUE(model_id, request_id)
);

CREATE TABLE creator_account_disassociations (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  prior_external_id TEXT,
  external_effect_state TEXT NOT NULL CHECK(external_effect_state IN (
    'not_required', 'requested', 'confirmed', 'ambiguous'
  )),
  operator TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY(request_id) REFERENCES creator_privacy_requests(id)
    ON UPDATE CASCADE,
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE,
  FOREIGN KEY(account_id) REFERENCES accounts(id) ON UPDATE CASCADE,
  UNIQUE(request_id, account_id)
);

CREATE TABLE creator_legal_holds (
  id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL,
  request_id TEXT,
  status TEXT NOT NULL CHECK(status IN ('active', 'released')),
  scope_json TEXT NOT NULL,
  legal_authority TEXT NOT NULL,
  reason TEXT NOT NULL,
  operator TEXT NOT NULL,
  effective_at TEXT NOT NULL,
  released_at TEXT,
  release_receipt_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE,
  FOREIGN KEY(request_id) REFERENCES creator_privacy_requests(id)
    ON UPDATE CASCADE
);

CREATE INDEX idx_creator_legal_holds_active
  ON creator_legal_holds(model_id, status, effective_at);

CREATE TABLE creator_data_inventory (
  id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL,
  request_id TEXT,
  data_class TEXT NOT NULL CHECK(data_class IN (
    'identity_registry', 'source_asset', 'rendered_asset', 'platform_account',
    'backup', 'provider_copy', 'financial_evidence', 'security_evidence',
    'legal_evidence', 'audit_evidence'
  )),
  locator TEXT NOT NULL,
  content_sha256 TEXT,
  contains_bytes INTEGER NOT NULL CHECK(contains_bytes IN (0, 1)),
  provider TEXT,
  provider_retention_until TEXT,
  source_asset_id TEXT,
  rendered_asset_id TEXT,
  account_id TEXT,
  retention_state TEXT NOT NULL CHECK(retention_state IN (
    'active', 'retain_financial', 'retain_security', 'retain_legal',
    'retain_audit', 'legal_hold', 'deletion_authorized',
    'deletion_verified', 'tombstoned', 'provider_retention_unknown',
    'provider_deletion_requested', 'provider_deletion_verified',
    'backup_retained', 'backup_purge_authorized', 'backup_purge_verified'
  )),
  policy_json TEXT NOT NULL DEFAULT '{}',
  verification_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE,
  FOREIGN KEY(request_id) REFERENCES creator_privacy_requests(id)
    ON UPDATE CASCADE,
  FOREIGN KEY(source_asset_id) REFERENCES source_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(rendered_asset_id) REFERENCES rendered_assets(id) ON UPDATE CASCADE,
  FOREIGN KEY(account_id) REFERENCES accounts(id) ON UPDATE CASCADE,
  UNIQUE(model_id, data_class, locator)
);

CREATE TABLE creator_data_inventory_events (
  id TEXT PRIMARY KEY,
  inventory_id TEXT NOT NULL,
  previous_state TEXT,
  new_state TEXT NOT NULL,
  action TEXT NOT NULL,
  operator TEXT NOT NULL,
  actual_scope_json TEXT NOT NULL DEFAULT '{}',
  evidence_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL CHECK(version > 0),
  created_at TEXT NOT NULL,
  FOREIGN KEY(inventory_id) REFERENCES creator_data_inventory(id)
    ON UPDATE CASCADE,
  UNIQUE(inventory_id, version)
);

CREATE INDEX idx_creator_privacy_requests_model
  ON creator_privacy_requests(model_id, state, requested_at);
CREATE INDEX idx_creator_future_use_blocks_model
  ON creator_future_use_blocks(model_id, effective_at);
CREATE INDEX idx_creator_data_inventory_model
  ON creator_data_inventory(model_id, data_class, retention_state);

CREATE TRIGGER incident_records_no_delete
BEFORE DELETE ON incident_records
BEGIN
  SELECT RAISE(ABORT, 'incident records are retained evidence');
END;

CREATE TRIGGER incident_records_transition_guard
BEFORE UPDATE ON incident_records
WHEN NEW.id <> OLD.id
  OR NEW.incident_fingerprint <> OLD.incident_fingerprint
  OR NEW.category <> OLD.category
  OR NEW.severity <> OLD.severity
  OR NEW.domain_owner <> OLD.domain_owner
  OR NEW.model_id IS NOT OLD.model_id
  OR NEW.campaign_id IS NOT OLD.campaign_id
  OR NEW.affected_assets_json <> OLD.affected_assets_json
  OR NEW.external_effect_state <> OLD.external_effect_state
  OR NEW.financial_exposure_json <> OLD.financial_exposure_json
  OR NEW.privacy_exposure_json <> OLD.privacy_exposure_json
  OR NEW.operator <> OLD.operator
  OR NEW.detected_at <> OLD.detected_at
  OR NEW.created_at <> OLD.created_at
  OR NEW.version <> OLD.version + 1
  OR NOT EXISTS (
    SELECT 1 FROM incident_events e
    WHERE e.incident_id = OLD.id
      AND e.version = NEW.version
      AND e.previous_state = OLD.state
      AND e.new_state = NEW.state
  )
  OR NOT (
    (OLD.state = 'detected' AND NEW.state IN ('triaged', 'manual_hold'))
    OR (OLD.state = 'triaged' AND NEW.state IN ('contained', 'manual_hold'))
    OR (OLD.state = 'contained'
        AND NEW.state IN ('manual_hold', 'repairing', 'reconciled'))
    OR (OLD.state = 'manual_hold'
        AND NEW.state IN ('triaged', 'contained', 'repairing', 'reconciled'))
    OR (OLD.state = 'repairing'
        AND NEW.state IN ('manual_hold', 'reconciled'))
    OR (OLD.state = 'reconciled'
        AND NEW.state IN ('manual_hold', 'verified'))
    OR (OLD.state = 'verified'
        AND NEW.state IN ('manual_hold', 'closed'))
  )
  OR (
    NEW.state IN ('verified', 'closed')
    AND NEW.verification_evidence_json = '[]'
  )
  OR (
    NEW.state = 'closed'
    AND (
      NEW.closed_at IS NULL
      OR NEW.verification_evidence_json = '[]'
      OR NEW.closure_receipt_json IS NULL
      OR NEW.closure_receipt_json = '{}'
    )
  )
BEGIN
  SELECT RAISE(ABORT, 'incident transition requires exact evidence');
END;

CREATE TRIGGER incident_events_no_update
BEFORE UPDATE ON incident_events
BEGIN
  SELECT RAISE(ABORT, 'incident events are immutable');
END;

CREATE TRIGGER incident_events_no_delete
BEFORE DELETE ON incident_events
BEGIN
  SELECT RAISE(ABORT, 'incident events are immutable');
END;

CREATE TRIGGER incident_evidence_links_no_update
BEFORE UPDATE ON incident_evidence_links
BEGIN
  SELECT RAISE(ABORT, 'incident evidence links are immutable');
END;

CREATE TRIGGER incident_evidence_links_no_delete
BEFORE DELETE ON incident_evidence_links
BEGIN
  SELECT RAISE(ABORT, 'incident evidence links are immutable');
END;

CREATE TRIGGER creator_privacy_requests_no_delete
BEFORE DELETE ON creator_privacy_requests
BEGIN
  SELECT RAISE(ABORT, 'creator privacy requests are retained evidence');
END;

CREATE TRIGGER creator_privacy_requests_transition_guard
BEFORE UPDATE ON creator_privacy_requests
WHEN NEW.id <> OLD.id
  OR NEW.request_fingerprint <> OLD.request_fingerprint
  OR NEW.model_id <> OLD.model_id
  OR NEW.request_type <> OLD.request_type
  OR NEW.future_use_required <> OLD.future_use_required
  OR NEW.account_disassociation_required <> OLD.account_disassociation_required
  OR NEW.provider_inventory_required <> OLD.provider_inventory_required
  OR NEW.deletion_scope_json <> OLD.deletion_scope_json
  OR NEW.retention_policy_json <> OLD.retention_policy_json
  OR NEW.operator <> OLD.operator
  OR NEW.legal_basis <> OLD.legal_basis
  OR NEW.requested_at <> OLD.requested_at
  OR NEW.effective_at <> OLD.effective_at
  OR NEW.created_at <> OLD.created_at
  OR NEW.version <> OLD.version + 1
  OR NOT EXISTS (
    SELECT 1 FROM creator_privacy_request_events e
    WHERE e.request_id = OLD.id
      AND e.version = NEW.version
      AND e.previous_state = OLD.state
      AND e.new_state = NEW.state
  )
  OR NOT (
    (OLD.state = 'requested' AND NEW.state IN ('scoped', 'manual_hold', 'blocked'))
    OR (OLD.state = 'scoped'
        AND NEW.state IN ('authorized', 'manual_hold', 'blocked'))
    OR (OLD.state = 'authorized'
        AND NEW.state IN ('executing', 'manual_hold', 'blocked'))
    OR (OLD.state = 'executing'
        AND NEW.state IN ('verification_pending', 'manual_hold', 'blocked'))
    OR (OLD.state = 'verification_pending'
        AND NEW.state IN ('verified', 'manual_hold', 'blocked'))
    OR (OLD.state = 'manual_hold'
        AND NEW.state IN ('scoped', 'authorized', 'executing',
                          'verification_pending', 'blocked'))
    OR (OLD.state = 'blocked' AND NEW.state IN ('scoped', 'manual_hold'))
    OR (OLD.state = 'verified' AND NEW.state = 'closed')
  )
  OR (
    NEW.state IN ('verified', 'closed')
    AND (
      NEW.verification_receipt_json IS NULL
      OR NEW.verification_receipt_json = '{}'
    )
  )
  OR (
    NEW.state = 'closed'
    AND (
      NEW.closed_at IS NULL
      OR NEW.closure_receipt_json IS NULL
      OR NEW.closure_receipt_json = '{}'
    )
  )
BEGIN
  SELECT RAISE(ABORT, 'creator privacy transition requires exact evidence');
END;

CREATE TRIGGER creator_privacy_request_events_no_update
BEFORE UPDATE ON creator_privacy_request_events
BEGIN
  SELECT RAISE(ABORT, 'creator privacy request events are immutable');
END;

CREATE TRIGGER creator_privacy_request_events_no_delete
BEFORE DELETE ON creator_privacy_request_events
BEGIN
  SELECT RAISE(ABORT, 'creator privacy request events are immutable');
END;

CREATE TRIGGER creator_future_use_blocks_no_update
BEFORE UPDATE ON creator_future_use_blocks
BEGIN
  SELECT RAISE(ABORT, 'creator future-use blocks are immutable');
END;

CREATE TRIGGER creator_future_use_blocks_no_delete
BEFORE DELETE ON creator_future_use_blocks
BEGIN
  SELECT RAISE(ABORT, 'creator future-use blocks are immutable');
END;

CREATE TRIGGER creator_account_disassociations_no_update
BEFORE UPDATE ON creator_account_disassociations
BEGIN
  SELECT RAISE(ABORT, 'creator account disassociations are immutable');
END;

CREATE TRIGGER creator_account_disassociations_no_delete
BEFORE DELETE ON creator_account_disassociations
BEGIN
  SELECT RAISE(ABORT, 'creator account disassociations are immutable');
END;

CREATE TRIGGER creator_legal_holds_no_delete
BEFORE DELETE ON creator_legal_holds
BEGIN
  SELECT RAISE(ABORT, 'creator legal holds are retained evidence');
END;

CREATE TRIGGER creator_legal_holds_transition_guard
BEFORE UPDATE ON creator_legal_holds
WHEN NEW.id <> OLD.id
  OR NEW.model_id <> OLD.model_id
  OR NEW.request_id IS NOT OLD.request_id
  OR NEW.scope_json <> OLD.scope_json
  OR NEW.legal_authority <> OLD.legal_authority
  OR NEW.reason <> OLD.reason
  OR NEW.operator <> OLD.operator
  OR NEW.effective_at <> OLD.effective_at
  OR NEW.created_at <> OLD.created_at
  OR OLD.status <> 'active'
  OR NEW.status <> 'released'
  OR NEW.released_at IS NULL
  OR NEW.release_receipt_json IS NULL
  OR NEW.release_receipt_json = '{}'
BEGIN
  SELECT RAISE(ABORT, 'creator legal hold transition is invalid');
END;

CREATE TRIGGER creator_data_inventory_no_delete
BEFORE DELETE ON creator_data_inventory
BEGIN
  SELECT RAISE(ABORT, 'creator data inventory is retained evidence');
END;

CREATE TRIGGER creator_data_inventory_transition_guard
BEFORE UPDATE ON creator_data_inventory
WHEN NEW.id <> OLD.id
  OR NEW.model_id <> OLD.model_id
  OR NEW.request_id IS NOT OLD.request_id
  OR NEW.data_class <> OLD.data_class
  OR NEW.locator <> OLD.locator
  OR NEW.content_sha256 IS NOT OLD.content_sha256
  OR NEW.contains_bytes <> OLD.contains_bytes
  OR NEW.provider IS NOT OLD.provider
  OR NEW.provider_retention_until IS NOT OLD.provider_retention_until
  OR NEW.source_asset_id IS NOT OLD.source_asset_id
  OR NEW.rendered_asset_id IS NOT OLD.rendered_asset_id
  OR NEW.account_id IS NOT OLD.account_id
  OR NEW.policy_json <> OLD.policy_json
  OR NEW.created_at <> OLD.created_at
  OR NEW.version <> OLD.version + 1
  OR NOT EXISTS (
    SELECT 1 FROM creator_data_inventory_events e
    WHERE e.inventory_id = OLD.id
      AND e.version = NEW.version
      AND e.previous_state = OLD.retention_state
      AND e.new_state = NEW.retention_state
  )
BEGIN
  SELECT RAISE(ABORT, 'creator data inventory transition requires exact evidence');
END;

CREATE TRIGGER creator_data_inventory_events_no_update
BEFORE UPDATE ON creator_data_inventory_events
BEGIN
  SELECT RAISE(ABORT, 'creator data inventory events are immutable');
END;

CREATE TRIGGER creator_data_inventory_events_no_delete
BEFORE DELETE ON creator_data_inventory_events
BEGIN
  SELECT RAISE(ABORT, 'creator data inventory events are immutable');
END;
"""

REQUIRED_TABLES = frozenset(
    {
        "incident_records",
        "incident_events",
        "incident_evidence_links",
        "creator_privacy_requests",
        "creator_privacy_request_events",
        "creator_future_use_blocks",
        "creator_account_disassociations",
        "creator_legal_holds",
        "creator_data_inventory",
        "creator_data_inventory_events",
    }
)
REQUIRED_INDEXES = frozenset(
    {
        "idx_incident_records_open",
        "idx_incident_records_creator",
        "idx_incident_records_campaign",
        "idx_incident_events_incident",
        "idx_creator_legal_holds_active",
        "idx_creator_privacy_requests_model",
        "idx_creator_future_use_blocks_model",
        "idx_creator_data_inventory_model",
    }
)
REQUIRED_TRIGGERS = frozenset(
    {
        "incident_records_no_delete",
        "incident_records_transition_guard",
        "incident_events_no_update",
        "incident_events_no_delete",
        "incident_evidence_links_no_update",
        "incident_evidence_links_no_delete",
        "creator_privacy_requests_no_delete",
        "creator_privacy_requests_transition_guard",
        "creator_privacy_request_events_no_update",
        "creator_privacy_request_events_no_delete",
        "creator_future_use_blocks_no_update",
        "creator_future_use_blocks_no_delete",
        "creator_account_disassociations_no_update",
        "creator_account_disassociations_no_delete",
        "creator_legal_holds_no_delete",
        "creator_legal_holds_transition_guard",
        "creator_data_inventory_no_delete",
        "creator_data_inventory_transition_guard",
        "creator_data_inventory_events_no_update",
        "creator_data_inventory_events_no_delete",
    }
)


def checksum(migration_id: str) -> str:
    if migration_id != MIGRATION_ID:
        raise ValueError(f"unexpected campaign schema v6 migration id: {migration_id}")
    payload = json.dumps(
        {
            "migrationId": MIGRATION_ID,
            "schemaSql": INCIDENT_PRIVACY_SCHEMA_SQL,
            "requiredTables": sorted(REQUIRED_TABLES),
            "requiredIndexes": sorted(REQUIRED_INDEXES),
            "requiredTriggers": sorted(REQUIRED_TRIGGERS),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def apply(conn: sqlite3.Connection) -> None:
    _execute_transactional_script(conn, INCIDENT_PRIVACY_SCHEMA_SQL)


def postcondition(conn: sqlite3.Connection) -> None:
    objects: dict[str, set[str]] = {
        str(row["type"]): set()
        for row in conn.execute("SELECT DISTINCT type FROM sqlite_master").fetchall()
    }
    for row in conn.execute(
        """
        SELECT type, name FROM sqlite_master
        WHERE type IN ('table', 'index', 'trigger')
        """
    ).fetchall():
        objects.setdefault(str(row["type"]), set()).add(str(row["name"]))
    requirements = {
        "table": REQUIRED_TABLES,
        "index": REQUIRED_INDEXES,
        "trigger": REQUIRED_TRIGGERS,
    }
    for kind, required in requirements.items():
        if missing := required - objects.get(kind, set()):
            raise RuntimeError(
                f"campaign_schema_v6_{kind}s_missing:" + ",".join(sorted(missing))
            )


def _execute_transactional_script(conn: sqlite3.Connection, script: str) -> None:
    statement = ""
    for line in script.splitlines():
        statement += f"{line}\n"
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise RuntimeError("campaign_schema_v6_sql_incomplete")
