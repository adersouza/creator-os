"""Recipe config loading and validation."""
from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


ALLOWED_COLOR_PRESETS = {"none", "bright_pop", "warm", "cool", "cinematic"}
ALLOWED_CAPTION_COLORS = {"light", "dark", "auto"}
ALLOWED_CAPTION_STYLES = {"classic", "meme", "ig", "thin", "soft", "bubble", "auto"}
ALLOWED_CAPTION_BANDS = {"top", "center", "bottom", "left", "right", "auto"}
ALLOWED_TEXT_VARIATION = {"off", "auto"}
ALLOWED_FONTS = {
    "auto",
    "Instagram Sans Condensed",
    "Instagram Sans Condensed Bold",
}
ALLOWED_TARGET_RATIOS = {"9:16", "4:5"}


def _validate_recipe_item(item: dict, idx: int) -> None:
    name = item.get("name", f"#{idx}")
    for field_name in ("trim_head", "trim_tail"):
        if field_name in item and float(item[field_name]) < 0:
            raise ValueError(f"recipe {name} {field_name} must be >= 0")
    if "speed" in item and float(item["speed"]) <= 0:
        raise ValueError(f"recipe {name} speed must be > 0")
    if "zoom" in item and float(item["zoom"]) <= 0:
        raise ValueError(f"recipe {name} zoom must be > 0")
    if "tilt_deg" in item and abs(float(item["tilt_deg"])) > 5:
        raise ValueError(f"recipe {name} tilt_deg must stay between -5 and 5")
    for field_name in ("eq_contrast", "eq_saturation"):
        if field_name in item and float(item[field_name]) <= 0:
            raise ValueError(f"recipe {name} {field_name} must be > 0")
    if "eq_brightness" in item and not -1 <= float(item["eq_brightness"]) <= 1:
        raise ValueError(f"recipe {name} eq_brightness must stay between -1 and 1")

    enum_checks = {
        "color_preset": ALLOWED_COLOR_PRESETS,
        "caption_color": ALLOWED_CAPTION_COLORS,
        "caption_style": ALLOWED_CAPTION_STYLES,
        "caption_band": ALLOWED_CAPTION_BANDS,
        "text_variation": ALLOWED_TEXT_VARIATION,
        "font": ALLOWED_FONTS,
    }
    for field_name, allowed in enum_checks.items():
        if field_name in item and item[field_name] not in allowed:
            raise ValueError(
                f"recipe {name} {field_name} must be one of {sorted(allowed)}"
            )
    if "target_ratios" in item:
        ratios = item["target_ratios"]
        if not isinstance(ratios, list) or not ratios:
            raise ValueError(f"recipe {name} target_ratios must be a non-empty list")
        unknown = set(ratios) - ALLOWED_TARGET_RATIOS
        if unknown:
            raise ValueError(f"recipe {name} target_ratios has unknown values: {sorted(unknown)}")


def load_recipes(path: Path, recipe_factory: Callable[..., T]) -> list[T]:
    """Load recipe objects from a JSON config file.

    The factory is usually the pipeline's ``Recipe`` dataclass. Validation is
    intentionally strict so typos in recipe files fail before any ffmpeg work.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"recipe config must be a list: {path}")

    allowed = {f.name for f in fields(recipe_factory)}
    required = {"name"}
    recipes: list[T] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"recipe #{idx} must be an object in {path}")
        missing = required - set(item)
        if missing:
            raise ValueError(f"recipe #{idx} missing required fields: {sorted(missing)}")
        unknown = set(item) - allowed
        if unknown:
            raise ValueError(f"recipe {item.get('name')} has unknown fields: {sorted(unknown)}")
        if item["name"] in seen:
            raise ValueError(f"duplicate recipe name: {item['name']}")
        _validate_recipe_item(item, idx)
        seen.add(item["name"])
        recipes.append(recipe_factory(**item))
    return recipes
