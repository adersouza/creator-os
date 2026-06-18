from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

_PACKAGE_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
_REPO_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
SCHEMA_DIR = _PACKAGE_SCHEMA_DIR if _PACKAGE_SCHEMA_DIR.exists() else _REPO_SCHEMA_DIR

AUDIO_INTENT_SCHEMA = "audio_intent.v1.schema.json"
CAMPAIGN_DRAFT_PAYLOAD_SCHEMA = "campaign_draft_payload.v1.schema.json"
AUDIO_CATALOG_EXPORT_SCHEMA = "audio_catalog_export.v1.schema.json"
PERFORMANCE_SYNC_SCHEMA = "performance_sync.v1.schema.json"
CAPTION_OUTCOME_CONTEXT_SCHEMA = "caption_outcome_context.v1.schema.json"
PATTERN_CARD_SCHEMA = "pattern_card.v1.schema.json"
VIDEO_ANALYSIS_SCHEMA = "video_analysis.v1.schema.json"
HIGGSFIELD_SOUL_IMAGE_PROMPT_SCHEMA = "higgsfield_soul_image_prompt.v1.schema.json"
KLING_3_VIDEO_PROMPT_SCHEMA = "kling_3_video_prompt.v1.schema.json"
GENERATED_ASSET_LINEAGE_SCHEMA = "generated_asset_lineage.v1.schema.json"
CREATIVE_PLAN_SCHEMA = "creative_plan.v1.schema.json"
RECOMMENDATION_NEXT_BATCH_SCHEMA = "recommendation_next_batch.v1.schema.json"
RECOMMENDATION_ACCURACY_REPORT_SCHEMA = "recommendation_accuracy_report.v1.schema.json"
REPURPOSING_PLAN_SCHEMA = "repurposing_plan.v1.schema.json"
VARIANT_ASSIGNMENT_SCHEMA = "variant_assignment.v1.schema.json"
MOTION_EDIT_RENDER_SCHEMA = "motion_edit_render.v1.schema.json"
FRONT_GENERATION_PLAN_SCHEMA = "front_generation_plan.v1.schema.json"

SCHEMA_NAMES = {
    "audio_intent": AUDIO_INTENT_SCHEMA,
    "campaign_draft_payload": CAMPAIGN_DRAFT_PAYLOAD_SCHEMA,
    "threadsdash_draft_payload": CAMPAIGN_DRAFT_PAYLOAD_SCHEMA,
    "audio_catalog_export": AUDIO_CATALOG_EXPORT_SCHEMA,
    "performance_sync": PERFORMANCE_SYNC_SCHEMA,
    "caption_outcome_context": CAPTION_OUTCOME_CONTEXT_SCHEMA,
    "campaign_factory_caption_outcome_context": CAPTION_OUTCOME_CONTEXT_SCHEMA,
    "pattern_card": PATTERN_CARD_SCHEMA,
    "video_analysis": VIDEO_ANALYSIS_SCHEMA,
    "higgsfield_soul_image_prompt": HIGGSFIELD_SOUL_IMAGE_PROMPT_SCHEMA,
    "kling_3_video_prompt": KLING_3_VIDEO_PROMPT_SCHEMA,
    "generated_asset_lineage": GENERATED_ASSET_LINEAGE_SCHEMA,
    "creative_plan": CREATIVE_PLAN_SCHEMA,
    "recommendation_next_batch": RECOMMENDATION_NEXT_BATCH_SCHEMA,
    "campaign_factory_recommendations_next_batch": RECOMMENDATION_NEXT_BATCH_SCHEMA,
    "recommendation_accuracy_report": RECOMMENDATION_ACCURACY_REPORT_SCHEMA,
    "campaign_factory_recommendation_accuracy_report": RECOMMENDATION_ACCURACY_REPORT_SCHEMA,
    "repurposing_plan": REPURPOSING_PLAN_SCHEMA,
    "campaign_factory_repurposing_plan": REPURPOSING_PLAN_SCHEMA,
    "variant_assignment": VARIANT_ASSIGNMENT_SCHEMA,
    "campaign_factory_variant_assignment": VARIANT_ASSIGNMENT_SCHEMA,
    "motion_edit_render": MOTION_EDIT_RENDER_SCHEMA,
    "reel_factory_motion_edit_render": MOTION_EDIT_RENDER_SCHEMA,
    "front_generation_plan": FRONT_GENERATION_PLAN_SCHEMA,
    "campaign_factory_front_generation_plan": FRONT_GENERATION_PLAN_SCHEMA,
}


