from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .caption_outcome import load_context_json
from .learning_score import (
    account_reward_baselines,
    aggregate_performance,
    performance_planning_score,
    performance_score,
)
from .persistence import json_load, utc_now


class PerformanceSummaryRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        campaign_by_slug: Callable[[str], dict[str, Any]],
        slugify: Callable[[str], str],
    ) -> None:
        self.conn = conn
        self._campaign_by_slug = campaign_by_slug
        self._slugify = slugify

    def performance_summary(self, campaign_slug: str) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        rows = self.conn.execute(
            "SELECT * FROM performance_snapshots WHERE campaign_id = ? AND metrics_eligible = 1 ORDER BY snapshot_at DESC, created_at DESC",
            (campaign["id"],),
        ).fetchall()
        snapshots = [self.performance_snapshot_payload(dict(row)) for row in rows]
        account_baselines = account_reward_baselines(snapshots)
        return {
            "schema": "campaign_factory.performance_summary.v1",
            "campaign": campaign["slug"],
            "snapshotCount": len(snapshots),
            "generatedAt": utc_now(),
            "renderedAssets": self.group_performance(
                snapshots, "renderedAssetId", account_baselines=account_baselines
            ),
            "sourceAssets": self.group_performance(
                snapshots, "sourceAssetId", account_baselines=account_baselines
            ),
            "captionHashes": self.group_performance(
                snapshots, "captionHash", account_baselines=account_baselines
            ),
            "recipes": self.group_performance(
                snapshots, "recipe", account_baselines=account_baselines
            ),
            "accounts": self.group_performance(
                snapshots, "instagramAccountId", account_baselines=account_baselines
            ),
            "surfaces": self.group_performance(
                snapshots, "contentSurface", account_baselines=account_baselines
            ),
            "leaderboards": self.performance_leaderboards(
                snapshots, account_baselines=account_baselines
            ),
            "captionOutcomeReview": self.caption_outcome_manual_review(snapshots),
            "snapshots": snapshots[:100],
        }

    def caption_outcome_report(self, campaign_slug: str) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        summary = self.performance_summary(campaign_slug)
        report = dict(summary["captionOutcomeReview"])
        report["campaign"] = campaign["slug"]
        report["generatedAt"] = summary["generatedAt"]
        return report

    def reference_outcome_report(self, campaign_slug: str) -> dict[str, Any]:
        campaign = self._campaign_by_slug(campaign_slug)
        rows = self.conn.execute(
            "SELECT * FROM performance_snapshots WHERE campaign_id = ? AND metrics_eligible = 1 ORDER BY snapshot_at DESC, created_at DESC",
            (campaign["id"],),
        ).fetchall()
        groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for row_obj in rows:
            row = dict(row_obj)
            raw = json_load(row.get("raw_json"), {})
            campaign_factory = self._raw_campaign_factory(raw)
            lineage_source = self._lineage_source(campaign_factory)
            reference_id = (
                campaign_factory.get("reference_id")
                or campaign_factory.get("referenceId")
                or lineage_source.get("referenceId")
                or lineage_source.get("reference_id")
                or row.get("source_asset_id")
                or row.get("rendered_asset_id")
                or row.get("post_id")
            )
            source_asset_id = (
                campaign_factory.get("source_asset_id")
                or campaign_factory.get("sourceAssetId")
                or row.get("source_asset_id")
                or ""
            )
            caption_hash = (
                campaign_factory.get("caption_hash")
                or campaign_factory.get("captionHash")
                or row.get("caption_hash")
                or ""
            )
            account_id = row.get("account_id") or row.get("instagram_account_id") or ""
            if not reference_id:
                continue
            key = (
                str(reference_id),
                str(source_asset_id),
                str(caption_hash),
                str(account_id),
            )
            group = groups.setdefault(
                key,
                {
                    "referenceId": str(reference_id),
                    "sourceAssetId": str(source_asset_id),
                    "captionHash": str(caption_hash),
                    "accountId": str(account_id),
                    "postIds": set(),
                    "approvedPostIds": set(),
                    "views24h": [],
                    "operatorNotes": [],
                },
            )
            post_id = str(row.get("post_id") or row.get("id") or "")
            if post_id:
                group["postIds"].add(post_id)
            review = campaign_factory.get("operator_review") or campaign_factory.get(
                "operatorReview"
            )
            if isinstance(review, dict):
                decision = str(review.get("decision") or "").strip().lower()
                if decision == "approved" and post_id:
                    group["approvedPostIds"].add(post_id)
                notes = review.get("notes")
                if (
                    isinstance(notes, str)
                    and notes.strip()
                    and notes.strip() not in group["operatorNotes"]
                ):
                    group["operatorNotes"].append(notes.strip())
            if self._is_24h_snapshot(row, raw) and row.get("views") is not None:
                group["views24h"].append(int(row["views"]))
        report_rows = []
        for group in groups.values():
            views = group.pop("views24h")
            post_ids = group.pop("postIds")
            approved_post_ids = group.pop("approvedPostIds")
            report_rows.append(
                {
                    **group,
                    "reelsPosted": len(post_ids),
                    "approvedCount": len(approved_post_ids),
                    "avgViews24h": round(sum(views) / len(views)) if views else 0,
                    "measurementState": "measured" if views else "unmeasured",
                }
            )
        report_rows.sort(
            key=lambda item: (
                -item["approvedCount"],
                -item["avgViews24h"],
                item["referenceId"],
            )
        )
        return {
            "schema": "campaign_factory.reference_outcome_report.v1",
            "campaign": campaign["slug"],
            "generatedAt": utc_now(),
            "rows": report_rows,
        }

    def performance_for_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        caption_hash = hashlib.sha256(
            " ".join((asset.get("caption") or "").strip().lower().split()).encode(
                "utf-8"
            )
        ).hexdigest()
        latest = self.conn.execute(
            "SELECT * FROM performance_snapshots WHERE rendered_asset_id = ? ORDER BY snapshot_at DESC, created_at DESC LIMIT 1",
            (asset["id"],),
        ).fetchone()
        source_rows = self.conn.execute(
            "SELECT * FROM performance_snapshots WHERE source_asset_id = ? ORDER BY snapshot_at DESC, created_at DESC",
            (asset["source_asset_id"],),
        ).fetchall()
        caption_rows = self.conn.execute(
            "SELECT * FROM performance_snapshots WHERE caption_hash = ? ORDER BY snapshot_at DESC, created_at DESC",
            (caption_hash,),
        ).fetchall()
        recipe_rows = (
            self.conn.execute(
                "SELECT * FROM performance_snapshots WHERE recipe = ? ORDER BY snapshot_at DESC, created_at DESC",
                (asset.get("recipe"),),
            ).fetchall()
            if asset.get("recipe")
            else []
        )
        source_snapshots = [
            self.performance_snapshot_payload(dict(row)) for row in source_rows
        ]
        caption_snapshots = [
            self.performance_snapshot_payload(dict(row)) for row in caption_rows
        ]
        recipe_snapshots = [
            self.performance_snapshot_payload(dict(row)) for row in recipe_rows
        ]
        account_baselines = account_reward_baselines(
            source_snapshots + caption_snapshots + recipe_snapshots
        )
        source = self.aggregate_performance(
            source_snapshots, account_baselines=account_baselines
        )
        caption = self.aggregate_performance(
            caption_snapshots, account_baselines=account_baselines
        )
        recipe = self.aggregate_performance(
            recipe_snapshots, account_baselines=account_baselines
        )
        score = self.performance_score(source=source, caption=caption, recipe=recipe)
        return {
            "latestPerformance": self.performance_snapshot_payload(dict(latest))
            if latest
            else None,
            "sourcePerformance": source,
            "captionPerformance": caption,
            "recipePerformance": recipe,
            "performanceScore": score,
        }

    def _raw_campaign_factory(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        metadata = raw.get("metadata")
        if not isinstance(metadata, dict):
            return {}
        campaign_factory = metadata.get("campaign_factory") or metadata.get(
            "campaignFactory"
        )
        return campaign_factory if isinstance(campaign_factory, dict) else {}

    def _lineage_source(self, campaign_factory: dict[str, Any]) -> dict[str, Any]:
        lineage = campaign_factory.get(
            "generated_asset_lineage"
        ) or campaign_factory.get("generatedAssetLineage")
        if not isinstance(lineage, dict):
            return {}
        source = lineage.get("source")
        return source if isinstance(source, dict) else {}

    def _is_24h_snapshot(self, row: dict[str, Any], raw: Any) -> bool:
        history = {}
        if isinstance(raw, dict):
            metadata = raw.get("metadata")
            if isinstance(metadata, dict):
                maybe_history = metadata.get(
                    "threadsdash_metric_history"
                ) or metadata.get("threadsdashMetricHistory")
                if isinstance(maybe_history, dict):
                    history = maybe_history
        hours = history.get("hoursSincePublish") or history.get("hours_since_publish")
        if isinstance(hours, (int, float)):
            return abs(float(hours) - 24.0) <= 1.0
        published_at = row.get("published_at")
        snapshot_at = row.get("snapshot_at")
        if not published_at or not snapshot_at:
            return False
        try:
            published = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
            snapshot = datetime.fromisoformat(str(snapshot_at).replace("Z", "+00:00"))
        except ValueError:
            return False
        hours_since_publish = (snapshot - published).total_seconds() / 3600
        return abs(hours_since_publish - 24.0) <= 1.0

    def performance_snapshot_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        caption_outcome_context = load_context_json(
            row.get("caption_outcome_context_json")
        )
        return {
            "id": row["id"],
            "campaignId": row["campaign_id"],
            "renderedAssetId": row["rendered_asset_id"],
            "sourceAssetId": row["source_asset_id"],
            "contentHash": row["content_hash"],
            "sourceContentHash": row["source_content_hash"],
            "captionHash": row["caption_hash"],
            "captionText": row.get("caption_text"),
            "captionBank": row.get("caption_bank"),
            "creatorMix": row.get("creator_mix"),
            "creatorModel": row.get("creator_model"),
            "frameType": row.get("frame_type"),
            "lengthClass": row.get("length_class"),
            "formatClass": row.get("format_class"),
            "captionFitVersion": row.get("caption_fit_version"),
            "captionOutcomeContext": caption_outcome_context,
            "captionFamilyId": caption_outcome_context.get("caption_family_id")
            or caption_outcome_context.get("captionFamilyId"),
            "captionVersionId": caption_outcome_context.get("caption_version_id")
            or caption_outcome_context.get("captionVersionId"),
            "conceptId": row.get("concept_id"),
            "parentReelId": row.get("parent_reel_id"),
            "variantFamilyId": row.get("variant_family_id"),
            "variantId": row.get("variant_id"),
            "variantIndex": row.get("variant_index"),
            "variantOperations": json_load(row.get("variant_operations_json"), []),
            "audioId": row.get("audio_id"),
            "recipe": row["recipe"],
            "postId": row["post_id"],
            "platform": row["platform"],
            "contentSurface": row.get("content_surface") or "reel",
            "status": row["status"],
            "accountId": row["account_id"],
            "instagramAccountId": row["instagram_account_id"],
            "permalink": row["permalink"],
            "publishedAt": row["published_at"],
            "snapshotAt": row["snapshot_at"],
            "metrics": {
                "views": row["views"],
                "likes": row["likes"],
                "comments": row["comments"],
                "shares": row["shares"],
                "saves": row["saves"],
                "impressions": row["impressions"],
                "reach": row["reach"],
                "watchTimeSeconds": row["watch_time_seconds"],
            },
            "metricContract": self.performance_metric_contract(row),
            "dimensions": self.performance_snapshot_dimensions(row),
        }

    def group_performance(
        self,
        snapshots: list[dict[str, Any]],
        key: str,
        *,
        account_baselines: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for snapshot in snapshots:
            value = snapshot.get(key)
            if value:
                groups.setdefault(str(value), []).append(snapshot)
        return {
            key: self.aggregate_performance(group, account_baselines=account_baselines)
            for key, group in groups.items()
        }

    def aggregate_performance(
        self,
        snapshots: list[dict[str, Any]],
        *,
        account_baselines: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        return aggregate_performance(snapshots, account_baselines=account_baselines)

    def performance_metric_contract(self, row: dict[str, Any]) -> dict[str, Any]:
        raw = json_load(row.get("raw_json"), {})
        contract = raw.get("metric_contract") if isinstance(raw, dict) else {}
        if not isinstance(contract, dict):
            contract = {}
        names = contract.get("metricNames")
        surface = contract.get("surface") or row.get("content_surface") or "reel"
        return {
            "version": contract.get("version") or "instagram_metrics_contract_v1",
            "surface": surface,
            "fallbackUsed": bool(
                contract.get("fallbackUsed") or contract.get("fallback_used")
            ),
            "metricNames": names
            if isinstance(names, list)
            else self.default_performance_metric_names(str(surface)),
        }

    def default_performance_metric_names(self, surface: str) -> list[str]:
        if surface == "story":
            return [
                "views",
                "reach",
                "replies",
                "navigation",
                "follows",
                "shares",
                "total_interactions",
            ]
        if surface == "reel":
            return [
                "views",
                "reach",
                "likes",
                "comments",
                "shares",
                "saved",
                "ig_reels_avg_watch_time",
                "reels_skip_rate",
                "ig_reels_video_view_total_time",
            ]
        return ["views", "reach", "likes", "comments", "shares", "saved"]

    def performance_leaderboards(
        self,
        snapshots: list[dict[str, Any]],
        *,
        account_baselines: dict[str, float] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        boards: dict[str, dict[str, dict[str, Any]]] = {
            "hooks": {},
            "recipes": {},
            "audioRecommendations": {},
            "referenceFormats": {},
            "promptPatterns": {},
            "patternCards": {},
            "modelAccounts": {},
            "captionFormulas": {},
            "variationPresets": {},
            "hookRecipeCombos": {},
            "hookAudioCombos": {},
            "formatRecipeCombos": {},
            "formatAudioCombos": {},
            "recipeAudioCombos": {},
            "hookRecipeAudioCombos": {},
        }
        for snapshot in snapshots:
            dimensions = snapshot.get("dimensions") or {}
            hook = (
                dimensions.get("hook")
                if isinstance(dimensions.get("hook"), dict)
                else None
            )
            recipe = dimensions.get("recipe") or snapshot.get("recipe")
            audio = (
                dimensions.get("audio")
                if isinstance(dimensions.get("audio"), dict)
                else None
            )
            reference_format = (
                dimensions.get("referenceFormat")
                if isinstance(dimensions.get("referenceFormat"), dict)
                else None
            )
            prompt_pattern = (
                dimensions.get("promptPattern")
                if isinstance(dimensions.get("promptPattern"), dict)
                else None
            )
            pattern_card = (
                dimensions.get("patternCard")
                if isinstance(dimensions.get("patternCard"), dict)
                else None
            )
            model_account = (
                dimensions.get("modelAccount")
                if isinstance(dimensions.get("modelAccount"), dict)
                else None
            )
            caption_formula = (
                dimensions.get("captionFormula")
                if isinstance(dimensions.get("captionFormula"), dict)
                else None
            )
            variation_preset = (
                dimensions.get("variationPreset")
                if isinstance(dimensions.get("variationPreset"), dict)
                else None
            )
            if hook:
                self.add_leaderboard_snapshot(
                    boards["hooks"], hook["key"], snapshot, {"hook": hook}
                )
            if recipe:
                self.add_leaderboard_snapshot(
                    boards["recipes"], str(recipe), snapshot, {"recipe": str(recipe)}
                )
            if audio:
                self.add_leaderboard_snapshot(
                    boards["audioRecommendations"],
                    audio["key"],
                    snapshot,
                    {"audio": audio},
                )
            if reference_format:
                self.add_leaderboard_snapshot(
                    boards["referenceFormats"],
                    reference_format["key"],
                    snapshot,
                    {"referenceFormat": reference_format},
                )
            if prompt_pattern:
                self.add_leaderboard_snapshot(
                    boards["promptPatterns"],
                    prompt_pattern["key"],
                    snapshot,
                    {"promptPattern": prompt_pattern},
                )
            if pattern_card:
                self.add_leaderboard_snapshot(
                    boards["patternCards"],
                    pattern_card["key"],
                    snapshot,
                    {"patternCard": pattern_card},
                )
            if model_account:
                self.add_leaderboard_snapshot(
                    boards["modelAccounts"],
                    model_account["key"],
                    snapshot,
                    {"modelAccount": model_account},
                )
            if caption_formula:
                self.add_leaderboard_snapshot(
                    boards["captionFormulas"],
                    caption_formula["key"],
                    snapshot,
                    {"captionFormula": caption_formula},
                )
            if variation_preset:
                self.add_leaderboard_snapshot(
                    boards["variationPresets"],
                    variation_preset["key"],
                    snapshot,
                    {"variationPreset": variation_preset},
                )
            if hook and recipe:
                self.add_leaderboard_snapshot(
                    boards["hookRecipeCombos"],
                    f"{hook['key']}|{recipe}",
                    snapshot,
                    {"hook": hook, "recipe": str(recipe)},
                )
            if hook and audio:
                self.add_leaderboard_snapshot(
                    boards["hookAudioCombos"],
                    f"{hook['key']}|{audio['key']}",
                    snapshot,
                    {"hook": hook, "audio": audio},
                )
            if reference_format and recipe:
                self.add_leaderboard_snapshot(
                    boards["formatRecipeCombos"],
                    f"{reference_format['key']}|{recipe}",
                    snapshot,
                    {"referenceFormat": reference_format, "recipe": str(recipe)},
                )
            if reference_format and audio:
                self.add_leaderboard_snapshot(
                    boards["formatAudioCombos"],
                    f"{reference_format['key']}|{audio['key']}",
                    snapshot,
                    {"referenceFormat": reference_format, "audio": audio},
                )
            if recipe and audio:
                self.add_leaderboard_snapshot(
                    boards["recipeAudioCombos"],
                    f"{recipe}|{audio['key']}",
                    snapshot,
                    {"recipe": str(recipe), "audio": audio},
                )
            if hook and recipe and audio:
                self.add_leaderboard_snapshot(
                    boards["hookRecipeAudioCombos"],
                    f"{hook['key']}|{recipe}|{audio['key']}",
                    snapshot,
                    {"hook": hook, "recipe": str(recipe), "audio": audio},
                )
        return {
            name: self.rank_leaderboard_entries(
                items, account_baselines=account_baselines
            )
            for name, items in boards.items()
        }

    def caption_outcome_manual_review(
        self, snapshots: list[dict[str, Any]]
    ) -> dict[str, Any]:
        with_context = [
            self.caption_outcome_snapshot_with_placement(snapshot)
            for snapshot in snapshots
            if self.has_caption_outcome_context(snapshot)
        ]
        return {
            "schema": "campaign_factory.caption_outcome_manual_review.v1",
            "manualReviewOnly": True,
            "coverage": {
                "snapshots": len(snapshots),
                "snapshotsWithCaptionOutcomeContext": len(with_context),
                "snapshotsMissingCaptionOutcomeContext": max(
                    0, len(snapshots) - len(with_context)
                ),
                "coverageRatio": round(len(with_context) / len(snapshots), 4)
                if snapshots
                else 0.0,
            },
            "byCaptionBank": self.caption_outcome_group(
                with_context, "captionBank", "captionBank"
            ),
            "byCreatorMix": self.caption_outcome_group(
                with_context, "creatorMix", "creatorMix"
            ),
            "byCreatorModel": self.caption_outcome_group(
                with_context, "creatorModel", "creatorModel"
            ),
            "byFrameType": self.caption_outcome_group(
                with_context, "frameType", "frameType"
            ),
            "byLengthClass": self.caption_outcome_group(
                with_context, "lengthClass", "lengthClass"
            ),
            "byFormatClass": self.caption_outcome_group(
                with_context, "formatClass", "formatClass"
            ),
            "byCaptionFitVersion": self.caption_outcome_group(
                with_context, "captionFitVersion", "captionFitVersion"
            ),
            "byCaptionHash": self.caption_outcome_group(
                with_context, "captionHash", "captionHash"
            ),
            "byCaptionPlacementLane": self.caption_outcome_group(
                with_context, "captionPlacementLane", "captionPlacementLane"
            ),
            "byCaptionPlacementStatus": self.caption_outcome_group(
                with_context, "captionPlacementStatus", "captionPlacementStatus"
            ),
        }

    def has_caption_outcome_context(self, snapshot: dict[str, Any]) -> bool:
        context = (
            snapshot.get("captionOutcomeContext")
            if isinstance(snapshot.get("captionOutcomeContext"), dict)
            else {}
        )
        return bool(context) or any(
            snapshot.get(key)
            for key in (
                "captionBank",
                "creatorMix",
                "frameType",
                "lengthClass",
                "formatClass",
                "captionFitVersion",
            )
        )

    def caption_outcome_snapshot_with_placement(
        self, snapshot: dict[str, Any]
    ) -> dict[str, Any]:
        context = (
            snapshot.get("captionOutcomeContext")
            if isinstance(snapshot.get("captionOutcomeContext"), dict)
            else {}
        )
        decision = (
            context.get("captionPlacementDecision") if isinstance(context, dict) else {}
        )
        if not isinstance(decision, dict):
            decision = {}
        enriched = dict(snapshot)
        enriched["captionPlacementLane"] = (
            decision.get("selectedLane")
            or decision.get("lane")
            or context.get("captionPlacementLane")
        )
        enriched["captionPlacementStatus"] = decision.get("status") or context.get(
            "captionPlacementStatus"
        )
        return enriched

    def caption_outcome_group(
        self, snapshots: list[dict[str, Any]], source_key: str, output_key: str
    ) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for snapshot in snapshots:
            value = snapshot.get(source_key)
            if value:
                groups.setdefault(str(value), []).append(snapshot)
        rows = []
        for value, group in groups.items():
            performance = self.aggregate_performance(group)
            contexts = self.caption_outcome_contexts_for_group(group)
            context_fields: dict[str, Any] = {"captionOutcomeContexts": contexts}
            if len(contexts) == 1:
                context_fields["captionOutcomeContext"] = contexts[0]
            rows.append(
                {
                    output_key: value,
                    "performance": performance,
                    "score": self.performance_quality_score(performance),
                    "renderedAssetIds": sorted(
                        {
                            str(snapshot["renderedAssetId"])
                            for snapshot in group
                            if snapshot.get("renderedAssetId")
                        }
                    ),
                    "postIds": sorted(
                        {
                            str(snapshot["postId"])
                            for snapshot in group
                            if snapshot.get("postId")
                        }
                    ),
                    **context_fields,
                }
            )
        return sorted(
            rows,
            key=lambda item: (
                -(item["score"] if item["score"] is not None else -1),
                -int((item.get("performance") or {}).get("count") or 0),
                str(item.get(output_key) or ""),
            ),
        )[:20]

    def caption_outcome_contexts_for_group(
        self, snapshots: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        contexts: list[dict[str, Any]] = []
        for snapshot in snapshots:
            context = snapshot.get("captionOutcomeContext")
            if not isinstance(context, dict) or not context:
                continue
            key = json.dumps(context, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            contexts.append(context)
            if len(contexts) >= 5:
                break
        return contexts

    def add_leaderboard_snapshot(
        self,
        items: dict[str, dict[str, Any]],
        key: str,
        snapshot: dict[str, Any],
        dimensions: dict[str, Any],
    ) -> None:
        item = items.setdefault(key, {"key": key, **dimensions, "snapshots": []})
        item["snapshots"].append(snapshot)

    def rank_leaderboard_entries(
        self,
        items: dict[str, dict[str, Any]],
        *,
        limit: int = 20,
        account_baselines: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        entries = []
        for item in items.values():
            snapshots = item["snapshots"]
            summary = self.aggregate_performance(
                snapshots, account_baselines=account_baselines
            )
            entries.append(
                {
                    **{key: value for key, value in item.items() if key != "snapshots"},
                    "performance": summary,
                    "score": self.performance_quality_score(summary),
                    "recommendation": self.performance_recommendation_label(summary),
                    "renderedAssetIds": sorted(
                        {
                            str(snapshot["renderedAssetId"])
                            for snapshot in snapshots
                            if snapshot.get("renderedAssetId")
                        }
                    ),
                    "postIds": sorted(
                        {
                            str(snapshot["postId"])
                            for snapshot in snapshots
                            if snapshot.get("postId")
                        }
                    ),
                }
            )
        return sorted(
            entries,
            key=lambda item: (
                -(item["score"] if item["score"] is not None else -1),
                -int((item.get("performance") or {}).get("count") or 0),
                str(item.get("key") or ""),
            ),
        )[:limit]

    def performance_recommendation_label(self, summary: dict[str, Any]) -> str:
        count = int(summary.get("count") or 0)
        if count < 3:
            return "needs_more_data"
        score = self.performance_quality_score(summary)
        totals = summary.get("totals") or {}
        reach = float(
            totals.get("reach") or totals.get("impressions") or totals.get("views") or 0
        )
        rates = summary.get("rates") or {}
        engagement_rate = float(rates.get("engagementRate") or 0)
        if score is not None and score >= 78:
            return "make_more_like_this"
        if score is not None and score <= 42:
            return "stop_using"
        if reach >= 10000 and engagement_rate < 0.01:
            return "good_views_bad_conversion_signal"
        return "needs_more_data"

    def performance_quality_score(self, summary: dict[str, Any]) -> int | None:
        return performance_score(summary)

    def performance_planning_score(self, summary: dict[str, Any]) -> int | None:
        return performance_planning_score(summary)

    def performance_snapshot_dimensions(self, row: dict[str, Any]) -> dict[str, Any]:
        raw = json_load(row.get("raw_json"), {})
        metadata = raw.get("metadata") if isinstance(raw, dict) else {}
        campaign_meta = (
            metadata.get("campaign_factory") if isinstance(metadata, dict) else {}
        )
        if not isinstance(campaign_meta, dict):
            campaign_meta = {}
        recipe = row.get("recipe") or campaign_meta.get("recipe")
        hook = self.performance_hook_dimension(campaign_meta)
        audio = self.performance_audio_dimension(campaign_meta)
        reference_format = self.performance_reference_format_dimension(campaign_meta)
        prompt_pattern = self.performance_prompt_pattern_dimension(campaign_meta)
        pattern_card = self.performance_pattern_card_dimension(campaign_meta)
        model_account = self.performance_model_account_dimension(campaign_meta, row)
        caption_formula = self.performance_caption_formula_dimension(campaign_meta)
        variation_preset = self.performance_variation_preset_dimension(
            campaign_meta, row
        )
        dimensions: dict[str, Any] = {}
        if recipe:
            dimensions["recipe"] = str(recipe)
        if hook:
            dimensions["hook"] = hook
        if audio:
            dimensions["audio"] = audio
        if reference_format:
            dimensions["referenceFormat"] = reference_format
        if prompt_pattern:
            dimensions["promptPattern"] = prompt_pattern
        if pattern_card:
            dimensions["patternCard"] = pattern_card
        if model_account:
            dimensions["modelAccount"] = model_account
        if caption_formula:
            dimensions["captionFormula"] = caption_formula
        if variation_preset:
            dimensions["variationPreset"] = variation_preset
        return dimensions

    def performance_hook_dimension(
        self, campaign_meta: dict[str, Any]
    ) -> dict[str, Any] | None:
        caption_generation = (
            campaign_meta.get("caption_generation")
            if isinstance(campaign_meta.get("caption_generation"), dict)
            else {}
        )
        reference_pattern = (
            campaign_meta.get("reference_pattern")
            if isinstance(campaign_meta.get("reference_pattern"), dict)
            else {}
        )
        generated_reference = (
            caption_generation.get("referencePattern")
            if isinstance(caption_generation.get("referencePattern"), dict)
            else {}
        )
        hook_key = (
            campaign_meta.get("hook_key")
            or reference_pattern.get("clusterKey")
            or reference_pattern.get("cluster_key")
            or generated_reference.get("clusterKey")
            or generated_reference.get("cluster_key")
            or generated_reference.get("hookType")
            or generated_reference.get("hook_type")
        )
        if not hook_key:
            return None
        return {
            "key": str(hook_key),
            "label": (
                campaign_meta.get("hook_label")
                or reference_pattern.get("label")
                or generated_reference.get("label")
                or generated_reference.get("hookType")
                or generated_reference.get("hook_type")
            ),
            "hookType": reference_pattern.get("hookType")
            or reference_pattern.get("hook_type")
            or generated_reference.get("hookType")
            or generated_reference.get("hook_type"),
            "captionArchetype": reference_pattern.get("captionArchetype")
            or reference_pattern.get("caption_archetype")
            or generated_reference.get("captionArchetype")
            or generated_reference.get("caption_archetype"),
        }

    def performance_audio_dimension(
        self, campaign_meta: dict[str, Any]
    ) -> dict[str, Any] | None:
        intent = (
            campaign_meta.get("audio_intent")
            if isinstance(campaign_meta.get("audio_intent"), dict)
            else {}
        )
        recommendations = (
            intent.get("recommendations")
            if isinstance(intent.get("recommendations"), list)
            else []
        )
        audio_recommendations = (
            campaign_meta.get("audio_recommendations")
            if isinstance(campaign_meta.get("audio_recommendations"), dict)
            else {}
        )
        if not recommendations and isinstance(
            audio_recommendations.get("recommendations"), list
        ):
            recommendations = audio_recommendations["recommendations"]
        selection = (
            intent.get("operator_selection")
            if isinstance(intent.get("operator_selection"), dict)
            else {}
        )
        candidates = [
            selection,
            *(item for item in recommendations if isinstance(item, dict)),
        ]
        for candidate in candidates:
            audio_id = (
                candidate.get("platform_audio_id")
                or candidate.get("platformAudioId")
                or candidate.get("native_audio_id")
                or candidate.get("nativeAudioId")
                or candidate.get("audio_id")
                or candidate.get("audioId")
            )
            title = (
                candidate.get("audio_title")
                or candidate.get("audioTitle")
                or candidate.get("title")
            )
            artist = (
                candidate.get("artist_name")
                or candidate.get("artistName")
                or candidate.get("artist")
            )
            if not audio_id and not title:
                continue
            key = str(
                audio_id or "|".join(str(part) for part in [title, artist] if part)
            )
            return {
                "key": key,
                "audioTitle": title,
                "artistName": artist,
                "platformAudioId": audio_id,
                "platformUrl": candidate.get("platform_url")
                or candidate.get("platformUrl")
                or candidate.get("native_audio_url")
                or candidate.get("nativeAudioUrl"),
                "status": intent.get("status"),
                "source": candidate.get("source")
                or audio_recommendations.get("source")
                or "campaign_factory",
            }
        return None

    def performance_reference_format_dimension(
        self, campaign_meta: dict[str, Any]
    ) -> dict[str, Any] | None:
        caption_generation = (
            campaign_meta.get("caption_generation")
            if isinstance(campaign_meta.get("caption_generation"), dict)
            else {}
        )
        reference_pattern = (
            campaign_meta.get("reference_pattern")
            if isinstance(campaign_meta.get("reference_pattern"), dict)
            else {}
        )
        generated_reference = (
            caption_generation.get("referencePattern")
            if isinstance(caption_generation.get("referencePattern"), dict)
            else {}
        )
        finished_intake = (
            campaign_meta.get("finished_video_intake")
            if isinstance(campaign_meta.get("finished_video_intake"), dict)
            else {}
        )
        source_prompt = (
            campaign_meta.get("source_prompt")
            if isinstance(campaign_meta.get("source_prompt"), dict)
            else {}
        )
        candidates = [
            campaign_meta.get("reference_format"),
            campaign_meta.get("format_type"),
            finished_intake.get("formatType"),
            finished_intake.get("format_type"),
            source_prompt.get("formatType"),
            source_prompt.get("format_type"),
            reference_pattern.get("visualFormat"),
            reference_pattern.get("visual_format"),
            generated_reference.get("visualFormat"),
            generated_reference.get("visual_format"),
        ]
        value = next(
            (str(item).strip() for item in candidates if str(item or "").strip()), ""
        )
        if not value:
            return None
        key = self._slugify(value)
        return {
            "key": key,
            "label": value,
            "source": "campaign_factory",
        }

    def performance_prompt_pattern_dimension(
        self, campaign_meta: dict[str, Any]
    ) -> dict[str, Any] | None:
        caption_generation = (
            campaign_meta.get("caption_generation")
            if isinstance(campaign_meta.get("caption_generation"), dict)
            else {}
        )
        reference_pattern = (
            campaign_meta.get("reference_pattern")
            if isinstance(campaign_meta.get("reference_pattern"), dict)
            else {}
        )
        generated_reference = (
            caption_generation.get("referencePattern")
            if isinstance(caption_generation.get("referencePattern"), dict)
            else {}
        )
        source_prompt = (
            campaign_meta.get("source_prompt")
            if isinstance(campaign_meta.get("source_prompt"), dict)
            else {}
        )
        strategy = (
            source_prompt.get("strategy")
            if isinstance(source_prompt.get("strategy"), dict)
            else {}
        )
        key = (
            campaign_meta.get("prompt_pattern")
            or campaign_meta.get("promptPattern")
            or source_prompt.get("referencePattern")
            or source_prompt.get("reference_pattern")
            or reference_pattern.get("clusterKey")
            or reference_pattern.get("cluster_key")
            or generated_reference.get("clusterKey")
            or generated_reference.get("cluster_key")
        )
        if not key:
            return None
        return {
            "key": str(key),
            "label": (
                campaign_meta.get("prompt_pattern_label")
                or reference_pattern.get("label")
                or generated_reference.get("label")
                or str(key)
            ),
            "primaryMetric": strategy.get("primaryMetric")
            or campaign_meta.get("primary_metric")
            or "views_reach",
            "source": "campaign_factory",
        }

    def performance_pattern_card_dimension(
        self, campaign_meta: dict[str, Any]
    ) -> dict[str, Any] | None:
        lineage = (
            campaign_meta.get("generated_asset_lineage")
            if isinstance(campaign_meta.get("generated_asset_lineage"), dict)
            else {}
        )
        source_prompt = (
            campaign_meta.get("source_prompt")
            if isinstance(campaign_meta.get("source_prompt"), dict)
            else {}
        )
        if not lineage and isinstance(source_prompt.get("generatedAssetLineage"), dict):
            lineage = source_prompt["generatedAssetLineage"]
        source = (
            lineage.get("source") if isinstance(lineage.get("source"), dict) else {}
        )
        reference_pattern = (
            campaign_meta.get("reference_pattern")
            if isinstance(campaign_meta.get("reference_pattern"), dict)
            else {}
        )
        key = (
            source.get("patternCardId")
            or source.get("pattern_card_id")
            or reference_pattern.get("patternCardId")
            or reference_pattern.get("id")
        )
        if not key:
            return None
        return {
            "key": str(key),
            "label": source.get("referencePattern")
            or reference_pattern.get("label")
            or str(key),
            "formatType": source.get("formatType")
            or reference_pattern.get("visualFormat"),
            "source": "reference_factory",
        }

    def performance_model_account_dimension(
        self, campaign_meta: dict[str, Any], row: dict[str, Any]
    ) -> dict[str, Any] | None:
        lineage = (
            campaign_meta.get("generated_asset_lineage")
            if isinstance(campaign_meta.get("generated_asset_lineage"), dict)
            else {}
        )
        source_prompt = (
            campaign_meta.get("source_prompt")
            if isinstance(campaign_meta.get("source_prompt"), dict)
            else {}
        )
        if not lineage and isinstance(source_prompt.get("generatedAssetLineage"), dict):
            lineage = source_prompt["generatedAssetLineage"]
        generation = (
            lineage.get("generation")
            if isinstance(lineage.get("generation"), dict)
            else {}
        )
        account = (
            campaign_meta.get("account_profile")
            if isinstance(campaign_meta.get("account_profile"), dict)
            else {}
        )
        model = (
            generation.get("modelProfile")
            or campaign_meta.get("model_slug")
            or campaign_meta.get("model_id")
        )
        account_id = (
            row.get("instagram_account_id")
            or row.get("account_id")
            or account.get("handle")
            or account.get("slug")
        )
        if not model and not account_id:
            return None
        key = "|".join(
            str(part)
            for part in (model or "unknown_model", account_id or "unknown_account")
        )
        return {
            "key": key,
            "modelProfile": model,
            "account": account_id,
            "source": "threadsdash_performance",
        }

    def performance_caption_formula_dimension(
        self, campaign_meta: dict[str, Any]
    ) -> dict[str, Any] | None:
        caption_generation = (
            campaign_meta.get("caption_generation")
            if isinstance(campaign_meta.get("caption_generation"), dict)
            else {}
        )
        reference_pattern = (
            campaign_meta.get("reference_pattern")
            if isinstance(campaign_meta.get("reference_pattern"), dict)
            else {}
        )
        generated_reference = (
            caption_generation.get("referencePattern")
            if isinstance(caption_generation.get("referencePattern"), dict)
            else {}
        )
        formula = (
            caption_generation.get("captionFormula")
            or caption_generation.get("caption_formula")
            or reference_pattern.get("captionArchetype")
            or reference_pattern.get("caption_archetype")
            or generated_reference.get("captionArchetype")
            or generated_reference.get("caption_archetype")
            or generated_reference.get("hookType")
        )
        if not formula:
            return None
        return {
            "key": self._slugify(str(formula)),
            "label": str(formula),
            "source": "campaign_factory",
        }

    def performance_variation_preset_dimension(
        self, campaign_meta: dict[str, Any], row: dict[str, Any]
    ) -> dict[str, Any] | None:
        assignment = (
            campaign_meta.get("variant_assignment")
            if isinstance(campaign_meta.get("variant_assignment"), dict)
            else {}
        )
        candidate_values = [
            campaign_meta.get("variationPreset"),
            campaign_meta.get("variation_preset"),
            campaign_meta.get("variantPreset"),
            campaign_meta.get("variant_preset"),
            assignment.get("presetName"),
            assignment.get("preset_name"),
        ]
        operations = json_load(row.get("variant_operations_json"), [])
        if isinstance(operations, list):
            for operation in operations:
                if not isinstance(operation, dict):
                    continue
                candidate_values.extend(
                    [
                        operation.get("presetName"),
                        operation.get("preset_name"),
                        operation.get("preset"),
                    ]
                )
                result = (
                    operation.get("result")
                    if isinstance(operation.get("result"), dict)
                    else {}
                )
                candidate_values.extend(
                    [
                        result.get("presetName"),
                        result.get("preset_name"),
                        result.get("preset"),
                    ]
                )
        preset = next(
            (
                str(value).strip()
                for value in candidate_values
                if str(value or "").strip()
            ),
            "",
        )
        if not preset:
            return None
        return {"key": preset, "label": preset, "source": "variant_assignment"}

    def performance_score(
        self, *, source: dict[str, Any], caption: dict[str, Any], recipe: dict[str, Any]
    ) -> int | None:
        weights = [(source, 0.45), (caption, 0.35), (recipe, 0.20)]
        available = [
            (summary, weight) for summary, weight in weights if summary.get("count")
        ]
        if not available:
            return None
        weighted = 0.0
        total_weight = 0.0
        for summary, weight in available:
            component = self.performance_quality_score(summary) or 50
            weighted += component * weight
            total_weight += weight
        return int(round(weighted / total_weight)) if total_weight else None
