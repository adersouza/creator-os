"""Shared Reel Factory feature extraction for ranking and learning."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

FEATURE_KEYS = (
    "scene",
    "camera",
    "pose",
    "motion",
    "outfit",
    "creator",
    "body_style",
    "caption_style",
    "hook_type",
    "audio_track_id",
)


def _low(text: str | None) -> str:
    return str(text or "").lower()


def _contains(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _first_nested(value: Any, *keys: str) -> Any:
    for obj in _walk_dicts(value):
        for key in keys:
            found = obj.get(key)
            if found not in (None, "", "unknown"):
                return found
    return None


def _caption_style(caption_lineage: dict[str, Any] | None) -> str:
    if not isinstance(caption_lineage, dict):
        return "unknown"
    length_class = _first_nested(caption_lineage, "length_class", "lengthClass")
    format_class = _first_nested(caption_lineage, "format_class", "formatClass")
    if length_class and format_class:
        return f"{length_class}_{format_class}"
    raw = _first_nested(
        caption_lineage, "rawCaptionText", "captionText", "caption_text"
    )
    if raw:
        text = str(raw).strip()
        length = "short" if len(text) <= 80 else "long"
        fmt = "question" if "?" in text else "direct"
        if re.search(r"(^|\n)\s*\d+[\.)]", text):
            fmt = "numbered_list"
        return f"{length}_{fmt}"
    return "unknown"


def _hook_type(text: str, caption_lineage: dict[str, Any] | None) -> str:
    hook = _first_nested(caption_lineage, "hook_type", "hookType")
    if hook:
        return str(hook)
    raw = _first_nested(
        caption_lineage, "rawCaptionText", "captionText", "caption_text"
    )
    combined = " ".join(part for part in (text, _low(raw)) if part)
    if _contains(combined, "?", "wait", "which", "choose", "guess", "end"):
        return "curiosity"
    if _contains(combined, "pov"):
        return "pov"
    return "unknown"


def _audio_track_id(caption_lineage: dict[str, Any] | None) -> str:
    track_id = _first_nested(
        caption_lineage,
        "track_id",
        "trackId",
        "native_audio_id",
        "nativeAudioId",
        "audio_track_id",
        "audioTrackId",
    )
    return str(track_id) if track_id else "unknown"


def _creator(text: str) -> str:
    for name in ("stacey1", "stacey", "larissa", "lola"):
        if name in text:
            return name
    return "unknown"


def extract_features(
    captured_prompt: str | None,
    caption_lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract the shared winner-DNA feature vocabulary from asset context."""
    text = _low(captured_prompt)
    scene = "unknown"
    if _contains(text, "bathroom", "mirror selfie", "mirror"):
        scene = "bathroom_mirror"
    elif _contains(text, "gym"):
        scene = "gym_mirror" if "mirror" in text else "gym"
    elif _contains(text, "beach", "ocean"):
        scene = "beach"
    elif _contains(text, "living room", "fireplace"):
        scene = "living_room"
    elif _contains(text, "bedroom"):
        scene = "bedroom"

    camera = "mirror_selfie" if _contains(text, "mirror", "selfie") else "unknown"
    pose = (
        "seated_side"
        if _contains(text, "seated", "sitting")
        else ("standing" if "standing" in text else "unknown")
    )
    motion = (
        "hip_sway"
        if _contains(text, "hip", "sway")
        else ("slow_pan" if _contains(text, "slow pan", "pan") else "unknown")
    )
    outfit = (
        "crop_top"
        if "crop top" in text
        else (
            "dress"
            if "dress" in text
            else (
                "bikini"
                if "bikini" in text
                else (
                    "black_set"
                    if _contains(text, "black set", "black top")
                    else "unknown"
                )
            )
        )
    )
    body_style = (
        "thick_hourglass"
        if _contains(text, "hourglass", "thick", "curvy", "curves")
        else "unknown"
    )
    return {
        "scene": scene,
        "camera": camera,
        "pose": pose,
        "motion": motion,
        "outfit": outfit,
        "creator": _creator(text),
        "body_style": body_style,
        "caption_style": _caption_style(caption_lineage),
        "hook_type": _hook_type(text, caption_lineage),
        "audio_track_id": _audio_track_id(caption_lineage),
    }


def features_from_lineage(lineage: dict[str, Any] | None) -> dict[str, Any]:
    """Return aligned features from a generation lineage sidecar."""
    if not isinstance(lineage, dict):
        return {key: "unknown" for key in FEATURE_KEYS}
    explicit = (
        lineage.get("features") if isinstance(lineage.get("features"), dict) else {}
    )
    generation = (
        lineage.get("generation") if isinstance(lineage.get("generation"), dict) else {}
    )
    source = lineage.get("source") if isinstance(lineage.get("source"), dict) else {}
    prompt_parts = [
        generation.get("capturedHiggsfieldPrompt"),
        json.dumps(generation.get("prompts"), ensure_ascii=False)
        if isinstance(generation.get("prompts"), dict)
        else None,
        source.get("soulName"),
        generation.get("soulName"),
        generation.get("campaign"),
        generation.get("creator"),
    ]
    extracted = extract_features("\n".join(str(part) for part in prompt_parts if part))
    extracted.update(
        {
            key: value
            for key, value in explicit.items()
            if key in FEATURE_KEYS and value not in (None, "", "unknown")
        }
    )
    for key, value in (
        ("creator", source.get("soulName") or generation.get("soulName")),
        ("scene", source.get("scene") or generation.get("scene")),
        ("pose", source.get("pose") or generation.get("pose")),
        ("motion", source.get("motion") or generation.get("motion")),
        ("outfit", source.get("outfit") or generation.get("outfit")),
        ("caption_style", generation.get("captionStyle")),
    ):
        if extracted.get(key) in (None, "", "unknown") and value not in (
            None,
            "",
            "unknown",
        ):
            extracted[key] = str(value).lower() if key == "creator" else value
    return {key: extracted.get(key) or "unknown" for key in FEATURE_KEYS}
