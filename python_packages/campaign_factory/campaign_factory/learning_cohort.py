from __future__ import annotations

import hashlib
import random
import sqlite3
import statistics
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

COHORT_ID = "stacey_learning_cohort_v1"
CREATOR = "Stacey"
SOUL_ID = "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36"
ACCOUNT_HANDLE = "staceyben101"
TIMEZONE = "America/New_York"
TOTAL_DAYS = 25


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


def _run_day_blockers(conn: sqlite3.Connection, *, day_index: int) -> list[str]:
    blockers: list[str] = []
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
