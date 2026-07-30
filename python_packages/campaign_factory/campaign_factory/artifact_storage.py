"""Managed Campaign Factory paths and crash-safe artifact writes."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CAMPAIGN_DIRECTORY_NAMES = {
    "sources": "00_sources",
    "reel_inputs": "01_reel_inputs",
    "rendered": "02_rendered",
    "audits": "03_contentforge_audits",
    "approved": "04_approved",
    "exports": "05_threadsdash_exports",
}
DEFAULT_MIN_FREE_BYTES = 512 * 1024 * 1024


class StorageCapacityError(OSError):
    """The destination cannot safely accept another managed artifact."""


def campaign_dirs(
    campaigns_root: Path,
    model_slug: str,
    campaign_slug: str,
    *,
    create: bool = True,
) -> dict[str, Path]:
    root = campaigns_root / model_slug / campaign_slug
    result = {"root": root}
    result.update(
        {key: root / directory for key, directory in CAMPAIGN_DIRECTORY_NAMES.items()}
    )
    if create:
        for path in result.values():
            path.mkdir(parents=True, exist_ok=True)
    return result


def has_symlink_component(path: Path) -> bool:
    absolute = Path(os.path.abspath(os.fspath(path.expanduser())))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                return True
        except FileNotFoundError:
            continue
    return False


def is_regular_file(path: Path) -> bool:
    try:
        value = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(value.st_mode) and not stat.S_ISLNK(value.st_mode)


def managed_roots(settings: Any) -> dict[str, Path]:
    return {
        "campaigns": Path(settings.campaigns_dir).expanduser().resolve(),
        "creative_approvals": Path(settings.creative_approvals_dir)
        .expanduser()
        .resolve(),
        "reference_factory": Path(settings.reference_reels_root).expanduser().resolve(),
        "reel_factory": Path(settings.reel_factory_root).expanduser().resolve(),
    }


def root_keyed_path(path: Path, roots: Mapping[str, Path]) -> dict[str, str] | None:
    if has_symlink_component(path):
        return None
    absolute = path.expanduser().resolve()
    for key, root in sorted(roots.items()):
        try:
            relative = absolute.relative_to(root.expanduser().resolve())
        except ValueError:
            continue
        return {"rootKey": key, "relativePath": relative.as_posix()}
    return None


def resolve_root_keyed_path(
    binding: Mapping[str, str], roots: Mapping[str, Path]
) -> Path:
    key = str(binding.get("rootKey") or "")
    relative = Path(str(binding.get("relativePath") or ""))
    if key not in roots or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid_root_keyed_path")
    root = roots[key].expanduser().resolve()
    if has_symlink_component(roots[key]):
        raise ValueError("root_keyed_path_symlink")
    lexical = root / relative
    if has_symlink_component(lexical):
        raise ValueError("root_keyed_path_symlink")
    result = lexical.resolve()
    try:
        result.relative_to(root)
    except ValueError as exc:
        raise ValueError("root_keyed_path_outside_root") from exc
    return result


def ensure_storage_capacity(
    destination: Path,
    incoming_bytes: int,
    *,
    storage_root: Path | None = None,
    quota_bytes: int | None = None,
    min_free_bytes: int | None = None,
) -> dict[str, int | None]:
    if min_free_bytes is None:
        min_free_bytes = _configured_byte_limit(
            "CREATOR_OS_ARTIFACT_MIN_FREE_BYTES", DEFAULT_MIN_FREE_BYTES
        )
    if quota_bytes is None:
        quota_bytes = _configured_byte_limit("CREATOR_OS_ARTIFACT_QUOTA_BYTES", None)
    if incoming_bytes < 0 or min_free_bytes < 0:
        raise ValueError("storage byte limits must be nonnegative")
    destination = Path(os.path.abspath(os.fspath(destination.expanduser())))
    root = Path(
        os.path.abspath(os.fspath((storage_root or destination.parent).expanduser()))
    )
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise ValueError("artifact_destination_outside_storage_root") from exc
    if has_symlink_component(root) or has_symlink_component(destination.parent):
        raise ValueError("artifact_storage_symlink")
    destination.parent.mkdir(parents=True, exist_ok=True)
    free_bytes = int(shutil.disk_usage(destination.parent).free)
    if free_bytes - incoming_bytes < min_free_bytes:
        raise StorageCapacityError("artifact_storage_minimum_free_space")
    used_bytes: int | None = None
    if quota_bytes is not None:
        if quota_bytes < 0:
            raise ValueError("storage byte limits must be nonnegative")
        used_bytes = _directory_size(root)
        if used_bytes + incoming_bytes > quota_bytes:
            raise StorageCapacityError("artifact_storage_quota_exceeded")
    return {
        "incomingBytes": incoming_bytes,
        "freeBytes": free_bytes,
        "minimumFreeBytes": min_free_bytes,
        "quotaBytes": quota_bytes,
        "usedBytes": used_bytes,
    }


def atomic_copy(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str,
    storage_root: Path | None = None,
    quota_bytes: int | None = None,
    min_free_bytes: int | None = None,
) -> None:
    if (
        not is_regular_file(source)
        or has_symlink_component(source)
        or has_symlink_component(destination.parent)
    ):
        raise ValueError("artifact_copy_requires_regular_non_symlink_paths")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if (
            not is_regular_file(destination)
            or sha256_file(destination) != expected_sha256
        ):
            raise FileExistsError(f"managed artifact collision: {destination}")
        return
    source_size = source.stat().st_size
    ensure_storage_capacity(
        destination,
        source_size,
        storage_root=storage_root,
        quota_bytes=quota_bytes,
        min_free_bytes=min_free_bytes,
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_handle:
            shutil.copyfileobj(input_handle, output)
            output.flush()
            os.fsync(output.fileno())
        if sha256_file(temporary) != expected_sha256:
            raise OSError("atomic copy SHA mismatch")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _directory_size(root: Path) -> int:
    total = 0
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except FileNotFoundError:
            continue
        for entry in entries:
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(entry_stat.st_mode):
                continue
            if stat.S_ISDIR(entry_stat.st_mode):
                stack.append(Path(entry.path))
            elif stat.S_ISREG(entry_stat.st_mode):
                total += int(entry_stat.st_size)
    return total


def _configured_byte_limit(name: str, default: int | None) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a nonnegative integer") from exc
    if value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
