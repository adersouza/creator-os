from __future__ import annotations

import hashlib
import json
import re
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


def intake_operator_direction(source: dict[str, Any]) -> dict[str, Any]:
    """Return the immutable operator-supplied direction stored at URL intake."""
    raw: Any = source.get("intake_metadata_json")
    if raw is None:
        raw = source.get("intakeMetadata")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except json.JSONDecodeError:
            raw = {}
    metadata = raw if isinstance(raw, dict) else {}
    warnings: list[str] = []
    for value in metadata.get("operatorWarnings") or []:
        text = " ".join(str(value or "").split())
        if text and text not in warnings:
            warnings.append(text)
    description = " ".join(str(metadata.get("description") or "").split()) or None
    classification = (
        " ".join(str(metadata.get("operatorClassification") or "").split()) or None
    )
    return {
        "schema": "reference_factory.operator_direction.v1",
        "source": "source_files.intake_metadata_json",
        "description": description,
        "classification": classification,
        "warnings": warnings,
        "declaredTalking": metadata.get("declaredTalking") is True,
        "declaredNonTalking": metadata.get("declaredNonTalking") is True,
    }


def reference_source_binding(source: dict[str, Any]) -> dict[str, Any]:
    """Bind derived analysis to one exact stored reference and byte hash."""
    reference_id = str(
        source.get("reference_id") or source.get("referenceId") or ""
    ).strip()
    source_sha256 = str(
        source.get("content_hash") or source.get("sourceSha256") or ""
    ).strip()
    if not reference_id:
        raise ValueError("reference source binding requires reference_id")
    if len(source_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in source_sha256.lower()
    ):
        raise ValueError("reference source binding requires exact source SHA-256")
    core = f"{reference_id}:{source_sha256.lower()}"
    return {
        "schema": "reference_factory.source_binding.v1",
        "referenceId": reference_id,
        "sourceSha256": source_sha256.lower(),
        "bindingFingerprint": hashlib.sha256(core.encode("utf-8")).hexdigest(),
    }


def structural_reference_policy(source: dict[str, Any]) -> dict[str, Any]:
    """Declare how a Reel or screenshot may influence a generated first frame."""
    source_kind = _norm(source.get("kind"))
    return {
        "schema": "reference_factory.structural_reference_policy.v1",
        "sourceRole": (
            "screenshot_composition_pose_reference"
            if source_kind == "image"
            else "reel_motion_composition_reference"
        ),
        "allowedSourceInfluence": [
            "first_frame_angle",
            "first_frame_crop",
            "first_frame_pose",
            "camera_distance",
            "subject_scale",
            "motion_timing",
        ],
        "sourceIdentityUse": "blocked",
        "identitySource": "selected_soul_only",
        "subjectDirection": {
            "adultAge": 19,
            "subjectDescription": "adult woman, age 19, with dark hair",
            "hairColor": "dark",
            "bodyDirection": (
                "body-forward but non-explicit; when visibly supported by the source, "
                "preserve fuller-chest and cleavage framing plus a rounded hip and butt "
                "silhouette as visual geometry through fitted clothing, crop, angle, "
                "and pose"
            ),
            "exposure": "fully covered and social-platform safe",
        },
        "requiredFirstFrameFields": ["angle", "crop", "pose"],
    }


def normalize_reference_analysis_prompt(prompt_text: str) -> str:
    """Apply the fixed adult/Soul direction to the prompt actually exported."""
    value = re.sub(
        r"\byoung\s+woman\b",
        "adult woman, age 19, with dark hair",
        prompt_text,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:tat" + r"too)s?\b",
        "identity-specific physical trait",
        value,
        flags=re.IGNORECASE,
    )
    value = value.replace(
        "Do not add new body markings or identity traits. If hair is visible, "
        "describe the observed hair only inside the `hair` field.",
        "Do not import identity-specific physical traits from the source. The "
        "generated subject is an adult woman, age 19, with dark hair, and the "
        "selected Soul ID is the sole identity source.",
    )
    value = value.replace(
        '"color": "Honey brown with golden highlights"',
        '"color": "Dark"',
    )
    return value
