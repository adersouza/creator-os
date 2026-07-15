#!/usr/bin/env python3
"""Report whether retained pre-cutover state is eligible for operator cleanup.

This command is deliberately incapable of deleting data. It validates every
cleanup precondition and emits candidate paths for a later, separately approved
operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/creator_os_core"))

from creator_os_core.runtime_state import (  # noqa: E402
    sha256_file,
    sqlite_snapshot,
    verify_clean_restore,
)

REPORT_SCHEMA = "creator_os.runtime_state_cleanup_eligibility.v1"
MIGRATION_SCHEMA = "creator_os.runtime_state_migration.v1"
OPERATING_CYCLE_SCHEMA = "creator_os.operating_cycle_evidence.v1"
BACKUP_MANIFEST_NAME = "backup-manifest.json"
PRIVATE_PATTERNS = ("*.env", "*.key", "*.pem", "secrets.toml")
OPERATING_CYCLE_CHECKS = (
    "runtimeShaMatched",
    "performanceSyncSucceeded",
    "learningFanoutObserved",
)
EXPECTED_DATABASES = {
    "campaign_factory",
    "reference_factory",
    "reel_manifest",
    "render_queue",
}


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value}")
    return parsed.astimezone(UTC)


def _tree_snapshot(path: Path, *, exclude_private: bool = False) -> dict[str, Any]:
    path = path.expanduser().resolve()
    files: list[Path] = []

    def collect(directory: Path, ancestors: frozenset[Path]) -> None:
        resolved = directory.resolve()
        if resolved in ancestors:
            raise ValueError(f"directory symlink cycle detected: {directory}")
        nested_ancestors = ancestors | {resolved}
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            item = Path(entry.path)
            if entry.is_dir(follow_symlinks=True):
                collect(item, nested_ancestors)
            elif entry.is_file(follow_symlinks=True) and not (
                exclude_private
                and any(item.match(pattern) for pattern in PRIVATE_PATTERNS)
            ):
                files.append(item)

    collect(path, frozenset())
    digest = hashlib.sha256()
    total_bytes = 0
    for item in sorted(files):
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(sha256_file(item).encode("ascii"))
        total_bytes += item.stat().st_size
    return {
        "path": str(path),
        "files": len(files),
        "bytes": total_bytes,
        "treeSha256": digest.hexdigest(),
    }


def _check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "status": "PASS" if passed else "FAIL", **evidence}


def _verify_manifest_safety(migration: dict[str, Any]) -> dict[str, Any]:
    database_names = {row.get("name") for row in migration.get("databases", [])}
    passed = (
        database_names == EXPECTED_DATABASES
        and migration.get("preserveOriginals") is True
        and migration.get("preserveThroughOperatingCycle") is True
    )
    return _check(
        "migration-manifest-safety",
        passed,
        {
            "databaseNames": sorted(str(name) for name in database_names),
            "preserveOriginals": migration.get("preserveOriginals"),
            "preserveThroughOperatingCycle": migration.get(
                "preserveThroughOperatingCycle"
            ),
        },
    )


def _verify_operating_cycle(
    evidence_path: Path, migration: dict[str, Any], now: datetime
) -> dict[str, Any]:
    if not evidence_path.is_file():
        return _check(
            "operating-cycle",
            False,
            {"reason": "evidence file is missing", "path": str(evidence_path)},
        )
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        completed_at = _parse_time(str(evidence["completedAt"]))
        applied_at = _parse_time(str(migration["appliedAt"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _check(
            "operating-cycle",
            False,
            {"reason": f"invalid evidence: {exc}", "path": str(evidence_path)},
        )
    checks = evidence.get("checks") or {}
    passed = (
        evidence.get("schema") == OPERATING_CYCLE_SCHEMA
        and evidence.get("status") == "PASS"
        and applied_at <= completed_at <= now
        and all(checks.get(name) is True for name in OPERATING_CYCLE_CHECKS)
    )
    return _check(
        "operating-cycle",
        passed,
        {
            "path": str(evidence_path.resolve()),
            "completedAt": completed_at.isoformat(),
            "requiredChecks": {
                name: checks.get(name) for name in OPERATING_CYCLE_CHECKS
            },
        },
    )


def _verify_originals(
    migration: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    passed = True
    for row in migration.get("databases", []):
        source = Path(row["source"]).expanduser().resolve()
        expected = row["verification"]["source"]
        try:
            current = sqlite_snapshot(source)
            exact = (
                current["integrity"] == "ok"
                and current["sha256"] == expected["sha256"]
                and current["rowCounts"] == expected["rowCounts"]
            )
        except (FileNotFoundError, OSError, sqlite3.DatabaseError):
            current = None
            exact = False
        passed = passed and exact
        rows.append(
            {
                "kind": "database",
                "name": row["name"],
                "path": str(source),
                "exactCutoverSnapshot": exact,
            }
        )
        candidates.append(
            {"kind": "database", "name": row["name"], "path": str(source)}
        )

    for row in migration.get("directories", []):
        source = Path(row["source"]).expanduser().resolve()
        if row["kind"] == "log":
            rows.append(
                {
                    "kind": "log",
                    "name": row["label"],
                    "path": str(source),
                    "retained": True,
                    "reason": "active log paths are never cleanup candidates",
                }
            )
            continue
        expected = row["sourceSnapshot"]
        try:
            current = _tree_snapshot(source, exclude_private=True)
            exact = all(
                current[key] == expected[key]
                for key in ("files", "bytes", "treeSha256")
            )
        except (FileNotFoundError, OSError, ValueError):
            exact = False
        passed = passed and exact
        rows.append(
            {
                "kind": row["kind"],
                "name": row["label"],
                "path": str(source),
                "exactCutoverSnapshot": exact,
            }
        )
        candidates.append(
            {"kind": row["kind"], "name": row["label"], "path": str(source)}
        )
    return _check("original-snapshots", passed, {"items": rows}), candidates


def _verify_canonical_databases(migration: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    passed = True
    for row in migration.get("databases", []):
        destination = Path(row["destination"]).expanduser().resolve()
        try:
            current = sqlite_snapshot(destination)
            restore = verify_clean_restore(destination)
            valid = (
                current["integrity"] == "ok"
                and current["mode"] == "0o600"
                and oct(destination.parent.stat().st_mode & 0o777) == "0o700"
                and restore["integrity"] == "ok"
            )
            evidence = {
                "name": row["name"],
                "path": str(destination),
                "integrity": current["integrity"],
                "mode": current["mode"],
                "parentMode": oct(destination.parent.stat().st_mode & 0o777),
                "cleanRestore": restore["integrity"],
                "rowCountsChangedSinceCutover": current["rowCounts"]
                != row["verification"]["destination"]["rowCounts"],
            }
        except (FileNotFoundError, OSError, sqlite3.DatabaseError, RuntimeError) as exc:
            valid = False
            evidence = {
                "name": row["name"],
                "path": str(destination),
                "error": str(exc),
            }
        passed = passed and valid
        rows.append(evidence)
    return _check("canonical-databases", passed, {"databases": rows})


def _verify_backup(
    backup_dir: Path,
    migration: dict[str, Any],
    now: datetime,
    max_age: timedelta,
) -> dict[str, Any]:
    backup_dir = backup_dir.expanduser().resolve()
    manifest_path = backup_dir / BACKUP_MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        created_at = _parse_time(str(manifest["createdAt"]))
    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        return _check(
            "fresh-backup-restore",
            False,
            {"path": str(backup_dir), "reason": f"invalid backup manifest: {exc}"},
        )

    expected_sources = {
        row["name"]: str(Path(row["destination"]).expanduser().resolve())
        for row in migration.get("databases", [])
    }
    rows: list[dict[str, Any]] = []
    found: set[str] = set()
    manifest_mode = oct(manifest_path.stat().st_mode & 0o777)
    backup_mode = oct(backup_dir.stat().st_mode & 0o777)
    passed = (
        timedelta(0) <= now - created_at <= max_age
        and manifest_mode == "0o600"
        and backup_mode == "0o700"
    )
    for entry in manifest.get("databases", []):
        name = entry.get("name")
        if name not in expected_sources or entry.get("status") != "backed_up":
            continue
        found.add(name)
        path = backup_dir / entry["path"]
        try:
            snapshot = sqlite_snapshot(path)
            restore = verify_clean_restore(path)
            valid = (
                str(Path(entry["source"]).expanduser().resolve())
                == expected_sources[name]
                and snapshot["sha256"] == entry["sha256"]
                and snapshot["integrity"] == "ok"
                and snapshot["mode"] == "0o600"
                and restore["integrity"] == "ok"
            )
            evidence = {
                "name": name,
                "path": str(path),
                "mode": snapshot["mode"],
                "integrity": snapshot["integrity"],
                "cleanRestore": restore["integrity"],
            }
        except (FileNotFoundError, OSError, sqlite3.DatabaseError, RuntimeError) as exc:
            valid = False
            evidence = {"name": name, "path": str(path), "error": str(exc)}
        passed = passed and valid
        rows.append(evidence)
    passed = passed and found == set(expected_sources)
    return _check(
        "fresh-backup-restore",
        passed,
        {
            "path": str(backup_dir),
            "createdAt": created_at.isoformat(),
            "maxAgeHours": max_age.total_seconds() / 3600,
            "manifestMode": manifest_mode,
            "backupDirMode": backup_mode,
            "databases": rows,
            "missingDatabases": sorted(set(expected_sources) - found),
        },
    )


def _active_files(roots: list[Path]) -> tuple[list[Path], list[dict[str, str]]]:
    files: set[Path] = set()
    errors: list[dict[str, str]] = []
    for root in roots:
        resolved = root.expanduser().resolve()
        if resolved.is_file():
            files.add(resolved)
        elif resolved.is_dir():
            try:
                files.update(
                    path
                    for path in resolved.rglob("*")
                    if path.is_file() and path.stat().st_size <= 1024 * 1024
                )
            except OSError as exc:
                errors.append({"root": str(resolved), "error": str(exc)})
        else:
            errors.append({"root": str(resolved), "error": "path is missing"})
    return sorted(files), errors


def _verify_active_references(
    candidates: list[dict[str, Any]], roots: list[Path]
) -> dict[str, Any]:
    references: list[dict[str, str]] = []
    candidate_paths = {row["path"] for row in candidates}
    active_files, errors = _active_files(roots)
    for config_path in active_files:
        try:
            text = config_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for old_path in candidate_paths:
            if old_path in text:
                references.append({"config": str(config_path), "oldPath": old_path})
    return _check(
        "active-old-path-references",
        not references and not errors,
        {
            "roots": [str(root.expanduser().resolve()) for root in roots],
            "references": references,
            "scanErrors": errors,
        },
    )


def cleanup_eligibility_report(
    manifest_path: Path,
    *,
    operating_cycle_evidence: Path,
    backup_dir: Path,
    active_config_roots: list[Path],
    now: datetime | None = None,
    max_backup_age_hours: float = 24.0,
) -> dict[str, Any]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    manifest_path = manifest_path.expanduser().resolve()
    migration = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        migration.get("schema") != MIGRATION_SCHEMA
        or migration.get("status") != "migrated"
    ):
        raise ValueError("not a completed Creator OS state migration manifest")

    retain_until = _parse_time(str(migration["rollbackRetainUntil"]))
    retention = _check(
        "rollback-retention",
        now >= retain_until,
        {"now": now.isoformat(), "retainUntil": retain_until.isoformat()},
    )
    originals, candidates = _verify_originals(migration)
    checks = [
        _verify_manifest_safety(migration),
        retention,
        _verify_operating_cycle(operating_cycle_evidence, migration, now),
        originals,
        _verify_canonical_databases(migration),
        _verify_backup(
            backup_dir,
            migration,
            now,
            timedelta(hours=max_backup_age_hours),
        ),
        _verify_active_references(candidates, active_config_roots),
    ]
    eligible = all(check["status"] == "PASS" for check in checks)
    return {
        "schema": REPORT_SCHEMA,
        "status": "ELIGIBLE" if eligible else "INELIGIBLE",
        "reportOnly": True,
        "deletionPerformed": False,
        "manifest": str(manifest_path),
        "checkedAt": now.isoformat(),
        "checks": checks,
        "candidates": [
            dict(candidate, cleanupEligible=eligible) for candidate in candidates
        ],
        "retained": [
            {
                "path": str(manifest_path),
                "reason": "migration evidence is never a cleanup candidate",
            },
            *[
                {
                    "path": row["source"],
                    "reason": "active log path is never a cleanup candidate",
                }
                for row in migration.get("directories", [])
                if row["kind"] == "log"
            ],
        ],
    }


def _default_active_roots() -> list[Path]:
    config_root = Path.home() / ".creator-os"
    return [
        *sorted(config_root.glob("*.env")),
        *sorted(config_root.glob("*.sh")),
        *sorted(config_root.glob("*.toml")),
        Path.home() / "Library/LaunchAgents",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--operating-cycle-evidence", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--active-config-root", type=Path, action="append")
    parser.add_argument("--max-backup-age-hours", type=float, default=24.0)
    args = parser.parse_args()
    roots = args.active_config_root or _default_active_roots()
    report = cleanup_eligibility_report(
        args.manifest,
        operating_cycle_evidence=args.operating_cycle_evidence,
        backup_dir=args.backup_dir,
        active_config_roots=roots,
        max_backup_age_hours=args.max_backup_age_hours,
    )
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "ELIGIBLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
