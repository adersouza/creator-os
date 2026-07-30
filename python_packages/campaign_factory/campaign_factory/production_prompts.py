"""Operator-approved deterministic prompts for the intent-first production lane."""

from __future__ import annotations

import hashlib
import json
import os
from types import MappingProxyType
from typing import Any, Final

from .prompt_registry import bind_campaign_prompt

PROMPT_CARD_SCHEMA: Final = "campaign_factory.creative_direction_prompt_card.v1"
COMPILED_PROMPT_SCHEMA: Final = "campaign_factory.compiled_passive_prompt.v1"
UNKNOWN: Final = "unknown"

INTENT_PROMPTS: Final[dict[str, str]] = {
    "passive_selfie": (
        "Natural eye and gaze movement, subtle head movement, one purposeful hair "
        "or clothing adjustment, restrained secondary movement, and natural "
        "handheld social camera behavior. The performance stays silent, restrained, "
        "and identity-stable."
    ),
    "flirty_portrait": (
        "A warm restrained gaze shift, a small confident head turn, one gentle hair "
        "adjustment, subtle breathing, and a natural handheld creator camera. The "
        "performance stays silent, restrained, and identity-stable."
    ),
    "outfit": (
        "A small posture shift to present the outfit, natural eye movement, one "
        "purposeful clothing adjustment, restrained fabric movement, and subtle "
        "handheld camera behavior. The performance stays silent and restrained."
    ),
    "lifestyle": (
        "Natural eye movement and a subtle head turn, one purposeful interaction "
        "with clothing or hair, restrained body movement, and casual handheld "
        "creator camera behavior. The performance stays silent and identity-stable."
    ),
    "animate_existing": (
        "Natural eye and gaze movement, subtle head movement, one purposeful hair "
        "or clothing adjustment, restrained secondary movement, and natural "
        "handheld camera behavior. The performance stays silent, restrained, and "
        "identity-stable."
    ),
    "recreate_reel": (
        "Recreate the supplied reference Reel's broad structure, performance, "
        "camera progression, pacing, framing, and social energy with the approved "
        "creator reference. Preserve identity and natural anatomy. Use original "
        "visual wording while provider audio remains disabled."
    ),
}

CREATOR_SOUL_IDS: Final = MappingProxyType(
    {
        creator: value
        for creator, variable in {
            "stacey": "CREATOR_OS_SOUL_ID_STACEY",
            "stacey1": "CREATOR_OS_SOUL_ID_STACEY1",
            "larissa": "CREATOR_OS_SOUL_ID_LARISSA",
            "lola": "CREATOR_OS_SOUL_ID_LOLA",
        }.items()
        if (value := str(os.environ.get(variable) or "").strip())
    }
)


def require_creator_soul_id(creator: str) -> tuple[str, str]:
    creator_slug = creator.strip().lower().replace(" ", "_")
    try:
        return creator_slug, CREATOR_SOUL_IDS[creator_slug]
    except KeyError as exc:
        raise ValueError(
            f"no pinned authenticated Higgsfield Soul identity for creator {creator}"
        ) from exc


def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _fact(facts: dict[str, Any], key: str) -> Any:
    value = facts.get(key)
    return value if value not in (None, "", [], {}) else UNKNOWN


