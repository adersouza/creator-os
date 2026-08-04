from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Final

MIGRATION_ID: Final = "20260803_provider_native_identity_v1"

_IDENTITY_TABLE_SQL: Final = """
CREATE TABLE creator_identity_profiles_v9 (
  id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  provider_identity_id TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version > 0),
  profile_json TEXT NOT NULL,
  profile_fingerprint TEXT NOT NULL,
  identity_manifest_path TEXT NOT NULL,
  identity_manifest_sha256 TEXT NOT NULL,
  canonical_source_asset_id TEXT,
  canonical_evidence_type TEXT NOT NULL
    CHECK(canonical_evidence_type IN (
      'operator_approved_original', 'provider_identity_attestation'
    )),
  provider_identity_evidence_path TEXT,
  provider_identity_evidence_sha256 TEXT,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK(status IN ('active', 'retired', 'revoked')),
  activated_at TEXT NOT NULL,
  retired_at TEXT,
  operator TEXT NOT NULL,
  created_at TEXT NOT NULL,
  CHECK (
    (
      canonical_evidence_type = 'operator_approved_original'
      AND canonical_source_asset_id IS NOT NULL
      AND provider_identity_evidence_path IS NULL
      AND provider_identity_evidence_sha256 IS NULL
    )
    OR
    (
      canonical_evidence_type = 'provider_identity_attestation'
      AND canonical_source_asset_id IS NULL
      AND length(provider_identity_evidence_path) > 0
      AND length(provider_identity_evidence_sha256) = 64
      AND provider_identity_evidence_sha256
          NOT GLOB '*[^0-9a-f]*'
    )
  ),
  FOREIGN KEY(model_id) REFERENCES models(id) ON UPDATE CASCADE,
  FOREIGN KEY(canonical_source_asset_id) REFERENCES source_assets(id)
    ON UPDATE CASCADE,
  UNIQUE(model_id, provider, version),
  UNIQUE(profile_fingerprint)
)
"""

_IDENTITY_GUARDS_SQL: Final = """
CREATE UNIQUE INDEX idx_creator_identity_profiles_active
  ON creator_identity_profiles(model_id, provider)
  WHERE status = 'active';

CREATE TRIGGER trg_creator_identity_profile_identity_immutable
BEFORE UPDATE ON creator_identity_profiles
WHEN NEW.model_id IS NOT OLD.model_id
  OR NEW.provider IS NOT OLD.provider
  OR NEW.provider_identity_id IS NOT OLD.provider_identity_id
  OR NEW.version IS NOT OLD.version
  OR NEW.profile_json IS NOT OLD.profile_json
  OR NEW.profile_fingerprint IS NOT OLD.profile_fingerprint
  OR NEW.identity_manifest_path IS NOT OLD.identity_manifest_path
  OR NEW.identity_manifest_sha256 IS NOT OLD.identity_manifest_sha256
  OR NEW.canonical_source_asset_id IS NOT OLD.canonical_source_asset_id
  OR NEW.canonical_evidence_type IS NOT OLD.canonical_evidence_type
  OR NEW.provider_identity_evidence_path
      IS NOT OLD.provider_identity_evidence_path
  OR NEW.provider_identity_evidence_sha256
      IS NOT OLD.provider_identity_evidence_sha256
  OR NEW.activated_at IS NOT OLD.activated_at
  OR NEW.operator IS NOT OLD.operator
  OR NEW.created_at IS NOT OLD.created_at
BEGIN
  SELECT RAISE(ABORT, 'creator identity evidence is immutable');
END;

CREATE TRIGGER trg_creator_identity_profile_transition
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

CREATE TRIGGER trg_creator_identity_profile_no_delete
BEFORE DELETE ON creator_identity_profiles
BEGIN
  SELECT RAISE(ABORT, 'creator identity profiles are immutable');
END;
"""


