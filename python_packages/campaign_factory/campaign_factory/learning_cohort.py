from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import statistics
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from creator_os_core.fileops import atomic_write_text

from .learning_score import learning_eligible, learning_loop_cutover, snapshot_reward
from .lineage_v2 import lineage_v2_is_learning_traceable

COHORT_ID = "stacey_learning_cohort_v1"
CREATOR = "Stacey"
SOUL_ID = "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"
ACCOUNT_HANDLE = "staceyben101"
TIMEZONE = "America/New_York"
TOTAL_DAYS = 25
METRIC_WINDOWS = {
    "metric_1h_state": (1.0, 0.75, 3.0),
    "metric_24h_state": (24.0, 20.0, 28.0),
    "metric_72h_state": (72.0, 68.0, 76.0),
}


def ensure_learning_cohort_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS learning_cohorts (
          id TEXT PRIMARY KEY,
          campaign_slug TEXT NOT NULL,
          creator TEXT NOT NULL,
          soul_id TEXT NOT NULL,
          account_handle TEXT NOT NULL,
          timezone TEXT NOT NULL,
          start_date TEXT NOT NULL,
          seed TEXT NOT NULL,
          status TEXT NOT NULL,
          autoposter_enabled INTEGER NOT NULL DEFAULT 0,
          automatic_trial_graduation INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS learning_cohort_assignments (
          id TEXT PRIMARY KEY,
          cohort_id TEXT NOT NULL,
          day_index INTEGER NOT NULL,
          arm TEXT NOT NULL CHECK (arm IN ('ranked', 'control')),
          surface TEXT NOT NULL CHECK (surface IN ('regular_reel', 'trial_reel')),
          scheduled_for TEXT NOT NULL,
          assignment_seed TEXT NOT NULL,
          reference_id TEXT,
          candidate_rank INTEGER,
          source_family TEXT,
          perceptual_cluster TEXT,
          content_fingerprint TEXT,
          provider_reservation_id TEXT,
          draft_id TEXT,
          post_id TEXT,
          generation_state TEXT NOT NULL DEFAULT 'planned',
          approval_state TEXT NOT NULL DEFAULT 'pending',
          schedule_state TEXT NOT NULL DEFAULT 'blocked_pending_approval',
          publish_state TEXT NOT NULL DEFAULT 'not_published',
          metric_1h_state TEXT NOT NULL DEFAULT 'pending',
          metric_24h_state TEXT NOT NULL DEFAULT 'pending',
          metric_72h_state TEXT NOT NULL DEFAULT 'not_required',
          reward_24h REAL,
          retry_count INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(cohort_id, day_index, surface),
          UNIQUE(cohort_id, content_fingerprint),
          FOREIGN KEY(cohort_id) REFERENCES learning_cohorts(id)
        );
        CREATE INDEX IF NOT EXISTS idx_learning_cohort_assignment_state
          ON learning_cohort_assignments(cohort_id, day_index, generation_state);
        """
    )
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(learning_cohort_assignments)")
    }
    added_column = False
    for name, definition in {
        "rendered_asset_id": "TEXT",
        "artifact_path": "TEXT",
        "lineage_path": "TEXT",
        "published_at": "TEXT",
    }.items():
        if name not in columns:
            conn.execute(
                f"ALTER TABLE learning_cohort_assignments ADD COLUMN {name} {definition}"
            )
            added_column = True
    if added_column:
        conn.commit()


def prepare_learning_cohort(
    conn: sqlite3.Connection, *, start_date: str, seed: str = COHORT_ID
) -> dict[str, Any]:
    ensure_learning_cohort_tables(conn)
    parsed_start = date.fromisoformat(start_date)
    existing = conn.execute(
        "SELECT * FROM learning_cohorts WHERE id = ?", (COHORT_ID,)
    ).fetchone()
    if existing:
        assignments = _assignment_rows(conn)
        return _prepare_report(assignments, idempotent=True)

    now = _utc_now()
    conn.execute(
        """INSERT OR IGNORE INTO campaigns
        (id, slug, name, platform, root_path, created_at, updated_at)
        VALUES (?, ?, ?, 'instagram', ?, ?, ?)""",
        (
            f"campaign_{_digest(COHORT_ID)[:12]}",
            COHORT_ID,
            "Stacey Learning Cohort v1",
            COHORT_ID,
            now,
            now,
        ),
    )
    conn.execute(
        """INSERT INTO learning_cohorts
        (id, campaign_slug, creator, soul_id, account_handle, timezone,
         start_date, seed, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?)""",
        (
            COHORT_ID,
            COHORT_ID,
            CREATOR,
            SOUL_ID,
            ACCOUNT_HANDLE,
            TIMEZONE,
            parsed_start.isoformat(),
            seed,
            now,
            now,
        ),
    )
    control_days = {
        surface: set(_control_days(seed, surface))
        for surface in ("regular_reel", "trial_reel")
    }
    for day_index in range(1, TOTAL_DAYS + 1):
        early_surface = "regular_reel" if day_index % 2 else "trial_reel"
        for surface in ("regular_reel", "trial_reel"):
            base_hour = 12 if surface == early_surface else 19
            assignment_seed = f"{seed}:{day_index}:{surface}"
            jitter = _jitter_minutes(assignment_seed)
            local_dt = datetime.combine(
                parsed_start + timedelta(days=day_index - 1),
                time(base_hour, 0),
                tzinfo=ZoneInfo(TIMEZONE),
            ) + timedelta(minutes=jitter)
            arm = "control" if day_index in control_days[surface] else "ranked"
            assignment_id = f"lca_{_digest(assignment_seed)[:16]}"
            conn.execute(
                """INSERT INTO learning_cohort_assignments
                (id, cohort_id, day_index, arm, surface, scheduled_for,
                 assignment_seed, metric_72h_state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    assignment_id,
                    COHORT_ID,
                    day_index,
                    arm,
                    surface,
                    local_dt.isoformat(),
                    assignment_seed,
                    "pending" if surface == "trial_reel" else "not_required",
                    now,
                    now,
                ),
            )
    conn.commit()
    return _prepare_report(_assignment_rows(conn), idempotent=False)


