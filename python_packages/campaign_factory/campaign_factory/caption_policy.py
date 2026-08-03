import json
import re
from typing import Any

CAPTION_PLACEMENT_QC_WARNING_CODES = {
    "caption_too_close_to_edge",
    "caption_overlaps_ui_safe_zone",
    "caption_low_confidence",
    "text_hidden",
    "safe_zone_violation",
}

WARNING_CLASS_HARD_BLOCKER = "hard_blocker"
WARNING_CLASS_OPERATOR_OVERRIDABLE = "operator_overridable"
WARNING_CLASS_ADVISORY = "advisory"

WARNING_CLASS_BY_CODE = {
    "caption_too_close_to_edge": WARNING_CLASS_OPERATOR_OVERRIDABLE,
    "caption_low_confidence": WARNING_CLASS_OPERATOR_OVERRIDABLE,
    "caption_low_contrast": WARNING_CLASS_OPERATOR_OVERRIDABLE,
    "caption_overlaps_ui_safe_zone": WARNING_CLASS_HARD_BLOCKER,
    "text_hidden": WARNING_CLASS_HARD_BLOCKER,
    "safe_zone_violation": WARNING_CLASS_HARD_BLOCKER,
    "face_covered_by_caption": WARNING_CLASS_HARD_BLOCKER,
    "ocr_unavailable_with_burned_text": WARNING_CLASS_HARD_BLOCKER,
    "pdq_detector_unavailable": WARNING_CLASS_HARD_BLOCKER,
    "sscd_detector_unavailable": WARNING_CLASS_HARD_BLOCKER,
    "exact_media_sha_mismatch": WARNING_CLASS_HARD_BLOCKER,
    "missing_identity_evidence": WARNING_CLASS_HARD_BLOCKER,
}


def warning_class(code: str) -> str:
    return WARNING_CLASS_BY_CODE.get(code, WARNING_CLASS_ADVISORY)


SIMPLE_INSTAGRAM_POST_CAPTION_REPAIR_POOL = (
    "new fit today",
    "which one wins?",
    "felt cute",
    "mirror check",
    "simple today",
    "pick one",
    "soft launch",
    "posting this one",
)

CONTEXTUAL_INSTAGRAM_POST_CAPTIONS = (
    (("pool", "swim", "water"), ("pool day", "needed this swim", "water always wins")),
    (
        ("gym", "workout", "fitness"),
        ("post workout check", "gym fit today", "after the workout"),
    ),
    (
        ("mirror", "outfit", "fullbody"),
        ("mirror said yes", "today's fit", "this look won"),
    ),
    (
        ("car", "passenger", "driver"),
        ("passenger seat thoughts", "car selfie", "on the way"),
    ),
    (
        ("beach", "ocean", "vacation"),
        ("needed this view", "beach day", "out of office"),
    ),
    (
        ("bedroom", "late_night", "indoor_selfie"),
        ("late night thoughts", "staying in", "one more selfie"),
    ),
)


def contextual_instagram_post_caption_pool(
    context: dict[str, Any] | None,
) -> tuple[str, ...]:
    context_text = json.dumps(context or {}, ensure_ascii=False, sort_keys=True).lower()
    return next(
        (
            candidates
            for tokens, candidates in CONTEXTUAL_INSTAGRAM_POST_CAPTIONS
            if any(token in context_text for token in tokens)
        ),
        SIMPLE_INSTAGRAM_POST_CAPTION_REPAIR_POOL,
    )


def caption_quality_recovery_class(quality_reasons: list[str]) -> str:
    reasons = set(quality_reasons)
    if reasons and reasons <= {
        "instagram_post_caption_too_many_hashtags",
        "instagram_post_caption_too_many_lines",
    }:
        return "recoverableByHashtagTrim"
    if "instagram_post_caption_platform_risk" in reasons:
        return "recoverableByCTARemoval"
    return "recoverableByCaptionRewrite"


def instagram_post_caption_quality(post_caption: dict[str, Any]) -> dict[str, Any]:
    caption = str(post_caption.get("instagram_post_caption") or "").strip()
    burned = str(post_caption.get("burned_caption_text") or "").strip()
    hashtags = list(post_caption.get("hashtags") or [])
    reasons: list[str] = []
    if not caption:
        return {
            "passed": False,
            "reasons": ["blank_instagram_post_caption"],
            "policy": "simple_ig_post_caption_v1",
            "maxCharacters": 140,
            "maxLines": 3,
            "maxHashtags": 5,
        }
    lines = [line for line in caption.splitlines() if line.strip()]
    if len(caption) > 140:
        reasons.append("instagram_post_caption_too_long")
    if len(lines) > 3:
        reasons.append("instagram_post_caption_too_many_lines")
    if len(re.findall(r"#[A-Za-z0-9_]+", caption)) > 5 or len(hashtags) > 5:
        reasons.append("instagram_post_caption_too_many_hashtags")
    if re.search(
        r"https?://|www\.|link\s*in\s*bio|dm\s+me|message\s+me|text\s+me|telegram|whatsapp|onlyfans|fansly",
        caption,
        re.IGNORECASE,
    ):
        reasons.append("instagram_post_caption_platform_risk")
    caption_words = re.findall(r"[A-Za-z0-9']+", caption.lower())
    burned_words = re.findall(r"[A-Za-z0-9']+", burned.lower())
    if burned and caption.lower() == burned.lower() and len(burned_words) > 8:
        reasons.append("instagram_post_caption_copied_long_burned_caption")
    return {
        "passed": not reasons,
        "reasons": sorted(set(reasons)),
        "policy": "simple_ig_post_caption_v1",
        "maxCharacters": 140,
        "maxLines": 3,
        "maxHashtags": 5,
        "characterCount": len(caption),
        "lineCount": len(lines),
        "wordCount": len(caption_words),
        "hashtagCount": max(len(re.findall(r"#[A-Za-z0-9_]+", caption)), len(hashtags)),
    }
