from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTEST_PATH_ORDER = (
    ROOT / "python_packages" / "campaign_factory",
    ROOT / "python_packages" / "reel_factory",
    ROOT / "python_packages" / "reference_factory",
    ROOT / "packages" / "pipeline_contracts",
)


def _normalize_monorepo_imports() -> None:
    # The root pytest run mixes legacy Reel top-level modules with real
    # package imports; keep the package paths deterministic for collection.
    for path in map(str, PYTEST_PATH_ORDER):
        while path in sys.path:
            sys.path.remove(path)
    for path in reversed(tuple(map(str, PYTEST_PATH_ORDER))):
        sys.path.insert(0, path)

    campaign_module = sys.modules.get("campaign_factory")
    if campaign_module is not None and not hasattr(campaign_module, "__path__"):
        for name in list(sys.modules):
            if name == "campaign_factory" or name.startswith("campaign_factory."):
                sys.modules.pop(name, None)
    importlib.import_module("campaign_factory")


def pytest_configure() -> None:
    _normalize_monorepo_imports()


def pytest_collect_file(file_path: Path, parent: object) -> None:
    _normalize_monorepo_imports()


def pytest_pycollect_makemodule(module_path: Path, parent: object) -> None:
    _normalize_monorepo_imports()