def run_learning_cohort_day(
    conn: sqlite3.Connection, *, day_index: int
) -> dict[str, Any]:
    ensure_learning_cohort_tables(conn)
    if not 1 <= day_index <= TOTAL_DAYS:
        raise ValueError("day_index must be between 1 and 25")
    cohort = conn.execute(
        "SELECT * FROM learning_cohorts WHERE id = ?", (COHORT_ID,)
    ).fetchone()
    if cohort is None:
        raise RuntimeError("cohort_not_prepared")
    blockers = _run_day_blockers(conn, day_index=day_index)
    assignments = _rows_to_dicts(
        conn.execute(
            """SELECT * FROM learning_cohort_assignments
            WHERE cohort_id = ? AND day_index = ? ORDER BY scheduled_for""",
            (COHORT_ID, day_index),
        ).fetchall()
    )
    if not blockers:
        now = _utc_now()
        conn.execute(
            """UPDATE learning_cohort_assignments
            SET generation_state = CASE WHEN generation_state = 'planned'
              THEN 'queued' ELSE generation_state END, updated_at = ?
            WHERE cohort_id = ? AND day_index = ?""",
            (now, COHORT_ID, day_index),
        )
        conn.execute(
            "UPDATE learning_cohorts SET status = 'active', updated_at = ? WHERE id = ?",
            (now, COHORT_ID),
        )
        conn.commit()
        assignments = _rows_to_dicts(
            conn.execute(
                """SELECT * FROM learning_cohort_assignments
                WHERE cohort_id = ? AND day_index = ? ORDER BY scheduled_for""",
                (COHORT_ID, day_index),
            ).fetchall()
        )
    return {
        "schema": "campaign_factory.learning_cohort.run_day.v1",
        "cohortId": COHORT_ID,
        "dayIndex": day_index,
        "status": "paused" if blockers else "queued_for_generation",
        "blockingReasons": blockers,
        "assignments": [_public_assignment(row) for row in assignments],
        "autoposterEnabled": False,
        "requiresApprovalBeforeSchedule": True,
    }


