#!/usr/bin/env python3
"""Back up local Creator OS runtime state without mutating source data."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DB_PATHS = (
    ("reel_manifest", Path("python_packages/reel_factory/manifest.sqlite")),
    ("render_queue", Path("python_packages/reel_factory/render_queue.sqlite")),
    (
        "campaign_factory",
        Path("python_packages/campaign_factory/campaign_factory.sqlite"),
    ),
    (
        "reference_factory",
        Path("python_packages/reference_factory/reference_factory.sqlite"),
    ),
)

DIR_PATHS = (
    ("identity_references", Path("python_packages/reel_factory/identity_references")),
    ("project_data", Path("python_packages/reel_factory/project_data")),
    ("caption_banks", Path("python_packages/reel_factory/caption_banks")),
    ("audio_library", Path("python_packages/reel_factory/03_audio_library")),
    ("reference_factory_data", Path("python_packages/reference_factory/data")),
)

MANIFEST_NAME = "backup-manifest.json"
CREDENTIAL_PATTERNS = ("secrets.toml", "*.env", "*.pem", "*.key")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_integrity(path: Path) -> dict[str, Any]:
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        row_counts = {
            table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for (table,) in tables
        }
    return {"integrity": integrity, "rowCounts": row_counts}


def vacuum_into(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True) as conn:
        conn.execute("VACUUM main INTO ?", (str(dest),))


def backup_runtime_state(
    repo_root: Path, output_dir: Path, *, timestamp: str | None = None
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    stamp = timestamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = output_dir.expanduser().resolve() / stamp
    target.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "createdAt": datetime.now(UTC).isoformat(),
        "backupDir": str(target),
        "databases": [],
        "directories": [],
    }

    for name, rel in DB_PATHS:
        source = repo_root / rel
        entry = {"name": name, "source": str(source), "status": "missing"}
        if source.exists():
            dest = target / "databases" / rel.name
            vacuum_into(source, dest)
            verification = sqlite_integrity(dest)
            if verification["integrity"] != "ok":
                raise RuntimeError(f"SQLite integrity check failed: {dest}")
            entry |= {
                "status": "backed_up",
                "path": str(dest.relative_to(target)),
                "bytes": dest.stat().st_size,
                "sha256": sha256_file(dest),
                **verification,
            }
        result["databases"].append(entry)

    for name, rel in DIR_PATHS:
        source = repo_root / rel
        entry = {"name": name, "source": str(source), "status": "missing"}
        if source.exists():
            dest = target / rel
            shutil.copytree(
                source,
                dest,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(*CREDENTIAL_PATTERNS),
            )
            entry |= {"status": "backed_up", "path": str(dest.relative_to(target))}
        result["directories"].append(entry)

    manifest = target / MANIFEST_NAME
    manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def verify_backup(backup_dir: Path) -> dict[str, Any]:
    backup_dir = backup_dir.expanduser().resolve()
    manifest_path = backup_dir / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verified: list[dict[str, Any]] = []
    for entry in manifest["databases"]:
        if entry["status"] != "backed_up":
            continue
        path = backup_dir / entry["path"]
        actual_hash = sha256_file(path)
        checks = sqlite_integrity(path)
        if actual_hash != entry["sha256"] or checks["integrity"] != "ok":
            raise RuntimeError(f"Backup verification failed: {entry['name']}")
        verified.append({"name": entry["name"], "sha256": actual_hash, **checks})
    return {"backupDir": str(backup_dir), "status": "ok", "databases": verified}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "backups" / "runtime",
    )
    parser.add_argument(
        "--verify",
        type=Path,
        help="Verify an existing backup directory without touching live state",
    )
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_backup(args.verify), indent=2))
        return 0
    print(json.dumps(backup_runtime_state(args.repo_root, args.output_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
