#!/usr/bin/env python3
"""Back up local Creator OS runtime state without mutating source data."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/creator_os_core"))

from creator_os_core.runtime_paths import resolve_runtime_paths
from creator_os_core.runtime_state import (
    sha256_file,
    sqlite_integrity,
    vacuum_into,
)
from creator_os_core.runtime_state_evidence import (
    load_json_manifest,
    verify_sqlite_evidence,
)

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


def backup_runtime_state(
    repo_root: Path,
    output_dir: Path,
    *,
    timestamp: str | None = None,
    database_sources: tuple[tuple[str, Path, Path], ...] | None = None,
    directory_sources: tuple[tuple[str, Path, Path], ...] | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    stamp = timestamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = output_dir.expanduser().resolve() / stamp
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target, 0o700)
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "createdAt": datetime.now(UTC).isoformat(),
        "backupDir": str(target),
        "databases": [],
        "directories": [],
    }

    databases = database_sources or tuple(
        (name, repo_root / rel, Path(rel.name)) for name, rel in DB_PATHS
    )
    directories = directory_sources or tuple(
        (name, repo_root / rel, rel) for name, rel in DIR_PATHS
    )

    for name, source, backup_rel in databases:
        entry: dict[str, Any] = {
            "name": name,
            "source": str(source),
            "status": "missing",
        }
        if source.exists():
            dest = target / "databases" / backup_rel
            vacuum_into(source, dest)
            dest.chmod(0o600)
            verification = sqlite_integrity(dest)
            if verification["integrity"] != "ok":
                raise RuntimeError(f"SQLite integrity check failed: {dest}")
            entry |= {
                "status": "backed_up",
                "path": str(dest.relative_to(target)),
                "bytes": dest.stat().st_size,
                "sha256": sha256_file(dest),
                "mode": oct(dest.stat().st_mode & 0o777),
                **verification,
            }
        result["databases"].append(entry)

    for name, source, backup_rel in directories:
        entry = {"name": name, "source": str(source), "status": "missing"}
        if source.exists():
            dest = target / backup_rel
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
    os.chmod(manifest, 0o600)
    return result


def backup_configured_runtime_state(
    output_dir: Path, *, timestamp: str | None = None
) -> dict[str, Any]:
    paths = resolve_runtime_paths(Path(__file__).resolve().parents[1])
    databases = (
        (
            "campaign_factory",
            paths.campaign_factory_db,
            Path("campaign_factory.sqlite"),
        ),
        (
            "reference_factory",
            paths.reference_factory_db,
            Path("reference_factory.sqlite"),
        ),
        ("reel_manifest", paths.reel_manifest_db, Path("manifest.sqlite")),
        ("render_queue", paths.reel_render_queue_db, Path("render_queue.sqlite")),
    )
    directories = (
        ("artifacts", paths.artifact_root, Path("artifacts")),
        ("models", paths.model_root, Path("models")),
        ("logs", paths.log_root, Path("logs")),
    )
    return backup_runtime_state(
        paths.source_root,
        output_dir,
        timestamp=timestamp,
        database_sources=databases,
        directory_sources=directories,
    )


def verify_backup(backup_dir: Path) -> dict[str, Any]:
    backup_dir = backup_dir.expanduser().resolve()
    manifest_path = backup_dir / MANIFEST_NAME
    _, manifest = load_json_manifest(manifest_path)
    verified: list[dict[str, Any]] = []
    for entry in manifest["databases"]:
        if entry["status"] != "backed_up":
            continue
        path = backup_dir / entry["path"]
        evidence = verify_sqlite_evidence(
            path,
            expected_sha256=entry["sha256"],
            required_mode="0o600",
            require_clean_restore=True,
        )
        if not evidence["valid"]:
            raise RuntimeError(f"Backup verification failed: {entry['name']}")
        snapshot = evidence["snapshot"]
        verified.append(
            {
                "name": entry["name"],
                "sha256": snapshot["sha256"],
                "mode": snapshot["mode"],
                "integrity": snapshot["integrity"],
                "rowCounts": snapshot["rowCounts"],
                "cleanRestore": evidence["cleanRestore"],
            }
        )
    return {"backupDir": str(backup_dir), "status": "ok", "databases": verified}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="legacy explicit checkout-root backup; configured roots are the default",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / ".creator-os/backups/runtime",
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
    result = (
        backup_runtime_state(args.repo_root, args.output_dir)
        if args.repo_root is not None
        else backup_configured_runtime_state(args.output_dir)
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
