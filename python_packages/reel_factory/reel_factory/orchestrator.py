"""Dormant Reel Factory asset pipeline orchestrator state.

This module tracks where an asset is in the local creative pipeline. It does
not start paid generation, scheduling, publishing, or ThreadsDashboard runtime
paths; stage wiring is intentionally left disabled until later PRs.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .sqlite_utils import connect_sqlite

STATES = {
    "planned",
    "prompted",
    "generated",
    "qc_passed",
    "qc_failed",
    "ranked",
    "captioned",
    "export_ready",
    "awaiting_approval",
    "approved",
    "exported",
    "rejected",
    "regenerate",
    "error",
    "failed",
}

TERMINAL_STATES = {"exported", "rejected", "failed", "qc_failed"}

TRANSITIONS = {
    "planned": {"prompted"},
    "prompted": {"generated"},
    "generated": {"qc_passed", "qc_failed"},
    "qc_passed": {"ranked"},
    "ranked": {"captioned"},
    "captioned": {"export_ready"},
    "export_ready": {"awaiting_approval"},
    "awaiting_approval": {"approved", "rejected", "regenerate"},
    "approved": {"exported"},
    "error": {"planned"},
}

MAX_REGENERATE_ATTEMPTS = 2
DEFAULT_STALL_SECONDS = 6 * 60 * 60


def now_epoch() -> int:
    return int(datetime.now(UTC).timestamp())


def manifest_db_path(root: Path) -> Path:
    return Path(root).expanduser().resolve() / "manifest.sqlite"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS asset_pipeline_state (
          asset_id TEXT PRIMARY KEY,
          campaign TEXT NOT NULL,
          run_id TEXT NOT NULL,
          state TEXT NOT NULL,
          state_updated_at INTEGER NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0,
          last_error TEXT,
          lineage_path TEXT,
          output_path TEXT,
          rank_score REAL,
          predicted_engagement_json TEXT,
          approval_decision TEXT,
          approval_reason TEXT,
          approved_at INTEGER,
          created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_asset_pipeline_state_campaign_run_state
          ON asset_pipeline_state(campaign, run_id, state);
        CREATE INDEX IF NOT EXISTS idx_asset_pipeline_state_state_updated
          ON asset_pipeline_state(state, state_updated_at);
        """
    )
    conn.commit()


