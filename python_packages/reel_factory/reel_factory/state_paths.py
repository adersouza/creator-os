"""Canonical Reel Factory state paths with explicit legacy-root compatibility."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from creator_os_core.runtime_paths import resolve_runtime_paths


def manifest_db_path(
    root: Path | str | None = None, *, env: Mapping[str, str] | None = None
) -> Path:
    values = os.environ if env is None else env
    explicit_root = Path(root).expanduser().resolve() if root is not None else None
    package_root = resolve_runtime_paths(env=values).reel_factory_root
    if explicit_root is not None and explicit_root != package_root:
        return explicit_root / "manifest.sqlite"
    if configured := values.get("REEL_FACTORY_MANIFEST_DB"):
        return Path(configured).expanduser().resolve()
    if explicit_root is not None:
        return explicit_root / "manifest.sqlite"
    return resolve_runtime_paths(env=values).reel_manifest_db


def render_queue_db_path(
    root: Path | str | None = None, *, env: Mapping[str, str] | None = None
) -> Path:
    values = os.environ if env is None else env
    explicit_root = Path(root).expanduser().resolve() if root is not None else None
    package_root = resolve_runtime_paths(env=values).reel_factory_root
    if explicit_root is not None and explicit_root != package_root:
        return explicit_root / "render_queue.sqlite"
    if configured := values.get("REEL_FACTORY_RENDER_QUEUE_DB"):
        return Path(configured).expanduser().resolve()
    if explicit_root is not None:
        return explicit_root / "render_queue.sqlite"
    return resolve_runtime_paths(env=values).reel_render_queue_db


def state_root(*, env: Mapping[str, str] | None = None) -> Path:
    return manifest_db_path(env=env).parent
