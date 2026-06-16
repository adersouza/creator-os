from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEVELOPER_ROOT = PROJECT_ROOT.parent


def _default_creator_os_root() -> Path:
    if PROJECT_ROOT.parent.name == "python_packages":
        return PROJECT_ROOT.parent.parent
    return DEVELOPER_ROOT / "creator-os"


CREATOR_OS_ROOT = Path(os.environ.get("CREATOR_OS_ROOT", _default_creator_os_root()))
WORKSPACE_ROOT = CREATOR_OS_ROOT.parent
CREATOR_OS_CAMPAIGN_FACTORY_ROOT = CREATOR_OS_ROOT / "python_packages" / "campaign_factory"
CREATOR_OS_REEL_FACTORY_ROOT = CREATOR_OS_ROOT / "python_packages" / "reel_factory"
CREATOR_OS_CONTENTFORGE_ROOT = CREATOR_OS_ROOT / "apps" / "contentforge"
CREATOR_OS_REFERENCE_FACTORY_ROOT = CREATOR_OS_ROOT / "python_packages" / "reference_factory"


@dataclass(frozen=True)
class Settings:
    root: Path = Path(os.environ.get("CAMPAIGN_FACTORY_ROOT", CREATOR_OS_CAMPAIGN_FACTORY_ROOT))
    db_path: Path = Path(os.environ.get("CAMPAIGN_FACTORY_DB", CREATOR_OS_CAMPAIGN_FACTORY_ROOT / "campaign_factory.sqlite"))
    reel_factory_root: Path = Path(os.environ.get("REEL_FACTORY_ROOT", CREATOR_OS_REEL_FACTORY_ROOT))
    contentforge_root: Path = Path(os.environ.get("CONTENTFORGE_ROOT", CREATOR_OS_CONTENTFORGE_ROOT))
    reference_factory_root: Path = Path(os.environ.get("REFERENCE_FACTORY_ROOT", CREATOR_OS_REFERENCE_FACTORY_ROOT))
    reference_reels_root: Path = Path(os.environ.get("REFERENCE_REELS_ROOT", WORKSPACE_ROOT / "reference_reels"))
    contentforge_base_url: str = os.environ.get("CONTENTFORGE_BASE_URL", "http://127.0.0.1:3000")
    threadsdash_root: Path = Path(os.environ.get("THREADSDASH_ROOT", WORKSPACE_ROOT / "ThreadsDashboard"))
    campaigns_dir: Path = Path(os.environ.get("CAMPAIGN_FACTORY_CAMPAIGNS", CREATOR_OS_CAMPAIGN_FACTORY_ROOT / "campaigns"))


def get_settings() -> Settings:
    return Settings()
