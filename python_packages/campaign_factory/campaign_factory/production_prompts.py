"""Operator-approved deterministic prompts for the intent-first production lane."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

from reel_factory.worker_api import (
    PASSIVE_SAFETY_CONSTRAINTS,
    passive_safety_prompt,
)

PROMPT_CARD_SCHEMA: Final = "campaign_factory.creative_direction_prompt_card.v1"
COMPILED_PROMPT_SCHEMA: Final = "campaign_factory.compiled_passive_prompt.v1"
UNKNOWN: Final = "unknown"

INTENT_PROMPTS: Final[dict[str, str]] = {
    "passive_selfie": (
        "Natural eye and gaze movement, subtle head movement, one purposeful hair "
        "or clothing adjustment, restrained secondary movement, and natural "
        "handheld social camera behavior. No speaking, exaggerated movement, or "
        "identity-changing action."
    ),
    "flirty_portrait": (
        "A warm restrained gaze shift, a small confident head turn, one gentle hair "
        "adjustment, subtle breathing, and a natural handheld creator camera. No "
        "speaking, exaggerated movement, or identity-changing action."
    ),
    "outfit": (
        "A small posture shift to present the outfit, natural eye movement, one "
        "purposeful clothing adjustment, restrained fabric movement, and subtle "
        "handheld camera behavior. No speaking or exaggerated movement."
    ),
    "lifestyle": (
        "Natural eye movement and a subtle head turn, one purposeful interaction "
        "with clothing or hair, restrained body movement, and casual handheld "
        "creator camera behavior. No speaking or identity-changing action."
    ),
    "animate_existing": (
        "Natural eye and gaze movement, subtle head movement, one purposeful hair "
        "or clothing adjustment, restrained secondary movement, and natural "
        "handheld camera behavior. No speaking, exaggerated movement, or "
        "identity-changing action."
    ),
    "recreate_reel": (
        "Recreate the supplied reference Reel's broad structure, performance, "
        "camera progression, pacing, framing, and social energy with the approved "
        "creator reference. Preserve identity and natural anatomy. Do not reproduce "
        "source text overlays or generate audio."
    ),
    "motion_copy": (
        "Transfer the driving video's body motion and timing faithfully while "
        "preserving the creator's face, body proportions, clothing, and portrait "
        "identity. Keep the source portrait framing and avoid camera cuts."
    ),
    "dance": (
        "Transfer the driving dance motion and timing faithfully while preserving "
        "the creator's face, body proportions, clothing, and portrait identity. "
        "Keep the source portrait framing and avoid camera cuts."
    ),
    "talking_selfie": (
        "A natural direct-to-camera creator delivery with accurate lip movement, "
        "subtle facial expression, restrained head motion, steady portrait framing, "
        "and consistent identity throughout."
    ),
    "talking_motion_copy": (
        "Transfer the driving video's body motion and timing while preserving the "
        "creator's identity and portrait framing, then synchronize the supplied "
        "creator voice without changing the face or body."
    ),
}

CREATOR_SOUL_IDS: Final[dict[str, str]] = {
    "stacey": "d63ea9c7-b2c7-439c-bf0c-edfdf9938a36",
    "stacey1": "5828d958-91dd-4d6d-8909-934503f47644",
    "larissa": "44326567-b12c-410c-95b7-31891bb0629b",
    "lola": "4c86c548-7aa5-4ad1-bc03-b94aa4ce8385",
}


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
        "negativeConstraints": list(PASSIVE_SAFETY_CONSTRAINTS),
        "evidenceProvenance": {
            "sourceMetadata": metadata.get("analysisReceiptId") or UNKNOWN,
            "referencePattern": pattern,
            "compatibilitySchema": observed_facts.get("schema") or UNKNOWN,
        },
    }
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
            passive_safety_prompt(),
            "Provider-generated music and ambient audio must remain disabled.",
        )
    )
    core = {
        "schema": COMPILED_PROMPT_SCHEMA,
        "promptCardFingerprint": card["promptCardFingerprint"],
        "text": " ".join(text.split()),
    }
    return {**core, "compiledPromptFingerprint": _fingerprint(core)}
