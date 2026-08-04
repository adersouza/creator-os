from __future__ import annotations

import hashlib
import inspect
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from creator_os_core.sqlite import connect_sqlite
from creator_os_core.sqlite import ensure_columns as _ensure_columns

from .campaign_schema_v5 import (
    apply as _apply_campaign_schema_v5,
)
from .campaign_schema_v5 import (
    checksum as _campaign_schema_v5_checksum,
)
from .campaign_schema_v5 import (
    postcondition as _campaign_schema_v5_postcondition,
)
from .campaign_schema_v6 import (
    apply as _apply_campaign_schema_v6,
)
from .campaign_schema_v6 import (
    checksum as _campaign_schema_v6_checksum,
)
from .campaign_schema_v6 import (
    postcondition as _campaign_schema_v6_postcondition,
)
from .campaign_schema_v7 import (
    apply as _apply_campaign_schema_v7,
)
from .campaign_schema_v7 import (
    checksum as _campaign_schema_v7_checksum,
)
from .campaign_schema_v7 import (
    postcondition as _campaign_schema_v7_postcondition,
)
from .campaign_schema_v8 import (
    apply as _apply_campaign_schema_v8,
)
from .campaign_schema_v8 import (
    checksum as _campaign_schema_v8_checksum,
)
from .campaign_schema_v8 import (
    postcondition as _campaign_schema_v8_postcondition,
)
from .campaign_schema_v9 import (
    apply as _apply_campaign_schema_v9,
)
from .campaign_schema_v9 import (
    checksum as _campaign_schema_v9_checksum,
)
from .campaign_schema_v9 import (
    postcondition as _campaign_schema_v9_postcondition,
)
from .creator_governance_schema import CREATOR_GOVERNANCE_SCHEMA
from .db_migrations import (
    _apply_creator_governance_backfill,
    _backfill_generation_output_lineage,
    _ensure_generation_lineage_guards,
    _migrate_rendered_assets_hash_scope,
    _migrate_source_assets_hash_scope,
    _repair_fk_references,
    _repair_source_asset_fk_references,
)
from .db_schema import SCHEMA
from .orchestration_schema import DAILY_ORCHESTRATION_SCHEMA
from .source_lifecycle_schema import SOURCE_LIFECYCLE_SCHEMA

_CAMPAIGN_SCHEMA_VERSION = 9
_CAMPAIGN_SCHEMA_MIGRATIONS = (
    (1, "20260730_campaign_schema_baseline_v1"),
    (2, "20260730_campaign_state_evidence_guards_v1"),
    (3, "20260730_source_lifecycle_reconciliation_v1"),
    (4, "20260730_daily_orchestration_authority_v1"),
    (5, "20260730_orchestration_cost_guards_v2"),
    (6, "20260730_incident_privacy_observability_v1"),
    (7, "20260730_learning_governance_registry_v1"),
    (8, "20260801_learning_cohort_schema_v1"),
    (9, "20260803_provider_native_identity_v1"),
)


