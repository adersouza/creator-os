from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_canonical_package() -> ModuleType:
    repo_root = Path(__file__).resolve().parent.parent
    package_root = repo_root / "packages" / "pipeline_contracts" / "pipeline_contracts"
    init_path = package_root / "__init__.py"
    if not init_path.exists():
        raise ImportError(f"canonical pipeline_contracts package not found: {init_path}")

    module_name = "_creator_os_canonical_pipeline_contracts"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    spec = importlib.util.spec_from_file_location(
        module_name,
        init_path,
        submodule_search_locations=[str(package_root)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load canonical pipeline_contracts package: {init_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_canonical = _load_canonical_package()
_canonical_validator = sys.modules.get(f"{_canonical.__name__}.validator")
if _canonical_validator is not None:
    sys.modules[f"{__name__}.validator"] = _canonical_validator

for _name in getattr(_canonical, "__all__", []):
    globals()[_name] = getattr(_canonical, _name)

__all__ = list(getattr(_canonical, "__all__", []))
