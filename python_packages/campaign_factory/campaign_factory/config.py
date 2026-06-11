from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEVELOPER_ROOT = PROJECT_ROOT.parent


@dataclass(frozen=True)
class Settings:
    root: Path = PROJECT_ROOT
    db_path: Path = Path(os.environ.get("CAMPAIGN_FACTORY_DB", PROJECT_ROOT / "campaign_factory.sqlite"))
    reel_factory_root: Path = Path(os.environ.get("REEL_FACTORY_ROOT", DEVELOPER_ROOT / "reel_factory"))
    contentforge_root: Path = Path(os.environ.get("CONTENTFORGE_ROOT", DEVELOPER_ROOT / "contentforge"))
    reference_factory_root: Path = Path(os.environ.get("REFERENCE_FACTORY_ROOT", DEVELOPER_ROOT / "reference_factory"))
    reference_reels_root: Path = Path(os.environ.get("REFERENCE_REELS_ROOT", DEVELOPER_ROOT / "reference_reels"))
    contentforge_base_url: str = os.environ.get("CONTENTFORGE_BASE_URL", "http://127.0.0.1:3000")
    threadsdash_root: Path = Path(os.environ.get("THREADSDASH_ROOT", DEVELOPER_ROOT / "ThreadsDashboard"))
    campaigns_dir: Path = Path(os.environ.get("CAMPAIGN_FACTORY_CAMPAIGNS", PROJECT_ROOT / "campaigns"))


def get_settings() -> Settings:
    return Settings()
