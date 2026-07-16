from __future__ import annotations

from typing import Any

ANALYSIS_SCHEMA = "reference_factory.video_analysis.v1"
PATTERN_CARD_SCHEMA = "reference_factory.pattern_card.v1"
DEFAULT_INTAKE_PROFILE = "ig_ofm"
PROMPT_READY_STATUS = "prompt_ready"

IG_OFM_CLOSENESS_CONTROLS = {
    "format_closeness": "high",
    "identity_copy_risk": "blocked",
    "scene_variation_required": True,
    "spicy_ofm_coded": True,
}

FORMAT_PRIORITY = [
    "mirror_selfie",
    "selfie_video",
    "pov",
    "spicy_lifestyle",
    "slideshow",
    "other",
]

GEMINI_PROMPT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "schema": {"type": "string"},
        "referenceId": {"type": "string"},
        "summary": {"type": "string"},
        "contentFormat": {"type": "string"},
        "recreation_blueprint": {
            "type": "object",
            "properties": {
                "format_type": {"type": "string"},
                "first_frame": {"type": "object"},
                "motion_beats": {"type": "array"},
                "native_style_constraints": {"type": "array"},
                "copy_risk_notes": {"type": "array"},
                "required_changes": {"type": "array"},
            },
            "required": [
                "format_type",
                "first_frame",
                "motion_beats",
                "native_style_constraints",
                "copy_risk_notes",
                "required_changes",
            ],
            "additionalProperties": True,
        },
        "image_prompt_json": {"type": "object"},
        "higgsfield_soul_image_prompt": {"type": "string"},
        "higgsfield_negative_prompt": {"type": "string"},
        "kling_3_video_prompt": {"type": "string"},
        "kling_negative_prompt": {"type": "string"},
        "motion_notes": {"type": "string"},
        "camera_notes": {"type": "string"},
        "style_notes": {"type": "string"},
        "copy_risk_notes": {"type": "string"},
        "what_to_change": {"type": "string"},
    },
    "required": [
        "schema",
        "referenceId",
        "summary",
        "contentFormat",
        "recreation_blueprint",
        "image_prompt_json",
        "higgsfield_soul_image_prompt",
        "higgsfield_negative_prompt",
        "kling_3_video_prompt",
        "kling_negative_prompt",
        "motion_notes",
        "camera_notes",
        "style_notes",
        "copy_risk_notes",
        "what_to_change",
    ],
    "additionalProperties": True,
}

GEMINI_PROMPT_SCORING_RUBRIC: dict[str, Any] = {
    "schema": "reference_factory.gemini_prompt_scoring_rubric.v1",
    "scale": "1-10",
    "criteria": [
        {"key": "format_closeness", "label": "Format closeness", "weight": 1.2},
        {
            "key": "first_frame_geometry",
            "label": "First-frame crop / pose / subject scale accuracy",
            "weight": 1.4,
        },
        {
            "key": "originality_identity_safety",
            "label": "Originality / no identity copying",
            "weight": 1.2,
        },
        {"key": "soul_id_consistency", "label": "Soul ID consistency", "weight": 1.0},
        {
            "key": "image_prompt_usefulness",
            "label": "Higgsfield image prompt usefulness",
            "weight": 1.0,
        },
        {
            "key": "video_prompt_usefulness",
            "label": "Kling prompt usefulness",
            "weight": 1.0,
        },
        {"key": "motion_accuracy", "label": "Motion accuracy", "weight": 1.2},
        {
            "key": "amateur_native_feel",
            "label": "Amateur native phone-shot feel",
            "weight": 1.2,
        },
        {
            "key": "platform_native_realism",
            "label": "Instagram/TikTok native realism",
            "weight": 1.0,
        },
        {
            "key": "performance_potential",
            "label": "Likely Reels performance",
            "weight": 0.8,
        },
    ],
    "failureModes": [
        "over_describes",
        "misses_motion",
        "too_cinematic",
        "copies_identity_too_closely",
        "ignores_first_frame_needs",
        "vague_prompts",
        "invents_unseen_details",
        "loses_pose_or_fit",
        "changes_camera_distance",
    ],
}

GROK_PROMPT_MODEL_DEFAULT = "grok-4"
XAI_CHAT_COMPLETIONS_URL = "https://api.x.ai/v1/chat/completions"


def _canonical_tool(target_tool: object) -> str:
    tool = _norm(target_tool)
    if tool in {"higgsfield", "higgsfield_soul", "higgsfield_soul_image", "soul_id"}:
        return "higgsfield_soul_image"
    if tool in {"kling", "kling_3", "kling_3_0", "kling_3_video"}:
        return "kling_3_video"
    return tool


def _closeness_controls(intake_profile: str | None) -> dict[str, Any]:
    if _norm(intake_profile) == DEFAULT_INTAKE_PROFILE:
        return dict(IG_OFM_CLOSENESS_CONTROLS)
    return {
        "format_closeness": "medium",
        "identity_copy_risk": "blocked",
        "scene_variation_required": True,
        "spicy_ofm_coded": False,
    }


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().lower().replace("-", "_").split())
