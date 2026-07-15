from __future__ import annotations

from typing import Any

SCHEMA = "campaign_factory.creative_workflow_modes.v1"
MODE_PROMPT = "Which Creator OS mode do you want for this run?"

_MODES: tuple[dict[str, Any], ...] = (
    {
        "id": "library_reuse",
        "label": "Library reuse",
        "costLabel": "free",
        "input": "approved existing image or video",
        "output": "review-ready library asset or safe variation",
        "requiredApprovals": ["human_asset_approval"],
        "entrypoint": "generation run --mode library_reuse",
        "paidImageGeneration": False,
        "paidVideoGeneration": False,
        "staticFallbackRequired": False,
    },
    {
        "id": "soul_static",
        "label": "Soul still + static MP4",
        "costLabel": "paid still generation, free MP4",
        "input": "operator-selected reference image",
        "output": "original/sexy Soul candidates with free static MP4 fallbacks",
        "requiredApprovals": ["paid_generation", "human_still_approval"],
        "entrypoint": "generation run --mode soul_static",
        "paidImageGeneration": True,
        "paidVideoGeneration": False,
        "staticFallbackRequired": True,
    },
    {
        "id": "motion_edit",
        "label": "Local motion edit",
        "costLabel": "free",
        "input": "approved still",
        "output": "local motion-edited MP4 with static fallback",
        "requiredApprovals": ["human_still_approval"],
        "entrypoint": "generation run --mode motion_edit",
        "paidImageGeneration": False,
        "paidVideoGeneration": False,
        "staticFallbackRequired": True,
    },
    {
        "id": "best_only_kling",
        "label": "Best-only Kling",
        "costLabel": "paid video",
        "input": "approved rank-one static candidate and selection receipt",
        "output": "paid Kling video with retained static fallback",
        "requiredApprovals": [
            "human_still_approval",
            "contentforge_approval",
            "rank_one_selection_receipt",
            "paid_generation",
        ],
        "entrypoint": "generation run --mode best_only_kling",
        "paidImageGeneration": False,
        "paidVideoGeneration": True,
        "staticFallbackRequired": True,
    },
    {
        "id": "reference_video_remix",
        "label": "Reference-video remix",
        "costLabel": "paid endpoint stills and paid Seedance/Kling video",
        "input": "operator-selected short reference video and motion analysis",
        "output": "new Soul endpoint frames and a review-ready Seedance or Kling video",
        "requiredApprovals": [
            "reference_rights",
            "both_endpoint_frames",
            "paid_generation",
            "contentforge_approval",
            "final_human_review",
        ],
        "entrypoint": "generation run --mode reference_video_remix",
        "paidImageGeneration": True,
        "paidVideoGeneration": True,
        "staticFallbackRequired": True,
    },
)


def creative_workflow_modes() -> dict[str, Any]:
    """Return the stable operator-facing mode catalog.

    A mode advertises a real existing entrypoint. It does not grant provider
    spend or publishing authority; those remain separate runtime approvals.
    """
    modes = [
        {
            **mode,
            "humanReviewRequired": True,
            "schedulingAllowed": False,
            "publishingAllowed": False,
        }
        for mode in _MODES
    ]
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