def checksum(migration_id: str) -> str:
    if migration_id != MIGRATION_ID:
        raise ValueError(f"unexpected campaign schema v9 migration id: {migration_id}")
    payload = json.dumps(
        {
            "migrationId": MIGRATION_ID,
            "identityTableSql": _IDENTITY_TABLE_SQL,
            "identityGuardsSql": _IDENTITY_GUARDS_SQL,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def apply(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS creator_identity_profiles_v9")
    conn.execute("DROP TRIGGER IF EXISTS trg_creator_identity_profile_no_delete")
    conn.execute("DROP TRIGGER IF EXISTS trg_creator_identity_profile_transition")
    conn.execute(
        "DROP TRIGGER IF EXISTS trg_creator_identity_profile_identity_immutable"
    )
    conn.execute("DROP INDEX IF EXISTS idx_creator_identity_profiles_active")
    conn.execute(_IDENTITY_TABLE_SQL)
    conn.execute(
        """
        INSERT INTO creator_identity_profiles_v9
        (id, model_id, provider, provider_identity_id, version, profile_json,
         profile_fingerprint, identity_manifest_path, identity_manifest_sha256,
         canonical_source_asset_id, canonical_evidence_type,
         provider_identity_evidence_path, provider_identity_evidence_sha256,
         status, activated_at, retired_at, operator, created_at)
        SELECT id, model_id, provider, provider_identity_id, version, profile_json,
               profile_fingerprint, identity_manifest_path,
               identity_manifest_sha256, canonical_source_asset_id,
               canonical_evidence_type, NULL, NULL, status, activated_at,
               retired_at, operator, created_at
        FROM creator_identity_profiles
        """
    )
    conn.execute("DROP TABLE creator_identity_profiles")
    conn.execute(
        "ALTER TABLE creator_identity_profiles_v9 RENAME TO creator_identity_profiles"
    )
    _execute_transactional_script(conn, _IDENTITY_GUARDS_SQL)


def postcondition(conn: sqlite3.Connection) -> None:
    columns = {
        str(row[1]): {"notnull": int(row[3])}
        for row in conn.execute("PRAGMA table_info(creator_identity_profiles)")
    }
    required = {
        "canonical_source_asset_id",
        "canonical_evidence_type",
        "provider_identity_evidence_path",
        "provider_identity_evidence_sha256",
    }
    if missing := required - columns.keys():
        raise RuntimeError(
            "campaign_schema_v9_columns_missing:" + ",".join(sorted(missing))
        )
    if columns["canonical_source_asset_id"]["notnull"] != 0:
        raise RuntimeError("campaign_schema_v9_canonical_source_still_required")
    invalid = conn.execute(
        """
        SELECT COUNT(*) FROM creator_identity_profiles
        WHERE NOT (
          (canonical_evidence_type = 'operator_approved_original'
           AND canonical_source_asset_id IS NOT NULL
           AND provider_identity_evidence_path IS NULL
           AND provider_identity_evidence_sha256 IS NULL)
          OR
          (canonical_evidence_type = 'provider_identity_attestation'
           AND canonical_source_asset_id IS NULL
           AND length(provider_identity_evidence_path) > 0
           AND length(provider_identity_evidence_sha256) = 64)
        )
        """
    ).fetchone()[0]
    if int(invalid):
        raise RuntimeError("campaign_schema_v9_identity_evidence_mode_invalid")
    objects = {
        str(row[0])
        for row in conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type IN ('index', 'trigger')
            """
        ).fetchall()
    }
    required_objects = {
        "idx_creator_identity_profiles_active",
        "trg_creator_identity_profile_identity_immutable",
        "trg_creator_identity_profile_transition",
        "trg_creator_identity_profile_no_delete",
    }
    if missing := required_objects - objects:
        raise RuntimeError(
            "campaign_schema_v9_guards_missing:" + ",".join(sorted(missing))
        )


def _execute_transactional_script(conn: sqlite3.Connection, script: str) -> None:
    statement = ""
    for line in script.splitlines():
        statement += f"{line}\n"
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise RuntimeError("campaign_schema_v9_sql_incomplete")
