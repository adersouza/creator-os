"""Reel Factory asset pipeline orchestrator state.

This module tracks where an asset is in the local creative pipeline. It does
not schedule, publish, or touch ThreadsDashboard runtime paths. Paid generation
only starts when the local dark config is explicitly enabled and cost preflight
passes.
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

from higgsfield_cost_preflight import check_higgsfield_cost_preflight
from pipeline_run import PipelineRunConfig, pipeline_run_dir, run_pipeline

try:
    from .fileops import atomic_write_text
except ImportError:  # script mode: package dir itself is on sys.path
    from fileops import atomic_write_text
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
MAX_TOTAL_ATTEMPTS = 3
DEFAULT_STALL_SECONDS = 6 * 60 * 60

# Human-paced states: assets here are waiting on an operator decision or
# parked as approved-pool replacements, not stuck. The stall sweep must
# never flush them to error (an operator sleeping 8h would otherwise wipe
# the approval inbox).
HUMAN_PACED_STATES = {"export_ready", "awaiting_approval"}


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


def maybe_create_asset(
    conn: sqlite3.Connection,
    *,
    asset_id: str,
    campaign: str,
    run_id: str,
    lineage_path: str | None = None,
    output_path: str | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    try:
        return get_asset(conn, asset_id)
    except ValueError:
        return create_asset(
            conn,
            asset_id=asset_id,
            campaign=campaign,
            run_id=run_id,
            lineage_path=lineage_path,
            output_path=output_path,
            now=now,
        )


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
    elif to_state == "planned" and from_state == "error":
        attempts += 1
        if attempts > MAX_TOTAL_ATTEMPTS:
            update_state = "failed"
            last_error = "retry_attempt_limit"
        else:
            last_error = None
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


CHAIN = (
    "planned",
    "prompted",
    "generated",
    "qc_passed",
    "ranked",
    "captioned",
    "export_ready",
    "awaiting_approval",
    "approved",
    "exported",
)


def advance_through(
    conn: sqlite3.Connection,
    asset_id: str,
    target_state: str,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    row = get_asset(conn, asset_id)
    current = str(row["state"])
    if current == target_state:
        return row
    if current not in CHAIN or target_state not in CHAIN:
        return row
    current_idx = CHAIN.index(current)
    target_idx = CHAIN.index(target_state)
    if current_idx > target_idx:
        return row
    for state in CHAIN[current_idx + 1 : target_idx + 1]:
        row = advance(conn, asset_id, state, now=now)
    return row


def update_asset_evidence(
    conn: sqlite3.Connection,
    asset_id: str,
    *,
    lineage_path: str | None = None,
    output_path: str | None = None,
    rank_score: float | None = None,
    predicted_engagement: Any = None,
) -> None:
    conn.execute(
        """
        UPDATE asset_pipeline_state
        SET lineage_path = COALESCE(?, lineage_path),
            output_path = COALESCE(?, output_path),
            rank_score = COALESCE(?, rank_score),
            predicted_engagement_json = COALESCE(?, predicted_engagement_json)
        WHERE asset_id = ?
        """,
        (
            lineage_path,
            output_path,
            rank_score,
            json.dumps(predicted_engagement, sort_keys=True)
            if predicted_engagement is not None
            else None,
            asset_id,
        ),
    )
    conn.commit()


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


def count_assets_created_since(conn: sqlite3.Connection, since: int) -> int:
    if not table_exists(conn, "asset_pipeline_state"):
        return 0
    row = conn.execute(
        "SELECT COUNT(*) FROM asset_pipeline_state WHERE created_at >= ?",
        (since,),
    ).fetchone()
    return int(row[0] or 0)


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
        WHERE state NOT IN (
            'exported', 'rejected', 'failed', 'qc_failed', 'error',
            'export_ready', 'awaiting_approval'
          )
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


def campaign_factory_db_path(root: Path) -> Path:
    env = os.environ.get("CAMPAIGN_FACTORY_DB")
    if env:
        return Path(env)
    return (
        Path(root).expanduser().resolve().parent
        / "campaign_factory"
        / "campaign_factory.sqlite"
    )


def record_rejection_evidence(
    asset: dict[str, Any],
    reason: str | None,
    db_path: Path,
    *,
    now: int | None = None,
) -> bool:
    """Persist the operator's reject decision as training signal.

    Best effort: the campaign factory DB may not exist on a fresh machine;
    the decision itself is already recorded in asset_pipeline_state.
    """
    if not db_path.exists():
        return False
    ts = now_epoch() if now is None else now
    created_at = datetime.fromtimestamp(ts, UTC).isoformat()
    asset_id = str(asset["asset_id"])
    try:
        # wal=False: this is campaign_factory's database — leave its journal
        # mode to its owner, we only append one evidence row.
        conn = connect_sqlite(db_path, wal=False)
        try:
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='asset_rejection_evidence'"
            ).fetchone()
            if not has_table:
                return False
            rendered = conn.execute(
                "SELECT 1 FROM rendered_assets WHERE id = ?", (asset_id,)
            ).fetchone()
            conn.execute(
                """
                INSERT INTO asset_rejection_evidence
                (id, rendered_asset_id, source_asset_id, campaign_id, content_surface,
                 failed_stage, failure_category, matched_text, source_field,
                 policy_version, repairable, evidence_json, created_at, updated_at)
                VALUES (?, ?, NULL, NULL, 'reel', 'human_approval',
                        'operator_rejected', ?, 'approval_reason', 'inbox.v1', 0, ?, ?, ?)
                ON CONFLICT(rendered_asset_id, failed_stage, failure_category,
                            matched_text, source_field, policy_version)
                DO UPDATE SET evidence_json = excluded.evidence_json,
                              updated_at = excluded.updated_at
                """,
                (
                    f"rejectev-inbox-{asset_id}-{ts}",
                    asset_id if rendered else None,
                    reason or "",
                    json.dumps(
                        {
                            "assetId": asset_id,
                            "campaign": asset.get("campaign"),
                            "runId": asset.get("run_id"),
                            "lineagePath": asset.get("lineage_path"),
                            "rankScore": asset.get("rank_score"),
                            "reason": reason or "",
                        },
                        sort_keys=True,
                    ),
                    created_at,
                    created_at,
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False


APPROVAL_DECISIONS = {"approved", "rejected", "regenerate"}


def decide(
    root: Path,
    asset_id: str,
    decision: str,
    *,
    reason: str | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    if decision not in APPROVAL_DECISIONS:
        raise ValueError(f"unknown decision: {decision}")
    conn = open_manifest(Path(root))
    try:
        asset = advance(conn, asset_id, decision, reason=reason, now=now)
    finally:
        conn.close()
    evidence_recorded = False
    if decision == "rejected":
        evidence_recorded = record_rejection_evidence(
            asset, reason, campaign_factory_db_path(Path(root)), now=now
        )
    return {
        "schema": "creator_os.reel_factory.orchestrator_decision.v1",
        "asset": asset,
        "decision": decision,
        "rejectionEvidenceRecorded": evidence_recorded,
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_config_path(root: Path, value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else root / path


def _qc_state_from_lineage(lineage: dict[str, Any] | None) -> str | None:
    if not isinstance(lineage, dict):
        return None
    generation = (
        lineage.get("generation") if isinstance(lineage.get("generation"), dict) else {}
    )
    status = str(generation.get("status") or "").lower()
    if "qc_rejected" in status or "reject" in status or "fail" in status:
        return "qc_failed"
    review = lineage.get("review") if isinstance(lineage.get("review"), dict) else {}
    qc_blocks = [
        review.get("generatedImageQc"),
        review.get("generatedVideoQc"),
    ]
    if any(isinstance(qc, dict) and qc.get("status") == "failed" for qc in qc_blocks):
        return "qc_failed"
    if any(isinstance(qc, dict) and qc.get("status") == "passed" for qc in qc_blocks):
        return "qc_passed"
    return None


def _rank_stem(row: dict[str, Any]) -> str:
    lineage = row.get("generated_asset_lineage")
    if isinstance(lineage, dict):
        source = (
            lineage.get("source") if isinstance(lineage.get("source"), dict) else {}
        )
        stem = str(source.get("stem") or "")
        if stem:
            return stem
    return Path(str(row.get("output_path") or "")).stem


def _ranked_for_stem(state: dict[str, Any], stem: str) -> dict[str, Any] | None:
    rows = ((state.get("stages") or {}).get("rank") or {}).get("ranked") or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _rank_stem(row) == stem or stem in str(row.get("output_path") or ""):
            return row
    return None


def ingest_pipeline_state(
    conn: sqlite3.Connection,
    state: dict[str, Any],
    *,
    now: int | None = None,
) -> int:
    campaign = str(state.get("campaign") or "")
    run_id = str(state.get("run_id") or "")
    jobs = (((state.get("stages") or {}).get("assets") or {}).get("jobs")) or []
    changed = 0
    for job in jobs:
        if not isinstance(job, dict) or not job.get("stem"):
            continue
        stem = str(job["stem"])
        lineage_path = str(job.get("lineage_path") or "")
        maybe_create_asset(
            conn,
            asset_id=stem,
            campaign=campaign,
            run_id=run_id,
            lineage_path=lineage_path or None,
            now=now,
        )
        if lineage_path and Path(lineage_path).exists():
            advance_through(conn, stem, "generated", now=now)
            lineage = _read_json(Path(lineage_path))
            qc_state = _qc_state_from_lineage(lineage)
            if qc_state == "qc_failed":
                advance(conn, stem, "qc_failed", reason="generated_qc_failed", now=now)
                changed += 1
                continue
            if qc_state == "qc_passed":
                advance_through(conn, stem, "qc_passed", now=now)
        ranked = _ranked_for_stem(state, stem)
        if ranked:
            output_path = str(ranked.get("output_path") or "")
            score = ranked.get("score")
            update_asset_evidence(
                conn,
                stem,
                lineage_path=lineage_path or None,
                output_path=output_path or None,
                rank_score=float(score) if isinstance(score, (int, float)) else None,
                predicted_engagement=ranked.get("predictedEngagement"),
            )
            advance_through(conn, stem, "ranked", now=now)
            if output_path and Path(output_path).exists():
                advance_through(conn, stem, "export_ready", now=now)
        changed += 1
    return changed


def ingest_pipeline_runs(root: Path, *, now: int | None = None) -> int:
    runs_dir = root / "project_data" / "pipeline_runs"
    if not runs_dir.exists():
        return 0
    conn = open_manifest(root)
    try:
        count = 0
        for state_path in sorted(runs_dir.glob("*/*/pipeline_run.json")):
            state = _read_json(state_path)
            if state:
                count += ingest_pipeline_state(conn, state, now=now)
        return count
    finally:
        conn.close()


def promote_top_k(
    conn: sqlite3.Connection,
    *,
    campaign: str,
    top_k: int,
    now: int | None = None,
) -> int:
    if top_k <= 0:
        return 0
    waiting = conn.execute(
        """
        SELECT COUNT(*) FROM asset_pipeline_state
        WHERE campaign = ? AND state = 'awaiting_approval'
        """,
        (campaign,),
    ).fetchone()
    slots = max(0, top_k - int(waiting[0] or 0))
    if slots <= 0:
        return 0
    rows = conn.execute(
        """
        SELECT asset_id FROM asset_pipeline_state
        WHERE campaign = ? AND state = 'export_ready'
        ORDER BY rank_score IS NULL, rank_score DESC, state_updated_at ASC
        LIMIT ?
        """,
        (campaign, slots),
    ).fetchall()
    for row in rows:
        advance(conn, str(row["asset_id"]), "awaiting_approval", now=now)
    return len(rows)


def export_approved_assets(root: Path, *, now: int | None = None) -> int:
    ts = now_epoch() if now is None else now
    conn = open_manifest(root)
    try:
        rows = conn.execute(
            """
            SELECT * FROM asset_pipeline_state
            WHERE state = 'approved' AND output_path IS NOT NULL
            ORDER BY approved_at, asset_id
            """
        ).fetchall()
        if not rows:
            return 0
        export_dir = root / "project_data" / "orchestrator_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "reel_factory.approved_export.v1",
            "exported_at": ts,
            "source": "orchestrator",
            "count": len(rows),
            "items": [],
        }
        for idx, row in enumerate(rows):
            lineage = (
                _read_json(Path(row["lineage_path"])) if row["lineage_path"] else {}
            )
            predicted = json.loads(row["predicted_engagement_json"] or "null")
            payload["items"].append(
                {
                    "index": idx,
                    "output_path": row["output_path"],
                    "review_state": "operator_approved",
                    "generated_asset_lineage": lineage or {},
                    "pipeline_rank": {
                        "score": row["rank_score"],
                        "predictedEngagement": predicted,
                    },
                }
            )
        path = export_dir / (
            datetime.fromtimestamp(ts, UTC).strftime("%Y%m%dT%H%M%SZ")
            + ".approved_export.json"
        )
        atomic_write_text(
            path, json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        for row in rows:
            advance(conn, str(row["asset_id"]), "exported", now=ts)
        return len(rows)
    finally:
        conn.close()


def load_config(root: Path) -> dict[str, Any]:
    config_path = (
        Path(root).expanduser().resolve() / "project_data" / "orchestrator.toml"
    )
    defaults: dict[str, Any] = {
        "enabled": False,
        "paid_generation_enabled": False,
        "daily_candidate_target": 10,
        "top_k_for_approval": 3,
        "campaign": "",
        "creator": "",
        "caption_mix": "",
        "reference_image": "",
        "reference_reel": "",
        "estimated_cost_per_asset_usd": None,
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


def operator_status(root: Path) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    config = load_config(root)
    return {
        "schema": "creator_os.reel_factory.operator_status.v1",
        "root": str(root),
        "enabled": bool(config.get("enabled", False)),
        "paidGenerationEnabled": bool(config.get("paid_generation_enabled", False)),
        "campaign": str(config.get("campaign") or ""),
        "creator": str(config.get("creator") or ""),
        "dailyCandidateTarget": int(config.get("daily_candidate_target", 10)),
        "topKForApproval": int(config.get("top_k_for_approval", 3)),
        "estimatedCostPerAssetUsd": config.get("estimated_cost_per_asset_usd"),
        "stateCounts": read_counts_if_present(root),
    }


def operator_inbox(root: Path, *, limit: int = 100) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    db_path = manifest_db_path(root)
    if not db_path.exists():
        return {
            "schema": "creator_os.reel_factory.operator_inbox.v1",
            "root": str(root),
            "available": False,
            "items": [],
        }
    safe_limit = max(1, min(int(limit), 500))
    conn = connect_sqlite(db_path, readonly=True, wal=False)
    try:
        rows = conn.execute(
            """
            SELECT * FROM asset_pipeline_state
            WHERE state = 'awaiting_approval'
            ORDER BY rank_score IS NULL, rank_score DESC, state_updated_at ASC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["predicted_engagement"] = json.loads(
                item.pop("predicted_engagement_json") or "null"
            )
            items.append(item)
        return {
            "schema": "creator_os.reel_factory.operator_inbox.v1",
            "root": str(root),
            "available": True,
            "count": len(items),
            "items": items,
        }
    finally:
        conn.close()


