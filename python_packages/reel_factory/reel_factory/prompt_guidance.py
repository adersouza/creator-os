"""Stateless prompt guidance selected explicitly by Campaign Factory/operators."""

from __future__ import annotations

RETRY_HELPER_DIRECTIONS = {
    "fix_pose": (
        "Retry focus: pose fidelity. Preserve the exact body orientation, crop, camera angle, "
        "limb placement, support-hand placement, and seated/standing relationship from the reference."
    ),
    "fix_hands": (
        "Retry focus: hand placement. Keep visible hands simple, anatomically plausible, relaxed, "
        "and close to the reference placement with clean support-hand shapes."
    ),
    "less_smile": (
        "Retry focus: sultry expression. Use sultry eye contact, teasing expression, confident gaze, "
        "and subtle parted lips as the expression direction."
    ),
    "more_reference_fidelity": (
        "Retry focus: increase reference fidelity. Match the reference room, lighting, framing, lens feel, outfit silhouette, "
        "pose, body angle, and camera distance more tightly while keeping the amplified body style: much larger pushed-up breasts, "
        "deep cleavage, thicker curvier frame, tiny waist, wide hips, thick thighs, round ass, and tight fabric tension. Vary only outfit color/material "
        "or cleavage-supporting cut details when making image variations."
    ),
    "more_body_emphasis": (
        "Retry focus: make the image much sexier while preserving the exact reference pose, framing, room, and camera angle. "
        "Use stronger body amplification with a curvier frame: much larger pushed-up full breasts, "
        "deep plunging cleavage as the focal point, smaller/tighter tops, visible fabric tension, thicker curvier frame, "
        "tiny waist, wider hips, thicker thighs, rounder ass, dramatic S-curve, and skin-tight fabric cling."
    ),
    "more_cleavage": (
        "Retry focus: make cleavage the strongest visual focal point while preserving the reference pose, framing, room, and camera angle. "
        "Use lower necklines, smaller/tighter tops, much larger pushed-up full breasts, deep plunging cleavage, visible fabric tension, "
        "and realistic stretch/cling with amplified curves."
    ),
}


def retry_helper_direction(helper: str | None) -> str:
    if not helper:
        return ""
    if helper not in RETRY_HELPER_DIRECTIONS:
        raise ValueError(
            f"retry_helper must be one of {sorted(RETRY_HELPER_DIRECTIONS)}"
        )
    return RETRY_HELPER_DIRECTIONS[helper]
