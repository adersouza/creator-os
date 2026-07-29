from __future__ import annotations

from typing import Any


def int_metric(row: dict[str, Any], meta: dict[str, Any], *keys: str) -> int | None:
    value = metric_value(row, meta, *keys)
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def float_metric(row: dict[str, Any], meta: dict[str, Any], *keys: str) -> float | None:
    value = metric_value(row, meta, *keys)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def watch_time_seconds(row: dict[str, Any], meta: dict[str, Any]) -> float | None:
    """Normalize ThreadsDashboard watch-time fields to total seconds."""

    normalized = float_metric(
        row, meta, "watch_time_seconds", "watchTimeSeconds", "watch_time"
    )
    if normalized is not None:
        return normalized
    total_ms = float_metric(row, meta, "ig_reels_video_view_total_time")
    if total_ms is not None:
        return total_ms / 1000.0
    average_ms = float_metric(row, meta, "ig_reels_avg_watch_time")
    if average_ms is None:
        return None
    views = int_metric(row, meta, "views", "view_count", "views_count", "ig_views")
    return None if views is None else average_ms * views / 1000.0


def metric_value(row: dict[str, Any], meta: dict[str, Any], *keys: str) -> Any:
    for source in (row, meta):
        for key in keys:
            if source.get(key) is not None:
                return source.get(key)
    return None
