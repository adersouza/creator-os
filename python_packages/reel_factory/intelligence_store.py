"""Shared intelligence-layer schema and helpers for Reel Factory."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

REVIEW_LABELS = {
    "eyes_bad",
    "face_drift",
    "hands_bad",
    "pose_drift",
    "weak_body",
    "weak_cleavage",
    "bad_crop",
    "background_changed",
    "motion_bad",
    "caption_bad",
    "grid_bad",
    "kling_zoomed_panel",
    "identity_good",
    "pose_good",
    "caption_good",
    "hook_good",
    "auto_review_pass",
    "low_resolution_crop",
    "manual_higgsfield_grid",
    "more_reference_fidelity",
    "native_grid_fallback",
}

POSITIVE_REASONS = {
    "identity_good",
    "pose_good",
    "caption_good",
    "hook_good",
    "auto_review_pass",
}
DECISIONS = {"approve", "reject", "maybe", "unreviewed"}
LOW_DATA_OUTCOME_THRESHOLD = 50


def db_path(root: Path) -> Path:
    return Path(root).resolve() / "manifest.sqlite"


def connect(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(root), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_intelligence_schema(conn)
    return conn


def ensure_intelligence_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS reel_outcomes (
        outcome_id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        output_path TEXT,
        job_key TEXT,
        campaign_output_id TEXT,
        campaign_id TEXT,
        asset_generation_id TEXT,
        prompt_run_id TEXT,
        source_reference_id TEXT,
        platform TEXT,
        account TEXT,
        posted_at TEXT,
        views INTEGER,
        likes INTEGER,
        comments INTEGER,
        shares INTEGER,
        saves INTEGER,
        watch_time REAL,
        retention_rate REAL,
        profile_visits INTEGER,
        follows INTEGER,
        manual_score REAL,
        source_url TEXT,
        notes TEXT,
        imported_at INTEGER NOT NULL,
        UNIQUE(filename, platform, account, posted_at)
    );
    CREATE INDEX IF NOT EXISTS idx_reel_outcomes_filename ON reel_outcomes(filename);
    CREATE INDEX IF NOT EXISTS idx_reel_outcomes_asset ON reel_outcomes(asset_generation_id);

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
        body_style TEXT,
        features_json TEXT NOT NULL DEFAULT '{}',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS experiments (
        experiment_id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        hypothesis TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS experiment_assignments (
        assignment_id TEXT PRIMARY KEY,
        experiment_id TEXT NOT NULL,
        group_name TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT,
        output_path TEXT,
        asset_generation_id TEXT,
        notes TEXT,
        created_at INTEGER NOT NULL,
        FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
    );
    CREATE INDEX IF NOT EXISTS idx_experiment_assignments_experiment ON experiment_assignments(experiment_id);

    CREATE TABLE IF NOT EXISTS cost_events (
        cost_id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        entity_id TEXT,
        output_path TEXT,
        asset_generation_id TEXT,
        soul_jobs INTEGER NOT NULL DEFAULT 0,
        kling_jobs INTEGER NOT NULL DEFAULT 0,
        estimated_generation_cost REAL,
        render_time_sec REAL,
        operator_seconds REAL,
        notes TEXT,
        created_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS winner_dna (
        dna_id TEXT PRIMARY KEY,
        feature_key TEXT NOT NULL,
        feature_value TEXT NOT NULL,
        sample_size INTEGER NOT NULL,
        avg_winner_score REAL NOT NULL,
        top_output_path TEXT,
        updated_at INTEGER NOT NULL,
        UNIQUE(feature_key, feature_value)
    );

    CREATE TABLE IF NOT EXISTS recommendation_decisions (
        decision_id TEXT PRIMARY KEY,
        campaign TEXT NOT NULL,
        recommendation_pattern TEXT,
        prompt_focus TEXT,
        avoid_labels_json TEXT NOT NULL DEFAULT '[]',
        confidence TEXT,
        confidence_reason TEXT,
        winner_dna_json TEXT NOT NULL DEFAULT '[]',
        rejection_patterns_json TEXT NOT NULL DEFAULT '[]',
        data_quality_json TEXT NOT NULL DEFAULT '{}',
        plan_json TEXT NOT NULL DEFAULT '{}',
        created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_recommendation_decisions_campaign
        ON recommendation_decisions(campaign, created_at);
    """)
    _ensure_columns(
        conn,
        "operator_ratings",
        {
            "decision": "TEXT NOT NULL DEFAULT 'unreviewed'",
            "primary_reason": "TEXT",
            "secondary_reasons_json": "TEXT NOT NULL DEFAULT '[]'",
            "face_score": "INTEGER",
            "eyes_score": "INTEGER",
            "hands_score": "INTEGER",
            "pose_accuracy_score": "INTEGER",
            "body_taste_score": "INTEGER",
            "background_score": "INTEGER",
            "crop_score": "INTEGER",
        },
    )
    _ensure_columns(
        conn,
        "asset_generations",
        {
            "soul_jobs": "INTEGER NOT NULL DEFAULT 0",
            "kling_jobs": "INTEGER NOT NULL DEFAULT 0",
            "estimated_generation_cost": "REAL",
            "operator_seconds": "REAL",
        },
    )
    _ensure_columns(
        conn,
        "variations",
        {
            "render_time_sec": "REAL",
        },
    )
    _ensure_columns(
        conn,
        "reel_outcomes",
        {
            "campaign_id": "TEXT",
            "prompt_run_id": "TEXT",
            "source_reference_id": "TEXT",
        },
    )
    conn.commit()


