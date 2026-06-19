from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from .caption_outcome import load_context_json
from .persistence import json_load, utc_now


class InventoryPerceptualRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        rendered_asset: Callable[[str], dict[str, Any]],
        compute_pdq_fingerprint: Callable[..., dict[str, Any]],
        pdq_hamming_distance: Callable[[str, str], int | None],
        sanitize_for_storage: Callable[[Any], Any],
    ) -> None:
        self.conn = conn
        self._rendered_asset = rendered_asset
        self._compute_pdq_fingerprint = compute_pdq_fingerprint
        self._pdq_hamming_distance = pdq_hamming_distance
        self._sanitize_for_storage = sanitize_for_storage

    def asset_uniqueness_values(
        self,
        asset: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        asset_metadata = json_load(asset.get("metadata_json"), {})
        if not isinstance(asset_metadata, dict):
            asset_metadata = {}
        metadata = {**asset_metadata, **(metadata or {})}
        caption_generation = json_load(asset.get("caption_generation_json"), {})
        if not isinstance(caption_generation, dict):
            caption_generation = {}
        caption_context = load_context_json(asset.get("caption_outcome_context_json"))
        source_family = (
            metadata.get("sourceFamilyId")
            or metadata.get("source_family_id")
            or caption_generation.get("sourceFamilyId")
            or caption_generation.get("source_family_id")
            or caption_context.get("source_family_id")
            or asset.get("parent_asset_id")
            or asset.get("parent_reel_id")
        )
        perceptual = (
            metadata.get("perceptualFingerprint")
            or metadata.get("perceptual_fingerprint")
            or caption_generation.get("perceptualFingerprint")
            or caption_generation.get("perceptual_fingerprint")
            or caption_context.get("perceptual_fingerprint")
        )
        cluster = (
            metadata.get("perceptualClusterId")
            or metadata.get("perceptual_cluster_id")
            or caption_generation.get("perceptualClusterId")
            or caption_generation.get("perceptual_cluster_id")
            or caption_context.get("perceptual_cluster_id")
            or perceptual
            or source_family
        )
        account_group = (
            metadata.get("accountGroupId")
            or metadata.get("account_group_id")
            or caption_generation.get("accountGroupId")
            or caption_generation.get("account_group_id")
            or caption_context.get("account_group_id")
            or asset.get("creator_model")
            or asset.get("creator_mix")
            or asset.get("campaign_id")
        )
        return {
            "sourceFamilyId": str(source_family or ""),
            "contentFingerprint": str(asset.get("content_hash") or ""),
            "perceptualFingerprint": str(perceptual or ""),
            "perceptualClusterId": str(cluster or ""),
            "accountGroupId": str(account_group or ""),
        }

    def ensure_rendered_asset_perceptual_metadata(
        self,
        rendered_asset_id: str,
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        asset = self._rendered_asset(rendered_asset_id)
        metadata = json_load(asset.get("metadata_json"), {})
        if not isinstance(metadata, dict):
            metadata = {}
        existing_fingerprint = metadata.get("perceptualFingerprint") or metadata.get("perceptual_fingerprint")
        existing_cluster = metadata.get("perceptualClusterId") or metadata.get("perceptual_cluster_id")
        if existing_fingerprint and existing_cluster:
            return asset

        media_path = Path(str(asset.get("campaign_path") or asset.get("output_path") or ""))
        result = self._compute_pdq_fingerprint(media_path)
        perceptual_meta = {
            "algorithm": result.get("algorithm") or "pdq_v1",
            "status": result.get("status") or "unavailable",
            "source": result.get("source"),
            "quality": result.get("quality"),
            "code": result.get("code"),
            "detail": result.get("detail"),
        }
        updated = dict(metadata)
        updated["perceptual"] = {key: value for key, value in perceptual_meta.items() if value is not None}
        if result.get("status") == "available" and result.get("fingerprint"):
            fingerprint = str(result["fingerprint"])
            cluster_id = self.pdq_cluster_id_for_fingerprint(
                campaign_id=str(asset["campaign_id"]),
                rendered_asset_id=str(asset["id"]),
                fingerprint=fingerprint,
            )
            updated.update({
                "perceptualFingerprint": fingerprint,
                "perceptual_fingerprint": fingerprint,
                "perceptualClusterId": cluster_id,
                "perceptual_cluster_id": cluster_id,
            })
        if updated == metadata:
            return asset
        now = utc_now()
        self.conn.execute(
            "UPDATE rendered_assets SET metadata_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(self._sanitize_for_storage(updated), ensure_ascii=False, sort_keys=True), now, rendered_asset_id),
        )
        if commit:
            self.conn.commit()
        refreshed = self.conn.execute("SELECT * FROM rendered_assets WHERE id = ?", (rendered_asset_id,)).fetchone()
        return dict(refreshed or asset)

    def pdq_cluster_id_for_fingerprint(
        self,
        *,
        campaign_id: str,
        rendered_asset_id: str,
        fingerprint: str,
    ) -> str:
        fallback = f"pdq:{fingerprint[:16]}"
        rows = self.conn.execute(
            "SELECT id, metadata_json FROM rendered_assets WHERE campaign_id = ? AND id <> ? ORDER BY created_at, id",
            (campaign_id, rendered_asset_id),
        ).fetchall()
        for row in rows:
            metadata = json_load(row["metadata_json"], {})
            if not isinstance(metadata, dict):
                continue
            other = metadata.get("perceptualFingerprint") or metadata.get("perceptual_fingerprint")
            distance = self._pdq_hamming_distance(fingerprint, str(other or ""))
            if distance is not None and distance <= 40:
                cluster = metadata.get("perceptualClusterId") or metadata.get("perceptual_cluster_id")
                return str(cluster or f"pdq:{str(other)[:16]}")
        return fallback
