#!/usr/bin/env python3
"""Advance the due learning-cohort day without spending or publishing."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from campaign_factory.learning_cohort import (
    COHORT_ID,
    TOTAL_DAYS,
    run_learning_cohort_day,
)
from creator_os_core.fileops import atomic_write_text
from creator_os_core.sqlite import connect_sqlite

SCHEMA = "creator_os.learning_cohort_daily.v1"


def configured_campaigns(raw: str | None) -> list[str]:
    try:
        values = json.loads(raw or "")
    except json.JSONDecodeError as exc:
        raise ValueError("campaigns must be a JSON array") from exc
    if not isinstance(values, list) or not values:
        raise ValueError("campaigns must be a non-empty JSON array")
    campaigns = [str(value).strip() for value in values]
    if not all(campaigns) or len(campaigns) != len(set(campaigns)):
        raise ValueError("campaigns must contain unique non-empty names")
    if campaigns != [COHORT_ID]:
        raise ValueError(f"daily cohort scope must be exactly {COHORT_ID}")
    return campaigns


def _cohort(conn: sqlite3.Connection) -> dict[str, Any] | None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='learning_cohorts'"
    ).fetchone()
    if not exists:
        return None
    row = conn.execute(
        "SELECT * FROM learning_cohorts WHERE id = ?", (COHORT_ID,)
    ).fetchone()
    return dict(row) if row is not None else None


def _local_now(cohort: dict[str, Any], now: datetime | None) -> datetime:
    timezone = ZoneInfo(str(cohort["timezone"]))
    if now is None:
        return datetime.now(timezone)
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    return now.astimezone(timezone)


def _due_day(cohort: dict[str, Any], local_now: datetime) -> int:
    start = datetime.fromisoformat(str(cohort["start_date"])).date()
    return (local_now.date() - start).days + 1


def _unresolved_prior_handoffs(
    conn: sqlite3.Connection, *, day_index: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, day_index, surface, scheduled_for, draft_id, post_id,
                  approval_state, schedule_state, publish_state
        FROM learning_cohort_assignments
        WHERE cohort_id = ? AND day_index < ?
          AND approval_state = 'approved'
          AND publish_state != 'published'
          AND schedule_state != 'blocked_rejected'
        ORDER BY day_index, surface""",
        (COHORT_ID, day_index),
    ).fetchall()
    return [dict(row) for row in rows]


def _due_assignments(
    conn: sqlite3.Connection, *, day_index: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, day_index, arm, surface, scheduled_for, generation_state,
                  approval_state, schedule_state, publish_state
        FROM learning_cohort_assignments
        WHERE cohort_id = ? AND day_index = ?
        ORDER BY scheduled_for""",
        (COHORT_ID, day_index),
    ).fetchall()
    return [dict(row) for row in rows]


def run_daily_cycle(
    conn: sqlite3.Connection, *, now: datetime | None = None, apply: bool = False
) -> dict[str, Any]:
    cohort = _cohort(conn)
    generated_at = (now or datetime.now(ZoneInfo("UTC"))).isoformat()
    base: dict[str, Any] = {
        "schema": SCHEMA,
        "cohortId": COHORT_ID,
        "generatedAt": generated_at,
        "apply": apply,
        "providerCalls": 0,
        "creditsSpent": 0,
        "draftActionsTaken": 0,
        "scheduleActionsTaken": 0,
        "publishingActionsTaken": 0,
    }
    if cohort is None:
        return {
            **base,
            "status": "cohort_not_prepared",
            "blockingReasons": ["cohort_not_prepared"],
        }
    local_now = _local_now(cohort, now)
    day_index = _due_day(cohort, local_now)
    base.update(
        {
            "generatedAt": local_now.isoformat(),
            "timezone": cohort["timezone"],
            "dayIndex": day_index,
        }
    )
    if day_index < 1:
        return {
            **base,
            "status": "waiting_for_start",
            "blockingReasons": [],
        }
    if day_index > TOTAL_DAYS:
        return {**base, "status": "cohort_window_complete", "blockingReasons": []}

    unresolved = _unresolved_prior_handoffs(conn, day_index=day_index)
    due = _due_assignments(conn, day_index=day_index)
    if unresolved:
        return {
            **base,
            "status": "operator_action_required",
            "blockingReasons": ["prior_approved_publish_not_confirmed"],
            "unresolvedPriorHandoffs": unresolved,
            "dueAssignments": due,
        }
    if not due:
        return {
            **base,
            "status": "due_assignments_missing",
            "blockingReasons": ["due_assignments_missing"],
            "dueAssignments": [],
        }
    if all(str(row.get("generation_state") or "") != "planned" for row in due):
        return {
            **base,
            "status": "day_already_started",
            "blockingReasons": [],
            "dueAssignments": due,
            "autoposterEnabled": False,
            "requiresApprovalBeforeSchedule": True,
        }
    if not apply:
        return {
            **base,
            "status": "ready_to_queue",
            "blockingReasons": [],
            "dueAssignments": due,
        }

    transition = run_learning_cohort_day(conn, day_index=day_index)
    status = str(transition["status"])
    return {
        **base,
        "status": status,
        "blockingReasons": transition.get("blockingReasons") or [],
        "dueAssignments": _due_assignments(conn, day_index=day_index),
        "autoposterEnabled": False,
        "requiresApprovalBeforeSchedule": True,
    }


def _parse_now(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--now must include a timezone")
    return parsed


def _notify(path: Path, report: dict[str, Any]) -> None:
    if not path.is_file():
        return
    unresolved = len(report.get("unresolvedPriorHandoffs") or [])
    level = "warn" if report["status"] == "operator_action_required" else "info"
    message = f"day {report.get('dayIndex', '-')} {report['status']}" + (
        f" | {unresolved} unresolved handoff(s)" if unresolved else ""
    )
    subprocess.run(
        [str(path), level, "cohort-daily", message],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("CAMPAIGN_FACTORY_DB", "")),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--now")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / ".creator-os" / "reports",
    )
    parser.add_argument(
        "--notify", type=Path, default=Path.home() / ".creator-os" / "notify.sh"
    )
    args = parser.parse_args(argv)
    if not args.db.is_file():
        parser.error("CAMPAIGN_FACTORY_DB must point to an existing database")
    try:
        configured_campaigns(os.environ.get("CAMPAIGN_FACTORY_SYNC_CAMPAIGNS"))
        now = _parse_now(args.now)
    except ValueError as exc:
        parser.error(str(exc))

    conn = connect_sqlite(args.db)
    try:
        report = run_daily_cycle(conn, now=now, apply=args.apply)
    finally:
        conn.close()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        args.output_dir / "learning-cohort-daily-latest.json",
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _notify(args.notify.expanduser(), report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
