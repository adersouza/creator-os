from __future__ import annotations

import sqlite3
from typing import Any, Callable


class CarouselIntegrityRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        slugify: Callable[[str], str],
        creator_label: Callable[[Any], str],
        normalize_content_surface: Callable[[str | None], str],
        surface_report_assets: Callable[..., list[dict[str, Any]]],
        surface_handoff_readiness_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        surface_draft_proof: Callable[..., dict[str, Any]],
        surface_readiness_scorecard: Callable[[], dict[str, Any]],
        asset_components: Callable[[str], list[dict[str, Any]]],
    ) -> None:
        self.conn = conn
        self._slugify = slugify
        self._creator_label = creator_label
        self._normalize_content_surface = normalize_content_surface
        self._surface_report_assets = surface_report_assets
        self._surface_handoff_readiness_for_asset = surface_handoff_readiness_for_asset
        self._surface_draft_proof = surface_draft_proof
        self._surface_readiness_scorecard = surface_readiness_scorecard
        self._asset_components = asset_components

    def carousel_integrity_report(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        assets = self.carousel_report_assets(
            creator=self._creator_label(creator) if creator else None,
            campaign_slug=campaign_slug,
            rendered_asset_id=rendered_asset_id,
        )
        rows = [self.carousel_integrity_for_asset(asset) for asset in assets]
        return {
            "schema": "campaign_factory.carousel_integrity_report.v1",
            "creator": self._creator_label(creator) if creator else None,
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "renderedAssetId": rendered_asset_id,
            "carouselAssetsAnalyzed": len(rows),
            "passed": sum(1 for row in rows if row.get("overallIntegrityPassed")),
            "failed": sum(1 for row in rows if not row.get("overallIntegrityPassed")),
            "assets": rows,
            "wouldWrite": False,
        }

    def carousel_child_metrics_plan(
        self,
        *,
        creator: str | None = None,
        campaign_slug: str | None = None,
        rendered_asset_id: str | None = None,
    ) -> dict[str, Any]:
        assets = self.carousel_report_assets(
            creator=self._creator_label(creator) if creator else None,
            campaign_slug=campaign_slug,
            rendered_asset_id=rendered_asset_id,
        )
        rows = []
        for asset in assets:
            integrity = self.carousel_integrity_for_asset(asset)
            children = []
            for component in integrity["assetComponents"]["components"]:
                children.append({
                    "renderedAssetId": asset["id"],
                    "componentIndex": component["componentIndex"],
                    "componentHash": component["mediaHash"],
                    "mediaType": component["mediaType"],
                    "contentSurface": "feed_carousel",
                    "futureMetricKeys": {
                        "rendered_asset_id": asset["id"],
                        "carousel_child_index": component["componentIndex"],
                        "carousel_child_hash": component["mediaHash"],
                        "content_surface": "feed_carousel",
                    },
                    "wouldWrite": False,
                })
            rows.append({
                "assetId": asset["id"],
                "contentSurface": "feed_carousel",
                "igMediaType": "CAROUSEL",
                "childCount": len(children),
                "parentMetricsCanonical": True,
                "parentMetricKeys": [
                    "post_id",
                    "rendered_asset_id",
                    "content_surface",
                    "views",
                    "reach",
                    "likes",
                    "comments",
                    "shares",
                    "saves",
                ],
                "childMetricsSupplemental": True,
                "childMetricsPlan": children,
                "metricsRollupKeys": [
                    "rendered_asset_id",
                    "carousel_child_index",
                    "carousel_child_hash",
                    "content_surface",
                ],
                "integrityPassed": bool(integrity.get("overallIntegrityPassed")),
                "wouldWrite": False,
            })
        return {
            "schema": "campaign_factory.carousel_child_metrics_plan.v1",
            "creator": self._creator_label(creator) if creator else None,
            "campaign": self._slugify(campaign_slug) if campaign_slug else None,
            "renderedAssetId": rendered_asset_id,
            "carouselAssetsAnalyzed": len(rows),
            "assets": rows,
            "wouldWrite": False,
        }

    def carousel_report_assets(
        self,
        *,
        creator: str | None,
        campaign_slug: str | None,
        rendered_asset_id: str | None,
    ) -> list[dict[str, Any]]:
        assets = self._surface_report_assets(creator=creator, campaign_slug=campaign_slug)
        rows = [
            asset for asset in assets
            if self._normalize_content_surface(asset.get("content_surface") or asset.get("source_content_surface")) == "feed_carousel"
        ]
        if rendered_asset_id:
            rows = [asset for asset in rows if asset["id"] == rendered_asset_id]
        return rows

    def carousel_integrity_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        components = self.carousel_component_signature(self._asset_components(asset["id"]))
        readiness = self._surface_handoff_readiness_for_asset(asset)
        manifest = readiness.get("handoffManifestV2") if isinstance(readiness.get("handoffManifestV2"), dict) else {}
        manifest_items = manifest.get("mediaItems") if isinstance(manifest.get("mediaItems"), list) else []
        manifest_signature = self.carousel_media_item_signature(manifest_items)
        draft_proof = self._surface_draft_proof(
            creator=asset.get("creator_mix") or asset.get("creator_model") or asset.get("model_name"),
            campaign=asset.get("campaign_slug"),
            rendered_asset_id=asset["id"],
        )
        draft = draft_proof["drafts"][0] if draft_proof.get("drafts") else {}
        draft_signature = self.carousel_media_item_signature(draft.get("mediaItems") if isinstance(draft, dict) else [])
        threadsdash_signature = self.carousel_media_item_signature(
            (draft.get("handoffManifestV2") or {}).get("mediaItems")
            if isinstance(draft.get("handoffManifestV2"), dict)
            else []
        )
        meta_preview = self.carousel_meta_child_payload_preview(asset=asset, draft=draft, components=components)
        meta_signature = self.carousel_media_item_signature(meta_preview.get("children") or [])
        caption_lineage_preserved = bool(
            manifest.get("instagramPostCaption")
            and manifest.get("caption_hash")
            and (draft.get("handoffManifestV2") or {}).get("caption_hash") == manifest.get("caption_hash")
        )
        content_surface_preserved = (
            readiness.get("contentSurface") == "feed_carousel"
            and manifest.get("contentSurface") == "feed_carousel"
            and draft.get("contentSurface") == "feed_carousel"
            and draft.get("igMediaType") == "CAROUSEL"
            and meta_preview.get("parentPayload", {}).get("media_type") == "CAROUSEL"
        )
        boundaries = [
            self.carousel_boundary_result("asset_components_to_handoff_manifest_v2", components, manifest_signature),
            self.carousel_boundary_result("handoff_manifest_v2_to_surface_draft_proof", manifest_signature, draft_signature),
            self.carousel_boundary_result("surface_draft_proof_to_threadsdash_payload", draft_signature, threadsdash_signature),
            self.carousel_boundary_result("threadsdash_payload_to_meta_child_payload_preview", threadsdash_signature, meta_signature),
        ]
        return {
            "assetId": asset["id"],
            "contentSurface": self._normalize_content_surface(asset.get("content_surface") or asset.get("source_content_surface")),
            "igMediaType": readiness.get("igMediaType"),
            "canHandoff": bool(readiness.get("canHandoff")),
            "contentSurfacePreserved": bool(content_surface_preserved),
            "captionLineagePreserved": bool(caption_lineage_preserved),
            "assetComponents": self.carousel_signature_payload(components),
            "handoffManifestV2": self.carousel_signature_payload(manifest_signature, extra={
                "contentSurface": manifest.get("contentSurface"),
                "igMediaType": manifest.get("igMediaType"),
                "captionHash": manifest.get("caption_hash"),
                "instagramPostCaptionHash": manifest.get("instagram_post_caption_hash"),
            }),
            "surfaceDraftProof": self.carousel_signature_payload(draft_signature, extra={
                "canProduceDraftPayload": bool(draft_proof.get("canProduceDraftPayload")),
                "draftCount": int(draft_proof.get("draftCount") or 0),
            }),
            "threadDashPayload": self.carousel_signature_payload(threadsdash_signature, extra={
                "schema": draft.get("schema"),
                "contentSurface": draft.get("contentSurface"),
                "igMediaType": draft.get("igMediaType"),
            }),
            "metaChildPayloadPreview": self.carousel_signature_payload(meta_signature, extra=meta_preview),
            "boundaries": boundaries,
            "overallIntegrityPassed": bool(
                readiness.get("canHandoff")
                and content_surface_preserved
                and caption_lineage_preserved
                and boundaries
                and all(
                    boundary["slideCountPreserved"]
                    and boundary["slideOrderPreserved"]
                    and boundary["componentHashesMatch"]
                    for boundary in boundaries
                )
            ),
            "wouldWrite": False,
        }

    def carousel_component_signature(self, components: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "componentIndex": int(component.get("component_index") or 0),
                "mediaPath": component.get("media_path"),
                "mediaHash": component.get("media_hash"),
                "mediaType": component.get("media_type"),
            }
            for component in components
        ]

    def carousel_media_item_signature(self, media_items: Any) -> list[dict[str, Any]]:
        if not isinstance(media_items, list):
            return []
        rows = []
        for item in media_items:
            if not isinstance(item, dict):
                continue
            rows.append({
                "componentIndex": int(item.get("componentIndex") if item.get("componentIndex") is not None else item.get("component_index") or 0),
                "mediaPath": item.get("mediaPath") or item.get("media_path"),
                "mediaHash": item.get("mediaHash") or item.get("media_hash") or item.get("componentHash"),
                "mediaType": item.get("mediaType") or item.get("media_type"),
            })
        return rows

    def carousel_signature_payload(self, signature: list[dict[str, Any]], *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "slideCount": len(signature),
            "componentIndexes": [item["componentIndex"] for item in signature],
            "componentHashes": [item["mediaHash"] for item in signature],
            "components": signature,
        }
        if extra:
            payload.update(extra)
        return payload

    def carousel_boundary_result(self, boundary: str, before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
        before_indexes = [item["componentIndex"] for item in before]
        after_indexes = [item["componentIndex"] for item in after]
        before_hashes = [item["mediaHash"] for item in before]
        after_hashes = [item["mediaHash"] for item in after]
        return {
            "boundary": boundary,
            "slideCountPreserved": len(before) == len(after),
            "slideOrderPreserved": before_indexes == after_indexes,
            "componentHashesMatch": before_hashes == after_hashes,
            "beforeComponentIndexes": before_indexes,
            "afterComponentIndexes": after_indexes,
            "beforeComponentHashes": before_hashes,
            "afterComponentHashes": after_hashes,
            "wouldWrite": False,
        }

    def carousel_meta_child_payload_preview(self, *, asset: dict[str, Any], draft: dict[str, Any], components: list[dict[str, Any]]) -> dict[str, Any]:
        children = []
        for component in components:
            media_type = "VIDEO" if str(component.get("mediaType") or "").lower() == "video" else "IMAGE"
            children.append({
                "componentIndex": component["componentIndex"],
                "mediaPath": component["mediaPath"],
                "mediaHash": component["mediaHash"],
                "mediaType": component["mediaType"],
                "media_type": media_type,
                "is_carousel_item": True,
                "previewContainerId": f"carousel_child_preview_{asset['id']}_{component['componentIndex']}",
                "wouldWrite": False,
            })
        return {
            "parentPayload": {
                "media_type": "CAROUSEL",
                "caption": draft.get("instagramPostCaption") or "",
                "children": [child["previewContainerId"] for child in children],
            },
            "children": children,
            "wouldWrite": False,
        }

    def carousel_certification_proof(self, *, rendered_asset_id: str | None = None) -> dict[str, Any]:
        asset = self.certification_asset_for_surface("feed_carousel", rendered_asset_id=rendered_asset_id)
        blockers: list[str] = []
        if not asset:
            blockers.append("carousel_asset_missing")
            return {
                "schema": "creator_os.carousel_certification_proof.v1",
                "carouselCreated": False,
                "carouselValidated": False,
                "carouselPublished": False,
                "slideOrderPreserved": False,
                "slideHashesPreserved": False,
                "parentMetricsImported": False,
                "lifecycleReconciled": False,
                "status": "blocked",
                "blockers": blockers,
                "audit": self.empty_surface_certification_audit("feed_carousel"),
                "wouldWrite": False,
            }
        readiness = self._surface_handoff_readiness_for_asset(asset)
        draft = self._surface_draft_proof(
            creator=asset.get("creator_mix") or asset.get("creator_model") or asset.get("model_name"),
            campaign=asset.get("campaign_slug"),
            rendered_asset_id=asset["id"],
        )
        draft_payload = draft["drafts"][0] if draft.get("drafts") else {}
        integrity = self.carousel_integrity_for_asset(asset)
        proof_run = self.latest_proof_run_for_asset(asset["id"])
        metrics = self.latest_surface_metric_for_asset(asset["id"], "feed_carousel")
        created = self._normalize_content_surface(asset.get("content_surface") or asset.get("source_content_surface")) == "feed_carousel"
        validated = bool(readiness.get("canHandoff") and draft.get("canProduceDraftPayload") and integrity.get("overallIntegrityPassed"))
        published = bool(
            metrics
            or (
                proof_run
                and proof_run.get("threadsdash_post_id")
                and str(proof_run.get("current_state") or "").lower()
                in {"published", "metrics_imported", "complete", "completed"}
            )
        )
        boundaries = integrity.get("boundaries") if isinstance(integrity.get("boundaries"), list) else []
        slide_order = bool(boundaries and all(boundary.get("slideOrderPreserved") for boundary in boundaries))
        slide_hashes = bool(boundaries and all(boundary.get("componentHashesMatch") for boundary in boundaries))
        metrics_imported = bool(metrics)
        if not validated:
            blockers.append("carousel_validation_failed")
            blockers.extend(str(reason) for reason in readiness.get("blockingReasons") or [])
        if not published:
            blockers.append("carousel_publish_evidence_missing")
        if not slide_order:
            blockers.append("carousel_slide_order_not_certified")
        if not slide_hashes:
            blockers.append("carousel_slide_hashes_not_certified")
        if not metrics_imported:
            blockers.append("carousel_parent_metrics_evidence_missing")
        lifecycle = bool(created and validated and published and slide_order and slide_hashes and metrics_imported)
        return {
            "schema": "creator_os.carousel_certification_proof.v1",
            "carouselCreated": bool(created),
            "carouselValidated": bool(validated),
            "carouselPublished": bool(published),
            "slideOrderPreserved": slide_order,
            "slideHashesPreserved": slide_hashes,
            "parentMetricsImported": metrics_imported,
            "lifecycleReconciled": lifecycle,
            "status": "passed" if lifecycle else "blocked",
            "blockers": sorted(set(blockers)),
            "audit": self.surface_certification_audit(
                asset=asset,
                readiness=readiness,
                draft_payload=draft_payload,
                proof_run=proof_run,
                metrics=metrics,
                carousel_integrity=integrity,
            ),
            "wouldWrite": False,
        }

    def certification_asset_for_surface(self, surface: str, *, rendered_asset_id: str | None = None) -> dict[str, Any] | None:
        params: list[Any] = []
        where = ["COALESCE(r.content_surface, s.content_surface) = ?"]
        params.append(self._normalize_content_surface(surface))
        if rendered_asset_id:
            where.append("r.id = ?")
            params.append(rendered_asset_id)
        query = """
            SELECT r.*, c.slug AS campaign_slug, s.media_type AS source_media_type,
                   s.content_surface AS source_content_surface, m.slug AS model_slug, m.name AS model_name
            FROM rendered_assets r
            JOIN campaigns c ON c.id = r.campaign_id
            JOIN source_assets s ON s.id = r.source_asset_id
            JOIN models m ON m.id = s.model_id
            WHERE """ + " AND ".join(where) + """
            ORDER BY
              EXISTS(SELECT 1 FROM performance_snapshots p WHERE p.rendered_asset_id = r.id AND p.content_surface = COALESCE(r.content_surface, s.content_surface)) DESC,
              EXISTS(SELECT 1 FROM proof_runs pr WHERE pr.rendered_asset_id = r.id AND pr.threadsdash_post_id IS NOT NULL) DESC,
              r.created_at DESC,
              r.id DESC
            LIMIT 1
        """
        row = self.conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def latest_proof_run_for_asset(self, rendered_asset_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM proof_runs
            WHERE rendered_asset_id = ?
            ORDER BY COALESCE(completed_at, updated_at, started_at, created_at) DESC, id DESC
            LIMIT 1
            """,
            (rendered_asset_id,),
        ).fetchone()
        return dict(row) if row else None

    def latest_surface_metric_for_asset(self, rendered_asset_id: str, surface: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM performance_snapshots
            WHERE rendered_asset_id = ? AND content_surface = ?
            ORDER BY snapshot_at DESC, created_at DESC, id DESC
            LIMIT 1
            """,
            (rendered_asset_id, self._normalize_content_surface(surface)),
        ).fetchone()
        return dict(row) if row else None

    def empty_surface_certification_audit(self, surface: str) -> dict[str, Any]:
        return {
            "contentSurface": self._normalize_content_surface(surface),
            "manifestV2": {},
            "mediaRequirements": {"passed": False},
            "publishPayload": {},
            "metricsPayload": {},
            "lifecycle": {},
            "wouldWrite": False,
        }

    def surface_certification_audit(
        self,
        *,
        asset: dict[str, Any],
        readiness: dict[str, Any],
        draft_payload: dict[str, Any],
        proof_run: dict[str, Any] | None,
        metrics: dict[str, Any] | None,
        carousel_integrity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manifest = readiness.get("handoffManifestV2") if isinstance(readiness.get("handoffManifestV2"), dict) else {}
        metrics_payload = {
            "postId": metrics.get("post_id"),
            "contentSurface": metrics.get("content_surface"),
            "snapshotAt": metrics.get("snapshot_at"),
            "views": metrics.get("views"),
            "reach": metrics.get("reach"),
        } if metrics else {}
        return {
            "contentSurface": readiness.get("contentSurface"),
            "igMediaType": readiness.get("igMediaType"),
            "manifestV2": {
                "present": bool(manifest),
                "contentSurface": manifest.get("contentSurface"),
                "igMediaType": manifest.get("igMediaType"),
                "mediaItems": manifest.get("mediaItems") or [],
            },
            "mediaRequirements": {
                "passed": bool(readiness.get("canHandoff")),
                "blockingReasons": readiness.get("blockingReasons") or [],
                "mediaType": readiness.get("mediaType"),
            },
            "publishPayload": {
                "present": bool(draft_payload),
                "contentSurface": draft_payload.get("contentSurface"),
                "igMediaType": draft_payload.get("igMediaType"),
                "mediaItems": draft_payload.get("mediaItems") or [],
                "threadDashCompatible": bool(draft_payload.get("schema") == "threadsdash.surface_draft.preview.v1"),
            },
            "metricsPayload": metrics_payload,
            "lifecycle": {
                "proofRunId": proof_run.get("id") if proof_run else None,
                "currentState": proof_run.get("current_state") if proof_run else None,
                "status": proof_run.get("status") if proof_run else None,
                "threadsdashDraftId": proof_run.get("threadsdash_draft_id") if proof_run else None,
                "threadsdashPostId": proof_run.get("threadsdash_post_id") if proof_run else None,
                "metricsEligible": bool((proof_run or {}).get("metrics_eligible")),
            },
            "carouselIntegrity": carousel_integrity or {},
            "asset": {
                "assetId": asset.get("id"),
                "campaign": asset.get("campaign_slug"),
                "contentHash": asset.get("content_hash"),
                "captionHash": asset.get("caption_hash"),
            },
            "wouldWrite": False,
        }

    def carousel_production_readiness(self) -> dict[str, Any]:
        scorecard = self._surface_readiness_scorecard()
        carousel = (scorecard.get("surfaces") or {}).get("feed_carousel", {})
        return {
            "schema": "creator_os.carousel_production_readiness.v1",
            "publishProofMissing": not bool(carousel.get("publishProof")),
            "metricsProofMissing": not bool(carousel.get("metricsProof")),
            "blockingContracts": list(carousel.get("blockers") or []),
            "rating": carousel.get("rating", 0),
            "wouldWrite": False,
        }

    def carousel_proof_gap_analysis(self) -> dict[str, Any]:
        readiness = self.carousel_production_readiness()
        return {
            **readiness,
            "schema": "creator_os.carousel_proof_gap_analysis.v1",
            "nextProofsRequired": ["carousel_publish_proof", "carousel_metrics_proof"]
            if readiness["publishProofMissing"] or readiness["metricsProofMissing"]
            else [],
            "wouldWrite": False,
        }
