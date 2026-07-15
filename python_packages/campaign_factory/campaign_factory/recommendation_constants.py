from __future__ import annotations

RECOMMENDATION_ITEM_STATUSES = {
    "proposed",
    "accepted",
    "rejected",
    "executed",
    "posted",
    "measured",
    "proved",
    "disproved",
}
RECOMMENDATION_STATUS_TRANSITIONS = {
    "proposed": {"accepted", "rejected"},
    "accepted": {"executed", "posted", "rejected"},
    "rejected": set(),
    "executed": {"posted", "measured", "proved", "disproved"},
    "posted": {"measured", "proved", "disproved"},
    "measured": {"proved", "disproved"},
    "proved": set(),
    "disproved": set(),
}
RECOMMENDATION_MEASUREMENT_VERSION = "recommendation_measurement.v1"
RECOMMENDATION_MEASUREMENT_THRESHOLD = 5
AUTONOMY_LEVELS = {"level_1", "level_2", "level_3"}
DEFAULT_AUTONOMY_LEVEL = "level_2"
REFERENCE_PATTERN_MIN_MEASURED_EXAMPLES = 3
