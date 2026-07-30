#!/usr/bin/env python3
"""Back up local Creator OS runtime state without mutating source data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/creator_os_core"))

from creator_os_core.configuration_registry import (
    configuration_manifest,
    redact_mapping,
    validate_operation_configuration,
)
from creator_os_core.runtime_paths import resolve_runtime_paths
from creator_os_core.runtime_state import (
    sha256_file,
    sqlite_integrity,
    vacuum_into,
    verified_vacuum_copy,
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
BACKUP_SCHEMA_VERSION = 2
DEFAULT_RPO_SECONDS = 24 * 60 * 60
DEFAULT_RTO_SECONDS = 2 * 60 * 60
_DEFAULT_DATABASE_RESTORE_PATHS = {
    "campaign_factory": Path("state/campaign_factory/campaign_factory.sqlite"),
    "reference_factory": Path("state/reference_factory/reference_factory.sqlite"),
    "reel_manifest": Path("state/reel_factory/manifest.sqlite"),
    "render_queue": Path("state/reel_factory/render_queue.sqlite"),
}


class RuntimeRestoreError(RuntimeError):
    pass


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _directory_inventory(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        entry: dict[str, Any]
        if path.is_symlink():
            target = os.readlink(path)
            entry = {
                "path": relative,
                "kind": "symlink",
                "target": target,
            }
        elif path.is_file():
            size = path.stat().st_size
            file_sha256 = sha256_file(path)
            entry = {
                "path": relative,
                "kind": "file",
                "bytes": size,
                "sha256": file_sha256,
                "mode": oct(path.stat().st_mode & 0o777),
            }
            total_bytes += size
        elif path.is_dir():
            continue
        else:
            entry = {"path": relative, "kind": "unsupported"}
        files.append(entry)
        digest.update(_canonical_json(entry))
    return {
        "files": files,
        "fileCount": sum(item["kind"] == "file" for item in files),
        "symlinkCount": sum(item["kind"] == "symlink" for item in files),
        "bytes": total_bytes,
        "treeSha256": digest.hexdigest(),
    }


def _safe_relative(value: str | Path, label: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise RuntimeRestoreError(f"unsafe_restore_path:{label}")
    return path


def _backup_subject(root: Path, relative: str | Path, label: str) -> Path:
    selected = _safe_relative(relative, label)
    subject = root / selected
    if subject.is_symlink():
        raise RuntimeRestoreError(f"unsafe_backup_subject_symlink:{label}")
    if not subject.resolve(strict=False).is_relative_to(root):
        raise RuntimeRestoreError(f"unsafe_backup_subject:{label}")
    return subject


def _parse_created_at(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise RuntimeRestoreError("backup_created_at_timezone_missing")
    return parsed.astimezone(UTC)


def _write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def backup_runtime_state(
    repo_root: Path,
    output_dir: Path,
    *,
    timestamp: str | None = None,
    created_at: datetime | None = None,
    database_sources: tuple[tuple[str, Path, Path], ...] | None = None,
    directory_sources: tuple[tuple[str, Path, Path], ...] | None = None,
    required_databases: Sequence[str] = (),
    required_directories: Sequence[str] = (),
    config_evidence: Mapping[str, Any] | None = None,
    rpo_seconds: int = DEFAULT_RPO_SECONDS,
    rto_seconds: int = DEFAULT_RTO_SECONDS,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    stamp = timestamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_root = output_dir.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_root, 0o700)
    target = output_root / stamp
    if target.exists():
        raise FileExistsError(f"refusing to replace existing backup: {target}")
    stage = output_root / f".{stamp}.{uuid.uuid4().hex}.tmp"
    stage.mkdir(mode=0o700)
    os.chmod(stage, 0o700)
    created = (created_at or datetime.now(UTC)).astimezone(UTC)
    result: dict[str, Any] = {
        "schemaVersion": BACKUP_SCHEMA_VERSION,
        "createdAt": created.isoformat(),
        "backupDir": str(target),
        "sourceRoot": str(repo_root),
        "databases": [],
        "directories": [],
        "requiredComponents": {
            "databases": sorted(set(required_databases)),
            "directories": sorted(set(required_directories)),
        },
        "configuration": redact_mapping(config_evidence or {}),
        "policy": {
            "rpoSeconds": int(rpo_seconds),
            "rtoTargetSeconds": int(rto_seconds),
            "backupScope": (
                "Creator OS SQLite state and retained runtime directories; "
                "source code is restored from exact Git history and secrets "
                "must be supplied separately."
            ),
            "restoreAuthority": "explicit operator authorization",
            "restoreVerification": (
                "manifest, SHA, directory tree, SQLite integrity, row counts, "
                "isolated restore, and post-restore reconciliation"
            ),
            "secretPolicy": "secret values are excluded and never recoverable",
        },
    }

    databases = database_sources or tuple(
        (name, repo_root / rel, Path(rel.name)) for name, rel in DB_PATHS
    )
    directories = directory_sources or tuple(
        (name, repo_root / rel, rel) for name, rel in DIR_PATHS
    )

    try:
        for name, source, backup_rel in databases:
            entry: dict[str, Any] = {
                "name": name,
                "source": str(source),
                "status": "missing",
            }
            if source.exists():
                dest = stage / "databases" / backup_rel
                vacuum_into(source, dest)
                dest.chmod(0o600)
                verification = sqlite_integrity(dest)
                if verification["integrity"] != "ok":
                    raise RuntimeError(f"SQLite integrity check failed: {dest}")
                entry |= {
                    "status": "backed_up",
                    "path": str(dest.relative_to(stage)),
                    "bytes": dest.stat().st_size,
                    "sha256": sha256_file(dest),
                    "mode": oct(dest.stat().st_mode & 0o777),
                    **verification,
                }
            result["databases"].append(entry)

        for name, source, backup_rel in directories:
            entry = {"name": name, "source": str(source), "status": "missing"}
            if source.exists():
                dest = stage / backup_rel
                shutil.copytree(
                    source,
                    dest,
                    symlinks=True,
                    ignore=shutil.ignore_patterns(*CREDENTIAL_PATTERNS),
                )
                entry |= {
                    "status": "backed_up",
                    "path": str(dest.relative_to(stage)),
                    "inventory": _directory_inventory(dest),
                }
            result["directories"].append(entry)

        available_databases = {
            str(row["name"])
            for row in result["databases"]
            if row["status"] == "backed_up"
        }
        available_directories = {
            str(row["name"])
            for row in result["directories"]
            if row["status"] == "backed_up"
        }
        result["status"] = (
            "complete"
            if set(required_databases) <= available_databases
            and set(required_directories) <= available_directories
            else "partial"
        )
        result["manifestFingerprint"] = _fingerprint(result)
        _write_manifest(stage / MANIFEST_NAME, result)
        os.replace(stage, target)
        return result
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


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
        required_databases=tuple(name for name, *_ in databases),
        required_directories=("artifacts", "models"),
        config_evidence=configuration_manifest(values=os.environ),
    )


def verify_backup(
    backup_dir: Path,
    *,
    now: datetime | None = None,
    max_age_seconds: int | None = None,
    require_complete: bool = False,
) -> dict[str, Any]:
    backup_dir = backup_dir.expanduser().resolve()
    manifest_path = backup_dir / MANIFEST_NAME
    _, manifest = load_json_manifest(manifest_path)
    schema_version = int(manifest.get("schemaVersion") or 1)
    if schema_version >= 2:
        claimed_fingerprint = str(manifest.get("manifestFingerprint") or "")
        fingerprint_subject = dict(manifest)
        fingerprint_subject.pop("manifestFingerprint", None)
        if claimed_fingerprint != _fingerprint(fingerprint_subject):
            raise RuntimeError("Backup verification failed: manifest fingerprint")
    created_at = _parse_created_at(manifest["createdAt"])
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    age_seconds = max(0.0, (checked_at - created_at).total_seconds())
    policy = manifest.get("policy") if isinstance(manifest.get("policy"), dict) else {}
    allowed_age = (
        max_age_seconds
        if max_age_seconds is not None
        else int(policy.get("rpoSeconds") or DEFAULT_RPO_SECONDS)
    )
    warnings: list[dict[str, Any]] = []
    if age_seconds > allowed_age:
        warnings.append(
            {
                "code": "backup_stale",
                "ageSeconds": age_seconds,
                "rpoSeconds": allowed_age,
            }
        )
    verified: list[dict[str, Any]] = []
    for entry in manifest["databases"]:
        if entry["status"] != "backed_up":
            continue
        path = _backup_subject(backup_dir, entry["path"], str(entry["name"]))
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
    verified_directories: list[dict[str, Any]] = []
    for entry in manifest.get("directories", []):
        if entry["status"] != "backed_up":
            continue
        path = _backup_subject(backup_dir, entry["path"], str(entry["name"]))
        if not path.is_dir():
            raise RuntimeError(f"Backup verification failed: {entry['name']}")
        inventory = _directory_inventory(path)
        if schema_version >= 2 and inventory != entry.get("inventory"):
            raise RuntimeError(f"Backup verification failed: {entry['name']}")
        if inventory["symlinkCount"]:
            warnings.append(
                {
                    "code": "backup_contains_symlinks",
                    "component": entry["name"],
                    "count": inventory["symlinkCount"],
                }
            )
        verified_directories.append(
            {
                "name": entry["name"],
                "treeSha256": inventory["treeSha256"],
                "fileCount": inventory["fileCount"],
                "bytes": inventory["bytes"],
            }
        )
    required = manifest.get("requiredComponents")
    required = required if isinstance(required, dict) else {}
    missing_required: list[str] = []
    for kind in ("databases", "directories"):
        rows = {
            str(row.get("name")): str(row.get("status"))
            for row in manifest.get(kind, [])
            if isinstance(row, dict)
        }
        missing_required.extend(
            f"{kind}:{name}"
            for name in required.get(kind, [])
            if rows.get(str(name)) != "backed_up"
        )
    if missing_required:
        warnings.append(
            {
                "code": "backup_partial",
                "missingRequired": sorted(missing_required),
            }
        )
        if require_complete:
            raise RuntimeError(
                "Backup verification failed: required components missing: "
                + ",".join(sorted(missing_required))
            )
    return {
        "backupDir": str(backup_dir),
        "status": "partial" if missing_required else "ok",
        "schemaVersion": schema_version,
        "manifestFingerprint": manifest.get("manifestFingerprint"),
        "createdAt": created_at.isoformat(),
        "checkedAt": checked_at.isoformat(),
        "ageSeconds": age_seconds,
        "rpoSeconds": allowed_age,
        "databases": verified,
        "directories": verified_directories,
        "warnings": warnings,
        "missingRequired": sorted(missing_required),
    }


def _receipt_timestamp(path: Path) -> datetime:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)
    if isinstance(payload, dict):
        for field in ("createdAt", "recordedAt", "timestamp", "updatedAt"):
            if payload.get(field):
                try:
                    return _parse_created_at(payload[field])
                except (TypeError, ValueError, RuntimeRestoreError):
                    continue
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def _newer_receipt_evidence(
    receipt_paths: Sequence[Path],
    *,
    backup_created_at: datetime,
) -> list[dict[str, str]]:
    newer: list[dict[str, str]] = []
    for raw in receipt_paths:
        path = raw.expanduser().resolve()
        if not path.is_file():
            continue
        created = _receipt_timestamp(path)
        if created > backup_created_at:
            newer.append(
                {
                    "path": str(path),
                    "createdAt": created.isoformat(),
                }
            )
    return newer


def _restore_relative_path(
    *,
    kind: str,
    entry: Mapping[str, Any],
    path_rebindings: Mapping[str, str | Path],
) -> Path:
    name = str(entry["name"])
    if name in path_rebindings:
        return _safe_relative(path_rebindings[name], name)
    if kind == "database":
        return _DEFAULT_DATABASE_RESTORE_PATHS.get(
            name,
            Path("state") / "databases" / Path(str(entry["path"])).name,
        )
    return _safe_relative(entry["path"], name)


def restore_runtime_state(
    backup_dir: Path,
    destination_root: Path,
    *,
    operator: str,
    authorized: bool,
    path_rebindings: Mapping[str, str | Path] | None = None,
    target_configuration: Mapping[str, Any] | None = None,
    required_operation: str = "restore_drill",
    allow_stale: bool = False,
    allow_newer_receipts: bool = False,
    allow_symlinks: bool = False,
    now: datetime | None = None,
    canonical_receipts: Sequence[Path] = (),
    database_upgraders: Mapping[str, Callable[[Path], None]] | None = None,
) -> dict[str, Any]:
    """Restore only into a new isolated root and never replace canonical state."""

    if not authorized or not operator.strip():
        raise PermissionError("runtime_restore_requires_explicit_operator_authority")
    started = time.monotonic()
    source = backup_dir.expanduser().resolve()
    destination = destination_root.expanduser().resolve()
    if destination.exists():
        raise FileExistsError(
            f"refusing to overwrite existing restore destination: {destination}"
        )
    if destination == source or destination.is_relative_to(source):
        raise RuntimeRestoreError("restore_destination_overlaps_backup")
    if destination.parent.is_symlink():
        raise RuntimeRestoreError("restore_destination_parent_symlink")

    _, manifest = load_json_manifest(source / MANIFEST_NAME)
    backup_created_at = _parse_created_at(manifest["createdAt"])
    verification = verify_backup(source, now=now, require_complete=True)
    stale = any(
        warning.get("code") == "backup_stale"
        for warning in verification.get("warnings", [])
    )
    if stale and not allow_stale:
        raise RuntimeRestoreError("stale_backup_requires_explicit_override")
    contains_symlinks = any(
        warning.get("code") == "backup_contains_symlinks"
        for warning in verification.get("warnings", [])
    )
    if contains_symlinks and not allow_symlinks:
        raise RuntimeRestoreError("backup_symlinks_require_explicit_reconciliation")
    newer_receipts = _newer_receipt_evidence(
        canonical_receipts,
        backup_created_at=backup_created_at,
    )
    if newer_receipts and not allow_newer_receipts:
        raise RuntimeRestoreError("newer_canonical_receipts_block_restore")
    config_receipt = validate_operation_configuration(
        required_operation,
        values=target_configuration or {},
    )

    bindings = dict(path_rebindings or {})
    upgraders = dict(database_upgraders or {})
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination.parent, 0o700)
    stage = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.restore"
    stage.mkdir(mode=0o700)
    os.chmod(stage, 0o700)
    restored_databases: list[dict[str, Any]] = []
    restored_directories: list[dict[str, Any]] = []
    try:
        for entry in manifest.get("databases", []):
            if entry.get("status") != "backed_up":
                continue
            name = str(entry["name"])
            backup_path = _backup_subject(source, entry["path"], name)
            relative = _restore_relative_path(
                kind="database",
                entry=entry,
                path_rebindings=bindings,
            )
            destination_path = stage / relative
            copy_evidence = verified_vacuum_copy(backup_path, destination_path)
            before_upgrade = copy_evidence["destination"]
            upgraded = False
            if upgrader := upgraders.get(name):
                upgrader(destination_path)
                upgraded = True
            after_upgrade = {
                "path": str(destination_path),
                "sha256": sha256_file(destination_path),
                **sqlite_integrity(destination_path),
            }
            if after_upgrade["integrity"] != "ok":
                raise RuntimeRestoreError(f"restored_database_invalid:{name}")
            restored_databases.append(
                {
                    "name": name,
                    "relativePath": relative.as_posix(),
                    "sourceSha256": entry["sha256"],
                    "preUpgradeSha256": before_upgrade["sha256"],
                    "restoredSha256": after_upgrade["sha256"],
                    "rowCounts": after_upgrade["rowCounts"],
                    "schemaUpgraded": upgraded,
                }
            )

        for entry in manifest.get("directories", []):
            if entry.get("status") != "backed_up":
                continue
            name = str(entry["name"])
            backup_path = _backup_subject(source, entry["path"], name)
            relative = _restore_relative_path(
                kind="directory",
                entry=entry,
                path_rebindings=bindings,
            )
            destination_path = stage / relative
            if destination_path.exists():
                raise RuntimeRestoreError(f"restore_path_collision:{name}")
            destination_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copytree(backup_path, destination_path, symlinks=True)
            inventory = _directory_inventory(destination_path)
            if inventory != entry.get("inventory"):
                raise RuntimeRestoreError(f"restored_directory_invalid:{name}")
            restored_directories.append(
                {
                    "name": name,
                    "relativePath": relative.as_posix(),
                    "treeSha256": inventory["treeSha256"],
                    "fileCount": inventory["fileCount"],
                }
            )

        elapsed = time.monotonic() - started
        policy = (
            manifest.get("policy") if isinstance(manifest.get("policy"), dict) else {}
        )
        rto_target = int(policy.get("rtoTargetSeconds") or DEFAULT_RTO_SECONDS)
        receipt: dict[str, Any] = {
            "schema": "creator_os.runtime_restore.v1",
            "operator": operator.strip(),
            "authorized": True,
            "backupDir": str(source),
            "backupManifestFingerprint": manifest.get("manifestFingerprint"),
            "backupCreatedAt": backup_created_at.isoformat(),
            "destinationRoot": str(destination),
            "isolatedRestore": True,
            "canonicalStateOverwritten": False,
            "configurationValidation": config_receipt,
            "pathRebindings": {
                item["name"]: item["relativePath"]
                for item in restored_databases + restored_directories
            },
            "databases": restored_databases,
            "directories": restored_directories,
            "schemaUpgradeApplied": any(
                item["schemaUpgraded"] for item in restored_databases
            ),
            "newerCanonicalReceipts": newer_receipts,
            "newerReceiptsRequireReconciliation": bool(newer_receipts),
            "staleBackupAccepted": stale,
            "symlinkedArtifactsAccepted": contains_symlinks,
            "postRestoreReconciliation": {
                "required": True,
                "checks": [
                    "database/filesystem reconciliation",
                    "provider-attempt reconciliation",
                    "receipt chronology reconciliation",
                    "configuration and secret revalidation",
                    "model availability qualification",
                ],
            },
            "rpoSeconds": verification["ageSeconds"],
            "rpoTargetSeconds": verification["rpoSeconds"],
            "rpoMet": verification["ageSeconds"] <= verification["rpoSeconds"],
            "rtoSeconds": elapsed,
            "rtoTargetSeconds": rto_target,
            "rtoMet": elapsed <= rto_target,
            "warnings": verification["warnings"],
        }
        _write_manifest(stage / "restore-receipt.json", receipt)
        os.replace(stage, destination)
        return receipt
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


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
    parser.add_argument(
        "--restore",
        type=Path,
        help="Restore a verified backup into a new isolated destination",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        help="New, non-existing root for an isolated restore",
    )
    parser.add_argument("--operator", help="Operator identity for restore evidence")
    parser.add_argument(
        "--restore-operation",
        default="restore_drill",
        help="Configuration scope to validate after restore",
    )
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="Explicitly accept an RPO-stale backup for an isolated drill",
    )
    parser.add_argument(
        "--allow-newer-receipts",
        action="store_true",
        help=(
            "Restore only into the isolated destination while retaining newer "
            "canonical receipts as mandatory reconciliation evidence"
        ),
    )
    parser.add_argument(
        "--allow-symlinks",
        action="store_true",
        help=(
            "Retain recorded symlinks only in the isolated restore and require "
            "post-restore reconciliation"
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Required for restore writes; backup creation remains the default",
    )
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_backup(args.verify), indent=2))
        return 0
    if args.restore:
        if args.destination is None or not args.operator:
            parser.error("--restore requires --destination and --operator")
        result = restore_runtime_state(
            args.restore,
            args.destination,
            operator=args.operator,
            authorized=args.apply,
            target_configuration=os.environ,
            required_operation=args.restore_operation,
            allow_stale=args.allow_stale,
            allow_newer_receipts=args.allow_newer_receipts,
            allow_symlinks=args.allow_symlinks,
        )
        print(json.dumps(result, indent=2))
        return 0
    result = (
        backup_runtime_state(args.repo_root, args.output_dir)
        if args.repo_root is not None
        else backup_configured_runtime_state(args.output_dir)
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
