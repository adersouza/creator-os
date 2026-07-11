"""Shared SQLite opener + schema helpers for Creator OS local databases."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def connect_sqlite(
    db_path: str | Path,
    *,
    readonly: bool = False,
    row_factory: Any = sqlite3.Row,
    wal: bool = True,
    busy_timeout_ms: int = 30_000,
) -> sqlite3.Connection:
    path = Path(db_path).expanduser()
    if readonly:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", timeout=30.0, uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = row_factory
    conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
    if wal and not readonly:
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_columns(
    conn: sqlite3.Connection, table: str, columns: dict[str, str]
) -> None:
    """Idempotently add missing ``columns`` (name -> DDL) to ``table``.

    Superset of the three factory copies this replaces:

    - Skips silently when ``table`` does not exist (reel_factory parity).
    - Guards on the existing-column set so unchanged schemas are a no-op.
    - Tolerates a concurrent "duplicate column name" ``OperationalError``
      (campaign_factory parity); any other operational error propagates.
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if not exists:
        return
    existing = {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, ddl in columns.items():
        if name not in existing:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
