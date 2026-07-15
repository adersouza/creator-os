from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for relative in (
    "packages/pipeline_contracts",
    "packages/creator_os_core",
    "python_packages/campaign_factory",
    "python_packages/reel_factory",
):
    sys.path.insert(0, str(ROOT / relative))

from reel_factory.generate_prompts import (  # noqa: E402
    build_higgsfield_reference_prompt_instruction,
)
from reel_factory.reference_video_remix import (  # noqa: E402
    gemini_motion_analysis_instruction,
)


def render_prompt(context: dict[str, Any]) -> str:
    """Render production prompts or captured caption text without a model call."""
    variables = context.get("vars") or {}
    surface = str(variables.get("surface") or "")
    if surface == "gemini_motion_analysis":
        return gemini_motion_analysis_instruction(str(variables["reference_id"]))
    if surface == "soul_reference_still":
        return build_higgsfield_reference_prompt_instruction(
            str(variables.get("creative_direction") or "")
        )
    if surface == "caption_hook":
        fixture = _fixture(variables)
        return str(fixture["text"])
    raise ValueError(f"unsupported offline prompt surface: {surface}")


def _fixture(variables: dict[str, Any]) -> dict[str, Any]:
    path = (ROOT / str(variables["captured_fixture"])).resolve()
    if ROOT not in path.parents:
        raise ValueError("captured fixture must stay inside the repository")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("captured fixture must be a JSON object")
    return value
