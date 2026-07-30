"""Approved Reel Factory prompt definitions."""

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

_MOTION_BUILDER = {
    "duration": 5,
    "identity": "preserve",
    "shot": "continuous",
    "motion": "restrained",
    "audio": "silent",
}
_SOURCE = Path(__file__).resolve().with_name("reel_motion_prompt.py")
_COMPILER_SOURCE = python_source_fingerprint(
    _SOURCE,
    source_id="reel_factory.reel_motion_prompt",
    symbols=("compile_reel_motion_prompt",),
)
_TEMPLATE_SOURCE = python_source_fingerprint(
    _SOURCE,
    source_id="reel_factory.reel_motion_prompt.templates",
    symbols=(
        "_MOTION_BY_SCENE",
        "_COMMON_SAFETY",
        "PASSIVE_SAFETY_CONSTRAINTS",
    ),
)
_ROOM_SELFIE_FIXTURE = (
    "Use the supplied 9:16 start image as the source frame. Preserve the same "
    "person, outfit, setting, pose family, camera angle, and lighting. Keep the "
    "full head and face visible. Create a short realistic 5-second creator video "
    "as one clean continuous shot with one person, stable wardrobe and location, "
    "restrained camera motion, and subtle movement within the original pose family. "
    "Keep the casual room selfie pose, room layout, outfit, and full head framing "
    "stable. Add a natural handheld feel, tiny posture shift, soft breathing, "
    "slight hip movement, and realistic body and fabric motion."
)
PROMPT_REGISTRY = prompt_registry(
    (
        prompt_definition(
            prompt_id="reel.passive_motion",
            version="1",
            owner="reel_factory",
            purpose="compile deterministic accepted-still motion prompt",
            provider="higgsfield",
            models=("kling3_0", "kling3_0_turbo"),
            template_version="reel_motion_prompt.v1",
            builder_fingerprint=fingerprint(_MOTION_BUILDER),
            compiler_source_fingerprint=_COMPILER_SOURCE,
            template_source_fingerprint=_TEMPLATE_SOURCE,
            input_contract="reel_factory.reel_motion_prompt_inputs.v1",
            output_contract="reel_factory.reel_motion_prompt.v1",
            approval={
                "state": "approved",
                "approvedBy": "creator_os_operator_baseline",
                "approvedAt": "2026-07-26T00:00:00+00:00",
                "evidence": "operator_accepted_kling_passive_motion",
                "materialFingerprint": "3988420ccac33b43bb26f40bed147cb12a930bcd1b5caa9149476bdde34f35a3",
            },
            effective_at="2026-07-26T00:00:00+00:00",
            cost_behavior="local_compile_then_paid_provider_call",
            regression_fixtures=(
                regression_fixture_hash(
                    fixture_id="reel.passive_motion.room_selfie.v1",
                    inputs={
                        "sceneType": "room_selfie",
                        "capturedHiggsfieldPrompt": None,
                        "aspectRatio": "9:16",
                        "durationSeconds": 5,
                    },
                    compiled_prompt=_ROOM_SELFIE_FIXTURE,
                ),
            ),
        ),
    )
)


def bind_reel_prompt(
    *,
    compiled_prompt: Any,
    inputs: Any,
    model: str = "kling3_0",
) -> dict[str, Any]:
    return bind_prompt_receipt(
        PROMPT_REGISTRY,
        prompt_id="reel.passive_motion",
        version="1",
        provider="higgsfield",
        model=model,
        compiled_prompt=compiled_prompt,
        input_fingerprint=fingerprint(inputs),
    )
