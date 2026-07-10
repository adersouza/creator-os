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
CREATOR_OS_CAMPAIGN_FACTORY_ROOT = (
    CREATOR_OS_ROOT / "python_packages" / "campaign_factory"
)
CREATOR_OS_REEL_FACTORY_ROOT = CREATOR_OS_ROOT / "python_packages" / "reel_factory"
CREATOR_OS_CONTENTFORGE_ROOT = CREATOR_OS_ROOT / "apps" / "contentforge"
CREATOR_OS_REFERENCE_FACTORY_ROOT = (
    CREATOR_OS_ROOT / "python_packages" / "reference_factory"
)
# ThreadsDashboard is an external sibling repo; default to <workspace>/ThreadsDashboard,
# override with THREADSDASH_ROOT. Avoids a hardcoded personal path.
DEFAULT_THREADSDASH_ROOT = WORKSPACE_ROOT / "ThreadsDashboard"


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
    contentforge_base_url: str = os.environ.get(
        "CONTENTFORGE_BASE_URL", "http://127.0.0.1:3002"
    )
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
    """Resolve sibling repo roots for smoke fixtures.

    Supports two layouts:
    - flat: ``<projects_root>/{reel_factory,contentforge,reference_factory,ThreadsDashboard}``
      (used by tests with temp dirs)
    - canonical: ``creator-os/python_packages/*``, ``creator-os/apps/contentforge``,
      with ``ThreadsDashboard`` as a sibling of ``creator-os``.

    ``projects_root`` may be the workspace root (parent of ``creator-os``) or the
    ``creator-os`` checkout itself. Env overrides (``REEL_FACTORY_ROOT`` etc.) win.
    """
    root = Path(projects_root).expanduser().resolve()
    if (root / "creator-os").is_dir():
        creator_os = root / "creator-os"
    elif root.name == "python_packages":
        # Legacy default from the smoke scripts: <creator-os>/python_packages
        creator_os = root.parent
    else:
        creator_os = root

    def pick(env_var: str, candidates: list[Path]) -> Path:
        env = os.environ.get(env_var)
        if env:
            return Path(env).expanduser().resolve()
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return candidates[-1]

    return {
        "reel_factory": pick(
            "REEL_FACTORY_ROOT",
            [
                root / "reel_factory",
                creator_os / "python_packages" / "reel_factory",
            ],
        ),
        "contentforge": pick(
            "CONTENTFORGE_ROOT",
            [
                root / "contentforge",
                creator_os / "apps" / "contentforge",
            ],
        ),
        "reference_factory": pick(
            "REFERENCE_FACTORY_ROOT",
            [
                root / "reference_factory",
                creator_os / "python_packages" / "reference_factory",
            ],
        ),
        "ThreadsDashboard": pick(
            "THREADSDASH_ROOT",
            [
                root / "ThreadsDashboard",
                creator_os.parent / "ThreadsDashboard",
            ],
        ),
    }
