from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from pipeline_contracts import validate_generated_asset_lineage_v2

LINEAGE_V2_SCHEMA = "reel_factory.generated_asset_lineage.v2"
_AUDIO_INTENT_NON_SEMANTIC_KEYS = {
    "pipelineTraceId",
    "assignee",
    "selected_by",
    "attached_by",
    "verified_by",
}


def canonical_json_sha256(value: Any) -> str:
    """Hash canonical UTF-8 JSON with sorted keys and no insignificant whitespace."""
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def audio_intent_fingerprint(audio_intent: dict[str, Any]) -> str:
    """Fingerprint intent semantics while ignoring audit/assignment metadata."""
    return canonical_json_sha256(_audio_intent_semantic_value(audio_intent))


def _audio_intent_semantic_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _audio_intent_semantic_value(item)
            for key, item in value.items()
            if key not in _AUDIO_INTENT_NON_SEMANTIC_KEYS
            and not key.endswith("_at")
            and not key.endswith("At")
        }
    if isinstance(value, list):
        return [_audio_intent_semantic_value(item) for item in value]
    return value


def build_lineage_v2_core(
    existing: dict[str, Any] | None,
    *,
    campaign_id: str,
    recipe_id: str,
    caption_hash: str,
    rendered_asset_id: str,
    content_fingerprint: str | None = None,
    prompt_id: str | None = None,
    reference_id: str | None = None,
) -> dict[str, Any]:
    """Upgrade upstream lineage and hard-check fields known before draft assembly."""
    lineage = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    source = lineage.get("source") if isinstance(lineage.get("source"), dict) else {}
    generation = (
        lineage.get("generation") if isinstance(lineage.get("generation"), dict) else {}
    )
    review = lineage.get("review") if isinstance(lineage.get("review"), dict) else {}

    resolved_prompt_id = _required_text(prompt_id or source.get("promptId"), "promptId")
    source["promptId"] = resolved_prompt_id
    resolved_reference_id = _optional_text(reference_id or source.get("referenceId"))
    if resolved_reference_id:
        source["referenceId"] = resolved_reference_id
    generation["tool"] = _required_text(
        generation.get("tool") or "manual_finished_video", "generation.tool"
    )

    lineage.update(
        {
            "schema": LINEAGE_V2_SCHEMA,
            "source": source,
            "generation": generation,
            "review": review,
            "campaignId": _required_text(campaign_id, "campaignId"),
            "recipeId": _required_text(recipe_id, "recipeId"),
            "captionHash": _required_text(caption_hash, "captionHash"),
            "renderedAssetId": _required_text(rendered_asset_id, "renderedAssetId"),
            "contentFingerprint": _required_text(
                content_fingerprint or lineage.get("contentFingerprint"),
                "contentFingerprint",
            ),
            "variationApplied": False,
            "variantId": None,
        }
    )
    if not _optional_text(lineage.get("pipelineTraceId")):
        lineage["pipelineTraceId"] = (
            "trace_generated_asset_"
            + canonical_json_sha256(
                {
                    "campaignId": campaign_id,
                    "renderedAssetId": rendered_asset_id,
                    "promptId": resolved_prompt_id,
                }
            )[:16]
        )
    lineage.pop("audioIntentFingerprint", None)
    for field in (
        "sourceFamilyId",
        "perceptualFingerprint",
        "perceptualClusterId",
        "perceptualAlgorithm",
    ):
        lineage[field] = _optional_text(lineage.get(field))
    lineage["audioId"] = _optional_text(lineage.get("audioId"))
    return lineage


def finalize_lineage_v2(
    lineage: dict[str, Any],
    *,
    audio_intent: dict[str, Any],
    variant_assignment: dict[str, Any] | None,
    audio_id: str | None = None,
) -> dict[str, Any]:
    """Stamp destination-specific audio/variant identity and validate v2."""
    result = copy.deepcopy(lineage)
    assignment = variant_assignment if isinstance(variant_assignment, dict) else None
    expected_variant_id = (
        _required_text(
            assignment.get("variant_asset_id"), "variantAssignment.variant_asset_id"
        )
        if assignment
        else None
    )
    prior_variant_id = _optional_text(result.get("variantId"))
    if assignment and prior_variant_id and prior_variant_id != expected_variant_id:
        raise ValueError(
            "generated asset lineage variantId does not match "
            "variantAssignment.variant_asset_id"
        )
    if not assignment and prior_variant_id:
        raise ValueError("base-asset lineage must carry variantId: null")
    result["variationApplied"] = bool(assignment)
    result["variantId"] = expected_variant_id
    result["audioIntentFingerprint"] = audio_intent_fingerprint(audio_intent)
    result["audioId"] = _optional_text(audio_id)
    validate_generated_asset_lineage_v2(result)
    return result


def lineage_v2_is_valid(
    value: Any,
    *,
    campaign_id: Any = None,
    recipe_id: Any = None,
    caption_hash: Any = None,
    rendered_asset_id: Any = None,
    variant_id: Any = None,
) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        validate_generated_asset_lineage_v2(value)
    except (TypeError, ValueError):
        return False
    expected = {
        "campaignId": _optional_text(campaign_id),
        "recipeId": _optional_text(recipe_id),
        "captionHash": _optional_text(caption_hash),
        "renderedAssetId": _optional_text(rendered_asset_id),
    }
    for key, expected_value in expected.items():
        if expected_value and _optional_text(value.get(key)) != expected_value:
            return False
    expected_variant = _optional_text(variant_id)
    actual_variant = _optional_text(value.get("variantId"))
    if expected_variant and actual_variant != expected_variant:
        return False
    if (
        not expected_variant
        and value.get("variationApplied") is False
        and actual_variant
    ):
        return False
    return True


def lineage_v2_is_learning_traceable(
    value: Any,
    *,
    campaign_id: Any = None,
    recipe_id: Any = None,
    caption_hash: Any = None,
    rendered_asset_id: Any = None,
    variant_id: Any = None,
) -> bool:
    """Require the stable v2 identities used by the forward learning cohort.

    ``renderedAssetId`` is the reel identity for this cohort. The published v2
    contract permits a null referenceId, so learning applies the stricter
    forward-only policy without changing the shared contract in place.
    """
    if not lineage_v2_is_valid(
        value,
        campaign_id=campaign_id,
        recipe_id=recipe_id,
        caption_hash=caption_hash,
        rendered_asset_id=rendered_asset_id,
        variant_id=variant_id,
    ):
        return False
    source = value.get("source") if isinstance(value, dict) else None
    return bool(
        isinstance(source, dict)
        and _optional_text(source.get("promptId"))
        and _optional_text(source.get("referenceId"))
        and _optional_text(value.get("campaignId"))
        and _optional_text(value.get("renderedAssetId"))
    )


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value)
    if not text:
        raise ValueError(f"generated asset lineage v2 missing {field}")
    return text


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