def build_creative_direction_prompt_card(
    *,
    creator: str,
    intent: str,
    source: dict[str, Any],
    observed_facts: dict[str, Any],
    reference_pattern_id: str | None = None,
) -> dict[str, Any]:
    """Build one evidence-bound card without inferring unobserved visual facts."""

    metadata = source.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    pattern = (
        reference_pattern_id
        or metadata.get("approvedReferencePatternId")
        or metadata.get("referencePatternId")
        or UNKNOWN
    )
    core: dict[str, Any] = {
        "schema": PROMPT_CARD_SCHEMA,
        "creator": creator,
        "contentIntent": intent,
        "source": {
            "id": str(source["id"]),
            "sha256": str(source["content_hash"]),
        },
        "sceneType": _fact(observed_facts, "sceneType"),
        "approvedReferencePatternId": pattern,
        "emotionalBeat": metadata.get("emotionalBeat") or UNKNOWN,
        "performanceHook": metadata.get("performanceHook") or UNKNOWN,
        "blocking": {
            "foreground": _fact(observed_facts, "foreground"),
            "midground": _fact(observed_facts, "midground"),
            "background": _fact(observed_facts, "background"),
            "screenPosition": _fact(observed_facts, "screenPosition"),
            "bodyDirection": _fact(observed_facts, "bodyDirection"),
            "gazeDirection": _fact(observed_facts, "gazeDirection"),
        },
        "cameraGrammar": {
            "approximateDiagonalFieldOfView": _fact(
                observed_facts, "approximateDiagonalFieldOfView"
            ),
            "cameraHeight": _fact(observed_facts, "cameraHeight"),
            "cameraDistance": _fact(observed_facts, "cameraDistance"),
            "movementProfile": "restrained casual handheld movement",
        },
        "lightingMotivation": {
            "primarySource": _fact(observed_facts, "lightingPrimarySource"),
            "direction": _fact(observed_facts, "lightingDirection"),
            "exposurePriority": _fact(observed_facts, "exposurePriority"),
        },
        "motionArc": {
            "startingPose": _fact(observed_facts, "poseClass"),
            "movementDuringClip": INTENT_PROMPTS[intent],
            "endingPose": "same pose family",
        },
        "invariants": {
            "identity": "same creator identity",
            "outfit": "same outfit",
            "setting": "same setting",
            "composition": "same portrait composition and pose family",
        },
        "audioRhythmIntent": "silent provider output; Audio Radar handoff follows",
        "whyConceptShouldWork": (
            "operator-approved passive intent applied to an approved exact source"
        ),
        "continuityRequirements": [
            "same creator identity",
            "same outfit",
            "same setting",
            "same pose family",
            "restrained casual movement",
            "full face and head visibility",
            "clean one-person frame",
            "continuous shot",
            "silent provider output",
        ],
        "evidenceProvenance": {
            "sourceMetadata": metadata.get("analysisReceiptId") or UNKNOWN,
            "referencePattern": pattern,
            "compatibilitySchema": observed_facts.get("schema") or UNKNOWN,
        },
    }
    core["promptGovernance"] = bind_campaign_prompt(
        prompt_id="campaign.creative_direction",
        version="1",
        provider="any",
        model="local_deterministic",
        compiled_prompt={"intentPrompt": INTENT_PROMPTS[intent]},
        inputs={
            "creator": creator,
            "intent": intent,
            "sourceSha256": source["content_hash"],
            "observedFacts": observed_facts,
            "referencePatternId": pattern,
        },
    )
    return {**core, "promptCardFingerprint": _fingerprint(core)}


def validate_prompt_card(card: dict[str, Any]) -> dict[str, Any]:
    core = {key: value for key, value in card.items() if key != "promptCardFingerprint"}
    if core.get("schema") != PROMPT_CARD_SCHEMA or card.get(
        "promptCardFingerprint"
    ) != _fingerprint(core):
        raise ValueError("creative_direction_prompt_card_invalid")
    return card


def compile_passive_prompt_card(
    card: dict[str, Any], *, base_prompt: str
) -> dict[str, Any]:
    validate_prompt_card(card)
    intent = str(card.get("contentIntent") or "")
    if intent not in {
        "passive_selfie",
        "flirty_portrait",
        "outfit",
        "lifestyle",
        "animate_existing",
    }:
        raise ValueError("prompt card compilation supports passive intents only")
    text = " ".join(
        (
            base_prompt.strip(),
            "Preserve the same person, outfit, setting, pose family, camera angle, "
            "and lighting. Keep the full head and face visible in a clean one-person "
            "continuous shot with restrained movement.",
            "Provider output stays silent for downstream Audio Radar finishing.",
        )
    )
    governance = bind_campaign_prompt(
        prompt_id="campaign.passive_provider_compile",
        version="1",
        provider="any",
        model="local_deterministic",
        compiled_prompt=text,
        inputs={
            "promptCardFingerprint": card["promptCardFingerprint"],
            "basePrompt": base_prompt,
        },
    )
    core = {
        "schema": COMPILED_PROMPT_SCHEMA,
        "promptCardFingerprint": card["promptCardFingerprint"],
        "text": " ".join(text.split()),
        "promptGovernance": governance,
    }
    return {**core, "compiledPromptFingerprint": _fingerprint(core)}
