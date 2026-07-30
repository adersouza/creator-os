"""Approved Campaign Factory prompt definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from creator_os_core.prompt_governance import (
    bind_prompt_receipt,
    fingerprint,
    prompt_definition,
    prompt_registry,
    python_source_fingerprint,
    regression_fixture_hash,
)

_EFFECTIVE = "2026-07-26T00:00:00+00:00"
_PACKAGE_ROOT = Path(__file__).resolve().parent
_REEL_FACTORY_ROOT = (
    Path(__file__).resolve().parents[2] / "reel_factory" / "reel_factory"
)

_PASSIVE_SELFIE_TEXT = (
    "Natural eye and gaze movement, subtle head movement, one purposeful hair "
    "or clothing adjustment, restrained secondary movement, and natural "
    "handheld social camera behavior. The performance stays silent, restrained, "
    "and identity-stable."
)
_PASSIVE_COMPILED_FIXTURE = (
    "Calm five-second creator motion. Preserve the same person, outfit, setting, "
    "pose family, camera angle, and lighting. Keep the full head and face visible "
    "in a clean one-person continuous shot with restrained movement. Provider "
    "output stays silent for downstream Audio Radar finishing."
)
_OPENAI_RECREATION_FIXTURE = (
    "The image is the approved creator identity for a calm short animation. "
    "Invent one attractive, realistic 9:16 scene and pose that will animate well "
    "with calm eye, head, breathing, hair, and small hand movements. Return an "
    "anchorPrompt for Higgsfield Soul 2, a detailed Seedance 2 Fast prompt, a "
    "Kling 3 Turbo prompt with a 2500-character maximum, and a chronological "
    "timeline. Intent: passive_selfie. The anchor prompt describes adult-coded "
    "pose, wardrobe, setting, lighting, framing, and composition using affirmative "
    "desired-result language. The approved creator image exclusively supplies "
    "identity, face, skin tone, hair, tattoos, beauty marks, and permanent body "
    "details, so the anchor prompt stays focused on the scene and composition. "
    "Video prompts explicitly use the approved anchor as the exact person, "
    "preserve every visible identity and permanent feature, and describe only "
    "desired visuals, movement, timing, and camera behavior in affirmative "
    "language. Provider settings control audio separately. Source writing stays "
    "outside the generated prompts."
)
_DERIVED_STILL_FIXTURE = (
    "Change only the existing garment color, using these colors in order: black, "
    "white. Preserve identity, body proportions, skin tone, pose, camera, lighting, "
    "background, hands, and framing exactly. Do not add text or UI. Return exactly "
    "2 separate 2:3 portrait images."
)

_PRODUCTION_COMPILER_SOURCE = python_source_fingerprint(
    _PACKAGE_ROOT / "production_prompts.py",
    source_id="campaign_factory.production_prompts",
    symbols=(
        "_fingerprint",
        "_fact",
        "build_creative_direction_prompt_card",
        "validate_prompt_card",
        "compile_passive_prompt_card",
    ),
)
_PRODUCTION_TEMPLATE_SOURCE = python_source_fingerprint(
    _PACKAGE_ROOT / "production_prompts.py",
    source_id="campaign_factory.production_prompts.templates",
    symbols=("PROMPT_CARD_SCHEMA", "COMPILED_PROMPT_SCHEMA", "INTENT_PROMPTS"),
)
_RECREATION_COMPILER_SOURCE = python_source_fingerprint(
    _PACKAGE_ROOT / "recreation_prompting.py",
    source_id="campaign_factory.recreation_prompting",
    symbols=("_instruction", "_response_schema"),
)
_RECREATION_TEMPLATE_SOURCE = python_source_fingerprint(
    _PACKAGE_ROOT / "recreation_prompting.py",
    source_id="campaign_factory.recreation_prompting.templates",
    symbols=("PROMPT_BUILDER_VERSION", "_instruction", "_response_schema"),
)
_DERIVED_COMPILER_SOURCE = python_source_fingerprint(
    _REEL_FACTORY_ROOT / "derived_stills.py",
    source_id="reel_factory.derived_stills",
    symbols=("build_edit_prompt",),
)
_DERIVED_TEMPLATE_SOURCE = python_source_fingerprint(
    _REEL_FACTORY_ROOT / "derived_stills.py",
    source_id="reel_factory.derived_stills.templates",
    symbols=("PROMPT_BUILDER_VERSION", "PILOT_COLORWAYS", "build_edit_prompt"),
)


def _definition(
    *,
    prompt_id: str,
    version: str,
    purpose: str,
    provider: str,
    models: tuple[str, ...],
    template_version: str,
    builder_source: Any,
    compiler_source_fingerprint: str,
    template_source_fingerprint: str,
    input_contract: str,
    output_contract: str,
    cost_behavior: str,
    regression_fixtures: tuple[str, ...],
    approved_material_fingerprint: str,
) -> dict[str, Any]:
    return prompt_definition(
        prompt_id=prompt_id,
        version=version,
        owner="campaign_factory",
        purpose=purpose,
        provider=provider,
        models=models,
        template_version=template_version,
        builder_fingerprint=fingerprint(builder_source),
        compiler_source_fingerprint=compiler_source_fingerprint,
        template_source_fingerprint=template_source_fingerprint,
        input_contract=input_contract,
        output_contract=output_contract,
        approval={
            "state": "approved",
            "approvedBy": "creator_os_operator_baseline",
            "approvedAt": "2026-07-26T00:00:00+00:00",
            "evidence": "operator_accepted_passive_kling_seedance_product_decision",
            "materialFingerprint": approved_material_fingerprint,
        },
        effective_at=_EFFECTIVE,
        cost_behavior=cost_behavior,
        regression_fixtures=regression_fixtures,
    )


PROMPT_REGISTRY = prompt_registry(
    (
        _definition(
            prompt_id="campaign.creative_direction",
            version="1",
            purpose="evidence-bound passive creative direction",
            provider="any",
            models=("*",),
            template_version="creative_direction_prompt_card.v1",
            builder_source={
                "invariants": [
                    "identity",
                    "outfit",
                    "setting",
                    "pose_family",
                    "silent_output",
                ],
                "motion": "intent_specific_restrained_motion",
            },
            compiler_source_fingerprint=_PRODUCTION_COMPILER_SOURCE,
            template_source_fingerprint=_PRODUCTION_TEMPLATE_SOURCE,
            input_contract="campaign_factory.creative_direction_inputs.v1",
            output_contract="campaign_factory.creative_direction_prompt_card.v1",
            cost_behavior="local_compile",
            regression_fixtures=(
                regression_fixture_hash(
                    fixture_id="campaign.creative_direction.passive_selfie.v1",
                    inputs={
                        "creator": "fixture_creator",
                        "intent": "passive_selfie",
                        "sourceSha256": "a" * 64,
                        "observedFacts": {"sceneType": "mirror_selfie"},
                    },
                    compiled_prompt={"intentPrompt": _PASSIVE_SELFIE_TEXT},
                ),
            ),
            approved_material_fingerprint="f8d0e0913a5b49bab409cb5f601c05baa3e2e31c48cd79672c0028386eccff98",
        ),
        _definition(
            prompt_id="campaign.passive_provider_compile",
            version="1",
            purpose="compile approved passive direction for provider motion",
            provider="any",
            models=("*",),
            template_version="compiled_passive_prompt.v1",
            builder_source={
                "preserve": "person_outfit_setting_pose_camera_lighting",
                "audio": "silent_for_audio_radar",
            },
            compiler_source_fingerprint=_PRODUCTION_COMPILER_SOURCE,
            template_source_fingerprint=_PRODUCTION_TEMPLATE_SOURCE,
            input_contract="campaign_factory.creative_direction_prompt_card.v1",
            output_contract="campaign_factory.compiled_passive_prompt.v1",
            cost_behavior="local_compile",
            regression_fixtures=(
                regression_fixture_hash(
                    fixture_id="campaign.passive_provider_compile.v1",
                    inputs={
                        "promptCardFingerprint": "b" * 64,
                        "basePrompt": "Calm five-second creator motion.",
                    },
                    compiled_prompt=_PASSIVE_COMPILED_FIXTURE,
                ),
            ),
            approved_material_fingerprint="ddd1706ae0e92d67c44acbe0e70e8ec36b048b9e457f48fb6dc5611ca140aabd",
        ),
        _definition(
            prompt_id="campaign.openai_recreation_pack",
            version="3",
            purpose="OpenAI-authored Soul anchor and provider motion prompts",
            provider="openai",
            models=("gpt-5",),
            template_version="creator_os_openai_prompt_builder.v3",
            builder_source={
                "identity": "approved_creator_image",
                "reference": "authorized_reel_frames_optional",
                "output": ["anchor", "seedance", "kling", "timeline"],
                "positive_language_only": True,
            },
            compiler_source_fingerprint=_RECREATION_COMPILER_SOURCE,
            template_source_fingerprint=_RECREATION_TEMPLATE_SOURCE,
            input_contract="campaign_factory.openai_prompt_request.v1",
            output_contract="campaign_factory.recreation_prompt_pack.v1",
            cost_behavior="paid_provider_call",
            regression_fixtures=(
                regression_fixture_hash(
                    fixture_id="campaign.openai_recreation_pack.no_reference.v3",
                    inputs={
                        "intent": "passive_selfie",
                        "hasReferenceVideo": False,
                    },
                    compiled_prompt=_OPENAI_RECREATION_FIXTURE,
                ),
            ),
            approved_material_fingerprint="719220245186951fad4a038dd9e6ec991e1800b5dc276c453d2cdefdb83ff8d0",
        ),
        _definition(
            prompt_id="campaign.recreation_provider_compile",
            version="1",
            purpose="bind recreation prompt pack to one provider model",
            provider="any",
            models=("*",),
            template_version="openai_video_prompt.v1",
            builder_source={
                "select": "provider_specific_prompt",
                "bind": "prompt_pack_and_prompt_card",
            },
            compiler_source_fingerprint=_RECREATION_COMPILER_SOURCE,
            template_source_fingerprint=_RECREATION_TEMPLATE_SOURCE,
            input_contract="campaign_factory.recreation_prompt_pack.v1",
            output_contract="campaign_factory.openai_video_prompt.v1",
            cost_behavior="local_compile",
            regression_fixtures=(
                regression_fixture_hash(
                    fixture_id="campaign.recreation_provider_compile.kling.v1",
                    inputs={
                        "promptPackFingerprint": "c" * 64,
                        "providerModel": "kling3_0",
                    },
                    compiled_prompt="Calm provider-specific recreation motion.",
                ),
            ),
            approved_material_fingerprint="0080fd514ac6ded39a61af35da4a18d9a7dd0a3e0f761939af996200098871f3",
        ),
        _definition(
            prompt_id="campaign.derived_still_edit",
            version="1",
            purpose="provider still colorway and outfit edit",
            provider="any",
            models=("gemini-3-pro-image", "gpt-image-2"),
            template_version="derived_still_edit_prompt.v1",
            builder_source={
                "operations": ["colorway", "outfit_swap"],
                "formats": ["individual", "grid_2x3"],
                "identity_and_locality": "preserve",
            },
            compiler_source_fingerprint=_DERIVED_COMPILER_SOURCE,
            template_source_fingerprint=_DERIVED_TEMPLATE_SOURCE,
            input_contract="campaign_factory.derived_still_edit_inputs.v1",
            output_contract="reel_factory.derived_still_edit_prompt.v1",
            cost_behavior="paid_provider_call",
            regression_fixtures=(
                regression_fixture_hash(
                    fixture_id="campaign.derived_still_edit.colorway.v1",
                    inputs={
                        "operation": "colorway",
                        "format": "individual",
                        "count": 2,
                        "colors": ["black", "white"],
                    },
                    compiled_prompt=_DERIVED_STILL_FIXTURE,
                ),
            ),
            approved_material_fingerprint="cb96c92815c4fb09f588e65babb77b8fa4efcb6acea7309baf593011ae24f7df",
        ),
    )
)


def bind_campaign_prompt(
    *,
    prompt_id: str,
    version: str,
    provider: str,
    model: str,
    compiled_prompt: Any,
    inputs: Any,
) -> dict[str, Any]:
    return bind_prompt_receipt(
        PROMPT_REGISTRY,
        prompt_id=prompt_id,
        version=version,
        provider=provider,
        model=model,
        compiled_prompt=compiled_prompt,
        input_fingerprint=fingerprint(inputs),
    )
