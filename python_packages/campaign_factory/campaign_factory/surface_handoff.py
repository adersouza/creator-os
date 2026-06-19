from __future__ import annotations

import sqlite3
from typing import Any, Callable


class SurfaceHandoffRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        slugify: Callable[[str], str],
        creator_label: Callable[[Any], str],
        surface_report_assets: Callable[..., list[dict[str, Any]]],
        build_surface_readiness: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        surface_handoff_readiness_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        asset_matches_creator: Callable[[dict[str, Any], str], bool],
    ) -> None:
        self.conn = conn
        self._slugify = slugify
        self._creator_label = creator_label
        self._surface_report_assets = surface_report_assets
        self._build_surface_readiness = build_surface_readiness
        self._surface_handoff_readiness_for_asset = surface_handoff_readiness_for_asset
        self._asset_matches_creator = asset_matches_creator

    def surface_handoff_readiness_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        assets = self._surface_report_assets(
            creator=self._creator_label(creator) if creator else None,
            campaign_slug=campaign_slug,
        )
        if rendered_asset_id:
            assets = [asset for asset in assets if asset["id"] == rendered_asset_id]
        items = self._build_surface_readiness(assets)
        return {
            "schema": "campaign_factory.surface_handoff_readiness_report.v1",
            "creator": self._creator_label(creator) if creator else None,
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "assets": items,
            "wouldWrite": False,
        }

    def surface_draft_proof(
        self,
        *,
        creator: str | None = None,
        campaign: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        assets = self._surface_report_assets(
            creator=self._creator_label(creator) if creator else None,
            campaign_slug=campaign,
        )
        if rendered_asset_id:
            assets = [asset for asset in assets if asset["id"] == rendered_asset_id]
        readiness_items = self._build_surface_readiness(assets)
        drafts = [
            self.surface_draft_payload_for_readiness(item)
            for item in readiness_items
            if item.get("canHandoff")
        ]
        blocking = [
            {
                "assetId": item["assetId"],
                "blockingReasons": item.get("blockingReasons") or [],
            }
            for item in readiness_items
            if not item.get("canHandoff")
        ]
        return {
            "schema": "campaign_factory.surface_draft_proof.v1",
            "creator": self._creator_label(creator) if creator else None,
            "campaign": self._slugify(campaign) if campaign else None,
            "renderedAssetId": rendered_asset_id,
            "canProduceDraftPayload": bool(drafts) and not blocking,
            "draftCount": len(drafts),
            "drafts": drafts,
            "blockedAssets": blocking,
            "wouldWrite": False,
        }

    def surface_report_assets(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = []
        if campaign_slug:
            where.append("c.slug = ?")
            params.append(self._slugify(campaign_slug))
        query = """
            SELECT r.*, c.slug AS campaign_slug, s.media_type AS source_media_type,
                   s.content_surface AS source_content_surface, m.slug AS model_slug, m.name AS model_name
            FROM rendered_assets r
            JOIN campaigns c ON c.id = r.campaign_id
            JOIN source_assets s ON s.id = r.source_asset_id
            JOIN models m ON m.id = s.model_id
        """
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY r.created_at, r.id"
        rows = [dict(row) for row in self.conn.execute(query, params).fetchall()]
        if not creator:
            return rows
        return [row for row in rows if self._asset_matches_creator(row, creator)]

    def build_surface_readiness(self, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self._surface_handoff_readiness_for_asset(asset) for asset in assets]

    def surface_draft_payload_for_readiness(self, readiness: dict[str, Any]) -> dict[str, Any]:
        manifest = readiness.get("handoffManifestV2") if isinstance(readiness.get("handoffManifestV2"), dict) else {}
        media_items = manifest.get("mediaItems") if isinstance(manifest.get("mediaItems"), list) else []
        return {
            "schema": "threadsdash.surface_draft.preview.v1",
            "status": "draft",
            "platform": "instagram",
            "assetId": readiness.get("assetId"),
            "contentSurface": readiness.get("contentSurface"),
            "igMediaType": readiness.get("igMediaType"),
            "mediaType": readiness.get("mediaType"),
            "mediaItems": media_items,
            "instagramPostCaption": manifest.get("instagramPostCaption") or "",
            "handoffManifestV2": manifest,
            "metadata": {
                "campaign_factory": {
                    "rendered_asset_id": readiness.get("assetId"),
                    "content_surface": readiness.get("contentSurface"),
                    "ig_media_type": readiness.get("igMediaType"),
                    "asset_state": "exportable",
                    "publishability_failure_reasons": [],
                    "content_fingerprint": manifest.get("content_fingerprint") or manifest.get("content_hash"),
                    "caption_hash": manifest.get("caption_hash"),
                    "instagram_post_caption": manifest.get("instagramPostCaption") or manifest.get("instagram_post_caption") or "",
                    "instagram_post_caption_hash": manifest.get("instagram_post_caption_hash"),
                    "hashtags": manifest.get("hashtags") or [],
                    "post_caption_style": manifest.get("post_caption_style") or "short_natural",
                    "handoff_manifest": manifest,
                    "handoff_manifest_v2": manifest,
                    "dry_run": True,
                }
            },
            "wouldWrite": False,
        }