def connect(db_path: Path) -> sqlite3.Connection:
    # Shared opener applies timeout + busy_timeout (overlapping cron writers
    # wait instead of failing with "database is locked") and WAL (readers
    # proceed during writes). foreign_keys stays campaign-specific.
    conn = connect_sqlite(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _apply_campaign_schema_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _apply_creator_governance_backfill(conn)
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
            "subject_sha256": "TEXT",
            "layers_json": "TEXT NOT NULL DEFAULT '{}'",
            "verdicts_json": "TEXT NOT NULL DEFAULT '{}'",
            "overall_verdict": "TEXT",
            "files_analyzed": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    _ensure_columns(
        conn,
        "motion_qc_receipts",
        {
            "analysis_fingerprint": "TEXT",
            "analyzer_registry_id": "TEXT",
            "analyzer_registry_fingerprint": "TEXT",
            "human_review_fingerprint": "TEXT",
            "source_sha256": "TEXT",
        },
    )
    _ensure_columns(conn, "approval_decisions", {"subject_sha256": "TEXT"})
    _ensure_columns(
        conn,
        "threadsdash_exports",
        {
            "idempotency_key": "TEXT",
            "request_fingerprint": "TEXT",
            "contract_schema": "TEXT",
            "contract_version": "TEXT",
            "contract_fingerprint": "TEXT",
            "rendered_asset_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "source_asset_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "final_sha256s_json": "TEXT NOT NULL DEFAULT '[]'",
            "destination_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "reservation_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "submitted_at": "TEXT",
            "acknowledged_at": "TEXT",
            "rejected_at": "TEXT",
            "superseded_at": "TEXT",
            "acknowledgment_json": "TEXT",
            "last_error": "TEXT",
            "source_system": "TEXT NOT NULL DEFAULT 'creator_os'",
            "owning_system": "TEXT NOT NULL DEFAULT 'threadsdashboard'",
            "updated_at": "TEXT",
        },
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_threadsdash_exports_idempotency "
        "ON threadsdash_exports(idempotency_key) WHERE idempotency_key IS NOT NULL"
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
        "existing_media_asset_reviews",
        {
            "source_sha256": "TEXT",
            "prompt_card_fingerprint": "TEXT",
            "compiled_prompt_fingerprint": "TEXT",
            "provider": "TEXT",
            "model_tool": "TEXT",
            "recipe_id": "TEXT",
            "generation_id": "TEXT",
            "seed": "INTEGER",
            "content_intent": "TEXT",
            "source_class": "TEXT",
            "rejection_reasons_json": "TEXT NOT NULL DEFAULT '[]'",
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
            "source_metric_history_id": "TEXT",
            "source_platform_post_id": "TEXT",
            "source_observation_fingerprint": "TEXT",
            "metric_window": "TEXT",
            "imported_at": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "pipeline_jobs",
        {
            "effect_state": "TEXT NOT NULL DEFAULT 'PRE_EFFECT'",
            "recovery_policy": "TEXT NOT NULL DEFAULT 'NEVER_AUTOMATIC'",
            "work_item_id": "TEXT",
            "authorization_id": "TEXT",
            "attempt_id": "TEXT",
            "external_operation_id": "TEXT",
            "reconciliation_classification": "TEXT",
            "reconciliation_json": "TEXT NOT NULL DEFAULT '{}'",
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
            "canonical_track_id": "TEXT",
            "canonical_title": "TEXT",
            "canonical_artists_json": "TEXT NOT NULL DEFAULT '[]'",
            "variant": "TEXT",
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
            "lifecycle_state": "TEXT NOT NULL DEFAULT 'EVERGREEN'",
            "pinned": "INTEGER NOT NULL DEFAULT 0",
            "active": "INTEGER NOT NULL DEFAULT 0",
            "last_seen_refresh_id": "TEXT",
            "consecutive_absences": "INTEGER NOT NULL DEFAULT 0",
            "last_seen_at": "TEXT",
            "activated_at": "TEXT",
            "refresh_metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    _ensure_columns(
        conn,
        "audio_cache_objects",
        {
            "encoded_audio_sha256": "TEXT",
            "canonical_pcm_sha256": "TEXT",
            "chromaprint": "TEXT",
            "chromaprint_version": "TEXT",
            "chromaprint_duration_seconds": "REAL",
            "container": "TEXT",
            "channel_layout": "TEXT",
            "loudness_json": "TEXT NOT NULL DEFAULT '{}'",
            "extraction_receipt_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_audio_catalog_canonical
        ON audio_catalog(canonical_track_id)
        WHERE canonical_track_id IS NOT NULL
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_audio_catalog_lifecycle
        ON audio_catalog(active, lifecycle_state, last_seen_at)
        """
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
    _reject_ambiguous_legacy_duplicates(conn)
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
    # Legacy table rebuilds drop triggers attached to the replaced tables.
    conn.executescript(CREATOR_GOVERNANCE_SCHEMA)
    _ensure_generation_lineage_guards(conn)
    _backfill_generation_output_lineage(conn)
    conn.commit()


def _reject_ambiguous_legacy_duplicates(conn: sqlite3.Connection) -> None:
    duplicate_specs = (
        (
            "asset_account_assignments",
            """
            SELECT rendered_asset_id, COALESCE(account_id, '') AS account_id,
                   COALESCE(instagram_account_id, '') AS instagram_account_id,
                   COALESCE(planned_window_start, '') AS planned_window_start,
                   COUNT(*) AS row_count
            FROM asset_account_assignments
            GROUP BY rendered_asset_id, COALESCE(account_id, ''),
                     COALESCE(instagram_account_id, ''),
                     COALESCE(planned_window_start, '')
            HAVING COUNT(*) > 1
            ORDER BY rendered_asset_id, account_id, instagram_account_id,
                     planned_window_start
            LIMIT 20
            """,
        ),
        (
            "distribution_plans",
            """
            SELECT rendered_asset_id, surface,
                   COALESCE(account_id, '') AS account_id,
                   COALESCE(instagram_account_id, '') AS instagram_account_id,
                   COALESCE(planned_window_start, '') AS planned_window_start,
                   COUNT(*) AS row_count
            FROM distribution_plans
            GROUP BY rendered_asset_id, surface, COALESCE(account_id, ''),
                     COALESCE(instagram_account_id, ''),
                     COALESCE(planned_window_start, '')
            HAVING COUNT(*) > 1
            ORDER BY rendered_asset_id, surface, account_id, instagram_account_id,
                     planned_window_start
            LIMIT 20
            """,
        ),
    )
    for table, query in duplicate_specs:
        rows = [dict(row) for row in conn.execute(query).fetchall()]
        if rows:
            raise RuntimeError(
                f"campaign_schema_duplicate_repair_required:{table}:"
                f"{json.dumps(rows, sort_keys=True, separators=(',', ':'))}"
            )


def _execute_transactional_script(conn: sqlite3.Connection, script: str) -> None:
    """Execute complete SQLite statements without ``executescript`` auto-commits."""
    statement = ""
    for line in script.splitlines():
        statement += f"{line}\n"
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise RuntimeError("campaign_schema_sql_incomplete")


def _apply_campaign_schema_v2(conn: sqlite3.Connection) -> None:
    _execute_transactional_script(
        conn,
        """
        CREATE TRIGGER IF NOT EXISTS approval_decisions_valid_insert
        BEFORE INSERT ON approval_decisions
        WHEN NEW.decision NOT IN ('approved', 'rejected')
        BEGIN
          SELECT RAISE(ABORT, 'invalid approval decision');
        END;
        CREATE TRIGGER IF NOT EXISTS approval_decisions_immutable_update
        BEFORE UPDATE ON approval_decisions
        BEGIN
          SELECT RAISE(ABORT, 'approval decisions are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS approval_decisions_immutable_delete
        BEFORE DELETE ON approval_decisions
        BEGIN
          SELECT RAISE(ABORT, 'approval decisions are append-only');
        END;

        CREATE TRIGGER IF NOT EXISTS audit_reports_immutable_update
        BEFORE UPDATE ON audit_reports
        BEGIN
          SELECT RAISE(ABORT, 'audit reports are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS audit_reports_immutable_delete
        BEFORE DELETE ON audit_reports
        BEGIN
          SELECT RAISE(ABORT, 'audit reports are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS activity_events_immutable_update
        BEFORE UPDATE ON activity_events
        BEGIN
          SELECT RAISE(ABORT, 'activity events are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS activity_events_immutable_delete
        BEFORE DELETE ON activity_events
        BEGIN
          SELECT RAISE(ABORT, 'activity events are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS promotion_events_immutable_update
        BEFORE UPDATE ON promotion_events
        BEGIN
          SELECT RAISE(ABORT, 'promotion events are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS promotion_events_immutable_delete
        BEFORE DELETE ON promotion_events
        BEGIN
          SELECT RAISE(ABORT, 'promotion events are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS campaign_schema_migrations_applied_immutable_update
        BEFORE UPDATE ON campaign_schema_migrations
        WHEN OLD.status = 'applied'
        BEGIN
          SELECT RAISE(ABORT, 'applied campaign migrations are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS campaign_schema_migrations_applied_immutable_delete
        BEFORE DELETE ON campaign_schema_migrations
        WHEN OLD.status = 'applied'
        BEGIN
          SELECT RAISE(ABORT, 'applied campaign migrations are immutable');
        END;

        CREATE TRIGGER IF NOT EXISTS pipeline_jobs_valid_insert
        BEFORE INSERT ON pipeline_jobs
        WHEN NEW.status NOT IN ('queued', 'running', 'succeeded', 'failed')
          OR NEW.effect_state NOT IN (
            'PRE_EFFECT', 'AUTHORIZATION_CONSUMED', 'SUBMISSION_STARTED',
            'EXTERNAL_ID_KNOWN', 'AMBIGUOUS', 'PROVIDER_FAILED',
            'PROVIDER_COMPLETED', 'OUTPUT_DOWNLOADED', 'OUTPUT_RETAINED',
            'COST_RECONCILED', 'NO_EFFECT_CONFIRMED', 'EFFECT_CONFIRMED',
            'FINALIZED'
          )
          OR NEW.recovery_policy NOT IN (
            'LOCAL', 'IDEMPOTENT_EXTERNAL', 'NEVER_AUTOMATIC'
          )
        BEGIN
          SELECT RAISE(ABORT, 'invalid pipeline job state');
        END;
        CREATE TRIGGER IF NOT EXISTS pipeline_jobs_effect_transition_guard
        BEFORE UPDATE OF effect_state ON pipeline_jobs
        WHEN OLD.effect_state != NEW.effect_state
         AND NOT (
           (OLD.effect_state = 'PRE_EFFECT' AND NEW.effect_state IN (
             'AUTHORIZATION_CONSUMED', 'SUBMISSION_STARTED',
             'NO_EFFECT_CONFIRMED', 'EXTERNAL_ID_KNOWN', 'FINALIZED'))
           OR (OLD.effect_state = 'AUTHORIZATION_CONSUMED'
               AND NEW.effect_state IN (
                 'SUBMISSION_STARTED', 'EXTERNAL_ID_KNOWN',
                 'NO_EFFECT_CONFIRMED', 'FINALIZED'))
           OR (OLD.effect_state = 'SUBMISSION_STARTED' AND NEW.effect_state IN (
                 'EXTERNAL_ID_KNOWN', 'AMBIGUOUS', 'PROVIDER_FAILED',
                 'NO_EFFECT_CONFIRMED', 'EFFECT_CONFIRMED', 'FINALIZED'))
           OR (OLD.effect_state = 'EXTERNAL_ID_KNOWN' AND NEW.effect_state IN (
                 'AMBIGUOUS', 'PROVIDER_FAILED', 'PROVIDER_COMPLETED',
                 'EFFECT_CONFIRMED', 'FINALIZED'))
           OR (OLD.effect_state = 'PROVIDER_FAILED'
               AND NEW.effect_state = 'FINALIZED')
           OR (OLD.effect_state = 'PROVIDER_COMPLETED'
               AND NEW.effect_state IN (
                 'OUTPUT_DOWNLOADED', 'OUTPUT_RETAINED', 'AMBIGUOUS',
                 'FINALIZED'))
           OR (OLD.effect_state = 'OUTPUT_DOWNLOADED'
               AND NEW.effect_state IN (
                 'OUTPUT_RETAINED', 'AMBIGUOUS', 'FINALIZED'))
           OR (OLD.effect_state = 'OUTPUT_RETAINED'
               AND NEW.effect_state IN (
                 'COST_RECONCILED', 'AMBIGUOUS', 'FINALIZED'))
           OR (OLD.effect_state = 'COST_RECONCILED'
               AND NEW.effect_state = 'FINALIZED')
           OR (OLD.effect_state = 'AMBIGUOUS' AND NEW.effect_state IN (
                 'EXTERNAL_ID_KNOWN', 'NO_EFFECT_CONFIRMED',
                 'EFFECT_CONFIRMED'))
           OR (OLD.effect_state = 'NO_EFFECT_CONFIRMED'
               AND NEW.effect_state IN ('PRE_EFFECT', 'FINALIZED'))
           OR (OLD.effect_state = 'EFFECT_CONFIRMED'
               AND NEW.effect_state = 'FINALIZED')
         )
        BEGIN
          SELECT RAISE(ABORT, 'invalid pipeline effect transition');
        END;

        CREATE TRIGGER IF NOT EXISTS inventory_reservations_valid_insert
        BEFORE INSERT ON asset_inventory_reservations
        WHEN NEW.status NOT IN (
          'pending', 'committed', 'released', 'expired', 'cancelled', 'published'
        )
        BEGIN
          SELECT RAISE(ABORT, 'invalid inventory reservation status');
        END;
        CREATE TRIGGER IF NOT EXISTS inventory_reservations_transition_guard
        BEFORE UPDATE OF status ON asset_inventory_reservations
        WHEN OLD.status != NEW.status
         AND NOT (
           (OLD.status = 'pending' AND NEW.status IN (
             'committed', 'released', 'expired', 'cancelled'))
           OR (OLD.status = 'committed' AND NEW.status IN (
             'released', 'expired', 'cancelled', 'published'))
         )
        BEGIN
          SELECT RAISE(ABORT, 'invalid inventory reservation transition');
        END;
        """,
    )


def _apply_campaign_schema_v3(conn: sqlite3.Connection) -> None:
    _execute_transactional_script(conn, SOURCE_LIFECYCLE_SCHEMA)
    now = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    allowed = {
        "rejected",
        "superseded",
        "archived",
        "deleted",
        "quarantined",
    }
    for row in conn.execute(
        """
        SELECT s.id, s.status FROM source_assets s
        LEFT JOIN source_asset_lifecycle l ON l.source_asset_id = s.id
        WHERE l.source_asset_id IS NULL
        ORDER BY s.id
        """
    ).fetchall():
        source_id = str(row["id"])
        legacy_status = str(row["status"] or "").lower()
        lifecycle_state = (
            "quarantined"
            if legacy_status == "approved"
            else legacy_status
            if legacy_status in allowed
            else (
                "cataloged"
                if legacy_status in {"imported", "cataloged"}
                else "quarantined"
            )
        )
        quarantine_reason = (
            None
            if lifecycle_state != "quarantined"
            else (
                "legacy_approved_source_requires_managed_backup"
                if legacy_status == "approved"
                else "legacy_source_requires_probe_reconciliation"
            )
        )
        conn.execute(
            """
            INSERT INTO source_asset_lifecycle
            (source_asset_id, lifecycle_state, storage_policy,
             classification_authority, probe_json, quarantine_reason,
             backup_state, metadata_json, updated_at)
            VALUES (?, ?, 'external_reference', 'unknown', '{}', ?,
                    'unknown', ?, ?)
            """,
            (
                source_id,
                lifecycle_state,
                quarantine_reason,
                json.dumps(
                    {
                        "migrationId": "20260730_source_lifecycle_reconciliation_v1",
                        "legacyStatus": legacy_status,
                        "pathOwnershipFabricated": False,
                        "probeEvidenceFabricated": False,
                    },
                    sort_keys=True,
                ),
                now,
            ),
        )
        if legacy_status == "approved":
            conn.execute(
                """
                UPDATE source_assets
                SET status = 'quarantined', updated_at = ?
                WHERE id = ? AND status = 'approved'
                """,
                (now, source_id),
            )
        event_id = (
            "source_lifecycle_migration_"
            + hashlib.sha256(source_id.encode()).hexdigest()[:20]
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO source_asset_lifecycle_events
            (id, source_asset_id, previous_state, new_state, reason, actor,
             evidence_json, created_at)
            VALUES (?, ?, NULL, ?, 'legacy_source_lifecycle_backfill',
                    'schema_migration', ?, ?)
            """,
            (
                event_id,
                source_id,
                lifecycle_state,
                json.dumps(
                    {
                        "legacyStatus": legacy_status,
                        "classificationAuthority": "unknown",
                    },
                    sort_keys=True,
                ),
                now,
            ),
        )


def _apply_campaign_schema_v4(conn: sqlite3.Connection) -> None:
    _execute_transactional_script(conn, DAILY_ORCHESTRATION_SCHEMA)


def _campaign_schema_v1_postcondition(conn: sqlite3.Connection) -> None:
    required_tables = {
        "campaigns",
        "models",
        "source_assets",
        "rendered_assets",
        "pipeline_jobs",
        "approval_decisions",
        "audit_reports",
        "activity_events",
        "asset_inventory_reservations",
    }
    tables = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if missing := required_tables - tables:
        raise RuntimeError(
            "campaign_schema_tables_missing:" + ",".join(sorted(missing))
        )
    _reject_ambiguous_legacy_duplicates(conn)
    required_indexes = {
        "idx_asset_account_assignments_uniqueness",
        "idx_distribution_plans_uniqueness",
    }
    indexes = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    if missing := required_indexes - indexes:
        raise RuntimeError(
            "campaign_schema_indexes_missing:" + ",".join(sorted(missing))
        )


def _campaign_schema_v2_postcondition(conn: sqlite3.Connection) -> None:
    _require_campaign_schema_triggers(
        conn,
        {
            "approval_decisions_immutable_update",
            "audit_reports_immutable_update",
            "activity_events_immutable_update",
            "promotion_events_immutable_update",
            "campaign_schema_migrations_applied_immutable_update",
            "pipeline_jobs_effect_transition_guard",
            "inventory_reservations_transition_guard",
        },
    )


def _campaign_schema_v3_postcondition(conn: sqlite3.Connection) -> None:
    _require_campaign_schema_triggers(
        conn,
        {
            "source_asset_lifecycle_transition_guard",
            "source_asset_lifecycle_approval_backup_guard_insert",
            "source_asset_lifecycle_approval_backup_guard_update",
            "source_asset_lifecycle_terminal_guard",
            "source_asset_lifecycle_delete_guard",
            "source_asset_lifecycle_events_immutable_update",
            "source_asset_lifecycle_events_immutable_delete",
            "artifact_reconciliation_repairs_immutable_update",
            "artifact_reconciliation_repairs_immutable_delete",
        },
    )


def _campaign_schema_v4_postcondition(conn: sqlite3.Connection) -> None:
    required_tables = {
        "daily_orchestrator_runs",
        "daily_orchestrator_items",
        "operator_authority_events",
    }
    tables = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if missing := required_tables - tables:
        raise RuntimeError(
            "campaign_schema_tables_missing:" + ",".join(sorted(missing))
        )
    _require_campaign_schema_triggers(
        conn,
        {
            "daily_orchestrator_runs_no_delete",
            "daily_orchestrator_items_no_delete",
            "operator_authority_events_immutable_update",
            "operator_authority_events_immutable_delete",
        },
    )


def _require_campaign_schema_triggers(
    conn: sqlite3.Connection, required_triggers: set[str]
) -> None:
    triggers = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    if missing := required_triggers - triggers:
        raise RuntimeError(
            "campaign_schema_triggers_missing:" + ",".join(sorted(missing))
        )


def _campaign_schema_postcondition(conn: sqlite3.Connection, *, version: int) -> None:
    {
        1: _campaign_schema_v1_postcondition,
        2: _campaign_schema_v2_postcondition,
        3: _campaign_schema_v3_postcondition,
        4: _campaign_schema_v4_postcondition,
        5: _campaign_schema_v5_postcondition,
        6: _campaign_schema_v6_postcondition,
        7: _campaign_schema_v7_postcondition,
        8: _campaign_schema_v8_postcondition,
        9: _campaign_schema_v9_postcondition,
    }[version](conn)


def _campaign_schema_checksum(version: int, migration_id: str) -> str:
    if version == 5:
        return _campaign_schema_v5_checksum(migration_id)
    if version == 6:
        return _campaign_schema_v6_checksum(migration_id)
    if version == 7:
        return _campaign_schema_v7_checksum(migration_id)
    if version == 8:
        return _campaign_schema_v8_checksum(migration_id)
    if version == 9:
        return _campaign_schema_v9_checksum(migration_id)
    implementation = {
        1: _apply_campaign_schema_v1,
        2: _apply_campaign_schema_v2,
        3: _apply_campaign_schema_v3,
        4: _apply_campaign_schema_v4,
        5: _apply_campaign_schema_v5,
        6: _apply_campaign_schema_v6,
        7: _apply_campaign_schema_v7,
        8: _apply_campaign_schema_v8,
        9: _apply_campaign_schema_v9,
    }[version]
    postcondition = {
        1: _campaign_schema_v1_postcondition,
        2: _campaign_schema_v2_postcondition,
        3: _campaign_schema_v3_postcondition,
        4: _campaign_schema_v4_postcondition,
        5: _campaign_schema_v5_postcondition,
        6: _campaign_schema_v6_postcondition,
        7: _campaign_schema_v7_postcondition,
        8: _campaign_schema_v8_postcondition,
        9: _campaign_schema_v9_postcondition,
    }[version]
    payload = inspect.getsource(implementation)
    if version == 1:
        payload += "\n" + inspect.getsource(_reject_ambiguous_legacy_duplicates)
        payload += "\n" + SCHEMA
    elif version == 2:
        payload += "\n" + inspect.getsource(_execute_transactional_script)
    elif version == 3:
        payload += "\n" + inspect.getsource(_execute_transactional_script)
        payload += "\n" + SOURCE_LIFECYCLE_SCHEMA
    elif version == 4:
        payload += "\n" + inspect.getsource(_execute_transactional_script)
        payload += "\n" + DAILY_ORCHESTRATION_SCHEMA
    payload += "\n" + inspect.getsource(postcondition)
    if version in {2, 3, 4}:
        payload += "\n" + inspect.getsource(_require_campaign_schema_triggers)
    return hashlib.sha256(f"{migration_id}\n{payload}".encode()).hexdigest()


def _ensure_campaign_schema_ledger(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS campaign_schema_migrations (
          migration_id TEXT PRIMARY KEY,
          checksum TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('applying', 'applied', 'failed')),
          started_at TEXT NOT NULL,
          applied_at TEXT,
          source_version TEXT NOT NULL,
          details_json TEXT NOT NULL DEFAULT '{}',
          error TEXT,
          repair_instructions TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS campaign_schema_state (
          singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
          version INTEGER NOT NULL CHECK(version >= 0),
          updated_at TEXT NOT NULL
        );
        """
    )
    now = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    conn.execute(
        """
        INSERT INTO campaign_schema_state(singleton, version, updated_at)
        VALUES (1, 0, ?)
        ON CONFLICT(singleton) DO NOTHING
        """,
        (now,),
    )
    conn.commit()


def _run_campaign_schema_migration(
    conn: sqlite3.Connection, *, version: int, migration_id: str
) -> None:
    checksum = _campaign_schema_checksum(version, migration_id)
    prior = conn.execute(
        """
        SELECT checksum, status
        FROM campaign_schema_migrations
        WHERE migration_id = ?
        """,
        (migration_id,),
    ).fetchone()
    if prior is not None and prior["checksum"] != checksum:
        raise RuntimeError(f"campaign_schema_migration_checksum_drift:{migration_id}")
    current = int(
        conn.execute(
            "SELECT version FROM campaign_schema_state WHERE singleton = 1"
        ).fetchone()["version"]
    )
    if current >= version:
        if prior is None or prior["status"] != "applied":
            raise RuntimeError(
                f"campaign_schema_ledger_state_mismatch:{migration_id}:{current}"
            )
        _campaign_schema_postcondition(conn, version=version)
        return

    source_version = os.environ.get("CREATOR_OS_SOURCE_SHA") or f"migration:{checksum}"
    conn.execute(
        """
        INSERT INTO campaign_schema_migrations
        (migration_id, checksum, status, started_at, applied_at, source_version,
         details_json, error, repair_instructions)
        VALUES (?, ?, 'applying', ?, NULL, ?, ?, NULL, ?)
        ON CONFLICT(migration_id) DO UPDATE SET
          checksum = excluded.checksum,
          status = 'applying',
          started_at = excluded.started_at,
          applied_at = NULL,
          source_version = excluded.source_version,
          details_json = excluded.details_json,
          error = NULL,
          repair_instructions = excluded.repair_instructions
        """,
        (
            migration_id,
            checksum,
            datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            source_version,
            json.dumps(
                {
                    "schemaVersion": version,
                    "transactionMode": (
                        "legacy_replay_safe_staged"
                        if version == 1
                        else "atomic_immediate"
                    ),
                },
                sort_keys=True,
            ),
            "restore a backup, repair the reported condition, then reconnect",
        ),
    )
    conn.commit()
    try:
        if version > 1:
            conn.execute("BEGIN IMMEDIATE")
        implementation = {
            1: _apply_campaign_schema_v1,
            2: _apply_campaign_schema_v2,
            3: _apply_campaign_schema_v3,
            4: _apply_campaign_schema_v4,
            5: _apply_campaign_schema_v5,
            6: _apply_campaign_schema_v6,
            7: _apply_campaign_schema_v7,
            8: _apply_campaign_schema_v8,
            9: _apply_campaign_schema_v9,
        }[version]
        implementation(conn)
        _campaign_schema_postcondition(conn, version=version)
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                "campaign_schema_foreign_key_check_failed:"
                + json.dumps([list(row) for row in violations], separators=(",", ":"))
            )
        applied_at = (
            datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        )
        cursor = conn.execute(
            """
            UPDATE campaign_schema_state
            SET version = ?, updated_at = ?
            WHERE singleton = 1 AND version = ?
            """,
            (version, applied_at, version - 1),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(
                f"campaign_schema_version_advance_failed:{version - 1}:{version}"
            )
        conn.execute(
            """
            UPDATE campaign_schema_migrations
            SET status = 'applied', applied_at = ?, error = NULL
            WHERE migration_id = ?
            """,
            (applied_at, migration_id),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        conn.execute(
            """
            UPDATE campaign_schema_migrations
            SET status = 'failed', error = ?
            WHERE migration_id = ?
            """,
            (f"{type(exc).__name__}:{exc}", migration_id),
        )
        conn.commit()
        raise


def init_db(conn: sqlite3.Connection) -> None:
    _ensure_campaign_schema_ledger(conn)
    current = int(
        conn.execute(
            "SELECT version FROM campaign_schema_state WHERE singleton = 1"
        ).fetchone()["version"]
    )
    if current > _CAMPAIGN_SCHEMA_VERSION:
        raise RuntimeError(
            f"campaign_schema_newer_than_runtime:{current}>{_CAMPAIGN_SCHEMA_VERSION}"
        )
    for version, migration_id in _CAMPAIGN_SCHEMA_MIGRATIONS:
        _run_campaign_schema_migration(conn, version=version, migration_id=migration_id)
