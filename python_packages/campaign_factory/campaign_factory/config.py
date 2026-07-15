from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from creator_os_core.runtime_paths import (
    resolve_component_roots,
    resolve_runtime_paths,
)

_PATHS = resolve_runtime_paths()
CREATOR_OS_ROOT = _PATHS.source_root
WORKSPACE_ROOT = _PATHS.workspace_root
CREATOR_OS_CAMPAIGN_FACTORY_ROOT = _PATHS.campaign_factory_root
CREATOR_OS_REEL_FACTORY_ROOT = _PATHS.reel_factory_root
CREATOR_OS_CONTENTFORGE_ROOT = _PATHS.contentforge_root
CREATOR_OS_REFERENCE_FACTORY_ROOT = _PATHS.reference_factory_root
DEFAULT_THREADSDASH_ROOT = _PATHS.threadsdash_root


@dataclass(frozen=True)
class Settings:
    root: Path = Path(
        os.environ.get("CAMPAIGN_FACTORY_ROOT", CREATOR_OS_CAMPAIGN_FACTORY_ROOT)
    )
    db_path: Path = Path(
        os.environ.get(
            "CAMPAIGN_FACTORY_DB",
            CREATOR_OS_CAMPAIGN_FACTORY_ROOT / "campaign_factory.sqlite",
        )
    )
    reel_factory_root: Path = Path(
        os.environ.get("REEL_FACTORY_ROOT", CREATOR_OS_REEL_FACTORY_ROOT)
    )
    contentforge_root: Path = Path(
        os.environ.get("CONTENTFORGE_ROOT", CREATOR_OS_CONTENTFORGE_ROOT)
    )
    reference_factory_root: Path = Path(
        os.environ.get("REFERENCE_FACTORY_ROOT", CREATOR_OS_REFERENCE_FACTORY_ROOT)
    )
    reference_reels_root: Path = Path(
        os.environ.get("REFERENCE_REELS_ROOT", WORKSPACE_ROOT / "reference_reels")
    )
    # Compatibility attribute for older call signatures. ContentForge is
    # subprocess-only; no URL or HTTP mode is configurable.
    contentforge_base_url: str = "cli://local"
    threadsdash_root: Path = Path(
        os.environ.get("THREADSDASH_ROOT", DEFAULT_THREADSDASH_ROOT)
    )
    campaigns_dir: Path = Path(
        os.environ.get(
            "CAMPAIGN_FACTORY_CAMPAIGNS", CREATOR_OS_CAMPAIGN_FACTORY_ROOT / "campaigns"
        )
    )


def get_settings() -> Settings:
    return Settings()


def resolve_repo_roots(projects_root: Path) -> dict[str, Path]:
    return resolve_component_roots(projects_root)
