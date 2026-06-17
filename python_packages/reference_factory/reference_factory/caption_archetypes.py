from __future__ import annotations

import re


def caption_archetype(caption: str) -> str:
    lowered = caption.lower().strip()
    if not lowered:
        return "captionless_visual"
    if re.search(r"\b(99\.9|find all|spot the|can.t find)\b", lowered):
        return "challenge_or_puzzle"
    if lowered.startswith("pov") or " pov " in f" {lowered} ":
        return "pov_scenario"
    if lowered.startswith(("when ", "me when", "how it feels")):
        return "relatable_scenario"
    if lowered.startswith(("pick one", "choose one")):
        return "choice_bait"
    if "?" in caption:
        return "question_hook"
    if len(lowered) <= 12:
        return "minimal_bait"
    if "#" in lowered:
        return "hashtag_context"
    if re.search(r"\bfollow\b|\bclaim\b|\bsend\b|\btag\b", lowered):
        return "cta_bait"
    return "short_meme_caption"