def assign_learning_cohort_references(
    conn: sqlite3.Connection,
    *,
    identity_manifest_path: Path,
    apply: bool = False,
) -> dict[str, Any]:
    """Deterministically attach Stacey identity evidence and ranked patterns."""
    ensure_learning_cohort_tables(conn)
    cohort = conn.execute(
        "SELECT * FROM learning_cohorts WHERE id = ?", (COHORT_ID,)
    ).fetchone()
    if cohort is None:
        raise RuntimeError("cohort_not_prepared")
    manifest_path = identity_manifest_path.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("creator") != CREATOR or manifest.get("status") != "ready":
        raise ValueError("identity manifest must be a ready Stacey reference set")
    source_images = [
        row
        for row in manifest.get("sourceImages", [])
        if row.get("status") == "embedded" and row.get("path") and row.get("sha256")
    ]
    if not source_images:
        raise ValueError("identity manifest has no embedded source images")
    missing_paths = [
        str(row["path"]) for row in source_images if not Path(row["path"]).is_file()
    ]
    if missing_paths:
        raise FileNotFoundError(
            "identity reference paths are missing: " + ", ".join(missing_paths)
        )
    patterns = conn.execute(
        """SELECT rp.id, rp.cluster_key, rp.rank
        FROM campaign_reference_plans crp
        JOIN campaigns c ON c.id = crp.campaign_id
        JOIN reference_patterns rp ON rp.id = crp.reference_pattern_id
        WHERE c.slug = ?
        ORDER BY COALESCE(rp.rank, 2147483647), rp.id""",
        (COHORT_ID,),
    ).fetchall()
    if not patterns:
        raise RuntimeError("cohort_has_no_reference_patterns")
    assignments = _assignment_rows(conn)
    planned: list[dict[str, Any]] = []
    changes = 0
    now = _utc_now()
    reference_set_id = str(manifest.get("referenceSetId") or "stacey")
    for index, assignment in enumerate(assignments):
        source = source_images[index % len(source_images)]
        pattern = patterns[index % len(patterns)]
        reference_id = f"{reference_set_id}:{str(source['sha256'])[:16]}"
        fingerprint = _digest(
            f"{COHORT_ID}:{assignment['id']}:{reference_id}:{pattern['id']}"
        )
        changed = any(
            (
                assignment["reference_id"] != reference_id,
                assignment["candidate_rank"] != pattern["rank"],
                assignment["source_family"] != pattern["id"],
                assignment["perceptual_cluster"] != pattern["cluster_key"],
                assignment["content_fingerprint"] != fingerprint,
            )
        )
        changes += int(changed)
        planned.append(
            {
                "assignmentId": assignment["id"],
                "referenceId": reference_id,
                "referencePath": str(source["path"]),
                "referencePatternId": pattern["id"],
                "candidateRank": pattern["rank"],
                "changed": changed,
            }
        )
        if apply and changed:
            conn.execute(
                """UPDATE learning_cohort_assignments
                SET reference_id = ?, candidate_rank = ?, source_family = ?,
                    perceptual_cluster = ?, content_fingerprint = ?, updated_at = ?
                WHERE id = ? AND cohort_id = ?""",
                (
                    reference_id,
                    pattern["rank"],
                    pattern["id"],
                    pattern["cluster_key"],
                    fingerprint,
                    now,
                    assignment["id"],
                    COHORT_ID,
                ),
            )
    if apply:
        conn.commit()
    return {
        "schema": "campaign_factory.learning_cohort.reference_assignment.v1",
        "cohortId": COHORT_ID,
        "dryRun": not apply,
        "assignmentCount": len(assignments),
        "changes": changes,
        "identityManifest": str(manifest_path),
        "referenceSetId": reference_set_id,
        "patternCount": len(patterns),
        "assignments": planned,
    }


def learning_cohort_status(conn: sqlite3.Connection) -> dict[str, Any]:
    ensure_learning_cohort_tables(conn)
    cohort = conn.execute(
        "SELECT * FROM learning_cohorts WHERE id = ?", (COHORT_ID,)
    ).fetchone()
    if cohort is None:
        return {
            "schema": "campaign_factory.learning_cohort.status.v1",
            "cohortId": COHORT_ID,
            "status": "not_prepared",
        }
    rows = _assignment_rows(conn)
    by_arm_surface: dict[str, int] = {}
    for row in rows:
        key = f"{row['arm']}:{row['surface']}"
        by_arm_surface[key] = by_arm_surface.get(key, 0) + 1
    return {
        "schema": "campaign_factory.learning_cohort.status.v1",
        "cohortId": COHORT_ID,
        "status": cohort["status"],
        "postsByArmSurface": by_arm_surface,
        "metricWindows": {
            "oneHourComplete": sum(r["metric_1h_state"] == "complete" for r in rows),
            "twentyFourHourComplete": sum(
                r["metric_24h_state"] == "complete" for r in rows
            ),
            "trialSeventyTwoHourComplete": sum(
                r["surface"] == "trial_reel" and r["metric_72h_state"] == "complete"
                for r in rows
            ),
        },
        "ledgerStates": _counts(rows, "generation_state"),
        "approvalStates": _counts(rows, "approval_state"),
        "publishStates": _counts(rows, "publish_state"),
        "retries": sum(int(r["retry_count"] or 0) for r in rows),
        "spend": _cohort_spend(conn),
        "currentLift": _lift_report(rows),
        "autoposterEnabled": bool(cohort["autoposter_enabled"]),
        "automaticTrialGraduation": bool(cohort["automatic_trial_graduation"]),
    }


