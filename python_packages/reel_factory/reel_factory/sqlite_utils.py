"""Shared SQLite opener defaults for Reel Factory local databases."""

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
