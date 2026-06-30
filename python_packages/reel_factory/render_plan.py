"""Typed render plan passed into the ffmpeg graph builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RenderPlan:
    src: Path
    caption_pngs: list[tuple[Path, float, float | None]]
    recipe: Any
    out: Path
    duration: float
    fonts_dir: Path
    src_hash: str
    src_dims: tuple[int, int]
    account_scope: str = "local_review"
    bitrate_mbps: int = 14
    src_bitrate_mbps: int | None = None
    output_profile: str = "social_h264"
    target_ratio: str = "9:16"


def validate_account_scope(
    account_scope: str | None, *, production_render: bool = False
) -> str:
    scope = (account_scope or "local_review").strip() or "local_review"
    if production_render and scope == "local_review":
        raise ValueError(
            "production render requires explicit account_id or account_group_id scope"
        )
    return scope
