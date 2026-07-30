from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import sqlite3
from datetime import UTC, datetime

from .creator_governance_schema import CREATOR_GOVERNANCE_SCHEMA

_GOVERNANCE_MIGRATION_ID = "20260730_creator_campaign_governance_v1"


def _migration_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(f"{prefix}:{value}".encode()).hexdigest()
    return f"{prefix}_{digest[:24]}"


def _apply_creator_governance_backfill(conn: sqlite3.Connection) -> None:
    """Backfill only ownership facts that existing rows prove unambiguously."""
    migration_checksum = hashlib.sha256(
        (
            _GOVERNANCE_MIGRATION_ID
            + "\n"
            + CREATOR_GOVERNANCE_SCHEMA
            + "\n"
            + inspect.getsource(_apply_creator_governance_backfill)
        ).encode()
    ).hexdigest()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          migration_id TEXT PRIMARY KEY,
          checksum TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('applying', 'applied', 'failed')),
          applied_at TEXT,
          source_version TEXT NOT NULL,
          details_json TEXT NOT NULL DEFAULT '{}',
          error TEXT
        )
        """
    )
    prior = conn.execute(
        "SELECT * FROM schema_migrations WHERE migration_id = ?",
        (_GOVERNANCE_MIGRATION_ID,),
    ).fetchone()
    if prior is not None:
        checksum = prior["checksum"] if isinstance(prior, sqlite3.Row) else prior[1]
        status = prior["status"] if isinstance(prior, sqlite3.Row) else prior[2]
        if checksum != migration_checksum:
            raise RuntimeError("creator_governance_migration_checksum_drift")
        if status == "applied":
            return
    now = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    source_version = (
        os.environ.get("CREATOR_OS_SOURCE_SHA") or f"migration:{migration_checksum}"
    )
    conn.execute(
        """
        INSERT INTO schema_migrations
        (migration_id, checksum, status, applied_at, source_version,
         details_json, error)
        VALUES (?, ?, 'applying', NULL, ?, '{}', NULL)
        ON CONFLICT(migration_id) DO UPDATE SET
          checksum = excluded.checksum,
          status = 'applying',
          applied_at = NULL,
          source_version = excluded.source_version,
          details_json = '{}',
          error = NULL
        """,
        (_GOVERNANCE_MIGRATION_ID, migration_checksum, source_version),
    )
    conn.commit()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for model in conn.execute("SELECT id, slug FROM models ORDER BY id").fetchall():
            model_id = str(model["id"] if isinstance(model, sqlite3.Row) else model[0])
            slug = str(model["slug"] if isinstance(model, sqlite3.Row) else model[1])
            conn.execute(
                """
                INSERT OR IGNORE INTO creator_lifecycle_state
                (model_id, status, status_reason, effective_at, changed_by, version,
                 offboarding_state, retention_state, updated_at)
                VALUES (?, 'active', 'legacy_creator_backfill_unverified_rights',
                        ?, 'schema_migration', 1, NULL, 'retain_audit', ?)
                """,
                (model_id, now, now),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO creator_lifecycle_events
                (id, model_id, old_status, new_status, reason, actor, effective_at,
                 evidence_json, version, created_at)
                VALUES (?, ?, NULL, 'active',
                        'legacy_creator_backfill_unverified_rights',
                        'schema_migration', ?, ?, 1, ?)
                """,
                (
                    _migration_id("creator_state", model_id),
                    model_id,
                    now,
                    json.dumps(
                        {
                            "migrationId": _GOVERNANCE_MIGRATION_ID,
                            "identityOrConsentFabricated": False,
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO creator_slug_history
                (id, model_id, slug, effective_at, retired_at, actor, reason,
                 created_at)
                VALUES (?, ?, ?, ?, NULL, 'schema_migration',
                        'legacy_creator_slug_backfill', ?)
                """,
                (_migration_id("creator_slug", model_id), model_id, slug, now, now),
            )

        ambiguous_campaigns: list[str] = []
        backfilled_campaigns: list[str] = []
        campaigns = conn.execute("SELECT id FROM campaigns ORDER BY id").fetchall()
        for campaign in campaigns:
            campaign_id = str(
                campaign["id"] if isinstance(campaign, sqlite3.Row) else campaign[0]
            )
            owners = conn.execute(
                """
                SELECT DISTINCT model_id FROM source_assets
                WHERE campaign_id = ? AND model_id IS NOT NULL
                ORDER BY model_id
                """,
                (campaign_id,),
            ).fetchall()
            owner_ids = [
                str(owner["model_id"] if isinstance(owner, sqlite3.Row) else owner[0])
                for owner in owners
            ]
            if len(owner_ids) != 1:
                ambiguous_campaigns.append(campaign_id)
                continue
            model_id = owner_ids[0]
            conn.execute(
                """
                INSERT OR IGNORE INTO campaign_governance
                (campaign_id, model_id, lifecycle_status, blocker_codes_json,
                 status_reason, changed_by, effective_at, version, updated_at)
                VALUES (?, ?, 'created', '[]', 'legacy_campaign_owner_backfill',
                        'schema_migration', ?, 1, ?)
                """,
                (campaign_id, model_id, now, now),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO campaign_lifecycle_events
                (id, campaign_id, model_id, old_status, new_status, reason, actor,
                 evidence_json, related_ids_json, version, created_at)
                VALUES (?, ?, ?, NULL, 'created',
                        'legacy_campaign_owner_backfill', 'schema_migration',
                        ?, '[]', 1, ?)
                """,
                (
                    _migration_id("campaign_state", campaign_id),
                    campaign_id,
                    model_id,
                    json.dumps(
                        {
                            "migrationId": _GOVERNANCE_MIGRATION_ID,
                            "ownershipEvidence": "single_distinct_source_asset_model",
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            backfilled_campaigns.append(campaign_id)
        for model in conn.execute("SELECT id FROM models ORDER BY id").fetchall():
            model_id = str(model["id"] if isinstance(model, sqlite3.Row) else model[0])
            state = conn.execute(
                "SELECT status, version FROM creator_lifecycle_state WHERE model_id = ?",
                (model_id,),
            ).fetchone()
            if state is None:
                raise RuntimeError(
                    f"creator_governance_backfill_missing_state:{model_id}"
                )
            version = int(
                state["version"] if isinstance(state, sqlite3.Row) else state[1]
            )
            status = str(
                state["status"] if isinstance(state, sqlite3.Row) else state[0]
            )
            event = conn.execute(
                """
                SELECT 1 FROM creator_lifecycle_events
                WHERE model_id = ? AND version = ? AND new_status = ?
                """,
                (model_id, version, status),
            ).fetchone()
            active_slug_count = conn.execute(
                """
                SELECT COUNT(*) FROM creator_slug_history
                WHERE model_id = ? AND retired_at IS NULL
                """,
                (model_id,),
            ).fetchone()[0]
            if event is None or int(active_slug_count) != 1:
                raise RuntimeError(
                    f"creator_governance_backfill_postcondition_failed:{model_id}"
                )
        for campaign_id in backfilled_campaigns:
            governance = conn.execute(
                """
                SELECT model_id, lifecycle_status, version FROM campaign_governance
                WHERE campaign_id = ?
                """,
                (campaign_id,),
            ).fetchone()
            event = (
                conn.execute(
                    """
                    SELECT 1 FROM campaign_lifecycle_events
                    WHERE campaign_id = ? AND model_id = ? AND version = ?
                      AND new_status = ?
                    """,
                    (
                        campaign_id,
                        governance["model_id"],
                        governance["version"],
                        governance["lifecycle_status"],
                    ),
                ).fetchone()
                if governance is not None
                else None
            )
            if governance is None or event is None:
                raise RuntimeError(
                    f"campaign_governance_backfill_postcondition_failed:{campaign_id}"
                )
        details = {
            "backfilledCampaignIds": backfilled_campaigns,
            "unresolvedCampaignIds": ambiguous_campaigns,
            "unresolvedReason": "campaign_requires_explicit_creator_owner"
            if ambiguous_campaigns
            else None,
        }
        conn.execute(
            """
            UPDATE schema_migrations
            SET status = 'applied', applied_at = ?, details_json = ?, error = NULL
            WHERE migration_id = ?
            """,
            (now, json.dumps(details, sort_keys=True), _GOVERNANCE_MIGRATION_ID),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        conn.execute(
            """
            UPDATE schema_migrations
            SET status = 'failed', error = ?
            WHERE migration_id = ?
            """,
            (f"{type(exc).__name__}:{exc}", _GOVERNANCE_MIGRATION_ID),
        )
        conn.commit()
        raise


def _ensure_generation_lineage_guards(conn: sqlite3.Connection) -> None:
    """Restore indexes/triggers if a legacy FK table rebuild removed them."""
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_generation_attempts_campaign_created
          ON generation_attempts(campaign_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_generation_attempts_blob
          ON generation_attempts(output_blob_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_generation_attempts_request
          ON generation_attempts(request_fingerprint);
        CREATE INDEX IF NOT EXISTS idx_generation_lineage_rendered
          ON generation_lineage_edges(rendered_asset_id, created_at);
        CREATE TRIGGER IF NOT EXISTS generation_attempts_append_only_update
        BEFORE UPDATE ON generation_attempts
        BEGIN
          SELECT RAISE(ABORT, 'generation_attempts are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS generation_output_blobs_immutable_update
        BEFORE UPDATE ON generation_output_blobs
        BEGIN
          SELECT RAISE(ABORT, 'generation_output_blobs are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS generation_output_blobs_immutable_delete
        BEFORE DELETE ON generation_output_blobs
        BEGIN
          SELECT RAISE(ABORT, 'generation_output_blobs are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS generation_attempts_append_only_delete
        BEFORE DELETE ON generation_attempts
        BEGIN
          SELECT RAISE(ABORT, 'generation_attempts are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS generation_lineage_edges_append_only_update
        BEFORE UPDATE ON generation_lineage_edges
        BEGIN
          SELECT RAISE(ABORT, 'generation_lineage_edges are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS generation_lineage_edges_append_only_delete
        BEFORE DELETE ON generation_lineage_edges
        BEGIN
          SELECT RAISE(ABORT, 'generation_lineage_edges are append-only');
        END;
        """
    )


def _backfill_generation_output_lineage(conn: sqlite3.Connection) -> None:
    """Give legacy rendered assets content identities without changing old reads."""
    conn.execute(
        """
        INSERT OR IGNORE INTO generation_output_blobs
        (id, content_sha256, byte_size, media_type, created_at)
        SELECT 'blob_' || lower(content_hash), lower(content_hash), NULL,
               COALESCE(NULLIF(media_type, ''), 'video'), created_at
        FROM rendered_assets
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO generation_attempts
        (id, campaign_id, pipeline_job_id, source_asset_id, rendered_asset_id,
         output_blob_id, request_fingerprint, model_id, motion_task, prompt_sha256,
         source_sha256, admission_fingerprint, input_json, worker_result_json,
         attempted_output_path, duplicate_disposition, created_at)
        SELECT 'attempt_legacy_' || id, campaign_id, NULL, source_asset_id, id,
               'blob_' || lower(content_hash), NULL,
               COALESCE(NULLIF(recipe, ''), 'legacy_unknown'), 'legacy_unknown',
               NULL, NULL, NULL, '{}', '{}', output_path, 'legacy_reference', created_at
        FROM rendered_assets
        WHERE NOT EXISTS (
          SELECT 1 FROM generation_attempts existing
          WHERE existing.rendered_asset_id = rendered_assets.id
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO generation_lineage_edges
        (id, generation_attempt_id, source_asset_id, rendered_asset_id,
         output_blob_id, relation, lineage_json, created_at)
        SELECT 'edge_legacy_' || id, 'attempt_legacy_' || id, source_asset_id, id,
               'blob_' || lower(content_hash), 'generated_output',
               '{"migration":"legacy_rendered_asset"}', created_at
        FROM rendered_assets
        WHERE EXISTS (
          SELECT 1 FROM generation_attempts existing
          WHERE existing.id = 'attempt_legacy_' || rendered_assets.id
            AND existing.duplicate_disposition = 'legacy_reference'
        )
        """
    )


def _migrate_source_assets_hash_scope(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'source_assets'"
    ).fetchone()
    sql = (row["sql"] if row else "") or ""
    if "content_hash TEXT NOT NULL UNIQUE" not in sql:
        indexes = {
            idx["name"]
            for idx in conn.execute("PRAGMA index_list(source_assets)").fetchall()
        }
        if "idx_source_assets_campaign_hash" not in indexes:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_source_assets_campaign_hash "
                "ON source_assets(campaign_id, content_hash)"
            )
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    conn.execute("ALTER TABLE source_assets RENAME TO source_assets_old_global_hash")
    conn.execute("PRAGMA legacy_alter_table = OFF")
    conn.execute(
        """
        CREATE TABLE source_assets (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          model_id TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          original_path TEXT NOT NULL,
          stored_path TEXT NOT NULL,
          filename TEXT NOT NULL,
          media_type TEXT NOT NULL DEFAULT 'video',
          content_surface TEXT NOT NULL DEFAULT 'reel',
          platform TEXT NOT NULL DEFAULT 'instagram',
          source_prompt TEXT,
          higgsfield_job_id TEXT,
          higgsfield_model TEXT,
          notes TEXT,
          account_ids_json TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'imported',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(campaign_id, content_hash),
          FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
          FOREIGN KEY(model_id) REFERENCES models(id)
        )
        """
    )
    columns = [
        "id",
        "campaign_id",
        "model_id",
        "content_hash",
        "original_path",
        "stored_path",
        "filename",
        "media_type",
        "content_surface",
        "platform",
        "source_prompt",
        "higgsfield_job_id",
        "higgsfield_model",
        "notes",
        "account_ids_json",
        "status",
        "created_at",
        "updated_at",
    ]
    joined = ", ".join(columns)
    conn.execute(
        f"INSERT INTO source_assets ({joined}) SELECT {joined} FROM source_assets_old_global_hash"
    )
    conn.execute("DROP TABLE source_assets_old_global_hash")
    conn.execute("PRAGMA foreign_keys = ON")


def _migrate_rendered_assets_hash_scope(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'rendered_assets'"
    ).fetchone()
    sql = (row["sql"] if row else "") or ""
    if "content_hash TEXT NOT NULL UNIQUE" not in sql:
        indexes = {
            idx["name"]
            for idx in conn.execute("PRAGMA index_list(rendered_assets)").fetchall()
        }
        if "idx_rendered_assets_campaign_hash" not in indexes:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_rendered_assets_campaign_hash "
                "ON rendered_assets(campaign_id, content_hash)"
            )
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    conn.execute(
        "ALTER TABLE rendered_assets RENAME TO rendered_assets_old_global_hash"
    )
    conn.execute("PRAGMA legacy_alter_table = OFF")
    conn.execute(
        """
        CREATE TABLE rendered_assets (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          source_asset_id TEXT NOT NULL,
          render_job_id TEXT,
          content_hash TEXT NOT NULL,
          output_path TEXT NOT NULL,
          campaign_path TEXT NOT NULL,
          filename TEXT NOT NULL,
          media_type TEXT NOT NULL DEFAULT 'video',
          content_surface TEXT NOT NULL DEFAULT 'reel',
          caption TEXT,
          caption_hash TEXT,
          caption_bank TEXT,
          caption_banks_json TEXT NOT NULL DEFAULT '[]',
          creator_mix TEXT,
          creator_model TEXT,
          frame_type TEXT,
          length_class TEXT,
          format_class TEXT,
          caption_fit_version TEXT,
          suitability_decision TEXT,
          suitability_reason TEXT,
          source_clip TEXT,
          caption_outcome_context_json TEXT NOT NULL DEFAULT '{}',
          caption_generation_json TEXT NOT NULL DEFAULT '{}',
          recipe TEXT,
          target_ratio TEXT,
          audit_status TEXT NOT NULL DEFAULT 'pending',
          review_state TEXT NOT NULL DEFAULT 'draft',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(campaign_id, content_hash),
          FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
          FOREIGN KEY(source_asset_id) REFERENCES source_assets(id),
          FOREIGN KEY(render_job_id) REFERENCES render_jobs(id)
        )
        """
    )
    columns = [
        "id",
        "campaign_id",
        "source_asset_id",
        "render_job_id",
        "content_hash",
        "output_path",
        "campaign_path",
        "filename",
        "media_type",
        "content_surface",
        "caption",
        "caption_hash",
        "caption_bank",
        "caption_banks_json",
        "creator_mix",
        "creator_model",
        "frame_type",
        "length_class",
        "format_class",
        "caption_fit_version",
        "suitability_decision",
        "suitability_reason",
        "source_clip",
        "caption_outcome_context_json",
        "caption_generation_json",
        "recipe",
        "target_ratio",
        "audit_status",
        "review_state",
        "created_at",
        "updated_at",
    ]
    joined = ", ".join(columns)
    conn.execute(
        f"INSERT INTO rendered_assets ({joined}) SELECT {joined} FROM rendered_assets_old_global_hash"
    )
    conn.execute("DROP TABLE rendered_assets_old_global_hash")
    conn.execute("PRAGMA foreign_keys = ON")


def _repair_source_asset_fk_references(conn: sqlite3.Connection) -> None:
    _repair_fk_references(conn, "source_assets_old_global_hash", "source_assets")


def _repair_fk_references(
    conn: sqlite3.Connection, broken_name: str, replacement_name: str
) -> None:
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql LIKE ?",
        (f"%{broken_name}%",),
    ).fetchall()
    if not rows:
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    for row in rows:
        table = row["name"]
        if table == broken_name:
            continue
        old_sql = row["sql"]
        new_sql = old_sql.replace(f'"{broken_name}"', replacement_name).replace(
            broken_name, replacement_name
        )
        temp_table = f"{table}_fk_repair"
        temp_sql = re.sub(
            rf"^CREATE TABLE\s+\"?{re.escape(table)}\"?",
            f"CREATE TABLE {temp_table}",
            new_sql,
            count=1,
            flags=re.I,
        )
        columns = [
            col["name"]
            for col in conn.execute(f"PRAGMA table_info({table})").fetchall()
        ]
        joined = ", ".join(columns)
        conn.execute(f"DROP TABLE IF EXISTS {temp_table}")
        conn.execute(temp_sql)
        conn.execute(
            f"INSERT INTO {temp_table} ({joined}) SELECT {joined} FROM {table}"
        )
        conn.execute(f"DROP TABLE {table}")
        conn.execute("PRAGMA legacy_alter_table = ON")
        conn.execute(f"ALTER TABLE {temp_table} RENAME TO {table}")
        conn.execute("PRAGMA legacy_alter_table = OFF")
    conn.execute("PRAGMA foreign_keys = ON")
