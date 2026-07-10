from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .caption_outcome import build_caption_outcome_context, load_context_json
from .lineage_v2 import build_lineage_v2_core
from .persistence import json_load, utc_now


def batch_summary(self, campaign_slug: str) -> dict[str, Any]:
    dashboard = self.dashboard(campaign_slug)
    rendered = dashboard.get("rendered") or []
    counts = {
        "sourcesImported": len(dashboard.get("sources") or []),
        "variantsGenerated": len(rendered),
        "auditedAssets": sum(1 for asset in rendered if asset.get("latest_audit")),
        "ready": sum(
            1
            for asset in rendered
            if (asset.get("export_readiness") or {}).get("state") == "ready"
        ),
        "review": sum(
            1
            for asset in rendered
            if (asset.get("export_readiness") or {}).get("state") == "warning"
            or asset.get("review_state") == "review_ready"
        ),
        "fix": sum(
            1
            for asset in rendered
            if (asset.get("export_readiness") or {}).get("state") == "blocked"
        ),
        "failed": sum(1 for asset in rendered if asset.get("audit_status") == "failed"),
        "approved": sum(
            1 for asset in rendered if asset.get("review_state") == "approved"
        ),
        "rejected": sum(
            1 for asset in rendered if asset.get("review_state") == "rejected"
        ),
    }
    audio_workflow = dashboard.get("audioWorkflow") or self.audio_workflow_summary(
        rendered
    )
    counts["needsAudio"] = audio_workflow["counts"]["needs_audio"]
    counts["audioReady"] = audio_workflow["counts"]["ready"]
    counts["audioBlocked"] = audio_workflow["counts"]["blocked"]
    daily_production = self.daily_production_counters(
        campaign_slug, dashboard=dashboard
    )
    creative_plan = dashboard.get("creativePlan") or self.creative_plan_for_campaign(
        campaign_slug, dashboard=dashboard
    )
    return {
        "schema": "campaign_factory.batch_summary.v1",
        "campaign": campaign_slug,
        "generatedAt": utc_now(),
        "counts": counts,
        "health": dashboard.get("health"),
        "audioWorkflow": audio_workflow,
        "dailyProduction": daily_production,
        "creativePlan": creative_plan,
        "topRecommended": (dashboard.get("ranking") or [])[:10],
        "variantPacks": self._variant_pack_groups(rendered),
    }


def daily_production_counters(
    self, campaign_slug: str, *, dashboard: dict[str, Any] | None = None
) -> dict[str, Any]:
    dashboard = dashboard or self.dashboard(campaign_slug)
    sources = dashboard.get("sources") or []
    rendered = dashboard.get("rendered") or []
    prompt_ready = 0
    generated = 0
    for source in sources:
        prompt = source.get("source_prompt") or source.get("sourcePrompt")
        payload = (
            json_load(prompt, {})
            if isinstance(prompt, str)
            else (prompt if isinstance(prompt, dict) else {})
        )
        if payload.get("schema") == "campaign_factory.finished_video_intake.v1":
            prompt_ready += 1
            generated += 1
    reviewed_states = {"approved", "rejected", "review_ready"}
    posted_states = {"exported", "scheduled", "posted", "published"}
    return {
        "schema": "campaign_factory.daily_production_counters.v1",
        "targetBaseVideos": 10,
        "promptReady": prompt_ready,
        "generated": generated,
        "sentToPipeline": len(rendered),
        "reviewed": sum(
            1 for asset in rendered if asset.get("review_state") in reviewed_states
        ),
        "postedOrScheduled": sum(
            1
            for asset in rendered
            if (asset.get("export_state") or asset.get("exportState") or "").lower()
            in posted_states
        ),
        "remainingBaseVideos": max(0, 10 - generated),
        "primaryMetric": "views_reach",
    }


