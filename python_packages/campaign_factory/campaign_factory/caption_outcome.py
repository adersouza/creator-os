from __future__ import annotations

import hashlib
import json
from typing import Any

from pipeline_contracts import validate_caption_outcome_context

SCHEMA = "campaign_factory.caption_outcome_context.v1"

CONTEXT_COLUMNS = {
    "caption_hash",
    "caption_text",
    "caption_bank",
    "caption_banks_json",
    "creator_mix",
    "creator_model",
    "frame_type",
    "length_class",
    "format_class",
    "caption_fit_version",
    "suitability_decision",
    "suitability_reason",
    "source_clip",
    "caption_outcome_context_json",
}


def build_caption_outcome_context(
    *,
    caption_text: str | None = None,
    caption_hash: str | None = None,
    render_recipe: str | None = None,
    source_clip: str | None = None,
    rendered_output: str | None = None,
    creator_model: str | None = None,
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lineage = lineage if isinstance(lineage, dict) else {}
    existing = lineage if lineage.get("schema") == SCHEMA else {}
    caption_lineage = _caption_lineage(lineage)
    selected_banks = _list_value(
        existing.get("caption_banks")
        or caption_lineage.get("selectedBanks")
        or caption_lineage.get("selected_banks")
        or caption_lineage.get("sourceBanks")
        or caption_lineage.get("source_banks")
        or lineage.get("captionBanks")
        or lineage.get("caption_banks")
    )
    primary_bank = _first_text(
        existing.get("caption_bank"),
        caption_lineage.get("selectedBank"),
        caption_lineage.get("selected_bank"),
        selected_banks[0] if selected_banks else None,
        lineage.get("captionBank")
        if isinstance(lineage.get("captionBank"), str)
        else None,
    )
    text = _first_text(
        existing.get("caption_text"),
        caption_lineage.get("rawCaptionText"),
        caption_lineage.get("raw_caption_text"),
        lineage.get("captionText"),
        lineage.get("caption_text"),
        caption_text,
    )
    resolved_hash = _first_text(
        existing.get("caption_hash"),
        lineage.get("captionHash"),
        lineage.get("caption_hash"),
        caption_lineage.get("captionHash"),
        caption_lineage.get("caption_hash"),
        caption_hash,
        _text_hash(text) if text else None,
    )
    context = dict(existing)
    context.update(
        {
            "schema": SCHEMA,
            "caption_hash": resolved_hash,
            "caption_text": text,
            "caption_bank": primary_bank,
            "caption_banks": selected_banks or ([primary_bank] if primary_bank else []),
            "creator_mix": _first_text(
                existing.get("creator_mix"),
                caption_lineage.get("selectedMix"),
                caption_lineage.get("selected_mix"),
                lineage.get("creatorMix"),
                lineage.get("creator_mix"),
            ),
            "creator_model": _first_text(
                existing.get("creator_model"),
                lineage.get("creatorModel"),
                lineage.get("creator_model"),
                creator_model,
            ),
            "frame_type": _first_text(
                existing.get("frame_type"),
                caption_lineage.get("frameType"),
                caption_lineage.get("frame_type"),
                lineage.get("frameType"),
                lineage.get("frame_type"),
            ),
            "length_class": _first_text(
                existing.get("length_class"),
                caption_lineage.get("lengthClass"),
                caption_lineage.get("length_class"),
                lineage.get("lengthClass"),
                lineage.get("length_class"),
            ),
            "format_class": _first_text(
                existing.get("format_class"),
                caption_lineage.get("formatClass"),
                caption_lineage.get("format_class"),
                lineage.get("formatClass"),
                lineage.get("format_class"),
            ),
            "caption_fit_version": _first_text(
                existing.get("caption_fit_version"),
                caption_lineage.get("captionFitVersion"),
                caption_lineage.get("caption_fit_version"),
                lineage.get("captionFitVersion"),
                lineage.get("caption_fit_version"),
            ),
            "suitability_decision": _first_text(
                existing.get("suitability_decision"),
                caption_lineage.get("suitabilityDecision"),
                caption_lineage.get("suitability_decision"),
                lineage.get("suitabilityDecision"),
                lineage.get("suitability_decision"),
            ),
            "suitability_reason": _first_text(
                existing.get("suitability_reason"),
                caption_lineage.get("suitabilityReason"),
                caption_lineage.get("suitability_reason"),
                lineage.get("suitabilityReason"),
                lineage.get("suitability_reason"),
            ),
            "render_recipe": existing.get("render_recipe")
            if "render_recipe" in existing
            else _first_text(
                lineage.get("recipe"),
                lineage.get("renderRecipe"),
                lineage.get("render_recipe"),
                render_recipe,
            ),
            "source_clip": _first_text(
                existing.get("source_clip"),
                caption_lineage.get("sourceClip"),
                caption_lineage.get("source_clip"),
                lineage.get("sourceClip"),
                lineage.get("source_clip"),
                source_clip,
            ),
            "rendered_output": _first_text(
                existing.get("rendered_output"),
                lineage.get("renderedOutput"),
                lineage.get("rendered_output"),
                rendered_output,
            ),
        }
    )
    for key in (
        "captionSceneTags",
        "reelSceneTags",
        "sceneCompatibilityDecision",
        "sceneCompatibilityReason",
        "captionSceneFitVersion",
    ):
        if key not in context:
            value = _first_present(caption_lineage.get(key), lineage.get(key))
            if value is not None:
                context[key] = value
    validate_caption_outcome_context(context)
    return context


def context_has_signal(context: dict[str, Any] | None) -> bool:
    if not isinstance(context, dict):
        return False
    return any(
        bool(context.get(key))
        for key in (
            "caption_hash",
            "caption_bank",
            "creator_mix",
            "frame_type",
            "length_class",
            "format_class",
            "caption_fit_version",
            "source_clip",
        )
    )


def context_json(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict) or not context_has_signal(context):
        return "{}"
    return json.dumps(context, ensure_ascii=False, sort_keys=True)


def column_values(context: dict[str, Any] | None) -> dict[str, Any]:
    context = context if isinstance(context, dict) else {}
    return {
        "caption_hash": context.get("caption_hash"),
        "caption_text": context.get("caption_text"),
        "caption_bank": context.get("caption_bank"),
        "caption_banks_json": json.dumps(
            context.get("caption_banks") or [], ensure_ascii=False, sort_keys=True
        ),
        "creator_mix": context.get("creator_mix"),
        "creator_model": context.get("creator_model"),
        "frame_type": context.get("frame_type"),
        "length_class": context.get("length_class"),
        "format_class": context.get("format_class"),
        "caption_fit_version": context.get("caption_fit_version"),
        "suitability_decision": context.get("suitability_decision"),
        "suitability_reason": context.get("suitability_reason"),
        "source_clip": context.get("source_clip"),
        "caption_outcome_context_json": context_json(context),
    }


def load_context_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _caption_lineage(lineage: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        lineage.get("captionBank"),
        lineage.get("caption_bank"),
        lineage.get("captionLineage"),
        lineage.get("caption_lineage"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    if lineage.get("schema") == "reel_factory.caption_lineage.v1":
        return lineage
    return {}


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _text_hash(value: str) -> str:
    normalized = " ".join((value or "").strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
