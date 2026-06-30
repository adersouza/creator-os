from __future__ import annotations

import hashlib
import math
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .persistence import json_load, utc_now

WINNER_EXPANSION_OPERATION_FAMILIES = [
    "cover_frame",
    "timing_trim",
    "caption_lane_timing",
    "crop_zoom_family",
    "color_profile",
    "audio_offset",
]
WINNER_EXPANSION_THRESHOLDS = {
    "qualityScore": 90,
    "captionReadabilityScore": 95,
    "focalSafetyScore": 95,
    "operationDiversityScore": 25,
    "differenceScore": 20,
}


class WinnerExpansionRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        campaign_by_slug: Callable[[str], dict[str, Any]],
        rendered_asset: Callable[[str], dict[str, Any]],
        concept_for_parent_asset: Callable[[str], dict[str, Any] | None],
        explain_publishability: Callable[[str], dict[str, Any]],
        creator_label: Callable[[Any], str],
        concept_payload: Callable[
            [sqlite3.Row | dict[str, Any] | None], dict[str, Any]
        ],
    ) -> None:
        self.conn = conn
        self._campaign_by_slug = campaign_by_slug
        self._rendered_asset = rendered_asset
        self._concept_for_parent_asset = concept_for_parent_asset
        self._explain_publishability = explain_publishability
        self._creator_label = creator_label
        self._concept_payload = concept_payload

    def winner_expansion_plan(
        self,
        *,
        creator: str | None = None,
        parent_asset_id: str,
        target_variants: int = 10,
        preset: str = "caption_safe_v2",
    ) -> dict[str, Any]:
        target = max(1, min(30, int(target_variants or 10)))
        contentforge_preset = (
            preset
            if preset in {"caption_safe_v2", "strong_safe"}
            else "caption_safe_v2"
        )
        parent = self._rendered_asset(parent_asset_id)
        concept = self._concept_for_parent_asset(parent_asset_id)
        can_proceed = concept is not None and bool(
            self._explain_publishability(parent_asset_id).get("publishableCandidate")
        )
        family_row = self.conn.execute(
            """
            SELECT * FROM variant_families
            WHERE parent_asset_id = ? AND contentforge_preset = ?
            ORDER BY created_at, id
            LIMIT 1
            """,
            (parent_asset_id, contentforge_preset),
        ).fetchone()
        camp_id = parent.get("campaign_id", "")
        variant_family_id = (
            family_row["id"]
            if family_row
            else f"vfam_{hashlib.sha256(f'{camp_id}:{parent_asset_id}:{contentforge_preset}:winner_expansion'.encode()).hexdigest()[:12]}"
        )
        rows = self.conn.execute(
            """
            SELECT * FROM variant_assets
            WHERE parent_asset_id = ?
            ORDER BY variant_index, created_at, id
            """,
            (parent_asset_id,),
        ).fetchall()
        valid_existing: list[dict[str, Any]] = []
        rejected = {"lowQuality": 0, "duplicateSiblings": 0, "notUploadReady": 0}
        seen_fingerprints: set[str] = set()
        seen_families: set[str] = set()
        for row in rows:
            payload = self.variant_asset_payload(row)
            rendered = self._rendered_asset(payload["variantAssetId"])
            candidate = self.winner_variant_candidate(payload, rendered)
            family_name = str(candidate.get("familyName") or "unknown")
            fingerprint = str(
                candidate.get("contentFingerprint")
                or candidate.get("sourceFingerprint")
                or payload["variantAssetId"]
            )
            if fingerprint in seen_fingerprints or family_name in seen_families:
                rejected["duplicateSiblings"] += 1
                continue
            decision = self.winner_variant_candidate_decision(candidate)
            if not decision["recommended"]:
                if "not_upload_ready" in decision["blockingReasons"]:
                    rejected["notUploadReady"] += 1
                else:
                    rejected["lowQuality"] += 1
                continue
            seen_fingerprints.add(fingerprint)
            seen_families.add(family_name)
            valid_existing.append(candidate)
        recommended_new = max(0, target - len(valid_existing))
        missing_families = [
            family
            for family in WINNER_EXPANSION_OPERATION_FAMILIES
            if family not in seen_families
        ]
        operation_families: list[str] = []
        while len(operation_families) < recommended_new:
            source_families = (
                missing_families
                if missing_families
                else WINNER_EXPANSION_OPERATION_FAMILIES
            )
            for family in source_families:
                if len(operation_families) >= recommended_new:
                    break
                operation_families.append(family)
            missing_families = []
        return {
            "schema": "campaign_factory.winner_expansion_plan.v1",
            "creator": creator,
            "parentAssetId": parent_asset_id,
            "parentReelId": concept.get("parentReelId") if concept else None,
            "variantFamilyId": variant_family_id,
            "existingVariants": len(valid_existing),
            "recommendedNewVariants": recommended_new,
            "operationFamilies": operation_families,
            "canProceed": bool(can_proceed),
            "blockingReason": ""
            if can_proceed
            else "parent_reel_not_registered_or_not_publishable",
            "wouldWrite": False,
            "preset": contentforge_preset,
            "thresholds": dict(WINNER_EXPANSION_THRESHOLDS),
            "rejectedExistingVariants": rejected,
        }

    def variant_inventory_plan(
        self,
        *,
        creator: str,
        campaign: str,
        target_draft_shortfall: int,
        preset: str = "caption_safe_v2",
        max_variants_per_parent: int = 10,
        minimum_recommended_per_parent: int = 3,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        campaign_row = self._campaign_by_slug(campaign)
        target = max(0, int(target_draft_shortfall or 0))
        max_per_parent = max(1, min(30, int(max_variants_per_parent or 10)))
        minimum_recommended = max(1, int(minimum_recommended_per_parent or 1))
        contentforge_preset = (
            preset
            if preset in {"caption_safe_v2", "strong_safe"}
            else "caption_safe_v2"
        )
        creator_label = self._creator_label(creator)
        rows = self.conn.execute(
            """
            SELECT * FROM concepts
            WHERE campaign_id = ? AND status IN ('active', 'approved', 'winner')
            ORDER BY created_at, id
            """,
            (campaign_row["id"],),
        ).fetchall()
        candidates: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for row in rows:
            concept = self._concept_payload(row)
            asset = self._rendered_asset(concept["parentAssetId"])
            asset_creator = self._creator_label(
                concept.get("creator")
                or asset.get("creator_model")
                or asset.get("creator_mix")
            )
            if creator_label != "unknown" and asset_creator not in {
                creator_label,
                "unknown",
            }:
                continue
            publishability = self._explain_publishability(concept["parentAssetId"])
            checks = (
                publishability.get("checks")
                if isinstance(publishability.get("checks"), dict)
                else {}
            )
            existing_count = int(
                self.conn.execute(
                    "SELECT COUNT(*) AS c FROM variant_assets WHERE parent_asset_id = ?",
                    (concept["parentAssetId"],),
                ).fetchone()["c"]
            )
            base_row = {
                "parentAssetId": concept["parentAssetId"],
                "parentReelId": concept["parentReelId"],
                "conceptId": concept["conceptId"],
                "existingVariantCount": existing_count,
                "existingRecommendedVariantCount": 0,
                "estimatedNewRecommendedVariants": 0,
                "operationFamiliesAvailable": [],
                "qualityRisk": "high",
                "captionSafe": bool(
                    checks.get("captioned_render_present")
                    and checks.get("caption_placement_qc_passed")
                    and checks.get("readiness_checks_pass")
                ),
                "audioSafe": bool(
                    checks.get("audio_assigned")
                    and checks.get("embedded_audio_verified") is not False
                ),
                "instagramPostCaptionSafe": bool(
                    checks.get("instagram_post_caption_present")
                ),
                "reasonEligible": "",
                "wouldWrite": False,
            }
            if not publishability.get("publishableCandidate"):
                failures = list(
                    publishability.get("publishability_failure_reasons") or []
                )
                blocking_reason = self.variant_inventory_primary_blocking_reason(
                    failures
                )
                blocked.append(
                    {
                        **base_row,
                        "blockingReason": blocking_reason,
                        "publishabilityFailureReasons": failures,
                    }
                )
                continue
            expansion = self.winner_expansion_plan(
                creator=creator,
                parent_asset_id=concept["parentAssetId"],
                target_variants=max_per_parent,
                preset=contentforge_preset,
            )
            existing_recommended = int(expansion.get("existingVariants") or 0)
            estimated_new = min(
                max_per_parent,
                max(0, max_per_parent - existing_recommended),
                int(expansion.get("recommendedNewVariants") or 0),
            )
            if estimated_new <= 0:
                blocked.append(
                    {
                        **base_row,
                        "existingRecommendedVariantCount": existing_recommended,
                        "blockingReason": "variant_capacity_exhausted",
                        "publishabilityFailureReasons": [],
                    }
                )
                continue
            if estimated_new < minimum_recommended and target > 0:
                blocked.append(
                    {
                        **base_row,
                        "existingRecommendedVariantCount": existing_recommended,
                        "estimatedNewRecommendedVariants": estimated_new,
                        "operationFamiliesAvailable": list(
                            expansion.get("operationFamilies") or []
                        )[:estimated_new],
                        "blockingReason": "below_minimum_recommended_per_parent",
                        "publishabilityFailureReasons": [],
                    }
                )
                continue
            winner_rank = self.variant_inventory_winner_rank(
                campaign_id=campaign_row["id"],
                parent_asset_id=concept["parentAssetId"],
                parent_reel_id=concept["parentReelId"],
            )
            reason = (
                "winner_metrics"
                if winner_rank["hasWinnerMetrics"]
                else "manual_approved_parent_reel"
            )
            quality_risk = self.variant_inventory_quality_risk(concept["parentAssetId"])
            family_id = str(expansion.get("variantFamilyId") or "")
            parent_row = {
                **base_row,
                "existingRecommendedVariantCount": existing_recommended,
                "estimatedNewRecommendedVariants": estimated_new,
                "operationFamiliesAvailable": list(
                    expansion.get("operationFamilies") or []
                )[:estimated_new],
                "qualityRisk": quality_risk,
                "captionSafe": True,
                "audioSafe": True,
                "instagramPostCaptionSafe": True,
                "reasonEligible": reason,
                "variantFamilyId": family_id,
                "preset": contentforge_preset,
                "winnerMetrics": winner_rank["metrics"]
                if winner_rank["hasWinnerMetrics"]
                else {},
                "_sort": (
                    0 if winner_rank["hasWinnerMetrics"] else 1,
                    -int(winner_rank["score"]),
                    str(concept["parentAssetId"]),
                ),
            }
            candidates.append(parent_row)
        candidates.sort(key=lambda item: item["_sort"])
        remaining = target
        execution_batches: list[dict[str, Any]] = []
        planned_families: list[dict[str, Any]] = []
        estimated_total = 0
        for candidate in candidates:
            if remaining <= 0:
                break
            requested = min(
                int(candidate["estimatedNewRecommendedVariants"]), remaining
            )
            if requested <= 0:
                continue
            families = list(candidate.get("operationFamiliesAvailable") or [])[
                :requested
            ]
            batch = {
                "parentAssetId": candidate["parentAssetId"],
                "preset": contentforge_preset,
                "requestedVariants": requested,
                "minimumRecommended": minimum_recommended,
                "operationFamilies": families,
            }
            execution_batches.append(batch)
            planned_families.append(
                {
                    "parentAssetId": candidate["parentAssetId"],
                    "parentReelId": candidate["parentReelId"],
                    "conceptId": candidate["conceptId"],
                    "variantFamilyId": candidate["variantFamilyId"],
                    "preset": contentforge_preset,
                    "requestedVariants": requested,
                    "operationFamilies": families,
                    "wouldWrite": False,
                }
            )
            estimated_total += requested
            remaining -= requested
        eligible_parents = []
        for candidate in candidates:
            item = dict(candidate)
            item.pop("_sort", None)
            eligible_parents.append(item)
        missing = max(0, target - estimated_total)
        can_fill = missing == 0
        return {
            "schema": "campaign_factory.variant_inventory_plan.v1",
            "creator": creator,
            "campaign": campaign_row["slug"],
            "targetDraftShortfall": target,
            "eligibleParents": eligible_parents,
            "blockedParents": blocked,
            "plannedVariantFamilies": planned_families,
            "estimatedRecommendedVariants": estimated_total,
            "missingRecommendedVariants": missing,
            "canFillShortfall": can_fill,
            "blockingReason": ""
            if can_fill
            else f"insufficient_eligible_parent_inventory_missing_{missing}_variants",
            "nextSafeAction": "execute_contentforge_variant_batches"
            if can_fill
            else "create_or_import_more_parent_reels",
            "executionBatches": execution_batches,
            "preset": contentforge_preset,
            "maxVariantsPerParent": max_per_parent,
            "minimumRecommendedPerParent": minimum_recommended,
            "dryRun": bool(dry_run),
            "wouldWrite": False,
        }

    def winner_expansion_report(
        self,
        campaign_slug: str,
        *,
        min_views: int = 1000,
        min_reach: int | None = None,
        min_followers: int = 1,
    ) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        rows = self.conn.execute(
            """
            SELECT * FROM performance_snapshots
            WHERE campaign_id = ? AND metrics_eligible = 1
            ORDER BY snapshot_at DESC, created_at DESC
            """,
            (campaign["id"],),
        ).fetchall()
        reach_floor = min_reach if min_reach is not None else min_views
        winners = []
        seen_posts: set[str] = set()
        for row in rows:
            data = dict(row)
            post_id = data.get("post_id")
            if not post_id or str(post_id) in seen_posts:
                continue
            raw = json_load(data.get("raw_json"), {})
            metrics = {
                "views": int(data.get("views") or 0),
                "reach": int(data.get("reach") or 0),
                "followers": int(raw.get("followers") or 0)
                if isinstance(raw, dict)
                else 0,
                "likes": int(data.get("likes") or 0),
                "comments": int(data.get("comments") or 0),
                "shares": int(data.get("shares") or 0),
                "saves": int(data.get("saves") or 0),
            }
            reason = ""
            if metrics["views"] >= min_views:
                reason = "high_views"
            elif metrics["reach"] >= reach_floor:
                reason = "high_reach"
            elif metrics["followers"] >= min_followers:
                reason = "follower_growth"
            if not reason:
                continue
            seen_posts.add(str(post_id))
            winners.append(
                {
                    "postId": post_id,
                    "assetId": data.get("rendered_asset_id") or "",
                    "parentReelId": data.get("parent_reel_id") or "",
                    "variantFamilyId": data.get("variant_family_id") or "",
                    "reason": reason,
                    "recommendedAction": "create_more_variants"
                    if data.get("parent_reel_id")
                    else "make_similar_reel",
                    "wouldWrite": False,
                    "metrics": metrics,
                }
            )
        return {
            "schema": "campaign_factory.winner_expansion_report.v1",
            "campaign": campaign["slug"],
            "generatedAt": utc_now(),
            "minViews": min_views,
            "minReach": reach_floor,
            "minFollowers": min_followers,
            "wouldWrite": False,
            "manualReviewOnly": True,
            "winners": winners,
            "recommendations": winners,
            "summary": {"winnerCount": len(winners)},
        }

    def winner_variant_candidate(
        self, variant_payload: dict[str, Any], rendered: dict[str, Any]
    ) -> dict[str, Any]:
        operation_result = self.contentforge_result_from_operations(
            variant_payload.get("variantOperations") or []
        )
        audit_result = self.latest_variant_audit_result(
            variant_payload.get("variantAssetId") or ""
        )
        merged = {**operation_result, **audit_result}
        readiness = (
            merged.get("readinessSummary")
            if isinstance(merged.get("readinessSummary"), dict)
            else {}
        )
        return {
            "variantId": variant_payload.get("variantId"),
            "variantAssetId": variant_payload.get("variantAssetId"),
            "variantFamilyId": variant_payload.get("variantFamilyId"),
            "parentAssetId": variant_payload.get("parentAssetId"),
            "familyName": merged.get("familyName")
            or (merged.get("variantFamilyRecipe") or {}).get("familyName")
            or self.operation_family_from_operations(
                variant_payload.get("variantOperations") or []
            ),
            "uploadReady": bool(
                merged.get("uploadReady")
                if "uploadReady" in merged
                else readiness.get("uploadReady")
            ),
            "qualityScore": self.score_value(merged.get("qualityScore")),
            "captionReadabilityScore": self.score_value(
                merged.get("captionReadabilityScore")
            ),
            "focalSafetyScore": self.score_value(merged.get("focalSafetyScore")),
            "operationDiversityScore": self.score_value(
                merged.get("operationDiversityScore")
            ),
            "differenceScore": self.score_value(merged.get("differenceScore")),
            "contentFingerprint": variant_payload.get("contentFingerprint")
            or rendered.get("content_hash")
            or rendered.get("contentHash"),
            "sourceFingerprint": variant_payload.get("sourceFingerprint"),
        }

    def winner_variant_candidate_decision(
        self, candidate: dict[str, Any]
    ) -> dict[str, Any]:
        blocking: list[str] = []
        if candidate.get("uploadReady") is not True:
            blocking.append("not_upload_ready")
        for field, minimum in WINNER_EXPANSION_THRESHOLDS.items():
            if self.score_value(candidate.get(field)) < minimum:
                blocking.append(f"{field}_below_minimum")
        return {"recommended": not blocking, "blockingReasons": blocking}

    def latest_variant_audit_result(self, variant_asset_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM audit_reports WHERE rendered_asset_id = ? ORDER BY created_at DESC LIMIT 1",
            (variant_asset_id,),
        ).fetchone()
        if not row or not row["report_path"]:
            return {}
        try:
            report = json_load(Path(row["report_path"]).read_text(encoding="utf-8"), {})
        except OSError:
            return {}
        variant = (
            report.get("variant") if isinstance(report.get("variant"), dict) else {}
        )
        readiness = (
            report.get("readinessSummary")
            if isinstance(report.get("readinessSummary"), dict)
            else {}
        )
        return {**variant, "readinessSummary": readiness}

    def contentforge_result_from_operations(
        self, operations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            result = operation.get("result")
            if operation.get("type") == "contentforge_result" and isinstance(
                result, dict
            ):
                return result
        return {}

    def operation_family_from_operations(
        self, operations: list[dict[str, Any]]
    ) -> str | None:
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            family = operation.get("familyName")
            if family:
                return str(family)
            result = (
                operation.get("result")
                if isinstance(operation.get("result"), dict)
                else {}
            )
            family = result.get("familyName") or (
                result.get("variantFamilyRecipe") or {}
            ).get("familyName")
            if family:
                return str(family)
        return None

    def score_value(self, value: Any) -> int:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 0
        if not math.isfinite(parsed):
            return 0
        return max(0, min(100, int(round(parsed))))

    def variant_inventory_primary_blocking_reason(self, failures: list[str]) -> str:
        priority = [
            "quarantined_asset",
            "embedded_audio_missing",
            "missing_audio",
            "missing_instagram_post_caption",
            "caption_placement_qc_failed",
            "missing_burned_captions",
            "readiness_failed",
        ]
        for reason in priority:
            if reason in failures:
                return reason
        return failures[0] if failures else "publishability_blocked"

    def variant_inventory_quality_risk(self, parent_asset_id: str) -> str:
        row = self.conn.execute(
            "SELECT score, status, overall_verdict FROM audit_reports WHERE rendered_asset_id = ? ORDER BY created_at DESC LIMIT 1",
            (parent_asset_id,),
        ).fetchone()
        if not row:
            return "high"
        score = self.score_value(row["score"])
        if row["overall_verdict"] == "fail" or row["status"] not in {
            "pass",
            "approved_candidate",
        }:
            return "high"
        if score >= WINNER_EXPANSION_THRESHOLDS["qualityScore"]:
            return "low"
        if score >= 80:
            return "medium"
        return "high"

    def variant_inventory_winner_rank(
        self,
        *,
        campaign_id: str,
        parent_asset_id: str,
        parent_reel_id: str,
    ) -> dict[str, Any]:
        rows = self.conn.execute(
            """
            SELECT * FROM performance_snapshots
            WHERE campaign_id = ?
              AND metrics_eligible = 1
              AND (rendered_asset_id = ? OR parent_reel_id = ?)
            ORDER BY snapshot_at DESC, created_at DESC
            """,
            (campaign_id, parent_asset_id, parent_reel_id),
        ).fetchall()
        best_score = 0
        best_metrics: dict[str, int] = {}
        for row in rows:
            data = dict(row)
            raw = json_load(data.get("raw_json"), {})
            metrics = {
                "views": int(data.get("views") or 0),
                "reach": int(data.get("reach") or 0),
                "followers": int(raw.get("followers") or 0)
                if isinstance(raw, dict)
                else 0,
                "likes": int(data.get("likes") or 0),
                "comments": int(data.get("comments") or 0),
                "shares": int(data.get("shares") or 0),
                "saves": int(data.get("saves") or 0),
            }
            score = (
                metrics["views"]
                + metrics["reach"]
                + (metrics["followers"] * 100)
                + (metrics["likes"] * 5)
                + (metrics["comments"] * 10)
                + (metrics["shares"] * 15)
                + (metrics["saves"] * 15)
            )
            if score > best_score:
                best_score = score
                best_metrics = metrics
        return {
            "hasWinnerMetrics": best_score > 0,
            "score": best_score,
            "metrics": best_metrics,
        }

    def variant_asset_payload(
        self, row: sqlite3.Row | dict[str, Any] | None
    ) -> dict[str, Any]:
        if row is None:
            return {}
        data = dict(row)
        return {
            "variantId": data["id"],
            "campaignId": data["campaign_id"],
            "conceptId": data["concept_id"],
            "parentReelId": data["parent_reel_id"],
            "variantFamilyId": data["variant_family_id"],
            "variantIndex": data["variant_index"],
            "parentAssetId": data["parent_asset_id"],
            "captionFamilyId": data.get("caption_family_id"),
            "captionVersionId": data.get("caption_version_id"),
            "variantAssetId": data["variant_asset_id"],
            "sourceAssetId": data.get("source_asset_id"),
            "sourceFingerprint": data.get("source_fingerprint"),
            "contentFingerprint": data.get("content_fingerprint"),
            "captionHash": data.get("caption_hash"),
            "audioId": data.get("audio_id"),
            "variantOperations": json_load(data.get("operations_json"), []),
            "qcStatus": data.get("qc_status"),
            "contentforgeRunId": data.get("contentforge_run_id"),
        }