def _variant_pack_groups(self, rendered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for asset in rendered:
        groups.setdefault(asset.get("source_asset_id") or "unknown", []).append(asset)
    packs = []
    for source_id, assets in groups.items():
        ranked = sorted(
            assets,
            key=lambda asset: (
                asset.get("performanceScore")
                or (asset.get("export_readiness") or {}).get("operatorScore")
                or 0
            ),
            reverse=True,
        )
        packs.append(
            {
                "sourceAssetId": source_id,
                "variantCount": len(assets),
                "approvedCount": sum(
                    1 for asset in assets if asset.get("review_state") == "approved"
                ),
                "reviewReadyCount": sum(
                    1 for asset in assets if asset.get("review_state") == "review_ready"
                ),
                "topVariant": {
                    "renderedAssetId": ranked[0]["id"],
                    "filename": ranked[0]["filename"],
                    "recipe": ranked[0].get("recipe"),
                    "score": ranked[0].get("performanceScore")
                    or (ranked[0].get("export_readiness") or {}).get("operatorScore"),
                }
                if ranked
                else None,
            }
        )
    return packs


def export_manifest(self, *, campaign_slug: str) -> dict[str, Any]:
    campaign = self.campaign_by_slug(campaign_slug)
    rows = self.conn.execute(
        """
        SELECT r.*, s.account_ids_json, s.content_hash AS source_content_hash, s.source_prompt, m.slug AS model_slug
        FROM rendered_assets r
        JOIN source_assets s ON s.id = r.source_asset_id
        JOIN models m ON m.id = s.model_id
        WHERE r.campaign_id = ? AND r.review_state = 'approved'
        ORDER BY r.created_at
        """,
        (campaign["id"],),
    ).fetchall()
    assets = []
    campaign_graph_id = self.graph_id_for(
        "campaigns",
        campaign["id"],
        entity_type="campaign",
        payload={"slug": campaign["slug"]},
    )
    for row in rows:
        row = dict(row)
        latest_audit = self.conn.execute(
            "SELECT * FROM audit_reports WHERE rendered_asset_id = ? ORDER BY created_at DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        audit_summary = {}
        if latest_audit and latest_audit["report_path"]:
            try:
                audit_report = json_load(
                    Path(latest_audit["report_path"]).read_text(encoding="utf-8"), {}
                )
                creative = audit_report.get("creativeQuality") or {}
                reference_match = audit_report.get("referenceMatch") or {}
                audit_summary = {
                    "overallVerdict": audit_report.get("overallVerdict"),
                    "readinessSummary": audit_report.get("readinessSummary") or {},
                    "creativeScore": creative.get("score")
                    or creative.get("overallScore"),
                    "variationScore": reference_match.get("variationScore")
                    or reference_match.get("differenceScore"),
                    "referenceMatchLevel": reference_match.get("referenceMatchLevel"),
                    "warningCount": len(audit_report.get("warnings") or []),
                }
            except OSError:
                audit_summary = {}
        caption_generation = json_load(row["caption_generation_json"], {})
        reference_pattern = self.active_reference_pattern_for_campaign(campaign["id"])
        source_prompt = (
            json_load(row["source_prompt"], {}) if row["source_prompt"] else {}
        )
        stored_lineage = (
            caption_generation.get("generatedAssetLineage")
            if isinstance(caption_generation.get("generatedAssetLineage"), dict)
            else None
        )
        generated_lineage = stored_lineage or self._generated_asset_lineage(
            source_prompt, reference_pattern
        )
        caption_outcome_context = load_context_json(
            row.get("caption_outcome_context_json")
        )
        if not caption_outcome_context:
            caption_outcome_context = build_caption_outcome_context(
                caption_text=row["caption"] or "",
                caption_hash=row.get("caption_hash"),
                render_recipe=row["recipe"],
                source_clip=row.get("source_clip"),
                rendered_output=row["output_path"],
                creator_model=row["model_slug"],
                lineage=caption_generation.get("generatedAssetLineage")
                if isinstance(caption_generation.get("generatedAssetLineage"), dict)
                else caption_generation,
            )
        generated_lineage = build_lineage_v2_core(
            generated_lineage,
            campaign_id=campaign["slug"],
            recipe_id=row["recipe"],
            caption_hash=caption_outcome_context.get("caption_hash")
            or row.get("caption_hash"),
            rendered_asset_id=row["id"],
            content_fingerprint=row["content_hash"],
            prompt_id=source_prompt.get("promptId") or source_prompt.get("prompt_id"),
            reference_id=source_prompt.get("referenceId")
            or source_prompt.get("reference_id")
            or (reference_pattern or {}).get("referenceId"),
        )
        creative_plan = None
        creative_plan_id = source_prompt.get("creativePlanId") or source_prompt.get(
            "creative_plan_id"
        )
        if creative_plan_id:
            plan_row = self.conn.execute(
                "SELECT * FROM creative_plans WHERE id = ?", (creative_plan_id,)
            ).fetchone()
            if plan_row:
                creative_plan = self._creative_plan_payload(dict(plan_row))
        audio_recommendations = self._audio_recommendations_for_asset(
            caption_generation=caption_generation,
            reference_pattern=reference_pattern,
            recipe=row["recipe"],
            account_tags=json_load(row["account_ids_json"], []),
        )
        source_graph_id = self.graph_id_for(
            "source_assets", row["source_asset_id"], entity_type="source_asset"
        )
        rendered_graph_id = self.graph_id_for(
            "rendered_assets", row["id"], entity_type="rendered_asset"
        )
        audit_graph_id = (
            self.graph_id_for(
                "audit_reports", latest_audit["id"], entity_type="audit_report"
            )
            if latest_audit
            else None
        )
        if audit_graph_id:
            self.ensure_graph_edge(
                rendered_graph_id,
                audit_graph_id,
                "rendered_asset_to_audit_report",
                evidence={
                    "source": "export_manifest",
                    "auditReportId": latest_audit["id"],
                },
            )
        assets.append(
            {
                "graphId": rendered_graph_id,
                "campaignGraphId": campaign_graph_id,
                "sourceAssetGraphId": source_graph_id,
                "renderedAssetGraphId": rendered_graph_id,
                "auditGraphId": audit_graph_id,
                "sourceAssetId": row["source_asset_id"],
                "renderedAssetId": row["id"],
                "contentHash": row["content_hash"],
                "sourceContentHash": row["source_content_hash"],
                "filePath": row["campaign_path"],
                "caption": row["caption"] or "",
                "captionHash": caption_outcome_context.get("caption_hash")
                or hashlib.sha256(
                    " ".join((row["caption"] or "").strip().lower().split()).encode(
                        "utf-8"
                    )
                ).hexdigest(),
                "captionOutcomeContext": caption_outcome_context,
                "captionGeneration": caption_generation,
                "modelId": row["model_slug"],
                "accountIds": json_load(row["account_ids_json"], []),
                "recipe": row["recipe"],
                "auditStatus": row["audit_status"],
                "auditSummary": audit_summary,
                "referencePattern": reference_pattern,
                "sourcePrompt": source_prompt,
                "generatedAssetLineage": generated_lineage,
                "creativePlan": creative_plan,
                "audioRecommendations": audio_recommendations,
                "contentForgeRunId": latest_audit["contentforge_run_id"]
                if latest_audit
                else None,
                "tags": [f"campaign:{campaign['slug']}", f"recipe:{row['recipe']}"],
            }
        )
    payload = {
        "schema": "campaign_factory.export.v1",
        "campaignId": campaign["slug"],
        "campaignGraphId": campaign_graph_id,
        "platform": campaign["platform"],
        "createdAt": utc_now(),
        "assets": assets,
    }
    return payload
