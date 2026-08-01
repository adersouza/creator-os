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
