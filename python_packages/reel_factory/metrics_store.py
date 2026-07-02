"""Manual publish metrics import and reporting."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from audio_intent import read_audio_intent
from campaign_store import ensure_campaign_schema, slugify
from intelligence_store import ensure_intelligence_schema, winner_score
from sqlite_utils import connect_sqlite

METRIC_COLUMNS = (
    "filename",
    "platform",
    "account",
    "uploaded_at",
    "views",
    "likes",
    "comments",
    "shares",
    "saves",
    "manual_score",
    "notes",
)


def connect_metrics_db(db_path: Path) -> sqlite3.Connection:
    return connect_sqlite(Path(db_path))


def ensure_metrics_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS publish_metrics (
            filename TEXT PRIMARY KEY,
            platform TEXT,
            account TEXT,
            uploaded_at TEXT,
            views INTEGER,
            likes INTEGER,
            comments INTEGER,
            shares INTEGER,
            saves INTEGER,
            manual_score REAL,
            notes TEXT,
            soul_id TEXT,
            campaign_output_id TEXT,
            job_key TEXT,
            imported_at INTEGER NOT NULL
        )
    """)
    _ensure_columns(
        conn,
        "publish_metrics",
        {"soul_id": "TEXT", "campaign_output_id": "TEXT", "job_key": "TEXT"},
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_publish_metrics_campaign_output ON publish_metrics(campaign_output_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_publish_metrics_job_key ON publish_metrics(job_key)"
    )
    ensure_intelligence_schema(conn)


def import_metrics_csv(root: Path, csv_path: Path) -> dict[str, Any]:
    db_path = Path(root) / "manifest.sqlite"
    if not db_path.exists():
        raise FileNotFoundError(f"manifest.sqlite not found under {root}")
    conn = connect_metrics_db(db_path)
    ensure_metrics_schema(conn)
    ensure_campaign_schema(conn)

    known = {
        Path(row["output_path"]).name
        for row in conn.execute(
            "SELECT output_path FROM variations WHERE status = 'ok'"
        )
    }
    known.update(
        row["metrics_filename"]
        for row in conn.execute(
            "SELECT metrics_filename FROM campaign_outputs WHERE metrics_filename IS NOT NULL"
        )
        if row["metrics_filename"]
    )
    imported = 0
    ignored: list[str] = []
    with Path(csv_path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "filename" not in reader.fieldnames:
            raise ValueError("metrics CSV must include a filename column")
        for row in reader:
            filename = (row.get("filename") or "").strip()
            if not filename or filename not in known:
                if filename:
                    ignored.append(filename)
                continue
            output_row = conn.execute(
                "SELECT output_path, job_key, caption_text, recipe, review_state FROM variations WHERE output_path LIKE ? LIMIT 1",
                (f"%/{filename}",),
            ).fetchone()
            campaign_output_row = conn.execute(
                "SELECT * FROM campaign_outputs WHERE metrics_filename=? LIMIT 1",
                (filename,),
            ).fetchone()
            if not campaign_output_row:
                campaign_output_row = conn.execute(
                    "SELECT * FROM campaign_outputs WHERE output_path LIKE ? LIMIT 1",
                    (f"%/{filename}",),
                ).fetchone()
            output_path = output_row["output_path"] if output_row else None
            if not output_path and campaign_output_row:
                output_path = campaign_output_row["output_path"]
            job_key = (output_row["job_key"] if output_row else None) or (
                campaign_output_row["job_key"] if campaign_output_row else None
            )
            campaign_output_id = None
            if output_path:
                campaign_output_id = (
                    campaign_output_row["campaign_output_id"]
                    if campaign_output_row
                    else f"out_{slugify(Path(output_path).stem)}"
                )
            soul_id = _resolve_metrics_soul_id(
                Path(root), conn, filename, output_path=output_path
            )
            conn.execute(
                """
                INSERT INTO publish_metrics (
                    filename, platform, account, uploaded_at, views, likes,
                    comments, shares, saves, manual_score, notes, soul_id,
                    campaign_output_id, job_key, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(filename) DO UPDATE SET
                    platform = excluded.platform,
                    account = excluded.account,
                    uploaded_at = excluded.uploaded_at,
                    views = excluded.views,
                    likes = excluded.likes,
                    comments = excluded.comments,
                    shares = excluded.shares,
                    saves = excluded.saves,
                    manual_score = excluded.manual_score,
                    notes = excluded.notes,
                    soul_id = excluded.soul_id,
                    campaign_output_id = excluded.campaign_output_id,
                    job_key = excluded.job_key,
                    imported_at = excluded.imported_at
                """,
                (
                    filename,
                    _text(row.get("platform")),
                    _text(row.get("account")),
                    _text(row.get("uploaded_at") or row.get("date")),
                    _int(row.get("views")),
                    _int(row.get("likes")),
                    _int(row.get("comments")),
                    _int(row.get("shares")),
                    _int(row.get("saves")),
                    _float(row.get("manual_score") or row.get("score")),
                    _text(row.get("notes")),
                    soul_id,
                    campaign_output_id,
                    job_key,
                    int(time.time()),
                ),
            )
            if output_row or campaign_output_row:
                now = int(time.time())
                conn.execute(
                    """
                    INSERT INTO campaign_outputs (
                        campaign_output_id, output_path, job_key, caption_text,
                        recipe, review_state, metrics_filename, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(output_path) DO UPDATE SET
                        job_key = COALESCE(excluded.job_key, campaign_outputs.job_key),
                        caption_text = COALESCE(excluded.caption_text, campaign_outputs.caption_text),
                        recipe = COALESCE(excluded.recipe, campaign_outputs.recipe),
                        review_state = COALESCE(excluded.review_state, campaign_outputs.review_state),
                        metrics_filename = excluded.metrics_filename,
                        updated_at = excluded.updated_at
                    """,
                    (
                        campaign_output_id,
                        output_path,
                        job_key,
                        (output_row["caption_text"] if output_row else None)
                        or (
                            campaign_output_row["caption_text"]
                            if campaign_output_row
                            else None
                        ),
                        (output_row["recipe"] if output_row else None)
                        or (
                            campaign_output_row["recipe"]
                            if campaign_output_row
                            else None
                        ),
                        (output_row["review_state"] if output_row else None)
                        or (
                            campaign_output_row["review_state"]
                            if campaign_output_row
                            else None
                        ),
                        filename,
                        now,
                        now,
                    ),
                )
            imported += 1
    conn.commit()
    return {"imported": imported, "ignored": ignored}


def import_outcomes_csv(root: Path, csv_path: Path) -> dict[str, Any]:
    db_path = Path(root) / "manifest.sqlite"
    if not db_path.exists():
        raise FileNotFoundError(f"manifest.sqlite not found under {root}")
    conn = connect_metrics_db(db_path)
    ensure_metrics_schema(conn)
    ensure_campaign_schema(conn)
    ensure_intelligence_schema(conn)

    imported = 0
    ignored: list[str] = []
    with Path(csv_path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "filename" not in reader.fieldnames:
            raise ValueError("outcomes CSV must include a filename column")
        for row in reader:
            filename = (row.get("filename") or "").strip()
            if not filename:
                continue
            variation = conn.execute(
                "SELECT * FROM variations WHERE output_path LIKE ? LIMIT 1",
                (f"%/{filename}",),
            ).fetchone()
            campaign_output = conn.execute(
                "SELECT * FROM campaign_outputs WHERE metrics_filename=? LIMIT 1",
                (filename,),
            ).fetchone()
            if not campaign_output:
                campaign_output = conn.execute(
                    "SELECT * FROM campaign_outputs WHERE output_path LIKE ? LIMIT 1",
                    (f"%/{filename}",),
                ).fetchone()
            if not variation and not campaign_output:
                ignored.append(filename)
            if variation and not campaign_output:
                now = int(time.time())
                conn.execute(
                    """
                    INSERT INTO campaign_outputs (
                        campaign_output_id, output_path, job_key, caption_text,
                        recipe, review_state, metrics_filename, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(output_path) DO UPDATE SET
                        job_key=COALESCE(excluded.job_key, campaign_outputs.job_key),
                        caption_text=COALESCE(excluded.caption_text, campaign_outputs.caption_text),
                        recipe=COALESCE(excluded.recipe, campaign_outputs.recipe),
                        review_state=COALESCE(excluded.review_state, campaign_outputs.review_state),
                        metrics_filename=excluded.metrics_filename,
                        updated_at=excluded.updated_at
                    """,
                    (
                        f"out_{slugify(Path(variation['output_path']).stem)}",
                        variation["output_path"],
                        variation["job_key"],
                        variation["caption_text"],
                        variation["recipe"],
                        variation["review_state"],
                        filename,
                        now,
                        now,
                    ),
                )
                campaign_output = conn.execute(
                    "SELECT * FROM campaign_outputs WHERE output_path=? LIMIT 1",
                    (variation["output_path"],),
                ).fetchone()
            output_path = (
                variation["output_path"]
                if variation
                else (campaign_output["output_path"] if campaign_output else None)
            )
            audio_track_id = _audio_track_id_for_output(output_path)
            source_reference_id = None
            prompt_run_id = (
                campaign_output["prompt_run_id"] if campaign_output else None
            )
            if campaign_output and campaign_output["asset_generation_id"]:
                asset = conn.execute(
                    "SELECT prompt_run_id, reference_id FROM asset_generations WHERE asset_generation_id=?",
                    (campaign_output["asset_generation_id"],),
                ).fetchone()
                if asset:
                    prompt_run_id = prompt_run_id or asset["prompt_run_id"]
                    source_reference_id = asset["reference_id"]
            platform = _text(row.get("platform")) or "instagram_reels"
            account = _outcome_dimension(row.get("account"))
            posted_at = _outcome_dimension(
                row.get("posted_at") or row.get("uploaded_at") or row.get("date")
            )
            soul_id = _resolve_metrics_soul_id(
                Path(root), conn, filename, output_path=output_path
            )
            outcome_id = f"outcome_{slugify(filename)}_{slugify(platform or 'platform')}_{slugify(account or 'account')}_{slugify(posted_at or 'unknown')}"
            payload = (
                outcome_id,
                filename,
                output_path,
                soul_id,
                (campaign_output["job_key"] if campaign_output else None)
                or (variation["job_key"] if variation else None),
                campaign_output["campaign_output_id"] if campaign_output else None,
                campaign_output["campaign_id"] if campaign_output else None,
                campaign_output["asset_generation_id"] if campaign_output else None,
                prompt_run_id,
                source_reference_id,
                audio_track_id,
                platform,
                account,
                posted_at,
                _int(row.get("views")),
                _int(row.get("likes")),
                _int(row.get("comments")),
                _int(row.get("shares")),
                _int(row.get("saves")),
                _float(row.get("watch_time")),
                _float(row.get("retention_rate")),
                _int(row.get("profile_visits")),
                _int(row.get("follows")),
                _float(row.get("manual_score") or row.get("score")),
                _text(row.get("source_url")),
                _text(row.get("notes")),
                int(time.time()),
            )
            conn.execute(
                """
                INSERT INTO reel_outcomes (
                    outcome_id, filename, output_path, soul_id, job_key, campaign_output_id,
                    campaign_id, asset_generation_id, prompt_run_id, source_reference_id,
                    audio_track_id, platform, account, posted_at, views, likes, comments, shares, saves,
                    watch_time, retention_rate, profile_visits, follows, manual_score,
                    source_url, notes, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(outcome_id) DO UPDATE SET
                    filename=excluded.filename,
                    output_path=excluded.output_path,
                    soul_id=excluded.soul_id,
                    job_key=excluded.job_key,
                    campaign_output_id=excluded.campaign_output_id,
                    campaign_id=excluded.campaign_id,
                    asset_generation_id=excluded.asset_generation_id,
                    prompt_run_id=excluded.prompt_run_id,
                    source_reference_id=excluded.source_reference_id,
                    audio_track_id=excluded.audio_track_id,
                    platform=excluded.platform,
                    account=excluded.account,
                    posted_at=excluded.posted_at,
                    views=excluded.views,
                    likes=excluded.likes,
                    comments=excluded.comments,
                    shares=excluded.shares,
                    saves=excluded.saves,
                    watch_time=excluded.watch_time,
                    retention_rate=excluded.retention_rate,
                    profile_visits=excluded.profile_visits,
                    follows=excluded.follows,
                    manual_score=excluded.manual_score,
                    source_url=excluded.source_url,
                    notes=excluded.notes,
                    imported_at=excluded.imported_at
                """,
                payload,
            )
            # Keep the old table in sync for existing dashboards.
            conn.execute(
                """
                INSERT INTO publish_metrics (
                    filename, platform, account, uploaded_at, views, likes,
                    comments, shares, saves, manual_score, notes, soul_id,
                    campaign_output_id, job_key, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(filename) DO UPDATE SET
                    platform=excluded.platform,
                    account=excluded.account,
                    uploaded_at=excluded.uploaded_at,
                    views=excluded.views,
                    likes=excluded.likes,
                    comments=excluded.comments,
                    shares=excluded.shares,
                    saves=excluded.saves,
                    manual_score=excluded.manual_score,
                    notes=excluded.notes,
                    soul_id=excluded.soul_id,
                    campaign_output_id=excluded.campaign_output_id,
                    job_key=excluded.job_key,
                    imported_at=excluded.imported_at
                """,
                (
                    filename,
                    platform,
                    account,
                    posted_at,
                    _int(row.get("views")),
                    _int(row.get("likes")),
                    _int(row.get("comments")),
                    _int(row.get("shares")),
                    _int(row.get("saves")),
                    _float(row.get("manual_score") or row.get("score")),
                    _text(row.get("notes")),
                    soul_id,
                    campaign_output["campaign_output_id"] if campaign_output else None,
                    (campaign_output["job_key"] if campaign_output else None)
                    or (variation["job_key"] if variation else None),
                    int(time.time()),
                ),
            )
            if campaign_output:
                conn.execute(
                    "UPDATE campaign_outputs SET metrics_filename=?, updated_at=? WHERE campaign_output_id=?",
                    (filename, int(time.time()), campaign_output["campaign_output_id"]),
                )
            imported += 1
    conn.commit()
    return {"imported": imported, "ignored": ignored}


def refresh_outcomes_from_performance_sync(
    root: Path,
    *,
    campaign_factory_db: Path,
    campaign: str | None = None,
) -> dict[str, Any]:
    """Bridge synced Campaign Factory performance facts into Reel Factory learning tables."""
    db_path = Path(root) / "manifest.sqlite"
    source_db = Path(campaign_factory_db)
    if not source_db.exists():
        raise FileNotFoundError(f"campaign factory DB not found: {source_db}")
    conn = connect_metrics_db(db_path)
    ensure_metrics_schema(conn)
    ensure_campaign_schema(conn)
    ensure_intelligence_schema(conn)

    source = connect_sqlite(source_db, readonly=True, wal=False)
    where = ["p.metrics_eligible = 1"]
    params: list[Any] = []
    if campaign:
        where.append("p.campaign_id = ?")
        params.append(campaign)
    where_sql = " AND ".join(where)
    rows = source.execute(
        f"""
        SELECT p.*, ra.output_path AS rendered_output_path,
               ra.filename AS rendered_filename,
               ra.caption AS rendered_caption,
               ra.recipe AS rendered_recipe,
               ra.review_state AS rendered_review_state
        FROM performance_snapshots p
        JOIN (
            SELECT post_id, MAX(snapshot_at) AS snapshot_at
            FROM performance_snapshots p
            WHERE {where_sql}
            GROUP BY post_id
        ) latest
          ON latest.post_id = p.post_id AND latest.snapshot_at = p.snapshot_at
        LEFT JOIN rendered_assets ra ON ra.id = p.rendered_asset_id
        WHERE {where_sql}
        ORDER BY p.snapshot_at DESC, p.created_at DESC
        """,
        (*params, *params),
    ).fetchall()

    imported = 0
    skipped: list[dict[str, Any]] = []
    now = int(time.time())
    for row in rows:
        output_path = _text(row["rendered_output_path"])
        filename = _text(row["rendered_filename"]) or (
            Path(output_path).name if output_path else None
        )
        if not filename or not output_path:
            skipped.append(
                {
                    "performanceSnapshotId": row["id"],
                    "postId": row["post_id"],
                    "reason": "missing_rendered_output_path",
                }
            )
            continue
        output_path = str(_project_path(Path(root), output_path).resolve())
        campaign_output = conn.execute(
            "SELECT * FROM campaign_outputs WHERE output_path=? LIMIT 1",
            (output_path,),
        ).fetchone()
        if not campaign_output:
            campaign_output = conn.execute(
                "SELECT * FROM campaign_outputs WHERE metrics_filename=? LIMIT 1",
                (filename,),
            ).fetchone()
        conn.execute(
            """
            INSERT INTO campaign_outputs (
                campaign_output_id, campaign_id, output_path, caption_text, recipe,
                review_state, metrics_filename, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(output_path) DO UPDATE SET
                campaign_id=COALESCE(campaign_outputs.campaign_id, excluded.campaign_id),
                caption_text=COALESCE(campaign_outputs.caption_text, excluded.caption_text),
                recipe=COALESCE(campaign_outputs.recipe, excluded.recipe),
                review_state=COALESCE(campaign_outputs.review_state, excluded.review_state),
                metrics_filename=excluded.metrics_filename,
                updated_at=excluded.updated_at
            """,
            (
                (campaign_output["campaign_output_id"] if campaign_output else None)
                or f"out_{slugify(Path(output_path).stem)}",
                row["campaign_id"],
                output_path,
                _text(row["rendered_caption"]) or _text(row["caption_text"]),
                _text(row["rendered_recipe"]) or _text(row["recipe"]),
                _text(row["rendered_review_state"]),
                filename,
                now,
                now,
            ),
        )
        campaign_output = conn.execute(
            "SELECT * FROM campaign_outputs WHERE output_path=? LIMIT 1", (output_path,)
        ).fetchone()
        soul_id = _resolve_metrics_soul_id(
            Path(root), conn, filename, output_path=output_path
        )
        audio_track_id = _audio_track_id_for_output(output_path)
        platform = _text(row["platform"]) or "instagram_reels"
        account = _outcome_dimension(row["instagram_account_id"]) or _outcome_dimension(
            row["account_id"]
        )
        posted_at = _outcome_dimension(row["published_at"]) or _outcome_dimension(
            row["snapshot_at"]
        )
        outcome_id = f"outcome_{slugify(filename)}_{slugify(platform or 'platform')}_{slugify(account or 'account')}_{slugify(posted_at or 'unknown')}"
        conn.execute(
            """
            INSERT INTO reel_outcomes (
                outcome_id, filename, output_path, soul_id, campaign_output_id,
                campaign_id, audio_track_id, platform, account, posted_at, views, likes, comments,
                shares, saves, watch_time, source_url, notes, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(outcome_id) DO UPDATE SET
                filename=excluded.filename,
                output_path=excluded.output_path,
                soul_id=excluded.soul_id,
                campaign_output_id=excluded.campaign_output_id,
                campaign_id=excluded.campaign_id,
                audio_track_id=excluded.audio_track_id,
                platform=excluded.platform,
                account=excluded.account,
                posted_at=excluded.posted_at,
                views=excluded.views,
                likes=excluded.likes,
                comments=excluded.comments,
                shares=excluded.shares,
                saves=excluded.saves,
                watch_time=excluded.watch_time,
                source_url=excluded.source_url,
                notes=excluded.notes,
                imported_at=excluded.imported_at
            """,
            (
                outcome_id,
                filename,
                output_path,
                soul_id,
                campaign_output["campaign_output_id"] if campaign_output else None,
                row["campaign_id"],
                audio_track_id,
                platform,
                account,
                posted_at,
                _int_from_any(row["views"]),
                _int_from_any(row["likes"]),
                _int_from_any(row["comments"]),
                _int_from_any(row["shares"]),
                _int_from_any(row["saves"]),
                _float_from_any(row["watch_time_seconds"]),
                _text(row["permalink"]),
                f"threadsdash performance snapshot {row['id']}",
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO publish_metrics (
                filename, platform, account, uploaded_at, views, likes, comments,
                shares, saves, notes, soul_id, campaign_output_id, job_key, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                platform=excluded.platform,
                account=excluded.account,
                uploaded_at=excluded.uploaded_at,
                views=excluded.views,
                likes=excluded.likes,
                comments=excluded.comments,
                shares=excluded.shares,
                saves=excluded.saves,
                notes=excluded.notes,
                soul_id=excluded.soul_id,
                campaign_output_id=excluded.campaign_output_id,
                job_key=excluded.job_key,
                imported_at=excluded.imported_at
            """,
            (
                filename,
                platform,
                account,
                posted_at,
                _int_from_any(row["views"]),
                _int_from_any(row["likes"]),
                _int_from_any(row["comments"]),
                _int_from_any(row["shares"]),
                _int_from_any(row["saves"]),
                f"threadsdash performance snapshot {row['id']}",
                soul_id,
                campaign_output["campaign_output_id"] if campaign_output else None,
                campaign_output["job_key"] if campaign_output else None,
                now,
            ),
        )
        imported += 1
    conn.commit()
    source.close()

    from caption_bank import refresh_caption_weights
    from winner_dna import refresh_winner_dna

    winner_dna = refresh_winner_dna(Path(root))
    caption_weights = refresh_caption_weights(Path(root))
    return {
        "imported": imported,
        "skipped": skipped,
        "winnerDna": winner_dna,
        "captionWeights": caption_weights,
    }


def outcomes_summary(root: Path, limit: int = 10) -> dict[str, Any]:
    db_path = Path(root) / "manifest.sqlite"
    if not db_path.exists():
        return {"count": 0, "top": [], "totals": {}}
    conn = connect_metrics_db(db_path)
    ensure_intelligence_schema(conn)
    rows = conn.execute("SELECT * FROM reel_outcomes").fetchall()
    totals = {
        metric: sum(int(row[metric] or 0) for row in rows)
        for metric in ("views", "likes", "comments", "shares", "saves", "follows")
    }
    top = sorted(
        (dict(row) | {"winner_score": winner_score(row)} for row in rows),
        key=lambda row: row["winner_score"],
        reverse=True,
    )[:limit]
    return {"count": len(rows), "totals": totals, "top": top}


def metrics_summary(root: Path) -> list[dict[str, Any]]:
    db_path = Path(root) / "manifest.sqlite"
    if not db_path.exists():
        return []
    conn = connect_metrics_db(db_path)
    ensure_metrics_schema(conn)
    rows = conn.execute("""
        SELECT
            v.recipe,
            m.filename,
            m.views,
            m.likes,
            m.comments,
            m.shares,
            m.saves,
            m.manual_score
        FROM variations v
        LEFT JOIN campaign_outputs co ON co.output_path = v.output_path
        JOIN publish_metrics m
          ON m.campaign_output_id = co.campaign_output_id
          OR (
              m.campaign_output_id IS NULL
              AND m.job_key IS NOT NULL
              AND v.job_key IS NOT NULL
              AND m.job_key = v.job_key
          )
          OR (
              m.campaign_output_id IS NULL
              AND (m.job_key IS NULL OR v.job_key IS NULL)
              AND substr(v.output_path, length(v.output_path) - length(m.filename) + 1) = m.filename
          )
        WHERE v.status = 'ok'
    """).fetchall()
    groups: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        hook_idx = _hook_idx(row["filename"])
        key = (row["recipe"], hook_idx)
        group = groups.setdefault(
            key,
            {
                "recipe": row["recipe"],
                "hook_idx": hook_idx,
                "upload_count": 0,
                "views": [],
                "likes": [],
                "comments": [],
                "shares": [],
                "saves": [],
                "top_output": None,
                "top_score": -1.0,
            },
        )
        group["upload_count"] += 1
        for metric in ("views", "likes", "comments", "shares", "saves"):
            if row[metric] is not None:
                group[metric].append(int(row[metric]))
        score = (
            float(row["manual_score"])
            if row["manual_score"] is not None
            else float(row["views"] or 0)
        )
        if score > group["top_score"]:
            group["top_score"] = score
            group["top_output"] = row["filename"]

    out = []
    for group in groups.values():
        out.append(
            {
                "recipe": group["recipe"],
                "hook_idx": group["hook_idx"],
                "upload_count": group["upload_count"],
                "avg_views": _avg(group["views"]),
                "avg_likes": _avg(group["likes"]),
                "avg_comments": _avg(group["comments"]),
                "avg_shares": _avg(group["shares"]),
                "avg_saves": _avg(group["saves"]),
                "top_output": group["top_output"],
            }
        )
    return sorted(out, key=lambda item: (item["recipe"], item["hook_idx"]))


def metrics_leaderboard(root: Path, limit: int = 10) -> dict[str, list[dict[str, Any]]]:
    db_path = Path(root) / "manifest.sqlite"
    if not db_path.exists():
        return {"hooks": [], "recipes": [], "combos": []}
    conn = connect_metrics_db(db_path)
    ensure_metrics_schema(conn)
    rows = conn.execute("""
        SELECT
            v.recipe,
            v.caption_text,
            m.filename,
            m.views,
            m.likes,
            m.comments,
            m.shares,
            m.saves,
            m.manual_score
        FROM variations v
        LEFT JOIN campaign_outputs co ON co.output_path = v.output_path
        JOIN publish_metrics m
          ON m.campaign_output_id = co.campaign_output_id
          OR (
              m.campaign_output_id IS NULL
              AND m.job_key IS NOT NULL
              AND v.job_key IS NOT NULL
              AND m.job_key = v.job_key
          )
          OR (
              m.campaign_output_id IS NULL
              AND (m.job_key IS NULL OR v.job_key IS NULL)
              AND substr(v.output_path, length(v.output_path) - length(m.filename) + 1) = m.filename
          )
        WHERE v.status = 'ok'
    """).fetchall()

    def add(group: dict[str, Any], row: sqlite3.Row) -> None:
        group["upload_count"] += 1
        for metric in ("views", "likes", "comments", "shares", "saves"):
            if row[metric] is not None:
                group[metric].append(int(row[metric]))
        engagement = sum(
            int(row[m] or 0) for m in ("likes", "comments", "shares", "saves")
        )
        score = (
            float(row["manual_score"])
            if row["manual_score"] is not None
            else float(row["views"] or 0)
        )
        if score > group["top_score"]:
            group["top_score"] = score
            group["top_output"] = row["filename"]
        group["engagement_total"] += engagement

    buckets: dict[str, dict[Any, dict[str, Any]]] = {
        "hooks": {},
        "recipes": {},
        "combos": {},
    }
    for row in rows:
        hook_idx = _hook_idx(row["filename"])
        keys = {
            "hooks": hook_idx,
            "recipes": row["recipe"],
            "combos": (row["recipe"], hook_idx),
        }
        for bucket_name, key in keys.items():
            bucket = buckets[bucket_name].setdefault(
                key,
                {
                    "key": key,
                    "recipe": row["recipe"] if bucket_name != "hooks" else None,
                    "hook_idx": hook_idx if bucket_name != "recipes" else None,
                    "hook_text": row["caption_text"]
                    if bucket_name in {"hooks", "combos"}
                    else None,
                    "upload_count": 0,
                    "views": [],
                    "likes": [],
                    "comments": [],
                    "shares": [],
                    "saves": [],
                    "engagement_total": 0,
                    "top_score": -1.0,
                    "top_output": None,
                },
            )
            add(bucket, row)

    def finish(groups: dict[Any, dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for group in groups.values():
            out.append(
                {
                    "recipe": group["recipe"],
                    "hook_idx": group["hook_idx"],
                    "hook_text": group["hook_text"],
                    "upload_count": group["upload_count"],
                    "avg_views": _avg(group["views"]) or 0,
                    "avg_likes": _avg(group["likes"]) or 0,
                    "avg_comments": _avg(group["comments"]) or 0,
                    "avg_shares": _avg(group["shares"]) or 0,
                    "avg_saves": _avg(group["saves"]) or 0,
                    "engagement_total": group["engagement_total"],
                    "top_output": group["top_output"],
                    "top_score": group["top_score"],
                }
            )
        return sorted(
            out,
            key=lambda item: (
                item["avg_views"],
                item["engagement_total"],
                item["top_score"],
            ),
            reverse=True,
        )[:limit]

    return {
        "hooks": finish(buckets["hooks"]),
        "recipes": finish(buckets["recipes"]),
        "combos": finish(buckets["combos"]),
    }


def soul_metrics_report(root: Path, *, by_account: bool = False) -> dict[str, Any]:
    db_path = Path(root) / "manifest.sqlite"
    if not db_path.exists():
        return {"rows": [], "unattributed_count": 0}
    conn = connect_metrics_db(db_path)
    ensure_metrics_schema(conn)
    select_account = "account, " if by_account else ""
    group_account = ", account" if by_account else ""
    rows = conn.execute(f"""
        SELECT
            {select_account}COALESCE(soul_id, 'unattributed') AS soul_id,
            COUNT(*) AS post_count,
            SUM(COALESCE(views, 0)) AS total_views,
            SUM(COALESCE(likes, 0)) AS total_likes,
            SUM(COALESCE(comments, 0)) AS total_comments,
            SUM(COALESCE(shares, 0)) AS total_shares,
            SUM(COALESCE(saves, 0)) AS total_saves,
            AVG(views) AS mean_views,
            AVG(likes) AS mean_likes,
            AVG(comments) AS mean_comments,
            AVG(shares) AS mean_shares,
            AVG(saves) AS mean_saves
        FROM publish_metrics
        GROUP BY COALESCE(soul_id, 'unattributed'){group_account}
    """).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        engagements = sum(
            int(row[f"total_{metric}"] or 0)
            for metric in ("likes", "comments", "shares", "saves")
        )
        total_views = int(row["total_views"] or 0)
        item = {
            "soul_id": row["soul_id"],
            "post_count": int(row["post_count"] or 0),
            "total_views": total_views,
            "mean_views": _round(row["mean_views"]),
            "total_likes": int(row["total_likes"] or 0),
            "mean_likes": _round(row["mean_likes"]),
            "total_comments": int(row["total_comments"] or 0),
            "mean_comments": _round(row["mean_comments"]),
            "total_shares": int(row["total_shares"] or 0),
            "mean_shares": _round(row["mean_shares"]),
            "total_saves": int(row["total_saves"] or 0),
            "mean_saves": _round(row["mean_saves"]),
            "total_engagements": engagements,
            "engagement_rate": round(engagements / total_views, 4)
            if total_views
            else 0.0,
        }
        if by_account:
            item["account"] = row["account"]
        out.append(item)
    out.sort(
        key=lambda item: (item["mean_views"] or 0, item["total_engagements"]),
        reverse=True,
    )
    return {
        "rows": out,
        "unattributed_count": sum(
            item["post_count"] for item in out if item["soul_id"] == "unattributed"
        ),
    }


def _resolve_metrics_soul_id(
    root: Path,
    conn: sqlite3.Connection,
    filename: str,
    *,
    output_path: str | None = None,
) -> str | None:
    rendered = _resolve_rendered_path(root, conn, filename, output_path=output_path)
    if rendered:
        caption_lineage = _load_json(
            rendered.with_suffix(rendered.suffix + ".caption_lineage.json")
        )
        source_stem = _text(
            _lineage_value(caption_lineage or {}, "source_clip", "sourceClip")
        )
        if not source_stem:
            source_stem = _source_stem_from_rendered(rendered.stem)
        soul_id = _soul_id_from_source_stem(root, source_stem)
        if soul_id:
            return soul_id
    # ponytail: slot identity is a last-resort campaign/account hint, not the
    # true variant on shared-account Stacey/Stacey1 tests.
    return _soul_id_from_posting_slot(conn, rendered)


def _audio_track_id_for_output(output_path: str | None) -> str | None:
    if not output_path:
        return None
    intent = read_audio_intent(Path(output_path))
    if not isinstance(intent, dict):
        return None
    selection = intent.get("audio_selection")
    if isinstance(selection, dict) and selection.get("track_id"):
        return str(selection["track_id"])
    return None


def _resolve_rendered_path(
    root: Path,
    conn: sqlite3.Connection,
    filename: str,
    *,
    output_path: str | None = None,
) -> Path | None:
    if output_path:
        return _project_path(root, output_path)
    row = conn.execute(
        "SELECT output_path FROM variations WHERE output_path LIKE ? LIMIT 1",
        (f"%/{filename}",),
    ).fetchone()
    if row and row["output_path"]:
        return _project_path(root, row["output_path"])
    row = conn.execute(
        "SELECT output_path FROM campaign_outputs WHERE metrics_filename=? LIMIT 1",
        (filename,),
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT output_path FROM campaign_outputs WHERE output_path LIKE ? LIMIT 1",
            (f"%/{filename}",),
        ).fetchone()
    if row and row["output_path"]:
        return _project_path(root, row["output_path"])
    direct = _project_path(root, filename)
    return direct if direct.exists() else None


def _soul_id_from_source_stem(root: Path, source_stem: str | None) -> str | None:
    if not source_stem:
        return None
    source_dir = root / "00_source_videos"
    for suffix in ("generated_asset_lineage", "direct_reference_lineage"):
        path = source_dir / f"{source_stem}.{suffix}.json"
        lineage = _load_json(path)
        soul_id = _text(_lineage_value(lineage or {}, "soulId", "soul_id"))
        if soul_id:
            return soul_id
    return None


def _soul_id_from_posting_slot(
    conn: sqlite3.Connection, rendered: Path | None
) -> str | None:
    if not rendered:
        return None
    try:
        row = conn.execute(
            """
            SELECT soul_id FROM posting_slots
            WHERE rendered_output_path=? AND soul_id IS NOT NULL
            ORDER BY updated_at DESC LIMIT 1
            """,
            (str(rendered.resolve()),),
        ).fetchone()
        if row and row["soul_id"]:
            return row["soul_id"]
        if rendered.exists():
            fp = _sha256_file(rendered)
            row = conn.execute(
                """
                SELECT soul_id FROM posting_slots
                WHERE content_fingerprint=? AND soul_id IS NOT NULL
                ORDER BY updated_at DESC LIMIT 1
                """,
                (fp,),
            ).fetchone()
            if row and row["soul_id"]:
                return row["soul_id"]
    except sqlite3.OperationalError:
        return None
    return None


def _source_stem_from_rendered(stem: str) -> str | None:
    match = re.match(r"^(.+?)_h\d+_v.+?_[^_]+_[A-Za-z0-9]{6,}$", stem)
    if match:
        return match.group(1)
    if "_h" in stem:
        return stem.split("_h", 1)[0]
    return None


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


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _ensure_columns(
    conn: sqlite3.Connection, table: str, columns: dict[str, str]
) -> None:
    existing = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _hook_idx(filename: str) -> int:
    for part in Path(filename).stem.split("_"):
        if part.startswith("h") and part[1:].isdigit():
            return int(part[1:])
    return -1


def _avg(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _round(value: Any) -> float | None:
    return round(float(value), 2) if value is not None else None


def _int(value: str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(float(str(value).replace(",", "")))


def _float(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(str(value).replace(",", ""))


def _int_from_any(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(float(str(value).replace(",", "")))


def _float_from_any(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(str(value).replace(",", ""))


def _text(value: str | None) -> str | None:
    value = "" if value is None else str(value).strip()
    return value or None


def _outcome_dimension(value: Any) -> str:
    return _text(value) or ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="cmd")
    parser.add_argument("--csv")
    import_out = sub.add_parser("import-outcomes")
    import_out.add_argument("csv")
    import_old = sub.add_parser("import")
    import_old.add_argument("csv")
    soul_report = sub.add_parser("soul-report")
    soul_report.add_argument("--by-account", action="store_true")
    refresh_out = sub.add_parser("refresh-outcomes")
    refresh_out.add_argument("--campaign-factory-db", required=True)
    refresh_out.add_argument("--campaign")
    sub.add_parser("outcomes-summary")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.cmd == "import-outcomes":
        result = import_outcomes_csv(root, Path(args.csv).resolve())
    elif args.cmd == "outcomes-summary":
        result = outcomes_summary(root)
    elif args.cmd == "soul-report":
        result = soul_metrics_report(root, by_account=args.by_account)
        _print_soul_report(result["rows"], by_account=args.by_account)
        return
    elif args.cmd == "refresh-outcomes":
        result = refresh_outcomes_from_performance_sync(
            root,
            campaign_factory_db=Path(args.campaign_factory_db).resolve(),
            campaign=args.campaign,
        )
    elif args.cmd == "import":
        result = import_metrics_csv(root, Path(args.csv).resolve())
    elif args.csv:
        result = import_metrics_csv(root, Path(args.csv).resolve())
    else:
        parser.error("provide --csv or a subcommand")
    print(result)


def _print_soul_report(rows: list[dict[str, Any]], *, by_account: bool) -> None:
    headers = ["account"] if by_account else []
    headers += ["soul_id", "posts", "mean_views", "eng_rate", "engagements"]
    print("\t".join(headers))
    for row in rows:
        values = [str(row.get("account") or "")] if by_account else []
        values += [
            str(row["soul_id"]),
            str(row["post_count"]),
            str(row["mean_views"] or 0),
            f"{row['engagement_rate']:.2%}",
            str(row["total_engagements"]),
        ]
        print("\t".join(values))


if __name__ == "__main__":
    main()
