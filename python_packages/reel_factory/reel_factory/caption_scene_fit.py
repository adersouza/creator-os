"""Scene compatibility helpers for caption-bank selection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

CAPTION_SCENE_FIT_VERSION = "v2"
CAPTION_TOPIC_FIT_VERSION = "v1"


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
    "swim_action",
    "calm_motion",
    "action_motion",
    "body_forward",
    "event_timing_resolved",
    "general",
}

REEL_SCENE_TAGS = {
    "indoor_selfie",
    "bedroom_mirror",
    "bathroom_mirror",
    "mirror_selfie",
    "kitchen",
    "car",
    "gym_body",
    "beach_pool",
    "outdoor_lifestyle",
    "swim_action",
    "calm_motion",
    "action_motion",
    "body_forward",
    "event_timing_resolved",
    "unknown",
}

SCENE_SPECIFIC_CAPTION_TAGS = CAPTION_SCENE_TAGS - {"general"}

CAPTION_TOPIC_BANKS = {
    "pick_one": {"choice_poll", "comment_bait"},
    "reverse_puzzle": {"read_backwards_puzzle", "coded_fill_ins"},
    "coded_fill": {"coded_fill_ins", "read_backwards_puzzle"},
    "good_boy": {"boyfriend_bait", "comment_bait"},
    "single_type": {"boyfriend_bait", "comment_bait", "shared_girl_next_door"},
    "dm_follow": {"dm_follow_bait", "comment_bait"},
    "gaming": {"choice_poll", "comment_bait", "boyfriend_bait"},
    "fandom": {"comment_bait", "choice_poll", "boyfriend_bait"},
    "political_ragebait": {"comment_bait"},
}

CAPTION_TOPIC_ORDER = tuple(CAPTION_TOPIC_BANKS)


@dataclass(frozen=True)
class SceneCompatibility:
    caption_scene_tags: list[str]
    reel_scene_tags: list[str]
    decision: str
    reason: str
    match_score: int = 0


def topic_caption_banks(topic: str | None) -> list[str]:
    if not topic:
        return []
    return sorted(CAPTION_TOPIC_BANKS.get(str(topic), set()))


def infer_caption_topic_for_reel(
    *,
    frame_type: str,
    video_stem: str = "",
    prompt_text: str = "",
) -> str | None:
    value = f" {frame_type} {video_stem} {prompt_text} ".lower()
    value = re.sub(r"[_\-]+", " ", value)
    value = re.sub(r"\s+", " ", value)

    def has(pattern: str) -> bool:
        return bool(re.search(pattern, value))

    if has(
        r"\b(backwards|read this|reverse|replace|without|swap|stands for|letters?|decipher)\b"
    ):
        return "reverse_puzzle"
    if has(r"\b(pick one|choose|which one|option|remove [0-9]|password|rank|order)\b"):
        return "pick_one"
    if has(r"\b(ps5|playstation|xbox|controller|gaming|gamer|press x)\b"):
        return "gaming"
    if has(
        r"\b(spider|batman|bat hero|antihero|deadpool|shark|anime|waifu|plush|mascot)\b"
    ):
        return "fandom"
    if has(
        r"\b(good boy|mommy|boyfriend|girlfriend|bf|relationship|crush|date me|wife)\b"
    ):
        return "good_boy"
    if has(r"\b(dm|follow|message|send me|text me)\b"):
        return "dm_follow"
    if has(r"\b(maga|israel|israeli|politic|corruption|libtard)\b"):
        return "political_ragebait"
    return None


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


def classify_caption_scene_tags(
    text: str, lineage: dict[str, Any] | None = None
) -> list[str]:
    lineage = lineage if isinstance(lineage, dict) else {}
    value = f" {str(text or '').lower()} "
    tags: set[str] = set()
    content_match = lineage.get("contentMatch") or lineage.get("content_match") or {}
    if isinstance(content_match, dict):
        tags.update(
            str(tag)
            for key in ("scene_tags", "required_context_tags")
            for tag in (content_match.get(key) or [])
        )
        if content_match.get("delivery") == "event_synced" and content_match.get(
            "timing_anchor"
        ):
            tags.add("event_timing_resolved")

    def has(pattern: str) -> bool:
        return bool(re.search(pattern, value))

    if has(
        r"\b(bedroom|bed|room|sleeping|sleepy|sleep in|sleepover|wake up|my room|in my bed)\b"
    ):
        tags.update({"indoor_room", "bedroom"})
    if has(r"\b(gym|workout|fitness|squat|leggings|leg press|protein|coach)\b"):
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
    if has(r"\b(swim|swimming|jump(?:s|ing)? into (?:the )?water|dive|splash)\b"):
        tags.update({"swim_action", "action_motion"})
    if has(r"\b(car|drive|driving|passenger seat|backseat|road trip)\b"):
        tags.update({"car", "travel"})
    if has(r"\b(outside|outdoor|park|street|city|cliff|trail|hike|walking)\b"):
        tags.add("outdoor")
    if has(r"\b(travel|vacation|trip|hotel|airport|flight)\b"):
        tags.add("travel")
    if has(
        r"\b(sleeper build|handle (?:a )?girl like me|favorite distraction|"
        r"curves?|body|figure|cleavage|bikini|lingerie|sexy|spicy)\b"
    ):
        tags.add("body_forward")
    if has(r"\bsleeper build\b"):
        tags.add("calm_motion")

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

    if (
        any(
            token in value
            for token in ("gym", "fitness", "workout", "leggings", "squat")
        )
        or frame_type == "gym_body"
    ):
        tags.add("gym_body")
    if any(
        token in value
        for token in ("beach", "pool", "ocean", "sea", "shore", "bikini", "swim")
    ):
        tags.add("beach_pool")
    if any(
        token in value
        for token in (
            "jump into water",
            "jump into the water",
            "jumps into water",
            "jumps into the water",
            "jumping into the water",
            "water entry",
            "dive",
            "splash",
            "swimming",
        )
    ):
        tags.update({"swim_action", "action_motion"})
    if any(token in value for token in ("bathroom", "shower")):
        tags.add("bathroom_mirror")
    if "mirror" in value:
        tags.add("mirror_selfie")
    if any(token in value for token in ("kitchen", "cook", "cooking")):
        tags.add("kitchen")
    if any(token in value for token in (" car ", "driver", "driving", "passenger")):
        tags.add("car")
    if (
        any(
            token in value
            for token in (
                "bedroom",
                "bedroom mirror",
                "bed ",
                " room ",
                "mirror_fullbody",
            )
        )
        or frame_type == "mirror_fullbody"
    ):
        tags.add("bedroom_mirror")
    if any(
        token in value for token in ("indoor", "selfie", "closeup", "halfbody", "room")
    ) or frame_type in {"closeup", "halfbody"}:
        tags.add("indoor_selfie")
    if any(
        token in value
        for token in (
            "outdoor",
            "outside",
            "street",
            "park",
            "city",
            "cliff",
            "travel",
            "vacation",
        )
    ):
        tags.add("outdoor_lifestyle")
    if any(
        token in value
        for token in (
            "body forward",
            "body-forward",
            "cleavage",
            "curves",
            "lingerie",
            "sexy",
            "spicy",
            "revealing",
            "swimsuit",
            "bikini",
        )
    ):
        tags.add("body_forward")
    if any(
        token in value
        for token in (
            "calm",
            "subtle motion",
            "gentle motion",
            "slow motion",
            "near static",
            "near-static",
            "locked still",
        )
    ):
        tags.add("calm_motion")
    if any(
        token in value
        for token in ("jump", "dive", "splash", "running", "dancing", "workout motion")
    ):
        tags.add("action_motion")

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
        return SceneCompatibility(
            caption_tags, reel_tags, "fit_disabled", "caption scene fit disabled", 0
        )

    required_context = {
        "swim_action",
        "calm_motion",
        "action_motion",
        "body_forward",
        "event_timing_resolved",
    }
    caption_requirements = set(caption_tags) & required_context
    missing_requirements = sorted(caption_requirements - set(reel_tags))
    if missing_requirements:
        return SceneCompatibility(
            caption_tags,
            reel_tags,
            "blocked",
            f"caption requires {','.join(missing_requirements)} visual context",
            0,
        )

    blocked_tags = _blocked_caption_tags_for_reel(reel_tags)
    explicit_caption_tags = set(caption_tags) - {"general"}
    blocked_overlap = sorted(explicit_caption_tags & blocked_tags)
    if blocked_overlap:
        return SceneCompatibility(
            caption_tags,
            reel_tags,
            "blocked",
            f"{','.join(blocked_overlap)} caption blocked for {','.join(reel_tags)} reel",
            0,
        )

    if "unknown" in reel_tags and explicit_caption_tags:
        return SceneCompatibility(
            caption_tags,
            reel_tags,
            "unknown_allowed",
            "unknown reel scene; no obvious scene mismatch",
            0,
        )

    scene_overlap = set(caption_tags) & _caption_tags_for_reel(reel_tags)
    return SceneCompatibility(
        caption_tags,
        reel_tags,
        "allowed",
        f"caption scene compatible with {','.join(reel_tags)} reel",
        len(scene_overlap) + (2 * len(caption_requirements)),
    )


def _caption_tags_for_reel(reel_tags: list[str]) -> set[str]:
    tags = set(reel_tags)
    mapped = set(tags)
    if "beach_pool" in tags:
        mapped.update({"beach", "pool", "outdoor"})
    if "gym_body" in tags:
        mapped.add("gym")
    if "outdoor_lifestyle" in tags:
        mapped.add("outdoor")
    if "bedroom_mirror" in tags:
        mapped.update({"bedroom", "mirror_selfie", "indoor_room"})
    if "bathroom_mirror" in tags:
        mapped.update({"bathroom", "mirror_selfie", "indoor_room"})
    if "mirror_selfie" in tags:
        mapped.add("mirror_selfie")
    if "kitchen" in tags:
        mapped.update({"kitchen", "indoor_room"})
    if "car" in tags:
        mapped.update({"car", "travel"})
    if "indoor_selfie" in tags:
        mapped.add("indoor_room")
    return mapped


def _blocked_caption_tags_for_reel(reel_tags: list[str]) -> set[str]:
    tags = set(reel_tags)
    if "beach_pool" in tags:
        return {"bedroom", "gym", "car"}
    if "gym_body" in tags:
        return {"bedroom", "beach", "pool", "car", "travel"}
    if "outdoor_lifestyle" in tags:
        return {"bedroom", "gym"}
    if "car" in tags:
        return {"bedroom", "bathroom", "kitchen", "gym", "beach", "pool"}
    if "kitchen" in tags:
        return {"bedroom", "bathroom", "gym", "beach", "pool", "car"}
    if tags & {"indoor_selfie", "bedroom_mirror", "bathroom_mirror"}:
        return {"beach", "pool", "gym", "car", "outdoor", "travel"}
    # unknown reel scene = undetected, NOT incompatible. Blocking on uncertainty
    # threw away the best captions (bedroom/coded winners) whenever scene detection
    # came back empty. Only block on a positive conflicting reel tag; "unknown"
    # falls through to the unknown_allowed path in evaluate_scene_compatibility.
    return set()


def _ordered_tags(tags: set[str], allowed: set[str]) -> list[str]:
    return sorted(tag for tag in tags if tag in allowed)
