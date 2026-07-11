from __future__ import annotations

import os
from typing import Any

DEFAULT_LABEL_WEIGHTS = {
    "gold": 4.0,
    "maybe": 2.0,
    "unlabeled": 1.0,
    "ignore": 0.0,
}


def review_label_weight(label: Any) -> float:
    normalized = str(label or "unlabeled").strip().lower()
    env_name = {
        "gold": "REFERENCE_LABEL_WEIGHT_GOLD",
        "maybe": "REFERENCE_LABEL_WEIGHT_MAYBE",
        "unlabeled": "REFERENCE_LABEL_WEIGHT_UNLABELED",
        "ignore": "REFERENCE_LABEL_WEIGHT_IGNORE",
    }.get(normalized, "REFERENCE_LABEL_WEIGHT_UNLABELED")
    default = DEFAULT_LABEL_WEIGHTS.get(normalized, DEFAULT_LABEL_WEIGHTS["unlabeled"])
    try:
        return max(0.0, float(os.environ.get(env_name, default)))
    except ValueError:
        return default


def item_taste_weight(item: dict[str, Any]) -> float:
    value = item.get("tasteWeight")
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    return review_label_weight(item.get("reviewLabel"))
