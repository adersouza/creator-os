from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from . import exports


class ExportSummaryRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        dashboard: Callable[[str], dict[str, Any]],
        audio_workflow_summary: Callable[[list[dict[str, Any]]], dict[str, Any]],
        creative_plan_for_campaign: Callable[..., dict[str, Any] | None],
        active_reference_pattern_for_campaign: Callable[..., dict[str, Any] | None],
        generated_asset_lineage: Callable[..., dict[str, Any]],
        creative_plan_payload: Callable[[dict[str, Any]], dict[str, Any]],
        audio_recommendations_for_asset: Callable[..., dict[str, Any]],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        graph_id_for: Callable[..., str | None],
        ensure_graph_edge: Callable[..., str],
    ) -> None:
        self.conn = conn
        self._dashboard = dashboard
        self._audio_workflow_summary = audio_workflow_summary
        self._creative_plan_for_campaign = creative_plan_for_campaign
        self._active_reference_pattern_for_campaign = (
            active_reference_pattern_for_campaign
        )
        self._generated_asset_lineage = generated_asset_lineage
        self._creative_plan_payload = creative_plan_payload
        self._audio_recommendations_for_asset = audio_recommendations_for_asset
        self._campaign_by_slug = campaign_by_slug
        self._graph_id_for = graph_id_for
        self._ensure_graph_edge = ensure_graph_edge

    def batch_summary(self, campaign_slug: str) -> dict[str, Any]:
        return exports.batch_summary(self, campaign_slug)

    def daily_production_counters(
        self,
        campaign_slug: str,
        *,
        dashboard: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return exports.daily_production_counters(
            self, campaign_slug, dashboard=dashboard
        )

    def variant_pack_groups(
        self, rendered: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return exports._variant_pack_groups(self, rendered)

    def export_manifest(
        self, *, campaign_slug: str, review_only: bool = False
    ) -> dict[str, Any]:
        if review_only:
            return exports.export_manifest(
                self,
                campaign_slug=campaign_slug,
                review_only=True,
            )
        return exports.export_manifest(self, campaign_slug=campaign_slug)
