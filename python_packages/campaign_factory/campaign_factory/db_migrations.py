from __future__ import annotations

import re
import sqlite3


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