class ContractValidationError(ValueError):
    pass


def schema_path(name: str) -> Path:
    return SCHEMA_DIR / _schema_filename(name)


def load_schema(name: str) -> dict[str, Any]:
    path = schema_path(name)
    if not path.exists():
        raise FileNotFoundError(f"contract schema not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_example(name: str) -> dict[str, Any]:
    filename = name if name.endswith(".json") else f"{name}.v1.example.json"
    path = SCHEMA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"contract example not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def example_names() -> list[str]:
    return sorted(path.name for path in SCHEMA_DIR.glob("*.example.json"))


def validate_contract(value: Any, schema_name: str) -> None:
    validator = _validator_for(schema_name)
    errors = sorted(validator.iter_errors(value), key=lambda error: [str(part) for part in error.path])
    if errors:
        raise ContractValidationError("; ".join(_format_error(error) for error in errors))


def validate_audio_intent(value: Any) -> None:
    validate_contract(value, AUDIO_INTENT_SCHEMA)


STRICT_CAMPAIGN_DRAFT_GRAPH_FIELDS = [
    "graph_id",
    "campaign_graph_id",
    "source_asset_graph_id",
    "rendered_asset_graph_id",
    "audit_graph_id",
]


def validate_campaign_draft_payload(value: Any, *, strict_graph_ids: bool = False) -> None:
    validate_contract(value, CAMPAIGN_DRAFT_PAYLOAD_SCHEMA)
    if strict_graph_ids:
        _validate_campaign_draft_graph_ids(value)


def validate_campaign_draft_payload_compat(value: Any) -> None:
    validate_campaign_draft_payload(value, strict_graph_ids=False)


def validate_campaign_draft_payload_strict(value: Any) -> None:
    validate_campaign_draft_payload(value, strict_graph_ids=True)


def validate_threadsdash_draft_payload(value: Any) -> None:
    validate_campaign_draft_payload(value)


def validate_threadsdash_draft_payload_strict(value: Any) -> None:
    validate_campaign_draft_payload(value, strict_graph_ids=True)


def validate_audio_catalog_export(value: Any) -> None:
    validate_contract(value, AUDIO_CATALOG_EXPORT_SCHEMA)


def validate_performance_sync(value: Any) -> None:
    validate_contract(value, PERFORMANCE_SYNC_SCHEMA)


def validate_caption_outcome_context(value: Any) -> None:
    validate_contract(value, CAPTION_OUTCOME_CONTEXT_SCHEMA)


def validate_pattern_card(value: Any) -> None:
    validate_contract(value, PATTERN_CARD_SCHEMA)


def validate_video_analysis(value: Any) -> None:
    validate_contract(value, VIDEO_ANALYSIS_SCHEMA)


def validate_higgsfield_soul_image_prompt(value: Any) -> None:
    validate_contract(value, HIGGSFIELD_SOUL_IMAGE_PROMPT_SCHEMA)


def validate_kling_3_video_prompt(value: Any) -> None:
    validate_contract(value, KLING_3_VIDEO_PROMPT_SCHEMA)


def validate_generated_asset_lineage(value: Any) -> None:
    validate_contract(value, GENERATED_ASSET_LINEAGE_SCHEMA)


def validate_creative_plan(value: Any) -> None:
    validate_contract(value, CREATIVE_PLAN_SCHEMA)


def validate_recommendation_next_batch(value: Any) -> None:
    validate_contract(value, RECOMMENDATION_NEXT_BATCH_SCHEMA)


def validate_recommendation_accuracy_report(value: Any) -> None:
    validate_contract(value, RECOMMENDATION_ACCURACY_REPORT_SCHEMA)


def validate_repurposing_plan(value: Any) -> None:
    validate_contract(value, REPURPOSING_PLAN_SCHEMA)


def validate_variant_assignment(value: Any) -> None:
    validate_contract(value, VARIANT_ASSIGNMENT_SCHEMA)


def validate_motion_edit_render(value: Any) -> None:
    validate_contract(value, MOTION_EDIT_RENDER_SCHEMA)


def validate_front_generation_plan(value: Any) -> None:
    validate_contract(value, FRONT_GENERATION_PLAN_SCHEMA)


def _validate_campaign_draft_graph_ids(value: Any) -> None:
    errors: list[str] = []
    if not isinstance(value, dict):
        return
    drafts = value.get("drafts")
    if not isinstance(drafts, list):
        return
    for index, draft in enumerate(drafts):
        if not isinstance(draft, dict):
            continue
        metadata = draft.get("metadata")
        campaign_factory = metadata.get("campaign_factory") if isinstance(metadata, dict) else None
        if not isinstance(campaign_factory, dict):
            errors.append(f"$.drafts[{index}].metadata.campaign_factory is required")
            continue
        if campaign_factory.get("legacy_compat") is True:
            continue
        for key in STRICT_CAMPAIGN_DRAFT_GRAPH_FIELDS:
            value = campaign_factory.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"$.drafts[{index}].metadata.campaign_factory.{key} is required in strict mode")
    if errors:
        raise ContractValidationError("; ".join(errors))


