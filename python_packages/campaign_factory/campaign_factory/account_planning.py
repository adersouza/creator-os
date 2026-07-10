from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from typing import Any

from .caption_outcome import load_context_json
from .persistence import json_load


class AccountPlanningRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        utc_now: Callable[[], str],
        campaign_by_slug: Callable[[str], dict[str, Any]],
        assignments_for_campaign: Callable[[str], list[dict[str, Any]]],
        assignments_for_asset: Callable[[str], list[dict[str, Any]]],
        distribution_plans_for_campaign: Callable[[str], list[dict[str, Any]]],
        account_compatible_with_model: Callable[
            ..., tuple[bool, str | None, dict[str, Any] | None]
        ],
        dashboard: Callable[[str], dict[str, Any]],
        ranking: Callable[[str], dict[str, Any]],
        rendered_for_campaign: Callable[[str], list[dict[str, Any]]],
        dashboard_rendered_asset: Callable[[dict[str, Any]], dict[str, Any]],
        active_reference_pattern_for_campaign: Callable[[str], dict[str, Any] | None],
        audio_recommendations_for_asset: Callable[..., dict[str, Any]],
        generated_asset_lineage: Callable[
            [dict[str, Any], dict[str, Any] | None], dict[str, Any]
        ],
        audit_report_payload: Callable[[dict[str, Any]], dict[str, Any]],
        performance_for_asset: Callable[[dict[str, Any]], dict[str, Any]],
        local_export_readiness: Callable[
            [dict[str, Any], dict[str, Any] | None], dict[str, Any]
        ],
        recommend_audio: Callable[..., dict[str, Any]],
        performance_quality_score: Callable[[dict[str, Any]], int | None],
    ) -> None:
        self.conn = conn
        self._utc_now = utc_now
        self._campaign_by_slug = campaign_by_slug
        self._assignments_for_campaign = assignments_for_campaign
        self._assignments_for_asset = assignments_for_asset
        self._distribution_plans_for_campaign = distribution_plans_for_campaign
        self._account_compatible_with_model = account_compatible_with_model
        self._dashboard = dashboard
        self._ranking = ranking
        self._rendered_for_campaign = rendered_for_campaign
        self._dashboard_rendered_asset = dashboard_rendered_asset
        self._active_reference_pattern_for_campaign = (
            active_reference_pattern_for_campaign
        )
        self._audio_recommendations_for_asset = audio_recommendations_for_asset
        self._generated_asset_lineage = generated_asset_lineage
        self._audit_report_payload = audit_report_payload
        self._performance_for_asset = performance_for_asset
        self._local_export_readiness = local_export_readiness
        self._recommend_audio = recommend_audio
        self._performance_quality_score = performance_quality_score

    def account_plan(
        self, campaign_slug: str, *, user_id: str, usage: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        payload_rows = []
        assignments = self._assignments_for_campaign(campaign_slug)
        assignment_by_asset: dict[str, list[dict[str, Any]]] = {}
        for assignment in assignments:
            assignment_by_asset.setdefault(assignment["rendered_asset_id"], []).append(
                assignment
            )
        distribution_by_asset: dict[str, list[dict[str, Any]]] = {}
        for plan in self._distribution_plans_for_campaign(campaign_slug):
            distribution_by_asset.setdefault(plan["renderedAssetId"], []).append(plan)
        usage_by_asset = {
            item["renderedAssetId"]: item for item in (usage or {}).get("assets", [])
        }
        for asset in self._dashboard(campaign_slug)["rendered"]:
            distribution_plans = distribution_by_asset.get(asset["id"]) or []
            if distribution_plans:
                destinations = [
                    {
                        "account_id": plan.get("accountId"),
                        "instagram_account_id": plan.get("instagramAccountId"),
                        "planned_window_start": plan.get("plannedWindowStart"),
                        "planned_window_end": plan.get("plannedWindowEnd"),
                        "notes": plan.get("reasonCode"),
                        "surface": plan.get("surface"),
                        "distribution_plan_id": plan.get("id"),
                        "smart_link": plan.get("smartLink"),
                        "cta_text": plan.get("ctaText"),
                    }
                    for plan in distribution_plans
                ]
            else:
                destinations = assignment_by_asset.get(asset["id"]) or []
            if not destinations:
                destinations = [
                    {
                        "account_id": None,
                        "instagram_account_id": None,
                        "planned_window_start": None,
                        "planned_window_end": None,
                        "notes": None,
                    }
                ]
            for destination in destinations:
                warnings = []
                asset_usage = usage_by_asset.get(asset["id"], {}).get("usage") or {}
                compatible, mismatch_reason, profile = (
                    self._account_compatible_with_model(
                        asset.get("model_slug") or asset.get("modelId") or "",
                        instagram_account_id=destination.get("instagram_account_id"),
                    )
                )
                if not compatible and mismatch_reason:
                    warnings.append(mismatch_reason)
                if asset_usage.get("published", 0) > 0:
                    warnings.append("exact_render_published")
                if (
                    asset_usage.get("draft", 0) > 0
                    or asset_usage.get("scheduled", 0) > 0
                ):
                    warnings.append("exact_render_already_queued")
                if (asset.get("export_readiness") or {}).get("state") == "warning":
                    warnings.append("asset_has_export_warnings")
                if (
                    asset.get("performanceScore") is not None
                    and asset["performanceScore"] < 45
                ):
                    warnings.append("weak_recent_performance")
                payload_rows.append(
                    {
                        "renderedAssetId": asset["id"],
                        "filename": asset["filename"],
                        "accountId": destination.get("account_id"),
                        "instagramAccountId": destination.get("instagram_account_id"),
                        "modelSlug": asset.get("model_slug") or asset.get("modelId"),
                        "accountProfile": profile,
                        "distributionPlanId": destination.get("distribution_plan_id"),
                        "distributionSurface": destination.get("surface")
                        or "regular_reel",
                        "plannedWindowStart": destination.get("planned_window_start"),
                        "plannedWindowEnd": destination.get("planned_window_end"),
                        "smartLink": destination.get("smart_link"),
                        "ctaText": destination.get("cta_text"),
                        "reviewState": asset["review_state"],
                        "exportState": (asset.get("export_readiness") or {}).get(
                            "state"
                        ),
                        "rankingScore": (
                            self._ranking(campaign_slug)["byAsset"].get(asset["id"])
                            or {}
                        ).get("score"),
                        "warnings": sorted(set(warnings)),
                    }
                )
        by_account: dict[str, int] = {}
        for row in payload_rows:
            account = row["instagramAccountId"] or row["accountId"] or "unassigned"
            by_account[account] = by_account.get(account, 0) + 1
        for row in payload_rows:
            account = row["instagramAccountId"] or row["accountId"] or "unassigned"
            if by_account[account] > 2:
                row["warnings"].append("account_batch_volume_review")
        return {
            "schema": "campaign_factory.account_plan.v1",
            "campaign": campaign["slug"],
            "userId": user_id,
            "generatedAt": self._utc_now(),
            "assignments": assignments,
            "rows": payload_rows,
            "threadsdashAccountUsage": (usage or {}).get("accountUsage") or {},
            "threadsdashSurfaceUsage": (usage or {}).get("surfaceUsage") or {},
            "warnings": sorted(set(w for row in payload_rows for w in row["warnings"])),
        }

    def ranking(self, campaign_slug: str) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        rows = []
        for asset in [
            self._dashboard_rendered_asset(asset)
            for asset in self._rendered_for_campaign(campaign["id"])
        ]:
            readiness = asset.get("export_readiness") or {}
            blocked = bool(readiness.get("blockingReasons"))
            quality_score = self.quality_score_for_ranking(asset)
            source_score = self.history_score(asset.get("sourcePerformance"))
            caption_score = self.history_score(asset.get("captionPerformance"))
            recipe_score = self.history_score(asset.get("recipePerformance"))
            account_score = self.account_fit_score(asset)
            novelty_score = self.novelty_score(asset)
            score = round(
                quality_score * 0.30
                + source_score * 0.20
                + caption_score * 0.15
                + recipe_score * 0.15
                + account_score * 0.10
                + novelty_score * 0.10
            )
            if blocked:
                score = min(score, 35)
            reasons = []
            if blocked:
                reasons.append("blocked assets stay low regardless of performance")
            if source_score > 55:
                reasons.append("source family has positive history")
            if caption_score > 55:
                reasons.append("caption hash has positive history")
            if recipe_score > 55:
                reasons.append("recipe has positive history")
            if quality_score >= 85:
                reasons.append("strong audit/readiness quality")
            if novelty_score < 50:
                reasons.append("reuse/novelty warnings reduce score")
            rows.append(
                {
                    "renderedAssetId": asset["id"],
                    "filename": asset["filename"],
                    "reviewState": asset["review_state"],
                    "exportState": readiness.get("state"),
                    "score": int(max(0, min(100, score))),
                    "breakdown": {
                        "quality": quality_score,
                        "sourceHistory": source_score,
                        "captionHistory": caption_score,
                        "recipeHistory": recipe_score,
                        "accountFit": account_score,
                        "novelty": novelty_score,
                    },
                    "reasons": reasons
                    or ["neutral history; score is mostly quality/readiness based"],
                    "blockingReasons": readiness.get("blockingReasons") or [],
                    "warnings": readiness.get("warnings") or [],
                }
            )
        rows = sorted(rows, key=lambda row: row["score"], reverse=True)
        return {
            "schema": "campaign_factory.ranking.v1",
            "campaign": campaign["slug"],
            "generatedAt": self._utc_now(),
            "assets": rows,
            "byAsset": {row["renderedAssetId"]: row for row in rows},
        }

    def quality_score_for_ranking(self, asset: dict[str, Any]) -> int:
        readiness = asset.get("export_readiness") or {}
        audit = asset.get("latest_audit") or {}
        score = int(readiness.get("operatorScore") or 50)
        if audit.get("readabilityScore") is not None:
            score = round((score + int(audit["readabilityScore"])) / 2)
        if audit.get("safeZoneScore") is not None:
            score = round((score + int(audit["safeZoneScore"])) / 2)
        return max(0, min(100, score))

    def history_score(self, summary: dict[str, Any] | None) -> int:
        if not summary or not summary.get("count"):
            return 50
        score = self._performance_quality_score(summary)
        if score is None:
            return 45
        return int(max(35, min(100, score)))

    def account_fit_score(self, asset: dict[str, Any]) -> int:
        assignments = self._assignments_for_asset(asset["id"])
        return 58 if assignments else 50

    def novelty_score(self, asset: dict[str, Any]) -> int:
        warnings = (asset.get("export_readiness") or {}).get("warnings") or []
        penalty = sum(
            10 for warning in warnings if "reuse" in warning or "queued" in warning
        )
        return max(0, 100 - penalty)

    def dashboard_rendered_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        source = self.conn.execute(
            """
            SELECT s.id, s.content_hash, s.filename, s.account_ids_json, m.slug AS model_slug
                 , s.source_prompt
            FROM source_assets s
            JOIN models m ON m.id = s.model_id
            WHERE s.id = ?
            """,
            (asset["source_asset_id"],),
        ).fetchone()
        latest_audit = self.conn.execute(
            "SELECT * FROM audit_reports WHERE rendered_asset_id = ? ORDER BY created_at DESC LIMIT 1",
            (asset["id"],),
        ).fetchone()
        enriched = dict(asset)
        source_dict = dict(source) if source else None
        enriched["source"] = source_dict
        enriched["captionGeneration"] = json_load(
            asset.get("caption_generation_json"), {}
        )
        caption_context = load_context_json(asset.get("caption_outcome_context_json"))
        enriched["captionOutcomeContext"] = caption_context
        enriched["captionHash"] = asset.get("caption_hash") or caption_context.get(
            "caption_hash"
        )
        enriched["referencePattern"] = self._active_reference_pattern_for_campaign(
            asset["campaign_id"]
        )
        enriched["audioRecommendations"] = self._audio_recommendations_for_asset(
            caption_generation=enriched.get("captionGeneration") or {},
            reference_pattern=enriched.get("referencePattern") or {},
            recipe=asset.get("recipe"),
            account_tags=json_load(source_dict["account_ids_json"], [])
            if source_dict
            else [],
        )
        if source_dict:
            enriched["account_ids"] = json_load(source_dict["account_ids_json"], [])
            enriched["model_slug"] = source_dict["model_slug"]
            enriched["sourcePrompt"] = (
                json_load(source_dict["source_prompt"], {})
                if source_dict.get("source_prompt")
                else {}
            )
            enriched["generatedAssetLineage"] = self._generated_asset_lineage(
                enriched["sourcePrompt"], enriched.get("referencePattern") or {}
            )
        audit_payload = (
            self._audit_report_payload(dict(latest_audit)) if latest_audit else None
        )
        enriched["latest_audit"] = audit_payload
        performance = self._performance_for_asset(asset)
        enriched["latestPerformance"] = performance["latestPerformance"]
        enriched["sourcePerformance"] = performance["sourcePerformance"]
        enriched["captionPerformance"] = performance["captionPerformance"]
        enriched["recipePerformance"] = performance["recipePerformance"]
        enriched["performanceScore"] = performance["performanceScore"]
        enriched["export_readiness"] = self._local_export_readiness(
            asset, audit_payload
        )
        if enriched["performanceScore"] is not None:
            base_score = enriched["export_readiness"].get("operatorScore", 0)
            adjustment = int(round((enriched["performanceScore"] - 50) * 0.3))
            enriched["export_readiness"]["operatorScore"] = max(
                0, min(100, base_score + adjustment)
            )
        return enriched

    def generated_asset_lineage(
        self,
        source_prompt: dict[str, Any],
        reference_pattern: dict[str, Any] | None,
    ) -> dict[str, Any]:
        reference_pattern = (
            reference_pattern if isinstance(reference_pattern, dict) else {}
        )
        existing = (
            source_prompt.get("generatedAssetLineage")
            if isinstance(source_prompt.get("generatedAssetLineage"), dict)
            else {}
        )
        if existing.get("schema") in {
            "reel_factory.generated_asset_lineage.v1",
            "reel_factory.generated_asset_lineage.v2",
        }:
            lineage = dict(existing)
        else:
            lineage = {
                "schema": "reel_factory.generated_asset_lineage.v1",
                "source": {},
                "generation": {},
                "review": {"humanReviewRequired": True, "status": "draft"},
                "quality": {},
            }
        source = lineage.setdefault("source", {})
        if isinstance(source, dict):
            source.setdefault(
                "formatType",
                source_prompt.get("formatType")
                or reference_pattern.get("visualFormat"),
            )
            source.setdefault(
                "referencePattern",
                source_prompt.get("referencePattern")
                or reference_pattern.get("clusterKey")
                or reference_pattern.get("id"),
            )
            source.setdefault(
                "patternCardId",
                source_prompt.get("patternCardId")
                or reference_pattern.get("patternCardId"),
            )
            source.setdefault("promptId", source_prompt.get("promptId"))
            source.setdefault(
                "referenceId",
                source_prompt.get("referenceId")
                or reference_pattern.get("referenceId"),
            )
        generation = lineage.setdefault("generation", {})
        if isinstance(generation, dict):
            generation.setdefault(
                "tool", source_prompt.get("generationTool") or "manual_finished_video"
            )
            generation.setdefault("modelProfile", source_prompt.get("modelProfile"))
        review = lineage.setdefault("review", {})
        if isinstance(review, dict):
            review.setdefault("humanReviewRequired", True)
            review.setdefault("status", "draft")
        if not lineage.get("pipelineTraceId"):
            source_prompt_id = source_prompt.get("promptId")
            if not source_prompt_id and isinstance(source, dict):
                source_prompt_id = source.get("promptId")
            generation_tool = source_prompt.get("generationTool")
            if not generation_tool and isinstance(generation, dict):
                generation_tool = generation.get("tool")
            asset_path = (
                generation.get("assetPath") if isinstance(generation, dict) else None
            )
            trace_seed = {
                "promptId": source_prompt_id,
                "referencePattern": source_prompt.get("referencePattern")
                or reference_pattern.get("clusterKey")
                or reference_pattern.get("id"),
                "generationTool": generation_tool,
                "assetPath": asset_path,
            }
            lineage["pipelineTraceId"] = (
                f"trace_generated_asset_{hashlib.sha256(json.dumps(trace_seed, sort_keys=True).encode('utf-8')).hexdigest()[:16]}"
            )
        return lineage

    def audio_recommendations_for_asset(
        self,
        *,
        caption_generation: dict[str, Any],
        reference_pattern: dict[str, Any] | None,
        recipe: str | None,
        account_tags: list[str],
    ) -> dict[str, Any]:
        existing = (
            (caption_generation or {}).get("audioRecommendations")
            or (reference_pattern or {}).get("audioRecommendations")
            or {}
        )
        content_tags = [
            (reference_pattern or {}).get("visualFormat"),
            (reference_pattern or {}).get("hookType"),
            (reference_pattern or {}).get("captionArchetype"),
            recipe,
        ]
        catalog = self._recommend_audio(
            platform="instagram",
            content_tags=[str(tag) for tag in content_tags if tag],
            account_tags=[str(tag) for tag in account_tags if tag],
            limit=5,
        )
        catalog_recs = catalog.get("recommendations") or []
        if not catalog_recs:
            return existing
        existing_recs = (
            existing.get("recommendations") if isinstance(existing, dict) else []
        )
        return {
            "schema": "campaign_factory.audio_recommendations.v1",
            "primaryStrategy": (existing or {}).get("primaryStrategy")
            if isinstance(existing, dict)
            else "native_audio_catalog_match",
            "fallbackInstruction": (existing or {}).get("fallbackInstruction")
            if isinstance(existing, dict)
            else "Attach selected native platform audio before publishing.",
            "nativeAudioPreferred": True,
            "recommendations": catalog_recs
            + (existing_recs if isinstance(existing_recs, list) else []),
            "decision": catalog.get("decision") or {},
            "catalogMatched": True,
        }
