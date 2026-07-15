"""Canonical path resolution for Creator OS source, runtime, and sibling repos."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    source_root: Path
    workspace_root: Path
    runtime_root: Path
    campaign_factory_root: Path
    reel_factory_root: Path
    reference_factory_root: Path
    contentforge_root: Path
    threadsdash_root: Path
    reference_data_root: Path


def resolve_runtime_paths(
    source_root: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> RuntimePaths:
    """Resolve the active monorepo layout without assuming a personal home path."""
    values = os.environ if env is None else env
    inferred_source = Path(__file__).resolve().parents[3]
    source = (
        Path(values.get("CREATOR_OS_ROOT") or source_root or inferred_source)
        .expanduser()
        .resolve()
    )
    workspace = source.parent
    runtime = (
        Path(values.get("CREATOR_OS_RUNTIME_ROOT") or workspace / "creator-os-runtime")
        .expanduser()
        .resolve()
    )
    reference_data = (
        Path(values.get("REFERENCE_FACTORY_DATA_ROOT") or workspace / "reference_reels")
        .expanduser()
        .resolve()
    )
    return RuntimePaths(
        source_root=source,
        workspace_root=workspace,
        runtime_root=runtime,
        campaign_factory_root=Path(
            values.get("CAMPAIGN_FACTORY_ROOT")
            or source / "python_packages/campaign_factory"
        )
        .expanduser()
        .resolve(),
        reel_factory_root=Path(
            values.get("REEL_FACTORY_ROOT") or source / "python_packages/reel_factory"
        )
        .expanduser()
        .resolve(),
        reference_factory_root=Path(
            values.get("REFERENCE_FACTORY_ROOT")
            or source / "python_packages/reference_factory"
        )
        .expanduser()
        .resolve(),
        contentforge_root=Path(
            values.get("CONTENTFORGE_ROOT") or source / "packages/contentforge"
        )
        .expanduser()
        .resolve(),
        threadsdash_root=Path(
            values.get("THREADSDASH_ROOT") or workspace / "ThreadsDashboard"
        )
        .expanduser()
        .resolve(),
        reference_data_root=reference_data,
    )


def resolve_component_roots(
    projects_root: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Path]:
    """Resolve canonical or flat fixture layouts for cross-component smoke tests."""
    values = os.environ if env is None else env
    root = Path(projects_root).expanduser().resolve()
    if (root / "creator-os").is_dir():
        creator_os = root / "creator-os"
    elif root.name == "python_packages":
        creator_os = root.parent
    else:
        creator_os = root

    def pick(env_var: str, candidates: list[Path]) -> Path:
        if value := values.get(env_var):
            return Path(value).expanduser().resolve()
        return next((path for path in candidates if path.is_dir()), candidates[-1])

    return {
        "reel_factory": pick(
            "REEL_FACTORY_ROOT",
            [root / "reel_factory", creator_os / "python_packages/reel_factory"],
        ),
        "contentforge": pick(
            "CONTENTFORGE_ROOT",
            [root / "contentforge", creator_os / "packages/contentforge"],
        ),
        "reference_factory": pick(
            "REFERENCE_FACTORY_ROOT",
            [
                root / "reference_factory",
                creator_os / "python_packages/reference_factory",
            ],
        ),
        "ThreadsDashboard": pick(
            "THREADSDASH_ROOT",
            [root / "ThreadsDashboard", creator_os.parent / "ThreadsDashboard"],
        ),
    }
