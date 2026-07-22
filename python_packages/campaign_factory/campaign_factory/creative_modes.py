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
        "id": "local_wan",
        "label": "Local Wan / LTX motion",
        "costLabel": "free",
        "input": "approved still plus optional source audio and explicit local task",
        "output": "local MLX Wan, LTX, or experimental LongCat review MP4 with static fallback and lineage",
        "entrypoint": "generation run --mode local_wan",
    },
    {
        "id": "best_motion",
        "label": "Best paid motion",
        "costLabel": "paid video",
        "input": "approved still plus explicit WaveSpeed model and motion prompt",
        "output": "Wan 2.7 Pro, reference, or speaking video with static fallback",
        "entrypoint": "generation run --mode best_motion",
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

# These definitions remain readable for historical run replay and contract
# validation, but they are intentionally absent from the operator catalog and
# CLI choices.  New work cannot select the retired FFmpeg motion mode or the
# Kling-only policy surface.
_RETIRED_MODES: dict[str, dict[str, Any]] = {
    "motion_edit": {
        "id": "motion_edit",
        "label": "Retired local motion edit",
        "costLabel": "retired",
        "input": "historical evidence only",
        "output": "historical evidence only",
        "entrypoint": None,
        "operatorSelectable": False,
    },
    "best_only_kling": {
        "id": "best_only_kling",
        "label": "Retired Kling-only mode",
        "costLabel": "retired",
        "input": "historical evidence only",
        "output": "historical evidence only",
        "entrypoint": None,
        "operatorSelectable": False,
    },
}


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
    retired = _RETIRED_MODES.get(normalized)
    if retired is not None:
        execution_plan = build_generation_execution_plan(normalized)
        return {
            **retired,
            "requiredApprovals": list(execution_plan.required_approvals),
            "paidImageGeneration": execution_plan.paid_image_generation,
            "paidVideoGeneration": execution_plan.paid_video_generation,
            "staticFallbackRequired": execution_plan.static_fallback_required,
            "humanReviewRequired": True,
            "schedulingAllowed": False,
            "publishingAllowed": False,
        }
    raise ValueError(f"unknown creative workflow mode: {mode_id}")


def creative_workflow_mode_ids() -> tuple[str, ...]:
    return tuple(str(mode["id"]) for mode in _MODES)


def creative_workflow_menu() -> str:
    lines = [MODE_PROMPT]
    for index, mode in enumerate(_MODES, start=1):
        lines.append(f"{index}. {mode['label']} — {mode['costLabel']}")
    return "\n".join(lines)
