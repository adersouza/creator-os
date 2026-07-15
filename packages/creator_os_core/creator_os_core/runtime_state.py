"""Small, fail-closed helpers for Creator OS runtime-state migration."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_integrity(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    with sqlite3.connect(f"file:{resolved}?mode=ro", uri=True) as conn:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        tables = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        row_counts = {
            str(table): int(
                conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            for (table,) in tables
        }
    return {"integrity": integrity, "rowCounts": row_counts}


def sqlite_snapshot(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    checks = sqlite_integrity(resolved)
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "bytes": stat.st_size,
        "sha256": sha256_file(resolved),
        "mode": oct(stat.st_mode & 0o777),
        **checks,
    }


def ensure_private_dir(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(resolved, 0o700)
    return resolved


def vacuum_into(source: Path, destination: Path) -> None:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    ensure_private_dir(destination.parent)
    if destination.exists():
        raise FileExistsError(f"refusing to replace existing database: {destination}")
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as conn:
        conn.execute("VACUUM main INTO ?", (str(destination),))


def verified_vacuum_copy(source: Path, destination: Path) -> dict[str, Any]:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    before = sqlite_snapshot(source)
    if before["integrity"] != "ok":
        raise RuntimeError(f"source SQLite integrity check failed: {source}")

    ensure_private_dir(destination.parent)
    temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
    try:
        vacuum_into(source, temporary)
        os.chmod(temporary, 0o600)
        after = sqlite_snapshot(temporary)
        if after["integrity"] != "ok" or after["rowCounts"] != before["rowCounts"]:
            raise RuntimeError(f"SQLite copy verification failed: {source}")
        if destination.exists():
            raise FileExistsError(
                f"refusing to replace existing database: {destination}"
            )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    restored = verify_clean_restore(destination)
    return {
        "source": before,
        "destination": sqlite_snapshot(destination),
        "cleanRestore": restored,
    }


def verify_clean_restore(path: Path) -> dict[str, Any]:
    source = path.expanduser().resolve()
    expected = sqlite_integrity(source)
    with tempfile.TemporaryDirectory(prefix="creator-os-restore-") as directory:
        restored = Path(directory) / source.name
        vacuum_into(source, restored)
        checks = sqlite_integrity(restored)
    if checks != expected:
        raise RuntimeError(f"clean restore verification failed: {source}")
    return checks
