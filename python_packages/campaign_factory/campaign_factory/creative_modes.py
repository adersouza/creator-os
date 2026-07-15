from __future__ import annotations

from typing import Any

from .generation_execution_plan import build_generation_execution_plan

SCHEMA = "campaign_factory.creative_workflow_modes.v1"
MODE_PROMPT = "Which Creator OS mode do you want for this run?"

_MODES: tuple[dict[str, Any], ...] = (
    {
        "id": "library_reuse",
        "label": "Library reuse",
        "costLabel": "free",
        "input": "explicit media folder and model slug",
        "output": "review-ready library asset or safe variation",
        "entrypoint": "generation run --mode library_reuse",
    },
    {
        "id": "soul_static",
        "label": "Soul still + static MP4",
        "costLabel": "paid still generation, free MP4",
        "input": "operator-selected reference image",
        "output": "original/sexy Soul candidates with free static MP4 fallbacks",
        "entrypoint": "generation run --mode soul_static",
    },
    {
        "id": "motion_edit",
        "label": "Local motion edit",
        "costLabel": "free",
        "input": "approved still",
        "output": "local motion-edited MP4 with static fallback",
        "entrypoint": "generation run --mode motion_edit",
    },
    {
        "id": "best_only_kling",
        "label": "Best-only Kling",
        "costLabel": "paid video",
        "input": "approved rank-one static candidate and selection receipt",
        "output": "paid Kling video with retained static fallback",
        "entrypoint": "generation run --mode best_only_kling",
    },
    {
        "id": "reference_video_remix",
        "label": "Reference-video remix",
        "costLabel": "paid endpoint stills and paid Seedance/Kling video",
        "input": "operator-selected short reference video and motion analysis",
        "output": "new Soul endpoint frames and a review-ready Seedance or Kling video",
        "entrypoint": "generation run --mode reference_video_remix",
    },
)


def creative_workflow_modes() -> dict[str, Any]:
    """Return the stable operator-facing mode catalog.

    A mode advertises a real existing entrypoint. It does not grant provider
    spend or publishing authority; those remain separate runtime approvals.
    """
    modes = []
    for mode in _MODES:
        execution_plan = build_generation_execution_plan(str(mode["id"]))
        modes.append(
            {
                **mode,
                "requiredApprovals": list(execution_plan.required_approvals),
                "paidImageGeneration": execution_plan.paid_image_generation,
                "paidVideoGeneration": execution_plan.paid_video_generation,
                "staticFallbackRequired": execution_plan.static_fallback_required,
                "humanReviewRequired": True,
                "schedulingAllowed": False,
                "publishingAllowed": False,
            }
        )
    return {
        "schema": SCHEMA,
        "modePrompt": MODE_PROMPT,
        "selectionRequired": True,
        "modes": modes,
    }


def creative_workflow_mode(mode_id: str) -> dict[str, Any]:
    normalized = str(mode_id or "").strip().lower().replace("-", "_")
    catalog = creative_workflow_modes()
    for mode in catalog["modes"]:
        if mode["id"] == normalized:
            return mode
    raise ValueError(f"unknown creative workflow mode: {mode_id}")


def creative_workflow_mode_ids() -> tuple[str, ...]:
    return tuple(str(mode["id"]) for mode in _MODES)


def creative_workflow_menu() -> str:
    lines = [MODE_PROMPT]
    for index, mode in enumerate(_MODES, start=1):
        lines.append(f"{index}. {mode['label']} — {mode['costLabel']}")
    return "\n".join(lines)
