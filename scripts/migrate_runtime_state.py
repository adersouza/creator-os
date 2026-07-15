#!/usr/bin/env python3
"""Copy Creator OS runtime state out of Git checkouts with verified rollback proof."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/creator_os_core"))

from creator_os_core.runtime_paths import RuntimePaths, resolve_runtime_paths
from creator_os_core.runtime_state import (
    ensure_private_dir,
    sqlite_snapshot,
    verified_vacuum_copy,
)
from creator_os_core.runtime_state_evidence import (
    DEFAULT_PRIVATE_PATTERNS,
    load_json_manifest,
    single_file_tree_snapshot,
    tree_snapshot,
    verify_sqlite_evidence,
)

SCHEMA = "creator_os.runtime_state_migration.v1"
MANIFEST_NAME = "migration-manifest.json"
PRIVATE_PATTERNS = DEFAULT_PRIVATE_PATTERNS


def _private_copy(source: Path, destination: Path, *, logs_only: bool) -> None:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to merge into existing path: {destination}")
    ensure_private_dir(destination.parent)

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = set(shutil.ignore_patterns(*PRIVATE_PATTERNS)(directory, names))
        if logs_only:
            base = Path(directory)
            ignored.update(
                name
                for name in names
                if (base / name).is_file() and not name.endswith(".log")
            )
        return ignored

    if source.is_dir():
        shutil.copytree(source, destination, ignore=ignore)
    elif source.is_file():
        if logs_only and not source.name.endswith(".log"):
            raise ValueError(f"log source is not a .log file: {source}")
        destination.mkdir(mode=0o700)
        shutil.copy2(source, destination / source.name)
    else:
        raise FileNotFoundError(source)
    for directory in [destination, *destination.rglob("*")]:
        if directory.is_dir():
            os.chmod(directory, 0o700)
        elif directory.is_file():
            os.chmod(directory, 0o600)


def _database_destinations(paths: RuntimePaths) -> dict[str, Path]:
    return {
        "campaign_factory": paths.campaign_factory_db,
        "reference_factory": paths.reference_factory_db,
        "reel_manifest": paths.reel_manifest_db,
        "render_queue": paths.reel_render_queue_db,
    }


def _directory_destination(paths: RuntimePaths, kind: str, label: str) -> Path:
    if kind == "artifact":
        return paths.artifact_root / "media" / label
    if kind == "identity":
        return paths.artifact_root / "identity_references" / label
    if kind == "model":
        return paths.model_root / label
    if kind == "log":
        return paths.log_root / label
    raise ValueError(f"unknown directory kind: {kind}")


def migration_plan(
    *,
    database_sources: dict[str, Path],
    directory_sources: list[tuple[str, str, Path]],
    paths: RuntimePaths,
) -> dict[str, Any]:
    destinations = _database_destinations(paths)
    required = set(destinations)
    if set(database_sources) != required:
        missing = sorted(required - set(database_sources))
        extra = sorted(set(database_sources) - required)
        raise ValueError(f"database sources mismatch: missing={missing}, extra={extra}")
    databases = []
    for name, destination in destinations.items():
        source = database_sources[name].expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if source == destination:
            raise ValueError(f"source is already canonical for {name}: {source}")
        databases.append(
            {
                "name": name,
                "source": str(source),
                "destination": str(destination),
                "sourceSnapshot": sqlite_snapshot(source),
                "destinationExists": destination.exists(),
            }
        )
    directories = []
    seen_destinations: set[Path] = set()
    for kind, label, raw_source in directory_sources:
        source = raw_source.expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(source)
        destination = _directory_destination(paths, kind, label)
        if source.is_dir() and destination.is_relative_to(source):
            raise ValueError(
                f"destination cannot be nested inside its source: {destination}"
            )
        if destination in seen_destinations:
            raise ValueError(f"duplicate destination: {destination}")
        seen_destinations.add(destination)
        directories.append(
            {
                "kind": kind,
                "label": label,
                "source": str(source),
                "destination": str(destination),
                "destinationExists": destination.exists(),
            }
        )
    return {
        "schema": SCHEMA,
        "status": "planned",
        "createdAt": datetime.now(UTC).isoformat(),
        "preserveOriginals": True,
        "minimumRollbackDays": 7,
        "preserveThroughOperatingCycle": True,
        "canonicalRoots": {
            "state": str(paths.state_root),
            "artifacts": str(paths.artifact_root),
            "models": str(paths.model_root),
            "logs": str(paths.log_root),
        },
        "databases": databases,
        "directories": directories,
    }


def apply_migration(
    plan: dict[str, Any], evidence_root: Path, *, timestamp: str | None = None
) -> dict[str, Any]:
    if any(row["destinationExists"] for row in plan["databases"]):
        raise FileExistsError("one or more database destinations already exist")
    if any(row["destinationExists"] for row in plan["directories"]):
        raise FileExistsError("one or more directory destinations already exist")

    stamp = timestamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence_dir = ensure_private_dir(evidence_root / stamp)
    result = dict(plan)
    result["status"] = "migrated"
    result["appliedAt"] = datetime.now(UTC).isoformat()
    result["rollbackRetainUntil"] = (datetime.now(UTC) + timedelta(days=7)).isoformat()

    for row in result["databases"]:
        row["verification"] = verified_vacuum_copy(
            Path(row["source"]), Path(row["destination"])
        )
    for row in result["directories"]:
        source = Path(row["source"])
        destination = Path(row["destination"])
        before = (
            tree_snapshot(
                source,
                logs_only=row["kind"] == "log",
                exclude_private=True,
            )
            if source.is_dir()
            else single_file_tree_snapshot(source)
        )
        _private_copy(source, destination, logs_only=row["kind"] == "log")
        after = tree_snapshot(destination)
        if (
            before["files"] != after["files"]
            or before["bytes"] != after["bytes"]
            or before["treeSha256"] != after["treeSha256"]
        ):
            raise RuntimeError(f"directory copy verification failed: {source}")
        row["sourceSnapshot"] = before
        row["destinationSnapshot"] = after

    manifest = evidence_dir / MANIFEST_NAME
    manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    os.chmod(manifest, 0o600)
    result["manifest"] = str(manifest)
    return result


def verify_migration(manifest_path: Path) -> dict[str, Any]:
    manifest_path, manifest = load_json_manifest(manifest_path)
    if manifest.get("schema") != SCHEMA or manifest.get("status") != "migrated":
        raise ValueError("not a completed Creator OS state migration manifest")
    databases = []
    for row in manifest["databases"]:
        expected = row["verification"]["destination"]
        evidence = verify_sqlite_evidence(
            Path(row["destination"]),
            expected_row_counts=expected["rowCounts"],
            required_mode="0o600",
        )
        if not evidence["valid"]:
            raise RuntimeError(f"database verification failed: {row['name']}")
        databases.append({"name": row["name"], "snapshot": evidence["snapshot"]})
    directories = []
    for row in manifest["directories"]:
        snapshot = tree_snapshot(Path(row["destination"]))
        expected = row["destinationSnapshot"]
        if snapshot != expected:
            raise RuntimeError(f"directory verification failed: {row['label']}")
        directories.append({"label": row["label"], "snapshot": snapshot})
    return {
        "schema": SCHEMA,
        "status": "verified",
        "manifest": str(manifest_path),
        "databases": databases,
        "directories": directories,
    }


def _labeled_sources(values: list[str], kind: str) -> list[tuple[str, str, Path]]:
    parsed = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"{kind} source must be LABEL=PATH: {value}")
        label, raw_path = value.split("=", 1)
        label = label.strip()
        if not label or "/" in label or label in {".", ".."}:
            raise ValueError(f"invalid {kind} label: {label!r}")
        parsed.append((kind, label, Path(raw_path)))
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--campaign-db-source", type=Path)
    parser.add_argument("--reference-db-source", type=Path)
    parser.add_argument("--reel-manifest-source", type=Path)
    parser.add_argument("--render-queue-source", type=Path)
    parser.add_argument("--artifact-source", action="append", default=[])
    parser.add_argument("--identity-source", action="append", default=[])
    parser.add_argument("--model-source", action="append", default=[])
    parser.add_argument("--log-source", action="append", default=[])
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path.home() / ".creator-os/backups/state-migrations",
    )
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_migration(args.verify), indent=2))
        return 0

    source_values = {
        "campaign_factory": args.campaign_db_source,
        "reference_factory": args.reference_db_source,
        "reel_manifest": args.reel_manifest_source,
        "render_queue": args.render_queue_source,
    }
    missing = [name for name, value in source_values.items() if value is None]
    if missing:
        parser.error(f"all four database sources are required; missing {missing}")
    database_sources = {
        name: value for name, value in source_values.items() if value is not None
    }
    directory_sources = [
        *_labeled_sources(args.artifact_source, "artifact"),
        *_labeled_sources(args.identity_source, "identity"),
        *_labeled_sources(args.model_source, "model"),
        *_labeled_sources(args.log_source, "log"),
    ]
    plan = migration_plan(
        database_sources=database_sources,
        directory_sources=directory_sources,
        paths=resolve_runtime_paths(ROOT),
    )
    result = apply_migration(plan, args.evidence_root) if args.apply else plan
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
