from __future__ import annotations

from typing import Any

from . import exports


class ExportSummaryRepository:
    def __init__(self, factory_context: Any) -> None:
        self._factory_context = factory_context

    def batch_summary(self, campaign_slug: str) -> dict[str, Any]:
        return exports.batch_summary(self._factory_context, campaign_slug)

    def daily_production_counters(
        self,
        campaign_slug: str,
        *,
        dashboard: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return exports.daily_production_counters(self._factory_context, campaign_slug, dashboard=dashboard)

    def variant_pack_groups(self, rendered: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return exports._variant_pack_groups(self._factory_context, rendered)

    def export_manifest(self, *, campaign_slug: str) -> dict[str, Any]:
        return exports.export_manifest(self._factory_context, campaign_slug=campaign_slug)