def write_tick_report(root: Path, report: dict[str, Any]) -> Path:
    ticks_dir = (
        Path(root).expanduser().resolve() / "project_data" / "orchestrator_ticks"
    )
    ticks_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.fromtimestamp(int(report["timestamp"]), UTC).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    path = ticks_dir / f"{ts}.json"
    atomic_write_text(
        path, json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
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
    allow_paid_generation: bool = False,
    max_total_cost_usd: float | None = None,
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
    generation: dict[str, Any] = {"started": False, "reason": "disabled"}
    ingested = 0
    promoted = 0
    exported = 0
    if enabled:
        conn = open_manifest(root)
        try:
            recovered = recover_stalled(conn, now=ts)
            start_of_day = int(
                datetime.fromtimestamp(ts, UTC)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .timestamp()
            )
            target = int(config.get("daily_candidate_target", 10))
            shortfall = max(0, target - count_assets_created_since(conn, start_of_day))
        finally:
            conn.close()

        estimate = config.get("estimated_cost_per_asset_usd")
        reference_image = _resolve_config_path(root, config.get("reference_image"))
        reference_reel = _resolve_config_path(root, config.get("reference_reel"))
        paid_generation_enabled = bool(config.get("paid_generation_enabled", False))
        if shortfall <= 0:
            generation = {"started": False, "reason": "daily_target_met"}
        elif not paid_generation_enabled:
            generation = {"started": False, "reason": "paid_generation_disabled"}
        elif not allow_paid_generation:
            generation = {
                "started": False,
                "reason": "paid_generation_cli_gate_missing",
            }
        elif max_total_cost_usd is None or max_total_cost_usd <= 0:
            generation = {"started": False, "reason": "maximum_total_cost_missing"}
        elif not config.get("campaign") or not config.get("creator"):
            generation = {"started": False, "reason": "campaign_or_creator_missing"}
        elif not reference_image and not reference_reel:
            generation = {"started": False, "reason": "reference_missing"}
        elif estimate is None:
            preflight = check_higgsfield_cost_preflight(
                asset_count=shortfall,
                estimated_cost_usd=None,
                root=root,
                cost_db_path=campaign_factory_db_path(root),
            )
            generation = {
                "started": False,
                "reason": "cost_estimate_missing",
                "preflight": preflight,
            }
        else:
            total_estimate = float(estimate) * shortfall
            if total_estimate > float(max_total_cost_usd):
                generation = {
                    "started": False,
                    "reason": "maximum_total_cost_exceeded",
                    "estimatedTotalCostUsd": total_estimate,
                    "maximumTotalCostUsd": float(max_total_cost_usd),
                }
            else:
                preflight = check_higgsfield_cost_preflight(
                    asset_count=shortfall,
                    estimated_cost_usd=total_estimate,
                    root=root,
                    cost_db_path=campaign_factory_db_path(root),
                )
            if generation.get("reason") == "maximum_total_cost_exceeded":
                pass
            elif preflight.get("allowed"):
                run_id = datetime.fromtimestamp(ts, UTC).strftime(
                    "orchestrator_%Y%m%d_%H%M%S"
                )
                state = run_pipeline(
                    PipelineRunConfig(
                        root=root,
                        campaign=str(config.get("campaign") or ""),
                        creator=str(config.get("creator") or ""),
                        count=shortfall,
                        run_id=run_id,
                        reference_image=reference_image,
                        reference_reel=reference_reel,
                        caption_mix=str(config.get("caption_mix") or "") or None,
                        execute_commands=True,
                        allow_paid_generation=True,
                        download_assets=True,
                        estimated_cost_per_asset_usd=float(estimate),
                    )
                )
                generation = {
                    "started": True,
                    "runId": run_id,
                    "count": shortfall,
                    "statePath": str(
                        pipeline_run_dir(
                            root, str(config.get("campaign") or ""), run_id
                        )
                        / "pipeline_run.json"
                    ),
                    "preflight": preflight,
                    "stageStatuses": {
                        key: value.get("status")
                        for key, value in (state.get("stages") or {}).items()
                        if isinstance(value, dict)
                    },
                }
            else:
                generation = {
                    "started": False,
                    "reason": preflight.get("blockingReason")
                    or "cost_preflight_blocked",
                    "preflight": preflight,
                }

        ingested = ingest_pipeline_runs(root, now=ts)
        conn = open_manifest(root)
        try:
            promoted = promote_top_k(
                conn,
                campaign=str(config.get("campaign") or ""),
                top_k=int(config.get("top_k_for_approval", 3)),
                now=ts,
            )
            state_counts = counts_by_state(conn)
        finally:
            conn.close()
        exported = export_approved_assets(root, now=ts)
        state_counts = read_counts_if_present(root)
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
            "paid_generation_enabled": bool(
                config.get("paid_generation_enabled", False)
            ),
        },
        "stateCounts": state_counts,
        "recoveredStalled": recovered,
        "ingested": ingested,
        "promotedToApproval": promoted,
        "exportedApproved": exported,
        "generation": generation,
    }
    report_path = write_tick_report(root, report)
    report["reportPath"] = str(report_path)
    if notify_user:
        notify(
            "info" if enabled else "warn",
            "enabled="
            f"{enabled} states={state_counts} "
            f"generation={generation.get('reason') or generation.get('started')}",
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("init", "tick", "status", "inbox", "decide"):
        command = sub.add_parser(name)
        command.add_argument(
            "--root",
            type=Path,
            default=Path(__file__).resolve().parents[1],
            help="Reel Factory root containing manifest.sqlite and project_data/",
        )
        if name == "decide":
            command.add_argument("--asset-id", required=True)
            command.add_argument(
                "--decision", required=True, choices=sorted(APPROVAL_DECISIONS)
            )
            command.add_argument("--reason", default=None)
        if name == "inbox":
            command.add_argument("--limit", type=int, default=100)
        if name == "tick":
            command.add_argument("--allow-paid-generation", action="store_true")
            command.add_argument("--max-total-cost-usd", type=float)
    args = parser.parse_args(argv)
    if args.cmd == "init":
        with open_manifest(args.root):
            pass
        print(json.dumps({"schema": "creator_os.reel_factory.orchestrator_init.v1"}))
        return 0
    if args.cmd == "tick":
        print(
            json.dumps(
                tick(
                    args.root,
                    allow_paid_generation=args.allow_paid_generation,
                    max_total_cost_usd=args.max_total_cost_usd,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.cmd == "status":
        print(json.dumps(operator_status(args.root), indent=2, sort_keys=True))
        return 0
    if args.cmd == "inbox":
        print(
            json.dumps(
                operator_inbox(args.root, limit=args.limit), indent=2, sort_keys=True
            )
        )
        return 0
    if args.cmd == "decide":
        try:
            result = decide(args.root, args.asset_id, args.decision, reason=args.reason)
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}))
            return 2
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