def audit_learning_cohort(conn: sqlite3.Connection) -> dict[str, Any]:
    status = learning_cohort_status(conn)
    if status.get("status") == "not_prepared":
        return {**status, "passed": False, "blockingReasons": ["cohort_not_prepared"]}
    rows = _assignment_rows(conn)
    lift = _lift_report(rows)
    blockers: list[str] = []
    if len(rows) != 50:
        blockers.append("eligible_post_count_not_50")
    if any(r["metric_1h_state"] != "complete" for r in rows):
        blockers.append("missing_1h_evidence")
    if any(r["metric_24h_state"] != "complete" for r in rows):
        blockers.append("missing_24h_evidence")
    if any(
        r["surface"] == "trial_reel" and r["metric_72h_state"] != "complete"
        for r in rows
    ):
        blockers.append("missing_trial_72h_evidence")
    if any(r["reward_24h"] is None for r in rows):
        blockers.append("missing_or_imputed_reward")
    if lift.get("overallLift") is None or float(lift["overallLift"]) < 0.15:
        blockers.append("ranked_lift_below_15_percent")
    if float(lift.get("bootstrapPositiveConfidence") or 0) < 0.95:
        blockers.append("bootstrap_positive_confidence_below_95_percent")
    surface_lifts = lift.get("surfaceLift") or {}
    if any(value is None or value < 0 for value in surface_lifts.values()):
        blockers.append("negative_surface_median_lift")
    if status.get("spend", {}).get("credits", 0) > 150:
        blockers.append("cohort_spend_cap_breached")
    if status.get("autoposterEnabled"):
        blockers.append("autoposter_enabled")
    if status.get("automaticTrialGraduation"):
        blockers.append("automatic_trial_graduation_enabled")
    if any(r["publish_state"] in {"ambiguous", "unauthorized"} for r in rows):
        blockers.append("ambiguous_or_unauthorized_publish")
    return {
        "schema": "campaign_factory.learning_cohort.audit.v1",
        "cohortId": COHORT_ID,
        "passed": not blockers,
        "blockingReasons": blockers,
        "lift": lift,
        "status": status,
    }


