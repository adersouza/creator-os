from __future__ import annotations

OWNERSHIP_SCHEMA = """
CREATE TABLE IF NOT EXISTS reference_promotion_receipts (
  id TEXT PRIMARY KEY,
  source_system TEXT NOT NULL,
  source_record_id TEXT NOT NULL,
  source_fingerprint TEXT NOT NULL,
  source_database_identity TEXT NOT NULL,
  source_database_version TEXT NOT NULL,
  promotion_policy TEXT NOT NULL,
  destination_table TEXT NOT NULL,
  destination_record_id TEXT NOT NULL,
  promoted_at TEXT NOT NULL,
  UNIQUE(source_system, source_fingerprint, destination_table, destination_record_id)
);
"""
