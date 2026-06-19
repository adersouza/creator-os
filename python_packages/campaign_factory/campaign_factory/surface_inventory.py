from __future__ import annotations

import sqlite3
from typing import Any, Callable


class SurfaceInventoryRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        slugify: Callable[[str], str],
        creator_label: Callable[[Any], str],
        normalize_content_surface: Callable[[str | None], str],
        surface_report_assets: Callable[..., list[dict[str, Any]]],
        build_surface_readiness: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        build_surface_inventory_for_audit: Callable[..., dict[str, Any]] | None = None,
        content_surfaces: tuple[str, ...],
    ) -> None:
        self.conn = conn
        self._slugify = slugify
        self._creator_label = creator_label
        self._normalize_content_surface = normalize_content_surface
        self._surface_report_assets = surface_report_assets
        self._build_surface_readiness = build_surface_readiness
        self._build_surface_inventory_for_audit = build_surface_inventory_for_audit
        self._content_surfaces = content_surfaces

    def multi_surface_inventory_audit(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        build_surface_inventory = self._build_surface_inventory_for_audit or self.build_surface_inventory
        built = build_surface_inventory(creator=creator_label, campaign_slug=campaign_slug)
        inventory = built["inventoryBySurface"]
        missing = [
            surface
            for surface, counts in inventory.items()
            if counts["total"] == 0 or counts["scheduleSafe"] == 0
        ]
        return {
            "schema": "campaign_factory.multi_surface_inventory_audit.v1",
            "creator": creator_label,
            "inventoryBySurface": inventory,
            "surfacesMissingInventory": missing,
            "wouldWrite": False,
        }

    def build_surface_inventory(
        self,
        *,
        creator: str,
        campaign_slug: str | None = None,
    ) -> dict[str, Any]:
        creator_label = self._creator_label(creator)
        assets_by_surface = {surface: [] for surface in self._content_surfaces}
        inventory = {
            surface: {"total": 0, "scheduleSafe": 0}
            for surface in self._content_surfaces
        }
        assets = self._surface_report_assets(creator=creator_label, campaign_slug=campaign_slug)
        readiness_items = self._build_surface_readiness(assets)
        readiness_by_asset = {item.get("assetId"): item for item in readiness_items}
        for asset in assets:
            surface = self._normalize_content_surface(asset.get("content_surface") or asset.get("source_content_surface"))
            if surface not in inventory:
                continue
            assets_by_surface[surface].append(asset)
            inventory[surface]["total"] += 1
            if (readiness_by_asset.get(asset.get("id")) or {}).get("canHandoff"):
                inventory[surface]["scheduleSafe"] += 1
        return {
            "creator": creator_label,
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "assets": assets,
            "assetsBySurface": assets_by_surface,
            "readiness": readiness_items,
            "inventoryBySurface": inventory,
            "wouldWrite": False,
        }
