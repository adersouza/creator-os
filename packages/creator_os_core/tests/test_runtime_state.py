from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from creator_os_core.runtime_state import (
    sqlite_snapshot,
    verified_vacuum_copy,
)


def _database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
        conn.executemany("INSERT INTO items (value) VALUES (?)", (("one",), ("two",)))


def test_verified_vacuum_copy_preserves_rows_and_is_private(tmp_path: Path) -> None:
    source = tmp_path / "legacy/source.sqlite"
    destination = tmp_path / "state/component/state.sqlite"
    _database(source)

    result = verified_vacuum_copy(source, destination)

    assert result["source"]["rowCounts"] == {"items": 2}
    assert result["destination"]["rowCounts"] == {"items": 2}
    assert result["destination"]["mode"] == "0o600"
    assert result["cleanRestore"] == {"integrity": "ok", "rowCounts": {"items": 2}}
    assert destination.parent.stat().st_mode & 0o077 == 0


def test_verified_vacuum_copy_never_overwrites_existing_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    destination = tmp_path / "destination.sqlite"
    _database(source)
    _database(destination)

    with pytest.raises(FileExistsError, match="refusing to replace"):
        verified_vacuum_copy(source, destination)

    assert sqlite_snapshot(destination)["rowCounts"] == {"items": 2}


def test_verified_vacuum_copy_rejects_non_database(tmp_path: Path) -> None:
    source = tmp_path / "not-a-database.sqlite"
    source.write_text("not sqlite", encoding="utf-8")

    with pytest.raises(sqlite3.DatabaseError):
        verified_vacuum_copy(source, tmp_path / "state.sqlite")
