"""Read-only evidence helpers for Creator OS runtime state.

These helpers inspect manifests, directories, permissions, and SQLite files.
They never alter live runtime state and intentionally expose no cleanup/apply
operation. Temporary SQLite restore proof is delegated to ``runtime_state``.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from creator_os_core.runtime_state import (
    sha256_file,
    sqlite_snapshot,
    verify_clean_restore,
)

DEFAULT_PRIVATE_PATTERNS = ("*.env", "*.key", "*.pem", "secrets.toml")
DEFAULT_ACTIVE_FILE_MAX_BYTES = 1024 * 1024


def load_json_manifest(path: Path) -> tuple[Path, dict[str, Any]]:
    """Load a JSON object from an exact path without modifying it."""

    resolved = path.expanduser().resolve()
    body = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(body, dict):
        raise ValueError(f"manifest must contain a JSON object: {resolved}")
    return resolved, body


def parse_utc_timestamp(value: str) -> datetime:
    """Parse an ISO timestamp and require explicit timezone evidence."""

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value}")
    return parsed.astimezone(UTC)


def permission_mode(path: Path) -> str:
    """Return the effective Unix permission bits for ``path``."""

    return oct(path.expanduser().resolve().stat().st_mode & 0o777)


def tree_snapshot(
    path: Path,
    *,
    logs_only: bool = False,
    exclude_private: bool = False,
    private_patterns: Sequence[str] = DEFAULT_PRIVATE_PATTERNS,
) -> dict[str, Any]:
    """Hash the files below ``path`` deterministically.

    Directory symlinks are followed to preserve migration-manifest behavior,
    while ancestor tracking rejects cycles. Credential-shaped files can be
    excluded using the same pattern set as runtime migration and backup.
    """

    resolved_root = path.expanduser().resolve()
    files: list[Path] = []

    def collect(directory: Path, ancestors: frozenset[Path]) -> None:
        resolved_directory = directory.resolve()
        if resolved_directory in ancestors:
            raise ValueError(f"directory symlink cycle detected: {directory}")
        nested_ancestors = ancestors | {resolved_directory}
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            item = Path(entry.path)
            if entry.is_dir(follow_symlinks=True):
                collect(item, nested_ancestors)
                continue
            if not entry.is_file(follow_symlinks=True):
                continue
            if logs_only and not item.name.endswith(".log"):
                continue
            if exclude_private and any(
                item.match(pattern) for pattern in private_patterns
            ):
                continue
            files.append(item)

    collect(resolved_root, frozenset())
    digest = hashlib.sha256()
    total_bytes = 0
    for item in sorted(files):
        relative = item.relative_to(resolved_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(sha256_file(item).encode("ascii"))
        total_bytes += item.stat().st_size
    return {
        "path": str(resolved_root),
        "files": len(files),
        "bytes": total_bytes,
        "treeSha256": digest.hexdigest(),
    }


def single_file_tree_snapshot(path: Path) -> dict[str, Any]:
    """Return the tree-compatible evidence shape for one file."""

    resolved = path.expanduser().resolve()
    file_hash = sha256_file(resolved)
    digest = hashlib.sha256()
    digest.update(resolved.name.encode("utf-8"))
    digest.update(file_hash.encode("ascii"))
    return {
        "path": str(resolved),
        "files": 1,
        "bytes": resolved.stat().st_size,
        "treeSha256": digest.hexdigest(),
    }


def verify_sqlite_evidence(
    path: Path,
    *,
    expected_sha256: str | None = None,
    expected_row_counts: Mapping[str, int] | None = None,
    required_mode: str | None = None,
    required_parent_mode: str | None = None,
    require_clean_restore: bool = False,
) -> dict[str, Any]:
    """Inspect one SQLite file and evaluate the requested evidence checks."""

    resolved = path.expanduser().resolve()
    snapshot = sqlite_snapshot(resolved)
    clean_restore = verify_clean_restore(resolved) if require_clean_restore else None
    checks = {
        "integrity": snapshot["integrity"] == "ok",
        "sha256": expected_sha256 is None or snapshot["sha256"] == expected_sha256,
        "rowCounts": expected_row_counts is None
        or snapshot["rowCounts"] == dict(expected_row_counts),
        "mode": required_mode is None or snapshot["mode"] == required_mode,
        "parentMode": required_parent_mode is None
        or permission_mode(resolved.parent) == required_parent_mode,
        "cleanRestore": not require_clean_restore
        or clean_restore is not None
        and clean_restore["integrity"] == "ok"
        and clean_restore["rowCounts"] == snapshot["rowCounts"],
    }
    return {
        "valid": all(checks.values()),
        "snapshot": snapshot,
        "cleanRestore": clean_restore,
        "checks": checks,
    }


def retention_deadline_evidence(
    retain_until: str, *, now: datetime | None = None
) -> dict[str, Any]:
    """Evaluate a retention deadline without changing retained paths."""

    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    deadline = parse_utc_timestamp(retain_until)
    return {
        "elapsed": checked_at >= deadline,
        "now": checked_at.isoformat(),
        "retainUntil": deadline.isoformat(),
    }


def scan_active_path_references(
    candidate_paths: Collection[str],
    roots: Sequence[Path],
    *,
    max_file_bytes: int = DEFAULT_ACTIVE_FILE_MAX_BYTES,
) -> dict[str, Any]:
    """Find exact retained-path strings in active configuration files.

    Missing or unreadable roots are reported as scan errors so cleanup callers
    can fail closed. Files above ``max_file_bytes`` are intentionally skipped.
    """

    active_files: set[Path] = set()
    errors: list[dict[str, str]] = []
    resolved_roots: list[str] = []
    for root in roots:
        resolved = root.expanduser().resolve()
        resolved_roots.append(str(resolved))
        if resolved.is_file():
            active_files.add(resolved)
        elif resolved.is_dir():
            try:
                active_files.update(
                    path
                    for path in resolved.rglob("*")
                    if path.is_file() and path.stat().st_size <= max_file_bytes
                )
            except OSError as exc:
                errors.append({"root": str(resolved), "error": str(exc)})
        else:
            errors.append({"root": str(resolved), "error": "path is missing"})

    references: list[dict[str, str]] = []
    for config_path in sorted(active_files):
        try:
            text = config_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for old_path in sorted(candidate_paths):
            if old_path in text:
                references.append({"config": str(config_path), "oldPath": old_path})
    return {
        "roots": resolved_roots,
        "references": references,
        "scanErrors": errors,
    }
