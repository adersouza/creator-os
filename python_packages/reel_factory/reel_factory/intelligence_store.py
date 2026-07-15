"""Shared intelligence-layer schema and helpers for Reel Factory."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from reel_factory.sqlite_utils import connect_sqlite

from .state_paths import manifest_db_path


def db_path(root: Path) -> Path:
    return manifest_db_path(root)


def connect(root: Path) -> sqlite3.Connection:
    conn = connect_sqlite(db_path(root))
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_intelligence_schema(conn)
    return conn


def ensure_intelligence_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS reference_analysis (
        analysis_id TEXT PRIMARY KEY,
        reference_path TEXT NOT NULL,
        reference_hash TEXT,
        sidecar_path TEXT,
        model TEXT,
        frame_paths_json TEXT NOT NULL DEFAULT '[]',
        analysis_json TEXT NOT NULL,
        created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_reference_analysis_hash ON reference_analysis(reference_hash);

    CREATE TABLE IF NOT EXISTS media_embeddings (
        embedding_id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        entity_id TEXT,
        path TEXT,
        model TEXT NOT NULL,
        vector_json TEXT NOT NULL,
        text_json TEXT NOT NULL DEFAULT '{}',
        created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_media_embeddings_entity ON media_embeddings(entity_type, entity_id);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_media_embeddings_unique
        ON media_embeddings(entity_type, COALESCE(entity_id, ''), COALESCE(path, ''), model);

    CREATE TABLE IF NOT EXISTS reel_features (
        feature_id TEXT PRIMARY KEY,
        output_path TEXT NOT NULL UNIQUE,
        asset_generation_id TEXT,
        campaign_id TEXT,
        source_reference_id TEXT,
        scene TEXT,
        camera TEXT,
        pose TEXT,
        motion TEXT,
        outfit TEXT,
        creator TEXT,
        grid_source INTEGER NOT NULL DEFAULT 0,
        caption_style TEXT,
        hook_type TEXT,
        audio_track_id TEXT,
        body_style TEXT,
        features_json TEXT NOT NULL DEFAULT '{}',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    );

    """)
    _ensure_columns(
        conn,
        "variations",
        {
            "render_time_sec": "REAL",
        },
    )
    _ensure_columns(
        conn,
        "reel_features",
        {
            "audio_track_id": "TEXT",
        },
    )
    conn.commit()


def _ensure_columns(
    conn: sqlite3.Connection, table: str, columns: dict[str, str]
) -> None:
    if not _table_exists(conn, table):
        return
    existing = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )
