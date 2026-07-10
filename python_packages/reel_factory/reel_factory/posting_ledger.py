"""Account Posting Ledger for campaign/account scheduling.

The ledger is the bridge between Reel Factory generated outputs and the
operator-controlled scheduling workflow. It intentionally does not publish to
social platforms.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from audio_intent import read_audio_intent
from intelligence_store import winner_score

from pipeline_contracts import validate_assignment_eligibility
from reel_factory.sqlite_utils import connect_sqlite

from .fileops import atomic_write_text

SLOT_TYPES = ("main", "trial_1", "trial_2")
POST_STATUSES = (
    "planned",
    "ready_for_review",
    "approved",
    "scheduled",
    "posted",
    "metrics_imported",
    "skipped",
    "failed",
)
TERMINAL_STATUSES = {"metrics_imported", "skipped", "failed"}
DEFAULT_SLOT_TIMES = {"main": "10:00", "trial_1": "15:00", "trial_2": "20:00"}
DEFAULT_TIMEZONE = "America/New_York"
SCHEMA = "campaign_factory.account_posting_ledger.v1"
DEFAULT_CROSS_ACCOUNT_REUSE_WINDOW_DAYS = 14


def ensure_posting_ledger_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS posting_slots (
        posting_slot_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        account_handle TEXT NOT NULL,
        platform TEXT NOT NULL DEFAULT 'ig',
        campaign_id TEXT,
        creator TEXT,
        soul_name TEXT,
        soul_id TEXT,
        accepted_soul_ids_json TEXT NOT NULL DEFAULT '[]',
        date TEXT NOT NULL,
        slot_type TEXT NOT NULL,
        planned_slot_time TEXT NOT NULL,
        timezone TEXT NOT NULL DEFAULT 'America/New_York',
        planned_at TEXT,
        source_reference_id TEXT,
        source_reference_path TEXT,
        source_family_id TEXT,
        reel_factory_asset_id TEXT,
        source_kling_video_path TEXT,
        rendered_output_path TEXT,
        content_fingerprint TEXT,
        perceptual_fingerprint TEXT,
        perceptual_cluster_id TEXT,
        account_group_id TEXT,
        origin_account_id TEXT,
        reuse_cooldown_days INTEGER NOT NULL DEFAULT 14,
        caption TEXT,
        caption_variant_id TEXT,
        audio_track_id TEXT,
        audio_source TEXT,
        audio_selected_reason TEXT,
        manual_audio_needed INTEGER NOT NULL DEFAULT 0,
        prompt_mode TEXT,
        higgsfield_job_id TEXT,
        kling_job_id TEXT,
        crop_panel_id TEXT,
        lineage_path TEXT,
        lineage_json TEXT NOT NULL DEFAULT '{}',
        review_status TEXT NOT NULL DEFAULT 'pending',
        approved_by TEXT,
        scheduled_at TEXT,
        posted_at TEXT,
        post_url TEXT,
        post_status TEXT NOT NULL DEFAULT 'planned'
            CHECK(post_status IN ('planned', 'ready_for_review', 'approved', 'scheduled', 'posted', 'metrics_imported', 'skipped', 'failed')),
        metrics_imported INTEGER NOT NULL DEFAULT 0,
        views INTEGER,
        likes INTEGER,
        comments INTEGER,
        shares INTEGER,
        saves INTEGER,
        retention REAL,
        winner_score REAL,
        notes TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        UNIQUE(account_id, date, slot_type)
    );
    CREATE TABLE IF NOT EXISTS posting_slot_events (
        event_id TEXT PRIMARY KEY,
        posting_slot_id TEXT NOT NULL,
        from_status TEXT,
        to_status TEXT NOT NULL,
        actor TEXT,
        notes TEXT,
        changes_json TEXT NOT NULL DEFAULT '{}',
        created_at INTEGER NOT NULL,
        FOREIGN KEY(posting_slot_id) REFERENCES posting_slots(posting_slot_id)
    );
    CREATE INDEX IF NOT EXISTS idx_posting_slots_campaign ON posting_slots(campaign_id, date, account_id);
    CREATE INDEX IF NOT EXISTS idx_posting_slots_status ON posting_slots(post_status, review_status);
    CREATE INDEX IF NOT EXISTS idx_posting_slots_fingerprint ON posting_slots(account_id, content_fingerprint);
    CREATE INDEX IF NOT EXISTS idx_posting_slots_rendered_output ON posting_slots(rendered_output_path);
    CREATE INDEX IF NOT EXISTS idx_posting_slots_content_fingerprint ON posting_slots(content_fingerprint);
    CREATE INDEX IF NOT EXISTS idx_posting_slots_cluster ON posting_slots(campaign_id, perceptual_cluster_id, date);
    CREATE INDEX IF NOT EXISTS idx_posting_slots_source_family ON posting_slots(campaign_id, source_family_id, date);
    CREATE INDEX IF NOT EXISTS idx_posting_slots_source ON posting_slots(account_id, source_reference_id, date);
    CREATE INDEX IF NOT EXISTS idx_posting_events_slot ON posting_slot_events(posting_slot_id, created_at);
    """)
    _ensure_posting_columns(conn)
    conn.commit()


def _ensure_posting_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(posting_slots)").fetchall()
    }
    columns = {
        "source_family_id": "TEXT",
        "perceptual_fingerprint": "TEXT",
        "perceptual_cluster_id": "TEXT",
        "account_group_id": "TEXT",
        "origin_account_id": "TEXT",
        "reuse_cooldown_days": "INTEGER NOT NULL DEFAULT 14",
        "soul_id": "TEXT",
        "accepted_soul_ids_json": "TEXT NOT NULL DEFAULT '[]'",
        "timezone": "TEXT NOT NULL DEFAULT 'America/New_York'",
        "planned_at": "TEXT",
    }
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE posting_slots ADD COLUMN {name} {ddl}")


def connect(root: Path) -> sqlite3.Connection:
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    conn = connect_sqlite(root / "manifest.sqlite")
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_posting_ledger_schema(conn)
    return conn


def content_fingerprint(path: Path) -> str:
    path = Path(path).resolve()
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def account_id_for(handle: str) -> str:
    return _slug(handle)


def _account_slot_plan(
    account: str | dict[str, Any], slot_times: dict[str, str]
) -> list[tuple[str, str]]:
    max_per_day = (
        int(account.get("max_per_day") or account.get("maxPerDay") or len(SLOT_TYPES))
        if isinstance(account, dict)
        else len(SLOT_TYPES)
    )
    max_per_day = max(1, max_per_day)
    if max_per_day <= len(SLOT_TYPES):
        return [
            (slot_type, slot_times[slot_type]) for slot_type in SLOT_TYPES[:max_per_day]
        ]
    gap_hours = (
        int(account.get("min_gap_hours") or account.get("minGapHours") or 1)
        if isinstance(account, dict)
        else 1
    )
    gap_hours = max(1, gap_hours)
    start_hour, start_minute = (int(part) for part in slot_times["main"].split(":", 1))
    start_minutes = start_hour * 60 + start_minute
    slots = []
    for index in range(max_per_day):
        slot_type = "main" if index == 0 else f"trial_{index}"
        minutes = (start_minutes + index * gap_hours * 60) % (24 * 60)
        slots.append((slot_type, f"{minutes // 60:02d}:{minutes % 60:02d}"))
    return slots


def _account_timezone(account: str | dict[str, Any]) -> str:
    tz = (
        account.get("timezone") or account.get("timeZone")
        if isinstance(account, dict)
        else None
    )
    tz = str(tz or DEFAULT_TIMEZONE)
    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown account timezone: {tz}") from exc
    return tz


def _planned_at(slot_date: str, planned_slot_time: str, timezone: str) -> str:
    hour, minute = (int(part) for part in planned_slot_time.split(":", 1))
    local = datetime.fromisoformat(slot_date).replace(
        hour=hour, minute=minute, tzinfo=ZoneInfo(timezone)
    )
    return local.isoformat()


def create_posting_plan(
    root: Path,
    *,
    creator: str,
    campaign_id: str,
    accounts: list[str | dict[str, Any]],
    start_date: str,
    days: int = 7,
    platform: str = "ig",
    slot_times: dict[str, str] | None = None,
    soul_id: str | None = None,
    accepted_soul_ids: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    slot_times = {**DEFAULT_SLOT_TIMES, **(slot_times or {})}
    start = date.fromisoformat(start_date)
    planned: list[dict[str, Any]] = []
    conn = connect(root)
    created = 0
    existing = 0
    now = int(time.time())
    creator_defaults = _creator_identity_defaults(conn, creator, campaign_id)
    plan_soul_id = _first_text(soul_id)
    plan_accepted = _text_list(accepted_soul_ids)
    for account in accounts:
        handle = str(
            account.get("handle") if isinstance(account, dict) else account
        ).lstrip("@")
        account_id = str(
            account.get("account_id")
            if isinstance(account, dict) and account.get("account_id")
            else account_id_for(handle)
        )
        account_soul_id = _first_text(
            account.get("soul_id") or account.get("soulId")
            if isinstance(account, dict)
            else None
        )
        account_accepted = _text_list(
            account.get("accepted_soul_ids") or account.get("acceptedSoulIds")
            if isinstance(account, dict)
            else None
        )
        final_soul_id = (
            account_soul_id
            or plan_soul_id
            or (account_accepted[0] if account_accepted else None)
            or (plan_accepted[0] if plan_accepted else None)
            or creator_defaults["soul_id"]
        )
        final_accepted = _dedupe_texts(
            account_accepted
            or plan_accepted
            or creator_defaults["accepted_soul_ids"]
            or ([final_soul_id] if final_soul_id else [])
        )
        if final_soul_id and final_soul_id not in final_accepted:
            final_accepted.insert(0, final_soul_id)
        account_slots = _account_slot_plan(account, slot_times)
        account_timezone = _account_timezone(account)
        for day_offset in range(days):
            slot_date = (start + timedelta(days=day_offset)).isoformat()
            for slot_type, planned_slot_time in account_slots:
                slot_id = _slot_id(account_id, slot_date, slot_type)
                row = {
                    "posting_slot_id": slot_id,
                    "account_id": account_id,
                    "account_handle": handle,
                    "platform": platform,
                    "campaign_id": campaign_id,
                    "creator": creator,
                    "soul_name": creator,
                    "soul_id": final_soul_id,
                    "accepted_soul_ids_json": json.dumps(final_accepted),
                    "date": slot_date,
                    "slot_type": slot_type,
                    "planned_slot_time": planned_slot_time,
                    "timezone": account_timezone,
                    "planned_at": _planned_at(
                        slot_date, planned_slot_time, account_timezone
                    ),
                    "post_status": "planned",
                    "review_status": "pending",
                    "created_at": now,
                    "updated_at": now,
                }
                planned.append(row)
                if dry_run:
                    continue
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO posting_slots (
                        posting_slot_id, account_id, account_handle, platform, campaign_id,
                        creator, soul_name, soul_id, accepted_soul_ids_json, date,
                        slot_type, planned_slot_time, timezone, planned_at, post_status, review_status,
                        created_at, updated_at
                    ) VALUES (
                        :posting_slot_id, :account_id, :account_handle, :platform, :campaign_id,
                        :creator, :soul_name, :soul_id, :accepted_soul_ids_json, :date,
                        :slot_type, :planned_slot_time, :timezone, :planned_at, :post_status, :review_status,
                        :created_at, :updated_at
                    )
                    """,
                    row,
                )
                if cur.rowcount:
                    created += 1
                    _record_event(
                        conn,
                        slot_id,
                        None,
                        "planned",
                        actor="ledger",
                        notes="slot planned",
                    )
                else:
                    existing += 1
    if not dry_run:
        conn.commit()
    return {
        "ok": True,
        "schema": SCHEMA,
        "created": created,
        "existing": existing,
        "slot_count": len(planned),
        "slots": planned,
    }


def assign_approved_reels(
    root: Path,
    *,
    campaign_id: str,
    approved_export: Path,
    dry_run: bool = False,
    source_reuse_window_days: int = DEFAULT_CROSS_ACCOUNT_REUSE_WINDOW_DAYS,
    eligibility_artifact: Path | None = None,
) -> dict[str, Any]:
    conn = connect(root)
    payload = json.loads(Path(approved_export).read_text(encoding="utf-8"))
    items = payload.get("items") or []
    artifact_decisions = _load_eligibility_decisions(eligibility_artifact)
    slots = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM posting_slots
            WHERE campaign_id=? AND post_status='planned'
            ORDER BY date, planned_slot_time, account_id, slot_type
            """,
            (campaign_id,),
        ).fetchall()
    ]
    assigned: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    available_slots = list(slots)
    now = int(time.time())
    for item in items:
        output_path = Path(
            str(item.get("output_path") or item.get("rendered_output_path") or "")
        ).expanduser()
        if not output_path.exists():
            conflicts.append(
                {
                    "output_path": str(output_path),
                    "reasons": ["rendered_output_missing"],
                }
            )
            continue
        item_lineage = (
            item.get("generated_asset_lineage")
            if isinstance(item.get("generated_asset_lineage"), dict)
            else {}
        )
        lineage_path = _find_lineage_path(output_path)
        if not lineage_path and not item_lineage:
            conflicts.append(
                {"output_path": str(output_path), "reasons": ["missing_lineage"]}
            )
            continue
        if not item_lineage and lineage_path:
            item_lineage = _json_object(lineage_path.read_text(encoding="utf-8"))
        if not available_slots:
            conflicts.append(
                {
                    "output_path": str(output_path.resolve()),
                    "reasons": ["no_available_planned_slot"],
                }
            )
            continue
        identity_reason = _creator_identity_conflict(
            conn, item=item, lineage=item_lineage, slot=available_slots[0]
        )
        if identity_reason:
            conflicts.append(
                {
                    "posting_slot_id": available_slots[0]["posting_slot_id"],
                    "account_handle": available_slots[0]["account_handle"],
                    "output_path": str(output_path.resolve()),
                    "reasons": [identity_reason],
                }
            )
            continue
        fp = str(
            _lineage_value(item_lineage, "contentFingerprint", "content_fingerprint")
            or item.get("content_fingerprint")
            or content_fingerprint(output_path)
        ).strip()
        item_lineage["contentFingerprint"] = fp
        exported_fp = str(item.get("content_fingerprint") or "").strip()
        if exported_fp and exported_fp != fp:
            conflicts.append(
                {
                    "output_path": str(output_path.resolve()),
                    "content_fingerprint": fp,
                    "reasons": ["lineage_content_fingerprint_mismatch"],
                }
            )
            continue
        candidate_uniqueness = _uniqueness_values(
            item, lineage=item_lineage, fingerprint=fp
        )
        slot_result: tuple[dict[str, Any], list[str]] | None = None
        conflict_accounts_seen: set[str] = set()
        terminal_conflict = False
        assigned_slot_index: int | None = None
        for idx, slot in enumerate(available_slots):
            reasons = _assignment_conflicts(
                conn,
                slot=slot,
                output_path=str(output_path.resolve()),
                fingerprint=fp,
                lineage=item_lineage,
                uniqueness=candidate_uniqueness,
                source_reuse_window_days=source_reuse_window_days,
                include_policy_rules=not artifact_decisions,
            )
            artifact_reason = _artifact_assignment_conflict(
                artifact_decisions,
                slot=slot,
                fingerprint=fp,
            )
            if artifact_reason:
                reasons.append(artifact_reason)
            if not reasons:
                slot_result = (slot, reasons)
                assigned_slot_index = idx
                break
            if "duplicate_content_fingerprint_for_campaign" in reasons:
                conflicts.append(
                    {
                        "posting_slot_id": slot["posting_slot_id"],
                        "account_handle": slot["account_handle"],
                        "output_path": str(output_path.resolve()),
                        "content_fingerprint": fp,
                        "reasons": reasons,
                    }
                )
                terminal_conflict = True
                break
            if slot["account_id"] not in conflict_accounts_seen:
                conflicts.append(
                    {
                        "posting_slot_id": slot["posting_slot_id"],
                        "account_handle": slot["account_handle"],
                        "output_path": str(output_path.resolve()),
                        "content_fingerprint": fp,
                        "reasons": reasons,
                    }
                )
                conflict_accounts_seen.add(slot["account_id"])
        if assigned_slot_index is not None:
            available_slots.pop(assigned_slot_index)
        if not slot_result:
            if (
                not available_slots
                and not conflict_accounts_seen
                and not terminal_conflict
            ):
                conflicts.append(
                    {
                        "output_path": str(output_path.resolve()),
                        "reasons": ["no_available_planned_slot"],
                    }
                )
            continue
        slot, _ = slot_result
        values = _assignment_values(
            item,
            output_path=output_path,
            lineage=item_lineage,
            lineage_path=lineage_path,
            fingerprint=fp,
            reuse_cooldown_days=source_reuse_window_days,
        )
        values.update(
            {
                "posting_slot_id": slot["posting_slot_id"],
                "origin_account_id": str(
                    _lineage_value(item_lineage, "originAccountId", "origin_account_id")
                    or slot["account_id"]
                ),
                "post_status": "ready_for_review",
                "review_status": "pending",
                "updated_at": now,
            }
        )
        assigned.append({"posting_slot_id": slot["posting_slot_id"], **values})
        if dry_run:
            continue
        conn.execute(
            """
            UPDATE posting_slots SET
                source_reference_id=:source_reference_id,
                source_reference_path=:source_reference_path,
                source_family_id=:source_family_id,
                reel_factory_asset_id=:reel_factory_asset_id,
                source_kling_video_path=:source_kling_video_path,
                rendered_output_path=:rendered_output_path,
                content_fingerprint=:content_fingerprint,
                perceptual_fingerprint=:perceptual_fingerprint,
                perceptual_cluster_id=:perceptual_cluster_id,
                account_group_id=:account_group_id,
                origin_account_id=:origin_account_id,
                reuse_cooldown_days=:reuse_cooldown_days,
                caption=:caption,
                caption_variant_id=:caption_variant_id,
                audio_track_id=:audio_track_id,
                audio_source=:audio_source,
                audio_selected_reason=:audio_selected_reason,
                manual_audio_needed=:manual_audio_needed,
                prompt_mode=:prompt_mode,
                higgsfield_job_id=:higgsfield_job_id,
                kling_job_id=:kling_job_id,
                crop_panel_id=:crop_panel_id,
                lineage_path=:lineage_path,
                lineage_json=:lineage_json,
                post_status=:post_status,
                review_status=:review_status,
                updated_at=:updated_at
            WHERE posting_slot_id=:posting_slot_id
            """,
            values,
        )
        _record_event(
            conn,
            slot["posting_slot_id"],
            slot["post_status"],
            "ready_for_review",
            actor="ledger",
            notes="approved reel assigned",
            changes=values,
        )
    if not dry_run:
        conn.commit()
    return {
        "ok": True,
        "assigned": len(assigned),
        "assignments": assigned,
        "conflicts": conflicts,
    }


def transition_slot(
    root: Path,
    posting_slot_id: str,
    to_status: str,
    *,
    actor: str = "",
    notes: str = "",
    approved_by: str | None = None,
    scheduled_at: str | None = None,
    posted_at: str | None = None,
    post_url: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if to_status not in POST_STATUSES:
        raise ValueError(f"post_status must be one of {POST_STATUSES}")
    conn = connect(root)
    row = conn.execute(
        "SELECT * FROM posting_slots WHERE posting_slot_id=?", (posting_slot_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"unknown posting slot: {posting_slot_id}")
    current = row["post_status"]
    if current in TERMINAL_STATUSES and to_status != current:
        raise ValueError(f"slot is terminal: {current}")
    _validate_transition(dict(row), to_status)
    updates: dict[str, Any] = {"post_status": to_status, "updated_at": int(time.time())}
    if to_status == "approved":
        updates["review_status"] = "approved"
        updates["approved_by"] = approved_by or actor or row["approved_by"]
    elif to_status == "skipped":
        updates["review_status"] = "skipped"
    elif to_status == "failed":
        updates["review_status"] = "failed"
    if scheduled_at:
        updates["scheduled_at"] = scheduled_at
    if posted_at:
        updates["posted_at"] = posted_at
    if post_url:
        updates["post_url"] = post_url
    if to_status == "metrics_imported":
        updates["metrics_imported"] = 1
        metric_values = metrics or {}
        for key in ("views", "likes", "comments", "shares", "saves", "retention"):
            if key in metric_values:
                updates[key] = metric_values[key]
        updates["winner_score"] = winner_score(metric_values)
    assignments = ", ".join(f"{key}=?" for key in updates)
    conn.execute(
        f"UPDATE posting_slots SET {assignments} WHERE posting_slot_id=?",
        [*updates.values(), posting_slot_id],
    )
    _record_event(
        conn,
        posting_slot_id,
        current,
        to_status,
        actor=actor,
        notes=notes,
        changes=updates,
    )
    conn.commit()
    return {
        "ok": True,
        "posting_slot_id": posting_slot_id,
        "from_status": current,
        "to_status": to_status,
    }


def review_queue(root: Path, *, campaign_id: str | None = None) -> dict[str, Any]:
    conn = connect(root)
    where = "WHERE post_status IN ('ready_for_review', 'approved')"
    params: list[Any] = []
    if campaign_id:
        where += " AND campaign_id=?"
        params.append(campaign_id)
    rows = conn.execute(
        f"""
        SELECT posting_slot_id, account_id, account_handle, campaign_id, creator,
            soul_name, soul_id, accepted_soul_ids_json, date, slot_type,
            planned_slot_time, timezone, planned_at, rendered_output_path, content_fingerprint, caption,
            audio_track_id, audio_source, audio_selected_reason, manual_audio_needed,
            lineage_path, review_status, post_status
        FROM posting_slots
        {where}
        ORDER BY date, planned_slot_time, account_handle
        """,
        params,
    ).fetchall()
    items = []
    for row in rows:
        data = dict(row)
        data["accepted_soul_ids"] = _json_text_list(data.pop("accepted_soul_ids_json"))
        data["audio_intent"] = _audio_state(data)
        data["actions"] = ["approve", "reject", "skip"]
        items.append(data)
    conflict_summary = ledger_conflicts(root, campaign_id=campaign_id)
    return {
        "ok": True,
        "schema": SCHEMA,
        "count": len(items),
        "assignmentBlockedCount": conflict_summary["count"],
        "items": items,
    }


def ledger_conflicts(
    root: Path, *, campaign_id: str | None = None, source_reuse_window_days: int = 7
) -> dict[str, Any]:
    conn = connect(root)
    params: list[Any] = []
    where = ""
    if campaign_id:
        where = "WHERE campaign_id=?"
        params.append(campaign_id)
    rows = [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM posting_slots {where}", params
        ).fetchall()
    ]
    conflicts: list[dict[str, Any]] = []
    seen_rendered: set[tuple[str, str]] = set()
    seen_fp: set[tuple[str, str]] = set()
    seen_campaign_fp: set[tuple[str, str]] = set()
    origin_by_fingerprint: dict[str, str] = {}
    for row in rows:
        if row.get("rendered_output_path"):
            key = (row["account_id"], row["rendered_output_path"])
            if key in seen_rendered:
                conflicts.append(
                    {
                        "posting_slot_id": row["posting_slot_id"],
                        "reason": "duplicate_rendered_output_for_account",
                    }
                )
            seen_rendered.add(key)
        if row.get("content_fingerprint"):
            key = (row["account_id"], row["content_fingerprint"])
            if key in seen_fp:
                conflicts.append(
                    {
                        "posting_slot_id": row["posting_slot_id"],
                        "reason": "duplicate_content_fingerprint_for_account",
                    }
                )
            seen_fp.add(key)
            campaign_key = (row.get("campaign_id") or "", row["content_fingerprint"])
            if campaign_key in seen_campaign_fp:
                conflicts.append(
                    {
                        "posting_slot_id": row["posting_slot_id"],
                        "reason": "duplicate_content_fingerprint_for_campaign",
                    }
                )
            seen_campaign_fp.add(campaign_key)
            if not (row.get("source_family_id") or row.get("perceptual_fingerprint")):
                fingerprint = str(row["content_fingerprint"])
                origin = str(
                    row.get("origin_account_id")
                    or origin_by_fingerprint.get(fingerprint)
                    or row["account_id"]
                )
                origin_by_fingerprint.setdefault(fingerprint, origin)
                if origin != row["account_id"]:
                    conflicts.append(
                        {
                            "posting_slot_id": row["posting_slot_id"],
                            "reason": "missing_identity_metadata",
                        }
                    )
        if row.get("source_reference_id"):
            nearby = _nearby_source_rows(conn, row, source_reuse_window_days)
            if nearby:
                conflicts.append(
                    {
                        "posting_slot_id": row["posting_slot_id"],
                        "reason": "nearby_source_reuse",
                        "nearby": nearby,
                    }
                )
    return {"ok": True, "count": len(conflicts), "conflicts": conflicts}


def export_schedule_package(
    root: Path,
    *,
    campaign_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    conn = connect(root)
    where = ["post_status IN ('approved', 'scheduled')"]
    params: list[Any] = []
    if campaign_id:
        where.append("campaign_id=?")
        params.append(campaign_id)
    if date_from:
        where.append("date>=?")
        params.append(date_from)
    if date_to:
        where.append("date<=?")
        params.append(date_to)
    rows = [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM posting_slots WHERE {' AND '.join(where)} ORDER BY date, planned_slot_time, account_handle",
            params,
        ).fetchall()
    ]
    items = []
    blocked = []
    for row in rows:
        audio = _audio_state(row)
        if not audio["schedule_ready"]:
            blocked.append(
                {
                    "posting_slot_id": row["posting_slot_id"],
                    "reason": "unresolved_audio",
                }
            )
            continue
        items.append(_schedule_item(row, audio))
    payload = {
        "schema": "campaign_factory.schedule_package.v1",
        "exported_at": int(time.time()),
        "campaign_id": campaign_id,
        "date_from": date_from,
        "date_to": date_to,
        "count": len(items),
        "items": items,
        "blocked": blocked,
        "auto_posting": False,
    }
    if not dry_run:
        out_dir = Path(root).resolve() / "04_exports" / "posting_ledger"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = (
            out_dir
            / f"schedule_{campaign_id or 'all'}_{date_from or 'start'}_{date_to or 'end'}_{int(time.time())}.json"
        )
        atomic_write_text(
            out_path,
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        payload["path"] = str(out_path)
    return payload


def cli_main() -> int:
    parser = argparse.ArgumentParser(description="Account Posting Ledger utilities.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    plan = sub.add_parser("create-plan")
    plan.add_argument("--root", default=".")
    plan.add_argument("--creator", default="Stacey")
    plan.add_argument("--campaign-id", required=True)
    plan.add_argument(
        "--accounts",
        required=True,
        help="Comma-separated handles or path to JSON list.",
    )
    plan.add_argument("--start-date", default=datetime.now(UTC).date().isoformat())
    plan.add_argument("--days", type=int, default=7)
    plan.add_argument("--platform", default="ig")
    plan.add_argument("--soul-id")
    plan.add_argument("--accepted-soul-id", action="append", default=[])
    plan.add_argument("--dry-run", action="store_true")
    assign = sub.add_parser("assign-approved-reels")
    assign.add_argument("--root", default=".")
    assign.add_argument("--campaign-id", required=True)
    assign.add_argument("--approved-export", required=True)
    assign.add_argument("--eligibility-artifact")
    assign.add_argument("--dry-run", action="store_true")
    conflicts = sub.add_parser("print-conflicts")
    conflicts.add_argument("--root", default=".")
    conflicts.add_argument("--campaign-id")
    export = sub.add_parser("export-schedule-package")
    export.add_argument("--root", default=".")
    export.add_argument("--campaign-id")
    export.add_argument("--date-from")
    export.add_argument("--date-to")
    export.add_argument("--dry-run", action="store_true")
    queue = sub.add_parser("review-queue")
    queue.add_argument("--root", default=".")
    queue.add_argument("--campaign-id")
    args = parser.parse_args()
    root = Path(getattr(args, "root", "."))
    if args.cmd == "create-plan":
        result = create_posting_plan(
            root,
            creator=args.creator,
            campaign_id=args.campaign_id,
            accounts=_parse_accounts(args.accounts),
            start_date=args.start_date,
            days=args.days,
            platform=args.platform,
            soul_id=args.soul_id,
            accepted_soul_ids=args.accepted_soul_id or None,
            dry_run=args.dry_run,
        )
    elif args.cmd == "assign-approved-reels":
        result = assign_approved_reels(
            root,
            campaign_id=args.campaign_id,
            approved_export=Path(args.approved_export),
            eligibility_artifact=Path(args.eligibility_artifact)
            if args.eligibility_artifact
            else None,
            dry_run=args.dry_run,
        )
    elif args.cmd == "print-conflicts":
        result = ledger_conflicts(root, campaign_id=args.campaign_id)
    elif args.cmd == "review-queue":
        result = review_queue(root, campaign_id=args.campaign_id)
    else:
        result = export_schedule_package(
            root,
            campaign_id=args.campaign_id,
            date_from=args.date_from,
            date_to=args.date_to,
            dry_run=args.dry_run,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _assignment_values(
    item: dict[str, Any],
    *,
    output_path: Path,
    lineage: dict[str, Any],
    lineage_path: Path | None,
    fingerprint: str,
    reuse_cooldown_days: int = DEFAULT_CROSS_ACCOUNT_REUSE_WINDOW_DAYS,
) -> dict[str, Any]:
    audio_intent = (
        item.get("audio_intent")
        if isinstance(item.get("audio_intent"), dict)
        else read_audio_intent(output_path)
    )
    audio_selection = (audio_intent or {}).get("audio_selection") or {}
    uniqueness = _uniqueness_values(item, lineage=lineage, fingerprint=fingerprint)
    return {
        "source_reference_id": _lineage_value(
            lineage, "sourceReferenceId", "reference_id", "source_reference_id"
        ),
        "source_reference_path": _lineage_value(
            lineage, "sourceReferencePath", "source_path", "source_reference_path"
        ),
        "source_family_id": uniqueness["source_family_id"],
        "reel_factory_asset_id": _lineage_value(
            lineage, "assetGenerationId", "asset_generation_id"
        )
        or (
            (item.get("campaign") or {}).get("asset_generation_id")
            if isinstance(item.get("campaign"), dict)
            else None
        ),
        "source_kling_video_path": _lineage_value(
            lineage, "klingVideoPath", "video", "local_video_path"
        ),
        "rendered_output_path": str(output_path.resolve()),
        "content_fingerprint": fingerprint,
        "perceptual_fingerprint": uniqueness["perceptual_fingerprint"],
        "perceptual_cluster_id": uniqueness["perceptual_cluster_id"],
        "account_group_id": uniqueness["account_group_id"],
        "origin_account_id": None,
        "reuse_cooldown_days": reuse_cooldown_days,
        "caption": item.get("hook_text")
        or item.get("caption")
        or item.get("caption_text"),
        "caption_variant_id": item.get("caption_variant_id"),
        "audio_track_id": audio_selection.get("track_id") or item.get("audio_track_id"),
        "audio_source": (audio_intent or {}).get("mode") or item.get("audio_source"),
        "audio_selected_reason": audio_selection.get("selected_reason")
        or item.get("audio_selected_reason"),
        "manual_audio_needed": 1 if item.get("manual_audio_needed") else 0,
        "prompt_mode": _lineage_value(lineage, "promptMode", "prompt_mode"),
        "higgsfield_job_id": _lineage_value(
            lineage, "imageJobId", "higgsfield_job_id", "image_job_id"
        ),
        "kling_job_id": _lineage_value(
            lineage, "klingJobId", "kling_job_id", "video_job_id"
        ),
        "crop_panel_id": _lineage_value(
            lineage, "cropPanelId", "selected_panel", "panel_id"
        ),
        "lineage_path": str(lineage_path.resolve()) if lineage_path else None,
        "lineage_json": json.dumps(lineage, ensure_ascii=False, sort_keys=True),
    }


def _assignment_conflicts(
    conn: sqlite3.Connection,
    *,
    slot: dict[str, Any],
    output_path: str,
    fingerprint: str,
    lineage: dict[str, Any],
    uniqueness: dict[str, Any],
    source_reuse_window_days: int,
    include_policy_rules: bool = True,
) -> list[str]:
    reasons = []
    existing_output = conn.execute(
        """
        SELECT posting_slot_id FROM posting_slots
        WHERE account_id=? AND rendered_output_path=? AND post_status NOT IN ('skipped', 'failed')
        """,
        (slot["account_id"], output_path),
    ).fetchone()
    if existing_output:
        reasons.append("duplicate_rendered_output_for_account")
    existing_fp = conn.execute(
        """
        SELECT posting_slot_id FROM posting_slots
        WHERE account_id=? AND content_fingerprint=? AND post_status NOT IN ('skipped', 'failed')
        """,
        (slot["account_id"], fingerprint),
    ).fetchone()
    if existing_fp:
        reasons.append("duplicate_content_fingerprint_for_account")
    existing_campaign_fp = conn.execute(
        """
        SELECT posting_slot_id FROM posting_slots
        WHERE campaign_id=? AND content_fingerprint=?
          AND post_status NOT IN ('planned', 'skipped', 'failed')
        """,
        (slot["campaign_id"], fingerprint),
    ).fetchone()
    if existing_campaign_fp:
        reasons.append("duplicate_content_fingerprint_for_campaign")
    if include_policy_rules:
        has_identity = bool(
            uniqueness.get("source_family_id")
            or uniqueness.get("perceptual_fingerprint")
        )
        declared_origin = str(
            _lineage_value(lineage, "originAccountId", "origin_account_id") or ""
        )
        if not has_identity:
            prior = conn.execute(
                """
                SELECT account_id, origin_account_id FROM posting_slots
                WHERE content_fingerprint=?
                  AND post_status NOT IN ('planned', 'skipped', 'failed')
                ORDER BY created_at LIMIT 1
                """,
                (fingerprint,),
            ).fetchone()
            origin = declared_origin or (
                str(prior["origin_account_id"] or prior["account_id"]) if prior else ""
            )
            if origin and origin != slot["account_id"]:
                reasons.append("missing_identity_metadata")
        source_reference_id = _lineage_value(
            lineage, "sourceReferenceId", "reference_id", "source_reference_id"
        )
        if source_reference_id:
            probe = dict(slot)
            probe["source_reference_id"] = source_reference_id
            if _nearby_source_rows(conn, probe, source_reuse_window_days):
                reasons.append("nearby_source_reuse_for_account")
        if _nearby_cross_account_uniqueness_rows(
            conn, slot, uniqueness, source_reuse_window_days
        ):
            reasons.append("cross_account_source_or_perceptual_reuse")
    return reasons


def _load_eligibility_decisions(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("schema") == (
        "campaign_factory.assignment_eligibility.v1"
    ):
        decisions = [payload]
    elif isinstance(payload, dict) and isinstance(payload.get("decisions"), list):
        decisions = [item for item in payload["decisions"] if isinstance(item, dict)]
    else:
        raise ValueError("invalid assignment eligibility artifact")
    for decision in decisions:
        if decision.get("schema") != "campaign_factory.assignment_eligibility.v1":
            raise ValueError("invalid assignment eligibility decision schema")
        if decision.get("auto_posting") is not False:
            raise ValueError(
                "assignment eligibility artifact must keep auto_posting=false"
            )
        validate_assignment_eligibility(decision)
    return decisions


def _artifact_assignment_conflict(
    decisions: list[dict[str, Any]],
    *,
    slot: dict[str, Any],
    fingerprint: str,
) -> str | None:
    if not decisions:
        return None
    for decision in decisions:
        inputs = (
            decision.get("inputs") if isinstance(decision.get("inputs"), dict) else {}
        )
        if str(inputs.get("accountId") or "") != str(slot["account_id"]):
            continue
        if str(inputs.get("contentFingerprint") or "") != fingerprint:
            continue
        reasons = decision.get("reasonCodes") or []
        if decision.get("allowed") is True and not reasons:
            return None
        return str(reasons[0] if reasons else "assignment_eligibility_blocked")
    return "assignment_eligibility_artifact_input_mismatch"


def _uniqueness_values(
    item: dict[str, Any], *, lineage: dict[str, Any], fingerprint: str
) -> dict[str, Any]:
    source_family = (
        item.get("source_family_id")
        or item.get("sourceFamilyId")
        or _lineage_value(
            lineage,
            "sourceFamilyId",
            "source_family_id",
            "sourceReferenceId",
            "reference_id",
            "source_reference_id",
        )
    )
    perceptual = (
        item.get("perceptual_fingerprint")
        or item.get("perceptualFingerprint")
        or _lineage_value(
            lineage, "perceptualFingerprint", "perceptual_fingerprint", "phash", "pHash"
        )
    )
    cluster = (
        item.get("perceptual_cluster_id")
        or item.get("perceptualClusterId")
        or _lineage_value(lineage, "perceptualClusterId", "perceptual_cluster_id")
        or perceptual
        or source_family
    )
    account_group = (
        item.get("account_group_id")
        or item.get("accountGroupId")
        or _lineage_value(
            lineage, "accountGroupId", "account_group_id", "creator", "model_slug"
        )
    )
    return {
        "source_family_id": str(source_family or ""),
        "perceptual_fingerprint": str(perceptual or ""),
        "perceptual_cluster_id": str(cluster or ""),
        "account_group_id": str(account_group or ""),
        "content_fingerprint": fingerprint,
    }


def _nearby_cross_account_uniqueness_rows(
    conn: sqlite3.Connection,
    slot: dict[str, Any],
    uniqueness: dict[str, Any],
    window_days: int,
) -> list[str]:
    slot_date = date.fromisoformat(slot["date"])
    start = (slot_date - timedelta(days=window_days)).isoformat()
    end = (slot_date + timedelta(days=window_days)).isoformat()
    account_group = uniqueness.get("account_group_id") or ""
    checks = [
        ("source_family_id", uniqueness.get("source_family_id") or ""),
        ("perceptual_cluster_id", uniqueness.get("perceptual_cluster_id") or ""),
    ]
    matches: list[str] = []
    for column, value in checks:
        if not value:
            continue
        query = f"""
            SELECT posting_slot_id FROM posting_slots
            WHERE campaign_id=? AND {column}=? AND date BETWEEN ? AND ?
              AND account_id<>? AND post_status NOT IN ('planned', 'skipped', 'failed')
        """
        params: list[Any] = [slot["campaign_id"], value, start, end, slot["account_id"]]
        if account_group:
            query += " AND (account_group_id=? OR account_group_id='' OR account_group_id IS NULL)"
            params.append(account_group)
        rows = conn.execute(query, params).fetchall()
        matches.extend(r["posting_slot_id"] for r in rows)
    return sorted(set(matches))


def _nearby_source_rows(
    conn: sqlite3.Connection, row: dict[str, Any], window_days: int
) -> list[str]:
    if not row.get("source_reference_id"):
        return []
    slot_date = date.fromisoformat(row["date"])
    start = (slot_date - timedelta(days=window_days)).isoformat()
    end = (slot_date + timedelta(days=window_days)).isoformat()
    rows = conn.execute(
        """
        SELECT posting_slot_id FROM posting_slots
        WHERE account_id=? AND source_reference_id=? AND date BETWEEN ? AND ?
          AND posting_slot_id<>? AND post_status NOT IN ('planned', 'skipped', 'failed')
        """,
        (
            row["account_id"],
            row["source_reference_id"],
            start,
            end,
            row["posting_slot_id"],
        ),
    ).fetchall()
    return [r["posting_slot_id"] for r in rows]


def _validate_transition(row: dict[str, Any], to_status: str) -> None:
    order = {
        "planned": {"ready_for_review", "skipped", "failed"},
        "ready_for_review": {"approved", "skipped", "failed"},
        "approved": {"scheduled", "skipped", "failed"},
        "scheduled": {"posted", "skipped", "failed"},
        "posted": {"metrics_imported", "failed"},
        "metrics_imported": {"metrics_imported"},
        "skipped": {"skipped"},
        "failed": {"failed"},
    }
    current = row["post_status"]
    if to_status == current:
        return
    if to_status not in order[current]:
        raise ValueError(f"invalid transition: {current} -> {to_status}")
    if to_status in {"ready_for_review", "approved", "scheduled"}:
        if not row.get("rendered_output_path") or not row.get("lineage_path"):
            raise ValueError(
                "lineage and rendered output are required before review/scheduling"
            )
    if to_status == "scheduled" and not _audio_state(row)["schedule_ready"]:
        raise ValueError(
            "resolved audio intent or manual_audio_needed is required before scheduling"
        )


def _audio_state(row: dict[str, Any]) -> dict[str, Any]:
    output = row.get("rendered_output_path")
    sidecar = read_audio_intent(Path(output)) if output else None
    manual = bool(row.get("manual_audio_needed"))
    sidecar_mode = (sidecar or {}).get("mode") if sidecar else None
    sidecar_status = str((sidecar or {}).get("status") or "").lower()
    sidecar_selection = (
        (sidecar or {}).get("audio_selection")
        if isinstance((sidecar or {}).get("audio_selection"), dict)
        else {}
    )
    sidecar_has_selection = bool(
        sidecar_selection.get("track_id")
        or sidecar_selection.get("title")
        or sidecar_selection.get("url")
    )
    if sidecar_mode == "native_trending_audio":
        sidecar_resolved = (
            sidecar_status in {"resolved", "selected", "approved", "ready"}
            or sidecar_has_selection
        )
    else:
        sidecar_resolved = bool(sidecar)
    row_audio_source = row.get("audio_source")
    row_audio_resolved = bool(
        row.get("audio_track_id")
        or (row_audio_source and row_audio_source != "native_trending_audio")
    )
    resolved = manual or row_audio_resolved or sidecar_resolved
    return {
        "manual_audio_needed": manual,
        "audio_track_id": row.get("audio_track_id"),
        "audio_source": row.get("audio_source") or sidecar_mode,
        "audio_selected_reason": row.get("audio_selected_reason"),
        "sidecar": sidecar,
        "schedule_ready": resolved,
    }


def _schedule_item(row: dict[str, Any], audio: dict[str, Any]) -> dict[str, Any]:
    return {
        "posting_slot_id": row["posting_slot_id"],
        "account_id": row["account_id"],
        "account_handle": row["account_handle"],
        "platform": row["platform"],
        "campaign_id": row["campaign_id"],
        "creator": row["creator"],
        "soul_name": row["soul_name"],
        "soul_id": row["soul_id"],
        "accepted_soul_ids": _json_text_list(row["accepted_soul_ids_json"]),
        "date": row["date"],
        "slot_type": row["slot_type"],
        "planned_slot_time": row["planned_slot_time"],
        "timezone": row["timezone"],
        "planned_at": row["planned_at"],
        "scheduled_at": row["scheduled_at"],
        "rendered_output_path": row["rendered_output_path"],
        "content_fingerprint": row["content_fingerprint"],
        "caption": row["caption"],
        "caption_variant_id": row["caption_variant_id"],
        "audio": audio,
        "lineage_path": row["lineage_path"],
        "source_reference_id": row["source_reference_id"],
        "source_reference_path": row["source_reference_path"],
        "reel_factory_asset_id": row["reel_factory_asset_id"],
        "source_kling_video_path": row["source_kling_video_path"],
        "higgsfield_job_id": row["higgsfield_job_id"],
        "kling_job_id": row["kling_job_id"],
        "crop_panel_id": row["crop_panel_id"],
        "post_status": row["post_status"],
    }


def _record_event(
    conn: sqlite3.Connection,
    posting_slot_id: str,
    from_status: str | None,
    to_status: str,
    *,
    actor: str = "",
    notes: str = "",
    changes: dict[str, Any] | None = None,
) -> None:
    event_id = (
        "evt_"
        + hashlib.sha256(
            f"{posting_slot_id}:{from_status}:{to_status}:{time.time_ns()}".encode()
        ).hexdigest()[:20]
    )
    conn.execute(
        """
        INSERT INTO posting_slot_events (
            event_id, posting_slot_id, from_status, to_status, actor, notes, changes_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            posting_slot_id,
            from_status,
            to_status,
            actor,
            notes,
            json.dumps(changes or {}, ensure_ascii=False, sort_keys=True),
            int(time.time()),
        ),
    )


def _creator_identity_defaults(
    conn: sqlite3.Connection, creator: str, campaign_id: str
) -> dict[str, Any]:
    row = None
    if _table_exists(conn, "campaigns") and _table_exists(conn, "creators"):
        row = conn.execute(
            """
            SELECT cr.name, cr.soul_id, cr.default_settings_json
            FROM campaigns c JOIN creators cr ON cr.creator_id = c.creator_id
            WHERE c.campaign_id=? OR c.name=?
            LIMIT 1
            """,
            (campaign_id, campaign_id),
        ).fetchone()
    if row is None and _table_exists(conn, "creators"):
        row = conn.execute(
            "SELECT name, soul_id, default_settings_json FROM creators WHERE lower(name)=lower(?)",
            (creator,),
        ).fetchone()
    if row is None:
        return {"soul_id": None, "accepted_soul_ids": [], "accepted_names": [creator]}
    settings = _json_object(row["default_settings_json"])
    accepted = _text_list(settings.get("accepted_soul_ids"))
    soul_id = _first_text(row["soul_id"])
    return {
        "soul_id": soul_id,
        "accepted_soul_ids": accepted or ([soul_id] if soul_id else []),
        "accepted_names": _dedupe_texts([row["name"], creator]),
    }


def _creator_identity_conflict(
    conn: sqlite3.Connection,
    *,
    item: dict[str, Any],
    lineage: dict[str, Any],
    slot: dict[str, Any],
) -> str | None:
    item_soul_id = _first_text(
        _lineage_value(lineage, "soulId", "soul_id")
        or item.get("soulId")
        or item.get("soul_id")
    )
    item_names = _dedupe_texts(
        [
            _lineage_value(lineage, "soulName", "soul_name")
            or item.get("soulName")
            or item.get("soul_name"),
            item.get("creator"),
        ]
    )
    if not item_soul_id and not item_names:
        return "creator_identity_unverifiable_for_slot"

    accepted_ids = _json_text_list(slot.get("accepted_soul_ids_json"))
    if not accepted_ids and slot.get("soul_id"):
        accepted_ids = [_first_text(slot.get("soul_id"))]
    if item_soul_id and accepted_ids:
        if item_soul_id not in accepted_ids:
            return "creator_identity_mismatch_for_slot"
        return None

    accepted_names = _slot_accepted_names(conn, slot, accepted_ids)
    if item_names and accepted_names:
        item_name_set = {_normalize_name(name) for name in item_names}
        accepted_name_set = {_normalize_name(name) for name in accepted_names}
        if item_name_set & accepted_name_set:
            return None
        return "creator_identity_mismatch_for_slot"
    return "creator_identity_unverifiable_for_slot"


def _slot_accepted_names(
    conn: sqlite3.Connection, slot: dict[str, Any], accepted_ids: list[str]
) -> list[str]:
    names = [slot.get("creator"), slot.get("soul_name")]
    if accepted_ids and _table_exists(conn, "creators"):
        placeholders = ",".join("?" for _ in accepted_ids)
        rows = conn.execute(
            f"SELECT name FROM creators WHERE soul_id IN ({placeholders})",
            accepted_ids,
        ).fetchall()
        names.extend(row["name"] for row in rows)
    return _dedupe_texts(names)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        is not None
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        return _text_list(parsed)
    return _text_list(value)


def _text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = [value]
    return _dedupe_texts(raw)


def _dedupe_texts(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = _first_text(value)
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _first_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_name(value: str) -> str:
    return value.strip().lower()


def _find_lineage_path(output_path: Path) -> Path | None:
    candidates = [
        output_path.with_suffix(output_path.suffix + ".generated_asset_lineage.json"),
        output_path.with_suffix(".generated_asset_lineage.json"),
        output_path.parent / f"{output_path.stem}.generated_asset_lineage.json",
    ]
    return next((path for path in candidates if path.exists()), None)


def _lineage_value(lineage: dict[str, Any], *keys: str) -> Any:
    stack = [lineage]
    while stack:
        obj = stack.pop()
        if not isinstance(obj, dict):
            continue
        for key in keys:
            if key in obj and obj[key] not in (None, ""):
                return obj[key]
        stack.extend(v for v in obj.values() if isinstance(v, dict))
    return None


def _parse_accounts(value: str) -> list[str | dict[str, Any]]:
    path = Path(value).expanduser()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("accounts JSON must be a list")
        return data
    return [part.strip().lstrip("@") for part in value.split(",") if part.strip()]


def _slot_id(account_id: str, slot_date: str, slot_type: str) -> str:
    digest = hashlib.sha256(
        f"{account_id}:{slot_date}:{slot_type}".encode()
    ).hexdigest()[:16]
    return f"slot_{digest}"


def _slug(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
    while "__" in clean:
        clean = clean.replace("__", "_")
    return clean or "account"


if __name__ == "__main__":
    raise SystemExit(cli_main())
