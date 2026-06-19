from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

from .caption_outcome import load_context_json
from .persistence import json_load, utc_now


class SurfaceHandoffRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        slugify: Callable[[str], str],
        creator_label: Callable[[Any], str],
        media_type_for_path: Callable[[Any], str],
        normalize_content_surface: Callable[[str | None], str],
        discoverability_safe_content_contract: Callable[..., dict[str, Any]],
        explain_publishability: Callable[..., dict[str, Any]],
        latest_distribution_plan_for_asset: Callable[[str], dict[str, Any] | None],
        latest_audit_for_asset: Callable[[str], dict[str, Any] | None],
        instagram_post_caption_for_asset: Callable[..., dict[str, Any]],
        variant_lineage_for_asset: Callable[[str], dict[str, Any]],
        story_quality_gate_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        story_style_value: Callable[[dict[str, Any]], str | None],
        story_intent_value: Callable[[dict[str, Any]], str | None],
        truthy: Callable[[Any], bool],
        story_native_proof_styles: set[str],
        ig_media_type_by_surface: dict[str, str],
    ) -> None:
        self.conn = conn
        self._slugify = slugify
        self._creator_label = creator_label
        self._media_type_for_path = media_type_for_path
        self._normalize_content_surface = normalize_content_surface
        self._discoverability_safe_content_contract = discoverability_safe_content_contract
        self._explain_publishability = explain_publishability
        self._latest_distribution_plan_for_asset = latest_distribution_plan_for_asset
        self._latest_audit_for_asset = latest_audit_for_asset
        self._instagram_post_caption_for_asset = instagram_post_caption_for_asset
        self._variant_lineage_for_asset = variant_lineage_for_asset
        self._story_quality_gate_for_asset = story_quality_gate_for_asset
        self._story_style_value = story_style_value
        self._story_intent_value = story_intent_value
        self._truthy = truthy
        self._story_native_proof_styles = story_native_proof_styles
        self._ig_media_type_by_surface = ig_media_type_by_surface

    def surface_handoff_readiness_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        assets = self.surface_report_assets(
            creator=self._creator_label(creator) if creator else None,
            campaign_slug=campaign_slug,
        )
        if rendered_asset_id:
            assets = [asset for asset in assets if asset["id"] == rendered_asset_id]
        items = self.build_surface_readiness(assets)
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
        assets = self.surface_report_assets(
            creator=self._creator_label(creator) if creator else None,
            campaign_slug=campaign,
        )
        if rendered_asset_id:
            assets = [asset for asset in assets if asset["id"] == rendered_asset_id]
        readiness_items = self.build_surface_readiness(assets)
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
        return [row for row in rows if self.asset_matches_creator(row, creator)]

    def build_surface_readiness(self, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.surface_handoff_readiness_for_asset(asset) for asset in assets]

    def requires_operator_visual_review_for_handoff(self, asset: dict[str, Any]) -> bool:
        operations: list[dict[str, Any]] = []
        raw_operations = json_load(asset.get("variant_operations_json"), [])
        if isinstance(raw_operations, list):
            operations.extend(item for item in raw_operations if isinstance(item, dict))
        metadata = json_load(asset.get("metadata_json"), {})
        if not isinstance(metadata, dict):
            metadata = {}
        asset_id = asset.get("id")
        if asset_id:
            lineage = self._variant_lineage_for_asset(str(asset_id))
            lineage_operations = lineage.get("variant_operations") if isinstance(lineage, dict) else None
            if isinstance(lineage_operations, list):
                operations.extend(item for item in lineage_operations if isinstance(item, dict))
        uses_ad_hoc_inventory_fill = any(
            operation.get("type") == "inventory_fill_ffmpeg_variant"
            for operation in operations
        )
        has_visual_review_pass = any(
            operation.get("type") in {"operator_visual_review_passed", "visual_qc_passed"}
            or operation.get("visualReviewPassed") is True
            or operation.get("visual_qc_passed") is True
            for operation in operations
        ) or metadata.get("operator_visual_review_passed") is True or metadata.get("visual_qc_passed") is True
        surface = self._normalize_content_surface(asset.get("content_surface") or asset.get("source_content_surface"))
        source_marker_parts = [
            str(asset.get("campaign_slug") or ""),
            str(asset.get("filename") or ""),
            Path(str(asset.get("campaign_path") or "")).name,
            Path(str(asset.get("output_path") or "")).name,
            str(asset.get("source_prompt") or ""),
            str(asset.get("notes") or ""),
        ]
        source_markers = " ".join(source_marker_parts).lower()
        uses_unreviewed_reel_proof_or_preview = surface == "reel" and any(
            marker in source_markers
            for marker in (
                "_audio_preview_",
                "parent_factory_53_production_trial",
                "inventory_fill",
                "variant_fanout_proof",
                "surface_proof",
            )
        )
        return bool((uses_ad_hoc_inventory_fill or uses_unreviewed_reel_proof_or_preview) and not has_visual_review_pass)

    def content_trust_status_blockers(
        self,
        asset: dict[str, Any],
        latest_audit: dict[str, Any] | None,
        caption_context: dict[str, Any] | None,
    ) -> tuple[list[str], dict[str, str]]:
        metadata = json_load(asset.get("metadata_json"), {})
        if not isinstance(metadata, dict):
            metadata = {}
        audit = latest_audit if isinstance(latest_audit, dict) else {}
        readiness = audit.get("readinessSummary") if isinstance(audit.get("readinessSummary"), dict) else {}

        def nested_status(source: dict[str, Any], *keys: str) -> str:
            for key in keys:
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip().lower()
                if isinstance(value, dict):
                    for nested_key in ("status", key, "visualQcStatus", "identityVerificationStatus"):
                        nested = value.get(nested_key)
                        if isinstance(nested, str) and nested.strip():
                            return nested.strip().lower()
            return ""

        passed_statuses = {"passed", "pass", "approved", "ready"}

        def resolved_status(*keys: str) -> str:
            statuses = [nested_status(source, *keys) for source in [metadata, caption_context or {}, audit, readiness]]
            statuses = [status for status in statuses if status]
            blocking_status = next((status for status in statuses if status not in passed_statuses), "")
            if blocking_status:
                return blocking_status
            return "passed" if statuses else ""

        visual_status = resolved_status("visualQcStatus", "visual_qc_status", "visualQc", "visual_qc")
        identity_status = resolved_status(
            "identityVerificationStatus",
            "identity_verification_status",
            "identityVerification",
            "identity_verification",
        )
        blockers: list[str] = []
        unavailable_statuses = {"", "missing", "none", "null", "pending", "queued", "unknown", "unavailable", "not_available", "not_found"}

        def blocker_code(prefix: str, status: str) -> str:
            suffix = "unavailable" if status in unavailable_statuses else "failed"
            return f"{prefix}_{suffix}"

        if visual_status != "passed":
            blockers.append(blocker_code("visual_qc", visual_status))
        if identity_status != "passed":
            blockers.append(blocker_code("identity_verification", identity_status))
        return blockers, {
            "visualQcStatus": visual_status or "unavailable",
            "identityVerificationStatus": identity_status or "unavailable",
        }

    def asset_matches_creator(self, asset: dict[str, Any], creator: str) -> bool:
        expected = self._creator_label(creator).lower()
        caption_context = load_context_json(asset.get("caption_outcome_context_json"))
        candidates = [
            asset.get("creator_mix"),
            asset.get("creator_model"),
            asset.get("model_slug"),
            asset.get("model_name"),
            caption_context.get("creator_mix") if isinstance(caption_context, dict) else None,
            caption_context.get("creator_model") if isinstance(caption_context, dict) else None,
        ]
        return any(self._creator_label(candidate).lower() == expected for candidate in candidates if candidate)

    def surface_handoff_readiness_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        surface = self._normalize_content_surface(asset.get("content_surface") or asset.get("source_content_surface"))
        media_type = str(
            asset.get("media_type")
            or asset.get("source_media_type")
            or self._media_type_for_path(asset.get("campaign_path") or asset.get("filename") or "")
        ).lower()
        blocking: list[str] = []
        warnings: list[str] = []
        caption_context = load_context_json(asset.get("caption_outcome_context_json"))
        post_caption = self._instagram_post_caption_for_asset(asset, caption_context if isinstance(caption_context, dict) else {})
        caption_generation = json_load(asset.get("caption_generation_json"), {})
        if not isinstance(caption_generation, dict):
            caption_generation = {}
        latest_audit = self._latest_audit_for_asset(str(asset["id"]))
        trust_blockers, trust_statuses = self.content_trust_status_blockers(
            asset,
            latest_audit,
            caption_context if isinstance(caption_context, dict) else {},
        )
        blocking.extend(trust_blockers)
        discoverability_contract = self._discoverability_safe_content_contract(
            post_caption.get("instagram_post_caption"),
            post_caption.get("burned_caption_text"),
            asset.get("caption"),
            caption_generation.get("story_cta_text"),
            caption_generation.get("story_cta_target_url"),
        )
        media_path = str(asset.get("campaign_path") or asset.get("output_path") or "")
        media_items = [{
            "mediaPath": media_path,
            "mediaHash": asset.get("content_hash"),
            "mediaType": media_type,
            "componentIndex": 0,
        }]
        can_handoff = False
        legacy_handoff = None
        story_quality: dict[str, Any] | None = None
        story_style_approved = False
        if surface != "feed_carousel":
            if not media_path or not Path(media_path).exists():
                blocking.append("media_file_missing")
            if not asset.get("content_hash"):
                blocking.append("content_hash_missing")

        if surface == "reel":
            plan = self._latest_distribution_plan_for_asset(asset["id"])
            publishability = self._explain_publishability(asset["id"], distribution_plan_id=plan["id"] if plan else None)
            legacy_handoff = publishability.get("handoff_manifest")
            if not publishability.get("publishableCandidate"):
                blocking.extend(str(reason) for reason in publishability.get("publishability_failure_reasons") or ["publishability_blocked"])
            if not legacy_handoff:
                blocking.append("handoff_manifest_missing")
            if media_type != "video":
                blocking.append("reel_requires_video")
            if self.requires_operator_visual_review_for_handoff(asset):
                blocking.append("operator_visual_review_required")
            can_handoff = not blocking
        elif surface == "story":
            if media_type not in {"image", "video"}:
                blocking.append("story_requires_image_or_video")
            if not self.aspect_ratio_safe(asset.get("target_ratio"), "story"):
                blocking.append("story_aspect_ratio_not_safe")
            story_quality = self._story_quality_gate_for_asset(asset)
            style = self._story_style_value(asset)
            story_asset_class = str(asset.get("story_asset_class") or caption_generation.get("story_asset_class") or "").strip()
            story_intent = self._story_intent_value(asset)
            story_style_approved = bool(style in self._story_native_proof_styles and (story_asset_class or story_intent))
            if not story_style_approved:
                blocking.append("story_style_not_approved")
            if not story_quality.get("story_quality_gate_passed"):
                blocking.append("story_quality_gate_failed")
                blocking.extend(str(reason) for reason in story_quality.get("failureReasons") or [])
            can_handoff = not blocking
        elif surface == "feed_single":
            if media_type != "image":
                blocking.append("feed_single_requires_image")
            if not self.aspect_ratio_safe(asset.get("target_ratio"), "feed_single"):
                blocking.append("feed_single_aspect_ratio_not_safe")
            if not post_caption.get("instagram_post_caption") and not self.allows_blank_instagram_post_caption(asset):
                blocking.append("instagram_post_caption_missing")
            can_handoff = not blocking
        elif surface == "feed_carousel":
            components = self.asset_components(asset["id"])
            media_items = [
                {
                    "mediaPath": item["media_path"],
                    "mediaHash": item["media_hash"],
                    "mediaType": item["media_type"],
                    "componentIndex": item["component_index"],
                }
                for item in components
            ]
            if not (2 <= len(components) <= 10):
                blocking.append("carousel_requires_2_to_10_components")
            indexes = [int(item["component_index"]) for item in components]
            if indexes != list(range(len(components))):
                blocking.append("carousel_components_not_ordered")
            for item in components:
                if item["media_type"] not in {"image", "video"}:
                    blocking.append("carousel_component_media_invalid")
                if not Path(item["media_path"]).exists():
                    blocking.append("carousel_component_media_missing")
                if str(item["publishability_state"] or "").lower() not in {"passed", "pass", "ready", "approved"}:
                    blocking.append("carousel_component_publishability_failed")
            if components and not self.aspect_ratio_safe(components[0]["aspect_ratio"], "feed_carousel"):
                blocking.append("carousel_cover_aspect_ratio_not_safe")
            if not post_caption.get("instagram_post_caption") and not self.allows_blank_instagram_post_caption(asset):
                blocking.append("instagram_post_caption_missing")
            can_handoff = not blocking
        else:
            blocking.append("unsupported_content_surface")

        if not discoverability_contract["discoverabilitySafe"]:
            blocking.append("discoverability_safety_failed")
            warnings.append(discoverability_contract["blockedReason"])
            can_handoff = False

        ig_media_type = self.ig_media_type_for_surface(surface, media_type)
        manifest_v2 = None
        if can_handoff:
            manifest_v2 = {
                "manifest_version": 2,
                "asset_id": asset["id"],
                "rendered_asset_id": asset["id"],
                "source_asset_id": asset.get("source_asset_id"),
                "content_fingerprint": asset.get("content_hash"),
                "content_hash": asset.get("content_hash"),
                "caption_hash": asset.get("caption_hash"),
                "contentSurface": surface,
                "content_surface": surface,
                "igMediaType": ig_media_type,
                "ig_media_type": ig_media_type,
                "mediaItems": media_items,
                "instagramPostCaption": post_caption.get("instagram_post_caption") or "",
                "instagram_post_caption": post_caption.get("instagram_post_caption") or "",
                "instagram_post_caption_hash": post_caption.get("instagram_post_caption_hash"),
                "hashtags": post_caption.get("hashtags") or [],
                "post_caption_style": post_caption.get("post_caption_style"),
                "visualQcStatus": trust_statuses["visualQcStatus"],
                "identityVerificationStatus": trust_statuses["identityVerificationStatus"],
                "visualQc": {"status": trust_statuses["visualQcStatus"]},
                "identityVerification": {"status": trust_statuses["identityVerificationStatus"]},
                "exported_by_system": "campaign_factory",
                "exported_at": utc_now(),
                "surfaceReadiness": {
                    "canHandoff": True,
                    "blockingReasons": [],
                    "warnings": warnings,
                },
                "discoverabilitySafe": discoverability_contract["discoverabilitySafe"],
                "discoverabilityContract": discoverability_contract,
            }
            if surface == "story" and story_quality is not None:
                manifest_v2.update({
                    "storyQualityGatePassed": bool(story_quality.get("storyQualityGatePassed")),
                    "storySourceNative": bool(story_quality.get("storySourceNative")),
                    "storyNoTextRequired": bool(story_quality.get("storyNoTextRequired")),
                    "storyNoTextPassed": bool(story_quality.get("storyNoTextPassed")),
                    "storyStyleApproved": bool(story_style_approved),
                    "sourceLineageBlockers": story_quality.get("sourceLineageBlockers") or [],
                    "visualQualityStatus": story_quality.get("visualQualityStatus") or "passed",
                })
        return {
            "assetId": asset["id"],
            "contentSurface": surface,
            "igMediaType": ig_media_type,
            "mediaType": media_type,
            "canHandoff": bool(can_handoff),
            "scheduleSafe": bool(can_handoff),
            "blockingReasons": sorted(set(blocking)),
            "warnings": sorted(set(warnings)),
            "visualQcStatus": trust_statuses["visualQcStatus"],
            "identityVerificationStatus": trust_statuses["identityVerificationStatus"],
            "discoverabilitySafe": discoverability_contract["discoverabilitySafe"],
            "discoverabilityContract": discoverability_contract,
            "storyQuality": story_quality,
            "storyStyleApproved": story_style_approved if surface == "story" else None,
            "handoffManifestV2": manifest_v2,
            "handoffManifest": legacy_handoff,
            "wouldWrite": False,
        }

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

    def asset_components(self, rendered_asset_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM asset_components WHERE asset_id = ? ORDER BY component_index",
            (rendered_asset_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def ig_media_type_for_surface(self, surface: str, media_type: str) -> str:
        return self._ig_media_type_by_surface.get(surface, "REELS")

    def aspect_ratio_safe(self, ratio: Any, surface: str) -> bool:
        text = str(ratio or "").strip()
        if not text:
            return True
        safe = {
            "story": {"9:16", "4:5", "1:1"},
            "feed_single": {"1:1", "4:5", "1.91:1", "9:16"},
            "feed_carousel": {"1:1", "4:5", "1.91:1", "9:16"},
        }
        return text in safe.get(surface, {text})

    def allows_blank_instagram_post_caption(self, asset: dict[str, Any]) -> bool:
        generation = json_load(asset.get("caption_generation_json"), {})
        if not isinstance(generation, dict):
            return False
        return self._truthy(generation.get("allow_empty_instagram_post_caption") or generation.get("allowEmptyInstagramPostCaption"))