def open_manifest(root: Path) -> sqlite3.Connection:
    conn = connect_sqlite(manifest_db_path(root))
    ensure_schema(conn)
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def create_asset(
    conn: sqlite3.Connection,
    *,
    asset_id: str,
    campaign: str,
    run_id: str,
    lineage_path: str | None = None,
    output_path: str | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    ensure_schema(conn)
    ts = now_epoch() if now is None else now
    conn.execute(
        """
        INSERT INTO asset_pipeline_state (
          asset_id, campaign, run_id, state, state_updated_at, lineage_path,
          output_path, created_at
        ) VALUES (?, ?, ?, 'planned', ?, ?, ?, ?)
        """,
        (asset_id, campaign, run_id, ts, lineage_path, output_path, ts),
    )
    conn.commit()
    return get_asset(conn, asset_id)


def get_asset(conn: sqlite3.Connection, asset_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM asset_pipeline_state WHERE asset_id = ?",
        (asset_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown asset_id: {asset_id}")
    return dict(row)


def _legal_next_states(from_state: str) -> set[str]:
    allowed = set(TRANSITIONS.get(from_state, set()))
    if from_state not in TERMINAL_STATES and from_state != "error":
        allowed.add("error")
    return allowed


def advance(
    conn: sqlite3.Connection,
    asset_id: str,
    to_state: str,
    *,
    reason: str | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    if to_state not in STATES:
        raise ValueError(f"unknown state: {to_state}")
    row = get_asset(conn, asset_id)
    from_state = str(row["state"])
    if to_state not in _legal_next_states(from_state):
        raise ValueError(f"illegal transition: {from_state} -> {to_state}")

    ts = now_epoch() if now is None else now
    update_state = to_state
    attempts = int(row["attempts"] or 0)
    approved_at = row["approved_at"]
    approval_decision = row["approval_decision"]
    approval_reason = row["approval_reason"]
    last_error = row["last_error"]

    if to_state == "regenerate":
        attempts += 1
        approval_decision = "regenerate"
        approval_reason = reason
        if attempts > MAX_REGENERATE_ATTEMPTS:
            update_state = "failed"
            last_error = "regenerate_attempt_limit"
        else:
            update_state = "planned"
            last_error = None
    elif to_state == "approved":
        approval_decision = "approved"
        approval_reason = reason
        approved_at = ts
        last_error = None
    elif to_state == "rejected":
        approval_decision = "rejected"
        approval_reason = reason
    elif to_state == "error":
        last_error = reason or "error"
    else:
        last_error = None if from_state == "error" else last_error

    conn.execute(
        """
        UPDATE asset_pipeline_state
        SET state = ?,
            state_updated_at = ?,
            attempts = ?,
            last_error = ?,
            approval_decision = ?,
            approval_reason = ?,
            approved_at = ?
        WHERE asset_id = ?
        """,
        (
            update_state,
            ts,
            attempts,
            last_error,
            approval_decision,
            approval_reason,
            approved_at,
            asset_id,
        ),
    )
    conn.commit()
    return get_asset(conn, asset_id)


def counts_by_state(conn: sqlite3.Connection) -> dict[str, int]:
    if not table_exists(conn, "asset_pipeline_state"):
        return {}
    rows = conn.execute(
        """
        SELECT state, COUNT(*) AS count
        FROM asset_pipeline_state
        GROUP BY state
        ORDER BY state
        """
    ).fetchall()
    return {str(row["state"]): int(row["count"]) for row in rows}


def recover_stalled(
    conn: sqlite3.Connection,
    *,
    now: int | None = None,
    max_age_seconds: int = DEFAULT_STALL_SECONDS,
) -> int:
    ts = now_epoch() if now is None else now
    cutoff = ts - max_age_seconds
    candidates = conn.execute(
        """
        SELECT asset_id
        FROM asset_pipeline_state
        WHERE state NOT IN ('exported', 'rejected', 'failed', 'qc_failed', 'error')
          AND state_updated_at < ?
        """,
        (cutoff,),
    ).fetchall()
    for row in candidates:
        conn.execute(
            """
            UPDATE asset_pipeline_state
            SET state = 'error', state_updated_at = ?, last_error = 'stalled'
            WHERE asset_id = ?
            """,
            (ts, row["asset_id"]),
        )
    conn.commit()
    return len(candidates)


def load_config(root: Path) -> dict[str, Any]:
    config_path = (
        Path(root).expanduser().resolve() / "project_data" / "orchestrator.toml"
    )
    defaults: dict[str, Any] = {
        "enabled": False,
        "daily_candidate_target": 10,
        "top_k_for_approval": 3,
        "campaign": "",
        "creator": "",
    }
    if not config_path.exists():
        return defaults
    with config_path.open("rb") as handle:
        loaded = tomllib.load(handle)
    return defaults | loaded


def read_counts_if_present(root: Path) -> dict[str, int]:
    db_path = manifest_db_path(root)
    if not db_path.exists():
        return {}
    try:
        conn = connect_sqlite(db_path, readonly=True, wal=False)
    except sqlite3.Error:
        return {}
    with conn:
        return counts_by_state(conn)


def write_tick_report(root: Path, report: dict[str, Any]) -> Path:
    ticks_dir = (
        Path(root).expanduser().resolve() / "project_data" / "orchestrator_ticks"
    )
    ticks_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.fromtimestamp(int(report["timestamp"]), UTC).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    path = ticks_dir / f"{ts}.json"
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def notify(level: str, message: str) -> None:
    notify_path = Path.home() / ".creator-os" / "notify.sh"
    if not notify_path.exists():
        return
    subprocess.run(
        [str(notify_path), level, "orchestrator", message],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def tick(
    root: Path,
    *,
    now: int | None = None,
    notify_user: bool = True,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    ts = now_epoch() if now is None else now
    if os.environ.get("CREATOR_OS_ORCHESTRATOR_DISABLED") == "1":
        return {
            "schema": "creator_os.reel_factory.orchestrator_tick.v1",
            "timestamp": ts,
            "enabled": False,
            "disabledReason": "kill_switch",
            "stateCounts": {},
            "generation": {"started": False, "reason": "kill_switch"},
        }

    config = load_config(root)
    enabled = bool(config.get("enabled", False))
    if enabled:
        conn = open_manifest(root)
        with conn:
            recovered = recover_stalled(conn, now=ts)
            state_counts = counts_by_state(conn)
    else:
        recovered = 0
        state_counts = read_counts_if_present(root)

    report = {
        "schema": "creator_os.reel_factory.orchestrator_tick.v1",
        "timestamp": ts,
        "enabled": enabled,
        "config": {
            "daily_candidate_target": int(config.get("daily_candidate_target", 10)),
            "top_k_for_approval": int(config.get("top_k_for_approval", 3)),
            "campaign": str(config.get("campaign", "")),
            "creator": str(config.get("creator", "")),
        },
        "stateCounts": state_counts,
        "recoveredStalled": recovered,
        "generation": {
            "started": False,
            "reason": "stage_wiring_not_enabled",
        },
    }
    report_path = write_tick_report(root, report)
    report["reportPath"] = str(report_path)
    if notify_user:
        notify(
            "info" if enabled else "warn",
            f"enabled={enabled} states={state_counts} generation=not_started",
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("init", "tick"):
        command = sub.add_parser(name)
        command.add_argument(
            "--root",
            type=Path,
            default=Path(__file__).resolve().parents[1],
            help="Reel Factory root containing manifest.sqlite and project_data/",
        )
    args = parser.parse_args(argv)
    if args.cmd == "init":
        with open_manifest(args.root):
            pass
        print(json.dumps({"schema": "creator_os.reel_factory.orchestrator_init.v1"}))
        return 0
    if args.cmd == "tick":
        print(json.dumps(tick(args.root), indent=2, sort_keys=True))
        return 0
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
