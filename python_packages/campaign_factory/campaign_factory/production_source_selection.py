"""Exact approved-source selection shared by supervised production callers."""

from __future__ import annotations

from typing import Any


def select_requested_source_assets(
    sources: list[dict[str, Any]],
    selected_source_asset_ids: tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    if selected_source_asset_ids is None:
        return sources
    requested = tuple(
        str(value).strip() for value in selected_source_asset_ids if str(value).strip()
    )
    if not requested:
        raise ValueError("selected source asset IDs cannot be empty")
    available = {str(source["id"]): source for source in sources}
    missing = [source_id for source_id in requested if source_id not in available]
    if missing:
        raise ValueError(
            "selected source is not an approved compatible creator asset: "
            + ", ".join(missing)
        )
    return [available[source_id] for source_id in requested]
