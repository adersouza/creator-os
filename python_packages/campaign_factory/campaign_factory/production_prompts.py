"""Operator-approved deterministic prompts for the intent-first production lane."""

from typing import Final

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
