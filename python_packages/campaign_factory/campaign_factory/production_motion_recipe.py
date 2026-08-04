"""Validated Higgsfield motion recipes for the production lane."""

from __future__ import annotations

import math
from typing import Any, Final

from .production_higgsfield_authorization import _fingerprint
from .production_prompts import INTENT_PROMPTS
from .recreate_reel import RECREATE_REEL_STAGE

SCHEMA: Final = "campaign_factory.production_motion_recipe.v1"
RECREATE_INTENTS: Final = frozenset({"recreate_reel"})


def bind_recreation_duration(
    recipe: dict[str, Any], reference_analysis: dict[str, Any]
) -> None:
    recipe["stages"][0]["durationSeconds"] = min(
        5 if recipe.get("recreationMode") == "calm" else 15,
        max(
            4,
            int(
                math.floor(float(reference_analysis["media"]["durationSeconds"]) + 0.5)
            ),
        ),
    )
    core = {key: value for key, value in recipe.items() if key != "recipeFingerprint"}
    recipe["recipeFingerprint"] = _fingerprint(core)


def build_production_motion_recipe(
    *,
    creator: str,
    intent: str,
    execution: str,
    source_sha256: str,
    recreation_mode: str | None = None,
    reference_classification: str | None = None,
) -> dict[str, Any]:
    if not (creator_slug := creator.strip().lower().replace(" ", "_")):
        raise ValueError("creator is required")
    if intent not in INTENT_PROMPTS:
        raise ValueError(f"intent {intent!r} is not in the production motion catalog")
    if intent in RECREATE_INTENTS and recreation_mode not in {
        None,
        "calm",
        "structural",
    }:
        raise ValueError("recreation mode must be calm or structural")
    if (
        execution == "cloud"
        and intent in RECREATE_INTENTS
        and recreation_mode == "calm"
    ):
        mode = "recreate_reel"
        stage = {
            "modelId": "higgsfield_kling3_turbo_i2v",
            "providerModel": "kling3_0_turbo",
            "recipeId": "higgsfield_passive_selfie",
            "durationSeconds": 5,
            "resolution": "720p",
            "mode": "turbo",
            "providerAudioControl": "unavailable",
            "requiredOutputAudioStreams": 0,
        }
        stages = ({**stage, "task": "image_to_video"},)
        model_id = str(stages[0]["modelId"])
        status = "supported"
        visual_selection_required = False
    elif execution == "cloud" and intent in RECREATE_INTENTS:
        mode = "recreate_reel"
        stages = ({**RECREATE_REEL_STAGE},)
        model_id = str(stages[0]["modelId"])
        status = "experimental"
        visual_selection_required = True
    elif execution == "cloud":
        mode = "calm_animation"
        stage = {
            "modelId": "higgsfield_kling3_turbo_i2v",
            "providerModel": "kling3_0_turbo",
            "recipeId": "higgsfield_passive_selfie",
            "durationSeconds": 5,
            "resolution": "720p",
            "mode": "turbo",
            "providerAudioControl": "unavailable",
            "requiredOutputAudioStreams": 0,
        }
        stages = ({**stage, "task": "image_to_video"},)
        model_id = str(stages[0]["modelId"])
        status = "supported"
        visual_selection_required = False
    else:
        raise ValueError("production create requires Higgsfield cloud execution")
    core = {
        "schema": SCHEMA,
        "recipeId": f"{execution}_{intent}_creator_motion_v2",
        "status": status,
        "creator": creator_slug,
        "intent": intent,
        "mode": mode,
        "modelId": model_id,
        "stages": [dict(stage) for stage in stages],
        "sourceSha256": source_sha256,
        "paidProviderFallbackAllowed": False,
        "researchSelectionRequired": False,
        "operatorVisualSelectionRequired": visual_selection_required,
        "provider": "higgsfield",
        "recreationMode": recreation_mode if intent in RECREATE_INTENTS else None,
        "referenceClassification": (
            reference_classification if intent in RECREATE_INTENTS else None
        ),
    }
    return {**core, "recipeFingerprint": _fingerprint(core)}


def validate_production_motion_recipe(
    recipe: dict[str, Any], *, model_id: str, source_sha256: str
) -> dict[str, Any]:
    core = dict(recipe)
    claimed = str(core.pop("recipeFingerprint", ""))
    if (
        core.get("schema") != SCHEMA
        or core.get("status") not in {"supported", "experimental"}
        or core.get("modelId") != model_id
        or core.get("sourceSha256") != source_sha256
        or core.get("researchSelectionRequired") is not False
        or core.get("operatorVisualSelectionRequired")
        != (core.get("status") == "experimental")
        or core.get("provider") != "higgsfield"
        or core.get("paidProviderFallbackAllowed") is not False
        or claimed != _fingerprint(core)
    ):
        raise PermissionError("production_motion_recipe_invalid")
    return recipe


def bind_production_motion_recipe(
    recipe: dict[str, Any] | None,
    *,
    model_id: str,
    source_sha256: str,
    research_admission: Any,
) -> bool:
    if recipe is None:
        return False
    if research_admission is not None:
        raise PermissionError("mixed_local_production_and_research_evidence")
    validate_production_motion_recipe(
        dict(recipe), model_id=model_id, source_sha256=source_sha256
    )
    return True
