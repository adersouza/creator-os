from __future__ import annotations

import sqlite3

from campaign_factory.operator_status import (
    audio_status,
    campaign_status,
    creator_status,
    generation_status,
    learning_status,
    publication_status,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE models (id TEXT, slug TEXT, name TEXT);
        CREATE TABLE campaigns (id TEXT, slug TEXT, name TEXT, platform TEXT, updated_at TEXT);
        CREATE TABLE source_assets (id TEXT, campaign_id TEXT, model_id TEXT, media_type TEXT, status TEXT);
        CREATE TABLE rendered_assets (id TEXT, campaign_id TEXT, review_state TEXT);
        CREATE TABLE threadsdash_exports (campaign_id TEXT, status TEXT);
        CREATE TABLE performance_snapshots (
          id TEXT, campaign_id TEXT, rendered_asset_id TEXT, content_hash TEXT,
          post_id TEXT, status TEXT, account_id TEXT, instagram_account_id TEXT,
          permalink TEXT, published_at TEXT, snapshot_at TEXT, views INTEGER,
          likes INTEGER, comments INTEGER, shares INTEGER, saves INTEGER,
          raw_json TEXT
        );
        CREATE TABLE reference_knowledge_packs (id TEXT);
        CREATE TABLE recommendation_runs (id TEXT, campaign_id TEXT);
        CREATE TABLE recommendation_items (id TEXT, status TEXT);
        CREATE TABLE manager_decisions (id TEXT, decision_type TEXT);
        CREATE TABLE audio_performance_rollups (id TEXT);
        CREATE TABLE generation_attempts (
          id TEXT, campaign_id TEXT, pipeline_job_id TEXT, source_asset_id TEXT,
          rendered_asset_id TEXT, output_blob_id TEXT, request_fingerprint TEXT,
          model_id TEXT, motion_task TEXT, duplicate_disposition TEXT,
          attempted_output_path TEXT, created_at TEXT
        );
        CREATE TABLE generation_lineage_edges (generation_attempt_id TEXT);
        CREATE TABLE audio_catalog (
          id TEXT, active INTEGER, resolved INTEGER, lifecycle_state TEXT
        );
        CREATE TABLE audio_cache_objects (cached INTEGER, size_bytes INTEGER);
        CREATE TABLE audio_selections (id TEXT);
        CREATE TABLE audio_refresh_runs (
          id TEXT, region TEXT, status TEXT, started_at TEXT, completed_at TEXT,
          error_summary TEXT, receipt_path TEXT
        );
        INSERT INTO models VALUES ('model_1', 'stacey', 'Stacey');
        INSERT INTO campaigns VALUES ('camp_1', 'stacey-main', 'Stacey', 'instagram', 'now');
        INSERT INTO source_assets VALUES ('src_1', 'camp_1', 'model_1', 'image', 'approved');
        INSERT INTO rendered_assets VALUES ('asset_1', 'camp_1', 'approved');
        INSERT INTO generation_attempts VALUES (
          'gen_1', 'camp_1', 'job_1', 'src_1', 'asset_1', 'blob_1', 'fp_1',
          'kling3_0', 'image_to_video', 'unique', '/private/output.mp4', 'now'
        );
        INSERT INTO generation_lineage_edges VALUES ('gen_1');
        INSERT INTO performance_snapshots VALUES (
          'perf_1', 'camp_1', 'asset_1', 'hash', 'post_1', 'published',
          'account_1', 'ig_account_1', 'https://instagram/p/1', 'then', 'now',
          2, 1, 0, 0, 0, '{"instagramMediaId":"media_1"}'
        );
        INSERT INTO audio_catalog VALUES ('audio_1', 1, 1, 'HOT');
        INSERT INTO audio_cache_objects VALUES (1, 100);
        INSERT INTO audio_refresh_runs VALUES (
          'refresh_1', 'US', 'partial', 'then', 'now', NULL, '/private/receipt.json'
        );
        """
    )
    return conn


def test_scoped_statuses_are_bounded_and_read_only() -> None:
    conn = _conn()
    changes_before = conn.total_changes
    assert creator_status(conn, "stacey")["sources"]["approvedImages"] == 1
    assert campaign_status(conn, "stacey-main")["rendered"] == {"approved": 1}
    assert generation_status(conn, "fp_1")["lineageEdges"] == 1
    assert publication_status(conn, "media_1")["snapshots"][0]["post_id"] == "post_1"
    assert learning_status(conn)["knowledgePacks"] == 0
    assert audio_status(conn)["catalog"]["active"] == 1
    assert conn.total_changes == changes_before
