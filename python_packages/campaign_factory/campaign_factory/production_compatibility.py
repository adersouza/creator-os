"""Evidence-only source compatibility for the existing passive production lane."""

from __future__ import annotations

import json
from typing import Any

SCHEMA = "campaign_factory.pre_spend_compatibility.v1"
OBSERVABLE_FIELDS = (
    "faceVisibility",
    "faceAngle",
    "bodyVisibility",
    "poseClass",
    "poseComplexity",
    "handLimbVisibility",
    "occlusions",
    "availableMovementSpace",
    "backgroundComplexity",
    "indoorOutdoor",
    "lightingCondition",
    "framing",
    "cameraDistance",
)
_ALIASES = {
    "faceVisibility": ("face_visibility",),
    "faceAngle": ("face_angle",),
    "bodyVisibility": ("body_visibility",),
    "poseClass": ("pose_class",),
    "poseComplexity": ("pose_complexity",),
    "handLimbVisibility": ("hand_limb_visibility", "handsVisible"),
    "occlusions": ("occlusion",),
    "availableMovementSpace": ("available_movement_space",),
    "backgroundComplexity": ("background_complexity",),
    "indoorOutdoor": ("indoor_outdoor", "environment"),
    "lightingCondition": ("lighting_condition",),
    "cameraDistance": ("camera_distance",),
}


def _observation(analysis: dict[str, Any], field: str) -> Any:
    for key in (field, *_ALIASES.get(field, ())):
        value = analysis.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _metadata(source: dict[str, Any]) -> dict[str, Any]:
    value = source.get("metadata")
    if isinstance(value, dict):
        return value
    raw = source.get("metadata_json")
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def assess_source_compatibility(source: dict[str, Any]) -> dict[str, Any]:
    """Use recorded observations only; no provider calls and no model scoring."""

    metadata = _metadata(source)
    analysis = metadata.get("visualAnalysis")
    analysis = analysis if isinstance(analysis, dict) else metadata
    resolution = source.get("sourceResolution")
    resolution = resolution if isinstance(resolution, dict) else {}
    facts: dict[str, Any] = {
        "schema": SCHEMA,
        **{
            field: _observation(analysis, field)
            for field in OBSERVABLE_FIELDS
            if _observation(analysis, field) is not None
        },
        "dimensions": (
            {
                "width": resolution.get("width"),
                "height": resolution.get("height"),
            }
            if resolution
            else None
        ),
        "aspectRatio": resolution.get("aspectRatio"),
        "sceneType": analysis.get("sceneType"),
    }
    blockers: list[str] = []
    ratio = resolution.get("aspectRatio")
    if isinstance(ratio, (int, float)) and not 0.50 <= float(ratio) <= 0.65:
        blockers.append("portrait_aspect_ratio_incompatible")
    if analysis.get("faceVisibility") is False:
        blockers.append("face_not_visible")
    if analysis.get("fullHeadVisible") is False:
        blockers.append("full_head_not_visible")
    unknowns = [
        field for field in (*OBSERVABLE_FIELDS, "sceneType") if field not in facts
    ]
    return {
        "schema": SCHEMA,
        "sourceAssetId": source.get("id"),
        "sourceSha256": source.get("content_hash"),
        "observedFacts": facts,
        "hardBlockers": blockers,
        "benchmarkSupportedModelEvidence": [],
        "unknowns": unknowns,
        "status": "blocked" if blockers else "advisory",
        "providerCalls": 0,
        "modelSwitchAuthorized": False,
        "spendAuthorized": False,
    }
