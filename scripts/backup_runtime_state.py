#!/usr/bin/env python3
"""Back up local Creator OS runtime state without mutating source data."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DB_PATHS = (
    ("reel_manifest", Path("python_packages/reel_factory/manifest.sqlite")),
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
    ("models", Path("python_packages/reel_factory/models")),
    ("audio_library", Path("python_packages/reel_factory/03_audio_library")),
)


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
            entry |= {"status": "backed_up", "path": str(dest)}
        result["databases"].append(entry)

    for name, rel in DIR_PATHS:
        source = repo_root / rel
        entry = {"name": name, "source": str(source), "status": "missing"}
        if source.exists():
            dest = target / rel
            shutil.copytree(source, dest, dirs_exist_ok=True)
            entry |= {"status": "backed_up", "path": str(dest)}
        result["directories"].append(entry)

    return result


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
    args = parser.parse_args()
    print(json.dumps(backup_runtime_state(args.repo_root, args.output_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
