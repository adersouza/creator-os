#!/usr/bin/env python3
"""Emit a one-line local Creator OS operations digest."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SYNC_STALE_AFTER = timedelta(hours=3)
BACKUP_STALE_AFTER = timedelta(hours=26)
AUDIO_STALE_AFTER = timedelta(days=14)


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        if value <= 0:
            return None
        return datetime.fromtimestamp(float(value), UTC)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return datetime.fromtimestamp(float(text), UTC)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def format_age(ts: datetime | None, now: datetime) -> str:
    if ts is None:
        return "missing"
    delta = max(now - ts, timedelta())
    if delta >= timedelta(days=1):
        return f"{int(delta.total_seconds() // 86400)}d old"
    if delta >= timedelta(hours=1):
        return f"{int(delta.total_seconds() // 3600)}h old"
    return f"{int(delta.total_seconds() // 60)}m old"


def sqlite_tables(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    try:
        with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[0]) for row in rows}


def outcome_status(repo_root: Path, now: datetime) -> dict[str, Any]:
    db_path = repo_root / "python_packages" / "reel_factory" / "manifest.sqlite"
    if "reel_outcomes" not in sqlite_tables(db_path):
        return {"summary": "outcomes missing", "level": "warn", "total": 0, "delta": 0}
    cutoff = now - timedelta(hours=24)
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        rows = conn.execute("SELECT imported_at FROM reel_outcomes").fetchall()
    imported = [parse_time(row[0]) for row in rows]
    delta = sum(1 for item in imported if item is not None and item >= cutoff)
    total = len(imported)
    return {
        "summary": f"outcomes {total}(+{delta})",
        "level": "info",
        "total": total,
        "delta": delta,
    }


def sync_status(ops_log: Path, now: datetime) -> dict[str, Any]:
    latest: tuple[datetime, str] | None = None
    if ops_log.exists():
        for line in ops_log.read_text(encoding="utf-8", errors="replace").splitlines():
            if "performance-sync" not in line:
                continue
            ts = parse_time(line.split(" ", 1)[0])
            if ts is None:
                continue
            if latest is None or ts > latest[0]:
                latest = (ts, line)
    if latest is None:
        return {"summary": "sync missing", "level": "error", "timestamp": None}
    ts, line = latest
    ok = "[info]" in line and "ok" in line
    stale = now - ts > SYNC_STALE_AFTER
    level = "error" if stale or not ok else "info"
    state = "ok" if ok else "failed"
    return {
        "summary": f"sync {state} {format_age(ts, now)}",
        "level": level,
        "timestamp": ts.isoformat(),
    }


def backup_status(backup_log: Path, now: datetime) -> dict[str, Any]:
    # The backup job appends "<iso-ts> backup ok: <snapshot> ( <size>)" to
    # ~/.creator-os/backup.log after its integrity check passes — that log
    # is the source of truth (snapshots live on iCloud, not in the repo).
    latest: tuple[datetime, str] | None = None
    if backup_log.exists():
        for line in backup_log.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            if "backup ok" not in line:
                continue
            ts = parse_time(line.split(" ", 1)[0])
            if ts is None:
                continue
            if latest is None or ts > latest[0]:
                latest = (ts, line)
    if latest is None:
        return {"summary": "backup missing", "level": "error", "timestamp": None}
    ts, line = latest
    size = line.rsplit("(", 1)[-1].rstrip(")").strip() if "(" in line else ""
    summary = (
        f"backup {size} {format_age(ts, now)}"
        if size
        else f"backup {format_age(ts, now)}"
    )
    level = "error" if now - ts > BACKUP_STALE_AFTER else "info"
    return {
        "summary": summary,
        "level": level,
        "timestamp": ts.isoformat(),
    }


def latest_orchestrator_tick(repo_root: Path) -> dict[str, Any]:
    ticks = (
        repo_root
        / "python_packages"
        / "reel_factory"
        / "project_data"
        / "orchestrator_ticks"
    )
    files = sorted(ticks.glob("*.json")) if ticks.exists() else []
    if not files:
        return {"summary": "gen no tick", "level": "warn"}
    try:
        payload = json.loads(files[-1].read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"summary": "gen tick unreadable", "level": "error"}
    counts = payload.get("stateCounts") if isinstance(payload, dict) else {}
    if not isinstance(counts, dict):
        counts = {}
    planned = int(counts.get("planned", 0))
    inbox = int(counts.get("awaiting_approval", 0))
    return {
        "summary": f"gen planned {planned} inbox {inbox}",
        "level": "info",
        "stateCounts": counts,
    }


def reference_db_paths(repo_root: Path) -> list[Path]:
    return [
        repo_root
        / "python_packages"
        / "reference_factory"
        / "reference_factory.sqlite",
        Path.home() / "Developer" / "reference_reels" / "reference_factory.sqlite",
    ]


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def audio_status(repo_root: Path, now: datetime) -> dict[str, Any]:
    db_path = first_existing(reference_db_paths(repo_root))
    if db_path is None or "audio_catalog" not in sqlite_tables(db_path):
        return {"summary": "audio missing", "level": "error", "timestamp": None}
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        # audio_catalog has no imported_at; updated_at is bumped on every
        # refresh-tiktok-audio run, which is exactly the freshness signal.
        row = conn.execute("SELECT MAX(updated_at) FROM audio_catalog").fetchone()
    ts = parse_time(row[0] if row else None)
    level = "error" if ts is None or now - ts > AUDIO_STALE_AFTER else "info"
    return {
        "summary": f"audio {format_age(ts, now)}",
        "level": level,
        "timestamp": ts.isoformat() if ts else None,
    }


def reference_status(repo_root: Path) -> dict[str, Any]:
    db_path = first_existing(reference_db_paths(repo_root))
    if db_path is None:
        return {"summary": "refs missing", "level": "warn", "rows": 0}
    tables = sqlite_tables(db_path)
    if not tables:
        return {"summary": "refs unreadable", "level": "warn", "rows": 0}
    total = 0
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        for table in tables:
            if table.startswith("sqlite_"):
                continue
            try:
                total += int(
                    conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                )
            except sqlite3.Error:
                continue
    return {"summary": f"refs {total}", "level": "info", "rows": total}


def digest(
    repo_root: Path,
    ops_log: Path,
    *,
    backup_log: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp = now or utc_now()
    if backup_log is None:
        backup_log = Path.home() / ".creator-os" / "backup.log"
    checks = [
        outcome_status(repo_root, timestamp),
        sync_status(ops_log, timestamp),
        backup_status(backup_log, timestamp),
        latest_orchestrator_tick(repo_root),
        audio_status(repo_root, timestamp),
        reference_status(repo_root),
    ]
    level = "error" if any(check["level"] == "error" for check in checks) else "info"
    line = " | ".join(str(check["summary"]) for check in checks)
    return {
        "schema": "creator_os.ops_digest.v1",
        "timestamp": timestamp.isoformat(),
        "level": level,
        "line": line,
        "checks": checks,
    }


def send_notify(notify_path: Path, level: str, line: str) -> None:
    if not notify_path.exists():
        return
    subprocess.run(
        [str(notify_path), level, "ops-digest", line],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--ops-log",
        type=Path,
        default=Path.home() / ".creator-os" / "ops.log",
    )
    parser.add_argument(
        "--notify",
        type=Path,
        default=Path.home() / ".creator-os" / "notify.sh",
    )
    parser.add_argument(
        "--backup-log",
        type=Path,
        default=Path.home() / ".creator-os" / "backup.log",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    result = digest(
        args.repo_root.resolve(),
        args.ops_log.expanduser(),
        backup_log=args.backup_log.expanduser(),
    )
    print(result["line"])
    if not args.dry_run:
        send_notify(args.notify.expanduser(), result["level"], result["line"])
    return 1 if result["level"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
