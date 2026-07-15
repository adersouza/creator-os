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
CREATOR_OS_CAMPAIGN_FACTORY_ROOT = _PATHS.campaign_factory_root
CREATOR_OS_REEL_FACTORY_ROOT = _PATHS.reel_factory_root
CREATOR_OS_CONTENTFORGE_ROOT = _PATHS.contentforge_root
CREATOR_OS_REFERENCE_FACTORY_ROOT = _PATHS.reference_factory_root
DEFAULT_THREADSDASH_ROOT = _PATHS.threadsdash_root
_UNSET_PATH = Path("__creator_os_unset_path__")


@dataclass(frozen=True)
class Settings:
    root: Path = Path(
        os.environ.get("CAMPAIGN_FACTORY_ROOT", CREATOR_OS_CAMPAIGN_FACTORY_ROOT)
    )
    db_path: Path = _UNSET_PATH
    reel_factory_root: Path = Path(
        os.environ.get("REEL_FACTORY_ROOT", CREATOR_OS_REEL_FACTORY_ROOT)
    )
    reel_manifest_db: Path = _UNSET_PATH
    reel_render_queue_db: Path = _UNSET_PATH
    contentforge_root: Path = Path(
        os.environ.get("CONTENTFORGE_ROOT", CREATOR_OS_CONTENTFORGE_ROOT)
    )
    reference_factory_root: Path = Path(
        os.environ.get("REFERENCE_FACTORY_ROOT", CREATOR_OS_REFERENCE_FACTORY_ROOT)
    )
    reference_reels_root: Path = Path(
        os.environ.get("REFERENCE_REELS_ROOT", _PATHS.reference_data_root)
    )
    reference_factory_db: Path = _UNSET_PATH
    # Compatibility attribute for older call signatures. ContentForge is
    # subprocess-only; no URL or HTTP mode is configurable.
    contentforge_base_url: str = "cli://local"
    threadsdash_root: Path = Path(
        os.environ.get("THREADSDASH_ROOT", DEFAULT_THREADSDASH_ROOT)
    )
    campaigns_dir: Path = Path(
        os.environ.get(
            "CAMPAIGN_FACTORY_CAMPAIGNS",
            _PATHS.artifact_root / "campaign_factory" / "campaigns",
        )
    )

    def __post_init__(self) -> None:
        campaign_root_is_override = self.root != CREATOR_OS_CAMPAIGN_FACTORY_ROOT
        reel_root_is_override = self.reel_factory_root != CREATOR_OS_REEL_FACTORY_ROOT
        reference_root_is_override = (
            self.reference_reels_root != _PATHS.reference_data_root
        )
        campaign_factory_db = Path(
            os.environ.get("CAMPAIGN_FACTORY_DB")
            or (
                self.root / "campaign_factory.sqlite"
                if campaign_root_is_override
                else _PATHS.campaign_factory_db
            )
        )
        reel_manifest_db = Path(
            self.reel_factory_root / "manifest.sqlite"
            if reel_root_is_override
            else os.environ.get("REEL_FACTORY_MANIFEST_DB") or _PATHS.reel_manifest_db
        )
        reel_render_queue_db = Path(
            self.reel_factory_root / "render_queue.sqlite"
            if reel_root_is_override
            else os.environ.get("REEL_FACTORY_RENDER_QUEUE_DB")
            or _PATHS.reel_render_queue_db
        )
        reference_factory_db = Path(
            self.reference_reels_root / "reference_factory.sqlite"
            if reference_root_is_override
            else os.environ.get("REFERENCE_FACTORY_DB") or _PATHS.reference_factory_db
        )
        for field_name, value in (
            ("db_path", campaign_factory_db),
            ("reel_manifest_db", reel_manifest_db),
            ("reel_render_queue_db", reel_render_queue_db),
            ("reference_factory_db", reference_factory_db),
        ):
            if getattr(self, field_name) == _UNSET_PATH:
                object.__setattr__(self, field_name, value.expanduser().resolve())


def get_settings() -> Settings:
    return Settings()


def resolve_repo_roots(projects_root: Path) -> dict[str, Path]:
    return resolve_component_roots(projects_root)