def _ensure_columns(
    conn: sqlite3.Connection, table: str, columns: dict[str, str]
) -> None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if not exists:
        return
    existing = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def validate_review(
    decision: str | None,
    primary_reason: str | None,
    secondary_reasons: list[str] | None = None,
) -> tuple[str, str | None, list[str]]:
    decision = decision or "unreviewed"
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
    secondary_reasons = secondary_reasons or []
    reasons = [r for r in [primary_reason, *secondary_reasons] if r]
    unknown = sorted(set(reasons) - REVIEW_LABELS)
    if unknown:
        raise ValueError(f"unknown review label(s): {unknown}")
    if decision in {"reject", "maybe"} and not primary_reason:
        raise ValueError("primary_reason is required for reject/maybe")
    if decision == "approve" and primary_reason and primary_reason not in REVIEW_LABELS:
        raise ValueError("primary_reason must be a known review label")
    return decision, primary_reason, secondary_reasons


def winner_score(row: sqlite3.Row | dict[str, Any]) -> float:
    get = (
        row.get
        if isinstance(row, dict)
        else lambda k, default=None: row[k] if k in row.keys() else default
    )
    if get("manual_score") is not None:
        return float(get("manual_score") or 0)
    views = float(get("views") or 0)
    likes = float(get("likes") or 0)
    comments = float(get("comments") or 0)
    shares = float(get("shares") or 0)
    saves = float(get("saves") or 0)
    return views + likes * 3 + comments * 8 + shares * 15 + saves * 12


def confidence_for_sample_size(
    sample_size: int, *, total_outcomes: int | None = None
) -> dict[str, Any]:
    sample_size = int(sample_size or 0)
    total_outcomes = sample_size if total_outcomes is None else int(total_outcomes or 0)
    if total_outcomes < LOW_DATA_OUTCOME_THRESHOLD or sample_size < 10:
        level = "low"
    elif sample_size < 25:
        level = "medium"
    else:
        level = "high"
    reason = (
        f"based on {sample_size} matching outcome row{'s' if sample_size != 1 else ''}"
    )
    if total_outcomes < LOW_DATA_OUTCOME_THRESHOLD:
        reason += f"; Winner DNA has only {total_outcomes} total outcome rows"
    return {
        "level": level,
        "sample_size": sample_size,
        "total_outcomes": total_outcomes,
        "reason": reason,
    }


def low_data_warning(total_outcomes: int) -> str | None:
    total_outcomes = int(total_outcomes or 0)
    if total_outcomes >= LOW_DATA_OUTCOME_THRESHOLD:
        return None
    return (
        f"Winner DNA is based on fewer than {LOW_DATA_OUTCOME_THRESHOLD} outcome rows "
        f"({total_outcomes} available). Treat recommendations as directional."
    )


