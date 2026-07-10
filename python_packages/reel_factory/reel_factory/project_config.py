"""Small TOML-backed project configuration for reel_factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .fileops import atomic_write_text

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


DEFAULT_CONFIG: dict[str, Any] = {
    "workers": 3,
    "caption_renderer": "pillow",
    "placement_mode": "source",
    "output_profile": "mac_h264_videotoolbox",
    "target_ratios": ["9:16"],
    "audio_enabled": False,
    "strict_preflight": False,
    "dailyBudgetUsd": 10.0,
    "perRunMaxAssets": 2,
    "minimumBalanceUsd": 5.0,
}


def config_path(root: Path) -> Path:
    return Path(root) / "reel_factory.toml"


def load_config(root: Path) -> dict[str, Any]:
    path = config_path(Path(root))
    data = dict(DEFAULT_CONFIG)
    if path.exists():
        loaded = tomllib.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update(loaded)
    return data


def save_config(root: Path, updates: dict[str, Any]) -> dict[str, Any]:
    data = load_config(root)
    allowed = set(DEFAULT_CONFIG)
    for key, value in updates.items():
        if key in allowed:
            data[key] = value
    lines = []
    for key, value in data.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = str(value)
        elif isinstance(value, list):
            rendered = "[" + ", ".join(_quote(str(v)) for v in value) + "]"
        else:
            rendered = _quote(str(value))
        lines.append(f"{key} = {rendered}")
    atomic_write_text(
        config_path(Path(root)), "\n".join(lines) + "\n", encoding="utf-8"
    )
    return data


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
