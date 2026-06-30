"""Manual publish metrics import and reporting."""

from __future__ import annotations

import argparse
import csv
import sqlite3
import time
from pathlib import Path
from typing import Any

from campaign_store import ensure_campaign_schema, slugify
from intelligence_store import ensure_intelligence_schema, winner_score

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
            imported_at INTEGER NOT NULL
        )
    """)
    ensure_intelligence_schema(conn)


def import_metrics_csv(root: Path, csv_path: Path) -> dict[str, Any]:
    db_path = Path(root) / "manifest.sqlite"
    if not db_path.exists():
        raise FileNotFoundError(f"manifest.sqlite not found under {root}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_metrics_schema(conn)
    ensure_campaign_schema(conn)

    known = {
        Path(row["output_path"]).name
        for row in conn.execute(
            "SELECT output_path FROM variations WHERE status = 'ok'"
        )
    }
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
            conn.execute(
                """
                INSERT INTO publish_metrics (
                    filename, platform, account, uploaded_at, views, likes,
                    comments, shares, saves, manual_score, notes, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    int(time.time()),
                ),
            )
            output_row = conn.execute(
                "SELECT output_path, job_key, caption_text, recipe, review_state FROM variations WHERE output_path LIKE ? LIMIT 1",
                (f"%/{filename}",),
            ).fetchone()
            if output_row:
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
                        f"out_{slugify(Path(output_row['output_path']).stem)}",
                        output_row["output_path"],
                        output_row["job_key"],
                        output_row["caption_text"],
                        output_row["recipe"],
                        output_row["review_state"],
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
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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
                "SELECT * FROM campaign_outputs WHERE output_path LIKE ? OR metrics_filename=? LIMIT 1",
                (f"%/{filename}", filename),
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
            account = _text(row.get("account"))
            posted_at = _text(
                row.get("posted_at") or row.get("uploaded_at") or row.get("date")
            )
            outcome_id = f"outcome_{slugify(filename)}_{slugify(platform or 'platform')}_{slugify(account or 'account')}_{slugify(posted_at or 'unknown')}"
            payload = (
                outcome_id,
                filename,
                output_path,
                variation["job_key"] if variation else None,
                campaign_output["campaign_output_id"] if campaign_output else None,
                campaign_output["campaign_id"] if campaign_output else None,
                campaign_output["asset_generation_id"] if campaign_output else None,
                prompt_run_id,
                source_reference_id,
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
                    outcome_id, filename, output_path, job_key, campaign_output_id,
                    campaign_id, asset_generation_id, prompt_run_id, source_reference_id,
                    platform, account, posted_at, views, likes, comments, shares, saves,
                    watch_time, retention_rate, profile_visits, follows, manual_score,
                    source_url, notes, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(filename, platform, account, posted_at) DO UPDATE SET
                    output_path=excluded.output_path,
                    job_key=excluded.job_key,
                    campaign_output_id=excluded.campaign_output_id,
                    campaign_id=excluded.campaign_id,
                    asset_generation_id=excluded.asset_generation_id,
                    prompt_run_id=excluded.prompt_run_id,
                    source_reference_id=excluded.source_reference_id,
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
                    comments, shares, saves, manual_score, notes, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def outcomes_summary(root: Path, limit: int = 10) -> dict[str, Any]:
    db_path = Path(root) / "manifest.sqlite"
    if not db_path.exists():
        return {"count": 0, "top": [], "totals": {}}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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
        FROM publish_metrics m
        JOIN variations v ON substr(v.output_path, length(v.output_path) - length(m.filename) + 1) = m.filename
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
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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
        FROM publish_metrics m
        JOIN variations v ON substr(v.output_path, length(v.output_path) - length(m.filename) + 1) = m.filename
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


def _hook_idx(filename: str) -> int:
    for part in Path(filename).stem.split("_"):
        if part.startswith("h") and part[1:].isdigit():
            return int(part[1:])
    return -1


def _avg(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _int(value: str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(float(str(value).replace(",", "")))


def _float(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(str(value).replace(",", ""))


def _text(value: str | None) -> str | None:
    value = "" if value is None else str(value).strip()
    return value or None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="cmd")
    parser.add_argument("--csv")
    import_out = sub.add_parser("import-outcomes")
    import_out.add_argument("csv")
    import_old = sub.add_parser("import")
    import_old.add_argument("csv")
    sub.add_parser("outcomes-summary")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.cmd == "import-outcomes":
        result = import_outcomes_csv(root, Path(args.csv).resolve())
    elif args.cmd == "outcomes-summary":
        result = outcomes_summary(root)
    elif args.cmd == "import":
        result = import_metrics_csv(root, Path(args.csv).resolve())
    elif args.csv:
        result = import_metrics_csv(root, Path(args.csv).resolve())
    else:
        parser.error("provide --csv or a subcommand")
    print(result)


if __name__ == "__main__":
    main()