def validate_schema_examples() -> list[dict[str, Any]]:
    validators: dict[str, Callable[[Any], None]] = {
        "audio_intent.v1.example.json": validate_audio_intent,
        "campaign_draft_payload.v1.example.json": validate_campaign_draft_payload,
        "audio_catalog_export.v1.example.json": validate_audio_catalog_export,
        "performance_sync.v1.example.json": validate_performance_sync,
        "caption_outcome_context.v1.example.json": validate_caption_outcome_context,
        "pattern_card.v1.example.json": validate_pattern_card,
        "video_analysis.v1.example.json": validate_video_analysis,
        "higgsfield_soul_image_prompt.v1.example.json": validate_higgsfield_soul_image_prompt,
        "kling_3_video_prompt.v1.example.json": validate_kling_3_video_prompt,
        "generated_asset_lineage.v1.example.json": validate_generated_asset_lineage,
        "creative_plan.v1.example.json": validate_creative_plan,
        "recommendation_next_batch.v1.example.json": validate_recommendation_next_batch,
        "recommendation_accuracy_report.v1.example.json": validate_recommendation_accuracy_report,
        "repurposing_plan.v1.example.json": validate_repurposing_plan,
        "variant_assignment.v1.example.json": validate_variant_assignment,
        "motion_edit_render.v1.example.json": validate_motion_edit_render,
        "front_generation_plan.v1.example.json": validate_front_generation_plan,
    }
    checks = []
    for filename, validator in validators.items():
        path = SCHEMA_DIR / filename
        data = json.loads(path.read_text(encoding="utf-8"))
        validator(data)
        checks.append({"name": filename, "status": "ok", "path": str(path)})
    return checks


def _schema_filename(name: str) -> str:
    if name in SCHEMA_NAMES:
        return SCHEMA_NAMES[name]
    return name


@lru_cache(maxsize=None)
def _schema_registry() -> Registry:
    resources: list[tuple[str, Resource[Any]]] = []
    for path in SCHEMA_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        resources.append((path.name, resource))
        resources.append((path.resolve().as_uri(), resource))
        schema_id = schema.get("$id")
        if isinstance(schema_id, str):
            resources.append((schema_id, resource))
    return Registry().with_resources(resources)


@lru_cache(maxsize=None)
def _validator_for(schema_name: str) -> Draft202012Validator:
    schema = load_schema(schema_name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=_schema_registry())


def _format_error(error: Any) -> str:
    path = "$"
    for part in error.path:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return f"{path}: {error.message}"
