from __future__ import annotations

import sqlite3
from pathlib import Path

from creator_os_core.sqlite import connect_sqlite
from creator_os_core.sqlite import ensure_columns as _ensure_columns

from .db_migrations import (
    _migrate_rendered_assets_hash_scope,
    _migrate_source_assets_hash_scope,
    _repair_fk_references,
    _repair_source_asset_fk_references,
)
from .db_schema import SCHEMA


def connect(db_path: Path) -> sqlite3.Connection:
    # Shared opener applies timeout + busy_timeout (overlapping cron writers
    # wait instead of failing with "database is locked") and WAL (readers
    # proceed during writes). foreign_keys stays campaign-specific.
    conn = connect_sqlite(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _ensure_columns(
        conn,
        "accounts",
        {
            "account_group_id": "TEXT",
            "oauth_granted_scopes_json": "TEXT",
            "oauth_scopes_verified_at": "TEXT",
            "trial_reels_capability": "TEXT NOT NULL DEFAULT 'unknown'",
            "trial_reels_capability_checked_at": "TEXT",
            "trial_reels_capability_reason": "TEXT",
            "threadsdash_is_active": "INTEGER",
            "threadsdash_status": "TEXT",
            "threadsdash_needs_reauth": "INTEGER",
            "threadsdash_sync_cohort": "TEXT",
            "threadsdash_projection_observed_at": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "audit_reports",
        {
            "layers_json": "TEXT NOT NULL DEFAULT '{}'",
            "verdicts_json": "TEXT NOT NULL DEFAULT '{}'",
            "overall_verdict": "TEXT",
            "files_analyzed": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    _ensure_columns(
        conn,
        "rendered_assets",
        {
            "media_type": "TEXT NOT NULL DEFAULT 'video'",
            "content_surface": "TEXT NOT NULL DEFAULT 'reel'",
            "parent_asset_id": "TEXT",
            "concept_id": "TEXT",
            "parent_reel_id": "TEXT",
            "variant_family_id": "TEXT",
            "variant_id": "TEXT",
            "variant_index": "INTEGER",
            "variant_operations_json": "TEXT NOT NULL DEFAULT '[]'",
            "caption_generation_json": "TEXT NOT NULL DEFAULT '{}'",
            "caption_hash": "TEXT",
            "caption_bank": "TEXT",
            "caption_banks_json": "TEXT NOT NULL DEFAULT '[]'",
            "creator_mix": "TEXT",
            "creator_model": "TEXT",
            "frame_type": "TEXT",
            "length_class": "TEXT",
            "format_class": "TEXT",
            "caption_fit_version": "TEXT",
            "suitability_decision": "TEXT",
            "suitability_reason": "TEXT",
            "source_clip": "TEXT",
            "caption_outcome_context_json": "TEXT NOT NULL DEFAULT '{}'",
            "metrics_eligible": "INTEGER NOT NULL DEFAULT 0",
            "story_asset_class": "TEXT",
            "story_cta_type": "TEXT",
            "story_cta_text": "TEXT",
            "story_cta_target_url": "TEXT",
            "story_intent": "TEXT",
            "story_goal": "TEXT",
            "story_style": "TEXT",
            "snapchat_username": "TEXT",
            "snapchat_display_name": "TEXT",
            "snapchat_cta_text": "TEXT",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            "origin_account_id": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "performance_snapshots",
        {
            "metrics_eligible": "INTEGER NOT NULL DEFAULT 0",
            "concept_id": "TEXT",
            "parent_reel_id": "TEXT",
            "caption_family_id": "TEXT",
            "caption_version_id": "TEXT",
            "caption_angle": "TEXT",
            "burned_caption_hash": "TEXT",
            "instagram_post_caption_hash": "TEXT",
            "variant_family_id": "TEXT",
            "variant_id": "TEXT",
            "variant_index": "INTEGER",
            "variant_operations_json": "TEXT NOT NULL DEFAULT '[]'",
            "audio_id": "TEXT",
            "content_surface": "TEXT NOT NULL DEFAULT 'reel'",
            "history_source": "TEXT",
            "lineage_v2_valid": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    _ensure_columns(
        conn,
        "proof_runs",
        {
            "current_state": "TEXT NOT NULL DEFAULT 'creative_approved'",
            "blocking_reason": "TEXT",
            "root_cause": "TEXT",
            "metrics_eligible": "INTEGER NOT NULL DEFAULT 0",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            "completed_at": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "quarantined_assets",
        {
            "distribution_plan_id": "TEXT",
            "threadsdash_post_id": "TEXT",
            "root_cause": "TEXT",
            "blocking_reason": "TEXT",
            "excluded_from_metrics": "INTEGER NOT NULL DEFAULT 1",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            "created_by": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "reference_patterns",
        {
            "audio_recommendations_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    _ensure_columns(
        conn,
        "audio_catalog",
        {
            "confidence": "REAL",
            "safe_usage_notes": "TEXT",
            "trend_score": "REAL",
            "velocity_score": "REAL",
            "fatigue_score": "REAL",
            "account_fit_score": "REAL",
            "creator_fit_score": "REAL",
            "recommendation_confidence": "TEXT",
            "performance_lift": "REAL",
            "source_confidence": "REAL",
            "trend_sources_json": "TEXT NOT NULL DEFAULT '[]'",
            "resolved": "INTEGER NOT NULL DEFAULT 0",
            "review_reasons_json": "TEXT NOT NULL DEFAULT '[]'",
            "example_reels_json": "TEXT NOT NULL DEFAULT '[]'",
            "performance_summary_json": "TEXT NOT NULL DEFAULT '{}'",
            "fatigue_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    _ensure_columns(
        conn,
        "source_assets",
        {
            "media_type": "TEXT NOT NULL DEFAULT 'video'",
            "content_surface": "TEXT NOT NULL DEFAULT 'reel'",
        },
    )
    _ensure_columns(
        conn,
        "performance_snapshots",
        {
            "impressions": "INTEGER",
            "caption_text": "TEXT",
            "caption_family_id": "TEXT",
            "caption_version_id": "TEXT",
            "caption_angle": "TEXT",
            "burned_caption_hash": "TEXT",
            "instagram_post_caption_hash": "TEXT",
            "caption_bank": "TEXT",
            "caption_banks_json": "TEXT NOT NULL DEFAULT '[]'",
            "creator_mix": "TEXT",
            "creator_model": "TEXT",
            "frame_type": "TEXT",
            "length_class": "TEXT",
            "format_class": "TEXT",
            "caption_fit_version": "TEXT",
            "suitability_decision": "TEXT",
            "suitability_reason": "TEXT",
            "source_clip": "TEXT",
            "caption_outcome_context_json": "TEXT NOT NULL DEFAULT '{}'",
            "concept_id": "TEXT",
            "parent_reel_id": "TEXT",
            "variant_family_id": "TEXT",
            "variant_id": "TEXT",
            "variant_index": "INTEGER",
            "variant_operations_json": "TEXT NOT NULL DEFAULT '[]'",
            "audio_id": "TEXT",
            "content_surface": "TEXT NOT NULL DEFAULT 'reel'",
            "history_source": "TEXT",
            "lineage_v2_valid": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    _ensure_columns(
        conn,
        "asset_account_assignments",
        {
            "caption_hash": "TEXT",
            "caption_text": "TEXT",
            "caption_bank": "TEXT",
            "caption_banks_json": "TEXT NOT NULL DEFAULT '[]'",
            "creator_mix": "TEXT",
            "creator_model": "TEXT",
            "frame_type": "TEXT",
            "length_class": "TEXT",
            "format_class": "TEXT",
            "caption_fit_version": "TEXT",
            "suitability_decision": "TEXT",
            "suitability_reason": "TEXT",
            "source_clip": "TEXT",
            "caption_outcome_context_json": "TEXT NOT NULL DEFAULT '{}'",
            "instagram_trial_reels": "INTEGER NOT NULL DEFAULT 0",
            "trial_graduation_strategy": "TEXT",
            "source_family_id": "TEXT",
            "perceptual_fingerprint": "TEXT",
            "perceptual_cluster_id": "TEXT",
            "account_group_id": "TEXT",
            "account_eligibility_json": "TEXT NOT NULL DEFAULT '{}'",
            "assignment_eligibility_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    _ensure_columns(
        conn,
        "distribution_plans",
        {
            "concept_id": "TEXT",
            "parent_reel_id": "TEXT",
            "caption_family_id": "TEXT",
            "caption_version_id": "TEXT",
            "caption_angle": "TEXT",
            "burned_caption_hash": "TEXT",
            "instagram_post_caption_hash": "TEXT",
            "variant_family_id": "TEXT",
            "variant_id": "TEXT",
            "variant_index": "INTEGER",
            "variant_operations_json": "TEXT NOT NULL DEFAULT '[]'",
            "content_surface": "TEXT NOT NULL DEFAULT 'reel'",
            "caption_hash": "TEXT",
            "caption_text": "TEXT",
            "caption_bank": "TEXT",
            "caption_banks_json": "TEXT NOT NULL DEFAULT '[]'",
            "creator_mix": "TEXT",
            "creator_model": "TEXT",
            "frame_type": "TEXT",
            "length_class": "TEXT",
            "format_class": "TEXT",
            "caption_fit_version": "TEXT",
            "suitability_decision": "TEXT",
            "suitability_reason": "TEXT",
            "source_clip": "TEXT",
            "caption_outcome_context_json": "TEXT NOT NULL DEFAULT '{}'",
            "story_asset_class": "TEXT",
            "story_cta_type": "TEXT",
            "story_cta_text": "TEXT",
            "story_cta_target_url": "TEXT",
            "story_intent": "TEXT",
            "story_goal": "TEXT",
            "story_style": "TEXT",
            "snapchat_username": "TEXT",
            "snapchat_display_name": "TEXT",
            "snapchat_cta_text": "TEXT",
            "instagram_trial_reels": "INTEGER NOT NULL DEFAULT 0",
            "trial_graduation_strategy": "TEXT",
            "trial_group_id": "TEXT",
            "trial_capability_status": "TEXT",
            "trial_capability_checked_at": "TEXT",
            "trial_capability_reason": "TEXT",
            "trial_capability_authorization": "TEXT",
            "source_family_id": "TEXT",
            "perceptual_fingerprint": "TEXT",
            "perceptual_cluster_id": "TEXT",
            "account_group_id": "TEXT",
            "account_eligibility_json": "TEXT NOT NULL DEFAULT '{}'",
            "assignment_eligibility_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    _ensure_columns(
        conn,
        "asset_inventory_reservations",
        {
            "account_eligibility_json": "TEXT NOT NULL DEFAULT '{}'",
            "assignment_eligibility_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    _ensure_columns(conn, "promotions", {"account_group_id": "TEXT"})
    _ensure_columns(
        conn,
        "promotion_events",
        {
            "rendered_asset_id": "TEXT",
            "content_fingerprint": "TEXT",
            "account_id": "TEXT",
            "posting_slot_id": "TEXT",
            "reason": "TEXT",
        },
    )
    conn.execute(
        """
        UPDATE promotions
        SET account_group_id = COALESCE(
            NULLIF(account_group_id, ''),
            (
                SELECT COALESCE(NULLIF(a.account_group_id, ''), NULLIF(a.model_id, ''))
                FROM accounts a
                WHERE a.id = promotions.account_id
            ),
            campaign_id
        )
        WHERE account_group_id IS NULL OR account_group_id = ''
        """
    )
    conn.execute(
        """
        UPDATE promotion_events
        SET rendered_asset_id = COALESCE(
                NULLIF(rendered_asset_id, ''),
                (SELECT p.rendered_asset_id FROM promotions p WHERE p.id = promotion_events.promotion_id)
            ),
            content_fingerprint = COALESCE(
                NULLIF(content_fingerprint, ''),
                (SELECT p.content_fingerprint FROM promotions p WHERE p.id = promotion_events.promotion_id)
            ),
            account_id = COALESCE(
                NULLIF(account_id, ''),
                (SELECT p.account_id FROM promotions p WHERE p.id = promotion_events.promotion_id)
            ),
            posting_slot_id = COALESCE(
                NULLIF(posting_slot_id, ''),
                (SELECT p.posting_slot_id FROM promotions p WHERE p.id = promotion_events.promotion_id)
            )
        WHERE rendered_asset_id IS NULL OR rendered_asset_id = ''
           OR content_fingerprint IS NULL OR content_fingerprint = ''
           OR account_id IS NULL OR account_id = ''
           OR posting_slot_id IS NULL OR posting_slot_id = ''
        """
    )
    _ensure_columns(
        conn,
        "account_content_requirements",
        {
            "main_reels_per_day": "INTEGER NOT NULL DEFAULT 1",
            "trial_reels_per_day": "INTEGER NOT NULL DEFAULT 2",
        },
    )
    _ensure_columns(
        conn,
        "variant_families",
        {
            "caption_family_id": "TEXT",
            "caption_version_id": "TEXT",
            "content_surface": "TEXT NOT NULL DEFAULT 'reel'",
        },
    )
    _ensure_columns(
        conn,
        "variant_assets",
        {
            "caption_family_id": "TEXT",
            "caption_version_id": "TEXT",
            "content_surface": "TEXT NOT NULL DEFAULT 'reel'",
        },
    )
    _ensure_columns(
        conn,
        "recommendation_items",
        {
            "status": "TEXT NOT NULL DEFAULT 'proposed'",
            "execution_status": "TEXT NOT NULL DEFAULT 'not_started'",
            "evidence_json": "TEXT NOT NULL DEFAULT '{}'",
            "data_quality_json": "TEXT NOT NULL DEFAULT '{}'",
            "decision_json": "TEXT NOT NULL DEFAULT '{}'",
            "outcome_json": "TEXT NOT NULL DEFAULT '{}'",
            "baseline_json": "TEXT NOT NULL DEFAULT '{}'",
            "measurement_version": "TEXT",
            "accepted_at": "TEXT",
            "rejected_at": "TEXT",
            "executed_at": "TEXT",
            "posted_at": "TEXT",
            "measured_at": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "trust_exceptions",
        {
            "snoozed_until": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "recommendation_accuracy_reports",
        {
            "account_key": "TEXT NOT NULL DEFAULT ''",
        },
    )
    _migrate_source_assets_hash_scope(conn)
    _migrate_rendered_assets_hash_scope(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_performance_caption_bank ON performance_snapshots(caption_bank)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_caption_versions_parent ON caption_versions(parent_asset_id, caption_family_index)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_caption_versions_angle ON caption_versions(caption_angle)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_performance_caption_version ON performance_snapshots(caption_family_id, caption_version_id, caption_angle)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_assets_surface ON source_assets(content_surface)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rendered_assets_surface ON rendered_assets(content_surface)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_distribution_plans_surface ON distribution_plans(content_surface, surface)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_performance_surface ON performance_snapshots(content_surface, snapshot_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_account_requirements_creator_surface ON account_content_requirements(creator, content_surface, active)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_components_asset_order ON asset_components(asset_id, component_index)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_performance_creator_mix ON performance_snapshots(creator_mix)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_performance_caption_fit ON performance_snapshots(frame_type, length_class, format_class, caption_fit_version)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_performance_learning_eligible "
        "ON performance_snapshots(campaign_id, metrics_eligible, history_source, lineage_v2_valid, published_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_distribution_plans_caption_hash ON distribution_plans(caption_hash)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_promotions_identity_window_v2 "
        "ON promotions(content_fingerprint, account_group_id, created_at, account_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_promotion_events_identity "
        "ON promotion_events(content_fingerprint, account_id, posting_slot_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_assignment_identity_window "
        "ON asset_account_assignments(account_group_id, source_family_id, perceptual_cluster_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_distribution_identity_window "
        "ON distribution_plans(account_group_id, source_family_id, perceptual_cluster_id, planned_window_start)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_proof_runs_campaign_asset ON proof_runs(campaign_id, rendered_asset_id, started_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_proof_runs_distribution_plan ON proof_runs(distribution_plan_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_quarantined_assets_campaign ON quarantined_assets(campaign_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_rejection_evidence_asset ON asset_rejection_evidence(rendered_asset_id, failed_stage, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_rejection_evidence_category ON asset_rejection_evidence(failed_stage, failure_category, created_at)"
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_inventory_reservations_active_asset
        ON asset_inventory_reservations(asset_id)
        WHERE status IN ('pending', 'committed')
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_inventory_reservations_idempotency
        ON asset_inventory_reservations(idempotency_key)
        WHERE idempotency_key IS NOT NULL AND idempotency_key != ''
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_asset_inventory_reservations_uniqueness
        ON asset_inventory_reservations(campaign_id, surface, source_family_id, perceptual_cluster_id, status, reserved_at)
        """
    )
    # Dedupe legacy rows before enforcing uniqueness (keep earliest insert).
    conn.execute(
        """
        DELETE FROM asset_account_assignments WHERE rowid NOT IN (
          SELECT MIN(rowid) FROM asset_account_assignments
          GROUP BY rendered_asset_id, COALESCE(account_id, ''),
                   COALESCE(instagram_account_id, ''), COALESCE(planned_window_start, '')
        )
        """
    )
    conn.execute(
        """
        DELETE FROM distribution_plans WHERE rowid NOT IN (
          SELECT MIN(rowid) FROM distribution_plans
          GROUP BY rendered_asset_id, surface, COALESCE(account_id, ''),
                   COALESCE(instagram_account_id, ''), COALESCE(planned_window_start, '')
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_account_assignments_uniqueness
        ON asset_account_assignments(
          rendered_asset_id, COALESCE(account_id, ''),
          COALESCE(instagram_account_id, ''), COALESCE(planned_window_start, '')
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_distribution_plans_uniqueness
        ON distribution_plans(
          rendered_asset_id, surface, COALESCE(account_id, ''),
          COALESCE(instagram_account_id, ''), COALESCE(planned_window_start, '')
        )
        """
    )
    _repair_source_asset_fk_references(conn)
    _repair_fk_references(conn, "rendered_assets_old_global_hash", "rendered_assets")
    conn.commit()
