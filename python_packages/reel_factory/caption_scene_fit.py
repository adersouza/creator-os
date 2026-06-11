"""Scene compatibility helpers for caption-bank selection."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


CAPTION_SCENE_FIT_VERSION = "v1"


CAPTION_SCENE_TAGS = {
    "indoor_room",
    "bedroom",
    "mirror_selfie",
    "bathroom",
    "kitchen",
    "gym",
    "beach",
    "pool",
    "car",
    "outdoor",
    "travel",
    "general",
}

REEL_SCENE_TAGS = {
    "indoor_selfie",
    "bedroom_mirror",
    "bathroom_mirror",
    "gym_body",
    "beach_pool",
    "outdoor_lifestyle",
    "unknown",
}

SCENE_SPECIFIC_CAPTION_TAGS = CAPTION_SCENE_TAGS - {"general"}


@dataclass(frozen=True)
class SceneCompatibility:
    caption_scene_tags: list[str]
    reel_scene_tags: list[str]
    decision: str
    reason: str


def caption_text_for_scene(hook: str | dict) -> str:
    if isinstance(hook, dict):
        segments = hook.get("segments")
        if isinstance(segments, list):
            return "\n".join(
                str(seg.get("text", "")).strip()
                for seg in segments
                if isinstance(seg, dict) and str(seg.get("text", "")).strip()
            ).strip()
        return json.dumps(hook, sort_keys=True, ensure_ascii=False)
    return str(hook)


def classify_caption_scene_tags(text: str, lineage: dict[str, Any] | None = None) -> list[str]:
    lineage = lineage if isinstance(lineage, dict) else {}
    value = f" {str(text or '').lower()} "
    banks = {str(bank) for bank in (lineage.get("selectedBanks") or lineage.get("sourceBanks") or [])}
    tags: set[str] = set()

    def has(pattern: str) -> bool:
        return bool(re.search(pattern, value))

    if "bedroom_mirror" in banks or has(r"\b(bedroom|bed|room|sleep|wake up|my room|in my bed)\b"):
        tags.update({"indoor_room", "bedroom"})
    if "gym_body" in banks or has(r"\b(gym|workout|fitness|squat|leggings|leg press|protein|coach)\b"):
        tags.add("gym")
    if has(r"\b(mirror|selfie)\b"):
        tags.add("mirror_selfie")
    if has(r"\b(bathroom|shower)\b"):
        tags.update({"indoor_room", "bathroom"})
    if has(r"\b(kitchen|cook|cooking|dinner)\b"):
        tags.update({"indoor_room", "kitchen"})
    if has(r"\b(beach|ocean|sea|shore|bikini|summer)\b"):
        tags.update({"beach", "outdoor"})
    if has(r"\b(pool|swim|hot tub)\b"):
        tags.update({"pool", "outdoor"})
    if has(r"\b(car|drive|driving|passenger seat|backseat|road trip)\b"):
        tags.update({"car", "travel"})
    if has(r"\b(outside|outdoor|park|street|city|cliff|trail|hike|walking)\b"):
        tags.add("outdoor")
    if has(r"\b(travel|vacation|trip|hotel|airport|flight)\b"):
        tags.add("travel")

    if not tags:
        tags.add("general")
    return _ordered_tags(tags, CAPTION_SCENE_TAGS)


def classify_reel_scene_tags(
    *,
    frame_type: str,
    video_stem: str = "",
    prompt_text: str = "",
) -> list[str]:
    value = f" {frame_type} {video_stem} {prompt_text} ".lower()
    tags: set[str] = set()

    if any(token in value for token in ("gym", "fitness", "workout", "leggings", "squat")) or frame_type == "gym_body":
        tags.add("gym_body")
    if any(token in value for token in ("beach", "pool", "ocean", "sea", "shore", "bikini", "swim")):
        tags.add("beach_pool")
    if any(token in value for token in ("bathroom", "shower")):
        tags.add("bathroom_mirror")
    if any(token in value for token in ("bedroom", "bedroom mirror", "bed ", " room ", "mirror_fullbody")) or frame_type == "mirror_fullbody":
        tags.add("bedroom_mirror")
    if any(token in value for token in ("indoor", "selfie", "closeup", "halfbody", "room")) or frame_type in {"closeup", "halfbody"}:
        tags.add("indoor_selfie")
    if any(token in value for token in ("outdoor", "outside", "street", "park", "city", "cliff", "travel", "vacation")):
        tags.add("outdoor_lifestyle")

    if not tags:
        tags.add("unknown")
    return _ordered_tags(tags, REEL_SCENE_TAGS)


def evaluate_scene_compatibility(
    *,
    caption_text: str,
    caption_lineage: dict[str, Any] | None,
    reel_scene_tags: list[str] | None,
    scene_fit_mode: str,
) -> SceneCompatibility:
    if scene_fit_mode not in {"auto", "off"}:
        raise ValueError(f"unknown caption scene fit mode: {scene_fit_mode}")

    caption_tags = classify_caption_scene_tags(caption_text, caption_lineage)
    reel_tags = _ordered_tags(set(reel_scene_tags or ["unknown"]), REEL_SCENE_TAGS)
    if scene_fit_mode == "off":
        return SceneCompatibility(caption_tags, reel_tags, "fit_disabled", "caption scene fit disabled")

    blocked_tags = _blocked_caption_tags_for_reel(reel_tags)
    explicit_caption_tags = set(caption_tags) - {"general"}
    blocked_overlap = sorted(explicit_caption_tags & blocked_tags)
    if blocked_overlap:
        return SceneCompatibility(
            caption_tags,
            reel_tags,
            "blocked",
            f"{','.join(blocked_overlap)} caption blocked for {','.join(reel_tags)} reel",
        )

    if "unknown" in reel_tags and explicit_caption_tags:
        return SceneCompatibility(
            caption_tags,
            reel_tags,
            "unknown_allowed",
            "unknown reel scene; no obvious scene mismatch",
        )

    return SceneCompatibility(
        caption_tags,
        reel_tags,
        "allowed",
        f"caption scene compatible with {','.join(reel_tags)} reel",
    )


def _blocked_caption_tags_for_reel(reel_tags: list[str]) -> set[str]:
    tags = set(reel_tags)
    if "beach_pool" in tags:
        return {"bedroom", "gym", "car"}
    if "gym_body" in tags:
        return {"bedroom", "beach", "pool", "car", "travel"}
    if "outdoor_lifestyle" in tags:
        return {"bedroom", "gym"}
    if tags & {"indoor_selfie", "bedroom_mirror", "bathroom_mirror"}:
        return {"beach", "pool", "gym", "car", "outdoor", "travel"}
    if "unknown" in tags:
        return {"beach", "pool", "gym", "car", "outdoor", "travel", "bedroom", "bathroom", "kitchen"}
    return set()


def _ordered_tags(tags: set[str], allowed: set[str]) -> list[str]:
    return sorted(tag for tag in tags if tag in allowed)
