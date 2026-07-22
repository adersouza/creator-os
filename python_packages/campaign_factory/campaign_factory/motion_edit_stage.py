"""Fail-closed compatibility surface for the retired local motion-edit mode.

Historical records and contracts remain readable, but no supported runtime path
may create a pipeline job, rendered asset, provider call, or file through this
module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run_motion_edit_stage(
    factory: Any,
    *,
    campaign_slug: str,
    still_path: Path,
    caption: str,
    duration_seconds: float = 5.0,
    dry_run: bool = True,
    apply: bool = False,
    enable_variation: bool = False,
    variation_preset: str = "ig_subtle",
    allow_upscale: bool = False,
) -> dict[str, Any]:
    """Reject historical motion-edit execution before touching any state."""
    raise PermissionError("motion_edit_mode_retired")
