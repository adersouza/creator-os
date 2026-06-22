"""Platform safe-zone scoring for vertical social outputs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PLATFORM_SAFE_ZONES: dict[str, dict[str, float]] = {
    "instagram_reels": {"top_pct": 14.6, "bottom_pct": 25.0, "left_pct": 5.0, "right_pct": 5.0},
    "instagram_feed": {"top_pct": 4.0, "bottom_pct": 8.0, "left_pct": 4.0, "right_pct": 4.0},
    "instagram_square": {"top_pct": 4.0, "bottom_pct": 8.0, "left_pct": 4.0, "right_pct": 4.0},
    "tiktok": {"top_pct": 10.0, "bottom_pct": 24.0, "left_pct": 6.0, "right_pct": 13.0},
}


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    @classmethod
    def from_value(cls, value: Any) -> "Box | None":
        if not value:
            return None
        if isinstance(value, dict):
            try:
                return cls(float(value["x"]), float(value["y"]), float(value["w"]), float(value["h"]))
            except (KeyError, TypeError, ValueError):
                return None
        if isinstance(value, (list, tuple)) and len(value) == 4:
            try:
                return cls(float(value[0]), float(value[1]), float(value[2]), float(value[3]))
            except (TypeError, ValueError):
                return None
        return None

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


def score_safe_zone(
    *,
    width: int | None,
    height: int | None,
    platform: str = "instagram_reels",
    caption_box: Any = None,
    face_box: Any = None,
) -> dict[str, Any]:
    zones = PLATFORM_SAFE_ZONES.get(platform, PLATFORM_SAFE_ZONES["instagram_reels"])
    warnings: list[str] = []
    caption = Box.from_value(caption_box)
    face = Box.from_value(face_box)
    caption_collision = False
    face_collision = False
    bottom_ui_risk = 0.0
    right_rail_risk = 0.0

    if not width or not height:
        warnings.append("safe_zone_dimensions_unknown")
    else:
        top = height * zones["top_pct"] / 100.0
        bottom = height * (1.0 - zones["bottom_pct"] / 100.0)
        left = width * zones["left_pct"] / 100.0
        right = width * (1.0 - zones["right_pct"] / 100.0)
        for label, box in (("caption", caption), ("face", face)):
            if not box:
                continue
            collides = box.y < top or box.bottom > bottom or box.x < left or box.right > right
            if collides and label == "caption":
                caption_collision = True
            if collides and label == "face":
                face_collision = True
        if caption_collision:
            warnings.append("caption_safe_zone_collision")
        if face_collision:
            warnings.append("face_safe_zone_collision")
        if caption:
            bottom_ui_risk = max(0.0, min(1.0, (caption.bottom - bottom) / max(1.0, height - bottom)))
            right_rail_risk = max(0.0, min(1.0, (caption.right - right) / max(1.0, width - right)))

    return {
        "schema": "reel_factory.safe_zone_score.v1",
        "platform": platform,
        "zones": zones,
        "safeZoneStatus": "warn" if warnings else "pass",
        "captionCollision": caption_collision,
        "faceCollision": face_collision,
        "bottomUiRisk": round(bottom_ui_risk, 3),
        "rightRailRisk": round(right_rail_risk, 3),
        "warnings": warnings,
    }