def data_quality_score(
    *,
    total_outcomes: int,
    matched_sample_size: int = 0,
    outcomes_with_metrics: int = 0,
    reviewed_outputs: int = 0,
    reviewed_with_reasons: int = 0,
    distinct_review_labels: int = 0,
    experiment_group_counts: list[int] | None = None,
) -> dict[str, Any]:
    total_outcomes = int(total_outcomes or 0)
    matched_sample_size = int(matched_sample_size or 0)
    outcomes_with_metrics = int(outcomes_with_metrics or 0)
    reviewed_outputs = int(reviewed_outputs or 0)
    reviewed_with_reasons = int(reviewed_with_reasons or 0)
    distinct_review_labels = int(distinct_review_labels or 0)
    experiment_group_counts = [int(v or 0) for v in (experiment_group_counts or [])]

    score = 100
    reasons: list[str] = []

    if total_outcomes < LOW_DATA_OUTCOME_THRESHOLD:
        score -= 30
        reasons.append(f"fewer than {LOW_DATA_OUTCOME_THRESHOLD} outcome rows")
    if matched_sample_size < 10:
        score -= 20
        reasons.append("matched Winner DNA sample is below 10")
    elif matched_sample_size < 25:
        score -= 10
        reasons.append("matched Winner DNA sample is below 25")

    metric_ratio = (outcomes_with_metrics / total_outcomes) if total_outcomes else 0.0
    if metric_ratio < 0.8:
        score -= 15
        reasons.append("some outcome rows are missing engagement/manual score fields")

    if reviewed_outputs == 0:
        score -= 15
        reasons.append("no structured reviews recorded")
    else:
        reason_ratio = reviewed_with_reasons / reviewed_outputs
        if reason_ratio < 0.8:
            score -= 15
            reasons.append("review decisions are missing structured reasons")
        if distinct_review_labels < 2 and reviewed_outputs >= 5:
            score -= 10
            reasons.append("review labels lack variety")

    nonzero_groups = [v for v in experiment_group_counts if v > 0]
    if experiment_group_counts and len(nonzero_groups) >= 2:
        balance = min(nonzero_groups) / max(nonzero_groups)
        if balance < 0.5:
            score -= 10
            reasons.append("experiment groups are imbalanced")
    elif experiment_group_counts:
        score -= 10
        reasons.append("comparison is missing an experiment group")

    score = max(0, min(100, score))
    if score < 40:
        level = "weak"
    elif score < 65:
        level = "directional"
    elif score < 85:
        level = "usable"
    else:
        level = "strong"
    if not reasons:
        reasons.append("data coverage is strong")
    return {
        "score": score,
        "level": level,
        "reasons": reasons,
        "inputs": {
            "total_outcomes": total_outcomes,
            "matched_sample_size": matched_sample_size,
            "outcomes_with_metrics": outcomes_with_metrics,
            "reviewed_outputs": reviewed_outputs,
            "reviewed_with_reasons": reviewed_with_reasons,
            "distinct_review_labels": distinct_review_labels,
            "experiment_group_counts": experiment_group_counts,
        },
    }


def data_quality_from_connection(
    conn: sqlite3.Connection,
    *,
    matched_sample_size: int = 0,
    experiment_group_counts: list[int] | None = None,
) -> dict[str, Any]:
    outcome_row = conn.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE
            WHEN manual_score IS NOT NULL
              OR COALESCE(views, 0) > 0
              OR COALESCE(likes, 0) > 0
              OR COALESCE(comments, 0) > 0
              OR COALESCE(shares, 0) > 0
              OR COALESCE(saves, 0) > 0
            THEN 1 ELSE 0 END) AS with_metrics
        FROM reel_outcomes
        """
    ).fetchone()
    review_row = conn.execute(
        """
        SELECT
          COUNT(*) AS reviewed,
          SUM(CASE WHEN decision IN ('approve','reject','maybe') AND primary_reason IS NOT NULL THEN 1 ELSE 0 END) AS with_reasons,
          COUNT(DISTINCT primary_reason) AS distinct_labels
        FROM operator_ratings
        WHERE decision IN ('approve','reject','maybe')
        """
    ).fetchone()
    outcome_total = outcome_row["total"] if outcome_row else 0
    outcome_with_metrics = outcome_row["with_metrics"] if outcome_row else 0
    reviewed = review_row["reviewed"] if review_row else 0
    with_reasons = review_row["with_reasons"] if review_row else 0
    distinct_labels = review_row["distinct_labels"] if review_row else 0
    return data_quality_score(
        total_outcomes=int(outcome_total or 0),
        matched_sample_size=matched_sample_size,
        outcomes_with_metrics=int(outcome_with_metrics or 0),
        reviewed_outputs=int(reviewed or 0),
        reviewed_with_reasons=int(with_reasons or 0),
        distinct_review_labels=int(distinct_labels or 0),
        experiment_group_counts=experiment_group_counts,
    )


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def now_ms_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}"