def learning_cohort_assignment_metadata(
    conn: sqlite3.Connection, assignment_id: str
) -> dict[str, Any]:
    ensure_learning_cohort_tables(conn)
    row = conn.execute(
        "SELECT * FROM learning_cohort_assignments WHERE id = ? AND cohort_id = ?",
        (assignment_id, COHORT_ID),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown learning cohort assignment: {assignment_id}")
    value = dict(row)
    return {
        "cohort_id": value["cohort_id"],
        "assignment_id": value["id"],
        "day_index": value["day_index"],
        "arm": value["arm"],
        "surface": value["surface"],
        "reference_id": value["reference_id"],
        "candidate_rank": value["candidate_rank"],
        "assignment_seed": value["assignment_seed"],
        "source_family": value["source_family"],
        "content_fingerprint": value["content_fingerprint"],
        "provider_reservation_id": value["provider_reservation_id"],
        "draft_id": value["draft_id"],
        "post_id": value["post_id"],
        "creator": CREATOR,
        "soul_id": SOUL_ID,
        "account_handle": ACCOUNT_HANDLE,
        "generation_state": value["generation_state"],
        "approval_state": value["approval_state"],
        "schedule_state": value["schedule_state"],
        "publish_state": value["publish_state"],
        "metric_1h_state": value["metric_1h_state"],
        "metric_24h_state": value["metric_24h_state"],
        "metric_72h_state": value["metric_72h_state"],
    }


def record_learning_cohort_generation(
    conn: sqlite3.Connection,
    *,
    assignment_id: str,
    rendered_asset_id: str,
    lineage_path: Path,
    artifact_path: Path,
    provider_reservation_id: str | None = None,
) -> dict[str, Any]:
    """Bind one real rendered asset and learning-traceable v2 lineage to its assignment."""
    ensure_learning_cohort_tables(conn)
    assignment = _assignment_row(conn, assignment_id)
    if assignment["generation_state"] not in {
        "queued",
        "complete",
        "draft_ingested",
    }:
        raise ValueError(
            "learning cohort generation can only be recorded from queued, complete, or draft_ingested state"
        )
    prior_asset_id = str(assignment.get("rendered_asset_id") or "")
    if prior_asset_id and prior_asset_id != rendered_asset_id:
        raise ValueError(
            "cohort assignment is already bound to a different rendered asset"
        )
    asset_row = conn.execute(
        """SELECT ra.*, c.slug AS campaign_slug, sa.source_prompt
        FROM rendered_assets ra
        JOIN campaigns c ON c.id = ra.campaign_id
        JOIN source_assets sa ON sa.id = ra.source_asset_id
        WHERE ra.id = ?""",
        (rendered_asset_id,),
    ).fetchone()
    if asset_row is None:
        raise ValueError(f"unknown rendered asset: {rendered_asset_id}")
    asset = dict(asset_row)
    if asset["campaign_slug"] != COHORT_ID:
        raise ValueError(
            "rendered asset does not belong to the learning cohort campaign"
        )

    artifact = artifact_path.expanduser().resolve()
    expected_artifact = Path(str(asset["output_path"])).expanduser().resolve()
    if not artifact.is_file() or artifact != expected_artifact:
        raise ValueError(
            "artifact path must match the registered rendered asset output"
        )
    source_lineage = lineage_path.expanduser().resolve()
    try:
        lineage = json.loads(source_lineage.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("lineage path must contain valid JSON") from exc
    if not lineage_v2_is_learning_traceable(
        lineage,
        campaign_id=asset["campaign_id"],
        recipe_id=asset["recipe"],
        caption_hash=asset["caption_hash"],
        rendered_asset_id=rendered_asset_id,
    ):
        raise ValueError("generated asset lineage is not learning-traceable v2")
    source = lineage.get("source") if isinstance(lineage.get("source"), dict) else {}
    if source.get("referenceId") != assignment["reference_id"]:
        raise ValueError("lineage referenceId does not match the cohort assignment")
    if lineage.get("contentFingerprint") != assignment["content_fingerprint"]:
        raise ValueError(
            "lineage contentFingerprint does not match the cohort assignment"
        )
    if lineage.get("sourceFamilyId") != assignment["source_family"]:
        raise ValueError("lineage sourceFamilyId does not match the cohort assignment")
    if lineage.get("perceptualClusterId") != assignment["perceptual_cluster"]:
        raise ValueError(
            "lineage perceptualClusterId does not match the cohort assignment"
        )

    source_prompt = _json_object(asset.get("source_prompt"))
    source_prompt.update(
        {
            "generatedAssetLineage": lineage,
            "promptId": source["promptId"],
            "referenceId": source["referenceId"],
            "referencePattern": assignment["source_family"],
            "cohortAssignment": {
                "cohortId": COHORT_ID,
                "assignmentId": assignment_id,
                "dayIndex": assignment["day_index"],
                "arm": assignment["arm"],
                "surface": assignment["surface"],
            },
        }
    )
    durable_lineage_path = artifact.with_suffix(
        artifact.suffix + ".generated_asset_lineage.json"
    )
    atomic_write_text(
        durable_lineage_path,
        json.dumps(lineage, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    now = _utc_now()
    conn.execute(
        "UPDATE source_assets SET source_prompt = ?, updated_at = ? WHERE id = ?",
        (
            json.dumps(source_prompt, ensure_ascii=False, sort_keys=True),
            now,
            asset["source_asset_id"],
        ),
    )
    conn.execute(
        """UPDATE learning_cohort_assignments
        SET rendered_asset_id = ?, artifact_path = ?, lineage_path = ?,
            provider_reservation_id = COALESCE(?, provider_reservation_id),
            generation_state = 'complete', updated_at = ?
        WHERE id = ? AND cohort_id = ?""",
        (
            rendered_asset_id,
            str(artifact),
            str(durable_lineage_path),
            provider_reservation_id,
            now,
            assignment_id,
            COHORT_ID,
        ),
    )
    conn.commit()
    return _transition_result(conn, assignment_id, "generation_recorded")


def record_learning_cohort_draft(
    conn: sqlite3.Connection, *, assignment_id: str, draft_id: str
) -> dict[str, Any]:
    ensure_learning_cohort_tables(conn)
    assignment = _assignment_row(conn, assignment_id)
    if not assignment.get("rendered_asset_id") or assignment[
        "generation_state"
    ] not in {
        "complete",
        "draft_ingested",
    }:
        raise ValueError("cohort draft requires a completed generated asset")
    prior = str(assignment.get("draft_id") or "")
    draft_id = str(draft_id or "").strip()
    if not draft_id:
        raise ValueError("draft_id is required")
    if prior and prior != draft_id:
        raise ValueError("cohort assignment is already bound to a different draft")
    now = _utc_now()
    conn.execute(
        """UPDATE learning_cohort_assignments
        SET draft_id = ?, generation_state = 'draft_ingested',
            schedule_state = 'blocked_pending_approval', updated_at = ?
        WHERE id = ? AND cohort_id = ?""",
        (draft_id, now, assignment_id, COHORT_ID),
    )
    conn.commit()
    return _transition_result(conn, assignment_id, "draft_recorded")


def record_learning_cohort_approval(
    conn: sqlite3.Connection, *, assignment_id: str, decision: str
) -> dict[str, Any]:
    ensure_learning_cohort_tables(conn)
    assignment = _assignment_row(conn, assignment_id)
    decision = str(decision or "").strip().lower()
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")
    if not assignment.get("draft_id"):
        raise ValueError("cohort approval requires a recorded draft")
    schedule_state = (
        "ready_for_manual_publish" if decision == "approved" else "blocked_rejected"
    )
    now = _utc_now()
    conn.execute(
        """UPDATE learning_cohort_assignments
        SET approval_state = ?, schedule_state = ?, updated_at = ?
        WHERE id = ? AND cohort_id = ?""",
        (decision, schedule_state, now, assignment_id, COHORT_ID),
    )
    conn.commit()
    return _transition_result(conn, assignment_id, "approval_recorded")


def record_learning_cohort_publish(
    conn: sqlite3.Connection,
    *,
    assignment_id: str,
    post_id: str,
    published_at: str,
) -> dict[str, Any]:
    ensure_learning_cohort_tables(conn)
    assignment = _assignment_row(conn, assignment_id)
    if assignment["approval_state"] != "approved" or not assignment.get("draft_id"):
        raise ValueError("cohort publish requires an approved recorded draft")
    post_id = str(post_id or "").strip()
    if not post_id:
        raise ValueError("post_id is required")
    parsed = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("published_at must include a timezone")
    prior = str(assignment.get("post_id") or "")
    if prior and prior != post_id:
        raise ValueError("cohort assignment is already bound to a different post")
    now = _utc_now()
    conn.execute(
        """UPDATE learning_cohort_assignments
        SET post_id = ?, published_at = ?, publish_state = 'published',
            schedule_state = 'published', updated_at = ?
        WHERE id = ? AND cohort_id = ?""",
        (post_id, parsed.isoformat(), now, assignment_id, COHORT_ID),
    )
    conn.commit()
    return _transition_result(conn, assignment_id, "publish_recorded")


def sync_learning_cohort_metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    """Project canonical metric-history snapshots into the cohort ledger.

    This is intentionally deterministic and reversible: every run derives the
    assignment state from the currently eligible snapshots, so a retracted or
    corrected snapshot removes stale completion/reward state on the next sync.
    """
    ensure_learning_cohort_tables(conn)
    cohort = conn.execute(
        "SELECT 1 FROM learning_cohorts WHERE id = ?", (COHORT_ID,)
    ).fetchone()
    if cohort is None:
        return {
            "schema": "campaign_factory.learning_cohort.metric_sync.v1",
            "cohortId": COHORT_ID,
            "status": "cohort_not_prepared",
            "assignmentsChecked": 0,
            "assignmentsChanged": 0,
        }
    cutover = learning_loop_cutover()
    if cutover is None:
        return {
            "schema": "campaign_factory.learning_cohort.metric_sync.v1",
            "cohortId": COHORT_ID,
            "status": "blocked_cutover_unset",
            "assignmentsChecked": 0,
            "assignmentsChanged": 0,
        }

    assignments = _rows_to_dicts(
        conn.execute(
            """SELECT * FROM learning_cohort_assignments
            WHERE cohort_id = ? AND publish_state = 'published'
              AND post_id IS NOT NULL
            ORDER BY day_index, surface""",
            (COHORT_ID,),
        ).fetchall()
    )
    post_ids = sorted({str(row["post_id"]) for row in assignments})
    snapshots_by_post: dict[str, list[dict[str, Any]]] = {}
    if post_ids:
        placeholders = ",".join("?" for _ in post_ids)
        snapshots = _rows_to_dicts(
            conn.execute(
                f"""SELECT * FROM performance_snapshots
                WHERE post_id IN ({placeholders})
                ORDER BY post_id, snapshot_at""",
                post_ids,
            ).fetchall()
        )
        for snapshot in snapshots:
            if not learning_eligible(snapshot, cutover=cutover):
                continue
            hour = _snapshot_history_hour(snapshot)
            if hour is None:
                continue
            snapshot["_history_hour"] = hour
            snapshots_by_post.setdefault(str(snapshot["post_id"]), []).append(snapshot)

    changed = 0
    completed = {"oneHour": 0, "twentyFourHour": 0, "trialSeventyTwoHour": 0}
    rewards_written = 0
    now = _utc_now()
    for assignment in assignments:
        snapshots = snapshots_by_post.get(str(assignment["post_id"]), [])
        one_hour = _snapshot_for_window(snapshots, "metric_1h_state")
        twenty_four_hour = _snapshot_for_window(snapshots, "metric_24h_state")
        seventy_two_hour = (
            _snapshot_for_window(snapshots, "metric_72h_state")
            if assignment["surface"] == "trial_reel"
            else None
        )
        next_1h = "complete" if one_hour is not None else "pending"
        next_24h = "complete" if twenty_four_hour is not None else "pending"
        next_72h = (
            "complete"
            if seventy_two_hour is not None
            else "pending"
            if assignment["surface"] == "trial_reel"
            else "not_required"
        )
        reward = (
            snapshot_reward(_learning_score_snapshot(twenty_four_hour))
            if twenty_four_hour is not None
            else None
        )
        completed["oneHour"] += next_1h == "complete"
        completed["twentyFourHour"] += next_24h == "complete"
        completed["trialSeventyTwoHour"] += next_72h == "complete"
        rewards_written += reward is not None
        row_changed = any(
            (
                assignment["metric_1h_state"] != next_1h,
                assignment["metric_24h_state"] != next_24h,
                assignment["metric_72h_state"] != next_72h,
                not _same_optional_float(assignment["reward_24h"], reward),
            )
        )
        if not row_changed:
            continue
        conn.execute(
            """UPDATE learning_cohort_assignments
            SET metric_1h_state = ?, metric_24h_state = ?, metric_72h_state = ?,
                reward_24h = ?, updated_at = ?
            WHERE id = ? AND cohort_id = ?""",
            (
                next_1h,
                next_24h,
                next_72h,
                reward,
                now,
                assignment["id"],
                COHORT_ID,
            ),
        )
        changed += 1
    conn.commit()
    return {
        "schema": "campaign_factory.learning_cohort.metric_sync.v1",
        "cohortId": COHORT_ID,
        "status": "synced",
        "assignmentsChecked": len(assignments),
        "assignmentsChanged": changed,
        "metricWindows": completed,
        "rewardsWritten": rewards_written,
    }


def _snapshot_history_hour(snapshot: dict[str, Any]) -> float | None:
    payload = _json_object(snapshot.get("raw_json"))
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    history = (
        metadata.get("threadsdash_metric_history")
        if isinstance(metadata, dict)
        else None
    )
    if isinstance(history, dict):
        value = history.get("hoursSincePublish", history.get("hours_since_publish"))
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
    try:
        snapshot_at = datetime.fromisoformat(
            str(snapshot["snapshot_at"]).replace("Z", "+00:00")
        )
        published_at = datetime.fromisoformat(
            str(snapshot["published_at"]).replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError):
        return None
    if snapshot_at.tzinfo is None:
        snapshot_at = snapshot_at.replace(tzinfo=ZoneInfo("UTC"))
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=ZoneInfo("UTC"))
    return (snapshot_at - published_at).total_seconds() / 3600


def _snapshot_for_window(
    snapshots: list[dict[str, Any]], state: str
) -> dict[str, Any] | None:
    target, minimum, maximum = METRIC_WINDOWS[state]
    candidates = [
        row for row in snapshots if minimum <= float(row["_history_hour"]) <= maximum
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda row: (
            abs(float(row["_history_hour"]) - target),
            str(row.get("snapshot_at") or ""),
        ),
    )


def _learning_score_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics": {
            "views": snapshot.get("views"),
            "likes": snapshot.get("likes"),
            "comments": snapshot.get("comments"),
            "shares": snapshot.get("shares"),
            "saves": snapshot.get("saves"),
            "impressions": snapshot.get("impressions"),
            "reach": snapshot.get("reach"),
        }
    }


def _same_optional_float(left: Any, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return abs(float(left) - right) < 1e-12


def _assignment_row(conn: sqlite3.Connection, assignment_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM learning_cohort_assignments WHERE id = ? AND cohort_id = ?",
        (assignment_id, COHORT_ID),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown learning cohort assignment: {assignment_id}")
    return dict(row)


def _transition_result(
    conn: sqlite3.Connection, assignment_id: str, transition: str
) -> dict[str, Any]:
    row = _assignment_row(conn, assignment_id)
    return {
        "schema": "campaign_factory.learning_cohort.transition.v1",
        "cohortId": COHORT_ID,
        "assignmentId": assignment_id,
        "transition": transition,
        "renderedAssetId": row.get("rendered_asset_id"),
        "draftId": row.get("draft_id"),
        "postId": row.get("post_id"),
        "generationState": row["generation_state"],
        "approvalState": row["approval_state"],
        "scheduleState": row["schedule_state"],
        "publishState": row["publish_state"],
        "publishedAt": row.get("published_at"),
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _run_day_blockers(conn: sqlite3.Connection, *, day_index: int) -> list[str]:
    blockers: list[str] = []
    missing_references = conn.execute(
        """SELECT COUNT(*) FROM learning_cohort_assignments
        WHERE cohort_id = ? AND day_index = ?
          AND (reference_id IS NULL OR source_family IS NULL
               OR content_fingerprint IS NULL)""",
        (COHORT_ID, day_index),
    ).fetchone()[0]
    if missing_references:
        blockers.append("reference_assignment_missing")
    ambiguous = conn.execute(
        """SELECT COUNT(*) FROM learning_cohort_assignments
        WHERE cohort_id = ? AND day_index < ? AND publish_state = 'ambiguous'""",
        (COHORT_ID, day_index),
    ).fetchone()[0]
    if ambiguous:
        blockers.append("prior_post_state_ambiguous")
    backlog = conn.execute(
        """SELECT COUNT(*) FROM learning_cohort_assignments
        WHERE cohort_id = ? AND day_index < ? AND day_index <= ?
          AND draft_id IS NOT NULL AND approval_state = 'pending'""",
        (COHORT_ID, day_index, day_index - 3),
    ).fetchone()[0]
    if backlog:
        blockers.append("approval_backlog_exceeds_two_days")
    spend = _cohort_spend(conn)["credits"]
    if spend >= 150:
        blockers.append("cohort_spend_cap_reached")
    return blockers


def _control_days(seed: str, surface: str) -> list[int]:
    rng = random.Random(int(_digest(f"{seed}:{surface}:controls")[:16], 16))
    return sorted(rng.sample(range(1, TOTAL_DAYS + 1), 5))


def _jitter_minutes(seed: str) -> int:
    return int(_digest(seed)[:8], 16) % 41 - 20


def _prepare_report(rows: list[dict[str, Any]], *, idempotent: bool) -> dict[str, Any]:
    return {
        "schema": "campaign_factory.learning_cohort.prepare.v1",
        "cohortId": COHORT_ID,
        "idempotent": idempotent,
        "assignmentCount": len(rows),
        "rankedCount": sum(r["arm"] == "ranked" for r in rows),
        "controlCount": sum(r["arm"] == "control" for r in rows),
        "surfaceCounts": _counts(rows, "surface"),
        "controlSurfaceCounts": _counts(
            [r for r in rows if r["arm"] == "control"], "surface"
        ),
        "autoposterEnabled": False,
        "automaticTrialGraduation": False,
    }


def _lift_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = [
        float(r["reward_24h"])
        for r in rows
        if r["arm"] == "ranked" and r["reward_24h"] is not None
    ]
    controls = [
        float(r["reward_24h"])
        for r in rows
        if r["arm"] == "control" and r["reward_24h"] is not None
    ]
    overall = _relative_median_lift(ranked, controls)
    surface_lift = {
        surface: _relative_median_lift(
            [
                float(r["reward_24h"])
                for r in rows
                if r["surface"] == surface
                and r["arm"] == "ranked"
                and r["reward_24h"] is not None
            ],
            [
                float(r["reward_24h"])
                for r in rows
                if r["surface"] == surface
                and r["arm"] == "control"
                and r["reward_24h"] is not None
            ],
        )
        for surface in ("regular_reel", "trial_reel")
    }
    confidence = _bootstrap_positive_confidence(ranked, controls)
    return {
        "overallLift": overall,
        "surfaceLift": surface_lift,
        "bootstrapPositiveConfidence": confidence,
        "rankedMeasured": len(ranked),
        "controlMeasured": len(controls),
    }


def _relative_median_lift(ranked: list[float], controls: list[float]) -> float | None:
    if not ranked or not controls:
        return None
    baseline = statistics.median(controls)
    if baseline <= 0:
        return None
    return round((statistics.median(ranked) - baseline) / baseline, 6)


def _bootstrap_positive_confidence(
    ranked: list[float], controls: list[float], *, samples: int = 2000
) -> float | None:
    if not ranked or not controls:
        return None
    rng = random.Random(20260710)
    positive = 0
    for _ in range(samples):
        ranked_median = statistics.median(rng.choices(ranked, k=len(ranked)))
        control_median = statistics.median(rng.choices(controls, k=len(controls)))
        positive += ranked_median > control_median
    return round(positive / samples, 6)


def _cohort_spend(conn: sqlite3.Connection) -> dict[str, Any]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='higgsfield_spend_reservations'"
    ).fetchone()
    if not exists:
        return {"credits": 0.0, "unit": "higgsfield_credits"}
    columns = {
        str(row[1])
        for row in conn.execute(
            "PRAGMA table_info(higgsfield_spend_reservations)"
        ).fetchall()
    }
    if not {"amount", "unit", "cohort_id"}.issubset(columns):
        return {"credits": 0.0, "unit": "higgsfield_credits"}
    row = conn.execute(
        """SELECT COALESCE(SUM(amount), 0) FROM higgsfield_spend_reservations
        WHERE cohort_id = ? AND unit = 'higgsfield_credits'
          AND status IN ('reserved', 'consumed')""",
        (COHORT_ID,),
    ).fetchone()
    return {"credits": round(float(row[0] or 0), 4), "unit": "higgsfield_credits"}


def _assignment_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return _rows_to_dicts(
        conn.execute(
            "SELECT * FROM learning_cohort_assignments WHERE cohort_id = ? ORDER BY day_index, surface",
            (COHORT_ID,),
        ).fetchall()
    )


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = str(row[key])
        result[value] = result.get(value, 0) + 1
    return result


def _public_assignment(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "assignmentId": row["id"],
        "cohortId": row["cohort_id"],
        "dayIndex": row["day_index"],
        "arm": row["arm"],
        "surface": row["surface"],
        "scheduledFor": row["scheduled_for"],
        "assignmentSeed": row["assignment_seed"],
        "generationState": row["generation_state"],
        "approvalState": row["approval_state"],
        "scheduleState": row["schedule_state"],
        "publishState": row["publish_state"],
        "metric1hState": row["metric_1h_state"],
        "metric24hState": row["metric_24h_state"],
        "metric72hState": row["metric_72h_state"],
        "referenceId": row["reference_id"],
        "candidateRank": row["candidate_rank"],
        "sourceFamily": row["source_family"],
        "contentFingerprint": row["content_fingerprint"],
        "providerReservationId": row["provider_reservation_id"],
        "draftId": row["draft_id"],
        "postId": row["post_id"],
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
