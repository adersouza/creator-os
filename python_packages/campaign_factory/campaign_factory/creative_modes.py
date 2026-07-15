from __future__ import annotations

from typing import Any

SCHEMA = "campaign_factory.creative_workflow_modes.v1"

_MODES: tuple[dict[str, Any], ...] = (
    {
        "id": "library_reuse",
        "label": "Library reuse",
        "input": "approved existing image or video",
        "output": "review-ready library asset or safe variation",
        "entrypoint": "proactive-cycle run --generation-mode existing_asset",
        "paidImageGeneration": False,
        "paidVideoGeneration": False,
        "staticFallbackRequired": False,
    },
    {
        "id": "soul_static",
        "label": "Soul still plus static MP4",
        "input": "operator-selected reference image",
        "output": "original/sexy Soul candidates with free static MP4 fallbacks",
        "entrypoint": "generation front-link --animation-mode static",
        "paidImageGeneration": True,
        "paidVideoGeneration": False,
        "staticFallbackRequired": True,
    },
    {
        "id": "motion_edit",
        "label": "Deterministic motion edit",
        "input": "approved still",
        "output": "local motion-edited MP4 with static fallback",
        "entrypoint": "generation front-link --animation-mode motion_edit",
        "paidImageGeneration": False,
        "paidVideoGeneration": False,
        "staticFallbackRequired": True,
    },
    {
        "id": "best_only_kling",
        "label": "Best-only Kling animation",
        "input": "approved rank-one static candidate and selection receipt",
        "output": "paid Kling video with retained static fallback",
        "entrypoint": "generation front-link --animation-mode kling",
        "paidImageGeneration": False,
        "paidVideoGeneration": True,
        "staticFallbackRequired": True,
    },
    {
        "id": "reference_video_remix",
        "label": "Structural reference-video remix",
        "input": "operator-selected short reference video and motion analysis",
        "output": "new Soul endpoint frames and Seedance or Kling animation plan",
        "entrypoint": "reel_factory.reference_video_remix",
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
            "publishingAllowed": False,
        }
        for mode in _MODES
    ]
    return {
        "schema": SCHEMA,
        "defaultMode": "library_reuse",
        "modes": modes,
    }


def creative_workflow_mode(mode_id: str) -> dict[str, Any]:
    normalized = str(mode_id or "").strip().lower().replace("-", "_")
    catalog = creative_workflow_modes()
    for mode in catalog["modes"]:
        if mode["id"] == normalized:
            return mode
    raise ValueError(f"unknown creative workflow mode: {mode_id}")
