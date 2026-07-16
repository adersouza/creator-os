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

from reel_factory.reference_video_remix import (  # noqa: E402
    gemini_motion_analysis_instruction,
)


def build_higgsfield_reference_prompt_instruction(
    creative_direction: str = "",
) -> str:
    """Captured offline Soul-reference prompt surface used only by Promptfoo."""
    direction = creative_direction.strip()
    extra = f"\nExtra direction from operator: {direction}\n" if direction else ""
    return (
        "Reference image attached.\n\n"
        "Make a prompt similar to this reference image for me to use in Higgsfield with Soul ID on my AI model.\n"
        "Make sure to get the pose down correctly, including body angle, camera angle, hand placement, crop, clothing, lighting, and setting.\n"
        "Make sure the prompt is sexy, body-forward, realistic, and amateur smartphone-style, while staying faithful to the reference pose, outfit, and setting.\n"
        "Do not mention hair, hairstyle, hair color, tattoos, identity traits, usernames, captions, UI, watermarks, or negative prompts.\n"
        "Do not make a grid, panel sheet, collage, or variation set. Write for exactly one standalone image.\n"
        "Do not say the reference image will be passed into Higgsfield. The final prompt must stand on its own.\n"
        f"{extra}\n"
        "Return only this JSON:\n"
        "{\n"
        '  "image_prompt": "...",\n'
        '  "notes": "..."\n'
        "}"
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
